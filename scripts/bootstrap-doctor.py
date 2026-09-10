#!/usr/bin/env python3
"""bootstrap-doctor: audit cold-start bootstrap hook drift across projects.

Because the bootstrap hooks are seed-and-own (each project keeps its own copy,
A-model), copies drift from the harness template over time. This makes the drift
VISIBLE: it scans the dev roots for projects that carry the bootstrap, reads each
project's hook version stamp, and compares it to the harness template's current
version. Read-only — it reports, it never modifies a project.

Run:  python scripts/bootstrap-doctor.py   (Windows)
      python3 scripts/bootstrap-doctor.py  (macOS/Linux)
Spec: specs/project-bootstrap-continuity.md
"""
import json
import os
import re
import sys
from pathlib import Path
from io import TextIOWrapper

if isinstance(sys.stdout, TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parents[1]
TEMPLATE_HOOK = REPO / "templates" / "hooks" / "freshness-inject.sh"
TEMPLATE_COMPACT = REPO / "templates" / "hooks" / "compact-handoff-gate.sh"
TEMPLATE_GATE = REPO / "templates" / "hooks" / "stop-handoff-gate.sh"
STAMP_RE = re.compile(r"#\s*bootstrap-hooks\s+v(\d+)")
TRIAL_RE = re.compile(r"^\s*TRIAL\s*=\s*(\d)", re.M)


def hook_version(path: Path):
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[:15]:
            m = STAMP_RE.search(line)
            if m:
                return int(m.group(1))
    except OSError:
        return None
    return None


def trial_mode(path: Path):
    try:
        m = TRIAL_RE.search(path.read_text(encoding="utf-8", errors="ignore"))
        return m.group(1) if m else None
    except OSError:
        return None


def dev_roots():
    home = Path.home()
    candidates = [home / "dev", Path("C:/dev")]
    seen, out = set(), []
    for r in candidates:
        try:
            rp = r.resolve()
        except OSError:
            continue
        if rp.is_dir() and rp not in seen:
            seen.add(rp)
            out.append(rp)
    return out


def hook_status(path: Path, template_v):
    """Version status of one seeded hook vs its template. Unified vocabulary
    (same as project-health.py): behind = OUTDATED, ahead = AHEAD?, equal = current."""
    if not path.is_file():
        return "MISSING"
    v = hook_version(path)
    if v is None:
        return "UNSTAMPED (pre-versioning)"
    if template_v is None:
        return f"v{v}"
    if v < template_v:
        return f"v{v} OUTDATED -> template v{template_v}"
    if v > template_v:
        return f"v{v} AHEAD? (template v{template_v})"
    return f"v{v} current"


def hook_config(proj: Path):
    hooks = proj / ".codex" / "hooks.json"
    legacy = proj / ".codex" / "settings.json"
    warns = []
    path = None
    if hooks.is_file():
        path = hooks
        if legacy.is_file():
            warns.append("legacy settings.json present")
    elif legacy.is_file():
        path = legacy
        warns.append("legacy settings.json only; Codex local hooks use hooks.json")
    if path is None:
        return None, warns
    try:
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        warns.append(f"hook config unreadable: {e}")
        return None, warns
    return cfg, warns


def hook_commands(proj: Path):
    cfg, warns = hook_config(proj)
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


def hook_config_warns(proj):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("codex_hook_contract", Path(REPO) / "scripts" / "hook_contract.py")
    assert spec is not None and spec.loader is not None
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    return contract.check(Path(proj))


def exec_warns(proj: Path):
    """POSIX execution-proof (same check as project-health.py): a seeded hook that
    lacks the exec bit AND is invoked directly (not via `sh `) in the project's
    hooks.json will silently never run. Skipped entirely on Windows; stat-cheap."""
    cmds, _warns = hook_commands(proj)
    warns = []
    if os.name != "posix":
        return warns
    for name in ("freshness-inject.sh", "compact-handoff-gate.sh", "stop-handoff-gate.sh"):
        p = proj / ".codex" / "hooks" / name
        if not p.is_file() or os.access(p, os.X_OK):
            continue
        for c in cmds:
            first = c.split()[0] if c.split() else ""
            if name in first:  # direct invocation: the script itself is the command
                warns.append(f"{name} not executable (invoked directly)")
                break
    return warns


def audit(proj: Path, template_v, gate_template_v):
    fhook = proj / ".codex" / "hooks" / "freshness-inject.sh"
    chook = proj / ".codex" / "hooks" / "compact-handoff-gate.sh"
    ghook = proj / ".codex" / "hooks" / "stop-handoff-gate.sh"
    has_hook_config = (proj / ".codex" / "hooks.json").is_file() or (proj / ".codex" / "settings.json").is_file()
    has_hooks = fhook.is_file() or chook.is_file() or ghook.is_file()
    has_agents = (proj / "AGENTS.md").is_file()
    has_next = (proj / "NEXT.md").is_file()
    if not (has_hooks or has_hook_config or has_agents or has_next):
        return None  # not a bootstrap project — skip

    if has_hooks or has_hook_config:
        t = trial_mode(fhook) if fhook.is_file() else None
        tier = {"1": "trial-hooks", "0": "enforced-hooks"}.get(t or "", "hooks(?)")
        compact_template_v = hook_version(TEMPLATE_COMPACT)
        status = (
            f"{hook_status(fhook, template_v)}"
            f" | compact {hook_status(chook, compact_template_v)}"
            f" | gate {hook_status(ghook, gate_template_v)}"
        )
        for w in hook_config_warns(proj) + exec_warns(proj):
            status += f" | WARN: {w}"
    else:
        tier = "docs-only"
        status = "(no hooks)"

    return {"name": proj.name, "tier": tier, "next": "yes" if has_next else "no", "status": status}


def main():
    template_v = hook_version(TEMPLATE_HOOK)
    compact_template_v = hook_version(TEMPLATE_COMPACT)
    gate_template_v = hook_version(TEMPLATE_GATE)
    roots = dev_roots()
    rows = []
    for root in roots:
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name == REPO.name:
                continue
            try:
                r = audit(child, template_v, gate_template_v)
            except OSError:
                r = None
            if r:
                rows.append(r)

    print(f"bootstrap-doctor - template versions: freshness v{template_v if template_v is not None else '?'} "
          f"| compact v{compact_template_v if compact_template_v is not None else '?'} "
          f"| gate v{gate_template_v if gate_template_v is not None else '?'}")
    print(f"dev roots scanned: {', '.join(str(r) for r in roots) or '(none found)'}")
    print()
    if not rows:
        print("No bootstrap projects found.")
        return

    w = max(len(r["name"]) for r in rows)
    print(f"{'PROJECT'.ljust(w)}  {'TIER'.ljust(15)}  {'NEXT'.ljust(4)}  STATUS")
    outdated = 0
    for r in rows:
        if any(k in r["status"] for k in ("OUTDATED", "UNSTAMPED", "MISSING", "WARN")):
            outdated += 1
        print(f"{r['name'].ljust(w)}  {r['tier'].ljust(15)}  {r['next'].ljust(4)}  {r['status']}")
    print()
    enforced = sum(1 for r in rows if r["tier"] == "enforced-hooks")
    trial = sum(1 for r in rows if r["tier"] == "trial-hooks")
    docs = sum(1 for r in rows if r["tier"] == "docs-only")
    print(f"{len(rows)} bootstrap project(s) | {enforced} enforced | {trial} trial | "
          f"{docs} docs-only | {outdated} need attention (outdated/unstamped/missing/warn)")
    if outdated:
        print("To upgrade a project: re-copy templates/hooks/* and templates/hooks.json into it, "
              "then re-apply that project's work-pattern tuning (do not blind-overwrite a tuned hook).")


if __name__ == "__main__":
    main()
