"""Preview install targets and restore only recorded, unchanged installation files."""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
from uuid import uuid4

from scripts.native_hook_io import safe_path

RECOVERY = "dev-setup-codex-community-recovery.json"
STATE = "dev-setup-codex-community-state.json"


def valid_relative(rel):
    if not isinstance(rel, str):
        return False
    path = PurePosixPath(rel)
    return (isinstance(rel, str) and str(path) == rel and not path.is_absolute()
            and ".." not in path.parts and "\\" not in rel and ":" not in rel
            and (rel in ("AGENTS.md", "hooks.json", STATE)
                 or (rel.startswith("skills/") and len(path.parts) > 2
                     and not path.parts[1].startswith("."))))


def read(path):
    safe_path(path)
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError("single regular file required: " + str(path))
    return path.read_bytes()


def digest(data):
    return None if data is None else hashlib.sha256(data).hexdigest()


def targets(engine, args):
    sc = engine.load_setup_check()
    root = sc.codex_home(args.home).absolute()
    safe_path(root)
    snapshot = engine.snapshot_tree(sc, args.repo / "skills")
    existing = engine.load_state(root / STATE) or {}
    prior = existing.get("skills_manifest", [])
    if not sc.is_str_list(prior):
        raise ValueError("invalid prior skill manifest; repair state before installation")
    paths = {"AGENTS.md", "hooks.json", STATE}
    paths.update("skills/" + rel for rel in set(snapshot) | set(prior))
    if not all(valid_relative(rel) for rel in paths):
        raise ValueError("unsafe managed target path")
    before = {rel: read(root / rel) for rel in sorted(paths)}
    return root, before, snapshot


def preview(engine, args):
    root, before, snapshot = targets(engine, args)
    print("Target: " + str(root))
    for rel, raw in before.items():
        if rel.startswith("skills/"):
            desired = snapshot.get(rel.removeprefix("skills/"))
            action = "keep" if desired == raw else "create" if raw is None else "retire" if desired is None else "replace (backup)"
        else:
            action = "create" if raw is None else "merge/update (backup)"
        print(f"  {action}: {rel}")
    print("Preview only. SSH, credentials, model settings and unrelated skills are not targets.")
    return 0


def journal(root):
    raw = read(root / RECOVERY)
    data = [] if raw is None else json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("invalid recovery journal")
    for row in data:
        if not isinstance(row, dict) or row.get("status") not in ("prepared", "installed", "failed", "restored"):
            raise ValueError("invalid recovery record")
        before, after = row.get("before"), row.get("after")
        if not isinstance(before, dict) or not isinstance(after, dict) or not all(valid_relative(rel) for rel in before):
            raise ValueError("unsafe recovery record")
        if set(after) - set(before):
            raise ValueError("invalid recovery target set")
        for value in before.values():
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError("invalid saved original bytes")
                base64.b64decode(value, validate=True)
        for value in after.values():
            if value is not None and (not isinstance(value, str) or len(value) != 64
                                      or any(c not in "0123456789abcdef" for c in value)):
                raise ValueError("invalid recovery hash")
        modes = row.get("modes", {})
        if not isinstance(modes, dict) or set(modes) - set(before) or any(
                type(mode) is not int or not 0 <= mode <= 0o7777 for mode in modes.values()):
            raise ValueError("invalid recovery modes")
    return data, raw


def save(engine, root, data, previous):
    engine.staged_write(root / RECOVERY, (json.dumps(data, indent=2) + "\n").encode(), previous)
    if os.name == "posix":
        (root / RECOVERY).chmod(0o600)


@contextmanager
def locked(root):
    safe_path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = safe_path(root / ".community-install.lock")
    with path.open("xb"):
        pass
    try:
        yield
    finally:
        path.unlink()


def install(engine, args, action):
    root, before, _ = targets(engine, args)
    with locked(root):
        rows, raw = journal(root)
        if any(row["status"] in ("prepared", "failed") for row in rows):
            raise ValueError("unfinished installation: preview rollback before reinstalling")
        before = {rel: read(root / rel) for rel in before}
        if (getattr(args, "prior_state_expected", before.get(STATE)) != before.get(STATE)
                or getattr(args, "prior_hooks_expected", before.get("hooks.json")) != before.get("hooks.json")):
            raise ValueError("installation inputs changed after recovery preflight")
        row = {"id": uuid4().hex, "status": "prepared",
               "before": {rel: None if data is None else base64.b64encode(data).decode() for rel, data in before.items()},
               "modes": {rel: stat.S_IMODE((root / rel).stat().st_mode) for rel, data in before.items() if data is not None},
               "after": {}}
        rows.append(row)
        save(engine, root, rows, raw)
        written = read(root / RECOVERY)
        try:
            result = action(args)
            row["status"] = "installed" if result == 0 else "failed"
            return result
        except BaseException:
            row["status"] = "failed"
            raise
        finally:
            row["after"] = {rel: digest(read(root / rel)) for rel in before}
            if row["status"] == "installed" and all(row["after"][rel] == digest(data) for rel, data in before.items()):
                rows.pop()
            save(engine, root, rows, written)
            print("Recovery snapshot: " + str(root / RECOVERY))


