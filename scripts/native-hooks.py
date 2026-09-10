#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# How to run: python scripts/native-hooks.py install|check --home CODEX_HOME --repo REPO
"""Merge source-owned global hooks; configuration never establishes hook trust."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shlex
import sys
from typing import Final, TypeAlias, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.native_hook_io import HookRefusal, atomic_write, read_bytes, safe_path, write_backup

JsonValue: TypeAlias = "None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]"
JsonObject: TypeAlias = dict[str, JsonValue]
SCRIPT_REPO: Final = Path(__file__).resolve().parents[1]
SPECS: Final = (
    ("SessionStart", "startup|resume|clear|compact", "native-session.py", "session"),
    ("PreCompact", "manual|auto", "native-session.py", "compact"),
    ("SessionStart", "startup|resume|clear|compact", "native-agent-contract.py", "session"),
    ("PreToolUse", "spawn_agent|Agent", "native-agent-contract.py", "pre"),
    ("PostToolUse", "spawn_agent|Agent", "native-agent-contract.py", "post"),
    ("SubagentStop", "", "native-agent-contract.py", "subagent-stop"),
)


@dataclass(frozen=True, slots=True)
class Handler:
    event: str
    matcher: str
    arguments: tuple[str, ...]
    hook: JsonObject

    @property
    def key(self) -> tuple[str, ...]:
        return self.arguments


class HookReport(TypedDict):
    status: str
    hooks_file: str
    issues: list[str]
    runtime: str


def _unique(pairs: list[tuple[str, JsonValue]]) -> JsonObject:
    result: JsonObject = {}
    for key, value in pairs:
        if key in result:
            raise HookRefusal(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise HookRefusal(f"non-finite JSON number: {value}")


def same_json(left: JsonValue, right: JsonValue) -> bool:
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def parse(raw: bytes | None) -> JsonObject:
    data: JsonValue = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique,
                                 parse_constant=_constant) if raw is not None else {}
    if not isinstance(data, dict):
        raise HookRefusal("hooks.json must be an object")
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise HookRefusal("hooks must be an object")
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            raise HookRefusal(f"{event} hook groups must be an array")
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise HookRefusal(f"{event} group must contain a hooks array")
            if not isinstance(group.get("matcher", ""), str):
                raise HookRefusal(f"{event} matcher must be a string")
            entries = group["hooks"]
            assert isinstance(entries, list)
            for hook in entries:
                if not isinstance(hook, dict):
                    raise HookRefusal(f"{event} handler must be an object")
    return data


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def handlers(home: Path, repo: Path) -> tuple[Handler, ...]:
    interpreter = Path(sys.executable)
    python = str(interpreter.absolute() if sys.prefix != sys.base_prefix else interpreter.resolve())
    codex_home, source = home.expanduser().resolve(), repo.expanduser().resolve()
    result: list[Handler] = []
    for event, matcher, script, mode in SPECS:
        option = ("--home", str(codex_home)) if script == "native-session.py" else (
            "--state-dir", str(codex_home / "dev-setup-codex/native-agents"))
        arguments = (str(source / "scripts" / script), mode, *option)
        words = [python, *arguments]
        body = "& " + " ".join(_ps_quote(word) for word in words) + "; exit $LASTEXITCODE"
        hook: JsonObject = {"type": "command", "command": shlex.join(words),
                            "commandWindows": body,
                            "async": False, "timeout": 30}
        if event == "SessionStart":
            hook["additionalContextLimit"] = 0
        result.append(Handler(event, matcher, arguments, hook))
    return tuple(result)


def _windows_words(command: str) -> list[str]:
    if command.startswith("& "):
        body = command
    else:
        powershell = str(Path(os.environ.get("SystemRoot", "C:/Windows")) /
                         "System32/WindowsPowerShell/v1.0/powershell.exe")
        parts = command.rsplit(" -EncodedCommand ", 1)
        if len(parts) != 2 or parts[0] != '"' + powershell + '" -NoLogo -NoProfile -NonInteractive':
            return []
        try:
            body = base64.b64decode(parts[1], validate=True).decode("utf-16-le")
        except (ValueError, UnicodeError):
            return []
    words = [match.group(1).replace("''", "'") for match in re.finditer(r"'((?:[^']|'')*)'", body)]
    expected = "& " + " ".join(_ps_quote(word) for word in words) + "; exit $LASTEXITCODE"
    return words if body == expected else []


def identity(hook: JsonObject, expected: tuple[Handler, ...]) -> tuple[str, ...] | None:
    """Own only complete launch argument shapes, never filenames in shell text."""
    for field in ("command", "commandWindows"):
        command = hook.get(field)
        if not isinstance(command, str):
            continue
        try:
            words = _windows_words(command) if field == "commandWindows" else shlex.split(command)
        except ValueError:
            continue
        if not words or not Path(words[0]).is_absolute():
            continue
        if not re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", Path(words[0]).name, re.I):
            continue
        for handler in expected:
            if tuple(words[1:]) == handler.arguments:
                return handler.key
    return None


def merge(config: JsonObject, expected: tuple[Handler, ...]) -> JsonObject:
    original = parse(json.dumps(config, allow_nan=False).encode())
    hooks = original.get("hooks", {})
    assert isinstance(hooks, dict)
    kept: JsonObject = {}
    extensions: dict[tuple[str, ...], JsonObject] = {}
    for event, groups in hooks.items():
        assert isinstance(groups, list)
        retained: list[JsonValue] = []
        for group in groups:
            assert isinstance(group, dict) and isinstance(group["hooks"], list)
            entries: list[JsonValue] = []
            owned = False
            for hook in group["hooks"]:
                assert isinstance(hook, dict)
                key = identity(hook, expected)
                if key is None:
                    entries.append(hook)
                else:
                    owned = True
                    extra = extensions.setdefault(key, {})
                    for name, value in hook.items():
                        if name in {"type", "command", "commandWindows", "async", "timeout", "additionalContextLimit"}:
                            continue
                        if name in extra and not same_json(extra[name], value):
                            raise HookRefusal(f"conflicting extension on duplicate owned handler: {name}")
                        extra[name] = value
            if not owned or entries or set(group) - {"matcher", "hooks"}:
                retained.append({**group, "hooks": entries})
        kept[event] = retained
    for handler in expected:
        added_group: JsonObject = {"matcher": handler.matcher,
                             "hooks": [{**extensions.get(handler.key, {}), **handler.hook}]}
        groups = kept.setdefault(handler.event, [])
        assert isinstance(groups, list)
        groups.append(added_group)
    return {**original, "hooks": kept}


def check(home: Path, repo: Path) -> HookReport:
    config = safe_path(home / "hooks.json")
    raw = read_bytes(config)
    current = parse(raw)
    issues = ["global handlers missing or incorrectly wired"] if raw is None or not same_json(
        merge(current, handlers(home, repo)), current) else []
    for name in {spec[2] for spec in SPECS}:
        if read_bytes(repo / "scripts" / name) is None:
            issues.append(f"source script missing: {name}")
    return {"status": "drift" if issues else "current", "hooks_file": str(config),
            "issues": issues, "runtime": "trust and event delivery unverified"}


def install(home: Path, repo: Path) -> HookReport:
    config = safe_path(home / "hooks.json")
    original = read_bytes(config)
    current = parse(original)
    previous = read_bytes(safe_path(home / "dev-setup-codex-community-state.json"))
    if previous:
        try:
            state = json.loads(previous)
        except (ValueError, UnicodeError):
            state = {}
        if isinstance(state, dict) and state.get("distribution") == "community":
            old_root = state.get("source_repo")
            if isinstance(old_root, str) and Path(old_root).is_absolute() and Path(old_root).resolve() != repo.resolve():
                old_handlers = handlers(home, Path(old_root))
                replacements = {old.key: new for old, new in zip(old_handlers, handlers(home, repo))}
                for groups in current.get("hooks", {}).values():
                    for group in groups:
                        for hook in group["hooks"]:
                            replacement = replacements.get(identity(hook, old_handlers))
                            if replacement:
                                hook.update(replacement.hook)
    merged = merge(current, handlers(home, repo))
    if same_json(parse(original), merged) and original is not None:
        return check(home, repo)
    for name in {spec[2] for spec in SPECS}:
        if read_bytes(repo / "scripts" / name) is None:
            raise HookRefusal(f"source script missing: {name}")
    encoded = (json.dumps(merged, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    if len(encoded) > 1_000_000:
        raise HookRefusal("merged hooks.json exceeds 1000000 bytes")
    if original is not None:
        _ = write_backup(config, original)
    atomic_write(config, encoded, original)
    return {"status": "installed", "hooks_file": str(config), "issues": [],
            "runtime": "review and trust changed hooks with /hooks; event delivery unverified"}


def main() -> int:
    args = sys.argv[1:]
    if args in (["--help"], ["-h"]):
        print(__doc__, "\nusage: native-hooks.py install|check [--home PATH] [--repo PATH]")
        return 0
    try:
        if not args or args[0] not in ("install", "check") or len(args) % 2 != 1:
            raise HookRefusal("usage: native-hooks.py install|check [--home PATH] [--repo PATH]")
        options = dict(zip(args[1::2], args[2::2], strict=True))
        if len(options) != len(args[1::2]) or options.keys() - {"--home", "--repo"}:
            raise HookRefusal("unknown or repeated option")
        home = Path(options.get("--home", os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
        repo = Path(options.get("--repo", str(SCRIPT_REPO)))
        report = install(home, repo) if args[0] == "install" else check(home, repo)
        print(json.dumps(report, ensure_ascii=False))
        return int(report["status"] == "drift")
    except (HookRefusal, OSError, ValueError, UnicodeError, RecursionError) as exc:
        print(f"native-hooks refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
