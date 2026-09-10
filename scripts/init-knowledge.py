"""Add missing project knowledge scaffolding and optional handoff hooks without overwriting files."""
import argparse
from datetime import date
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.native_hook_io import atomic_write, safe_path

DIRECTORIES = ("knowledge/raw/papers", "knowledge/raw/data", "knowledge/raw/transcripts",
               "knowledge/raw/assets", "knowledge/journal", "knowledge/synthesis",
               "knowledge/comparisons", "knowledge/queries", "knowledge/_archive",
               "knowledge/_fragments", "workflow/plans")


def scaffold(project, hooks=False):
    today = date.today().isoformat()
    result = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"], capture_output=True, text=True)
    head = result.stdout.strip() if result.returncode == 0 else "UNCOMMITTED"
    texts = {
        "knowledge/SCHEMA.md": (ROOT / "skills/research-kb/templates/SCHEMA.md").read_text(encoding="utf-8"),
        "knowledge/index.md": "# Knowledge index\n\n## Journal\n\n## Synthesis\n\n## Comparisons\n\n## Queries\n",
        "knowledge/log.md": f"# Knowledge log\n\n## [{today}] create | Initialized knowledge workflow\n",
        "knowledge/_fragments/units.yml": (ROOT / "templates/knowledge-units.yml").read_text(),
        "workflow/README.md": "# Workflow\n\nNEXT.md owns the active handoff. workflow/plans/ holds active multi-phase plans.\n",
        "NEXT.md": f"""---
last_verified_commit: {head}
last_touched: {today}
writer: codex
unit_paths: knowledge/index.md
---

# NEXT

## Active Unit

Goal: Establish and verify this project's knowledge workflow.
Current state:
- Missing knowledge scaffolding has been added; existing project files were preserved.
Blocker:
- Git freshness is unverified until a valid project commit is available.
Pointers:
- knowledge/SCHEMA.md
- knowledge/index.md
Acceptance:
- Record a meaningful delta, distill it at a unit boundary, and run the knowledge linter.

## Next Action

Register the active unit in knowledge/_fragments/units.yml before capturing decisions.

## Pending, Not This Unit

- Review project hook trust and project-specific conventions.
""",
    }
    files = {rel: text.encode("utf-8") for rel, text in texts.items()}
    if hooks:
        files[".codex/hooks.json"] = (ROOT / "templates/hooks.json").read_bytes()
        for name in ("freshness-inject.sh", "compact-handoff-gate.sh", "stop-handoff-gate.sh", "plan-handoff.py"):
            files[".codex/hooks/" + name] = (ROOT / "templates/hooks" / name).read_bytes()
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--hooks", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    project = safe_path(args.project.absolute())
    if not project.is_dir():
        parser.error("project must be an existing directory")
    files = scaffold(project, args.hooks)
    for rel in (*DIRECTORIES, *files):
        safe_path(project / rel)
    missing = {rel: data for rel, data in files.items() if not (project / rel).exists()}
    for rel in files:
        print(("create: " if rel in missing else "preserve existing: ") + rel)
    if not args.apply:
        print("Preview only. Add --apply to create missing files.")
        return 0
    for rel in DIRECTORIES:
        (project / rel).mkdir(parents=True, exist_ok=True)
    for rel, data in missing.items():
        atomic_write(project / rel, data, None)
        if rel.endswith(".sh") and os.name == "posix":
            (project / rel).chmod(0o755)
    print("Knowledge scaffold created. Existing files were preserved.")
    if args.hooks:
        print("Review/merge project hook definitions and trust their exact commands in Codex.")
    print("Project freshness hooks require Git. Semantic capture/distillation remains agent-owned.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
