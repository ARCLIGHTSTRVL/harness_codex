"""Canonical public source metadata and opt-in remote freshness checks."""
import re
import subprocess
from pathlib import Path

PUBLIC_REPOSITORY_URL = "https://github.com/ARCLIGHTSTRVL/harness_codex"
PUBLIC_DEFAULT_BRANCH = "main"
_PUBLIC_REF = "refs/heads/" + PUBLIC_DEFAULT_BRANCH
_OBJECT_ID = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})")


def _run(command, runner):
    try:
        return runner(command, capture_output=True, text=True, encoding="utf-8",
                      errors="replace", timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _local_head(repo, runner):
    repo = Path(repo).resolve()
    root = _run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"], runner)
    if root is None or root.returncode != 0:
        return None
    try:
        if Path(root.stdout.strip()).resolve() != repo:
            return None
    except (OSError, ValueError):
        return None
    head = _run(["git", "-C", str(repo), "rev-parse", "--verify", "HEAD^{commit}"], runner)
    value = "" if head is None or head.returncode != 0 else head.stdout.strip()
    return value.lower() if _OBJECT_ID.fullmatch(value) else None


def report(repo, check_updates=False, runner=None):
    lines = [f"Public source: {PUBLIC_REPOSITORY_URL} "
             f"(default branch: {PUBLIC_DEFAULT_BRANCH})"]
    if not check_updates:
        lines.append("Public update status: latest not checked; this run checked local "
                     "installation and source content only. Use --check-updates to compare.")
        return lines, 0

    runner = runner or subprocess.run
    local = _local_head(repo, runner)
    if local is None:
        lines.append("Public update status: unknown; a Git revision could not be established "
                     "at this exact source root. Extracted ZIPs cannot be compared by Git "
                     "revision; clone the public repository or download and extract a newer "
                     "ZIP to update.")
        return lines, 2

    remote = _run(["git", "ls-remote", "--exit-code", PUBLIC_REPOSITORY_URL,
                   _PUBLIC_REF], runner)
    if remote is None or remote.returncode != 0:
        lines.append("Public update status: unknown; the canonical public branch could not "
                     "be queried. Try --check-updates again when GitHub is reachable.")
        return lines, 2
    fields = remote.stdout.strip().split()
    if (len(fields) != 2 or fields[1] != _PUBLIC_REF
            or not _OBJECT_ID.fullmatch(fields[0])):
        lines.append("Public update status: unknown; the canonical public branch returned "
                     "an unexpected response.")
        return lines, 2
    remote_head = fields[0].lower()
    if local == remote_head:
        lines.append(f"Public update status: current at {local[:12]}; the local revision "
                     f"matches canonical {PUBLIC_DEFAULT_BRANCH}. Working-tree edits are "
                     "outside this revision check.")
        return lines, 0
    lines.append(f"Public update status: differs; local HEAD {local[:12]} and canonical "
                 f"{PUBLIC_DEFAULT_BRANCH} {remote_head[:12]} are not equal. This check does "
                 "not determine ancestry.")
    return lines, 1
