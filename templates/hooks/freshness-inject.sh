#!/bin/bash
# bootstrap-hooks v8
# Cold-start / post-compaction freshness check — generic project template.
# Reads NEXT.md, verifies it against git, injects a verdict at SessionStart
# (stdout is added to Codex's context).
# FAIL-CLOSED: any error or ambiguity => UNVERIFIED/STALE, never a false "FRESH"
# (a wrong "fresh" would suppress the re-derivation the agent should do).
# Verdict contract is shared with scripts/project-health.py — keep the two aligned
# (truth table: specs/freshness-detection-spine.md).
# Cross-platform: git-bash (Windows), bash (macOS/Linux). No project-specific content.
# Spec: dev-setup-codex/specs/project-bootstrap-continuity.md
# NOTE: unit_paths is a single space-separated frontmatter line; entries must not
#       contain spaces or glob metacharacters (globbing is disabled below; a glob/
#       space entry fails closed to STALE via the existence check).
set -uo pipefail
set -f                       # no glob expansion of unit_paths (e.g. *.py)
TRIAL=1                      # new project: frame FRESH as advisory. Flip to 0 once trusted.
INPUT=$(cat)
HOOK_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SRC=$(printf '%s' "$INPUT" | sed -n 's/.*"source"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)
PREFIX="[freshness${SRC:+ source=$SRC}]"

owner_marker() {
  printf '%s' "$INPUT" | "$PY" -I -c '
import datetime, hashlib, json, os, pathlib, stat, sys, tempfile
def safe(path):
    for part in reversed((path, *path.parents)):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError("linked observation path")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise OSError("hardlinked observation path")
def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate payload key")
        result[key] = value
    return result
try:
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        raise ValueError("payload too large")
    data = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(data, dict) or data.get("hook_event_name") != "SessionStart":
        sys.exit(0)
    sid, source, cwd = data.get("session_id"), data.get("source"), data.get("cwd")
    if not isinstance(sid, str) or not sid.strip() or len(sid) > 200 or source not in ("startup", "resume", "clear", "compact"):
        raise ValueError("invalid session identity")
    root = pathlib.Path(sys.argv[1]).resolve()
    if not isinstance(cwd, str) or not pathlib.Path(cwd).is_absolute() or not pathlib.Path(cwd).resolve().is_relative_to(root):
        raise ValueError("project correlation mismatch")
    home = pathlib.Path(os.environ.get("CODEX_HOME", str(pathlib.Path.home() / ".codex"))).expanduser().absolute()
    target = home / "dev-setup-codex/project-hook-marks" / (hashlib.sha256(str(root).encode()).hexdigest() + ".json")
    safe(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    safe(target)
    record = {"schema": 1, "owner": "project-sessionstart", "cwd": str(root), "session_id": sid,
              "emission": {"event": "SessionStart", "source": source, "status": "emitted",
                           "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                           "invocation": "unauthenticated-native-payload", "delivery": "unverified", "host_dispatch": "unverified"}}
    descriptor, name = tempfile.mkstemp(prefix=".owner-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(json.dumps(record).encode())
        safe(target)
        os.replace(name, target)
    finally:
        pathlib.Path(name).unlink(missing_ok=True)
except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
    print("project SessionStart observation UNVERIFIED: marker unavailable", file=sys.stderr)
' "$PLAN_ROOT"
}

emit() {
  msg=$1
  case "$msg" in
    "[freshness]"*) printf '%s%s\n' "$PREFIX" "${msg#\[freshness\]}" ;;
    *) printf '%s\n' "$msg" ;;
  esac
  PY=""
  for candidate in python python3 py; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -I -c '' >/dev/null 2>&1; then PY="$candidate"; break; fi
  done
  PLAN_ROOT="$PWD"
  if command -v cygpath >/dev/null 2>&1; then PLAN_ROOT=$(cygpath -w "$PLAN_ROOT"); fi
  if [ -n "$PY" ] && [ -n "${ROOT:-}" ]; then owner_marker; fi
  # SessionStart carries saved plan state. This is a local file read, not proof
  # that a PreCompact stdout payload survives Codex's compaction mechanism.
  PLAN_READER="$HOOK_DIR/plan-handoff.py"
  if [ -f "$PLAN_READER" ]; then
    if command -v cygpath >/dev/null 2>&1; then
      PLAN_READER=$(cygpath -w "$PLAN_READER")
    fi
    if [ -n "$PY" ]; then "$PY" -I "$PLAN_READER" "$PLAN_ROOT" || printf '%s\n' '[plan-handoff] reader failed; inspect workflow/plans/'
    else printf '%s\n' '[plan-handoff] Python unavailable; inspect workflow/plans/'; fi
  else
    printf '%s\n' '[plan-handoff] reader missing; copy templates/hooks/plan-handoff.py'
  fi
  exit 0
}
NL='
'

DIR="${CODEX_PROJECT_DIR:-$(pwd)}"
# normalize a Windows path to this bash's form (git-bash /c/..; WSL /mnt/c/..; no-op elsewhere)
case "$DIR" in
  [A-Za-z]:*|*\\*)
    if command -v cygpath >/dev/null 2>&1; then DIR=$(cygpath -u "$DIR" 2>/dev/null || printf '%s' "$DIR")
    elif command -v wslpath >/dev/null 2>&1; then DIR=$(wslpath -u "$DIR" 2>/dev/null || printf '%s' "$DIR"); fi
    ;;
esac
cd "$DIR" 2>/dev/null || emit "[freshness] NEXT UNVERIFIED - cannot enter project dir. Re-derive from workflow/status.md + recent */log.md."
ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || emit "[freshness] NEXT UNVERIFIED - not a git repo here. Re-derive from workflow/status.md."
cd "$ROOT" 2>/dev/null || emit "[freshness] NEXT UNVERIFIED - cannot enter repo root."
NEXT="$ROOT/NEXT.md"
[ -f "$NEXT" ] || emit "[freshness] No NEXT.md - no active handoff. Derive the next unit from workflow/status.md + recent */log.md, confirm with the user."

# frontmatter reader: first '---' block only; keeps everything after the first colon.
fm() { awk -v k="$1" '
  NR==1 && /^---[[:space:]]*$/ {infm=1; next}
  infm && /^---[[:space:]]*$/ {exit}
  infm { i=index($0,":"); if (i>0 && substr($0,1,i-1)==k) { v=substr($0,i+1); sub(/^[[:space:]]+/,"",v); print v; exit } }
' "$NEXT" | tr -d '\r'; }
LV=$(fm last_verified_commit | tr -d '[:space:]')
[ -n "$LV" ] || LV=$(fm last_verified | tr -d '[:space:]')   # fallback key (same pair as project-health.py)
LT=$(fm last_touched | tr -d '[:space:]')
WR=$(fm writer | tr -d '[:space:]')
UP=$(fm unit_paths)

[ -n "$LV" ] || emit "[freshness] NEXT.md has no last_verified_commit - cannot verify. Treat as stale; confirm next unit with the user."

schema_issue() {
  [ -n "$LT" ] || { echo "missing last_touched"; return; }
  case "$LT" in ????-??-??) ;; *) echo "last_touched must be YYYY-MM-DD"; return ;; esac
  [ -n "$WR" ] || { echo "missing writer"; return; }
  [ -n "$UP" ] || { echo "missing unit_paths"; return; }
  case " $UP " in *" NEXT.md "*) echo "unit_paths must not include root NEXT.md"; return ;; esac
  if grep -Eq '<(git-sha|YYYY-MM-DD|codex\|human\|other|space-separated|one concrete|what is|none \| exact blocker|file:line|wiki/page|knowledge/page|why it matters|observable|test/build|manual smoke|the next smallest|deferred gate)' "$NEXT"; then echo "template placeholders remain"; return; fi
  for marker in "## Active Unit" "Goal:" "Current state:" "Blocker:" "Pointers:" "Acceptance:" "## Next Action" "## Pending, Not This Unit"; do
    grep -Fq "$marker" "$NEXT" || { echo "missing $marker"; return; }
  done
  grep -Eq '^Goal:[[:space:]]+[^[:space:]]' "$NEXT" || { echo "Goal is empty"; return; }
}
SCHEMA_ISSUE=$(schema_issue)
[ -z "$SCHEMA_ISSUE" ] || emit "[freshness] NEXT UNVERIFIED - schema check failed: $SCHEMA_ISSUE. Re-derive from workflow/status.md + recent */log.md."

