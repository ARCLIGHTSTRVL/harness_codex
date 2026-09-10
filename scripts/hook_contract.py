#!/usr/bin/env python3
"""Static Codex bootstrap wiring checks; never executes project commands.

An exact seeded launcher can be recognized. Custom shell commands remain
unverified, and neither recognition nor file versions prove /hooks trust or
live event delivery. Claude transcript liveness is intentionally not used.
"""
import json
from pathlib import Path
import re


def check(root: Path) -> list[str]:
    config = root / ".codex/hooks.json"
    warnings: list[str] = []
    if (root / ".codex/settings.json").is_file():
        warnings.append("legacy settings.json present; Codex local hooks use hooks.json")
    if not config.is_file():
        return warnings + ["hooks.json missing"]
    try:
        data = json.loads(config.read_text(encoding="utf-8-sig"))
        template = json.loads((Path(__file__).resolve().parents[1] / "templates/hooks.json").read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return warnings + [f"hook config/template unreadable ({type(exc).__name__})"]
    if not isinstance(data, dict) or not isinstance(data.get("hooks"), dict):
        return warnings + ["hook config has no hooks table"]
    hooks = data["hooks"]
    required = {
        "SessionStart": ("freshness-inject.sh", ("startup", "resume", "clear", "compact")),
        "PreCompact": ("compact-handoff-gate.sh", ("manual", "auto")),
        "Stop": ("stop-handoff-gate.sh", ("",)),
    }
    for event, (script, sources) in required.items():
        groups = hooks.get(event)
        if not isinstance(groups, list):
            warnings.append(f"{event} hook groups missing or malformed")
            continue
        covered: set[str] = set()
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                warnings.append(f"{event} hook group malformed")
                continue
            matcher = group.get("matcher", "")
            if not isinstance(matcher, str):
                warnings.append(f"{event} matcher is not a string")
                continue
            try:
                matched = {source for source in sources if not matcher or re.fullmatch(matcher, source)}
            except re.error:
                warnings.append(f"{event} matcher is invalid")
                continue
            for hook in group["hooks"]:
                if not isinstance(hook, dict) or hook.get("type") != "command":
                    continue
                command = hook.get("command")
                windows = hook.get("commandWindows")
                if not isinstance(command, str) or script not in command:
                    continue
                if not isinstance(windows, str) or script not in windows:
                    warnings.append(f"{event} commandWindows missing {script}")
                    continue
                if "exit $LASTEXITCODE" not in windows:
                    warnings.append(f"{event} commandWindows does not preserve hook exit code")
                    continue
                seeded = template["hooks"][event][0]["hooks"][0]
                if command != seeded["command"] or windows != seeded["commandWindows"]:
                    warnings.append(f"{event} custom command execution UNVERIFIED; compare with templates/hooks.json")
                    continue
                covered.update(matched)
        if covered != set(sources):
            warnings.append(f"{event} seeded launcher/matcher coverage missing: {', '.join(sorted(set(sources) - covered)) or 'Stop'}")
        if not (root / ".codex/hooks" / script).is_file():
            warnings.append(f"{script} MISSING")
    if not (root / ".codex/hooks/plan-handoff.py").is_file():
        warnings.append("plan-handoff.py MISSING; SessionStart saved-plan recovery unavailable")
    return warnings
