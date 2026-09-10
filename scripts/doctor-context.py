#!/usr/bin/env python3
import os
import subprocess
import sys
from typing import Literal


def check(root: str) -> tuple[bool | Literal["advisory"], str]:
    engine = os.path.join(root, "scripts", "context-cost.py")
    if not os.path.isfile(engine):
        return True, "contracts unmeasurable: scripts/context-cost.py is missing"
    try:
        result = subprocess.run([sys.executable, engine, "--check"], cwd=root,
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return True, f"context-cost.py could not run: {exc}"
    overs = [line.split() for line in result.stdout.splitlines() if "OVER:" in line]
    blocks = [row[0] for row in overs if len(row) > 2 and row[2] == "block"]
    if result.returncode == 1 and blocks:
        return True, "block-tier contract violated: " + ", ".join(blocks)
    if result.returncode != 0:
        return True, "context-cost.py errored: " + (result.stderr or result.stdout)[-500:]
    if blocks:
        return True, "inconsistent context-cost.py result: block OVER with exit 0"
    if overs:
        return "advisory", "warn-tier artifacts over budget: " + ", ".join(row[0] for row in overs)
    return False, "within contracts"
