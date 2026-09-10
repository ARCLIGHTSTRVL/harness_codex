#!/usr/bin/env python3
"""doctor — consolidated deep health for the CURRENT project, on demand.

Runs the deterministic project checks the cheap session-start hook defers:
  - NEXT.md git-truth freshness   (reused from project-health)
  - bootstrap-hook version         (reused from project-health)
  - wiki-lint    (if wiki/SCHEMA.md)      -> installed codebase-wiki linter
  - kb-lint      (if knowledge/SCHEMA.md) -> installed research-kb linter
  - KR mirror    -> deferred (vault resolution interactive); run /knowledge-mirror

Every managed-project run records <project>/.codex/.last-doctor (ISO timestamp).
The marker records cadence, not cleanliness. Unresolved checks retain their
ATTENTION rows and exit 1; standing debt cannot permanently arm an overdue nag.

Fail-safe (per specs/freshness-detection-spine.md): any state it could NOT verify
(UNVERIFIED NEXT, no git, a linter that could not run or errored, a check that
threw) is ATTENTION, never silently folded into "All clear". Detection + machine
output only; fixing and semantic judgement stay with you + the agent.

Usage: python doctor.py [--help]
Exit: 0 = all checked items clean, 1 = attention needed, 2 = doctor itself failed.
"""
import os
import sys
import subprocess
import importlib.util
import datetime
import tempfile
import json
import re
from io import TextIOWrapper
from typing import TypeAlias

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ADVISORY = "advisory"
JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

