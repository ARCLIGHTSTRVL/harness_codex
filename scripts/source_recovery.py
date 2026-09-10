"""Capture and validate immutable recovery sources for community installs."""
from dataclasses import dataclass
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

from scripts.native_hook_io import safe_path
from scripts.package import inventory


@dataclass(frozen=True)
class PreparedSource:
    files: tuple[tuple[str, bytes], ...]
    digest: str


def _source_digest(files):
    value = hashlib.sha256()
    for rel, content in files:
        value.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(content).digest())
    return value.hexdigest()


def _read_file(root, path):
    target = safe_path(path)
    try:
        descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise RuntimeError(f"recovery source could not be read: {target} ({type(exc).__name__}: {exc})") from exc
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError("recovery source must be a single regular file: " + str(target))
        content = stream.read()
    return target.relative_to(root).as_posix(), content


def _capture(root):
    root = safe_path(Path(root))
    if not root.is_dir():
        raise RuntimeError("recovery source root is not a directory: " + str(root))
    try:
        paths = inventory(root)
    except (OSError, ValueError) as exc:
        raise RuntimeError("recovery source inventory failed: " + str(exc)) from exc
    rows = tuple(_read_file(root, path) for path in paths)
    if len({rel for rel, _content in rows}) != len(rows):
        raise RuntimeError("recovery source inventory contains duplicate paths")
    return tuple(sorted(rows))


def prepare(root):
    first = _capture(root)
    second = _capture(root)
    if first != second:
        raise RuntimeError("recovery source changed while it was captured")
    return PreparedSource(first, _source_digest(first))


def _actual_files(root):
    rows = []
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise RuntimeError(f"recovery snapshot could not be enumerated: {current} ({type(exc).__name__}: {exc})") from exc
        for entry in entries:
            try:
                info = os.lstat(entry.path)
            except OSError as exc:
                raise RuntimeError(f"recovery snapshot entry could not be inspected: {entry.path}") from exc
            rel = Path(entry.path).relative_to(root).as_posix()
            linked = stat.S_ISLNK(info.st_mode) or bool(
                getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            )
            if linked:
                raise RuntimeError("linked recovery snapshot entry refused: " + rel)
            if stat.S_ISDIR(info.st_mode):
                pending.append(Path(entry.path))
            elif stat.S_ISREG(info.st_mode):
                if info.st_nlink != 1:
                    raise RuntimeError("hardlinked recovery snapshot file refused: " + rel)
                if "__pycache__" in Path(rel).parts:
                    if not re.fullmatch(r".+\.[A-Za-z0-9_]+-\d+(?:\.opt-\d+)?\.pyc", Path(rel).name):
                        raise RuntimeError("invalid recovery snapshot cache file: " + rel)
                    try:
                        source = Path(importlib.util.source_from_cache(str(Path(entry.path))))
                    except ValueError as exc:
                        raise RuntimeError("invalid recovery snapshot cache file: " + rel) from exc
                    if source.parent != Path(entry.path).parent.parent or not source.name.endswith(".py"):
                        raise RuntimeError("invalid recovery snapshot cache location: " + rel)
                    safe_path(source)
                    if not source.is_file():
                        raise RuntimeError("sourceless recovery snapshot cache refused: " + rel)
                    continue
                if rel.endswith(".pyc"):
                    raise RuntimeError("sourceless recovery snapshot bytecode refused: " + rel)
                rows.append(rel)
            else:
                raise RuntimeError("non-regular recovery snapshot entry refused: " + rel)
    return tuple(sorted(rows))


def validate(snapshot, expected_digest):
    if not isinstance(expected_digest, str) or len(expected_digest) != 64 or any(
            char not in "0123456789abcdef" for char in expected_digest):
        raise RuntimeError("invalid recovery source digest")
    root = safe_path(Path(snapshot))
    if root.name != expected_digest or not root.is_dir():
        raise RuntimeError("invalid recovery source location: " + str(root))
    names = _actual_files(root)
    first = tuple(_read_file(root, root.joinpath(*rel.split("/"))) for rel in names)
    second_names = _actual_files(root)
    second = tuple(_read_file(root, root.joinpath(*rel.split("/"))) for rel in second_names)
    if names != second_names:
        raise RuntimeError("recovery snapshot file set changed: " + str(root))
    if first != second or _source_digest(first) != expected_digest:
        raise RuntimeError("recovery snapshot content changed: " + str(root))
    return root


def state_snapshot(state, codex_home, verify=True):
    has_source = "recovery_source" in state
    has_digest = "recovery_digest" in state
    if has_source != has_digest:
        raise RuntimeError("recovery_source and recovery_digest must be recorded together")
    if not has_source:
        return None
    source, digest = state["recovery_source"], state["recovery_digest"]
    if not isinstance(source, str) or not Path(source).is_absolute():
        raise RuntimeError("invalid recovery_source in installation state")
    if not isinstance(digest, str) or len(digest) != 64 or any(
            char not in "0123456789abcdef" for char in digest):
        raise RuntimeError("invalid recovery_digest in installation state")
    store = safe_path(Path(codex_home) / "dev-setup-codex-community" / "sources")
    expected = store / str(digest)
    if os.path.normcase(os.path.abspath(source)) != os.path.normcase(os.path.abspath(expected)):
        raise RuntimeError("recovery_source is outside the managed source store")
    return validate(expected, digest) if verify else expected


def publish(codex_home, prepared):
    home = safe_path(Path(codex_home))
    store = home / "dev-setup-codex-community" / "sources"
    destination = store / prepared.digest
    if destination.exists():
        validate(destination, prepared.digest)
        return destination
    safe_path(store)
    store.mkdir(parents=True, exist_ok=True)
    store = safe_path(store)
    temporary = Path(tempfile.mkdtemp(prefix=".source-", dir=store))
    try:
        for rel, content in prepared.files:
            target = temporary.joinpath(*rel.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            safe_path(target.parent)
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        if _actual_files(temporary) != tuple(rel for rel, _content in prepared.files):
            raise RuntimeError("staged recovery snapshot file set mismatch")
        if tuple(_read_file(temporary, temporary.joinpath(*rel.split("/")))
                 for rel, _content in prepared.files) != prepared.files:
            raise RuntimeError("staged recovery snapshot content mismatch")
        try:
            os.rename(temporary, destination)
        except OSError:
            if not destination.exists():
                raise
            validate(destination, prepared.digest)
        validate(destination, prepared.digest)
        return destination
    finally:
        if temporary.exists():
            if os.path.commonpath((str(store), str(temporary))) != str(store):
                raise RuntimeError("temporary recovery source escaped its store")
            shutil.rmtree(temporary)
