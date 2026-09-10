#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import shutil


def bash_shell() -> str | None:
    candidates: list[Path] = []
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            for root in list(Path(git).resolve().parents)[:4]:
                candidates.extend((root / "usr" / "bin" / "bash.exe",
                                   root / "bin" / "bash.exe"))
    found = shutil.which("bash")
    if found:
        candidates.append(Path(found))
    system_root = os.environ.get("SystemRoot")
    for candidate in candidates:
        resolved = candidate.resolve()
        if os.name == "nt" and system_root:
            windows = Path(system_root).resolve()
            if resolved == windows or windows in resolved.parents:
                continue
        if resolved.is_file():
            return str(resolved)
    return None