# age note (hint only, never flips the verdict). Portable: GNU date -d, else BSD date -j.
epoch() { date -d "$1" +%s 2>/dev/null || date -j -f '%Y-%m-%d' "${1%%T*}" +%s 2>/dev/null; }
AGE=""
if [ -n "$LT" ]; then
  N=$(date +%s 2>/dev/null); T=$(epoch "$LT")
  if [ -n "$N" ] && [ -n "$T" ]; then D=$(( (N - T) / 86400 )); [ "$D" -gt 7 ] && AGE=" (note: handoff ${D}d old - hint only.)"; fi
fi

# Check 0 (identity): a base SHA unknown to git is ambiguity (shallow clone / gc /
# typo), NOT proven divergence => UNVERIFIED, never STALE.
git rev-parse --verify --quiet "${LV}^{commit}" >/dev/null 2>&1 || emit "[freshness] NEXT UNVERIFIED - last_verified_commit $LV is unknown to this repo (shallow clone / gc / typo?). Re-derive from workflow/status.md + recent */log.md.${AGE}"

# Check 1 (ancestry): rebase/squash/force-push/branch-switch. Exit 1 = proven
# not-an-ancestor => STALE; any other failure = git error => UNVERIFIED.
git merge-base --is-ancestor "$LV" HEAD 2>/dev/null
case $? in
  0) ;;
  1) emit "[freshness] NEXT STALE - last_verified_commit $LV is not an ancestor of HEAD (rebase/squash/force-push/branch switch). Do NOT trust NEXT's pointers; re-derive from workflow/status.md + git log --oneline -20, confirm with the user.${AGE}" ;;
  *) emit "[freshness] NEXT UNVERIFIED - git error while checking ancestry. Re-derive from workflow/status.md.${AGE}" ;;
