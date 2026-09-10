#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# How to run: python scripts/native-hook-status.py probe|status --home PATH
"""Separate configured-command smoke results from unauthenticated observations."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Final, TypeAlias, TypedDict

REPO: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from scripts.native_hook_io import HookRefusal, read_bytes, safe_path

spec = importlib.util.spec_from_file_location("native_hooks_status_contract", REPO / "scripts/native-hooks.py")
assert spec is not None and spec.loader is not None
contract = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = contract
spec.loader.exec_module(contract)
Json: TypeAlias = None | bool | int | float | str | list["Json"] | dict[str, "Json"]
SOURCES: Final = ("startup", "resume", "clear", "compact")


class ProbeResult(TypedDict):
    event: str
    mode: str
    passed: bool
    exit_code: int


class ProbeReport(TypedDict):
    schema: int
    configuration: str
    execution: str
    probes: list[ProbeResult]
    issues: list[str]
    trust: str
    host_dispatch: str


class Observation(TypedDict):
    state: str
    detail: str


class StatusReport(TypedDict):
    schema: int
    global_session: Observation
    project_sessionstart: Observation
    correlation: str
    trust: str
    host_dispatch: str


def unique_pairs(pairs: list[tuple[str, Json]]) -> dict[str, Json]:
    result: dict[str, Json] = {}
    for key, value in pairs:
        if key in result:
            raise HookRefusal("duplicate evidence key")
        result[key] = value
    return result


def parse(raw: bytes) -> dict[str, Json]:
    data: Json = json.loads(raw, object_pairs_hook=unique_pairs)
    if not isinstance(data, dict):
        raise HookRefusal("evidence must be an object")
    return data


def rejection_matches(result: subprocess.CompletedProcess[bytes], event: str, script: str) -> bool:
    if script == "native-session.py":
        return result.returncode == 1 and result.stdout == b"" and result.stderr.startswith(b"native-session refused:")
    if result.returncode != 0 or result.stderr:
        return False
    output = parse(result.stdout)
    expected: dict[str, dict[str, Json]] = {
        "SubagentStop": {"systemMessage": "Native agent contract UNVERIFIED: invalid_json"},
        "PreToolUse": {"hookSpecificOutput": {"hookEventName": event, "permissionDecision": "deny",
                       "permissionDecisionReason": "Native agent contract: invalid_json"}},
        "SessionStart": {"hookSpecificOutput": {"hookEventName": event,
                         "additionalContext": "Native agent contract UNVERIFIED: invalid_json"}},
        "PostToolUse": {"hookSpecificOutput": {"hookEventName": event,
                        "additionalContext": "Native agent contract UNVERIFIED: invalid_json"}},
    }
    return output == expected.get(event)


def probe(home: Path, repo: Path) -> ProbeReport:
    home, repo = safe_path(home), safe_path(repo)
    checked = contract.check(home, repo)
    rows: list[ProbeResult] = []
    report: ProbeReport = {"schema": 1, "configuration": checked["status"], "execution": "not-run",
                          "probes": rows, "issues": checked["issues"], "trust": "unverified", "host_dispatch": "unverified"}
    if checked["status"] != "current":
        return report
    config = contract.parse(read_bytes(home / "hooks.json"))
    for handler in contract.handlers(home, repo):
        matches = [hook for group in config["hooks"].get(handler.event, [])
                   if group.get("matcher", "") == handler.matcher for hook in group["hooks"]
                   if all(contract.same_json(hook.get(key), value) for key, value in handler.hook.items())]
        if len(matches) != 1:
            report.update(configuration="drift", issues=["exact owned handler mismatch"])
            return report
    for handler in contract.handlers(home, repo):
        command = handler.hook["commandWindows" if os.name == "nt" else "command"]
        invocation = [str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
                      "-NoProfile", "-NonInteractive", "-Command", command] if os.name == "nt" else shlex.split(command)
        result = subprocess.run(invocation, cwd=repo, input=b"{", capture_output=True, timeout=10,
                                env=dict(os.environ, CODEX_HOME=str(home), PYTHONUTF8="1"))
        rows.append({"event": handler.event, "mode": handler.arguments[1], "exit_code": result.returncode,
                     "passed": rejection_matches(result, handler.event, Path(handler.arguments[0]).name)})
    report["execution"] = "passed" if all(row["passed"] for row in rows) else "failed"
    return report


def project_root(cwd: Path) -> Path:
    root = safe_path(cwd).resolve()
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root,
                            capture_output=True, text=True, encoding="utf-8", timeout=5)
    return safe_path(Path(result.stdout.strip())).resolve() if result.returncode == 0 else root


def observation(path: Path, correlation: tuple[str, str], project: bool) -> Observation:
    try:
        raw = read_bytes(path, 32768)
        if raw is None:
            return {"state": "missing", "detail": "no retained observation"}
        data = parse(raw)
        if type(data.get("schema")) is not int or data.get("schema") != 1:
            raise HookRefusal("unsupported evidence schema")
        if (data.get("cwd"), data.get("session_id")) != correlation:
            raise HookRefusal("project or session correlation mismatch")
        if project and data.get("owner") != "project-sessionstart":
            raise HookRefusal("project owner mismatch")
        emitted = data.get("emission")
        if not isinstance(emitted, dict) or emitted.get("event") not in ("SessionStart", "PreCompact") or emitted.get("source") not in SOURCES:
            raise HookRefusal("not a supported SessionStart observation")
        if project and emitted.get("event") != "SessionStart":
            raise HookRefusal("project marker event mismatch")
        if emitted.get("invocation") != "unauthenticated-native-payload" or any(
            emitted.get(key) != "unverified" for key in ("delivery", "host_dispatch")
        ):
            raise HookRefusal("unsupported delivery or authentication claim")
        stamp = emitted.get("at")
        if not isinstance(stamp, str):
            raise HookRefusal("timestamp missing")
        timestamp = datetime.fromisoformat(stamp)
        if timestamp.tzinfo is None:
            raise HookRefusal("timestamp has no timezone")
        age = (datetime.now(timezone.utc) - timestamp).total_seconds()
        if age < -300:
            raise HookRefusal("timestamp is in the future")
        if age > 86400:
            return {"state": "stale", "detail": "observation is over 24 hours old"}
        states: dict[str, Observation] = {
            "prepared": {"state": "prepared", "detail": "output emission was not recorded"},
            "emitted": {"state": "observed-unverified", "detail": "local unauthenticated invocation record"},
        }
        stage = emitted.get("status")
        if not isinstance(stage, str) or stage not in states:
            raise HookRefusal("unknown emission state")
        if emitted.get("event") == "PreCompact":
            return {"state": "other-event", "detail": "latest global observation is PreCompact, not SessionStart"}
        return states[stage]
    except (HookRefusal, OSError, ValueError, UnicodeError, RecursionError):
        return {"state": "malformed", "detail": "record unreadable, inconsistent, or unsupported"}


def status(home: Path, cwd: Path, session_id: str) -> StatusReport:
    root = str(project_root(cwd))
    if not session_id.strip() or len(session_id) > 200:
        raise HookRefusal("bounded session ID required")
    home = safe_path(home)
    key = sha256(json.dumps([root, session_id]).encode()).hexdigest()
    owner_key = sha256(root.encode()).hexdigest()
    correlation = (root, session_id)
    global_session = observation(home / "dev-setup-codex/native-sessions" / (key + ".json"), correlation, False)
    owner = observation(home / "dev-setup-codex/project-hook-marks" / (owner_key + ".json"), correlation, True)
    return {"schema": 1, "global_session": global_session, "project_sessionstart": owner,
            "correlation": "matched-unverified" if global_session["state"] == owner["state"] == "observed-unverified" else "unverified",
            "trust": "unverified", "host_dispatch": "unverified"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("probe", "status"))
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--project", "--cwd", dest="cwd", type=Path, default=Path.cwd())
    parser.add_argument("--session-id")
    args = parser.parse_args()
    try:
        if args.mode == "probe":
            report = probe(args.home, args.repo)
            print(json.dumps(report))
            return int(report["execution"] != "passed")
        if not args.session_id:
            raise HookRefusal("status requires --session-id")
        print(json.dumps(status(args.home, args.cwd, args.session_id)))
        return 0
    except (HookRefusal, OSError, ValueError, UnicodeError, RecursionError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"schema": 1, "configuration": "unverified", "execution": "not-run", "issues": [type(exc).__name__],
                          "probes": [], "trust": "unverified", "host_dispatch": "unverified"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
