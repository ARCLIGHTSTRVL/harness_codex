#!/usr/bin/env bash
# Pull latest from remote and re-apply (Mac).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$REPO"

if git_root=$(git rev-parse --show-toplevel); then
    git_root=$(cd -P -- "$git_root" && pwd)
else
    code=$?
    echo "Unable to identify the Git root (exit $code) -- aborting before sync." >&2
    exit 1
fi
if [[ "$git_root" != "$REPO" ]]; then
    echo "Git root does not match sync source -- aborting before status/pull/install." >&2
    echo "Git root: $git_root" >&2
    echo "Sync source: $REPO" >&2
    exit 1
fi

if dirty=$(git status --porcelain --untracked-files=all); then
    :
else
    code=$?
    echo "git status failed (exit $code) -- aborting before sync." >&2
    exit 1
fi
if [[ -n "$dirty" ]]; then
    echo "Working tree is dirty -- aborting sync before pull/install." >&2
    echo "Commit/stash changes first, or run the installer directly if you intentionally want a dirty working-tree install." >&2
    exit 1
fi

echo "=== git pull ==="
git pull --ff-only

echo
echo "=== install ==="
bash "$REPO/scripts/install-mac.sh" "$@"
