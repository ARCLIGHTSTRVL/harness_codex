"""Build a deterministic, allowlisted source ZIP and SHA-256 checksum."""
import hashlib
import importlib.util
import datetime
import json
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TREES = ("codex", "scripts", "skills", "templates", "specs", "tests", "docs")
FILES = ("README.md", "START-HERE.md", "BOOTSTRAP.md", "SKILLS.md", "NOTICE.md", "VERSION",
         "requirements.txt", ".gitignore", ".gitattributes", "secrets-exceptions.json",
         "model-name-exceptions.json", "AGENTS.md", "NEXT.md", "workflow/README.md",
         "knowledge/SCHEMA.md", "knowledge/index.md", "knowledge/log.md",
         "knowledge/comparisons/portable-distribution.md",
         "knowledge/journal/2026-09-10-distribution-readiness.md",
         "wiki/SCHEMA.md", "wiki/index.md", "wiki/log.md", "wiki/AGENTS.md")
ROUTING_MAPPING_NAME = "agent-routing.json"


def inventory(root=ROOT):
    paths = []
    for name in (*TREES, *FILES):
        base = root / name
        if not base.exists():
            raise ValueError("missing release input: " + name)
        if base.is_symlink() or bool(getattr(base.lstat(), "st_reparse_tag", 0) & 0x20000000):
            raise ValueError("linked release root: " + name)
        candidates = base.rglob("*") if base.is_dir() else [base]
        for path in candidates:
            rel = path.relative_to(root)
            if any(p.startswith(".") and p not in FILES for p in rel.parts):
                continue
            if "__pycache__" in rel.parts or path.suffix in (".pyc", ".log"):
                continue
            if path.is_symlink() or bool(getattr(path.lstat(), "st_reparse_tag", 0) & 0x20000000):
                raise ValueError("linked release input: " + rel.as_posix())
            if path.is_file():
                paths.append(path)
    return sorted(paths, key=lambda p: p.relative_to(root).as_posix())


def build(root=ROOT, output=None):
    spec = importlib.util.spec_from_file_location("release_preflight", root / "skills/ask/scripts/ask-preflight.py")
    preflight = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preflight)
    spec = importlib.util.spec_from_file_location("release_gate", root / "scripts/secrets-gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    entries, errors = gate.load_registry((root / "secrets-exceptions.json").read_text(),
                                         datetime.date.today())
    if errors:
        raise ValueError("invalid secret exception registry")
    if any(entry["expired"] for entry in entries):
        raise ValueError("expired secret exception registry entry")
    exceptions = json.loads((root / "secrets-exceptions.json").read_text())
    allowed = {(row["path"], row["rule"], row["sha256"]) for row in exceptions}
    version = (root / "VERSION").read_text().strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("invalid VERSION")
    captured = []
    for path in inventory(root):
        rel = path.relative_to(root).as_posix()
        if Path(rel).name.casefold() == ROUTING_MAPPING_NAME:
            raise ValueError("routing mapping cannot be packaged: " + rel)
        if preflight.CREDENTIAL_PATH.search(rel):
            raise ValueError("credential file cannot be packaged: " + rel)
        data = path.read_bytes()
        for number, line in enumerate(data.decode("utf-8").splitlines(), 1):
            for rule, pattern in gate.line_rules(preflight).items():
                if pattern.search(line) and (rel, rule, hashlib.sha256(line.rstrip().encode()).hexdigest()) not in allowed:
                    raise ValueError(f"release scan blocked {rel}:{number} ({rule})")
        if rel != "scripts/package.py" and re.search(r"arclights|ARCLIGHTSTRVL|C:[/\\]Users[/\\]", data.decode("utf-8"), re.I):
            raise ValueError("personal identifier in " + rel)
        captured.append((rel, data))
    captured.append(("knowledge/_fragments/units.yml", (root / "templates/knowledge-units.yml").read_bytes()))
    captured.sort()
    output = output or root / "dist"
    output.mkdir(parents=True, exist_ok=True)
    name = "dev-setup-codex-community-" + version
    archive = output / (name + ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for rel, data in captured:
            info = zipfile.ZipInfo(name + "/" + rel, (2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100755 if rel.endswith(".sh") else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, data, compresslevel=9)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(digest + "  " + archive.name + "\n", encoding="utf-8")
    print(f"Built {archive.name}: {len(captured)} files, sha256={digest}")
    return archive


if __name__ == "__main__":
    try:
        build()
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
