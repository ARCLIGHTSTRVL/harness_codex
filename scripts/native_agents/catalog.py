"""Read native model capabilities through the app-server protocol."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import shutil
import subprocess
from threading import Thread
from typing import IO, Final, TypeAlias

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
TIMEOUT_SECONDS: Final = 10.0
MAX_LINE_BYTES: Final = 1_048_576


@dataclass(frozen=True, slots=True)
class Model:
    model: str
    efforts: tuple[str, ...]


class CatalogError(Exception):
    code: str

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _model(raw: JsonValue) -> tuple[str, Model]:
    if not isinstance(raw, dict):
        raise CatalogError("invalid-model")
    for key in ("id", "model", "displayName", "description", "defaultReasoningEffort"):
        if not isinstance(raw.get(key), str):
            raise CatalogError("incomplete-model")
    if any(type(raw.get(key)) is not bool for key in ("hidden", "isDefault")):
        raise CatalogError("incomplete-model")
    identifier, slug = raw["id"], raw["model"]
    options = raw.get("supportedReasoningEfforts")
    if not isinstance(identifier, str) or not isinstance(slug, str):
        raise CatalogError("invalid-model")
    if not identifier.strip() or not slug.strip() or not isinstance(options, list) or not options:
        raise CatalogError("incomplete-model")
    efforts: list[str] = []
    for option in options:
        if not isinstance(option, dict) or not isinstance(option.get("description"), str):
            raise CatalogError("invalid-effort")
        effort = option.get("reasoningEffort")
        if not isinstance(effort, str) or not effort.strip() or effort in efforts:
            raise CatalogError("invalid-effort")
        efforts.append(effort)
    if raw["defaultReasoningEffort"] not in efforts:
        raise CatalogError("invalid-default-effort")
    return identifier, Model(slug, tuple(efforts))


def _reply(stream: IO[bytes], request_id: int) -> JsonValue:
    for _ in range(1000):
        line = stream.readline(MAX_LINE_BYTES + 1)
        if not line:
            raise CatalogError("catalog-eof")
        if len(line) > MAX_LINE_BYTES:
            raise CatalogError("catalog-output-limit")
        try:
            response: JsonValue = json.loads(line)
        except (ValueError, UnicodeError, RecursionError):
            raise CatalogError("invalid-json") from None
        if not isinstance(response, dict):
            raise CatalogError("invalid-response")
        if "id" not in response and isinstance(response.get("method"), str):
            continue
        if type(response.get("id")) is not int or response["id"] != request_id:
            raise CatalogError("unexpected-response")
        if "error" in response:
            raise CatalogError("catalog-rpc-error")
        if "result" not in response:
            raise CatalogError("invalid-response")
        return response["result"]
    raise CatalogError("catalog-output-limit")


def _send(stream: IO[bytes], message: JsonValue) -> None:
    stream.write((json.dumps(message, ensure_ascii=True) + "\n").encode("utf-8"))
    stream.flush()


def _exchange(stdin: IO[bytes], stdout: IO[bytes]) -> tuple[Model, ...]:
    _send(stdin, {"id": 1, "method": "initialize", "params": {
        "clientInfo": {"name": "dev_setup_native_catalog", "version": "1"}}})
    if not isinstance(_reply(stdout, 1), dict):
        raise CatalogError("invalid-initialize")
    _send(stdin, {"method": "initialized"})
    cursor: str | None = None
    cursors: set[str] = set()
    identifiers: set[str] = set()
    models: dict[str, Model] = {}
    for request_id in range(2, 130):
        params: dict[str, JsonValue] = {"limit": 100, "includeHidden": True}
        if cursor is not None:
            params["cursor"] = cursor
        _send(stdin, {"id": request_id, "method": "model/list", "params": params})
        page = _reply(stdout, request_id)
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            raise CatalogError("invalid-catalog-page")
        data = page["data"]
        if not isinstance(data, list) or not data:
            raise CatalogError("empty-catalog-page")
        for raw in data:
            identifier, model = _model(raw)
            if identifier in identifiers or model.model in models:
                raise CatalogError("duplicate-model")
            identifiers.add(identifier)
            models[model.model] = model
            if len(models) > 10_000:
                raise CatalogError("catalog-output-limit")
        next_cursor = page.get("nextCursor")
        if next_cursor is None:
            return tuple(models.values())
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor in cursors:
            raise CatalogError("invalid-catalog-cursor")
        cursors.add(next_cursor)
        cursor = next_cursor
    raise CatalogError("catalog-page-limit")


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        # Terminate npm's Windows command shim together with its native child.
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
        try:
            subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        process.kill()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        raise CatalogError("catalog-stop-timeout") from None


def discover(command: Sequence[str]) -> tuple[Model, ...]:
    """Discover the active configured catalog without starting a thread or turn."""
    if not command or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in command):
        raise CatalogError("invalid-catalog-command")
    executable = shutil.which(command[0])
    if executable is None:
        raise CatalogError("catalog-command-unavailable")
    results: Queue[tuple[Model, ...] | CatalogError] = Queue(maxsize=1)
    try:
        with subprocess.Popen([executable, *command[1:]], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
            assert process.stdin is not None and process.stdout is not None
            stdin, stdout = process.stdin, process.stdout

            def exchange() -> None:
                try:
                    results.put(_exchange(stdin, stdout))
                except CatalogError as error:
                    results.put(error)
                except (OSError, ValueError):
                    results.put(CatalogError("catalog-transport-error"))

            worker = Thread(target=exchange, daemon=True)
            worker.start()
            try:
                try:
                    result = results.get(timeout=TIMEOUT_SECONDS)
                except Empty:
                    raise CatalogError("catalog-timeout") from None
                if isinstance(result, CatalogError):
                    raise result
                stdin.close()
                try:
                    exit_code = process.wait(timeout=0.25)
                except subprocess.TimeoutExpired:
                    exit_code = None
                if exit_code not in (None, 0):
                    raise CatalogError("catalog-process-failed")
                return result
            finally:
                _stop(process)
                worker.join(timeout=1)
    except OSError:
        raise CatalogError("catalog-transport-error") from None


def catalog_fingerprint(models: Sequence[Model]) -> str:
    capabilities = sorted((model.model, sorted(model.efforts)) for model in models)
    wire = json.dumps(capabilities, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(wire.encode("utf-8")).hexdigest()
