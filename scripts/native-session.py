#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# How to run: python native-session.py session|compact --home CODEX_HOME < payload.json
"""Adapt public lifecycle payloads into correlated project-context carry."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Final, Literal, TypeAlias, assert_never
from uuid import uuid4

REPO: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from scripts.native_hook_io import HookRefusal, atomic_write, read_bytes, safe_path


INPUT_CAP: Final = 65536
CONTEXT_CAP: Final = 14000
CARRY_AGE: Final = 86400
Source = Literal["startup", "resume", "clear", "compact"]
Json: TypeAlias = None | bool | int | float | str | list["Json"] | dict[str, "Json"]


@dataclass(frozen=True, slots=True)
class Payload:
    cwd: Path
    session_id: str
    source: Source
    trigger: str


@dataclass(frozen=True, slots=True)
class Carry:
    nonce: str
    captured_at: str
    trigger: str
    next_snapshot: str
    plan_handoff: str


@dataclass(frozen=True, slots=True)
class Emission:
    nonce: str
    event: str
    source: str
    at: str
    carry_nonce: str | None
    status: str = "prepared"
    delivery: str = "unverified"
    invocation: str = "unauthenticated-native-payload"
    host_dispatch: str = "unverified"


@dataclass(frozen=True, slots=True)
class SessionState:
    cwd: str
    session_id: str
    carry: Carry | None
    emission: Emission
    schema: int = 1


def unique_pairs(pairs: list[tuple[str, Json]]) -> Json:
    result: dict[str, Json] = {}
    for key, value in pairs:
        if key in result:
            raise HookRefusal(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_payload(mode: str) -> Payload:
    raw = sys.stdin.buffer.read(INPUT_CAP + 1)
    if len(raw) > INPUT_CAP:
        raise HookRefusal("payload exceeds size limit")
    data: Json = json.loads(raw, object_pairs_hook=unique_pairs)
    if not isinstance(data, dict):
        raise HookRefusal("payload must be an object")
    cwd, session = data.get("cwd"), data.get("session_id")
    if not isinstance(cwd, str) or not Path(cwd).is_absolute() or not Path(cwd).is_dir():
        raise HookRefusal("payload requires an existing absolute cwd")
    if not isinstance(session, str) or not session.strip() or len(session) > 200:
        raise HookRefusal("payload requires a bounded session_id")
    expected = "SessionStart" if mode == "session" else "PreCompact"
    if data.get("hook_event_name") != expected:
        raise HookRefusal("hook event does not match adapter command")
    source = data.get("source", "compact" if mode == "compact" else None)
    if source not in ("startup", "resume", "clear", "compact"):
        raise HookRefusal("unsupported or missing SessionStart source")
    trigger = data.get("trigger", "unknown")
    if trigger not in ("auto", "manual", "unknown"):
        raise HookRefusal("unsupported PreCompact trigger")
    root = Path(cwd).resolve()
    try:
        git = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root,
                             capture_output=True, text=True, encoding="utf-8", timeout=5)
        if git.returncode == 0 and Path(git.stdout.strip()).is_dir():
            root = Path(git.stdout.strip()).resolve()
    except (OSError, subprocess.TimeoutExpired):
        root = Path(cwd).resolve()
    return Payload(root, session, source, trigger)


def run_script(command: list[str], payload: Payload, home: Path) -> str:
    env = {**os.environ, "CODEX_HOME": str(home), "PYTHONUTF8": "1"}
    result = subprocess.run([sys.executable, *command], cwd=payload.cwd, env=env,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=12)
    if result.returncode not in (0, 1):
        raise HookRefusal(f"context command failed: {Path(command[0]).name}")
    return result.stdout.strip()


def bounded(text: str, limit: int, pointer: str) -> str:
    if len(text) <= limit:
        return text
    suffix = f"\n[truncated {len(text)}-character source; read {pointer} for complete content]"
    return text[:limit - len(suffix)] + suffix


def capture(payload: Payload, home: Path) -> Carry:
    try:
        next_bytes = read_bytes(payload.cwd / "NEXT.md", 65536)
        next_text = bounded(next_bytes.decode("utf-8-sig"), 4000, "NEXT.md") if next_bytes is not None else ""
    except (HookRefusal, UnicodeError) as exc:
        next_text = f"NEXT snapshot unavailable ({type(exc).__name__}); inspect NEXT.md."
    try:
        _ = safe_path(payload.cwd / "workflow/plans")
        plans = bounded(run_script([str(REPO / "templates/hooks/plan-handoff.py"), str(payload.cwd)],
                                   payload, home), 5000, "workflow/plans/")
    except (HookRefusal, OSError, subprocess.TimeoutExpired) as exc:
        plans = f"Plan snapshot unavailable ({type(exc).__name__}); inspect workflow/plans/."
    return Carry(uuid4().hex, datetime.now(timezone.utc).isoformat(), payload.trigger, next_text, plans)


def load_carry(previous: bytes | None, payload: Payload) -> Carry | None:
    if previous is None:
        return None
    data: Json = json.loads(previous, object_pairs_hook=unique_pairs)
    if not isinstance(data, dict) or type(data.get("schema")) is not int or data.get("schema") != 1:
        raise HookRefusal("unsupported native session state")
    if data.get("cwd") != str(payload.cwd) or data.get("session_id") != payload.session_id:
        raise HookRefusal("native session state correlation mismatch")
    carry = data.get("carry")
    if carry is None:
        return None
    fields = ("nonce", "captured_at", "trigger", "next_snapshot", "plan_handoff")
    if not isinstance(carry, dict):
        raise HookRefusal("malformed native session carry")
    strings = {key: value for key, value in carry.items() if key in fields and isinstance(value, str)}
    if len(strings) != len(fields):
        raise HookRefusal("malformed native session carry")
    if len(strings["next_snapshot"]) > 4000 or len(strings["plan_handoff"]) > 5000:
        raise HookRefusal("native session carry exceeds size limit")
    captured_at = datetime.fromisoformat(strings["captured_at"])
    if captured_at.tzinfo is None:
        raise HookRefusal("native session carry has no timezone")
    age = (datetime.now(timezone.utc) - captured_at).total_seconds()
    if age < 0 or age > CARRY_AGE:
        return None
    return Carry(*(strings[key] for key in fields))


def session_context(payload: Payload, home: Path, carry: Carry | None) -> str:
    parts = [f"[native-session source={payload.source}]"]
    try:
        _ = safe_path(payload.cwd / "NEXT.md")
        parts.append(run_script([str(REPO / "scripts/project-health.py"), "--no-heartbeat"], payload, home))
    except (HookRefusal, OSError, subprocess.TimeoutExpired) as exc:
        parts.append(f"PROJECT HEALTH: UNVERIFIED ({type(exc).__name__}).")
    current = carry or capture(payload, home)
    label = "compact-carry" if carry is not None else "current-project-handoff"
    parts.extend([f"[{label} nonce={current.nonce} captured_at={current.captured_at}]",
                      "Preserve conversational ACTIVE FEATURE STATE: the user's goal, accepted constraints, "
                      "decisions, completed work, unresolved work, and next action. Continue the active feature. "
                      "The following saved project files supplement the conversation; verify their current state.",
                      "[NEXT.md snapshot]\n" + current.next_snapshot, current.plan_handoff])
    return bounded("\n".join(part for part in parts if part), CONTEXT_CAP, "NEXT.md and workflow/plans/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("session", "compact"))
    parser.add_argument("--home", required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = parse_payload(args.mode)
        home = safe_path(args.home.absolute())
        key = sha256(json.dumps([str(payload.cwd), payload.session_id]).encode()).hexdigest()
        path = home / "dev-setup-codex/native-sessions" / (key + ".json")
        previous = read_bytes(path)
        carry = load_carry(previous, payload)
        event = "PreCompact" if args.mode == "compact" else "SessionStart"
        if args.mode == "compact":
            carry = capture(payload, home)
            output = {"systemMessage": f"Saved compact carry {carry.nonce} for this session and project. "
                      "Preserve conversational ACTIVE FEATURE STATE through compaction."}
        else:
            match payload.source:
                case "startup" | "clear" | "resume":
                    carry = None
                case "compact":
                    pass
                case unreachable:
                    assert_never(unreachable)
            output = {"hookSpecificOutput": {"hookEventName": "SessionStart",
                      "additionalContext": session_context(payload, home, carry)}}
        emission = Emission(uuid4().hex, event, payload.source, datetime.now(timezone.utc).isoformat(),
                            carry.nonce if carry is not None else None)
        state = SessionState(str(payload.cwd), payload.session_id, carry, emission)
        prepared = json.dumps(asdict(state), ensure_ascii=False).encode("utf-8")
        atomic_write(path, prepared, previous)
        print(json.dumps(output, ensure_ascii=True), flush=True)
        emitted = replace(state, emission=replace(emission, status="emitted"))
        atomic_write(path, json.dumps(asdict(emitted), ensure_ascii=False).encode("utf-8"), prepared)
        return 0
    except (HookRefusal, OSError, UnicodeError, ValueError, RecursionError, subprocess.TimeoutExpired) as exc:
        print(f"native-session refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
