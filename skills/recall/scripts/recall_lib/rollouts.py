#!/usr/bin/env python3
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import ntpath
from pathlib import Path
from typing import Final, TypeAlias

Json: TypeAlias = str | int | float | bool | None | list["Json"] | dict[str, "Json"]
KINDS: Final = ("text", "tool_use", "tool_result", "thinking", "summary")


@dataclass(frozen=True, slots=True)
class Block:
    kind: str
    role: str
    text: str


@dataclass(frozen=True, slots=True)
class Row:
    number: int
    stamp: str
    kind: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True, slots=True)
class Session:
    path: Path
    session_id: str
    cwd: str
    branch: str
    parent: str
    rows: tuple[Row, ...]
    bad: int
    partial: int


def stamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def same_cwd(left: str, right: str) -> bool:
    if ntpath.splitdrive(left)[0] or ntpath.splitdrive(right)[0]:
        return ntpath.normcase(ntpath.normpath(left)) == ntpath.normcase(ntpath.normpath(right))
    return Path(left).resolve() == Path(right).resolve() if left and right else False


def text_parts(value: Json) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(part["text"]) for part in value
                         if isinstance(part, dict) and isinstance(part.get("text"), str))
    return ""


def blocks_of(kind: str, payload: dict[str, Json]) -> tuple[Block, ...]:
    if kind == "compacted":
        text = text_parts(payload.get("message"))
        return (Block("summary", "summary", text),) if text else ()
    if kind == "event_msg":
        role = {"user_message": "user", "agent_message": "assistant"}.get(str(payload.get("type")))
        text = text_parts(payload.get("message"))
        return (Block("text", role, text),) if role and text else ()
    if kind != "response_item":
        return ()
    shape = payload.get("type")
    if shape == "message":
        role = str(payload.get("role", ""))
        text = text_parts(payload.get("content"))
        category = "thinking" if payload.get("channel") == "analysis" else "text"
        return (Block(category, role, text),) if role in ("user", "assistant") and text else ()
    if shape in ("function_call", "custom_tool_call"):
        content = payload.get("arguments") if shape == "function_call" else payload.get("input")
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        return (Block("tool_use", "assistant", str(payload.get("name", "")) + "\n" + text),)
    if shape in ("function_call_output", "custom_tool_call_output"):
        return (Block("tool_result", "tool", text_parts(payload.get("output"))),)
    if shape == "reasoning":
        text = "\n".join(filter(None, (text_parts(payload.get("summary")), text_parts(payload.get("content")))))
        return (Block("thinking", "assistant", text),) if text else ()
    return ()


def read_session(path: Path) -> Session:
    rows: list[Row] = []
    session_id, cwd, branch, parent = path.stem, "", "", ""
    bad = partial = 0
    with path.open("rb") as stream:
        for number, raw in enumerate(stream, 1):
            if not raw.strip():
                continue
            try:
                value: Json = json.loads(raw.decode("utf-8-sig", "replace"))
            except ValueError:
                bad += int(raw.endswith(b"\n"))
                partial += int(not raw.endswith(b"\n"))
                continue
            if not isinstance(value, dict):
                bad += 1
                continue
            kind = str(value.get("type", ""))
            payload = value.get("payload")
            fields = payload if isinstance(payload, dict) else {}
            if kind == "session_meta":
                session_id = str(fields.get("id") or path.stem)
                cwd = str(fields.get("cwd") or "")
                git = fields.get("git")
                branch = str(git.get("branch") or "") if isinstance(git, dict) else ""
                source = fields.get("source")
                agent = source.get("subagent") if isinstance(source, dict) else None
                spawned = agent.get("thread_spawn") if isinstance(agent, dict) else None
                parent = str(spawned.get("parent_thread_id") or "") if isinstance(spawned, dict) else ""
            rows.append(Row(number, str(value.get("timestamp") or ""), kind, blocks_of(kind, fields)))
    return Session(path, session_id, cwd, branch, parent, tuple(rows), bad, partial)
