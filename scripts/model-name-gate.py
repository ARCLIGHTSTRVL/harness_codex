#!/usr/bin/env python3
"""Commit gate: staged ADDED lines carry no model names (vendor family words or versioned model ids), with the front door's exemptions as path rules and a line registry (model-name-exceptions.json) for the two code sites that must carry one."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
SELF_REL = "scripts/model-name-gate.py"
REGISTRY_REL = "model-name-exceptions.json"
EXEMPT_PREFIXES = ("knowledge/", "tests/", ".codex/", ".ask-artifacts/")
EXEMPT_FILES = ("NEXT.md", "NEXT-archive.md", SELF_REL, REGISTRY_REL)
RULES = (
    ("versioned-id", re.compile(r"\b(?:gpt|claude)-[a-z0-9]*-?\d", re.IGNORECASE)),
    ("family-word", re.compile(r"\b(?:opus|sonnet|haiku|fable)\b", re.IGNORECASE)),
)
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def exempt(path):
    if path in EXEMPT_FILES or path.startswith(EXEMPT_PREFIXES):
        return True
    parts = path.split("/")
    return "test_fixtures" in parts or parts[-1].startswith("test_")


def line_key(line):
    return hashlib.sha256(line.strip().encode("utf-8")).hexdigest()


def _git_bytes(repo, args):
    r = subprocess.run(["git", "-C", str(repo)] + args, capture_output=True)
    return (r.stdout, None) if r.returncode == 0 else (None, r.stderr.decode("utf-8", "replace"))


def index_registry(repo):
    """(text or None, error or None) for the registry blob IN THE INDEX.

    What this gate scans is the index, so what suppresses a finding has to come
    from the index too: reading the registry from the working tree let a staged
    model-name line commit against an exception that was never staged with it
    (3B audit 2026-09-02). `secrets-gate.py` closed this one layer down and this
    mirrors it, including the refusal on a non-regular-file entry -- a symlink
    is still a blob and its target text can be valid registry JSON.
    """
    out, err = _git_bytes(repo, ["ls-files", "-s", "-z", "--", REGISTRY_REL])
    if out is None:
        return None, "git ls-files failed -- " + (err or "").strip()
    blob = None
    for record in out.split(b"\0"):
        if not record:
            continue
        meta = record.decode("utf-8", "replace").split("\t", 1)[0].split(" ")
        if len(meta) == 3 and meta[2] == "0":
            if meta[0] not in ("100644", "100755"):
                return None, "registry is not a regular file in the index (mode %s)" % meta[0]
            blob = meta[1]
    if blob is None:
        return None, None
    out, err = _git_bytes(repo, ["cat-file", "blob", blob])
    if out is None:
        return None, "git cat-file failed -- " + (err or "").strip()
    try:
        return out.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "registry unreadable: UnicodeDecodeError"


def load_registry(repo):
    """({(path, sha256): reason}, [note]) from the INDEX, or an exception."""
    text, error = index_registry(repo)
    if error:
        return ValueError(error), []
    notes = []
    worktree = None
    path = repo / REGISTRY_REL
    if path.is_file():
        try:
            worktree = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            worktree = None
    # Newline-normalised, as the secrets gate does: autocrlf checks a LF blob out
    # as CRLF, and a byte compare would fire this note on every Windows commit.
    norm = lambda s: None if s is None else s.replace("\r\n", "\n")
    if norm(worktree) != norm(text):
        notes.append("registry: read from the index; the working-tree copy differs "
                     "-- stage %s for your edit to apply" % REGISTRY_REL)
    if text is None:
        return {}, notes
    try:
        entries = json.loads(text)
        return {(e["path"], e["sha256"]): e.get("reason", "") for e in entries}, notes
    except (ValueError, TypeError, KeyError) as exc:
        return exc, notes


def added_lines(repo):
    # `--text` and `--no-textconv`: a rendered diff is shaped by repository
    # configuration, and an ordinary `-diff` attribute on a path emptied this
    # gate's entire input -- "Binary files differ" carries no added lines, so the
    # gate reported OK on a staged model name (3B audit 2026-09-02). `--find-renames`
    # is off and the filter now admits typechanges (T), whose new content is as
    # scannable as any other.
    r = subprocess.run(["git", "-C", str(repo), "-c", "core.quotepath=false",
                        "diff", "--cached", "--no-color", "--unified=0", "--no-prefix",
                        "--text", "--no-textconv", "--no-ext-diff",
                        "--diff-filter=ACMRT"], capture_output=True)
    if r.returncode != 0:
        return None, r.stderr.decode("utf-8", "replace")
    text = r.stdout.decode("utf-8", "replace")
    # Hunk-state-aware. `+++ ` is a file header only OUTSIDE a hunk: an added line
    # whose own content begins "++ " is rendered as "+++ ...", and reading that as a
    # header skipped the line and every line after it until the next real header --
    # the gate printed OK over a staged model name (r2 Major, 2026-09-03). The
    # secrets gate has pinned this shape since it stopped reading rendered patches
    # at all; the better fix here is the same plumbing move (diff-index --raw plus
    # cat-file), and it is deliberately NOT taken in this unit: it is a rewrite of
    # the gate's input, not a repair of its parser, and it wants its own red-first
    # unit rather than a late edit in a long one.
    path, lineno, out, in_hunk = None, 0, [], False
    for raw in text.split("\n"):
        if raw.startswith("diff --git "):
            path, in_hunk = None, False
            continue
        if not in_hunk:
            if raw.startswith("+++ "):
                path = raw[4:].strip()
                continue
            if raw.startswith("--- "):
                continue
        m = HUNK.match(raw)
        if m:
            lineno = int(m.group(1))
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if raw.startswith("+") and path is not None:
            out.append((path, lineno, raw[1:]))
            lineno += 1
        elif raw.startswith(" ") and path is not None:
            lineno += 1
        elif raw.startswith("\\"):
            # "\ No newline at end of file" belongs to the preceding line.
            continue
    return out, ""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    repo = HERE.parent
    if "--repo" in argv:
        i = argv.index("--repo")
        repo = Path(argv[i + 1])
        del argv[i:i + 2]
    if argv != ["staged"]:
        print("usage: model-name-gate.py staged [--repo PATH]", file=sys.stderr)
        return 2
    if not (repo / ".git").exists():
        print("model-name-gate: %s is not a git repository" % repo, file=sys.stderr)
        return 2
    lines, error = added_lines(repo)
    if lines is None:
        print("model-name-gate: git diff failed -- " + error.strip(), file=sys.stderr)
        return 2
    registry, registry_notes = load_registry(repo)
    if isinstance(registry, Exception):
        print("model-name-gate: %s is not a readable registry (%s) -- failing closed"
              % (REGISTRY_REL, type(registry).__name__), file=sys.stderr)
        return 2
    # Printed before any finding: a suppression the committer did not stage is the
    # first thing to know about a verdict that depends on suppressions.
    for note in registry_notes:
        print("model-name-gate: " + note, file=sys.stderr)
    hits = 0
    for path, lineno, line in lines:
        if exempt(path):
            continue
        for rule, pattern in RULES:
            m = pattern.search(line)
            if not m:
                continue
            key = (path, line_key(line))
            if key in registry:
                print("suppressed by registry: %s:%d %s (reason: %s)" % (path, lineno, rule, registry[key]))
                break
            hits += 1
            print("%s:%d: %s -- %s" % (path, lineno, rule, m.group(0)))
            break
    if hits:
        print("MODEL-NAME GATE BLOCKED (staged): %d added line(s) carry a model name; move the name into an "
              "exempt record, or register the line in %s with a reason" % (hits, REGISTRY_REL), file=sys.stderr)
        return 1
    print("MODEL-NAME GATE OK (staged)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