def _state_path(state, key, required=False):
    if key not in state:
        if required:
            raise ValueError("saved installation state is missing " + key)
        return None
    value = state[key]
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError("saved installation state has invalid " + key)
    return Path(value)


def activate_source(engine, root, desired):
    raw_state = desired.get(STATE)
    if raw_state is None:
        return desired, None
    try:
        state = json.loads(raw_state)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("saved installation state is invalid") from exc
    sc = engine.load_setup_check()
    if (not isinstance(state, dict) or state.get("distribution") != "community"
            or not sc.state_schema_current(state)):
        raise ValueError("saved installation state is unsupported")
    old_repo = _state_path(state, "source_repo", required=True)
    update_repo = _state_path(state, "update_repo") or old_repo
    snapshot = engine.source_recovery.state_snapshot(state, root, verify=True)
    hooks = desired.get("hooks.json")
    native_hooks = engine.load_native_hooks()
    if "python_executable" in state:
        python = _state_path(state, "python_executable", required=True)
        python = engine.validate_python(python, require_yaml=True)
    else:
        if hooks is None:
            raise ValueError("saved hooks are required to recover a legacy interpreter")
        python = native_hooks.legacy_python(native_hooks.parse(hooks), root, old_repo)
        python = engine.validate_python(python, require_yaml=True)
    if snapshot is None:
        recorded = state.get("source_digest")
        if not isinstance(recorded, str) or engine.source_digest(old_repo) != recorded:
            raise ValueError("legacy recovery source no longer matches its recorded digest")
        return desired, {"snapshot": None, "python": python}
    if hooks is None:
        raise ValueError("saved hooks are missing; recovery cannot activate its source")
    activated = dict(desired)
    state["source_repo"] = str(snapshot)
    state["update_repo"] = str(update_repo)
    state["python_executable"] = str(python)
    activated[STATE] = (json.dumps(state, indent=2) + "\n").encode("utf-8")
    activated["hooks.json"] = native_hooks.retarget(
        hooks, root, old_repo, snapshot, python
    )
    return activated, {"snapshot": snapshot, "python": python}


def restore(engine, args, uninstall=False):
    root = engine.load_setup_check().codex_home(args.home).absolute()
    rows, raw = journal(root)
    active = [row for row in rows if row["status"] != "restored"]
    if not active:
        raise ValueError("no recovery snapshot; older releases require their original file backups")
    selected = active if uninstall else active[-1:]
    if any(set(row["before"]) != set(row["after"]) for row in selected):
        raise ValueError("interrupted snapshot has no complete post-install record; inspect its saved originals")
    first_state = selected[0]["before"].get(STATE)
    if uninstall and first_state is not None:
        raise ValueError("baseline predates recovery support; rollback restores that version, full uninstall needs its original backups")
    desired, expected, modes = {}, {}, {}
    for row in selected:
        for rel, encoded in row["before"].items():
            original = None if encoded is None else base64.b64decode(encoded, validate=True)
            if rel in expected and digest(original) != expected[rel]:
                raise ValueError("user edits exist between installations; rollback one version at a time: " + rel)
            if rel not in desired:
                desired[rel] = original
                modes[rel] = row.get("modes", {}).get(rel, 0o644)
            expected[rel] = row["after"][rel]
    current = {rel: read(root / rel) for rel in desired}
    conflicts = [rel for rel in desired if digest(current[rel]) != expected[rel] and current[rel] != desired[rel]]
    if conflicts:
        raise ValueError("files changed since installation; nothing restored: " + ", ".join(conflicts))
    original = dict(desired)
    activation = None
    if not uninstall:
        desired, activation = activate_source(engine, root, desired)
    for rel, data in desired.items():
        print(("remove: " if data is None else "restore: ") + rel)
    if not args.apply:
        print("Preview only. Add --apply to restore. Later user edits cause refusal.")
        return 0
    with locked(root):
        if read(root / RECOVERY) != raw or any(read(root / rel) != data for rel, data in current.items()):
            raise ValueError("recovery inputs changed; nothing restored")
        if activation is not None:
            if activation["snapshot"] is not None:
                engine.source_recovery.validate(activation["snapshot"], activation["snapshot"].name)
            engine.validate_python(activation["python"], require_yaml=True)
        for rel, data in desired.items():
            target = root / rel
            if current[rel] == data:
                continue
            if read(target) != current[rel]:
                raise ValueError("file changed during restore: " + rel)
            if data is None:
                target.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                engine.staged_write(target, data, current[rel])
                if os.name == "posix":
                    target.chmod(modes[rel])
        for row in selected:
            row["status"] = "restored"
        surviving = [row for row in rows if row["status"] != "restored"]
        if not uninstall and surviving:
            previous = surviving[-1]
            for rel in ("hooks.json", STATE):
                if desired.get(rel) != original.get(rel) and previous["after"].get(rel) == digest(original.get(rel)):
                    previous["after"][rel] = digest(desired.get(rel))
        save(engine, root, rows, raw)
    print("Restored recorded files. Local backups and runtime records are retained.")
    return 0
