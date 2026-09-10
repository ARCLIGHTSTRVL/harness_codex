#!/usr/bin/env python3
"""Shared path and backup primitives for harness installers."""
import os
from pathlib import Path
import re
import shutil


BACKUP_LIMIT = 3


def is_source_junk(relative: str) -> bool:
    parts = relative.split("/")
    return "__pycache__" in parts[:-1] or parts[-1] == ".gitkeep" or parts[-1].endswith(".pyc")


def normalized_path(value):
    if not isinstance(value, str) or not value:
        raise ValueError("path is missing")
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(value))))


def persisted_path(value):
    return Path(normalized_path(value)).as_posix()


def resolved_executable(value):
    if not isinstance(value, str) or not value:
        raise ValueError("interpreter is missing")
    expanded = os.path.expanduser(value)
    located = expanded if os.path.isabs(expanded) else shutil.which(expanded)
    if not located:
        raise ValueError("interpreter is not executable")
    path = Path(located).resolve()
    if not path.is_file():
        raise ValueError("interpreter is not executable")
    if os.name == "posix" and not os.access(path, os.X_OK):
        raise ValueError("interpreter is not executable")
    return str(path)


def allocate_backup(path, suffix):
    if not isinstance(suffix, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", suffix):
        raise ValueError("backup suffix is malformed")
    base = Path(str(path) + ".bak." + suffix)
    candidate = base
    index = 0
    while candidate.exists() or candidate.is_symlink():
        index += 1
        candidate = Path(str(base) + ".%d" % index)
    return candidate


def _backup_rank(path, base_name):
    prefix = base_name + "."
    tail = path.name[len(prefix):] if path.name.startswith(prefix) else ""
    generation = int(tail) if tail.isascii() and tail.isdecimal() else 0
    return path.stat().st_mtime_ns, generation, path.name


def backup_file(path, suffix, limit=BACKUP_LIMIT):
    if limit < 1:
        raise ValueError("backup limit must be positive")
    source = Path(path)
    backup = allocate_backup(source, suffix)
    try:
        shutil.copy2(source, backup)
        # The numeric suffix is a collision generation, not a timestamp. Use it
        # as the deterministic tiebreaker when copy2-preserved mtimes are equal.
        older = [item for item in source.parent.glob(source.name + ".bak.*")
                 if item != backup]
        base_name = source.name + ".bak." + suffix
        older.sort(key=lambda item: _backup_rank(item, base_name), reverse=True)
        for old in older[limit - 1:]:
            old.unlink()
    except Exception:
        try:
            backup.unlink()
        except OSError:
            pass
        raise
    return backup
