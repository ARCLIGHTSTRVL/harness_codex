"""Exercise Git root and dirty-state boundaries in sync and bootstrap wrappers."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def find_bash():
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe"
        if candidate.is_file():
            return str(candidate)
    return shutil.which("bash")


class SyncBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="sync boundaries ")
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name).resolve()
        home = self.root / "home"
        for path in (home, home / "codex", self.root / "pip-cache", self.root / "temp"):
            path.mkdir(parents=True, exist_ok=True)
        self.marker = self.root / "install marker"
        self.env = {
            **os.environ,
            "HOME": str(home),
            "USERPROFILE": str(home),
            "CODEX_HOME": str(home / "codex"),
            "PIP_CACHE_DIR": str(self.root / "pip-cache"),
            "TEMP": str(self.root / "temp"),
            "TMP": str(self.root / "temp"),
            "BOUNDARY_MARKER": str(self.marker),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        self.powershell = shutil.which("pwsh") or shutil.which("powershell")
        self.bash = find_bash()

    def run_process(self, command, cwd=None):
        return subprocess.run(command, cwd=cwd, env=self.env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")

    def git(self, *args, cwd=None, code=0):
        result = self.run_process(["git", *map(str, args)], cwd=cwd)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result.stdout.strip()

    def write_installers(self, scripts):
        (scripts / "install-windows.ps1").write_text(
            '[IO.File]::AppendAllText($env:BOUNDARY_MARKER, "installed`n")\n',
            encoding="utf-8",
        )
        (scripts / "install-mac.sh").write_text(
            "#!/usr/bin/env bash\nprintf 'installed\\n' >> \"$BOUNDARY_MARKER\"\n",
            encoding="utf-8",
        )

    def make_repo(self, name, nested=False):
        repo = self.root / name
        repo.mkdir()
        self.git("init", "--initial-branch=main", cwd=repo)
        self.git("config", "user.name", "Boundary Test", cwd=repo)
        self.git("config", "user.email", "boundary@example.invalid", cwd=repo)
        source = repo / "vendor/harness" if nested else repo
        scripts = source / "scripts"
        scripts.mkdir(parents=True)
        for wrapper_name in ("sync.ps1", "sync.sh"):
            shutil.copy2(ROOT / "scripts" / wrapper_name, scripts / wrapper_name)
        self.write_installers(scripts)
        (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        self.git("add", ".", cwd=repo)
        self.git("commit", "-m", "fixture", cwd=repo)
        remote = self.root / f"{name}-remote.git"
        self.git("init", "--bare", "--initial-branch=main", remote)
        self.git("remote", "add", "custom", remote, cwd=repo)
        self.git("push", "-u", "custom", "main", cwd=repo)
        return repo, source

    def metadata(self, repo):
        git_dir = Path(self.git("rev-parse", "--absolute-git-dir", cwd=repo))
        fetch = git_dir / "FETCH_HEAD"
        return self.git("show-ref", cwd=repo), fetch.read_bytes() if fetch.exists() else None

    def tracking(self, repo):
        return (
            self.git("remote", "get-url", "custom", cwd=repo),
            self.git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", cwd=repo),
        )

    def powershell_sync(self, source):
        if not self.powershell:
            self.skipTest("PowerShell is unavailable")
        return self.run_process([self.powershell, "-NoProfile", "-ExecutionPolicy", "Bypass",
                                 "-File", str(source / "scripts/sync.ps1")])

    def bash_sync(self, source):
        if not self.bash:
            self.skipTest("Bash is unavailable")
        return self.run_process([self.bash, str(source / "scripts/sync.sh")])

    def powershell_bootstrap(self, target):
        if not self.powershell:
            self.skipTest("PowerShell is unavailable")
        return self.run_process([self.powershell, "-NoProfile", "-ExecutionPolicy", "Bypass",
                                 "-File", str(ROOT / "scripts/bootstrap-windows.ps1"),
                                 "-RepoUrl", "unused", "-Target", str(target)])

    def bash_bootstrap(self, target):
        if not self.bash:
            self.skipTest("Bash is unavailable")
        env = self.env.copy()
        env.update({"REPO_URL": "unused", "TARGET": target.as_posix()})
        return subprocess.run([self.bash, str(ROOT / "scripts/bootstrap-mac.sh")],
                              env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    def sync_wrappers(self):
        wrappers = []
        if self.powershell:
            wrappers.append(("powershell", self.powershell_sync))
        if self.bash:
            wrappers.append(("bash", self.bash_sync))
        return wrappers

    def bootstrap_wrappers(self):
        wrappers = []
        if self.powershell:
            wrappers.append(("powershell", self.powershell_bootstrap))
        if self.bash:
            wrappers.append(("bash", self.bash_bootstrap))
        return wrappers

    def assert_rejected_without_mutation(self, repo, invoke, message):
        before = self.metadata(repo)
        result = invoke()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(message, result.stdout + result.stderr)
        self.assertEqual(self.metadata(repo), before)
        self.assertFalse(self.marker.exists())

    def test_sync_rejects_nested_parent_repository_before_pull_or_install(self):
        for name, invoke in self.sync_wrappers():
            with self.subTest(wrapper=name):
                repo, source = self.make_repo(f"nested-sync-{name}", nested=True)
                self.assert_rejected_without_mutation(
                    repo, lambda s=source, method=invoke: method(s),
                    "Git root does not match sync source",
                )

    def test_bootstrap_rejects_nested_parent_repository_before_pull_or_install(self):
        for name, invoke in self.bootstrap_wrappers():
            with self.subTest(wrapper=name):
                repo, target = self.make_repo(f"nested-bootstrap-{name}", nested=True)
                self.assert_rejected_without_mutation(
                    repo, lambda t=target, method=invoke: method(t),
                    "Git root does not match bootstrap target",
                )

    def test_explicit_untracked_scan_ignores_status_configuration(self):
        wrappers = [("sync-" + name, invoke) for name, invoke in self.sync_wrappers()]
        wrappers += [("bootstrap-" + name, invoke) for name, invoke in self.bootstrap_wrappers()]
        for name, invoke in wrappers:
            with self.subTest(wrapper=name):
                repo, source = self.make_repo(f"untracked-{name}")
                self.git("config", "status.showUntrackedFiles", "no", cwd=repo)
                (repo / "untracked file.txt").write_text("preserve me\n", encoding="utf-8")
                result = invoke(source)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("dirty", (result.stdout + result.stderr).lower())
                self.assertFalse(self.marker.exists())

    def test_git_status_failure_is_explicit_and_fail_closed(self):
        wrappers = [("sync-" + name, invoke) for name, invoke in self.sync_wrappers()]
        wrappers += [("bootstrap-" + name, invoke) for name, invoke in self.bootstrap_wrappers()]
        for name, invoke in wrappers:
            with self.subTest(wrapper=name):
                repo, source = self.make_repo(f"status-failure-{name}")
                git_dir = Path(self.git("rev-parse", "--absolute-git-dir", cwd=repo))
                (git_dir / "index").write_bytes(b"invalid index")
                before = self.metadata(repo)
                result = invoke(source)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("git status failed", (result.stdout + result.stderr).lower())
                self.assertEqual(self.metadata(repo), before)
                self.assertFalse(self.marker.exists())

    def test_bootstrap_accepts_exact_git_worktree_with_git_file(self):
        base, _ = self.make_repo("worktree-base")
        wrappers = self.bootstrap_wrappers()
        for name, invoke in wrappers:
            with self.subTest(wrapper=name):
                worktree = self.root / f"worktree-{name}"
                self.git("worktree", "add", "-b", f"branch-{name}", worktree,
                         "custom/main", cwd=base)
                self.assertTrue((worktree / ".git").is_file())
                self.git("branch", "--set-upstream-to=custom/main", cwd=worktree)
                result = invoke(worktree)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.marker.read_text(encoding="utf-8").count("installed"), len(wrappers))

    def test_sync_uses_and_preserves_configured_tracking_source(self):
        wrappers = self.sync_wrappers()
        for name, invoke in wrappers:
            with self.subTest(wrapper=name):
                repo, source = self.make_repo(f"tracking-{name}")
                before = self.tracking(repo)
                result = invoke(source)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.tracking(repo), before)
        self.assertEqual(self.marker.read_text(encoding="utf-8").count("installed"), len(wrappers))

    @unittest.skipUnless(os.name == "nt", "Windows paths are case-insensitive")
    def test_windows_bootstrap_compares_canonical_path_case_insensitively(self):
        repo, _ = self.make_repo("Case Space Repo")
        target = Path(str(repo).swapcase())
        result = self.powershell_bootstrap(target)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.marker.is_file())


if __name__ == "__main__":
    unittest.main()
