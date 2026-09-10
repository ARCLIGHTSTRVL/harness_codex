#!/usr/bin/env python3
# bootstrap-hooks v2
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Read saved active plan handoffs for Codex SessionStart, without writing state.

Run: python plan-handoff.py <project-root>
Literal, unique handoff markers are required. Capped reads never claim marker
uniqueness; ambiguous or unreadable files emit a recovery pointer instead.
This proves local payload construction, not live Codex hook dispatch or delivery.
"""
from dataclasses import dataclass
from io import TextIOWrapper
import os
from pathlib import Path
import re
import stat
import sys
from typing import Final


READ_CAP: Final = 65536
PLAN_CAP: Final = 2500
TOTAL_CAP: Final = 4000
FILE_CAP: Final = 128
NOTE_CAP: Final = 12
BEGIN: Final = "<!-- handoff:begin -->"
END: Final = "<!-- handoff:end -->"
STATUS: Final = re.compile(r"status:[ \t]+([^\s#][^\s]*)(?:[ \t]+#.*)?[ \t]*$")


@dataclass(frozen=True, slots=True)
class UnsafePath(OSError):
    path: Path

    def __str__(self) -> str:
        return f"linked, replaced, or nonregular plan path: {self.path}"


def checked_path(path: Path) -> tuple[os.stat_result, ...]:
    absolute = path.absolute()
    states: list[os.stat_result] = []
    for candidate in reversed((absolute, *absolute.parents)):
        info = candidate.lstat()
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                or (candidate != absolute and not stat.S_ISDIR(info.st_mode))
                or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
            raise UnsafePath(candidate)
        states.append(info)
    return tuple(states)


def unchanged_path(path: Path, before: tuple[os.stat_result, ...]) -> None:
    after = checked_path(path)
    if len(before) != len(after) or any(
        not os.path.samestat(old, new) for old, new in zip(before, after)
    ):
        raise UnsafePath(path)


def read_plan(path: Path) -> tuple[str | None, str | None]:
    before = checked_path(path)
    if not stat.S_ISREG(before[-1].st_mode):
        raise UnsafePath(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                or not os.path.samestat(before[-1], opened)):
            raise UnsafePath(path)
        unchanged_path(path, before)
        raw = stream.read(READ_CAP + 1)
        if os.fstat(stream.fileno()).st_nlink != 1:
            raise UnsafePath(path)
        unchanged_path(path, before)
    if len(raw) > READ_CAP:
        return None, "read cap exceeded; active status and unique handoff unverified"
    lines = raw.decode("utf-8-sig").splitlines()
    if not lines or lines[0] != "---":
        return None, "closed frontmatter missing; active status unknown"
    end = next((i for i in range(1, min(len(lines), 80)) if lines[i] == "---"), None)
    if end is None:
        return None, "frontmatter closer missing within 80 lines; active status unknown"
    declarations = [line for line in lines[1:end] if line.startswith("status:")]
    if len(declarations) != 1:
        return None, "exactly one status declaration required"
    matched = STATUS.fullmatch(declarations[0])
    if matched is None or matched.group(1) not in ("active", "paused", "abandoned"):
        return None, "status must be active, paused, or abandoned"
    if matched.group(1) != "active":
        return None, None
    begins = [i for i in range(end + 1, len(lines)) if lines[i].rstrip() == BEGIN]
    ends = [i for i in range(end + 1, len(lines)) if lines[i].rstrip() == END]
    if len(begins) != 1 or len(ends) != 1 or begins[0] >= ends[0]:
        return None, "exactly one ordered handoff marker pair required"
    body = "\n".join(lines[begins[0] + 1:ends[0]]).strip()
    if not body:
        return None, "active handoff is empty"
    return body, None


def render(root: Path) -> str:
    plans = (root / "workflow" / "plans").absolute()
    try:
        before = checked_path(plans)
    except FileNotFoundError:
        return ""
    except OSError as exc:
        return f"[plan-handoff] scan failed ({type(exc).__name__}); inspect workflow/plans/"
    try:
        if not stat.S_ISDIR(before[-1].st_mode):
            raise UnsafePath(plans)
        files: list[Path] = []
        capped = False
        for path in plans.iterdir():
            if path.suffix != ".md":
                continue
            if len(files) == FILE_CAP:
                capped = True
                break
            files.append(path)
        unchanged_path(plans, before)
    except OSError as exc:
        return f"[plan-handoff] scan failed ({type(exc).__name__}); inspect workflow/plans/"
    parts: list[str] = []
    total = 0
    notes = 0
    for path in sorted(files):
        rel = "workflow/plans/" + path.name
        try:
            body, note = read_plan(path)
        except (OSError, UnicodeError) as exc:
            body, note = None, f"unreadable ({type(exc).__name__}); active status unknown"
        if note is not None:
            notes += 1
            if notes <= NOTE_CAP:
                parts.append(f"[plan-handoff] {rel}: {note}; read this file")
        if body is None:
            continue
        budget = max(0, min(PLAN_CAP, TOTAL_CAP - total))
        kept = body[:budget]
        total += len(kept)
        parts.append(f"[plan-handoff] {rel}\n{kept}")
        if len(body) > budget:
            parts.append(f"[plan-handoff] omitted {len(body) - budget} characters; read {rel}")
    if notes > NOTE_CAP:
        parts.append(f"[plan-handoff] {notes - NOTE_CAP} more unreadable or ambiguous files; inspect workflow/plans/")
    if capped:
        parts.append(f"[plan-handoff] file cap {FILE_CAP} reached; scan incomplete; inspect workflow/plans/")
    return "\n".join(parts)


def main() -> int:
    if isinstance(sys.stdout, TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if len(sys.argv) != 2:
        print("usage: python plan-handoff.py <project-root>", file=sys.stderr)
        return 2
    output = render(Path(sys.argv[1]))
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
