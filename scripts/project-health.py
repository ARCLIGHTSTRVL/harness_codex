#!/usr/bin/env python3
"""project-health (brief): one-line health for a managed project.

Read-only w.r.t. the PROJECT; sole write = the machine-global liveness heartbeat
`$CODEX_HOME/.last-health` (default `~/.codex`) -- never the worktree.
This is the cheap checker reused by /doctor, setup-check selftest, manual runs,
and the global native-session adapter. The adapter uses --no-heartbeat and owns
its separate event evidence; a manual checker timestamp is not hook delivery.
Deep checks (wiki-lint, kb-lint, KR-mirror status) are NOT run here -> run
/doctor; this only covers what is cheap enough for frequent checks.

Invariants (per specs/freshness-detection-spine.md):
  1. No silent skip for managed projects: marker-bearing projects print exactly
     one `PROJECT HEALTH:` line. Unmanaged dirs stay silent to avoid global-hook
     noise when a user wires this script themselves.
  3. Fail-safe: any uncertainty (git error, missing field, timeout) -> UNVERIFIED,
     never FRESH.
  4. FRESH is scoped: "NEXT FRESH" means byte/git checks passed, not semantic truth.
  5. Coverage explicit: the line states what was NOT checked here.
  8. Detection only; never fixes. Sole write: the machine-global liveness
     heartbeat `$CODEX_HOME/.last-health` (evidence that this checker ran; lives in
     the home dir, NEVER the project worktree -- a worktree write would dirty
     every managed repo lacking a gitignore entry).

NEXT freshness separates committed drift (STALE) from uncommitted unit work
(WIP). Dirty files outside the active unit are WARN context. Neither FRESH nor
WIP establishes semantic truth about the handoff.

Usage: python project-health.py [--selftest | --no-heartbeat]
Exit: always 0 for normal health output; severity is in the text. A leading
"WARN:" marks a stale NEXT, the resume-correctness invariant.
"""
import datetime
import os
import sys
import subprocess
import json
import re
from io import TextIOWrapper

if isinstance(sys.stdout, TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKERS = ("NEXT.md", "wiki/SCHEMA.md", "knowledge/SCHEMA.md")
BOOTSTRAP_HOOKS = (
    ("freshness", "freshness-inject.sh"),
    ("compact", "compact-handoff-gate.sh"),
    ("gate", "stop-handoff-gate.sh"),
)
CONTEXT_PATHS = (
    "workflow/status.md",
    "workflow/README.md",
    "wiki/log.md",
    "wiki/index.md",
    "knowledge/log.md",
    "knowledge/index.md",
)
NEXT_PLACEHOLDER_RE = re.compile(
    r"<(?:git-sha|YYYY-MM-DD|codex\|human\|other|space-separated|one concrete|"
    r"what is|none \| exact blocker|file:line|wiki/page|knowledge/page|"
    r"why it matters|observable|test/build|manual smoke|the next smallest|"
    r"deferred gate)"
)


def git(args, cwd, strip=True):
    """Return (returncode|None, stdout, stderr). None code = git unavailable/errored.
    strip=False preserves stdout verbatim — REQUIRED for `status --porcelain`, where
    .strip() would eat the leading status space of the first line and shift the
    [3:] path extraction."""
    try:
        r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                           text=True, encoding="utf-8", errors="strict", timeout=5)
        return r.returncode, r.stdout.strip() if strip else r.stdout, r.stderr.strip()
    except Exception as e:
        return None, "", str(e)


def find_root(cwd):
    code, out, _ = git(["rev-parse", "--show-toplevel"], cwd)
    if code == 0 and out:
        return os.path.normpath(out), True
    return cwd, False


