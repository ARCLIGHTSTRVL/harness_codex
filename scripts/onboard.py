"""Check the recipient environment, then preview or apply with an isolated dependency runtime."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

import runtime

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    py = runtime.select_python(ROOT)
    has_yaml = runtime.probe_python(py)["has_yaml"]
    git = shutil.which("git")
    bash = Path(os.environ.get("OMO_CODEX_GIT_BASH_PATH", str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"))) if os.name == "nt" else shutil.which("bash")
    print("Python: " + str(py))
    print("PyYAML: " + ("ready" if has_yaml else "will install into .runtime on --apply"))
    print("Git: " + (git or "missing; install Git for project freshness/hooks"))
    print("Bash: " + (str(bash) if bash and (os.name != "nt" or bash.is_file()) else "missing; install Git Bash"))
    print("Codex CLI: " + (shutil.which("codex") or "not on PATH; CLI consultations/catalog discovery unavailable"))
    if not git or not bash or (os.name == "nt" and not bash.is_file()):
        return 1
    platform = "windows" if os.name == "nt" else "mac"
    command = [str(ROOT / "scripts/install.py"), "install" if args.apply else "preview",
               "--home", str(Path.home()), "--repo", str(ROOT), "--platform", platform]
    code = runtime.run(ROOT, command, apply=args.apply)
    if code or not args.apply:
        return code
    return runtime.run(ROOT, [str(ROOT / "scripts/setup-check.py"), "--repo", str(ROOT)])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
