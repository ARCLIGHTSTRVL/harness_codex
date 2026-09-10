#!/usr/bin/env python3
"""One spelling of how NEXT-archive.md is cut into sections and digested, shared by the signals suite and archive-closeout.py."""
import hashlib
import re

MARK = re.compile(r"^<!-- (?:archived from NEXT\.md|closeout recorded|superseded) [^>]*-->$")
PREAMBLE = "(preamble)"


def sections(text):
    out = []
    cur = None
    lines = []
    pre = []
    active = False
    for line in text.split("\n"):
        if MARK.match(line.strip()):
            if active:
                out.append((cur, lines))
            cur, lines, active = None, [line], True
            continue
        (lines if active else pre).append(line)
        if active and cur is None and line.startswith("#"):
            cur = line.strip()
    if active:
        out.append((cur, lines))

    def body(lines):
        joined = "\n".join(lines).strip()
        return joined[:-3].rstrip() if joined.endswith("\n---") else joined

    secs = {h: body(b) for h, b in out if h}
    secs[PREAMBLE] = body(pre)
    return secs


def digest(body):
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def read_digests(path):
    recorded = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        d, _, h = line.partition("  ")
        recorded[h] = d
    return recorded


def read_index(path):
    return [l.rstrip("\r") for l in path.read_text(encoding="utf-8").split("\n") if l.strip()]


def marker_count(text):
    return sum(1 for line in text.split("\n") if MARK.match(line.strip())) + 1
