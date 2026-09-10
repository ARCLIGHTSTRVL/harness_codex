#!/usr/bin/env python3
"""Select and prepare the repository-local Python dependency runtime."""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

MIN_VERSION = (3, 11)
NAME_SURROGATE = 0x20000000
PROBE_MARKER = "DEV_SETUP_RUNTIME_PROBE="
PROBE_TIMEOUT = 15


def _absolute(path):
    return Path(os.path.abspath(os.fspath(path)))


def _same_lexical_path(left, right):
    return os.path.normcase(os.fspath(_absolute(left))) == os.path.normcase(os.fspath(_absolute(right)))


def _is_link(st):
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_reparse_tag", 0) & NAME_SURROGATE)


def _lstat(path, label, kind, allow_symlink=False):
    try:
        value = os.lstat(path)
    except OSError as exc:
        raise RuntimeError(f"{label} could not be inspected ({type(exc).__name__}: {exc})") from exc
    if _is_link(value) and not allow_symlink:
        raise RuntimeError(f"{label} must not be a link: {path}")
    if kind == "directory" and not stat.S_ISDIR(value.st_mode):
        raise RuntimeError(f"{label} is not a directory: {path}")
    if kind == "file" and not (stat.S_ISREG(value.st_mode) or (allow_symlink and stat.S_ISLNK(value.st_mode))):
        raise RuntimeError(f"{label} is not a file: {path}")
    return value


def _validate_path_chain(path, label):
    path = _absolute(path)
    current = Path(path.anchor)
    _lstat(current, label, "directory")
    for part in path.parts[1:]:
        current /= part
        _lstat(current, label, "directory")


def _validate_runtime_tree(runtime):
    scripts = runtime / ("Scripts" if os.name == "nt" else "bin")
    pending = [runtime]
    while pending:
        current = pending.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise RuntimeError(f".runtime could not be inspected ({type(exc).__name__}: {exc})") from exc
        for entry in entries:
            path = Path(entry.path)
            try:
                value = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise RuntimeError(f".runtime could not be inspected ({type(exc).__name__}: {exc})") from exc
            linked = _is_link(value)
            allowed_executable_link = (
                os.name != "nt" and path.parent == scripts and path.name.startswith("python")
                and stat.S_ISLNK(value.st_mode)
            )
            allowed_lib_alias = False
            if os.name != "nt" and path.parent == runtime and path.name == "lib64" and stat.S_ISLNK(value.st_mode):
                try:
                    target = path.parent / os.readlink(path)
                except OSError as exc:
                    raise RuntimeError(f".runtime/lib64 could not be inspected ({type(exc).__name__}: {exc})") from exc
                allowed_lib_alias = _same_lexical_path(target, runtime / "lib")
                if allowed_lib_alias:
                    _lstat(runtime / "lib", ".runtime/lib", "directory")
            if linked and not (allowed_executable_link or allowed_lib_alias):
                raise RuntimeError(f".runtime must not contain linked paths: {path}")
            if stat.S_ISDIR(value.st_mode) and not linked:
                pending.append(path)


def probe_python(executable):
    executable = _absolute(executable)
    source = (
        "import json,os,sys\n"
        "try:\n"
        " import yaml\n"
        " has_yaml=True\n"
        "except Exception:\n"
        " has_yaml=False\n"
        f"print({PROBE_MARKER!r}+json.dumps({{"
        "'executable':os.path.abspath(sys.executable),"
        "'prefix':os.path.abspath(sys.prefix),"
        "'base_prefix':os.path.abspath(sys.base_prefix),"
        "'version':list(sys.version_info[:3]),'has_yaml':has_yaml}))"
    )
    try:
        result = subprocess.run(
            [str(executable), "-I", "-c", source], capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False, timeout=PROBE_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Python probe timed out after {PROBE_TIMEOUT}s: {executable}") from exc
    except OSError as exc:
        raise RuntimeError(f"Python is not runnable: {executable} ({type(exc).__name__}: {exc})") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"Python probe failed for {executable}: {detail or f'exit {result.returncode}'}")
    lines = [line[len(PROBE_MARKER):] for line in result.stdout.splitlines()
             if line.startswith(PROBE_MARKER)]
    if len(lines) != 1:
        raise RuntimeError(f"Python probe returned an invalid response: {executable}")
    try:
        probe = json.loads(lines[0])
        version = tuple(probe["version"])
        probe["version"] = version
        probe["has_yaml"] = probe["has_yaml"] is True
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Python probe returned an invalid response: {executable}") from exc
    if not _same_lexical_path(probe["executable"], executable):
        raise RuntimeError(
            f"Python executable identity changed during probing: {executable} -> {probe['executable']}"
        )
    probe["executable"] = str(executable)
    return probe


