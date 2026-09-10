#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# How to run: python scripts/native-hooks.py install|check --home CODEX_HOME --repo REPO [--python PYTHON]
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

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.native_hook_io import HookRefusal, atomic_write, read_bytes, safe_path, write_backup
from scripts.runtime import validate_python

JsonValue: TypeAlias = "None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]"
JsonObject: TypeAlias = dict[str, JsonValue]
SCRIPT_REPO: Final = Path(__file__).resolve().parents[1]
STATE_NAME: Final = "dev-setup-codex-community-state.json"
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
    python: str
    script: str
    mode: str
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


def _absolute_python(path: Path | str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise HookRefusal("installed Python path must be absolute")
    return Path(os.path.abspath(os.fspath(candidate)))


def _available_python(path: Path | str) -> Path:
    candidate = _absolute_python(path)
    try:
        return _absolute_python(validate_python(candidate, require_yaml=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise HookRefusal(f"installed Python unavailable: {candidate} ({exc})") from exc


def _handlers(home: Path, repo: Path, python_executable: Path | str,
              no_bytecode: bool) -> tuple[Handler, ...]:
    python = str(_absolute_python(python_executable))
    codex_home, source = home.expanduser().resolve(), repo.expanduser().resolve()
    result: list[Handler] = []
    for event, matcher, script, mode in SPECS:
        option = ("--home", str(codex_home)) if script == "native-session.py" else (
            "--state-dir", str(codex_home / "dev-setup-codex/native-agents"))
        arguments = (*(('-B',) if no_bytecode else ()), str(source / "scripts" / script), mode, *option)
        words = [python, *arguments]
        body = "& " + " ".join(_ps_quote(word) for word in words) + "; exit $LASTEXITCODE"
        hook: JsonObject = {"type": "command", "command": shlex.join(words),
                            "commandWindows": body,
                            "async": False, "timeout": 30}
        if event == "SessionStart":
            hook["additionalContextLimit"] = 0
        result.append(Handler(event, matcher, python, script, mode, arguments, hook))
    return tuple(result)


def handlers(home: Path, repo: Path, python_executable: Path | str) -> tuple[Handler, ...]:
    return _handlers(home, repo, python_executable, True)


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


def _hook_words(hook: JsonObject) -> tuple[str, ...] | None:
    command, windows = hook.get("command"), hook.get("commandWindows")
    if not isinstance(command, str) or not isinstance(windows, str):
        return None
    try:
        command_words = tuple(shlex.split(command))
        windows_words = tuple(_windows_words(windows))
    except ValueError:
        return None
    if not command_words or command_words != windows_words or not Path(command_words[0]).is_absolute():
        return None
    return command_words


def identity(hook: JsonObject, expected: tuple[Handler, ...]) -> tuple[str, ...] | None:
    """Own only complete launch argument shapes, never filenames in shell text."""
    words = _hook_words(hook)
    if words is None:
        return None
    for handler in expected:
        if (tuple(words[1:]) == handler.arguments
                and os.path.normcase(os.path.abspath(words[0])) == os.path.normcase(handler.python)):
            return handler.key
    return None


def _complete_contract(config: JsonObject, expected: tuple[Handler, ...]) -> bool:
    hooks = config.get("hooks", {})
    assert isinstance(hooks, dict)
    counts = {handler.key: 0 for handler in expected}
    for groups in hooks.values():
        assert isinstance(groups, list)
        for group in groups:
            assert isinstance(group, dict) and isinstance(group["hooks"], list)
            for hook in group["hooks"]:
                assert isinstance(hook, dict)
                key = identity(hook, expected)
                if key is not None:
                    counts[key] += 1
    return all(count == 1 for count in counts.values())


def _legacy_contract(config: JsonObject, home: Path, repo: Path) -> tuple[Path, tuple[Handler, ...]]:
    hooks = config.get("hooks", {})
    assert isinstance(hooks, dict)
    paths: list[str] = []
    for groups in hooks.values():
        assert isinstance(groups, list)
        for group in groups:
            assert isinstance(group, dict) and isinstance(group["hooks"], list)
            for hook in group["hooks"]:
                assert isinstance(hook, dict)
                words = _hook_words(hook)
                if words is not None:
                    paths.append(words[0])
    candidates: list[tuple[Path, tuple[Handler, ...]]] = []
    seen: set[str] = set()
    for value in paths:
        python = _absolute_python(value)
        key = os.path.normcase(str(python))
        if key in seen:
            continue
        seen.add(key)
        for no_bytecode in (False, True):
            expected = _handlers(home, repo, python, no_bytecode)
            if _complete_contract(config, expected):
                candidates.append((python, expected))
    if len(candidates) != 1:
        raise HookRefusal("installed Python unavailable: no single complete owned hook contract")
    return candidates[0]


def legacy_python(config: JsonObject, home: Path, repo: Path) -> Path:
    return _legacy_contract(config, home, repo)[0]


def _state_object(raw: bytes) -> JsonObject:
    data: JsonValue = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique,
                                 parse_constant=_constant)
    if not isinstance(data, dict):
        raise HookRefusal("installation state must be an object")
    return data


def installed_contract(home: Path, repo: Path,
                       state: dict | None = None) -> tuple[Path, tuple[Handler, ...]]:
    if state is None:
        raw = read_bytes(safe_path(home / STATE_NAME))
        state = _state_object(raw) if raw is not None else {}
    if not isinstance(state, dict):
        raise HookRefusal("installation state must be an object")
    if "python_executable" in state:
        value = state["python_executable"]
        if not isinstance(value, str) or not value:
            raise HookRefusal("installed Python unavailable: invalid saved python_executable")
        python = _available_python(value)
        return python, handlers(home, repo, python)
    raw = read_bytes(safe_path(home / "hooks.json"))
    if raw is None:
        raise HookRefusal("installed Python unavailable: hooks.json is missing")
    python, expected = _legacy_contract(parse(raw), home, repo)
    return _available_python(python), expected


def installed_python(home: Path, repo: Path, state: dict | None = None) -> Path:
    return installed_contract(home, repo, state)[0]


def _retarget_config(config: JsonObject, old_handlers: tuple[Handler, ...],
                     new_handlers: tuple[Handler, ...], strict: bool) -> JsonObject:
    replacements = {old.key: new for old, new in zip(old_handlers, new_handlers, strict=True)}
    counts = {old.key: 0 for old in old_handlers}
    hooks = config.get("hooks", {})
    assert isinstance(hooks, dict)
    for groups in hooks.values():
        assert isinstance(groups, list)
        for group in groups:
            assert isinstance(group, dict) and isinstance(group["hooks"], list)
            for hook in group["hooks"]:
                assert isinstance(hook, dict)
                key = identity(hook, old_handlers)
                if key is None:
                    continue
                counts[key] += 1
                replacement = replacements[key]
                hook["command"] = replacement.hook["command"]
                hook["commandWindows"] = replacement.hook["commandWindows"]
    if strict and not all(count == 1 for count in counts.values()):
        raise HookRefusal("owned hook retarget requires exactly one complete handler per specification")
    return config


def retarget(raw: bytes, home: Path, old_repo: Path, new_repo: Path,
             python_executable: Path) -> bytes:
    python = _available_python(python_executable)
    config = parse(raw)
    contracts = tuple(expected for no_bytecode in (False, True)
                      if _complete_contract(config, expected := _handlers(
                          home, old_repo, python, no_bytecode)))
    if len(contracts) != 1:
        raise HookRefusal("owned hook retarget requires one unambiguous complete contract")
    updated = _retarget_config(config, contracts[0], handlers(home, new_repo, python), True)
    return (json.dumps(updated, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


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


def check(home: Path, repo: Path, python_executable: Path | str | None = None) -> HookReport:
    config = safe_path(home / "hooks.json")
    raw = read_bytes(config)
    current = parse(raw)
    try:
        if python_executable is None:
            _, expected = installed_contract(home, repo)
        else:
            python = _available_python(python_executable)
            expected = handlers(home, repo, python)
    except HookRefusal as exc:
        return {"status": "unavailable", "hooks_file": str(config), "issues": [str(exc)],
                "runtime": "installed interpreter unavailable; trust and event delivery unverified"}
    issues = ["global handlers missing or incorrectly wired"] if raw is None or not same_json(
        merge(current, expected), current) else []
    for name in {spec[2] for spec in SPECS}:
        if read_bytes(repo / "scripts" / name) is None:
            issues.append(f"source script missing: {name}")
    return {"status": "drift" if issues else "current", "hooks_file": str(config),
            "issues": issues, "runtime": "trust and event delivery unverified"}


def install(home: Path, repo: Path, python_executable: Path | str | None = None) -> HookReport:
    if python_executable is None:
        raise HookRefusal("install requires an explicit --python interpreter")
    python = _available_python(python_executable)
    config = safe_path(home / "hooks.json")
    original = read_bytes(config)
    current = parse(original)
    previous = read_bytes(safe_path(home / STATE_NAME))
    state: JsonObject | None = None
    if previous:
        try:
            state = _state_object(previous)
        except (HookRefusal, ValueError, UnicodeError, RecursionError):
            state = None
        if state is not None and state.get("distribution") == "community":
            old_root = state.get("source_repo")
            if not isinstance(old_root, str) or not Path(old_root).is_absolute():
                raise HookRefusal("previous source_repo must be an absolute path")
            if "python_executable" in state:
                value = state["python_executable"]
                if not isinstance(value, str) or not value:
                    raise HookRefusal("installed Python unavailable: invalid saved python_executable")
                old_python = _absolute_python(value)
                old_handlers = handlers(home, Path(old_root), old_python)
            else:
                old_python, old_handlers = _legacy_contract(current, home, Path(old_root))
            new_handlers = handlers(home, repo, python)
            current = _retarget_config(current, old_handlers, new_handlers, False)
    if previous is None or state is None or state == {}:
        try:
            _, old_handlers = _legacy_contract(current, home, repo)
        except HookRefusal:
            pass
        else:
            current = _retarget_config(current, old_handlers, handlers(home, repo, python), False)
    merged = merge(current, handlers(home, repo, python))
    if same_json(parse(original), merged) and original is not None:
        return check(home, repo, python)
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
        print(__doc__, "\nusage: native-hooks.py install|check [--home PATH] [--repo PATH] [--python PATH]")
        return 0
    try:
        if not args or args[0] not in ("install", "check") or len(args) % 2 != 1:
            raise HookRefusal("usage: native-hooks.py install|check [--home PATH] [--repo PATH] [--python PATH]")
        options = dict(zip(args[1::2], args[2::2], strict=True))
        if len(options) != len(args[1::2]) or options.keys() - {"--home", "--repo", "--python"}:
            raise HookRefusal("unknown or repeated option")
        home = Path(options.get("--home", os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
        repo = Path(options.get("--repo", str(SCRIPT_REPO)))
        python = Path(options["--python"]) if "--python" in options else None
        report = install(home, repo, python) if args[0] == "install" else check(home, repo, python)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["status"] in {"current", "installed"} else (1 if report["status"] == "drift" else 2)
    except (HookRefusal, OSError, ValueError, UnicodeError, RecursionError) as exc:
        print(f"native-hooks refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