if isinstance(sys.stdout, TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run(cmd, timeout=120, cwd=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except Exception as e:
        return None, "", str(e)


def find_script(rel):
    """Prefer sibling source skills; fall back to CODEX_HOME or ~/.codex."""
    installed_root = os.path.expanduser(os.environ.get("CODEX_HOME", "~/.codex"))
    for base in (os.path.join(REPO, "skills"), os.path.join(installed_root, "skills")):
        p = os.path.join(base, *rel.split("/"))
        if os.path.exists(p):
            return p
    return None


def tail(s, n=3):
    lines = [ln for ln in s.splitlines() if ln.strip()]
    return " | ".join(lines[-n:]) if lines else ""


def classify_wiki_issues(issues):
    return _load("doctor_wiki", os.path.join(HERE, "doctor-wiki.py")).classify_wiki_issues(issues)


def safe(label, fn):
    """Run a check; any exception becomes an ATTENTION row, never aborting the report."""
    try:
        att, text = fn()
        return (att, label, text)
    except Exception as e:
        return (True, label, "check errored: %s" % e)


def native_agents_status(root: str) -> tuple[bool, str]:
    code, out, err = run([sys.executable, os.path.join(HERE, "native-agent-contract.py"),
                          "status", "--cwd", root], timeout=15)
    if code != 0:
        return True, "UNVERIFIED: status helper failed (exit %s): %s" % (code, tail(err))
    try:
        data: JsonValue = json.loads(out)
    except (ValueError, RecursionError):
        return True, "UNVERIFIED: invalid status JSON"
    if not isinstance(data, dict):
        return True, "UNVERIFIED: status must be an object"
    state, detail = data.get("state"), data.get("code")
    if (not isinstance(state, str) or state not in ("FRESH", "UNSET", "STALE", "INVALID", "UNVERIFIED")
            or not isinstance(detail, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:+@-]{0,199}", detail)):
        return True, "UNVERIFIED: invalid status fields"
    completion = data.get("completion")
    fields = ("verified", "pending", "unregistered", "unverified", "mismatch", "damaged")
    if not isinstance(completion, dict):
        return True, state + ": completion summary UNVERIFIED"
    counts: dict[str, int] = {}
    for key in fields:
        value = completion.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return True, state + ": completion summary UNVERIFIED"
        counts[key] = value
    attention = any(counts[key] for key in fields if key != "verified")
    if type(completion.get("attention")) is not bool or completion["attention"] != attention:
        return True, state + ": completion summary inconsistent"
    details = ", ".join("%s=%s" % (key, counts[key]) for key in fields if counts[key])
    return state not in ("FRESH", "UNSET") or attention, state + ": " + detail + ("; " + details if details else "")


def atomic_write(path, text):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".lastdoc.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def main():
    args = sys.argv[1:]
    if args:
        if args in (["--help"], ["-h"]):
            print((__doc__ or "").strip())
            return 0
        print("doctor: unrecognized argument(s): %s" % " ".join(args), file=sys.stderr)
        return 2
    try:
        ph = _load("project_health", os.path.join(HERE, "project-health.py"))
        cwd = os.getcwd()
        root, git_ok = ph.find_root(cwd)
        name = os.path.basename(root) or root
        markers = [m for m in ph.MARKERS if os.path.exists(os.path.join(root, m))]
        if not markers:
            print("/doctor: %s -- NOT A MANAGED PROJECT (no NEXT.md / wiki/ / knowledge/)" % name)
            return 0
        py = sys.executable
        rows = []
        if not git_ok:
            rows.append((True, "git", "unavailable or not a repo; freshness cannot be verified"))

        # NEXT -- anything that is not FRESH is attention (incl. UNVERIFIED / no git)
        if os.path.exists(os.path.join(root, "NEXT.md")):
            if git_ok:
                def _next():
                    st, d = ph.check_next(root)
                    return (st not in ("FRESH", "WIP"), st + (": " + d if d else ""))
                rows.append(safe("NEXT", _next))
            else:
                rows.append((True, "NEXT", "UNVERIFIED: no git, cannot verify"))

        # bootstrap-hooks -- omit when the project has none (opt-in, absence != stale)
        def _hooks():
            hk = ph.check_hooks(root)
            if not hk:
                return (None, None)
            return (ph.hook_attention(hk), hk)
        rows.append(safe("bootstrap-hooks", _hooks))
        rows.append(safe("hook-executable", lambda: (
            bool(detail := ph.check_hook_exec(root)), detail)))

        def _external():
            external = _load("external_review", os.path.join(HERE, "external-review.py"))
            ok, detail = external.status_all(root)
            return (not ok, detail)
        rows.append(safe("external-review", _external))
        rows.append(safe("native-agents", lambda: native_agents_status(root)))

        if os.path.isfile(os.path.join(root, "workflow", "context-contracts.yml")):
            checks = _load("doctor_context", os.path.join(HERE, "doctor-context.py"))
            rows.append(safe("context-budget", lambda: checks.check(root)))

        if os.path.exists(os.path.join(root, "wiki", "SCHEMA.md")):
            def _wiki():
                wl = find_script("codebase-wiki/scripts/wiki-lint.py")
                if not wl:
                    return (True, "linter script not found")
                code, out, err = run([py, wl, os.path.join(root, "wiki"), "--json"])
                if code is None:
                    return (True, "could not run: " + err)        # fail-safe: attention
                if code not in (0, 1):
                    return (True, "error -> " + (tail(err or out) or ("exit %s" % code)))
                try:
                    issues = json.loads(out)
                except json.JSONDecodeError as exc:
                    return (True, "invalid linter JSON: %s" % exc)
                if not isinstance(issues, list):
                    return (True, "invalid linter JSON: root is not an array")
                return classify_wiki_issues(issues)
            rows.append(safe("wiki-lint", _wiki))

        kb_present = os.path.exists(os.path.join(root, "knowledge", "SCHEMA.md"))
        if kb_present:
            def _kb():
                kl = find_script("research-kb/scripts/kb-lint.py")
                if not kl:
                    return (True, "linter script not found")
                code, out, err = run([py, kl, os.path.join(root, "knowledge")])
                if code is None:
                    return (True, "could not run: " + err)        # fail-safe: attention
                if code == 0:
                    return (False, "clean")
                if code == 1:
                    return (True, "issues -> " + (tail(out) or "see `kb-lint`"))
                return (True, "error -> " + (tail(err or out) or ("exit %s" % code)))
            rows.append(safe("kb-lint", _kb))

        # Debt age and archive damage use separate advisory/attention channels.
        frag_lines = None
        if os.path.isdir(os.path.join(root, "knowledge", "_fragments")):
            df = find_script("knowledge-fragment/scripts/deltas-for.py")
            if not df:
                frag_lines = ["deltas-for script not found -- consolidation debt not counted"]
                rows.append((True, "fragment-debt", "debt cannot be measured: script missing"))
            else:
                code, out, err = run([py, df, os.path.join(root, "knowledge"), "--debt"])
                if code != 0:
                    frag_lines = ["could not run deltas-for --debt: "
                                  + (tail(err or out) or ("exit %s" % code))]
                    rows.append((True, "fragment-debt", "debt cannot be measured"))
                else:
                    debt = _load("doctor_fragments", os.path.join(HERE, "doctor-fragments.py"))
                    frag_lines, debt_rows = debt.report(out.splitlines(), err)
                    rows.extend(debt_rows)

        rows = [r for r in rows if r[2] is not None]   # drop omitted (e.g. no hooks)
        attention = [r for r in rows if r[0] is True]
        advisory = [r for r in rows if r[0] == "advisory"]

        try:
            atomic_write(os.path.join(root, ".codex", ".last-doctor"),
                         datetime.datetime.now().isoformat())
            recorded = "recorded .codex/.last-doctor (last run, not last clean run)"
        except OSError as e:
            recorded = "WARN: could not record .last-doctor (%s)" % e
            rows.append((True, "doctor-stamp", recorded))
            attention = [r for r in rows if r[0] is True]

        print("=== /doctor: %s ===" % name)
        for att, label, text in rows:
            print("  %s%-16s %s" % ("!! " if att is True else "~~ " if att else "   ", label, text))
        if frag_lines is not None:
            print("  KNOWLEDGE FRAGMENTS (consolidation debt):")
            for ln in frag_lines:
                print("    " + ln)
        print("")
        if attention:
            print("ATTENTION (%d): %s" % (len(attention), ", ".join(l for _, l, _ in attention)))
        else:
            print("All clear of what was checked (deterministic, within coverage).")
        if advisory:
            print("ADVISORY (%d): %s" % (len(advisory), ", ".join(l for _, l, _ in advisory)))
        if kb_present:
            print("not checked here: KR mirror -> run /knowledge-mirror (vault resolution interactive)")
        print("%s  [semantic review -- is the content actually correct? -- is still yours]" % recorded)
        print("harness-wide drift -> /setup-check (install) and /bootstrap-doctor (hook versions)")
        return 1 if attention else 0
    except Exception as e:
        # No-silent-skip for the command itself: a total failure is still visible.
        print("/doctor FAILED to run (%s)" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
