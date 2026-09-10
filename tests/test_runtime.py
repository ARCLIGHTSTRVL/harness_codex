"""Verify dependency-runtime selection, safety, and wrapper continuity."""
import importlib.metadata
import importlib.util
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


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = load("runtime_support", ROOT / "scripts/runtime.py")


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="community runtime ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def run_command(self, command, env=None, code=0, timeout=180, cwd=None):
        result = subprocess.run(
            list(map(str, command)), env=env, cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def make_venv(self, name, system_site_packages=False):
        target = self.root / name
        command = [sys.executable, "-m", "venv"]
        if system_site_packages:
            command.append("--system-site-packages")
        command.append(target)
        self.run_command(command)
        return target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def build_wheel(self):
        version = importlib.metadata.version("PyYAML")
        wheelhouse = self.root / "wheelhouse"
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
                    "Metadata-Version: 2.1\nName: PyYAML\n"
                    f"Version: {version}\n"
                ),
                f"{dist_info}/WHEEL": (
                    "Wheel-Version: 1.0\nGenerator: runtime-test\n"
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

    def runtime_command(self, python, repo, *command, apply=False, env=None, code=0):
        argv = [python, ROOT / "scripts/runtime.py", "--repo", repo]
        if apply:
            argv.append("--apply")
        argv.extend(["--", *command])
        return self.run_command(argv, env=env, code=code)

    def test_preview_without_yaml_is_read_only(self):
        repo = self.root / "source"
        shutil.copytree(
            ROOT, repo,
            ignore=shutil.ignore_patterns(".git", ".runtime", "dist", "__pycache__", "*.pyc"),
        )
        base = self.make_venv("base")
        self.run_command([base, "-I", "-c", "import yaml"], code=1)
        home = self.root / "profile"
        env = {
            **os.environ,
            "USERPROFILE": str(home),
            "HOME": str(home),
            "CODEX_HOME": str(home / ".codex"),
            "PYTHONUTF8": "1",
        }
        result = self.run_command([base, repo / "scripts/onboard.py"], env=env)
        self.assertIn("Preview only", result.stdout)
        self.assertFalse((repo / ".runtime").exists())
        self.assertFalse(home.exists())

    def test_invalid_runtime_refuses_without_overwrite(self):
        repo = self.root / "source"
        invalid = repo / ".runtime"
        invalid.mkdir(parents=True)
        sentinel = invalid / "owned.txt"
        sentinel.write_bytes(b"preserve me")
        base = self.make_venv("base")
        result = self.runtime_command(base, repo, "-c", "print('unexpected')", apply=True, code=1)
        self.assertIn(".runtime/pyvenv.cfg", result.stderr)
        self.assertEqual(sentinel.read_bytes(), b"preserve me")
        self.assertEqual(sorted(path.name for path in invalid.iterdir()), ["owned.txt"])

    def test_linked_repository_parent_is_refused_before_runtime_creation(self):
        actual = self.root / "actual"
        actual.mkdir()
        linked = self.root / "linked"
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(actual), str(linked))
        else:
            os.symlink(actual, linked, target_is_directory=True)
        base = self.make_venv("base")
        result = self.runtime_command(
            base, linked, "-c", "print('unexpected')", apply=True, code=1,
        )
        self.assertIn("repository runtime parent must not be a link", result.stderr)
        self.assertFalse((actual / ".runtime").exists())

    def test_linked_runtime_package_is_refused_before_import(self):
        repo = self.root / "source"
        repo.mkdir()
        runtime_dir = repo / ".runtime"
        self.run_command([sys.executable, "-m", "venv", "--without-pip", runtime_dir])
        site_packages = runtime_dir / ("Lib/site-packages" if os.name == "nt" else
                                      f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages")
        shutil.rmtree(site_packages)
        outside = self.root / "outside-site"
        package = outside / "yaml"
        package.mkdir(parents=True)
        marker = self.root / "imported.txt"
        (package / "__init__.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
            encoding="utf-8",
        )
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(outside), str(site_packages))
        else:
            os.symlink(outside, site_packages, target_is_directory=True)
        result = self.runtime_command(
            sys.executable, repo, "-c", "print('unexpected')", code=1,
        )
        self.assertIn(".runtime must not contain linked paths", result.stderr)
        self.assertFalse(marker.exists())
        runtime_python = runtime_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        result = self.runtime_command(
            runtime_python, repo, "-c", "print('unexpected')", code=1,
        )
        self.assertIn(".runtime must not contain linked paths", result.stderr)
        self.assertFalse(marker.exists())

    def test_capable_active_environment_is_preserved(self):
        repo = self.root / "source"
        repo.mkdir()
        active = self.make_venv("active", system_site_packages=True)
        self.run_command([active, "-I", "-c", "import yaml"])
        result = self.runtime_command(active, repo, "-c", "import sys; print(sys.executable)", apply=True)
        self.assertIn(f"Runtime Python: {active.absolute()}", result.stdout)
        self.assertIn(str(active.absolute()), result.stdout)
        self.assertFalse((repo / ".runtime").exists())

    def test_existing_runtime_precedes_capable_global_python(self):
        current = runtime.probe_python(sys.executable)
        if current["prefix"] != current["base_prefix"]:
            self.skipTest("test runner uses an explicit active environment")
        repo = self.root / "source"
        repo.mkdir()
        runtime_dir = repo / ".runtime"
        self.run_command([
            sys.executable, "-m", "venv", "--system-site-packages", runtime_dir,
        ])
        selected = runtime.select_python(repo, executable=sys.executable)
        expected = runtime_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.assertEqual(selected, expected)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows wrapper test")
    def test_windows_wrapper_bootstrap_and_sync_share_runtime(self):
        seed = self.root / "seed"
        shutil.copytree(
            ROOT, seed,
            ignore=shutil.ignore_patterns(".git", ".runtime", "dist", "__pycache__", "*.pyc"),
        )
        git_env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
        }
        self.run_command(["git", "init", "-b", "main"], cwd=seed,
                         env=git_env)
        self.run_command(["git", "-C", seed, "config", "user.email", "runtime@example.invalid"],
                         env=git_env)
        self.run_command(["git", "-C", seed, "config", "user.name", "Runtime Test"], env=git_env)
        self.run_command(["git", "-C", seed, "add", "."], env=git_env)
        self.run_command(["git", "-C", seed, "commit", "-m", "fixture"], env=git_env)
        remote = self.root / "remote.git"
        self.run_command(["git", "clone", "--bare", seed, remote], env=git_env)
        source = self.root / "source"
        self.run_command(["git", "clone", remote, source], env=git_env)

        base = self.make_venv("base")
        wheelhouse = self.build_wheel()
        home = self.root / "profile"
        codex = home / ".codex"
        codex.mkdir(parents=True)
        pip_cache = self.root / "pip-cache"
        outside_target = self.root / "outside-target"
        pip_config = self.root / "pip.ini"
        pip_config.write_text(f"[global]\ntarget = {outside_target}\n", encoding="utf-8")
        env = {
            **os.environ,
            "PATH": str(base.parent) + os.pathsep + os.environ["PATH"],
            "USERPROFILE": str(home),
            "HOME": str(home),
            "CODEX_HOME": str(codex),
            "PYTHONUTF8": "1",
            "PIP_CACHE_DIR": str(pip_cache),
            "PIP_FIND_LINKS": wheelhouse.as_uri(),
            "PIP_NO_INDEX": "1",
            "PIP_CONFIG_FILE": str(pip_config),
            "PIP_TARGET": str(outside_target),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
        }
        platform = "windows"
        legacy = self.run_command(
            [base, source / "scripts/install.py", "install", "--home", home,
             "--repo", source, "--platform", platform], env=env, code=1,
        )
        self.assertIn("ModuleNotFoundError: No module named 'yaml'", legacy.stdout + legacy.stderr)

        powershell = shutil.which("powershell")
        applied = self.run_command(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             source / "scripts/install-windows.ps1"], env=env,
        )
        runtime_python = source / ".runtime/Scripts/python.exe"
        self.assertIn(f"Runtime Python: {runtime_python}", applied.stdout)
        self.run_command([runtime_python, "-I", "-c", "import yaml"])
        self.assertFalse(outside_target.exists())
        self.assertEqual(
            self.run_command(["git", "-C", source, "status", "--porcelain"], env=git_env).stdout,
            "",
        )

        bootstrap_home = self.root / "bootstrap-profile"
        bootstrap_codex = bootstrap_home / ".codex"
        bootstrap_codex.mkdir(parents=True)
        bootstrap_target = self.root / "bootstrap-source"
        bootstrap_env = {
            **env,
            "USERPROFILE": str(bootstrap_home),
            "HOME": str(bootstrap_home),
            "CODEX_HOME": str(bootstrap_codex),
        }
        bootstrapped = self.run_command(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             source / "scripts/bootstrap-windows.ps1", "-RepoUrl", remote,
             "-Target", bootstrap_target],
            env=bootstrap_env,
        )
        bootstrap_python = bootstrap_target / ".runtime/Scripts/python.exe"
        self.assertIn(f"Runtime Python: {bootstrap_python}", bootstrapped.stdout)
        self.run_command([bootstrap_python, "-I", "-c", "import yaml"])
        self.run_command([
            bootstrap_python, bootstrap_target / "scripts/setup-check.py",
            "--home", bootstrap_home, "--repo", bootstrap_target,
        ], env=bootstrap_env)
        self.assertFalse(outside_target.exists())

        shutil.rmtree(wheelhouse)
        env["PIP_FIND_LINKS"] = str(self.root / "missing-wheelhouse")
        synced = self.run_command(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             source / "scripts/sync.ps1"], env=env,
        )
        self.assertIn(f"Runtime Python: {runtime_python}", synced.stdout)
        self.assertIn("Already up to date", synced.stdout)


if __name__ == "__main__":
    unittest.main()
