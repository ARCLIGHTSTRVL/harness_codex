from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Final

from .boundary import ContractError, Event, JsonMap, Store, context, deny, digest, read_map, token
from .catalog import Model, catalog_fingerprint
from .roles import ROLE_BODIES, instruction

MAX_AGE: Final = 86_400


@dataclass(frozen=True, slots=True)
class Pin:
    agent_type: str
    model: str
    reasoning_effort: str
    allowed_reasoning_efforts: tuple[str, ...]

    def wire(self, effort: str | None = None) -> JsonMap:
        return {"model": self.model,
                "reasoning_effort": self.reasoning_effort if effort is None else effort}


@dataclass(frozen=True, slots=True)
class Routing:
    fingerprint: str
    config_hash: str
    source: str
    scope: str
    roles: dict[str, Pin]


def _load(path: Path, anchor: Path, scope: str) -> Routing | None:
    path = path.expanduser().absolute()
    anchor = anchor.expanduser().absolute()
    if path.parent.is_symlink():
        raise ContractError("routing_path_escape")
    if not path.exists() and not path.is_symlink():
        return None
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_relative_to(anchor.resolve()):
        raise ContractError("routing_path_escape")
    data = read_map(resolved)
    version = data.get("schema_version")
    if set(data) != {"schema_version", "catalog_fingerprint", "roles"} or type(version) is not int or version not in (1, 2):
        raise ContractError("invalid_routing_schema")
    fingerprint = data.get("catalog_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
        raise ContractError("invalid_catalog_fingerprint")
    rows = data.get("roles")
    if not isinstance(rows, dict) or set(rows) != set(ROLE_BODIES):
        raise ContractError("missing_role_pins")
    roles: dict[str, Pin] = {}
    for role, row in rows.items():
        selector = "agent_type" if version == 1 else "task_name_prefix"
        required = {selector, "model", "reasoning_effort"}
        if not isinstance(row, dict) or set(row) not in (required, required | {"allowed_reasoning_efforts"}):
            raise ContractError("invalid_role_pin")
        if version == 2 and row.get(selector) != role + "_":
            raise ContractError("invalid_task_role_prefix")
        identity = token(row.get(selector)) if version == 1 else "task:" + role
        default_effort = token(row.get("reasoning_effort"))
        if "allowed_reasoning_efforts" not in row:
            efforts = (default_effort,)
        else:
            raw_efforts = row["allowed_reasoning_efforts"]
            if not isinstance(raw_efforts, list) or not raw_efforts:
                raise ContractError("invalid_allowed_reasoning_efforts")
            efforts = tuple(token(value) for value in raw_efforts)
            if len(set(efforts)) != len(efforts) or default_effort not in efforts:
                raise ContractError("invalid_allowed_reasoning_efforts")
        roles[token(role)] = Pin(identity, token(row.get("model")), default_effort, efforts)
    if len({pin.agent_type for pin in roles.values()}) != len(roles):
        raise ContractError("role_host_mappings_must_be_unique")
    return Routing(fingerprint, digest(data), str(resolved), scope, roles)


def load(root: Path, home: Path | None = None) -> Routing | None:
    project = _load(root / ".codex/agent-routing.json", root, "project")
    if project is not None or home is None:
        return project
    return _load(home / "dev-setup-codex-community/agent-routing.json", home, "global")


def revoke(event: Event, store: Store) -> None:
    session_key = digest(event.session_id)
    try:
        store.path(f"leases/{session_key}.json").unlink(missing_ok=True)
    except OSError as exc:
        try:
            store.write(f"revocations/{session_key}.json", {"state": "UNVERIFIED", "session_id": event.session_id})
        except OSError:
            raise ContractError("session_revocation_failed") from exc
    event = store.bind(event, create=True)
    previous = store.read(f"sessions/{event.key}.json") or {}
    previous_roles = previous.get("roles", {})
    if not isinstance(previous_roles, dict):
        raise ContractError("invalid_session_roles")
    revoked: JsonMap = {
        "state": "UNVERIFIED", "code": "catalog_discovery_pending", "roles": {**store.owned_roles(event), **previous_roles},
        "project": str(event.root), "session_id": event.session_id,
    }
    store.write(f"sessions/{event.key}.json", revoked)
    store.write(f"projects/{digest(str(event.root))}.json", {"session_id": event.session_id})


def attest(event: Event, store: Store, models: tuple[Model, ...], home: Path | None = None) -> JsonMap:
    event = store.bind(event, create=True)
    config = load(event.root, home)
    owned_roles = store.owned_roles(event)
    state: JsonMap = {"state": "UNSET", "code": "user_role_configuration_required",
                      "project": str(event.root), "session_id": event.session_id,
                      "catalog_fingerprint": catalog_fingerprint(models),
                      "catalog": [{"model": model.model, "efforts": list(model.efforts)} for model in models],
                      "source": "codex_app_server_model_list", "attested_at": time.time(), "roles": owned_roles}
    if not config and owned_roles:
        state.update({"state": "STALE", "code": "routing_config_removed"})
    if config:
        available = {model.model: model.efforts for model in models}
        supported = all(pin.model in available and all(effort in available[pin.model]
                                                       for effort in pin.allowed_reasoning_efforts)
                        for pin in config.roles.values())
        fingerprint_matches = config.fingerprint == state["catalog_fingerprint"]
        fresh = supported
        code = "catalog_matches" if fingerprint_matches else "selected_models_supported"
        if not supported:
            code = "selected_tuple_unavailable"
        state.update({"state": "FRESH" if fresh else "STALE", "code": code,
                      "configured_catalog_fingerprint": config.fingerprint,
                      "config_hash": config.config_hash,
                      "config_source": config.source, "config_scope": config.scope,
                      "roles": {**owned_roles, **{pin.agent_type: {
                          "role": role, **pin.wire(),
                          "allowed_reasoning_efforts": list(pin.allowed_reasoning_efforts),
                      } for role, pin in config.roles.items()}}})
    store.write(f"sessions/{event.key}.json", state)
    store.write(f"bindings/{digest(event.session_id)}.json", {
        "project": str(event.root), "session_id": event.session_id, "roles": state.get("roles", {}),
    })
    store.write(f"projects/{digest(str(event.root))}.json", {"session_id": event.session_id})
    store.write(f"leases/{digest(event.session_id)}.json", {"attestation": digest(state)})
    store.path(f"revocations/{digest(event.session_id)}.json").unlink(missing_ok=True)
    return context("SessionStart", str(state["state"]), str(state["code"]))


def status(event: Event, store: Store, home: Path | None = None) -> JsonMap:
    event = store.bind(event)
    config = load(event.root, home)
    owned_roles = store.owned_roles(event)
    revoked = store.read(f"revocations/{digest(event.session_id)}.json")
    if revoked:
        return {**revoked, "state": "UNVERIFIED", "code": "session_attestation_revoked", "roles": owned_roles}
    state = store.read(f"sessions/{event.key}.json")
    if not state:
        return {"state": "UNVERIFIED" if config or owned_roles else "UNSET", "code": "session_attestation_missing", "roles": owned_roles}
    attestation = digest(state)
    state_roles = state.get("roles", {})
    if not isinstance(state_roles, dict):
        raise ContractError("invalid_session_roles")
    state["roles"] = {**owned_roles, **state_roles}
    lease = store.read(f"leases/{digest(event.session_id)}.json")
    if state.get("state") == "FRESH" and (not lease or lease.get("attestation") != attestation):
        return {**state, "state": "UNVERIFIED", "code": "session_attestation_revoked"}
    attested = state.get("attested_at")
    if not isinstance(attested, (float, int)) or not 0 <= time.time() - attested <= MAX_AGE:
        return {**state, "state": "UNVERIFIED", "code": "session_attestation_expired"}
    if config and state.get("config_source") != config.source:
        return {**state, "state": "STALE", "code": "routing_config_source_changed"}
    if config and state.get("config_hash") != config.config_hash:
        return {**state, "state": "STALE", "code": "routing_config_changed"}
    if not config and state.get("roles"):
        return {**state, "state": "STALE", "code": "routing_config_removed"}
    return state


def pre(event: Event, store: Store, home: Path | None = None) -> JsonMap:
    if event.data.get("tool_name") not in {"spawn_agent", "Agent"}:
        return {}
    event = store.bind(event)
    config = load(event.root, home)
    current = status(event, store, home)
    prior_roles = current.get("roles")
    chosen = next(((role, pin) for role, pin in config.roles.items() if pin.agent_type == event.role), None) if config else None
    pin = chosen[1] if chosen else None
    managed = pin is not None or event.role in store.owned_roles(event) or isinstance(prior_roles, dict) and event.role in prior_roles
    if not managed:
        output = context("PreToolUse", "UNSET" if config is None else "UNVERIFIED", "host_profile_unverified")
        detail = output["hookSpecificOutput"]
        if isinstance(detail, dict):
            detail["permissionDecision"] = "allow"
        return output
    if current.get("state") != "FRESH" or pin is None:
        return deny("managed_role_requires_fresh_session_attestation")
    explicit_model = event.arguments.get("model")
    if "model" in event.arguments and explicit_model != pin.model:
        return deny("explicit_tuple_conflicts_with_project_pin")
    explicit_effort = event.arguments.get("reasoning_effort")
    if "reasoning_effort" in event.arguments and explicit_effort not in pin.allowed_reasoning_efforts:
        return deny("explicit_tuple_conflicts_with_project_pin")
    if event.arguments.get("fork_turns") == "all" or event.arguments.get("fork_context") is True:
        return deny("full_history_cannot_accept_model_effort_overrides")
    selected_effort = explicit_effort if isinstance(explicit_effort, str) else pin.reasoning_effort
    requested = pin.wire(selected_effort)
    updated = {**event.arguments, **requested}
    if "task_name" in updated and "fork_turns" not in updated:
        updated["fork_turns"] = "none"
    message = updated.get("message")
    if not isinstance(message, str) or chosen is None:
        return deny("managed_role_requires_native_message")
    updated["message"] = instruction(chosen[0], message)
    store.write(f"launches/{event.call_key}.json", {
        "state": "PENDING", "project": str(event.root), "session_id": event.session_id,
        "agent_type": token(event.arguments.get("agent_type", "default")), "role_selector": event.role,
        "requested": requested, "config_hash": config.config_hash if config else None,
        "config_source": config.source if config else None,
        "tool_use_id": token(event.data.get("tool_use_id")),
    })
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "updatedInput": updated}}
