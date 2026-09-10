"""Verify MSYS2 runtime layouts and Windows entrypoint behavior."""
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_runtime():
    spec = importlib.util.spec_from_file_location("msys_runtime", ROOT / "scripts/runtime.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(command, *, env=None, cwd=None, code=0, timeout=240):
    result = subprocess.run(
        list(map(str, command)), env=env, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if result.returncode != code:
        raise AssertionError(result.stdout + result.stderr)
    return result


def build_yaml_wheel(root):
    version = importlib.metadata.version("PyYAML")
    wheelhouse = root / "wheelhouse"
    wheelhouse.mkdir()
    wheel = wheelhouse / f"pyyaml-{version}-py3-none-any.whl"
    package = Path(yaml.__file__).resolve().parent
    dist_info = f"pyyaml-{version}.dist-info"
    names = []
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as bundle:
        for source in package.rglob("*.py"):
            name = source.relative_to(package.parent).as_posix()
            bundle.write(source, name)
            names.append(name)
        generated = {
            f"{dist_info}/METADATA": (
                "Metadata-Version: 2.1\nName: PyYAML\n" f"Version: {version}\n"
            ),
            f"{dist_info}/WHEEL": (
                "Wheel-Version: 1.0\nGenerator: msys-runtime-test\n"
                "Root-Is-Purelib: true\nTag: py3-none-any\n"
            ),
            f"{dist_info}/top_level.txt": "yaml\n",
        }
        for name, content in generated.items():
            bundle.writestr(name, content)
            names.append(name)
        record = "\n".join(f"{name},," for name in names + [f"{dist_info}/RECORD"])
        bundle.writestr(f"{dist_info}/RECORD", record + "\n")
    return wheelhouse


@unittest.skipUnless(os.name == "nt", "MSYS2 compatibility is Windows-specific")
class MsysRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="community-msys-runtime-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def make_bin_runtime(self):
        repo = self.root / "source"
        repo.mkdir()
        target = repo / ".runtime"
        run([sys.executable, "-m", "venv", "--system-site-packages", target])
        (target / "Scripts").rename(target / "bin")
        return repo, target / "bin/python.exe"

    def test_msys2_bin_runtime_is_reused_by_windows_cpython(self):
        runtime = load_runtime()
        repo, expected = self.make_bin_runtime()
        selected = runtime.select_python(repo, executable=sys.executable)
        self.assertEqual(selected, expected)
        self.assertIn(str(expected), run([selected, "-c", "import sys; print(sys.executable)"]).stdout)

    def test_ambiguous_runtime_layout_is_refused_before_probe(self):
        runtime = load_runtime()
        repo, alternate = self.make_bin_runtime()
        scripts = repo / ".runtime/Scripts"
        scripts.mkdir()
        shutil.copyfile(alternate, scripts / "python.exe")
        original = runtime.subprocess.run
        runtime.subprocess.run = lambda *args, **kwargs: self.fail("ambiguous runtime was executed")
        self.addCleanup(setattr, runtime.subprocess, "run", original)
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            runtime.select_python(repo, executable=sys.executable)

    def test_windows_wrapper_skips_posix_shadow_for_native_python(self):
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        marker = self.root / "unexpected-runtime.txt"
        (fake_bin / "python.cmd").write_text(
            "@echo off\n"
            "echo %* | %SystemRoot%\\System32\\findstr.exe /C:\"version_info\" >nul\n"
            "if not errorlevel 1 (echo 1& exit /b 0)\n"
            "echo %* | %SystemRoot%\\System32\\findstr.exe /C:\"os.name\" >nul\n"
            "if not errorlevel 1 (echo posix:cygwin& exit /b 0)\n"
            "echo %* | %SystemRoot%\\System32\\findstr.exe /C:\"sys.executable\" >nul\n"
            "if not errorlevel 1 (echo /usr/bin/python3.exe& exit /b 0)\n"
            f">\"{marker}\" echo invoked\nexit /b 91\n",
            encoding="ascii",
        )
        task_profile = self.root / "profile"
        env = {
            **os.environ,
            "PATH": str(fake_bin) + os.pathsep + str(Path(sys.executable).parent)
                    + os.pathsep + os.environ["PATH"],
            "HOME": str(task_profile),
            "USERPROFILE": str(task_profile),
            "CODEX_HOME": str(task_profile / ".codex"),
        }
        result = run([
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            ROOT / "scripts/install-windows.ps1",
        ], env=env)
        self.assertIn("Skipping MSYS POSIX Python", result.stdout + result.stderr)
        self.assertFalse(marker.exists())
        self.assertTrue((task_profile / ".codex/dev-setup-codex-community-state.json").is_file())

    @unittest.skipUnless(os.environ.get("MSYS2_UCRT_PYTHON"), "actual MSYS2 UCRT Python not configured")
    def test_actual_ucrt_python_installs_and_cross_checks(self):
        ucrt = Path(os.environ["MSYS2_UCRT_PYTHON"]).resolve()
        source = self.root / "recipient"
        shutil.copytree(
            ROOT, source,
            ignore=shutil.ignore_patterns(".git", ".runtime", "dist", "__pycache__", "*.pyc"),
        )
        task_profile = self.root / "profile"
        wheelhouse = build_yaml_wheel(self.root)
        env = {
            **os.environ,
            "PATH": str(ucrt.parent) + os.pathsep + os.environ["PATH"],
            "HOME": str(task_profile),
            "USERPROFILE": str(task_profile),
            "CODEX_HOME": str(task_profile / ".codex"),
            "PIP_FIND_LINKS": wheelhouse.as_uri(),
            "PIP_NO_INDEX": "1",
            "PYTHONUTF8": "1",
        }
        installed = run([
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            source / "scripts/install-windows.ps1",
        ], env=env)
        runtime_python = source / ".runtime/bin/python.exe"
        self.assertIn(f"Runtime Python: {runtime_python}", installed.stdout)
        self.assertTrue(runtime_python.is_file())
        self.assertFalse((source / ".runtime/Scripts/python.exe").exists())
        state = json.loads((task_profile / ".codex/dev-setup-codex-community-state.json")
                           .read_text(encoding="utf-8"))
        self.assertTrue(os.path.samefile(state["python_executable"], runtime_python))
        run([
            sys.executable, source / "scripts/setup-check.py", "--home", task_profile,
            "--repo", source,
        ], env=env)

    @unittest.skipUnless(os.environ.get("MSYS2_UCRT_PYTHON"), "actual MSYS2 UCRT Python not configured")
    def test_actual_ucrt_python_reuses_windows_runtime(self):
        ucrt = Path(os.environ["MSYS2_UCRT_PYTHON"]).resolve()
        source = self.root / "recipient"
        shutil.copytree(
            ROOT, source,
            ignore=shutil.ignore_patterns(".git", ".runtime", "dist", "__pycache__", "*.pyc"),
        )
        base = self.root / "windows-base"
        run([sys.executable, "-m", "venv", base])
        base_python = base / "Scripts/python.exe"
        task_profile = self.root / "profile"
        wheelhouse = build_yaml_wheel(self.root)
        env = {
            **os.environ,
            "PATH": str(base_python.parent) + os.pathsep + os.environ["PATH"],
            "HOME": str(task_profile),
            "USERPROFILE": str(task_profile),
            "CODEX_HOME": str(task_profile / ".codex"),
            "PIP_FIND_LINKS": wheelhouse.as_uri(),
            "PIP_NO_INDEX": "1",
            "PYTHONUTF8": "1",
        }
        run([
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            source / "scripts/install-windows.ps1",
        ], env=env)
        runtime_python = source / ".runtime/Scripts/python.exe"
        self.assertTrue(runtime_python.is_file())
        reused = run([
            ucrt, source / "scripts/runtime.py", "--repo", source, "--",
            source / "scripts/setup-check.py", "--home", task_profile, "--repo", source,
        ], env=env)
        self.assertIn(f"Runtime Python: {runtime_python}", reused.stdout)


if __name__ == "__main__":
    unittest.main()
