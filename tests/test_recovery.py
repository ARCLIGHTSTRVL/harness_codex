"""Exercise immutable source recovery and installed interpreter continuity."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts import source_recovery


ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="community recovery ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source"
        shutil.copytree(ROOT, self.source, ignore=shutil.ignore_patterns(
            ".git", ".runtime", "dist", "__pycache__", "*.pyc"
        ))
        self.profile = self.root / "profile"
        self.codex = self.profile / ".codex"
        self.codex.mkdir(parents=True)
        self.marker = self.root / "marker.txt"
        self.env = dict(os.environ, CODEX_HOME=str(self.codex), PYTHONUTF8="1",
                        RECOVERY_MARKER=str(self.marker))
        self.platform = "windows" if os.name == "nt" else "mac"
        self.session_source = (self.source / "scripts/native-session.py").read_text(encoding="utf-8")
        self.skill_source = (self.source / "skills/doctor/SKILL.md").read_text(encoding="utf-8")

    def run_script(self, name, *arguments, source=None, python=None, code=0):
        source = source or self.source
        result = subprocess.run(
            [str(python or sys.executable), "-B", str(source / "scripts" / name), *map(str, arguments)],
            cwd=source, env=self.env, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def install(self, source=None, python=None):
        source = source or self.source
        return self.run_script("install.py", "install", "--home", self.profile, "--repo", source,
                               "--platform", self.platform, source=source, python=python)

    def restore(self, mode="rollback", code=0):
        return self.run_script("install.py", mode, "--home", self.profile, "--repo", self.source,
                               "--platform", self.platform, "--apply", code=code)

    def version(self, name):
        insertion = ("from __future__ import annotations\n\n"
                     "from pathlib import Path as _RecoveryMarkerPath\n"
                     "import os as _recovery_marker_os\n"
                     f"_RecoveryMarkerPath(_recovery_marker_os.environ['RECOVERY_MARKER']).write_text('{name}')\n")
        text = self.session_source.replace("from __future__ import annotations\n", insertion, 1)
        (self.source / "scripts/native-session.py").write_text(text, encoding="utf-8")
        (self.source / "skills/doctor/SKILL.md").write_text(
            self.skill_source + f"\nRecovery marker: {name}\n", encoding="utf-8"
        )

    def state(self):
        return json.loads((self.codex / "dev-setup-codex-community-state.json").read_text(encoding="utf-8"))

    def file_bytes(self):
        return {path.relative_to(self.codex).as_posix(): path.read_bytes()
                for path in self.codex.rglob("*") if path.is_file()}

    def test_same_directory_rollback_uses_preserved_runtime_and_default_check(self):
        self.version("A")
        self.install()
        source_a = Path(self.state()["recovery_source"])
        self.version("B")
        self.install()
        self.restore()
        state = self.state()
        self.assertEqual(Path(state["source_repo"]), source_a)
        self.assertEqual(Path(state["update_repo"]), self.source)
        self.assertIn("Recovery marker: A", (self.codex / "skills/doctor/SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("write_text('B')", (self.source / "scripts/native-session.py").read_text(encoding="utf-8"))
        self.run_script("setup-check.py", "--home", self.profile, "--probe-hooks")
        self.assertEqual(self.marker.read_text(), "A")

    def test_repeated_rollback_then_uninstall_and_reinstall(self):
        for name in ("A", "B", "C"):
            self.version(name)
            self.install()
        self.restore()
        self.assertIn("Recovery marker: B", (self.codex / "skills/doctor/SKILL.md").read_text(encoding="utf-8"))
        self.restore()
        self.assertIn("Recovery marker: A", (self.codex / "skills/doctor/SKILL.md").read_text(encoding="utf-8"))
        self.restore("uninstall")
        self.assertFalse((self.codex / "dev-setup-codex-community-state.json").exists())
        self.version("D")
        self.install()
        self.run_script("setup-check.py", "--home", self.profile)

    def test_between_install_edits_are_not_blessed_by_retarget(self):
        self.version("A")
        self.install()
        state_path = self.codex / "dev-setup-codex-community-state.json"
        state = self.state()
        state["user_note"] = "keep"
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        hooks_path = self.codex / "hooks.json"
        hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
        own = {"type": "command", "command": "echo user-hook"}
        managed = hooks["hooks"]["SessionStart"][0]["hooks"][0]
        managed["timeout"] = 31
        managed["user_extension"] = "keep"
        hooks["hooks"].setdefault("Stop", []).append({"matcher": "", "hooks": [own]})
        hooks_path.write_text(json.dumps(hooks, indent=2) + "\n", encoding="utf-8")
        self.version("B")
        self.install()
        self.restore()
        self.assertEqual(self.state()["user_note"], "keep")
        restored = json.loads(hooks_path.read_text(encoding="utf-8"))
        managed = restored["hooks"]["SessionStart"][0]["hooks"][0]
        self.assertEqual(managed["timeout"], 31)
        self.assertEqual(managed["user_extension"], "keep")
        self.assertIn(own, [hook for groups in restored["hooks"].values()
                            for group in groups for hook in group["hooks"]])
        before = self.file_bytes()
        self.restore("uninstall", code=1)
        self.assertEqual(self.file_bytes(), before)

    def test_snapshot_corruption_and_missing_runtime_refuse_without_target_writes(self):
        self.version("A")
        self.install()
        snapshot = Path(self.state()["recovery_source"])
        self.version("B")
        self.install()
        victim = snapshot / "README.md"
        original = victim.read_bytes()
        mutations = (
            lambda: victim.write_bytes(original + b"changed"),
            lambda: (snapshot / "added.txt").write_text("added"),
            lambda: victim.unlink(),
            lambda: os.link(victim, snapshot / "linked.txt"),
        )
        for mutate in mutations:
            mutate()
            before = self.file_bytes()
            self.restore(code=1)
            self.assertEqual(self.file_bytes(), before)
            victim.write_bytes(original)
            (snapshot / "added.txt").unlink(missing_ok=True)
            (snapshot / "linked.txt").unlink(missing_ok=True)

        runtime = self.root / "venv"
        subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(runtime)], check=True)
        python = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.restore()
        self.version("C")
        self.install(python=python)
        self.version("D")
        self.install()
        shutil.rmtree(runtime)
        before = self.file_bytes()
        self.restore(code=1)
        self.assertEqual(self.file_bytes(), before)

    def test_legacy_separate_source_recovers_but_overwritten_source_refuses(self):
        self.version("A")
        self.install()
        state_path = self.codex / "dev-setup-codex-community-state.json"
        legacy = self.state()
        for key in ("recovery_source", "recovery_digest", "python_executable"):
            legacy.pop(key)
        state_path.write_text(json.dumps(legacy, indent=2) + "\n", encoding="utf-8")
        native = load(self.source / "scripts/native-hooks.py", "legacy_native_hooks")
        legacy_hooks = native.merge({}, native._handlers(self.codex, self.source, sys.executable, False))
        (self.codex / "hooks.json").write_text(
            json.dumps(legacy_hooks, indent=2) + "\n", encoding="utf-8"
        )
        self.run_script("setup-check.py", "--home", self.profile, "--probe-hooks")
        source_b = self.root / "source-b"
        shutil.copytree(self.source, source_b, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (source_b / "skills/doctor/SKILL.md").write_text(
            self.skill_source + "\nLegacy B\n", encoding="utf-8"
        )
        self.install(source=source_b)
        self.restore()
        self.assertEqual(self.state()["source_repo"], str(self.source.resolve()))
        self.run_script("setup-check.py", "--home", self.profile, "--probe-hooks")

        self.version("C")
        self.install()
        same_legacy = self.state()
        for key in ("recovery_source", "recovery_digest", "python_executable"):
            same_legacy.pop(key)
        state_path.write_text(json.dumps(same_legacy, indent=2) + "\n", encoding="utf-8")
        self.version("D")
        self.install()
        before = self.file_bytes()
        self.restore(code=1)
        self.assertEqual(self.file_bytes(), before)

    def test_saved_venv_survives_base_checker_and_selected_python_refresh(self):
        first = self.root / "venv-one"
        second = self.root / "venv-two"
        for runtime in (first, second):
            subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(runtime)], check=True)
        name = "Scripts/python.exe" if os.name == "nt" else "bin/python"
        python_one, python_two = first / name, second / name
        self.install(python=python_one)
        self.run_script("setup-check.py", "--home", self.profile)
        self.run_script("setup-check.py", "--home", self.profile, "--probe-hooks")
        self.install(python=python_two)
        state = self.state()
        self.assertEqual(os.path.normcase(state["python_executable"]), os.path.normcase(str(python_two.absolute())))
        hooks = json.loads((self.codex / "hooks.json").read_text(encoding="utf-8"))
        commands = [hook.get("command", "") for groups in hooks["hooks"].values()
                    for group in groups for hook in group["hooks"]]
        self.assertTrue(all(str(python_two.absolute()) in command for command in commands))
        self.assertTrue(all(str(python_one.absolute()) not in command for command in commands))

    def test_historical_snapshot_validation_is_independent_of_current_inventory(self):
        prepared = source_recovery.prepare(self.source)
        snapshot = source_recovery.publish(self.codex, prepared)
        with mock.patch.object(source_recovery, "inventory", side_effect=ValueError("new release layout")):
            self.assertEqual(source_recovery.validate(snapshot, prepared.digest), snapshot)

    def test_linked_store_refuses_before_creating_outside_sources(self):
        outside = self.root / "outside"
        outside.mkdir()
        linked = self.codex / "dev-setup-codex-community"
        try:
            os.symlink(outside, linked, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                raise
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(outside)],
                                    capture_output=True, text=True)
            if result.returncode:
                self.skipTest("directory links are unavailable")
        self.addCleanup(lambda: os.rmdir(linked) if os.path.lexists(linked) else None)
        prepared = source_recovery.prepare(self.source)
        with self.assertRaisesRegex(RuntimeError, "linked path refused"):
            source_recovery.publish(self.codex, prepared)
        self.assertFalse((outside / "sources").exists())

    def test_snapshot_cache_and_link_boundaries(self):
        prepared = source_recovery.prepare(self.source)
        snapshot = source_recovery.publish(self.codex, prepared)
        cache_env = dict(self.env)
        cache_env.pop("PYTHONDONTWRITEBYTECODE", None)
        cache_env.pop("PYTHONPYCACHEPREFIX", None)
        result = subprocess.run([sys.executable, str(snapshot / "scripts/init-knowledge.py"), "--help"],
                                cwd=snapshot, env=cache_env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(any((snapshot / "scripts/__pycache__").glob("*.pyc")))
        self.assertEqual(source_recovery.validate(snapshot, prepared.digest), snapshot)

        cache = snapshot / "scripts/__pycache__"
        fake = cache / "native_hook_io.cpython-311.txt"
        fake.write_text("not bytecode")
        with self.assertRaisesRegex(RuntimeError, "invalid recovery snapshot cache"):
            source_recovery.validate(snapshot, prepared.digest)
        fake.unlink()
        sourceless = snapshot / "orphan.pyc"
        sourceless.write_bytes(b"bytecode")
        with self.assertRaisesRegex(RuntimeError, "sourceless recovery snapshot bytecode"):
            source_recovery.validate(snapshot, prepared.digest)
        sourceless.unlink()
        hardlink = snapshot / "docs/hardlinked.md"
        os.link(snapshot / "README.md", hardlink)
        with self.assertRaisesRegex(RuntimeError, "hardlinked recovery snapshot"):
            source_recovery.validate(snapshot, prepared.digest)
        hardlink.unlink()

    def test_new_checkout_after_rollback_becomes_update_authority(self):
        self.version("A")
        self.install()
        self.version("B")
        self.install()
        self.restore()
        source_d = self.root / "source-d"
        shutil.copytree(self.source, source_d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (source_d / "skills/doctor/SKILL.md").write_text(
            self.skill_source + "\nRecovery marker: D\n", encoding="utf-8"
        )
        self.install(source=source_d)
        state = self.state()
        self.assertEqual(state["source_repo"], str(source_d.resolve()))
        self.assertNotIn("update_repo", state)

    def test_missing_old_runtime_does_not_block_forward_repair(self):
        runtime = self.root / "old-venv"
        subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(runtime)], check=True)
        python = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.version("A")
        self.install(python=python)
        shutil.rmtree(runtime)
        self.version("B")
        self.install()
        self.assertEqual(os.path.normcase(self.state()["python_executable"]),
                         os.path.normcase(os.path.abspath(sys.executable)))

    def test_empty_state_normalizes_same_root_legacy_hooks(self):
        native = load(self.source / "scripts/native-hooks.py", "empty_state_native_hooks")
        legacy = native.merge({}, native._handlers(self.codex, self.source, sys.executable, False))
        unrelated = {"type": "command", "command": "echo unrelated"}
        legacy["hooks"].setdefault("Stop", []).append({"matcher": "", "hooks": [unrelated]})
        (self.codex / "hooks.json").write_text(json.dumps(legacy, indent=2) + "\n", encoding="utf-8")
        (self.codex / "dev-setup-codex-community-state.json").write_text("{}\n", encoding="utf-8")
        self.run_script("native-hooks.py", "install", "--home", self.codex, "--repo", self.source,
                        "--python", sys.executable)
        hooks = json.loads((self.codex / "hooks.json").read_text(encoding="utf-8"))
        entries = [hook for groups in hooks["hooks"].values()
                   for group in groups for hook in group["hooks"]]
        self.assertEqual(sum(" -B " in hook.get("command", "") for hook in entries), 6)
        self.assertEqual(sum("native-session.py" in hook.get("command", "")
                             or "native-agent-contract.py" in hook.get("command", "") for hook in entries), 6)
        self.assertIn(unrelated, entries)


if __name__ == "__main__":
    unittest.main()
