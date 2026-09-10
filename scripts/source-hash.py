#!/usr/bin/env python3
"""Compute a deterministic hash of managed dev-setup-codex source files."""
import hashlib
import importlib.util
import os
import sys
from pathlib import Path

CHECKER = Path(__file__).with_name("setup-check.py")
SKIP_PARTS = {"__pycache__", ".git"}
SKIP_SUFFIXES = (".pyc",)
SKIP_CONTAINS = (".bak.",)


def include(path):
    parts = set(path.parts)
    if parts & SKIP_PARTS:
        return False
    if path.name.endswith(SKIP_SUFFIXES):
        return False
    if any(token in path.name for token in SKIP_CONTAINS):
        return False
    return path.is_file()


def main():
    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    spec = importlib.util.spec_from_file_location("source_hash_checker", CHECKER)
    if spec is None or spec.loader is None:
        raise RuntimeError("setup-check module loader unavailable")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    files = []
    for rel in checker.MANAGED_SOURCE_PATHS:
        p = repo / rel
        if include(p):
            files.append(p)
            continue
        if not p.is_dir():
            continue
        for child in p.rglob("*"):
            if include(child):
                files.append(child)
    out = hashlib.sha256()
    for p in sorted(files, key=lambda x: x.relative_to(repo).as_posix()):
        rel = p.relative_to(repo).as_posix()
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        out.update(f"{rel}\t{h}\n".encode("utf-8"))
    print(out.hexdigest())


if __name__ == "__main__":
    main()
