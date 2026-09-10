#!/usr/bin/env bash
# Pull latest from remote and re-apply (Mac).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

if [[ -n $(git status --porcelain) ]]; then
    echo "Working tree is dirty -- aborting sync before pull/install." >&2
    echo "Commit/stash changes first, or run the installer directly if you intentionally want a dirty working-tree install." >&2
    exit 1
fi

echo "=== git pull ==="
git pull --ff-only

echo
echo "=== install ==="
bash "$REPO/scripts/install-mac.sh" "$@"
