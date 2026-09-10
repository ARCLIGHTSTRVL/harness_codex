from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from .boundary import ContractError, JsonMap, Store, digest


class CompletionSummary(TypedDict):
    verified: int
    pending: int
    unregistered: int
    unverified: int
    mismatch: int
    damaged: int
    attention: bool


def records(store: Store, category: str) -> tuple[dict[str, JsonMap], int]:
    result: dict[str, JsonMap] = {}
    damaged = 0
    directory = store.root / category
    try:
        if not directory.exists():
            return result, 0
        for index, path in enumerate(directory.iterdir()):
            if index >= 1024:
                damaged += 1
                break
            if path.name.startswith(".native-agent-"):
                continue
            try:
                if store.path(f"{category}/{path.name}").stat().st_size > 16_384:
                    raise ContractError("completion_record_too_large")
                data = store.read(f"{category}/{path.name}")
                if data is None:
                    damaged += 1
                else:
                    result[path.stem] = data
            except (ContractError, OSError, UnicodeError):
                damaged += 1
    except OSError:
        damaged += 1
    return result, damaged


def summary(store: Store, project: Path) -> CompletionSummary:
    launches, launch_errors = records(store, "launches")
    agents, agent_errors = records(store, "agents")
    verdicts, verdict_errors = records(store, "verdicts")
    result: CompletionSummary = {"verified": 0, "pending": 0, "unregistered": 0,
                                 "unverified": 0, "mismatch": 0,
                                 "damaged": launch_errors + agent_errors + verdict_errors,
                                 "attention": False}
    root = str(project)
    linked: dict[str, list[str]] = {}
    for key, agent in agents.items():
        if agent.get("project") != root:
            owner = agent.get("project")
            if not isinstance(owner, str) or not Path(owner).is_absolute():
                result["damaged"] += 1
            continue
        sid, child, call = agent.get("session_id"), agent.get("agent_id"), agent.get("tool_use_id")
        if not all(isinstance(value, str) and value for value in (sid, child, call)):
            result["damaged"] += 1
            continue
        session_key = digest([root, sid])
        if key != digest([session_key, child]):
            result["damaged"] += 1
            continue
        launch_key = digest([session_key, call])
        linked.setdefault(launch_key, []).append(key)
        if launch_key not in launches:
            result["damaged"] += 1
    selected: set[str] = set()
    for key, launch in launches.items():
        if launch.get("project") != root:
            owner = launch.get("project")
            if not isinstance(owner, str) or not Path(owner).is_absolute():
                result["damaged"] += 1
            continue
        sid, call = launch.get("session_id"), launch.get("tool_use_id")
        if (not isinstance(sid, str) or not isinstance(call, str)
                or key != digest([digest([root, sid]), call])
                or not isinstance(launch.get("requested"), dict)):
            result["damaged"] += 1
            continue
        children = linked.get(key, [])
        if not children:
            result["unregistered"] += 1
            continue
        if len(children) != 1:
            result["damaged"] += 1
            continue
        child_key = children[0]
        selected.add(child_key)
        verdict = verdicts.get(child_key)
        if verdict is None:
            result["pending"] += 1
            continue
        agent = agents[child_key]
        if verdict.get("session_id") != sid or verdict.get("agent_id") != agent.get("agent_id"):
            result["damaged"] += 1
            continue
        match verdict.get("state"):
            case "VERIFIED_RUNTIME":
                actual, requested = verdict.get("actual"), launch.get("requested")
                if (not isinstance(actual, dict) or not isinstance(requested, dict)
                        or verdict.get("requested") != requested or agent.get("requested") != requested
                        or actual.get("agent_type") != agent.get("agent_type")
                        or any(not isinstance(requested.get(field), str)
                               or actual.get(field) != requested[field]
                               for field in ("model", "reasoning_effort"))):
                    result["damaged"] += 1
                else:
                    result["verified"] += 1
            case "MISMATCH":
                result["mismatch"] += 1
            case "UNVERIFIED":
                result["unverified"] += 1
            case _:
                result["damaged"] += 1
    for key, verdict in verdicts.items():
        if verdict.get("project") == root and key not in selected:
            result["unverified"] += 1
        elif key not in selected:
            owner = verdict.get("project")
            if not isinstance(owner, str) or not Path(owner).is_absolute():
                result["damaged"] += 1
    result["attention"] = any(result[key] for key in ("pending", "unregistered", "unverified", "mismatch", "damaged"))
    return result
