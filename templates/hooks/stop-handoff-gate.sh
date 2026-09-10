#!/bin/bash
# bootstrap-hooks v6
# Stop handoff gate (bootstrap Candidate B) — generic project template.
# Blocks once per concern per session if real work happened this
# session but NEXT.md was not updated, or NEXT.md exceeds its line budget.
# FAIL-SAFE: never blocks unless it can also un-block, so a session
# can never be trapped in a Stop loop.
# Cross-platform: git-bash (Windows), bash (macOS/Linux).
# Spec: dev-setup-codex/specs/project-bootstrap-continuity.md
set -uo pipefail
INPUT=$(cat)

# Portable JSON parse: find a python that actually runs. Order matters — on Windows
# 'python' is the real one and 'python3' may be the broken Microsoft Store stub, so
# we test isolated execution (`-I -c ''`) and take the first that works.
PY=""
for c in python python3 py; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -I -c '' >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -z "$PY" ] && exit 0   # no JSON parser available => fail-safe, do not block

# F3 re-entry guard: already continuing from a stop-hook block => let it end.
ACTIVE=$(printf '%s' "$INPUT" | "$PY" -I -c "import sys,json; print(json.loads(sys.stdin.read()).get('stop_hook_active', False))" 2>/dev/null) || exit 0
[ "$ACTIVE" = "True" ] && exit 0
SID=$(printf '%s' "$INPUT" | "$PY" -I -c "import sys,json; print(json.loads(sys.stdin.read()).get('session_id',''))" 2>/dev/null) || exit 0
case "$SID" in *[!A-Za-z0-9._-]*) SID="" ;; esac

DIR="${CODEX_PROJECT_DIR:-$(pwd)}"
case "$DIR" in
  [A-Za-z]:*|*\\*)
    if command -v cygpath >/dev/null 2>&1; then DIR=$(cygpath -u "$DIR" 2>/dev/null || printf '%s' "$DIR")
    elif command -v wslpath >/dev/null 2>&1; then DIR=$(wslpath -u "$DIR" 2>/dev/null || printf '%s' "$DIR"); fi
    ;;
esac
cd "$DIR" 2>/dev/null || exit 0
ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$ROOT" 2>/dev/null || exit 0

next_lint_reason() {
  "$PY" -I - "$ROOT/NEXT.md" <<'PY'
import re, sys
path = sys.argv[1]
try:
    text = open(path, encoding="utf-8").read()
except Exception as e:
    print("NEXT.md unreadable: %s" % e)
    raise SystemExit(1)
lines = text.splitlines()
fm = {}
if lines and lines[0].strip() == "---":
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
issues = []
for key in ("last_verified_commit", "last_touched", "writer", "unit_paths"):
    if not fm.get(key):
        issues.append("missing %s" % key)
if fm.get("last_touched") and not re.match(r"^\d{4}-\d{2}-\d{2}$", fm["last_touched"]):
    issues.append("last_touched must be YYYY-MM-DD")
if "NEXT.md" in fm.get("unit_paths", "").split():
    issues.append("unit_paths must not include root NEXT.md")
if re.search(r"<(?:git-sha|YYYY-MM-DD|codex\|human\|other|space-separated|one concrete|what is|none \| exact blocker|file:line|wiki/page|knowledge/page|why it matters|observable|test/build|manual smoke|the next smallest|deferred gate)", text):
    issues.append("template placeholders remain")
for marker in ("## Active Unit", "Goal:", "Current state:", "Blocker:", "Pointers:", "Acceptance:", "## Next Action", "## Pending, Not This Unit"):
    if marker not in text:
        issues.append("missing %s" % marker)
if not re.search(r"(?m)^Goal:\s+\S", text):
    issues.append("Goal is empty")
if issues:
    print("; ".join(issues[:3]))
    raise SystemExit(1)
PY
}

# F3 sentinel: at most ONE nudge per session. (Empty session_id => fail-safe no-block:
# never risk a trap without a stable key.)
[ -z "$SID" ] && exit 0
SENT="$ROOT/.codex/.stop-warned-${SID}"

