#!/usr/bin/env python3
"""Lint dev-setup-codex source consistency.

Checks:
- managed install sources exist
- every skills/<name>/SKILL.md has valid minimal frontmatter
- skills/ and SKILLS.md table agree

Exit 0 on clean, 1 on inconsistency.
"""
import os
import re
import sys
import json
import ast
import yaml

CONTEXT_PATHS = (
    "workflow/status.md",
    "workflow/README.md",
    "wiki/log.md",
    "wiki/index.md",
    "knowledge/log.md",
    "knowledge/index.md",
)
NEXT_SCHEMA_MARKERS = (
    "## Active Unit",
    "Goal:",
    "Current state:",
    "Blocker:",
    "Pointers:",
    "Acceptance:",
    "## Next Action",
    "## Pending, Not This Unit",
)
NEXT_SCHEMA_PHRASES = (
    "last_verified_commit",
    "last_touched must be YYYY-MM-DD",
    "unit_paths must not include root NEXT.md",
    "template placeholders remain",
    "Goal is empty",
)


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def assigned_literal_set(path, names):
    tree = ast.parse(read_text(path))
    values = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in names:
                values[target.id] = set(ast.literal_eval(node.value))
    return set().union(*(values.get(name, set()) for name in names))


def work_glob(path):
    text = read_text(path)
    m = re.search(r"^\s+([^)\n]+)\)\s+WORK=\"\$\{WORK\}", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def frontmatter(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return out
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return {}


def next_lint_body(path):
    text = read_text(path)
    m = re.search(r"next_lint_reason\(\) \{\n.*?<<'PY'\n(.*?)\nPY\n\}", text, re.S)
    return m.group(1) if m else ""


def main():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    errors = []

    required = (
        "codex/AGENTS.md",
        "templates/AGENTS.md",
        "templates/NEXT.md",
        "templates/new-project-init.md",
        "templates/hooks.json",
        "templates/hooks/freshness-inject.sh",
        "templates/hooks/compact-handoff-gate.sh",
        "templates/hooks/stop-handoff-gate.sh",
        "scripts/install-windows.ps1",
        "scripts/install-mac.sh",
        "scripts/sync.ps1",
        "scripts/sync.sh",
        "scripts/source-hash.py",
        "scripts/skills-tree-hash.py",
        "scripts/setup-check.py",
        "knowledge/index.md",
        "knowledge/SCHEMA.md",
        "skills",
        "SKILLS.md",
    )
    for rel in required:
        if not os.path.exists(os.path.join(repo, rel)):
            errors.append(f"managed source missing: {rel}")
    if os.path.exists(os.path.join(repo, "templates/settings.json")):
        errors.append("legacy managed source present: templates/settings.json (use templates/hooks.json)")

    codex_agents = os.path.join(repo, "codex", "AGENTS.md")
    if os.path.isfile(codex_agents):
        text = read_text(codex_agents)
        if "# Direct Codex Policy" not in text or "Codex is the primary agent" not in text:
            errors.append("codex/AGENTS.md: missing direct-Codex primary-agent policy")
        if "# Claude-Invoked Mode Contract" in text or "Claude owns orchestration" in text:
            errors.append("codex/AGENTS.md: retired Claude caller contract must not be installed")

    root_next = os.path.join(repo, "NEXT.md")
    if os.path.isfile(root_next):
        fm = frontmatter(read_text(root_next))
        if "NEXT.md" in fm.get("unit_paths", "").split():
            errors.append("NEXT.md: unit_paths must not include root NEXT.md; it self-invalidates handoff-only commits")

    project_init = os.path.join(repo, "templates", "new-project-init.md")
    if os.path.isfile(project_init):
        text = read_text(project_init)
        if "/hooks" not in text or "trust" not in text.lower():
            errors.append("templates/new-project-init.md: missing /hooks trust step for project-local hooks")

    project_init_skill = os.path.join(repo, "skills", "project-init", "SKILL.md")
    if os.path.isfile(project_init_skill):
        text = read_text(project_init_skill)
        if "/hooks" not in text or "trust" not in text.lower():
            errors.append("skills/project-init/SKILL.md: missing /hooks trust boundary")

    for rel in ("scripts/install.py", "scripts/installer_support.py",
                "scripts/external-review.py", "scripts/secrets-gate.py"):
        if not os.path.isfile(os.path.join(repo, rel)):
            errors.append(f"managed source missing: {rel}")

    for rel in ("scripts/install-windows.ps1", "scripts/install-mac.sh"):
        text = read_text(os.path.join(repo, rel))
        if "install.py" not in text:
            errors.append(f"{rel}: launcher must invoke the shared install engine")

    try:
        source_tree = ast.parse(read_text(os.path.join(repo, "scripts", "source-hash.py")))
        uses_shared_paths = any(
            isinstance(node, ast.Attribute) and node.attr == "MANAGED_SOURCE_PATHS"
            for node in ast.walk(source_tree)
        )
        checker_paths = assigned_literal_set(
            os.path.join(repo, "scripts", "setup-check.py"),
            {"MANAGED_SOURCE_PATHS"},
        )
        if not uses_shared_paths or not checker_paths:
            errors.append("source-hash.py must consume setup-check.py MANAGED_SOURCE_PATHS")
    except (OSError, SyntaxError, ValueError, TypeError) as exc:
        errors.append(f"managed-source path-set lint failed: {exc}")

    sync_contracts = (
        ("scripts/sync.ps1", "Working tree is dirty"),
        ("scripts/sync.sh", "Working tree is dirty"),
        ("scripts/bootstrap-windows.ps1", "Target clone is dirty"),
        ("scripts/bootstrap-mac.sh", "Target clone is dirty"),
    )
    for rel, phrase in sync_contracts:
        path = os.path.join(repo, *rel.split("/"))
        if os.path.isfile(path):
            text = read_text(path)
            if "status --porcelain" not in text or phrase not in text:
                errors.append(f"{rel}: missing dirty working-tree abort guard")

    hooks_json = os.path.join(repo, "templates", "hooks.json")
    if os.path.isfile(hooks_json):
        try:
            with open(hooks_json, encoding="utf-8-sig") as f:
                cfg = json.load(f)
            hooks = cfg.get("hooks") if isinstance(cfg, dict) else None
            required_hooks = {
                "SessionStart": "freshness-inject.sh",
                "PreCompact": "compact-handoff-gate.sh",
                "Stop": "stop-handoff-gate.sh",
            }
            if not isinstance(hooks, dict):
                errors.append("templates/hooks.json: missing hooks object")
            else:
                for event, script in required_hooks.items():
                    groups = hooks.get(event)
                    matchers = []
                    seen_posix = False
                    seen_windows = False
                    windows_exit = False
                    if isinstance(groups, list):
                        for group in groups:
                            if not isinstance(group, dict):
                                continue
                            matchers.append(str(group.get("matcher", "")))
                            for hook in group.get("hooks", []):
                                if not isinstance(hook, dict):
                                    continue
                                if script in str(hook.get("command", "")):
                                    seen_posix = True
                                command_windows = str(hook.get("commandWindows", ""))
                                if script in command_windows:
                                    seen_windows = True
                                    if "exit $LASTEXITCODE" in command_windows:
                                        windows_exit = True
                            if seen_posix and seen_windows and windows_exit:
                                break
                    if not seen_posix:
                        errors.append(f"templates/hooks.json: {event} command does not invoke {script}")
                    if not seen_windows:
                        errors.append(f"templates/hooks.json: {event} commandWindows does not invoke {script}")
                    elif not windows_exit:
                        errors.append(f"templates/hooks.json: {event} commandWindows does not preserve hook exit code")
                    matcher_text = "|".join(matchers)
                    if event == "SessionStart":
                        for token in ("startup", "resume", "clear", "compact"):
                            if token not in matcher_text:
                                errors.append(f"templates/hooks.json: SessionStart matcher missing {token}")
                    if event == "PreCompact":
                        for token in ("manual", "auto"):
                            if token not in matcher_text:
                                errors.append(f"templates/hooks.json: PreCompact matcher missing {token}")
        except Exception as e:
            errors.append(f"templates/hooks.json: invalid JSON ({e})")

    stop_hook = os.path.join(repo, "templates", "hooks", "stop-handoff-gate.sh")
    compact_hook = os.path.join(repo, "templates", "hooks", "compact-handoff-gate.sh")
    if os.path.isfile(stop_hook) and os.path.isfile(compact_hook):
        stop_glob = work_glob(stop_hook)
        compact_glob = work_glob(compact_hook)
        if not stop_glob:
            errors.append("templates/hooks/stop-handoff-gate.sh: work glob not found")
        if not compact_glob:
            errors.append("templates/hooks/compact-handoff-gate.sh: work glob not found")
        if stop_glob and compact_glob and stop_glob != compact_glob:
            errors.append("Stop and PreCompact hook work globs differ; keep them aligned")
        required_glob_tokens = (
            "src/*", "docs/*", "package.json", "Cargo.toml", "go.mod",
            "pyproject.toml", "Dockerfile",
        )
        for token in required_glob_tokens:
            if stop_glob and token not in stop_glob:
                errors.append(f"hook work glob missing {token}")

        stop_body = next_lint_body(stop_hook)
        compact_body = next_lint_body(compact_hook)
        if not stop_body:
            errors.append("templates/hooks/stop-handoff-gate.sh: next_lint_reason body not found")
        if not compact_body:
            errors.append("templates/hooks/compact-handoff-gate.sh: next_lint_reason body not found")
        if stop_body and compact_body and stop_body != compact_body:
            errors.append("Stop and PreCompact hook NEXT schema checks differ; keep next_lint_reason aligned")
        for hook_path, body in ((stop_hook, stop_body), (compact_hook, compact_body)):
            rel = os.path.relpath(hook_path, repo).replace(os.sep, "/")
            if body:
                for phrase in NEXT_SCHEMA_PHRASES:
                    if phrase not in body:
                        errors.append(f"{rel}: NEXT schema check missing {phrase}")
                for marker in NEXT_SCHEMA_MARKERS:
                    if marker not in body:
                        errors.append(f"{rel}: NEXT schema check missing marker {marker}")

    executable_contracts = (
        "scripts/project-health.py",
        "templates/hooks/freshness-inject.sh",
    )
    for rel in executable_contracts:
        path = os.path.join(repo, *rel.split("/"))
        if os.path.isfile(path):
            text = read_text(path)
            for phrase in NEXT_SCHEMA_PHRASES:
                if phrase not in text:
                    errors.append(f"{rel}: NEXT schema contract missing {phrase}")
            for marker in NEXT_SCHEMA_MARKERS:
                if marker not in text:
                    errors.append(f"{rel}: NEXT schema contract missing marker {marker}")
            for context_path in CONTEXT_PATHS:
                if context_path not in text:
                    errors.append(f"{rel}: context WARN path missing {context_path}")

    skills_dir = os.path.join(repo, "skills")
    fs_skills = []
    if os.path.isdir(skills_dir):
        fs_skills = sorted(
            d for d in os.listdir(skills_dir)
            if os.path.isdir(os.path.join(skills_dir, d))
            and os.path.isfile(os.path.join(skills_dir, d, "SKILL.md"))
        )

    skills_md_path = os.path.join(repo, "SKILLS.md")
    table_skills = []
    if os.path.isfile(skills_md_path):
        table_skills = sorted(set(
            re.findall(r"^\|\s*`([a-z][a-z0-9-]*)`\s*\|", read_text(skills_md_path), re.MULTILINE)
        ))

    for skill in fs_skills:
        fp = os.path.join(skills_dir, skill, "SKILL.md")
        head = read_text(fp)[:4096]
        if not head.startswith("---"):
            errors.append(f"skills/{skill}/SKILL.md: missing YAML frontmatter")
            continue
        boundary = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", head, re.S)
        if not boundary:
            errors.append(f"skills/{skill}/SKILL.md: unterminated YAML frontmatter")
            continue
        try:
            metadata = yaml.safe_load(boundary.group(1))
        except yaml.YAMLError as exc:
            errors.append(f"skills/{skill}/SKILL.md: invalid YAML ({exc})")
            continue
        if not isinstance(metadata, dict) or not isinstance(metadata.get("description"), str):
            errors.append(f"skills/{skill}/SKILL.md: description must be a YAML string")
            continue
        m = re.search(r"^name:\s*(\S+)", head, re.MULTILINE)
        if not m:
            errors.append(f"skills/{skill}/SKILL.md: missing name")
        elif m.group(1) != skill:
            errors.append(f"skills/{skill}/SKILL.md: name {m.group(1)!r} != directory {skill!r}")
        if not re.search(r"^description:\s*\S+", head, re.MULTILINE):
            errors.append(f"skills/{skill}/SKILL.md: missing description")

    fs_set, table_set = set(fs_skills), set(table_skills)
    only_fs = sorted(fs_set - table_set)
    only_table = sorted(table_set - fs_set)
    if only_fs:
        errors.append(f"skills/ has {only_fs} but SKILLS.md table is missing them")
    if only_table:
        errors.append(f"SKILLS.md table has {only_table} but skills/ is missing them")

    if errors:
        print("Lint failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"  Lint OK: {len(fs_skills)} Codex skills consistent (skills/, SKILLS.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