esac

# A git failure must fail closed, not read as "clean".
DIRTY_RAW=$(git -c core.quotePath=false status --porcelain 2>/dev/null) || emit "[freshness] NEXT UNVERIFIED - git status failed. Re-derive from workflow/status.md.${AGE}"

# Drop our own tooling-state files from the dirt (same set as project-health.py
# _is_tooling_state); rename/copy records are real work and are never dropped.
DIRTY=""
while IFS= read -r ln; do
  [ -n "$ln" ] || continue
  p=${ln#???}; p=${p#\"}; p=${p%\"}
  case "$ln" in
    [RC]?\ *|?[RC]\ *) ;;                      # rename/copy = real work, keep
    *) case "$p" in
         .codex/.last-doctor|.codex/.last-health) continue ;;
         .codex/.stop-warned*) case "${p#.codex/}" in */*) ;; *) continue ;; esac ;;
         .codex/.compact-warned*) case "${p#.codex/}" in */*) ;; *) continue ;; esac ;;
       esac ;;
  esac
  DIRTY="${DIRTY}${ln}${NL}"
done <<EOF
$DIRTY_RAW
EOF
DIRTY=${DIRTY%"$NL"}

# A FRESH verdict REQUIRES machine-readable unit_paths; without them the unit-change
# check cannot run, so we must not claim FRESH.
if [ -z "$UP" ]; then
  [ -n "$DIRTY" ] && emit "[freshness] NEXT UNVERIFIED - no unit_paths in frontmatter AND the tree is dirty:
$DIRTY
Verify the active unit's files and the diff manually.${AGE}"
  emit "[freshness] NEXT UNVERIFIED - frontmatter has no machine-readable unit_paths, so the unit-change check was skipped. Ancestor ok + tree clean, but confirm the active unit's files before trusting NEXT.${AGE}"
fi

# Check 2 (PRIMARY): unit paths missing now, or moved since last_verified?
for p in $UP; do
  [ -e "$p" ] || emit "[freshness] NEXT STALE - it points to '$p', which no longer exists at HEAD. Re-derive the unit; confirm with the user.${AGE}"
done

# Committed drift outranks uncommitted work, even when both are present.
DELTA=$(git log --oneline "$LV..HEAD" -- $UP 2>/dev/null) || emit "[freshness] NEXT UNVERIFIED - git log failed on unit paths. Re-derive from workflow/status.md.${AGE}"
[ -n "$DELTA" ] && emit "[freshness] NEXT PARTIALLY STALE - the active unit's paths changed since $LV:
$DELTA
Re-verify those pointers before trusting NEXT's current-state claims.${AGE}"

# Dirty unit files are work in progress, not evidence of committed divergence.
touches_unit() {
  tp=$1; tp=${tp#\"}; tp=${tp%\"}
  for u in $UP; do
    u=${u%/}
    case "$tp" in "$u"|"$u"/*) return 0 ;; esac
  done
  return 1
}
UNIT_DIRT=""
while IFS= read -r ln; do
  [ -n "$ln" ] || continue
  p=${ln#???}; p=${p#\"}; p=${p%\"}
  case "$p" in
    *' -> '*) { touches_unit "${p%% -> *}" || touches_unit "${p#* -> }"; } && UNIT_DIRT=1 ;;
    *) touches_unit "$p" && UNIT_DIRT=1 ;;
  esac
done <<EOF
$DIRTY
EOF
[ -n "$UNIT_DIRT" ] && emit "[freshness] NEXT WIP - uncommitted work touches the active unit's paths:
$DIRTY
Expected mid-unit; at a cold start, review the diff before trusting NEXT's current-state claims.${AGE}"

# Cross-check broader project-state pointers. These do not flip FRESH to STALE:
# they surface semantic-staleness risk when workflow/wiki/knowledge state moved
# after the handoff even though the declared unit paths did not.
CTX_DELTA=$(git log --oneline --max-count=5 "$LV..HEAD" -- workflow/status.md workflow/README.md wiki/log.md wiki/index.md knowledge/log.md knowledge/index.md 2>/dev/null)

# All checks pass. Real dirt OUTSIDE the unit's paths never flips the verdict,
# but is surfaced as a WARN suffix.
WARN=""
[ -n "$DIRTY" ] && WARN="
WARN: working tree has uncommitted changes outside the unit's paths:
$DIRTY
Not unit work, but review before relying on a clean state."
[ -n "$CTX_DELTA" ] && WARN="${WARN}
WARN: project context files changed since this handoff:
$CTX_DELTA
Review workflow/status.md, wiki/log.md, or knowledge/log.md before relying on semantic freshness."
[ "$TRIAL" = "1" ] && emit "[freshness] NEXT looks FRESH @${LV} - advisory trial; glance at NEXT.md before proceeding.${AGE}${WARN}"
emit "[freshness] NEXT FRESH @${LV}.${AGE}${WARN}"