def validate_python(executable, require_yaml=True):
    probe = probe_python(executable)
    if probe["version"] < MIN_VERSION:
        raise RuntimeError(f"Python 3.11+ is required: {probe['executable']}")
    if require_yaml and not probe["has_yaml"]:
        raise RuntimeError(f"PyYAML is unavailable: {probe['executable']}")
    return Path(probe["executable"])


def _runtime_python(repo):
    runtime = _absolute(repo) / ".runtime"
    if not os.path.lexists(runtime):
        return runtime, None
    _lstat(runtime, ".runtime", "directory")
    config = runtime / "pyvenv.cfg"
    scripts = runtime / ("Scripts" if os.name == "nt" else "bin")
    executable = scripts / ("python.exe" if os.name == "nt" else "python")
    _lstat(config, ".runtime/pyvenv.cfg", "file")
    _lstat(scripts, ".runtime interpreter directory", "directory")
    _lstat(executable, ".runtime interpreter", "file", allow_symlink=os.name != "nt")
    _validate_runtime_tree(runtime)
    probe = probe_python(executable)
    if probe["version"] < MIN_VERSION:
        raise RuntimeError(f".runtime requires Python 3.11+: {executable}")
    if not _same_lexical_path(probe["prefix"], runtime):
        raise RuntimeError(f".runtime interpreter has the wrong environment prefix: {probe['prefix']}")
    return runtime, probe


def select_python(repo, apply=False, executable=None):
    repo = _absolute(repo)
    _validate_path_chain(repo, "repository runtime parent")
    runtime, runtime_probe = _runtime_python(repo)
    base = _absolute(executable or sys.executable)
    if runtime_probe is not None and _same_lexical_path(base, runtime_probe["executable"]):
        base_probe = runtime_probe
    else:
        base_probe = probe_python(base)
    if base_probe["version"] < MIN_VERSION:
        raise RuntimeError(f"Python 3.11+ is required: {base}")
    active_environment = not _same_lexical_path(base_probe["prefix"], base_probe["base_prefix"])
    if base_probe["has_yaml"] and active_environment:
        return base
    if runtime_probe is not None and runtime_probe["has_yaml"]:
        return Path(runtime_probe["executable"])
    if base_probe["has_yaml"]:
        return base
    if not apply:
        return base
    if runtime_probe is None:
        subprocess.run([str(base), "-m", "venv", str(runtime)], check=True)
        runtime, runtime_probe = _runtime_python(repo)
    runtime_python = Path(runtime_probe["executable"])
    requirements = repo / "requirements.txt"
    _lstat(requirements, "requirements.txt", "file")
    install_env = os.environ.copy()
    for name in ("PIP_PREFIX", "PIP_ROOT", "PIP_TARGET", "PIP_USER", "PYTHONUSERBASE"):
        install_env.pop(name, None)
    install_env["PIP_CONFIG_FILE"] = os.devnull
    install_env["PIP_REQUIRE_VIRTUALENV"] = "1"
    install_env["PYTHONNOUSERSITE"] = "1"
    install_env["VIRTUAL_ENV"] = str(runtime)
    subprocess.run(
        [str(runtime_python), "-m", "pip", "install", "-r", str(requirements)],
        check=True, env=install_env,
    )
    return validate_python(runtime_python)


def run(repo, argv, apply=False, executable=None):
    selected = select_python(repo, apply=apply, executable=executable)
    print(f"Runtime Python: {selected}", flush=True)
    return subprocess.run([str(selected), *map(str, argv)]).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a Python script or interpreter argument is required after --")
    return run(args.repo, command, apply=args.apply)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
