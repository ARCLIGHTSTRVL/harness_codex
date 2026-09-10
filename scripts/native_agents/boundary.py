from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Final, TypeAlias

Json: TypeAlias = None | bool | int | float | str | list["Json"] | dict[str, "Json"]
JsonMap: TypeAlias = dict[str, Json]
LIMIT: Final = 1_048_576
IDENTITY_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:+@-]{0,199}")
NAME_SURROGATE: Final = 0x20000000


class ContractError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def parse_map(raw: str) -> JsonMap:
    try:
        value: Json = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise ContractError("invalid_json") from exc
    if not isinstance(value, dict):
        raise ContractError("expected_object")
    return value


def token(value: Json) -> str:
    if not isinstance(value, str) or not IDENTITY_PATTERN.fullmatch(value):
        raise ContractError("invalid_identity_field")
    return value


def optional_token(value: Json) -> str | None:
    return None if value is None else token(value)


def digest(value: Json) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_map(path: Path) -> JsonMap:
    with path.open("rb") as source:
        raw = source.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ContractError("file_too_large")
    return parse_map(raw.decode("utf-8-sig"))


def _linked_component(path: Path) -> bool:
    current = path.absolute()
    while True:
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ContractError("state_path_escape") from exc
        else:
            if (stat.S_ISLNK(metadata.st_mode)
                    or bool(getattr(metadata, "st_reparse_tag", 0) & NAME_SURROGATE)):
                return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


def project_root(cwd: str) -> Path:
    directory = Path(cwd)
    if not directory.is_absolute() or not directory.is_dir():
        raise ContractError("invalid_cwd")
    resolved = directory.resolve()
    for candidate in (resolved, *resolved.parents):
        routing = candidate / ".codex/agent-routing.json"
        if (routing.exists() or routing.is_symlink() or routing.parent.is_symlink()
                or (candidate / ".git").exists()):
            return candidate
    return resolved


@dataclass(frozen=True, slots=True)
class Event:
    session_id: str
    root: Path
    data: JsonMap

    @classmethod
    def parse(cls, raw: str) -> Event:
        if len(raw.encode()) > LIMIT:
            raise ContractError("payload_too_large")
        data = parse_map(raw)
        cwd = data.get("cwd")
        if not isinstance(cwd, str):
            raise ContractError("missing_cwd")
        return cls(token(data.get("session_id")), project_root(cwd), data)

    @property
    def key(self) -> str:
        return digest([str(self.root), self.session_id])

    @property
    def arguments(self) -> JsonMap:
        value = self.data.get("tool_input")
        if not isinstance(value, dict):
            raise ContractError("invalid_tool_input")
        return value

    @property
    def role(self) -> str:
        task = self.arguments.get("task_name")
        if "agent_type" not in self.arguments and isinstance(task, str):
            role, separator, suffix = task.partition("_")
            if separator and suffix and role in {"worker", "reviewer", "explore", "plan", "general"}:
                return "task:" + role
        return token(self.arguments.get("agent_type", "default"))

    @property
    def call_key(self) -> str:
        return digest([self.key, token(self.data.get("tool_use_id"))])


@dataclass(frozen=True, slots=True)
class Store:
    root: Path

    def owned_roles(self, event: Event) -> JsonMap:
        binding = self.read(f"bindings/{digest(event.session_id)}.json") or {}
        roles = binding.get("roles", {})
        if not isinstance(roles, dict):
            raise ContractError("invalid_session_binding_roles")
        return roles

    def bind(self, event: Event, create: bool = False) -> Event:
        name = f"bindings/{digest(event.session_id)}.json"
        binding = self.read(name)
        if binding is None:
            if create:
                self.write(name, {"project": str(event.root), "session_id": event.session_id})
            return event
        project, cwd = binding.get("project"), event.data.get("cwd")
        if not isinstance(project, str) or not isinstance(cwd, str) or binding.get("session_id") != event.session_id:
            raise ContractError("invalid_session_binding")
        root = Path(project)
        if not root.is_absolute() or root.resolve() != root or not Path(cwd).resolve().is_relative_to(root):
            raise ContractError("cwd_outside_attested_project")
        return Event(event.session_id, root, event.data)

    def latest(self, event: Event) -> Event:
        cwd = event.data.get("cwd")
        if not isinstance(cwd, str):
            raise ContractError("missing_cwd")
        directory = Path(cwd).resolve()
        for root in (directory, *directory.parents):
            latest = self.read(f"projects/{digest(str(root))}.json")
            if latest:
                return self.bind(Event(token(latest.get("session_id")), root, event.data))
            if root == event.root:
                break
        return event

    def path(self, name: str) -> Path:
        if not re.fullmatch(r"[a-z]+/[0-9a-f]{64}\.json", name):
            raise ContractError("invalid_state_key")
        target = self.root.absolute() / name
        resolved = self.root.absolute().resolve()
        if _linked_component(target) or not target.resolve().is_relative_to(resolved):
            raise ContractError("state_path_escape")
        return target

    def read(self, name: str) -> JsonMap | None:
        path = self.path(name)
        return read_map(path) if path.exists() else None

    def write(self, name: str, data: JsonMap) -> None:
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.path(name)
        descriptor, temporary = tempfile.mkstemp(prefix=".native-agent-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(json.dumps(data, sort_keys=True) + "\n")
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def context(event: str, state: str, code: str) -> JsonMap:
    return {"hookSpecificOutput": {"hookEventName": event,
                                   "additionalContext": f"Native agent contract {state}: {code}"}}


def deny(code: str) -> JsonMap:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": f"Native agent contract: {code}"}}
