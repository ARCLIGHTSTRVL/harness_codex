"""Check the recipient environment, then preview or apply with an isolated dependency runtime."""
import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error("Python 3.11+ is required; install it and retry")
    py = sys.executable
    has_yaml = importlib.util.find_spec("yaml") is not None
    git = shutil.which("git")
    bash = Path(os.environ.get("OMO_CODEX_GIT_BASH_PATH", str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"))) if os.name == "nt" else shutil.which("bash")
    print("Python: " + py)
    print("PyYAML: " + ("ready" if has_yaml else "will install into .runtime on --apply"))
    print("Git: " + (git or "missing; install Git for project freshness/hooks"))
    print("Bash: " + (str(bash) if bash and (os.name != "nt" or bash.is_file()) else "missing; install Git Bash"))
    print("Codex CLI: " + (shutil.which("codex") or "not on PATH; CLI consultations/catalog discovery unavailable"))
    if not git or not bash or (os.name == "nt" and not bash.is_file()):
        return 1
    if args.apply and not has_yaml:
        runtime = ROOT / ".runtime"
        if runtime.exists():
            runtime_py = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            if not runtime_py.is_file() or not (runtime / "pyvenv.cfg").is_file():
                raise ValueError(".runtime is not a virtual environment; inspect it before retrying")
        else:
            subprocess.run([py, "-m", "venv", str(runtime)], check=True)
        py = str(runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
        subprocess.run([py, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")], check=True)
    platform = "windows" if os.name == "nt" else "mac"
    command = [py, str(ROOT / "scripts/install.py"), "install" if args.apply else "preview",
               "--home", str(Path.home()), "--repo", str(ROOT), "--platform", platform]
    code = subprocess.run(command).returncode
    if code or not args.apply:
        return code
    return subprocess.run([py, str(ROOT / "scripts/setup-check.py"), "--repo", str(ROOT)]).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
