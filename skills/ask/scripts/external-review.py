#!/usr/bin/env python3
"""Read project-owned reviewer pins without importing Claude agent routing."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
from typing import Final, Literal, NotRequired, TypedDict

CONFIG_REL: Final = Path(".codex") / "external-review.json"
EXTERNAL_BACKENDS: Final = ("claude", "codex")
CODEX_CATALOG: Final = Path.home() / ".codex" / "opencodex-catalog.json"
EFFORT_KEY: Final = "model_reasoning_effort"
SLUG: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+/-]{0,127}\Z")
State = Literal["missing", "unpinned", "pinned", "invalid"]
Catalog = dict[str, list[str]]


class Pin(TypedDict):
    model: str
    effort: str
    selected_at: NotRequired[str]


class ReviewConfig(TypedDict):
    schema: int
    external_review: dict[str, Pin]
    catalogs: dict[str, Catalog]


class ConfigError(ValueError):
    """The project review configuration cannot be interpreted safely."""


def load_config(path: Path) -> ReviewConfig:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict) or raw.get("schema") != 1:
        raise ConfigError("external-review.json requires schema 1")
    pins = raw.get("external_review", {})
    catalogs = raw.get("catalogs", {})
    if not isinstance(pins, dict) or not isinstance(catalogs, dict):
        raise ConfigError("external_review and catalogs must be objects")
    parsed: ReviewConfig = {"schema": 1, "external_review": {}, "catalogs": {}}
    for backend, pin in pins.items():
        if backend not in EXTERNAL_BACKENDS or not isinstance(pin, dict):
            raise ConfigError("unsupported review backend or pin shape")
        model, effort = pin.get("model"), pin.get("effort")
        if (not isinstance(model, str) or not SLUG.fullmatch(model)
                or not isinstance(effort, str) or not SLUG.fullmatch(effort)):
            raise ConfigError("pin model and effort must be nonempty slugs")
        value: Pin = {"model": model, "effort": effort}
        if "selected_at" in pin:
            if not isinstance(pin["selected_at"], str):
                raise ConfigError("selected_at must be a string")
            value["selected_at"] = pin["selected_at"]
        parsed["external_review"][backend] = value
    for backend, models in catalogs.items():
        if backend not in EXTERNAL_BACKENDS or not isinstance(models, dict):
            raise ConfigError("catalogs must map backends to model objects")
        parsed_models: Catalog = {}
        for model, efforts in models.items():
            if (not isinstance(model, str) or not SLUG.fullmatch(model)
                    or not isinstance(efforts, list)
                    or not all(isinstance(e, str) and SLUG.fullmatch(e) for e in efforts)):
                raise ConfigError("catalog model ids map to effort lists")
            parsed_models[model] = efforts
        parsed["catalogs"][backend] = parsed_models
    return parsed


def pin_state(project_root: str | Path, backend: str) -> tuple[State, Pin | None]:
    if backend not in EXTERNAL_BACKENDS:
        return "invalid", None
    path = Path(project_root) / CONFIG_REL
    try:
        config = load_config(path)
    except FileNotFoundError:
        return "missing", None
    except (OSError, UnicodeError, ValueError):
        return "invalid", None
    pin = config["external_review"].get(backend)
    return ("pinned", pin) if pin else ("unpinned", None)


def read_pin(project_root: str | Path, backend: str) -> Pin | None:
    return pin_state(project_root, backend)[1]


def codex_flags(pin: Pin) -> list[str]:
    return ["-m", pin["model"], "-c", f"{EFFORT_KEY}={pin['effort']}"]


def claude_flags(pin: Pin) -> list[str]:
    return ["--model", pin["model"], "--effort", pin["effort"]]


def flags_for(backend: str, pin: Pin) -> list[str]:
    renderers = {"codex": codex_flags, "claude": claude_flags}
    if backend not in renderers:
        raise ConfigError(f"no flag renderer for backend {backend!r}")
    return renderers[backend](pin)


def catalog_models(path: str | Path | None = None) -> Catalog | None:
    try:
        raw = json.loads(Path(path or CODEX_CATALOG).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("models"), list):
        return None
    models: Catalog = {}
    for row in raw["models"]:
        if not isinstance(row, dict):
            continue
        slug = row.get("slug") or row.get("id")
        if not isinstance(slug, str) or not slug:
            continue
        levels = row.get("supported_reasoning_levels") or []
        if not isinstance(levels, list):
            continue
        efforts = []
        for level in levels:
            name = level.get("effort") if isinstance(level, dict) else level
            if isinstance(name, str) and name:
                efforts.append(name)
        models[slug] = efforts
    return models or None


def catalog_for(backend: str, project_root: str | Path) -> Catalog | None:
    config: ReviewConfig
    try:
        config = load_config(Path(project_root) / CONFIG_REL)
    except (OSError, UnicodeError, ValueError):
        config = {"schema": 1, "external_review": {}, "catalogs": {}}
    recorded = config["catalogs"].get(backend)
    return recorded or (catalog_models() if backend == "codex" else None)


def verify_pin(pin: Pin | None, models: Catalog | None,
               state: State = "pinned") -> tuple[bool, str]:
    if state == "invalid":
        return False, "INVALID -- the review config cannot be read"
    if pin is None:
        return True, "UNSET -- no external review model pinned for this project"
    shown = f"{pin['model']} at {pin['effort']} effort"
    if models is None:
        return True, f"UNVALIDATED -- {shown}; no provider catalog on this machine"
    if pin["model"] not in models:
        return False, f"INVALID -- {pin['model']} is not in this machine's provider catalog"
    efforts = models[pin["model"]]
    if efforts and pin["effort"] not in efforts:
        return False, f"INVALID -- {pin['model']} does not offer {pin['effort']} effort"
    return True, "PINNED -- " + shown


def status(project_root: str | Path, backend: str = "claude",
           models: Catalog | None = None) -> tuple[bool, str]:
    state, pin = pin_state(project_root, backend)
    return verify_pin(pin, catalog_for(backend, project_root) if models is None else models, state)


def status_all(project_root: str | Path) -> tuple[bool, str]:
    verdicts = [(backend, status(project_root, backend)) for backend in EXTERNAL_BACKENDS]
    return (all(result[0] for _, result in verdicts),
            " | ".join(f"{backend}: {result[1]}" for backend, result in verdicts))


def main() -> int:
    args = sys.argv[1:]
    if not 1 <= len(args) <= 3 or args[0] not in ("status", "flags"):
        print("usage: external-review.py status|flags [project-root] [claude|codex]", file=sys.stderr)
        return 2
    command, root = args[0], args[1] if len(args) > 1 else os.getcwd()
    backend = args[2] if len(args) > 2 else "claude"
    if backend not in EXTERNAL_BACKENDS:
        print("external-review: unsupported backend", file=sys.stderr)
        return 2
    if command == "status":
        ok, verdict = status_all(root) if len(args) < 3 else status(root, backend)
        print("external-review: " + verdict)
        return 0 if ok else 1
    state, pin = pin_state(root, backend)
    if state != "pinned" or pin is None:
        print(f"external-review: {state} -- no usable {backend} pin", file=sys.stderr)
        return 1
    print(" ".join(flags_for(backend, pin)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
