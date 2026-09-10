"""Verify portable native routing, isolation, and delegated report injection."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from native_agents import boundary, catalog, roles, routing


class NativeRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="community-native-routing-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / ".git").mkdir()
        self.home = self.root / "codex-home"
        self.state = self.root / "state"
        self.models = (catalog.Model("model-a", ("high", "xhigh")),)
        self.payload = {
            "session_id": "parent-1", "cwd": str(self.project),
            "tool_name": "spawn_agent", "tool_use_id": "call-1",
            "tool_input": {"task_name": "worker_task", "message": "bounded task"},
        }

    def config(self, model: str = "model-a", allowed: list[str] | None = None,
               models: tuple[catalog.Model, ...] | None = None) -> dict:
        rows = {}
        for role in roles.ROLE_BODIES:
            row = {"task_name_prefix": role + "_", "model": model,
                   "reasoning_effort": "high"}
            if allowed is not None:
                row["allowed_reasoning_efforts"] = allowed
            rows[role] = row
        return {"schema_version": 2,
                "catalog_fingerprint": catalog.catalog_fingerprint(models or self.models),
                "roles": rows}

    def write_project(self, config: dict) -> Path:
        target = self.project / ".codex/agent-routing.json"
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(config), encoding="utf-8")
        return target

    def write_global(self, config: dict) -> Path:
        target = self.home / "dev-setup-codex-community/agent-routing.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(config), encoding="utf-8")
        return target

    def event(self) -> boundary.Event:
        return boundary.Event.parse(json.dumps(self.payload))

    def invoke(self, mode: str, payload: dict | None = None, *, state: Path | None = None,
               home: Path | None = None, cwd: Path | None = None) -> dict:
        command = [sys.executable, str(ROOT / "scripts/native-agent-contract.py"), mode]
        if state is not None:
            command += ["--state-dir", str(state)]
        if home is not None:
            command += ["--home", str(home)]
        if cwd is not None:
            command += ["--cwd", str(cwd)]
        result = subprocess.run(command, input=json.dumps(payload or {}), capture_output=True,
                                text=True, encoding="utf-8", check=False,
                                env={**os.environ, "CODEX_HOME": str(self.root / "ambient-decoy")})
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_absent_project_and_global_config_remains_unset(self) -> None:
        result = routing.attest(self.event(), boundary.Store(self.state), self.models, self.home)
        self.assertIn("UNSET", result["hookSpecificOutput"]["additionalContext"])
        current = routing.status(self.event(), boundary.Store(self.state), self.home)
        self.assertEqual((current["state"], current["code"]),
                         ("UNSET", "user_role_configuration_required"))

    def test_project_override_precedes_user_global_default(self) -> None:
        offered = (catalog.Model("model-a", ("high", "xhigh")),
                   catalog.Model("model-b", ("high",)))
        global_config = self.config("model-b", models=offered)
        project_config = self.config("model-a", models=offered)
        self.write_global(global_config)
        project_path = self.write_project(project_config)
        routing.attest(self.event(), boundary.Store(self.state), offered, self.home)
        current = routing.status(self.event(), boundary.Store(self.state), self.home)
        self.assertEqual(current["config_scope"], "project")
        self.assertEqual(Path(current["config_source"]), project_path.resolve())
        updated = routing.pre(self.event(), boundary.Store(self.state), self.home)
        self.assertEqual(updated["hookSpecificOutput"]["updatedInput"]["model"], "model-a")

    def test_malformed_project_override_cannot_use_global_default(self) -> None:
        self.write_global(self.config())
        self.write_project({})
        with self.assertRaisesRegex(boundary.ContractError, "invalid_routing_schema"):
            routing.attest(self.event(), boundary.Store(self.state), self.models, self.home)

    def test_linked_project_override_cannot_use_global_default(self) -> None:
        global_path = self.write_global(self.config())
        project_path = self.project / ".codex/agent-routing.json"
        project_path.parent.mkdir()
        try:
            project_path.symlink_to(global_path)
        except OSError as exc:
            self.skipTest(str(exc))
        with self.assertRaisesRegex(boundary.ContractError, "routing_path_escape"):
            routing.attest(self.event(), boundary.Store(self.state), self.models, self.home)

    def test_linked_state_root_is_rejected(self) -> None:
        outside = self.root / "outside-state"
        outside.mkdir()
        linked = self.root / "state-link"
        try:
            linked.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(str(exc))
        with self.assertRaisesRegex(boundary.ContractError, "state_path_escape"):
            boundary.Store(linked).write(
                "bindings/" + boundary.digest("session") + ".json", {})
        self.assertFalse((outside / "bindings").exists())

    def test_dangling_nested_links_remain_the_project_boundary(self) -> None:
        self.write_global(self.config())
        for kind in ("file", "directory"):
            with self.subTest(kind=kind):
                nested = self.project / kind
                nested.mkdir()
                if kind == "file":
                    (nested / ".codex").mkdir()
                    link = nested / ".codex/agent-routing.json"
                    target = self.root / "missing.json"
                else:
                    link = nested / ".codex"
                    target = self.root / "missing-directory"
                try:
                    link.symlink_to(target, target_is_directory=kind == "directory")
                except OSError as exc:
                    self.skipTest(str(exc))
                self.payload["cwd"] = str(nested)
                event = self.event()
                self.assertEqual(event.root, nested.resolve())
                with self.assertRaisesRegex(boundary.ContractError, "routing_path_escape"):
                    routing.attest(event, boundary.Store(self.state / kind), self.models, self.home)

    def test_allowed_effort_is_preserved_and_recorded(self) -> None:
        self.write_project(self.config(allowed=["high", "xhigh"]))
        event = self.event()
        store = boundary.Store(self.state)
        routing.attest(event, store, self.models, self.home)
        self.payload["tool_input"]["reasoning_effort"] = "xhigh"
        event = self.event()
        output = routing.pre(event, store, self.home)
        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["reasoning_effort"], "xhigh")
        launch = store.read(f"launches/{event.call_key}.json")
        self.assertEqual(launch["requested"], {"model": "model-a", "reasoning_effort": "xhigh"})
        self.assertTrue(updated["message"].endswith("bounded task"))

    def test_scalar_effort_remains_the_only_allowed_value(self) -> None:
        self.write_project(self.config())
        routing.attest(self.event(), boundary.Store(self.state), self.models, self.home)
        self.payload["tool_input"]["reasoning_effort"] = "xhigh"
        output = routing.pre(self.event(), boundary.Store(self.state), self.home)
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_compatible_catalog_drift_is_fresh_and_missing_effort_is_stale(self) -> None:
        self.write_project(self.config(allowed=["high", "xhigh"]))
        expanded = (*self.models, catalog.Model("unselected-model", ("medium",)))
        event = self.event()
        store = boundary.Store(self.state)
        routing.attest(event, store, expanded, self.home)
        current = routing.status(event, store, self.home)
        self.assertEqual((current["state"], current["code"]),
                         ("FRESH", "selected_models_supported"))
        routing.attest(event, store, (catalog.Model("model-a", ("high",)),), self.home)
        current = routing.status(event, store, self.home)
        self.assertEqual((current["state"], current["code"]),
                         ("STALE", "selected_tuple_unavailable"))

    def test_config_source_and_content_changes_invalidate_attestation(self) -> None:
        config = self.config(allowed=["high", "xhigh"])
        global_path = self.write_global(config)
        project_path = self.write_project(config)
        event = self.event()
        store = boundary.Store(self.state)
        routing.attest(event, store, self.models, self.home)
        project_path.unlink()
        current = routing.status(event, store, self.home)
        self.assertEqual((current["state"], current["code"]),
                         ("STALE", "routing_config_source_changed"))
        routing.attest(event, store, self.models, self.home)
        changed = self.config(allowed=["high", "xhigh"])
        changed["roles"]["worker"]["reasoning_effort"] = "xhigh"
        global_path.write_text(json.dumps(changed), encoding="utf-8")
        current = routing.status(event, store, self.home)
        self.assertEqual((current["state"], current["code"]),
                         ("STALE", "routing_config_changed"))
        global_path.unlink()
        current = routing.status(event, store, self.home)
        self.assertEqual((current["state"], current["code"]),
                         ("STALE", "routing_config_removed"))

    def test_expired_attestation_is_unverified(self) -> None:
        self.write_global(self.config())
        event = self.event()
        store = boundary.Store(self.state)
        with patch.object(routing.time, "time", return_value=10.0):
            routing.attest(event, store, self.models, self.home)
        with patch.object(routing.time, "time", return_value=10.0 + routing.MAX_AGE + 1):
            current = routing.status(event, store, self.home)
        self.assertEqual((current["state"], current["code"]),
                         ("UNVERIFIED", "session_attestation_expired"))

    def test_report_contract_is_injected_once_without_replacing_task(self) -> None:
        for role in roles.ROLE_BODIES:
            injected = roles.instruction(role, "task payload")
            self.assertEqual(roles.instruction(role, injected), injected)
            self.assertEqual(injected.count(roles.REPORT_CONTRACT), 1)
            self.assertTrue(injected.endswith("task payload"))

    def test_home_and_canonical_state_dir_do_not_read_ambient_home(self) -> None:
        home_state = self.home / "dev-setup-codex/native-agents"
        self.write_global(self.config())
        routing.attest(self.event(), boundary.Store(home_state), self.models, self.home)
        by_home = self.invoke("status", home=self.home, cwd=self.project)
        self.assertEqual((by_home["state"], by_home["config_scope"]), ("FRESH", "global"))
        by_state = self.invoke("status", state=home_state, cwd=self.project)
        self.assertEqual((by_state["state"], by_state["config_scope"]), ("FRESH", "global"))
        self.assertFalse((self.root / "ambient-decoy").exists())


if __name__ == "__main__":
    unittest.main()
