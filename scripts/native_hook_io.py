#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# How to run: imported by native-hooks.py and native-session.py; no dependencies.
"""Bounded, link-refusing file operations shared by native hook adapters."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import tempfile


@dataclass(frozen=True, slots=True)
class HookRefusal(RuntimeError):
    reason: str

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.reason)


def safe_path(path: Path) -> Path:
    """Reject linked components without resolving away their evidence."""
    absolute = path.expanduser().absolute()
    for candidate in reversed((absolute, *absolute.parents)):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise HookRefusal(f"linked path refused: {candidate}")
        if candidate != absolute and not stat.S_ISDIR(info.st_mode):
            raise HookRefusal(f"parent is not a directory: {candidate}")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise HookRefusal(f"hardlinked file refused: {candidate}")
    return absolute


def read_bytes(path: Path, limit: int = 1_000_000) -> bytes | None:
    target = safe_path(path)
    try:
        descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise HookRefusal(f"single regular file required: {target}")
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise HookRefusal(f"file exceeds {limit} bytes: {target}")
    return content


def write_backup(path: Path, content: bytes) -> Path:
    target = safe_path(path)
    descriptor, name = tempfile.mkstemp(prefix=target.name + ".bak.", dir=target.parent)
    with os.fdopen(descriptor, "wb") as stream:
        _ = stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return Path(name)


def atomic_write(path: Path, content: bytes, expected: bytes | None) -> None:
    """Compare captured bytes under an exclusive writer lock, then replace."""
    target = safe_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _ = safe_path(target.parent)
    lock = safe_path(target.with_name(target.name + ".lock"))
    try:
        with lock.open("xb"):
            pass
    except FileExistsError as exc:
        raise HookRefusal(f"another writer owns {lock}") from exc
    temporary: Path | None = None
    try:
        if read_bytes(target) != expected:
            raise HookRefusal(f"file changed since capture: {target}")
        descriptor, name = tempfile.mkstemp(prefix=target.name + ".tmp.", dir=target.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            _ = stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if read_bytes(target) != expected:
            raise HookRefusal(f"file changed during staging: {target}")
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlink()
