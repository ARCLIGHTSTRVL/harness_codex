#!/usr/bin/env bash
# Clone or update dev-setup-codex from GitHub, then install it on Mac/Linux.

set -euo pipefail

REPO_URL="${REPO_URL:?Set REPO_URL to your chosen distribution repository}"
TARGET="${TARGET:-$HOME/dev/dev-setup-codex-community}"

if [[ -d "$TARGET" ]]; then
    target_root=$(cd -P -- "$TARGET" && pwd)
    if git_root=$(git -C "$TARGET" rev-parse --show-toplevel); then
        git_root=$(cd -P -- "$git_root" && pwd)
    else
        code=$?
        echo "Unable to identify the target Git root (exit $code) -- aborting before bootstrap update." >&2
        exit 1
    fi
    if [[ "$git_root" != "$target_root" ]]; then
        echo "Git root does not match bootstrap target -- aborting before status/pull/install." >&2
        echo "Git root: $git_root" >&2
        echo "Bootstrap target: $target_root" >&2
        exit 1
    fi
    if dirty=$(git -C "$TARGET" status --porcelain --untracked-files=all); then
        :
    else
        code=$?
        echo "git status failed (exit $code) -- aborting before bootstrap update." >&2
        exit 1
    fi
    if [[ -n "$dirty" ]]; then
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
