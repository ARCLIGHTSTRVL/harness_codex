#!/usr/bin/env python3
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from io import TextIOWrapper
import os
from pathlib import Path
import re
import sys
from typing import Final

from .redaction import Scanner, load_scanner
from .rollouts import Block, KINDS, Row, Session, read_session, same_cwd, stamp

DEFAULT_KINDS: Final = "text,tool_use,tool_result,summary"
MIN_STAMP: Final = datetime.min.replace(tzinfo=timezone.utc)
LOCATOR: Final = re.compile(r"^(.+\.jsonl):([0-9]+)$")


class Options(argparse.Namespace):
    def __init__(self) -> None:
        super().__init__()
        self.pattern: list[str] = []
        self.show: str | None = None
        self.all: bool = False
        self.kinds: str = DEFAULT_KINDS
        self.include_recent: bool = False
        self.case: bool = False
        self.limit: int = 40
        self.max_chars: int = 20000
        self.cwd: str = os.getcwd()
        self.now: str | None = None
        self.sessions_dir: Path = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser() / "sessions"


@dataclass(frozen=True, slots=True)
class Hit:
    session: Session
    row: Row
    block: Block


def search(args: Options, scanner: Scanner) -> tuple[int, str]:
    root = args.sessions_dir.resolve()
    if not root.is_dir():
        return 2, "no transcripts directory at " + scanner.redact(str(root))
    try:
        patterns = [re.compile(p, 0 if args.case else re.IGNORECASE) for p in args.pattern]
    except re.error:
        return 2, "invalid regular expression"
    kinds = set(KINDS) if args.kinds == "all" else set(args.kinds.split(","))
    if kinds - set(KINDS):
        return 2, "unknown block kind(s); choose from " + ",".join(KINDS)
    now = stamp(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        return 2, "--now is not an ISO-8601 stamp"
    sessions = [read_session(p) for p in sorted(root.rglob("*.jsonl")) if p.resolve().is_relative_to(root)]
    by_id = {s.session_id: s for s in sessions}
    groups: dict[str, list[Hit]] = {}
    rows = bad = partial = recent = files = 0
    for session in sessions:
        if not args.all and not same_cwd(session.cwd, args.cwd):
            continue
        files += 1
        rows += len(session.rows)
        bad += session.bad
        partial += session.partial
        responses = {(b.role, b.text) for r in session.rows if r.kind == "response_item"
                     for b in r.blocks if b.kind == "text"}
        for row in session.rows:
            when = stamp(row.stamp)
            if when is not None and not args.include_recent and (now - when).total_seconds() < 120:
                recent += 1
                continue
            for block in row.blocks:
                if row.kind == "event_msg" and (block.role, block.text) in responses:
                    continue
                if block.kind not in kinds or not all(p.search(block.text) for p in patterns):
                    continue
                parent = by_id.get(session.parent)
                group = parent if parent and (args.all or same_cwd(parent.cwd, args.cwd)) else session
                key = group.path.relative_to(root).as_posix()
                groups.setdefault(key, []).append(Hit(session, row, block))
    total = sum(map(len, groups.values()))
    output = [f"== {total} hit(s) in {len(groups)} session(s); scanned {files} file(s), {rows} row(s); " +
              f"skipped {bad} bad line(s), {partial} partial last line(s), {recent} row(s) newer than 120s"]
    if not files:
        output.append("no transcripts for " + scanner.redact(args.cwd))
    ordered = sorted(groups.items(), key=lambda item: max(stamp(h.row.stamp) or MIN_STAMP for h in item[1]), reverse=True)
    for key, hits in ordered:
        hits.sort(key=lambda h: stamp(h.row.stamp) or MIN_STAMP, reverse=True)
        context = hits[0].session
        output.append(f"-- {scanner.redact(key)} ({scanner.redact(context.cwd)}, {scanner.redact(context.branch or 'branch ?')})")
        for hit in hits[:args.limit]:
            locator = hit.session.path.relative_to(root).as_posix()
            label = f"L{hit.row.number}" if locator == key else f"{scanner.redact(locator)}:{hit.row.number}"
            tag = hit.block.role + "/" + hit.block.kind
            if hit.session.parent:
                tag += " agent:" + scanner.redact(hit.session.session_id)
            output.append(f"  {label}  {scanner.redact(hit.row.stamp or '?')}  {tag}  {scanner.snippet(hit.block.text, patterns[0])}")
        if len(hits) > args.limit:
            output.append(f"   ... {len(hits) - args.limit} more hit(s) in this session beyond --limit {args.limit}")
    if ordered:
        first = ordered[0][1][0]
        locator = first.session.path.relative_to(root).as_posix() + f":{first.row.number}"
        output.append("show one: python recall.py --show <session-file>:<L>  (e.g. " + scanner.redact(locator) + ")")
    return 0, "\n".join(output)


def show(args: Options, scanner: Scanner) -> tuple[int, str]:
    match = LOCATOR.fullmatch(args.show or "")
    if match is None:
        return 2, "--show wants <session-file>:<line>, as printed by a search"
    root = args.sessions_dir.resolve()
    path = (root / match.group(1)).resolve()
    if not path.is_relative_to(root):
        return 2, "refusing a locator outside the transcripts directory"
    if not path.is_file():
        return 2, "no such transcript: " + scanner.redact(match.group(1))
    session = read_session(path)
    wanted = int(match.group(2))
    for row in session.rows:
        if row.number != wanted:
            continue
        fields = [scanner.redact(value) for value in (match.group(1), row.stamp, row.kind, session.session_id, session.cwd)]
        output = [f"== {fields[0]}:{wanted}  {fields[1]}  type={fields[2]}  session={fields[3]}  cwd={fields[4]}"]
        budget = args.max_chars
        for block in row.blocks:
            output.append(f"-- {block.role}/{block.kind} ({len(block.text)} chars)")
            safe = scanner.redact(block.text)
            output.append(safe[:budget])
            if len(safe) > budget:
                output.append(f"[truncated: showing {budget} of {len(block.text)} chars; raise --max-chars]")
                break
            budget -= len(safe)
        return 0, "\n".join(output)
    return 2, f"line {wanted} is not a transcript row in " + scanner.redact(match.group(1))


def main() -> int:
    parser = argparse.ArgumentParser(prog="recall.py")
    parser.add_argument("pattern", nargs="*")
    parser.add_argument("--show", metavar="SESSION-FILE:LINE")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--in", dest="kinds", default=DEFAULT_KINDS)
    parser.add_argument("--include-recent", action="store_true")
    parser.add_argument("--case", action="store_true")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--max-chars", type=int, default=20000)
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--now")
    parser.add_argument("--sessions-dir", type=Path, default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser() / "sessions")
    args = parser.parse_args(namespace=Options())
    scanner = load_scanner()
    if scanner is None:
        print("recall: ask-preflight scanner missing beside this skill; refusing to print transcript text", file=sys.stderr)
        return 2
    if args.limit < 1 or args.max_chars < 0:
        parser.error("--limit must be positive and --max-chars must be nonnegative")
    try:
        if args.show:
            code, text = show(args, scanner)
        elif args.pattern:
            code, text = search(args, scanner)
        else:
            parser.print_usage(sys.stderr)
            return 2
    except OSError as exc:
        code, text = 2, "cannot read transcript files: " + type(exc).__name__
    print(text, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    if isinstance(sys.stdout, TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    if isinstance(sys.stderr, TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
