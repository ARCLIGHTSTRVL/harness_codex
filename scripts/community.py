"""Content identity and installation checks for extracted community releases."""
import hashlib
import importlib.util
import json
from pathlib import Path

from scripts.public_source import report as public_source_report

ROOT = Path(__file__).resolve().parents[1]
STATE_NAME = "dev-setup-codex-community-state.json"
SOURCE_ROOTS = ("codex", "skills", "scripts", "templates", "VERSION")


def engine():
    spec = importlib.util.spec_from_file_location("community_install", ROOT / "scripts/install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_digest(repo):
    installer = engine()
    digest = hashlib.sha256()
    for name in SOURCE_ROOTS:
        base = Path(repo) / name
        installer.refuse_linked_path(Path(repo), base)
        if base.is_file():
            entries = [(name, base.read_bytes())]
        else:
            entries = [(name + "/" + rel, data) for rel, data in
                       installer.snapshot_tree(installer.load_setup_check(), base).items()]
        for rel, data in sorted(entries):
            digest.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
    return digest.hexdigest()


def source_hashes(sc, repo):
    installer = engine()
    snapshot = installer.snapshot_tree(sc, Path(repo) / "skills")
    policy = installer.read_source(sc, Path(repo), "codex", "AGENTS.md").decode("utf-8-sig")
    return installer.expected_hashes(sc, {"skills_manifest": snapshot}, {"codex": policy})


def findings(sc, home, repo, platform=None, hooks=True, probe=False):
    installer = engine()
    try:
        target = sc.codex_home(home)
        installer.refuse_linked_path(target, target / STATE_NAME)
        state = json.loads((target / STATE_NAME).read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("distribution") != "community":
            return ["missing community installation baseline"]
        if not sc.state_schema_current(state):
            return ["unsupported installation state schema"]
        issues = []
        if platform and state.get("platform") != platform:
            issues.append("installed platform differs")
        if state.get("source_repo") != str(Path(repo).resolve()):
            issues.append("installation source location differs; reinstall from this folder")
        if state.get("source_digest") != source_digest(repo):
            issues.append("source content changed; reinstall")
        manifest = state.get("skills_manifest")
        if not sc.is_str_list(manifest):
            return ["invalid skill manifest"]
        for rel in manifest:
            if not rel or "\\" in rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
                return ["unsafe skill manifest path"]
            installer.refuse_linked_path(target, target / "skills" / rel)
        installer.refuse_linked_path(target, target / "AGENTS.md")
        current = installer.produced_hashes(sc, home, {"skills_manifest": manifest})
        if state.get("files") != current:
            issues.append("installed policy or skills changed or are missing")
        if current != source_hashes(sc, repo):
            issues.append("installed content differs from the distribution source")
        if hooks:
            issues.extend(sc.native_hook_findings(home, repo, probe=probe))
        return issues
    except (OSError, ValueError, RuntimeError, installer.Refusal, sc.ProducerRefusal) as exc:
        return ["installation cannot be verified: " + str(exc)]


def status(sc, home, repo, hooks=True, probe=False, check_updates=False):
    issues = findings(sc, home, repo, hooks=hooks, probe=probe)
    for issue in issues:
        print("Drift: " + issue)
    if not issues:
        print("In sync: community source and installed content match")
    print("Hook trust and host event delivery are unverified." if hooks
          else "Hook configuration was not checked.")
    public_lines, public_code = public_source_report(repo, check_updates=check_updates)
    for line in public_lines:
        print(line)
    return max(int(bool(issues)), public_code)
