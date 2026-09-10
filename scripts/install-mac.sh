#!/usr/bin/env bash
# dev-setup-codex installer (Mac) -- bootstrap only.
#
# Usage: bash scripts/install-mac.sh [--force] [--dry-run]
#
# Resolves a Python 3 and hands the whole install to scripts/install.py, which
# owns every step and every rule for both platforms. This file used to carry a
# second implementation of all of it in bash, and each divergence between the
# two decided a file's fate differently in the two domains the install has to
# keep identical.
#
# Nothing here may grow a rule. A rule added here is a rule spelled twice
# again, and test_install_engine.py fails on the vocabulary of one appearing in
# this file at all.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
FORCE=0
PREVIEW=0

for arg in "$@"; do
    case "$arg" in
        --force|-f) FORCE=1 ;;
        --dry-run) PREVIEW=1 ;;
        *)
            echo "Unknown option: $arg" >&2
            echo "Usage: bash scripts/install-mac.sh [--force] [--dry-run]" >&2
            exit 2 ;;
    esac
done

# ONE resolution order for the whole harness: python, python3, py. `python` first so an
# active venv wins -- this installer used to try `python3` only, so a Mac working inside
# a venv installed hooks pointing at the SYSTEM interpreter while every other entry
# point used the venv's. Keep this generic order identical to githooks/pre-commit,
# templates/hooks/stop-handoff-gate.sh and scripts/install-windows.ps1.
# The Git gate also checks managed Homebrew paths for bare SSH environments.
py=""
for cand in python python3 py; do
    command -v "$cand" >/dev/null 2>&1 || continue
    supported=$("$cand" -c 'import sys; print(int(sys.version_info >= (3, 11)))' 2>/dev/null) || continue
    if [[ "$supported" == "1" ]]; then py="$cand"; break; fi
done
if [[ -z "$py" ]]; then
    echo "No runnable Python 3.11+ found (tried: python, python3, py). Install Python 3.11+ and retry." >&2
    exit 1
fi
PYTHON_CMD=$("$py" -c 'import os,sys; print(os.path.abspath(sys.executable))')
if [[ -z "$PYTHON_CMD" || ! -x "$PYTHON_CMD" ]]; then
    echo "Python 3.11+ executable could not be resolved. Install Python 3.11+ and retry." >&2
    exit 1
fi

engine_args=(install --home "$HOME" --repo "$REPO" --platform mac)
if [[ $FORCE -eq 1 ]]; then engine_args+=(--force); fi
if [[ $PREVIEW -eq 1 ]]; then engine_args+=(--dry-run); fi
runtime_args=(--repo "$REPO")
if [[ $PREVIEW -eq 0 ]]; then runtime_args+=(--apply); fi
runtime_args+=(-- "$REPO/scripts/install.py" "${engine_args[@]}")

# set -e propagates the engine's exit status; it has already printed its reason.
"$PYTHON_CMD" "$REPO/scripts/runtime.py" "${runtime_args[@]}"
