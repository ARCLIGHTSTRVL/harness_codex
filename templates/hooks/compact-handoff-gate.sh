#!/bin/bash
# bootstrap-hooks v6
# PreCompact handoff gate (Codex-native): automatic compaction can happen before
# the agent decides to stop, so give the model one chance per session to update
# NEXT.md before context is summarized.
# Cross-platform: invoked via `bash` from .codex/hooks.json.
set -uo pipefail
INPUT=$(cat)

json_out() {
  "$PY" -I -c 'import json,sys; print(json.dumps({"continue": False, "stopReason": sys.stdin.read().strip()}))' 2>/dev/null
}

PY=""
for c in python python3 py; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -I -c '' >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -z "$PY" ] && exit 0

SID=$(printf '%s' "$INPUT" | "$PY" -I -c "import sys,json; print(json.loads(sys.stdin.read()).get('session_id',''))" 2>/dev/null) || exit 0
case "$SID" in *[!A-Za-z0-9._-]*) SID="" ;; esac
[ -z "$SID" ] && exit 0

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

SENT="$ROOT/.codex/.compact-warned-${SID}"
[ -f "$SENT" ] && exit 0

PORC=$(mktemp 2>/dev/null) || exit 0
git -c core.quotePath=false status --porcelain=v1 -z >"$PORC" 2>/dev/null || { rm -f "$PORC"; exit 0; }
WORK=""; NEXT_TOUCHED=""; SKIP=""
while IFS= read -r -d '' rec; do
  if [ -n "$SKIP" ]; then SKIP=""; continue; fi
  case "$rec" in
    [RC]?\ *|?[RC]\ *) SKIP=1 ;;
  esac
  p=${rec#???}
  [ "$p" = "NEXT.md" ] && NEXT_TOUCHED=1
  # TUNE PER PROJECT: same work-pattern gate as stop-handoff-gate.sh.
  case "$p" in
    workflow/*|scripts/*|src/*|app/*|lib/*|tests/*|test/*|docs/*|.github/*|*.py|*.js|*.jsx|*.ts|*.tsx|*.rs|*.go|*.md|*.json|*.toml|*.yaml|*.yml|package.json|package-lock.json|pnpm-lock.yaml|yarn.lock|Cargo.toml|Cargo.lock|go.mod|go.sum|pyproject.toml|requirements*.txt|uv.lock|poetry.lock|Dockerfile|docker-compose*.yml) WORK="${WORK}  - ${p}"$'\n' ;;
  esac
done <"$PORC"
rm -f "$PORC"

[ -z "$WORK" ] && exit 0
NEXT_ISSUE=""
if [ -n "$NEXT_TOUCHED" ]; then
  if NEXT_ISSUE=$(next_lint_reason 2>/dev/null); then exit 0; fi
  [ -n "$NEXT_ISSUE" ] || NEXT_ISSUE="NEXT.md schema check failed"
fi
( umask 077; : > "$SENT" ) 2>/dev/null || exit 0

{
  echo "PreCompact gate: automatic compaction is about to summarize context, but this session changed:"
  printf '%s' "$WORK"
  if [ -n "$NEXT_TOUCHED" ]; then
    echo "NEXT.md was touched, but its handoff schema is not usable: $NEXT_ISSUE"
  fi
  echo "Update NEXT.md with the active unit, decisions, loaded context, risks, pointers, acceptance, and next action before compaction."
  echo "If no handoff update is needed, add a clear note in NEXT.md that preserves the required handoff shape."
  echo "This PreCompact gate will not block again in this session."
} | json_out
