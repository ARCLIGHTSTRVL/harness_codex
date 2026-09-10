from __future__ import annotations

import os
from pathlib import Path

from .boundary import ContractError, Event, JsonMap, Store, context, digest, optional_token, parse_map, token


def post(event: Event, store: Store) -> JsonMap:
    if event.data.get("tool_name") not in {"spawn_agent", "Agent"}:
        return {}
    event = store.bind(event)
    launch = store.read(f"launches/{event.call_key}.json")
    response = event.data.get("tool_response")
    if isinstance(response, str):
        response = parse_map(response)
    if not launch or not isinstance(response, dict) or not response.get("agent_id"):
        return context("PostToolUse", "UNVERIFIED", "validated_launch_or_native_agent_id_missing")
    child = token(response.get("agent_id"))
    expected = launch.get("requested")
    if not isinstance(expected, dict) or event.role != launch.get("role_selector", launch.get("agent_type")):
        return {"decision": "block", "reason": "Native agent contract MISMATCH: launch_attribution_changed"}
    for field, value in expected.items():
        if event.arguments.get(field) != value:
            return {"decision": "block", "reason": "Native agent contract MISMATCH: launched_tuple_changed"}
    store.write(f"agents/{digest([event.key, child])}.json", {**launch, "agent_id": child})
    return context("PostToolUse", "PENDING", "native_child_registered_completion_not_yet_verified")


def transcript_identity(event: Event, store: Store) -> JsonMap:
    value = event.data.get("agent_transcript_path")
    if not isinstance(value, str) or not value:
        return {}
    path = Path(value)
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).resolve()
    allowed = (home / "sessions", home / "archived_sessions", store.root.resolve())
    resolved = path.resolve()
    if not path.is_absolute() or path.is_symlink() or not any(resolved.is_relative_to(root) for root in allowed):
        raise ContractError("transcript_path_outside_owned_roots")
    with path.open("rb") as source:
        raw = source.read(16_777_217)
    if len(raw) > 16_777_216:
        raise ContractError("transcript_too_large")
    identity: JsonMap = {}
    child_id = token(event.data.get("agent_id"))
    linked = False
    for line in raw.decode("utf-8-sig").splitlines():
        item = parse_map(line)
        payload = item.get("payload")
        if not isinstance(payload, dict):
            if item.get("type") in {"session_meta", "turn_context"}:
                raise ContractError("native_metadata_malformed")
            continue
        if item.get("type") == "session_meta":
            if payload.get("id") != child_id:
                raise ContractError("transcript_child_id_mismatch")
            linked = True
        if item.get("type") == "turn_context":
            model = optional_token(payload.get("model"))
            effort = optional_token(payload.get("effort"))
            identity = {"model": model, "reasoning_effort": effort}
    return identity if linked else {}


def stopped(event: Event, store: Store) -> JsonMap:
    event = store.bind(event)
    child = token(event.data.get("agent_id"))
    key = digest([event.key, child])
    launch = store.read(f"agents/{key}.json")
    previous = store.read(f"verdicts/{key}.json")
    actual: JsonMap = {"agent_type": token(event.data.get("agent_type")),
                       "model": optional_token(event.data.get("model")), "reasoning_effort": None}
    evidence_code = "native_effort_evidence_missing"
    try:
        transcript = transcript_identity(event, store)
    except (ContractError, OSError, UnicodeError) as exc:
        transcript = {}
        evidence_code = exc.code if isinstance(exc, ContractError) else "transcript_unreadable"
    reported_model = transcript.get("model")
    contradicts_event = bool(reported_model and actual["model"] and reported_model != actual["model"])
    if reported_model:
        actual["model"] = actual["model"] or reported_model
        actual["reasoning_effort"] = transcript.get("reasoning_effort")
    state = "UNVERIFIED"
    expected = launch.get("requested") if launch else None
    if isinstance(expected, dict) and launch:
        observed = {"model": actual["model"], "reasoning_effort": actual["reasoning_effort"]}
        mismatch = actual["agent_type"] != launch.get("agent_type") or contradicts_event
        mismatch = mismatch or any(value is not None and value != expected.get(field) for field, value in observed.items())
        if mismatch:
            state, evidence_code = "MISMATCH", "runtime_identity_differs"
        elif all(value is not None for value in observed.values()):
            state, evidence_code = "VERIFIED_RUNTIME", "native_event_and_child_transcript_match"
    else:
        evidence_code = "validated_launch_missing"
    blocked_once = bool(previous and previous.get("blocked_once"))
    request_retry = state == "MISMATCH" and not blocked_once
    store.write(f"verdicts/{key}.json", {"state": state, "code": evidence_code, "agent_id": child,
                                       "project": str(event.root),
                                       "session_id": event.session_id, "actual": actual,
                                       "requested": expected, "source": "native_subagent_stop",
                                       "blocked_once": blocked_once or request_retry})
    output: JsonMap = {"systemMessage": f"Native agent contract {state}: {evidence_code}"}
    if request_retry:
        output.update({"decision": "block", "reason": "Native agent contract MISMATCH: report the runtime identity mismatch to the parent; do not present this result as verified."})
    return output