def read_frontmatter(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out, closed = {}, False
    for line in lines[1:]:
        if line.strip() == "---":
            closed = True
            break
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out if closed else {}


def next_schema_issues(root, fm=None):
    """Light structural lint for NEXT.md.

    This is not a semantic truth check. It catches the Goodhart failure where a
    hook sees "NEXT.md was touched" but the file is still a placeholder or lacks
    the minimum handoff shape a cold session needs.
    """
    path = os.path.join(root, "NEXT.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return ["NEXT.md unreadable"]
    fm = fm if fm is not None else read_frontmatter(path)
    issues = []
    if not fm:
        issues.append("missing or malformed frontmatter")
    for key in ("last_verified_commit", "last_touched", "writer", "unit_paths"):
        if not fm.get(key):
            issues.append("missing %s" % key)
    lt = fm.get("last_touched", "")
    if lt and not re.match(r"^\d{4}-\d{2}-\d{2}$", lt):
        issues.append("last_touched must be YYYY-MM-DD")
    unit_paths = fm.get("unit_paths", "").split()
    if "NEXT.md" in unit_paths:
        issues.append("unit_paths must not include root NEXT.md")
    if NEXT_PLACEHOLDER_RE.search(text):
        issues.append("template placeholders remain")
    required = (
        "## Active Unit",
        "Goal:",
        "Current state:",
        "Blocker:",
        "Pointers:",
        "Acceptance:",
        "## Next Action",
        "## Pending, Not This Unit",
    )
    for marker in required:
        if marker not in text:
            issues.append("missing %s" % marker)
    if not re.search(r"(?m)^Goal:\s+\S", text):
        issues.append("Goal is empty")
    return issues


def stamp_version(path):
    """Read `# bootstrap-hooks vN` stamp from a hook script, else None."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for _ in range(5):
                line = f.readline()
                if not line:
                    break
                s = line.strip()
                if s.startswith("# bootstrap-hooks v"):
                    return s.split("# bootstrap-hooks v", 1)[1].strip()
    except OSError:
        pass
    return None


def _is_tooling_state(porcelain_line):
    """True if a `git status --porcelain` line is one of our own per-machine tooling
    state files (.codex/.last-doctor, .last-health, .stop-warned-*,
    .compact-warned-*) at the repo root.
    Never filters rename/copy entries (those are real work)."""
    status = porcelain_line[:2]
    if "R" in status or "C" in status:        # rename/copy = real work, never filter
        return False
    path = porcelain_line[3:].strip().strip('"')
    if not path.startswith(".codex/"):
        return False
    rest = path[len(".codex/"):]
    if "/" in rest:                           # nested -> not our root-level state
        return False
    return (
        rest in (".last-doctor", ".last-health")
        or rest.startswith(".stop-warned")
        or rest.startswith(".compact-warned")
    )


def _dirty_touches_unit(porcelain_line, unit_paths):
    """True if a dirty porcelain line touches one of NEXT's unit_paths (for a
    rename/copy line, either side counts)."""
    p = porcelain_line[3:].strip().strip('"')
    halves = p.split(" -> ") if " -> " in p else [p]
    for h in halves:
        h = h.strip().strip('"')
        for u in unit_paths:
            u = u.rstrip("/")
            if u and (h == u or h.startswith(u + "/")):
                return True
    return False


def check_next(root):
    """(state, detail) — FRESH / WIP / STALE / UNVERIFIED. Pessimistic + fail-safe:
    any git call that does not cleanly succeed -> UNVERIFIED, never FRESH.
    Verdict contract is shared with templates/hooks/freshness-inject.sh — keep the
    two aligned (truth table: specs/freshness-detection-spine.md)."""
    fm = read_frontmatter(os.path.join(root, "NEXT.md"))
    commit = fm.get("last_verified_commit") or fm.get("last_verified")
    if not commit:
        return ("UNVERIFIED", "NEXT.md has no last_verified_commit")
    schema_issues = next_schema_issues(root, fm)
    if schema_issues:
        return ("UNVERIFIED", "NEXT.md schema: " + "; ".join(schema_issues[:3]))
    code, base_sha, _ = git(["rev-parse", "--verify", commit + "^{commit}"], root)
    if code != 0 or not base_sha:
        return ("UNVERIFIED", "last_verified_commit %s not found (rebased?)" % commit[:8])
    # is-ancestor: 0 = ancestor (ok), 1 = not ancestor (STALE), anything else = error
    code, _, _ = git(["merge-base", "--is-ancestor", base_sha, "HEAD"], root)
    if code == 1:
        return ("STALE", "base not ancestor of HEAD (rebase / force-push / branch switch)")
    if code != 0:
        return ("UNVERIFIED", "git error checking ancestry")
    code, out, _ = git(["-c", "core.quotePath=false", "status", "--porcelain"], root, strip=False)
    if code != 0:
        return ("UNVERIFIED", "git status failed")
    # ignore our own tooling-state files (.last-doctor etc.) -- they are not work,
    # and would otherwise make every /doctor run self-trigger a STALE NEXT.
    dirty = [ln for ln in out.splitlines() if ln.strip() and not _is_tooling_state(ln)]
    paths = fm.get("unit_paths", "").split()
    if not paths:
        # No unit_paths: the unit-change check cannot run -> never FRESH.
        return ("UNVERIFIED", "no unit_paths in NEXT.md, cannot verify unit%s"
                % ("; tree dirty" if dirty else ""))
    for p in paths:
        # A declared unit path GONE from the working tree means NEXT points at
        # nothing — never fail-open to FRESH via an empty git log on it.
        if not os.path.exists(os.path.join(root, p)):
            return ("STALE", "unit_path '%s' does not exist in working tree" % p)
    code, out, _ = git(["log", "--oneline", base_sha + "..HEAD", "--"] + paths, root)
    if code != 0:
        return ("UNVERIFIED", "git log failed")
    if out:
        return ("STALE", "unit_paths changed since last_verified (NEXT may be behind)")
    if any(_dirty_touches_unit(ln, paths) for ln in dirty):
        return ("WIP", "uncommitted work on unit_paths; expected mid-unit, but review the diff at a cold start")
    warnings = []
    # Real dirt OUTSIDE unit_paths never flips the verdict, but is surfaced.
    if dirty:
        warnings.append("dirty tree outside unit_paths")
    code, out, _ = git(["log", "--oneline", "--max-count=5", base_sha + "..HEAD", "--"] + list(CONTEXT_PATHS), root)
    if code == 0 and out:
        warnings.append("context files changed since handoff: " + " | ".join(out.splitlines()))
    elif code != 0:
        warnings.append("context-file cross-check failed")
    return ("FRESH", "WARN: " + "; ".join(warnings) if warnings else "")


def check_hooks(root):
    """(text|None) — installed bootstrap-hook version vs the repo template."""
    hook_dir = os.path.join(root, ".codex", "hooks")
    has_hook_config = (
        os.path.isfile(os.path.join(root, ".codex", "hooks.json"))
        or os.path.isfile(os.path.join(root, ".codex", "settings.json"))
    )
    if not os.path.isdir(hook_dir) and not has_hook_config:
        return None  # bootstrap hooks are opt-in; absence is not staleness
    found = False
    parts = []
    for label, filename in BOOTSTRAP_HOOKS:
        inst = os.path.join(hook_dir, filename)
        if not os.path.exists(inst):
            if has_hook_config:
                parts.append("%s MISSING" % label)
            continue
        found = True
        iv = stamp_version(inst)
        tv = stamp_version(os.path.join(REPO, "templates", "hooks", filename))
        if iv is None:
            parts.append("%s UNSTAMPED" % label)
            continue
        if tv and iv != tv:
            # unified vocabulary (same as bootstrap-doctor): behind = OUTDATED, ahead = AHEAD?
            try:
                ahead = int(iv) > int(tv)
            except ValueError:
                ahead = False
            if ahead:
                parts.append("%s v%s AHEAD? (template v%s)" % (label, iv, tv))
            else:
                parts.append("%s v%s OUTDATED (template v%s)" % (label, iv, tv))
            continue
        parts.append("%s v%s" % (label, iv))
    if not found and not parts:
        return None
    cfg_warns = hook_config_warns(root)
    return "hooks " + ", ".join(parts + cfg_warns)


def hook_config(root):
    hooks = os.path.join(root, ".codex", "hooks.json")
    legacy = os.path.join(root, ".codex", "settings.json")
    warns = []
    path = None
    if os.path.isfile(hooks):
        path = hooks
        if os.path.isfile(legacy):
            warns.append("WARN: legacy settings.json present")
    elif os.path.isfile(legacy):
        path = legacy
        warns.append("WARN: legacy settings.json only; Codex local hooks use hooks.json")
    if path is None:
        warns.append("WARN: hooks.json missing")
        return {}, warns
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
    except Exception as e:
        warns.append("WARN: hook config unreadable (%s)" % e)
        return {}, warns
    return cfg, warns


def hook_config_warns(root):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("codex_hook_contract", Path(REPO) / "scripts" / "hook_contract.py")
    assert spec is not None and spec.loader is not None
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    return ["WARN: " + warning for warning in contract.check(Path(root))]


def hook_commands(root):
    cfg, warns = hook_config(root)
    cmds = []
    hooks_cfg = cfg.get("hooks") if isinstance(cfg, dict) else None
    if isinstance(hooks_cfg, dict):
        for groups in hooks_cfg.values():
            if not isinstance(groups, list):
                continue
            for g in groups:
                if not isinstance(g, dict):
                    continue
                for h in g.get("hooks", []):
                    if isinstance(h, dict) and isinstance(h.get("command"), str):
                        cmds.append(h["command"])
    return cmds, warns


def hook_attention(text):
    if not text:
        return False
    return any(k in text for k in ("OUTDATED", "UNSTAMPED", "AHEAD?", "MISSING", "WARN"))


def check_hook_exec(root):
    """(text|None) — POSIX execution-proof: a seeded bootstrap hook that lacks the
    exec bit AND is invoked directly (not via `sh `) in .codex/hooks.json will
    silently never run. stat-cheap; not applicable on Windows."""
    if os.name != "posix":
        return None
    cmds, _warns = hook_commands(root)
    bad = []
    for _, name in BOOTSTRAP_HOOKS:
        p = os.path.join(root, ".codex", "hooks", name)
        if not os.path.isfile(p) or os.access(p, os.X_OK):
            continue
        for c in cmds:
            first = c.split()[0] if c.split() else ""
            if name in first:  # direct invocation: the script itself is the command
                bad.append(name)
                break
    if bad:
        return "WARN: hook not executable (invoked directly): " + ", ".join(bad)
    return None


def doctor_age(root):
    """Days since the last doctor run, from .codex/.last-doctor (read-only)."""
    p = os.path.join(root, ".codex", ".last-doctor")
    if not os.path.exists(p):
        return "never"
    try:
        import datetime
        with open(p, "r", encoding="utf-8") as f:
            ts = f.read().strip()
        when = datetime.datetime.fromisoformat(ts)
        days = (datetime.datetime.now() - when).days
        return "%dd ago%s" % (days, " (overdue)" if days > 7 else "")
    except Exception:
        return "unverified"


def main():
    try:
        if "--selftest" in sys.argv:
            # liveness probe for setup-check: proves the script runs, dir-independent.
            # Deliberately does NOT write the heartbeat: setup-check runs selftest
            # itself, so a selftest write would refresh the heartbeat and make the
            # recency check vacuous.
            print("PROJECT HEALTH SELFTEST: ok")
            return 0

        # Liveness heartbeat -- the script's SOLE write (invariant 8, amended
        # machine-global under ~/.codex, NEVER the project worktree
        # (Codex M: a worktree write dirties every managed repo without a gitignore
        # entry). Written on every real run, managed dir or not, so it proves only
        # "project-health executed on this machine". Best-effort: must never block
        # detection.
        if "--no-heartbeat" not in sys.argv:
            try:
                hb_dir = os.path.expanduser(os.environ.get(
                    "CODEX_HOME", os.path.join(os.path.expanduser("~"), ".codex")))
                os.makedirs(hb_dir, exist_ok=True)
                with open(os.path.join(hb_dir, ".last-health"), "w", encoding="utf-8") as f:
                    f.write(datetime.datetime.now().isoformat())
            except OSError as exc:
                print("PROJECT HEALTH: heartbeat unavailable (%s)" % type(exc).__name__, file=sys.stderr)

        cwd = os.getcwd()
        root, git_ok = find_root(cwd)
        name = os.path.basename(root) or root
        markers = [m for m in MARKERS if os.path.exists(os.path.join(root, m))]

        if not markers:
            # No markers -> not a managed project -> stay SILENT (nothing here to keep
            # fresh; this avoids noise when users wire project-health broadly).
            # Marker-bearing projects still emit a line when this checker is run.
            return 0

        if not git_ok:
            print("PROJECT HEALTH: %s -- UNVERIFIED: no git, cannot verify freshness (markers: %s)"
                  % (name, ", ".join(markers)))
            return 0

        parts, warn = [], False
        if os.path.exists(os.path.join(root, "NEXT.md")):
            state, detail = check_next(root)
            parts.append("NEXT %s%s" % (state, ": " + detail if detail else ""))
            if state == "STALE":
                warn = True
        else:
            # Managed project (wiki/ or knowledge/ marker) without a NEXT.md front
            # door: absence must be VISIBLE, not silently omitted -- a missing
            # segment reads as "nothing to check" (false-negative shape; 2026-06-10
            # cold eval). Not a WARN: knowledge-only projects legitimately have no
            # NEXT.md.
            parts.append("NEXT none")
        hooks = check_hooks(root)
        if hooks:
            parts.append(hooks)
        hook_exec = check_hook_exec(root)
        if hook_exec:
            parts.append(hook_exec)
        parts.append("doctor %s" % doctor_age(root))

        lead = "WARN: " if warn else ""
        cov = "deep checks (wiki/knowledge lint, KR mirror) not run here -> /doctor"
        print("%sPROJECT HEALTH: %s -- %s  [%s]" % (lead, name, " | ".join(parts), cov))
        return 0
    except Exception as e:
        print("PROJECT HEALTH: FAILED to run (%s)" % e)
        return 0


if __name__ == "__main__":
    sys.exit(main())
