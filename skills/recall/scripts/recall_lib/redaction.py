#!/usr/bin/env python3
from dataclasses import dataclass
import importlib.util
from pathlib import Path
import re
from typing import Callable, Final

RULES: Final = (("private-key", "PRIVATE_KEY"), ("known-credential", "KNOWN_SECRET"),
               ("url-credential", "URL_CREDENTIAL"), ("assignment", "ASSIGNMENT"),
               ("npm-auth", "NPM_AUTH"), ("bearer", "BEARER"))
PEM_END: Final = re.compile(r"-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----", re.IGNORECASE)
MARKER: Final = re.compile(r"<redacted: [a-z -]+>")


@dataclass(frozen=True, slots=True)
class Scanner:
    rules: tuple[tuple[str, re.Pattern[str]], ...]
    scan: Callable[[str], list[str]]

    def redact(self, text: str) -> str:
        if "credential-file diff" in self.scan(text):
            return "<redacted: credential-file diff>"
        output: list[str] = []
        inside_key = False
        for line in text.split("\n"):
            if inside_key:
                output.append("<redacted: private-key>")
                inside_key = not bool(PEM_END.search(line))
                continue
            rule = next((name for name, pattern in self.rules if pattern.search(line)), None)
            if rule == "private-key":
                inside_key = not bool(PEM_END.search(line))
            output.append(f"<redacted: {rule}>" if rule else line)
        return "\n".join(output)

    def snippet(self, body: str, pattern: re.Pattern[str]) -> str:
        safe = self.redact(body)
        match = pattern.search(safe)
        if match is None:
            original = pattern.search(body)
            line_index = body.count("\n", 0, original.start()) if original else 0
            offset = sum(len(line) + 1 for line in safe.split("\n")[:line_index])
            match = MARKER.search(safe, offset)
        start = max(0, match.start() - 40) if match else 0
        end = min(len(safe), match.end() + 80) if match else 120
        return ("..." if start else "") + " ".join(safe[start:end].split()) + ("..." if end < len(safe) else "")


def load_scanner() -> Scanner | None:
    path = Path(__file__).resolve().parents[3] / "ask/scripts/ask-preflight.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("ask_preflight_for_recall", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return Scanner(tuple((name, getattr(module, attr)) for name, attr in RULES), module.scan)