# This session's uncommitted work, INCLUDING untracked new files, NUL-safe and with
# path-quoting off so non-ASCII paths are not missed. The records go through a temp
# file, not `< <(...)`: process substitution is a syntax error under POSIX-mode sh
# (hooks.json invokes this script via `bash`).
HANDOFF_BLOCK=""
WORK=""; NEXT_TOUCHED=""; SKIP=""
NEXT_ISSUE=""
if [ ! -f "$SENT" ] && PORC=$(mktemp 2>/dev/null); then
git -c core.quotePath=false status --porcelain=v1 -z >"$PORC" 2>/dev/null
while IFS= read -r -d '' rec; do
  # rename/copy records (R*/C* in either status column) carry a SECOND NUL field —
  # the original path, with no status prefix. Consume it; only the new path counts.
  if [ -n "$SKIP" ]; then SKIP=""; continue; fi
  case "$rec" in
    [RC]?\ *|?[RC]\ *) SKIP=1 ;;
  esac
  p=${rec#???}                                # strip 2-char status + 1 space
  [ "$p" = "NEXT.md" ] && NEXT_TOUCHED=1       # exact repo-root NEXT.md only
  # --- TUNE PER PROJECT: which changed paths count as "real work" that should ---
  # --- advance NEXT.md. Keep this block aligned with compact-handoff-gate.sh. ---
  case "$p" in
    workflow/*|scripts/*|src/*|app/*|lib/*|tests/*|test/*|docs/*|.github/*|*.py|*.js|*.jsx|*.ts|*.tsx|*.rs|*.go|*.md|*.json|*.toml|*.yaml|*.yml|package.json|package-lock.json|pnpm-lock.yaml|yarn.lock|Cargo.toml|Cargo.lock|go.mod|go.sum|pyproject.toml|requirements*.txt|uv.lock|poetry.lock|Dockerfile|docker-compose*.yml) WORK="${WORK}  - ${p}"$'\n' ;;
  esac
  # --- end tune ---
done <"$PORC"
rm -f "$PORC"

if [ -n "$WORK" ]; then
  HANDOFF_BLOCK=1
  if [ -n "$NEXT_TOUCHED" ]; then
    if NEXT_ISSUE=$(next_lint_reason 2>/dev/null); then
      HANDOFF_BLOCK=""
    elif [ -z "$NEXT_ISSUE" ]; then
      NEXT_ISSUE="NEXT.md schema check failed"
    fi
  fi
fi
fi

# Each concern owns a sentinel, so resolving a handoff does not hide the budget.
NEXT_LINE_CAP=60
BSENT="$ROOT/.codex/.stop-warned-budget-${SID}"
BUDGET_BLOCK=""; NEXT_LINES=""
if [ ! -f "$BSENT" ] && [ -f "$ROOT/NEXT.md" ]; then
  NEXT_LINES=$(wc -l < "$ROOT/NEXT.md" 2>/dev/null | tr -d '[:space:]')
  case "$NEXT_LINES" in ''|*[!0-9]*) NEXT_LINES="" ;; esac
  if [ -n "$NEXT_LINES" ] && [ "$NEXT_LINES" -gt "$NEXT_LINE_CAP" ]; then BUDGET_BLOCK=1; fi
fi
if [ -n "$HANDOFF_BLOCK" ]; then
  ( umask 077; : > "$SENT" ) 2>/dev/null || HANDOFF_BLOCK=""
fi
if [ -n "$BUDGET_BLOCK" ]; then
  ( umask 077; : > "$BSENT" ) 2>/dev/null || BUDGET_BLOCK=""
fi
[ -z "$HANDOFF_BLOCK" ] && [ -z "$BUDGET_BLOCK" ] && exit 0

{
  if [ -n "$HANDOFF_BLOCK" ]; then
  echo "Stop gate: this session changed -"
  printf '%s' "$WORK"
  if [ -n "$NEXT_TOUCHED" ]; then
    echo "- and NEXT.md was touched, but its handoff schema is not usable: $NEXT_ISSUE"
  else
    echo "- but NEXT.md was not updated."
  fi
  echo "Advance NEXT.md with active unit / last_verified_commit / last_touched / pointers / acceptance,"
  echo "or add a clear note why no handoff change is needed, then end again."
  fi
  if [ -n "$BUDGET_BLOCK" ]; then
    echo "NEXT.md budget: ${NEXT_LINES} lines > cap ${NEXT_LINE_CAP}."
    echo "Move closed-unit results to knowledge, keep phase details in workflow/plans/, then end again."
  fi
  echo "(This will not re-block this session.)"
} >&2
exit 2
