#!/usr/bin/env bash
# Clone or update dev-setup-codex from GitHub, then install it on Mac/Linux.

set -euo pipefail

REPO_URL="${REPO_URL:?Set REPO_URL to your chosen distribution repository}"
TARGET="${TARGET:-$HOME/dev/dev-setup-codex-community}"

if [[ -d "$TARGET" ]]; then
    if [[ ! -d "$TARGET/.git" ]]; then
        echo "Target exists but is not a git clone: $TARGET" >&2
        exit 1
    fi
    if [[ -n $(git -C "$TARGET" status --porcelain) ]]; then
        echo "Target clone is dirty -- aborting bootstrap update before pull/install: $TARGET" >&2
        echo "Commit/stash changes first, or run scripts/install-mac.sh directly if you intentionally want a dirty working-tree install." >&2
        exit 1
    fi
    git -C "$TARGET" pull --ff-only
else
    mkdir -p "$(dirname "$TARGET")"
    git clone "$REPO_URL" "$TARGET"
fi

bash "$TARGET/scripts/install-mac.sh" "$@"
