#!/usr/bin/env python3
"""Stamp NEXT.md's last_verified_commit to a commit (default HEAD) in one command, byte-preserving, refusing a dirty NEXT.md."""
import argparse
from pathlib import Path
import subprocess
import sys

KEY = b"last_verified_commit: "


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def refuse(message):
    print("next-stamp: " + message, file=sys.stderr)
    return 2


def main(argv=None):
    parser = argparse.ArgumentParser(prog="next-stamp", add_help=True)
    parser.add_argument("commit", nargs="?", default="HEAD")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    repo = Path(args.repo)
    target = repo / "NEXT.md"
    if not target.is_file():
        return refuse("no NEXT.md at %s" % target)
    resolved = git(repo, "rev-parse", "--short", "--verify", "--quiet", args.commit + "^{commit}")
    if resolved.returncode != 0 or not resolved.stdout.strip():
        return refuse("cannot resolve '%s' to a commit in %s" % (args.commit, repo))
    new = resolved.stdout.strip().encode("utf-8")
    raw = target.read_bytes()
    # splitlines(keepends=True), not split on ONE chosen delimiter: a file whose key
    # line ends LF inside an otherwise-CRLF NEXT.md put every following LF-terminated
    # line inside the key's element, and the replacement deleted them -- `unit_paths`
    # gone, exit 0 (3B audit 2026-09-02, Critical). Only the key line's own bytes are
    # rewritten; every other byte, terminators included, is carried through untouched.
    lines = raw.splitlines(True)
    hits = [i for i, line in enumerate(lines) if line.startswith(KEY)]
    if len(hits) != 1:
        return refuse("NEXT.md carries %d '%s' lines; exactly one is required"
                      % (len(hits), KEY.decode().strip()))
    key_line = lines[hits[0]]
    body = key_line
    terminator = b""
    for end in (b"\r\n", b"\n", b"\r"):
        if body.endswith(end):
            body, terminator = body[:-len(end)], end
            break
    old = body[len(KEY):]
    if old == new:
        print("next-stamp: already at %s" % new.decode())
        return 0
    if git(repo, "ls-files", "--error-unmatch", "--", "NEXT.md").returncode != 0:
        return refuse("NEXT.md is untracked -- commit the handoff before stamping")
    unstaged = git(repo, "diff", "--quiet", "--", "NEXT.md").returncode
    staged = git(repo, "diff", "--cached", "--quiet", "--", "NEXT.md").returncode
    if unstaged != 0 or staged != 0:
        return refuse("NEXT.md has uncommitted changes -- a stamp is its own commit; commit or stash them first")
    if args.dry_run:
        print("next-stamp: would stamp %s -> %s (dry run, nothing written)"
              % (old.decode("utf-8", "replace"), new.decode()))
        return 0
    lines[hits[0]] = KEY + new + terminator
    target.write_bytes(b"".join(lines))
    print("next-stamp: %s -> %s" % (old.decode("utf-8", "replace"), new.decode()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
