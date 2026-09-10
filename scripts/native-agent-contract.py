#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.native_agents.boundary import ContractError, Event, JsonMap, Store, context, deny
from scripts.native_agents.catalog import CatalogError, discover
from scripts.native_agents.audit import summary
from scripts.native_agents.completion import post, stopped
from scripts.native_agents.routing import attest, pre, revoke, status


def main() -> int:
    parser = argparse.ArgumentParser(description="Native Codex role pins and runtime identity evidence")
    parser.add_argument("mode", choices=("session", "pre", "post", "subagent-stop", "status"))
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--cwd", type=Path)
    parser.add_argument("--session-id")
    parser.add_argument("--codex-bin", default="codex")
    args = parser.parse_args()
    ambient_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    effective_home = args.home or ambient_home
    state_root = args.state_dir or effective_home / "dev-setup-codex/native-agents"
    if args.home is not None:
        routing_home = args.home
    elif (state_root.name == "native-agents"
          and state_root.parent.name == "dev-setup-codex"):
        routing_home = state_root.parent.parent
    else:
        routing_home = None
    store = Store(state_root)
    output: JsonMap
    try:
        raw = json.dumps({"cwd": str(args.cwd.resolve()), "session_id": args.session_id or "status"}) if args.cwd else sys.stdin.read(1_048_577)
        event = Event.parse(raw)
        if args.mode == "status" and args.cwd and not args.session_id:
            event = store.latest(event)
        match args.mode:
            case "session":
                revoke(event, store)
                output = attest(event, store, discover([args.codex_bin, "app-server"]), routing_home)
            case "pre":
                output = pre(event, store, routing_home)
            case "post":
                output = post(event, store)
            case "subagent-stop":
                output = stopped(event, store)
            case "status":
                output = status(event, store, routing_home)
                completion = summary(store, store.bind(event).root)
                output["completion"] = {
                    "verified": completion["verified"], "pending": completion["pending"],
                    "unregistered": completion["unregistered"], "unverified": completion["unverified"],
                    "mismatch": completion["mismatch"], "damaged": completion["damaged"],
                    "attention": completion["attention"],
                }
            case _:
                raise ContractError("unsupported_mode")
    except (ContractError, CatalogError, OSError, UnicodeError) as exc:
        code = exc.code if isinstance(exc, (ContractError, CatalogError)) else "io_failure"
        if args.mode == "pre":
            output = deny(code)
        elif args.mode == "status":
            output = {"state": "UNVERIFIED", "code": code}
        else:
            event_name = {"session": "SessionStart", "post": "PostToolUse", "subagent-stop": "SubagentStop"}[args.mode]
            output = {"systemMessage": f"Native agent contract UNVERIFIED: {code}"} if args.mode == "subagent-stop" else context(event_name, "UNVERIFIED", code)
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
