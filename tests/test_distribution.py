"""Exercise extracted installs, preservation, drift, portability and release boundaries."""
import hashlib
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

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.release = tempfile.TemporaryDirectory(prefix="community release ")
        cls.packager = load("packager", ROOT / "scripts/package.py")
        cls.archive = cls.packager.build(ROOT, Path(cls.release.name))
        with zipfile.ZipFile(cls.archive) as bundle:
            bundle.extractall(Path(cls.release.name) / "unpacked")
        cls.source = next((Path(cls.release.name) / "unpacked").iterdir()).resolve()

    @classmethod
    def tearDownClass(cls):
        cls.release.cleanup()

    def setUp(self):
        self.profile = tempfile.TemporaryDirectory(prefix="community profile ")
        self.addCleanup(self.profile.cleanup)
        self.home = Path(self.profile.name).resolve()
        self.codex = self.home / "custom codex"
        self.codex.mkdir()
        self.env = {**os.environ, "CODEX_HOME": str(self.codex), "PYTHONUTF8": "1"}
        self.platform = "windows" if os.name == "nt" else "mac"

    def run_script(self, name, *args, code=0, source=None):
        proc = subprocess.run([sys.executable, str((source or self.source) / "scripts" / name), *map(str, args)],
                              env=self.env, text=True, encoding="utf-8", errors="replace", capture_output=True)
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        return proc.stdout

    def install(self, source=None):
        return self.run_script("install.py", "install", "--home", self.home,
                               "--repo", source or self.source, "--platform", self.platform, source=source)

    def check(self, code=0, source=None):
        return self.run_script("setup-check.py", "--home", self.home,
                               "--repo", source or self.source, code=code, source=source)

    def test_install_preserves_user_files_and_repeats(self):
        (self.home / ".ssh").mkdir()
        protected = {
            self.home / ".ssh/config": b"Host my-machine\n    HostName example.invalid\n",
            self.codex / "config.toml": b'model = "user-selected"\n',
            self.codex / "auth.json": b"{}\n",
            self.codex / "dev-setup-codex-community/agent-routing.json":
                b'{"roles":{"worker":{"model":"recipient-choice"}}}\n',
            self.codex / "skills/.system/owned.txt": b"system-owned",
            self.codex / "skills/unrelated/SKILL.md": b"user-owned",
        }
        for path, data in protected.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        policy = "# My policy\n<!-- USER:CUSTOM:START -->\nKeep me\n<!-- USER:CUSTOM:END -->\n"
        (self.codex / "AGENTS.md").write_text(policy)
        own_hook = {"type": "command", "command": "echo user-hook"}
        (self.codex / "hooks.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [own_hook]}]}}))
        self.install()
        self.check()
        self.assertIn("skipping", self.install())
        self.check()
        self.run_script("setup-check.py", "--home", self.home, "--repo", self.source, "--probe-hooks")
        for path, data in protected.items():
            self.assertEqual(path.read_bytes(), data)
        current = (self.codex / "AGENTS.md").read_text()
        self.assertTrue(current.startswith(policy))
        self.assertEqual(current.count("<!-- DEV-SETUP-CODEX:START -->"), 1)
        hooks = json.loads((self.codex / "hooks.json").read_text())
        self.assertIn(own_hook, [h for g in hooks["hooks"]["Stop"] for h in g["hooks"]])
        state = json.loads((self.codex / "dev-setup-codex-community-state.json").read_text())
        self.assertEqual(state["source_repo"], str(self.source.resolve()))
        self.assertNotIn("ssh_config", state["files"])

    def test_changed_skill_is_detected_and_backed_up(self):
        self.install()
        path = self.codex / "skills/doctor/SKILL.md"
        path.write_text("local modification")
        self.check(code=1)
        self.install()
        self.check()
        self.assertTrue(any(p.read_text() == "local modification" for p in path.parent.glob("SKILL.md.bak.*")))

    def test_source_change_is_detected(self):
        source = self.home / "source"
        shutil.copytree(self.source, source)
        self.install(source)
        with (source / "scripts/community.py").open("a") as stream:
            stream.write("\n# source changed\n")
        self.check(code=1, source=source)

    def test_corrupt_state_recovers_without_deleting_unrelated_files(self):
        self.install()
        state = self.codex / "dev-setup-codex-community-state.json"
        state.write_text("[]")
        self.check(code=1)
        self.install()
        self.check()

    def test_host_platform_launcher(self):
        if os.name == "nt":
            command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                       str(self.source / "scripts/install-windows.ps1")]
        else:
            command = ["bash", str(self.source / "scripts/install-mac.sh")]
        proc = subprocess.run(command, env=self.env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.check()

    def test_installed_review_helper_is_self_contained(self):
        self.install()
        module = load("installed_ask", self.codex / "skills/ask/scripts/ask-codex.py")
        helper = module.load_review_helper()
        self.assertIsNotNone(helper)
        self.assertEqual(Path(helper.__file__).parent.resolve(), (self.codex / "skills/ask/scripts").resolve())

    def test_archive_reproducibility_and_boundaries(self):
        first = hashlib.sha256(self.archive.read_bytes()).digest()
        again = self.packager.build(ROOT, Path(self.profile.name))
        self.assertEqual(first, hashlib.sha256(again.read_bytes()).digest())
        with zipfile.ZipFile(again) as bundle:
            names = bundle.namelist()
            self.assertFalse(any("/.git/" in n or "/ssh/" in n or "test_fixtures" in n or "cliproxy" in n for n in names))
            self.assertFalse(any(n.endswith("/agent-routing.json") for n in names))
            self.assertTrue(any(n.endswith("/knowledge/SCHEMA.md") for n in names))

    def test_upgrade_to_another_directory_retargets_hooks(self):
        self.install()
        source = self.home / "new release"
        shutil.copytree(self.source, source)
        self.install(source)
        self.check(source=source)
        hooks = json.loads((self.codex / "hooks.json").read_text())
        commands = [h["command"] for groups in hooks["hooks"].values()
                    for group in groups for h in group["hooks"]]
        self.assertEqual(len(commands), 6)
        self.assertTrue(all(str(source.resolve()) in command for command in commands))

    def test_packaging_rejects_credential_file(self):
        source = self.home / "source"
        shutil.copytree(self.source, source)
        (source / "docs/auth.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "credential file"):
            self.packager.build(source, self.home / "out")

    def test_packaging_rejects_routing_mapping(self):
        source = self.home / "source"
        shutil.copytree(self.source, source)
        (source / "codex/Agent-Routing.JSON").write_text("{}")
        with self.assertRaisesRegex(ValueError, "routing mapping"):
            self.packager.build(source, self.home / "out")

    def lifecycle(self, mode, apply=False, code=0):
        options = [mode, "--home", self.home, "--repo", self.source, "--platform", self.platform]
        if apply:
            options.append("--apply")
        return self.run_script("install.py", *options, code=code)

    def test_preview_is_read_only_and_lists_collisions(self):
        path = self.codex / "skills/doctor/SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text("user doctor")
        before = {str(p): p.read_bytes() for p in self.codex.rglob("*") if p.is_file()}
        report = self.lifecycle("preview")
        self.assertIn("replace (backup): skills/doctor/SKILL.md", report)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.codex.rglob("*") if p.is_file()})

    def test_uninstall_restores_original_collisions(self):
        policy = self.codex / "AGENTS.md"
        policy.write_bytes(b"user policy\n")
        skill = self.codex / "skills/doctor/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_bytes(b"original doctor\n")
        self.install()
        self.lifecycle("uninstall")
        self.check()
        self.lifecycle("uninstall", apply=True)
        self.assertEqual(policy.read_bytes(), b"user policy\n")
        self.assertEqual(skill.read_bytes(), b"original doctor\n")
        self.assertFalse((self.codex / "hooks.json").exists())
        self.assertFalse((self.codex / "dev-setup-codex-community-state.json").exists())
        self.assertFalse((self.codex / "skills/research-kb/SKILL.md").exists())

    def test_rollback_refuses_later_user_edits_before_writing(self):
        self.install()
        (self.codex / "AGENTS.md").write_text("later user edit")
        before = {str(p): p.read_bytes() for p in self.codex.rglob("*") if p.is_file()}
        self.lifecycle("rollback", apply=True, code=1)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.codex.rglob("*") if p.is_file()})

    def test_rollback_restores_previous_install(self):
        self.install()
        original = (self.codex / "skills/doctor/SKILL.md").read_bytes()
        source = self.home / "changed source"
        shutil.copytree(self.source, source)
        with (source / "skills/doctor/SKILL.md").open("a") as stream:
            stream.write("\nAdditional local policy.\n")
        self.install(source)
        self.lifecycle("rollback", apply=True)
        self.assertEqual((self.codex / "skills/doctor/SKILL.md").read_bytes(), original)
        self.run_script("setup-check.py", "--home", self.home)

    def test_uninstall_preserves_edits_between_installations(self):
        self.install()
        policy = self.codex / "AGENTS.md"
        policy.write_bytes(policy.read_bytes() + b"\nNew user instruction\n")
        source = self.home / "upgrade"
        shutil.copytree(self.source, source)
        self.install(source)
        current = policy.read_bytes()
        self.lifecycle("uninstall", apply=True, code=1)
        self.assertEqual(policy.read_bytes(), current)
        self.lifecycle("rollback", apply=True)
        self.assertIn(b"New user instruction", policy.read_bytes())

    def test_failed_install_can_restore_captured_originals(self):
        original = b"<!-- DEV-SETUP-CODEX:START -->\nbroken marker pair\n"
        (self.codex / "AGENTS.md").write_bytes(original)
        self.run_script("install.py", "install", "--home", self.home, "--repo", self.source,
                        "--platform", self.platform, code=1)
        self.lifecycle("rollback", apply=True)
        self.assertEqual((self.codex / "AGENTS.md").read_bytes(), original)
        self.assertFalse((self.codex / "hooks.json").exists())

    def test_knowledge_initializer_preserves_existing_files(self):
        project = self.home / "project"
        project.mkdir()
        (project / "NEXT.md").write_text("existing project handoff")
        self.run_script("init-knowledge.py", project, "--hooks")
        self.assertFalse((project / "knowledge").exists())
        self.run_script("init-knowledge.py", project, "--hooks", "--apply")
        self.assertEqual((project / "NEXT.md").read_text(), "existing project handoff")
        self.assertTrue((project / "knowledge/_fragments/units.yml").is_file())
        self.assertTrue((project / ".codex/hooks/plan-handoff.py").is_file())
        self.assertTrue((self.source / "knowledge/_fragments/units.yml").is_file())

    def test_onboarding_previews_then_applies(self):
        self.run_script("onboard.py")
        self.assertFalse((self.codex / "AGENTS.md").exists())
        self.run_script("onboard.py", "--apply")
        self.check()

    def test_virtual_environment_interpreter_is_retained(self):
        runtime = self.home / "venv"
        subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(runtime)], check=True,
                       capture_output=True)
        py = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        result = subprocess.run([str(py), str(self.source / "scripts/onboard.py"), "--apply"],
                                env=self.env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        hooks = json.loads((self.codex / "hooks.json").read_text())
        commands = [h["command"] for groups in hooks["hooks"].values() for group in groups for h in group["hooks"]]
        self.assertTrue(all(str(py.absolute()) in command for command in commands))

    def test_knowledge_distill_archive_lint_and_compact_recovery(self):
        self.install()
        project = self.home / "knowledge project"
        project.mkdir()
        self.run_script("init-knowledge.py", project, "--hooks", "--apply")
        knowledge = project / "knowledge"
        (knowledge / "_fragments/units.yml").write_text("units:\n- canonical_id: pipeline\n  aliases: []\n")
        fragment = knowledge / "_fragments/test-session.md"
        fragment.write_text('''---
fragment_schema: 1
session_id: test-session
date: 2026-09-10
---

## delta: test-session-001

```yaml
delta_id: test-session-001
created_at: 2026-09-10T00:00:00Z
unit_id: pipeline
kind: decision
status: accepted
summary: Preserve source evidence during consolidation.
feeds: [knowledge]
evidence:
  - {type: transcript, ref: "Fixture decision approved for the behavioral test."}
```

Preserve source evidence. Rejected option: deleting raw decisions before consolidation.
Risk: a later reader could otherwise lose the reason behind the decision.
''', encoding="utf-8")
        original_fragment = fragment.read_bytes()

        def skill(name, *args, code=0):
            path = self.codex / "skills" / name
            result = subprocess.run([sys.executable, str(path), *map(str, args)], env=self.env,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, code, result.stdout + result.stderr)
            return result.stdout

        self.assertIn("test-session-001", skill("knowledge-fragment/scripts/deltas-for.py", knowledge, "pipeline"))
        skill("knowledge-fragment/scripts/consolidate.py", knowledge, "pipeline", "--draft")
        self.assertEqual(fragment.read_bytes(), original_fragment)
        skill("knowledge-fragment/scripts/consolidate.py", knowledge, "pipeline", "--apply", code=1)
        self.assertEqual(fragment.read_bytes(), original_fragment)
        draft = knowledge / "_fragments/_drafts/pipeline.md"
        text = draft.read_text(encoding="utf-8")
        end = text.index("\n---", 4) + 4
        frontmatter = text[:end].replace("target: journal/pipeline.md", "target: comparisons/pipeline.md")
        draft.write_text(frontmatter + '''

# Evidence preservation

## Layer A
Decision: Preserve source evidence during consolidation.
Rejected option: deleting raw decisions before consolidation.
Risk: a later reader could lose the reason behind the decision.

## Layer B
The reviewed decision retains both the alternative and its consequence so a future
session can reconstruct the choice. See [[context]] and [[risks]].
''', encoding="utf-8")
        skill("knowledge-fragment/scripts/consolidate.py", knowledge, "pipeline", "--apply")
        target = knowledge / "comparisons/pipeline.md"
        self.assertIn("test-session-001", target.read_text(encoding="utf-8"))
        self.assertIn("Rejected option", target.read_text(encoding="utf-8"))
        self.assertFalse(fragment.exists())
        archived = knowledge / "_fragments/_archive/test-session.md"
        self.assertIn("status: consolidated", archived.read_text(encoding="utf-8"))
        self.assertIn("test-session-002", skill("knowledge-fragment/scripts/deltas-for.py", knowledge, "--next-id", "test-session"))
        for name, other in [("context", "risks"), ("risks", "context")]:
            (knowledge / "comparisons" / (name + ".md")).write_text(f'''---
title: {name}
created: 2026-09-10
updated: 2026-09-10
type: comparison
tags: [decision]
sources: []
---

See [[pipeline]] and [[{other}]] for the preserved reasoning.
''', encoding="utf-8")
        (knowledge / "index.md").write_text("# Knowledge\n\n[[pipeline]]\n[[context]]\n[[risks]]\n")
        self.assertIn("0 issues", skill("research-kb/scripts/kb-lint.py", knowledge))
        self.assertIn("unconsolidated deltas", skill("knowledge-fragment/scripts/deltas-for.py", knowledge, "--debt"))
        handoff = project / "workflow/plans/pipeline.md"
        handoff.write_text('''---
unit: pipeline
created: 2026-09-10
status: active
plan_schema: 1
---

## Handoff
<!-- handoff:begin -->
Read knowledge/comparisons/pipeline.md; preserved decision and risk are authoritative.
<!-- handoff:end -->
''')
        saved_next = (project / "NEXT.md").read_text()
        def event(mode, kind):
            payload = {"cwd": str(project), "session_id": "knowledge-cycle", "hook_event_name": kind,
                       "source": "compact", "trigger": "auto"}
            result = subprocess.run([sys.executable, str(self.source / "scripts/native-session.py"), mode,
                                     "--home", str(self.codex)], input=json.dumps(payload), env=self.env,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        event("compact", "PreCompact")
        (project / "NEXT.md").write_text("later handoff")
        response = event("session", "SessionStart")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("compact-carry", response)
        self.assertIn(saved_next.strip(), response)
        self.assertIn("knowledge/comparisons/pipeline.md", response)


if __name__ == "__main__":
    unittest.main()
