"""Prove captured installer inputs against immutable Git objects."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass

from scripts.installer_support import is_source_junk


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    files: Mapping[str, bytes]
    scopes: tuple[str, ...]


def _git(repo: Path, *args: str, input_bytes: bytes = b"") -> bytes | None:
    try:
        result = subprocess.run(["git", "--literal-pathspecs", "-C", str(repo), *args],
                                input=input_bytes, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _text_checkout(repo: Path, head: str, path: str) -> bool:
    attributes = _git(repo, "check-attr", f"--source={head}", "-z", "--stdin",
                      "text", "eol", "filter", "working-tree-encoding",
                      input_bytes=os.fsencode(path) + b"\0")
    if attributes is None:
        return False
    fields = attributes.split(b"\0")
    if len(fields) != 13 or fields[-1] != b"":
        return False
    values = {fields[index + 1]: fields[index + 2] for index in range(0, 12, 3)}
    if any(fields[index] != os.fsencode(path) for index in range(0, 12, 3)):
        return False
    if (values.get(b"filter") not in (b"unspecified", b"unset")
            or values.get(b"working-tree-encoding") not in (b"unspecified", b"unset")):
        return False
    text = values.get(b"text")
    if text == b"unset":
        return False
    if text in (b"set", b"auto") or values.get(b"eol") in (b"lf", b"crlf"):
        return True
    if text != b"unspecified":
        return False
    autocrlf = _git(repo, "config", "--get", "core.autocrlf")
    return autocrlf is not None and autocrlf.strip().lower() in (b"true", b"input")


def snapshot_matches_commit(repo: Path, head: str, snapshot: SourceSnapshot) -> bool:
    """Permit exact blobs or text-only CRLF differences; never execute filters."""
    tree = _git(repo, "ls-tree", "-r", "-z", "--full-tree", head, "--", *snapshot.scopes)
    if tree is None:
        return False
    objects: dict[str, str] = {}
    for record in tree.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        fields = metadata.split(b" ")
        if not separator or len(fields) != 3 or fields[1] != b"blob":
            return False
        path = os.fsdecode(raw_path)
        if is_source_junk(path):
            continue
        if fields[0] not in (b"100644", b"100755") or path in objects:
            return False
        objects[path] = fields[2].decode("ascii")
    if snapshot.files.keys() != objects.keys():
        return False
    for path, captured in snapshot.files.items():
        committed = _git(repo, "cat-file", "blob", objects[path])
        if committed is None:
            return False
        if captured == committed:
            continue
        if (b"\r" in committed or any(byte < 32 and byte not in (9, 10) or byte == 127
                                    for byte in committed)
                or captured.replace(b"\r\n", b"\n") != committed
                or not _text_checkout(repo, head, path)):
            return False
    return True
