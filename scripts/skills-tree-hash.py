#!/usr/bin/env python3
"""Hash a target skill tree for a given manifest."""
import subprocess
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 3:
        print("usage: skills-tree-hash.py <skills-root> <manifest-file>", file=sys.stderr)
        return 2
    return subprocess.run([sys.executable, str(Path(__file__).with_name("setup-check.py")),
                           "--hash-tree", *sys.argv[1:]]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
