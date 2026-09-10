#!/usr/bin/env python3
"""Run one Mode-N prompt through the native `claude` CLI and publish the artifact.

Why this exists, when a copy-pasteable recipe already did: the recipe hardcoded a
model. `/ask claude` therefore ran whatever the document said rather than what the
project pinned, and on 2026-08-25 that silently produced a review on the wrong
model in a 15-round sequence. The codex side had already been moved behind an
executor for exactly this class ("the config declared one model and five of six
runs used another"); the claude side was left as prose and reproduced the defect.

Three things the recipe could not do and this does:

  * reads the project's pin and renders the flags from it, so the model is a
    property of the project rather than of the documentation;
  * prepends the shared mode contract (`~/.codex/AGENTS.md`) itself -- a `claude -p`
    session does not load it, and "remember to prepend it" is not a mechanism;
  * recovers the model that ACTUALLY ran. `claude -p` writes no run header, which
    is what codex's artifact verification reads, so the claude artifact used to
    record a request and call it a report. `--output-format json` carries
    `modelUsage`, keyed by the model the provider billed, and that key is what
    lands in the artifact.

Effort is NOT recoverable: the envelope does not carry it. The artifact says so
rather than restating the request as though it were confirmed.

Egress, publication and failure handling are ask-codex.py's -- imported, not
copied, so the scanner-refuses-then-nothing-is-sent contract has one
implementation and cannot drift between backends.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
CODEX_EXECUTOR = HERE / "ask-codex.py"
# The shared Mode 1/2/3/3B contract. codex loads it natively; claude cannot.
MODE_CONTRACT = Path.home() / ".codex" / "AGENTS.md"

TOOLS = "Read,Grep,Glob"
DENIED = "Write,Edit,NotebookEdit,Bash,PowerShell,Agent,Task,Workflow"
# The harness's known proxy is env-injected, so the family flip is only real if
# these are cleared for the child. A settings-file apiKeyHelper or an OS-wide
# HTTP proxy would still need separately curated settings.
PROXY_ENV = (
    "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL", "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "ANTHROPIC_BEDROCK_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS",
)


def load_codex_executor():
    spec = importlib.util.spec_from_file_location("community_ask_codex", str(CODEX_EXECUTOR))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_claude(explicit, project_root):
    """(absolute path, error). Same rule as the codex resolver: `shutil.which`
    puts the current directory first on Windows, and a same-named file inside the
    project under review would be just as wrong."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            return None, "the --claude path does not exist: %s" % path
        return str(path.resolve()), None
    found = shutil.which("claude", path=os.environ.get("PATH", ""))
    if not found:
        return None, "claude is not on PATH (pass --claude to name it explicitly)"
    path = Path(found).resolve()
    for label, directory in (("the current directory", Path.cwd()),
                             ("the project under review", Path(project_root))):
        try:
            resolved = Path(directory).resolve()
        except OSError:
            continue
        if path == resolved or resolved in path.parents:
            return None, ("the claude on PATH resolves inside %s (%s) -- refusing. "
                          "Pass --claude to name the installed CLI." % (label, path))
    return str(path), None


def build_argv(executable, flags):
    return [str(executable), "-p", "--permission-mode", "dontAsk",
            "--tools", TOOLS, "--disallowedTools", DENIED,
            "--strict-mcp-config", "--no-chrome", "--no-session-persistence",
            "--output-format", "json"] + list(flags)


def build_env(base=None):
    env = dict(os.environ if base is None else base)
    for name in PROXY_ENV:
        env.pop(name, None)
    return env


def compose_prompt(prompt_text, contract=None):
    """(text, note). The contract is prepended when it is readable; when it is
    not, the caller is TOLD rather than silently sending a headerless prompt --
    AGENTS.md treats a prompt without the mode contract as advisory, so its
    absence changes what the review is."""
    path = Path(contract) if contract is not None else MODE_CONTRACT
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return prompt_text, ("the mode contract at %s could not be read -- the "
                             "prompt was sent WITHOUT it" % path)
    return text + "\n\n---\n\n" + prompt_text, None


def parse_envelope(stdout):
    """(body, model, error). `result` is the review; `modelUsage` is keyed by what
    actually ran. More than one key means the run switched models mid-way, which is
    reported rather than collapsed to the first."""
    try:
        data = json.loads(stdout or "")
    except (json.JSONDecodeError, TypeError):
        return None, None, "the CLI did not return a JSON envelope"
    if not isinstance(data, dict):
        return None, None, "the CLI returned JSON that is not an object"
    body = data.get("result")
    usage = data.get("modelUsage")
    model = None
    if isinstance(usage, dict) and usage:
        names = sorted(usage)
        model = names[0] if len(names) == 1 else "+".join(names)
    return (body if isinstance(body, str) else None), model, None


def model_verdict(pin, model):
    if model is None:
        return "UNREPORTED -- the envelope named no model; what ran is unknown"
    if pin is None:
        return "UNPINNED -- ran on %s; nothing was requested" % model
    if model == pin["model"]:
        return "MATCH -- ran on %s (effort requested %s, not reported by this CLI)" % (
            model, pin["effort"])
    return "MISMATCH -- requested %s, ran on %s" % (pin["model"], model)


def render_artifact(pin, model, verdict, returncode, body, sections=(), notes=(), codex=None):
    """Every dynamic scalar JSON-quoted, so provider-controlled text cannot
    reshape the front matter."""
    fields = [
        ("backend", "claude"),
        ("requested", ("%s at %s effort" % (pin["model"], pin["effort"])) if pin else "(unpinned)"),
        ("reported_model", model or "(unreported)"),
        ("reported_effort", "(not reported by claude -p)"),
        ("header_verdict", verdict),
        ("exit_code", str(returncode)),
    ]
    text = "---\n" + "".join("%s: %s\n" % (k, json.dumps(v)) for k, v in fields) + "---\n\n"
    for note in notes:
        if note:
            text += "> NOTE: %s\n\n" % note
    assert codex is not None
    text += (codex.clean(body or "")).rstrip() + "\n"
    for title, section in sections:
        if section:
            text += "\n## %s\n\n%s\n" % (title, section)
    return text


def read_pin(review, project_root):
    """Read configuration and render flags within the same failure boundary."""
    try:
        state, pin = review.pin_state(project_root, "claude")
        flags = review.flags_for("claude", pin) if state == "pinned" else []
    except Exception as exc:
        return None, None, "the external-review helper failed (%s)" % type(exc).__name__
    return state, (pin, flags), None


def run(prompt_file, project_root, out, claude=None, model=None, effort=None,
        spawn=None, scan_fn=None, contract=None):
    spawn = spawn or subprocess.run
    project_root = Path(project_root).expanduser().resolve()
    target = Path(out).expanduser()
    codex = load_codex_executor()

    try:
        preflight = codex.load_preflight()
    except Exception as exc:
        print("ask-claude: the egress scanner could not be loaded (%s) -- refusing"
              % type(exc).__name__, file=sys.stderr)
        return 2
    scan_fn = scan_fn or (lambda text: codex.scan(text, preflight))

    try:
        prompt_text = Path(prompt_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print("ask-claude: could not read the prompt (%s)" % type(exc).__name__, file=sys.stderr)
        return 2

    prompt_text, context_note = codex.compose_review_context(prompt_text, project_root)
    if context_note:
        print("ask-claude: " + context_note, file=sys.stderr)
    prompt_text, contract_note = compose_prompt(prompt_text, contract)
    if contract_note:
        print("ask-claude: " + contract_note, file=sys.stderr)

    # Scanned AFTER composition: what is scanned must be what is sent.
    try:
        code, message = scan_fn(prompt_text)
    except Exception as exc:  # a gate that crashes must not read as a pass
        print("ask-claude: the preflight scan itself failed (%s) -- nothing sent"
              % type(exc).__name__, file=sys.stderr)
        return 2
    if code != 0:
        print("ask-claude: prompt did not pass preflight -- %s" % message, file=sys.stderr)
        return 1 if code == 1 else 2

    try:
        review = codex.load_review_helper()
    except Exception as exc:
        print("ask-claude: the trusted external-review helper failed to load (%s) -- "
              "refusing rather than falling back" % type(exc).__name__, file=sys.stderr)
        return 2
    if review is None:
        print("ask-claude: no external-review helper at a documented clone location. "
              "Refusing.", file=sys.stderr)
        return 2
    state, found, error = read_pin(review, project_root)
    if error:
        print("ask-claude: %s -- refusing" % error, file=sys.stderr)
        return 2
    if state == "invalid":
        print("ask-claude: the review config cannot be read -- fix it before reviewing",
              file=sys.stderr)
        return 1
    assert found is not None
    pin, flags = found
    override_note = None
    if state != "pinned":
        why = ("no review config for this project" if state == "missing"
               else "no claude pin for this project")
        if model:
            # An explicit pair is a stated choice, not a default: it is rendered
            # into the artifact as the request so the run stays auditable.
            pin = {"model": model, "effort": effort or "high"}
            flags = review.flags_for("claude", pin)
            override_note = ("%s -- ran on the flags given on the command line "
                             "(%s at %s effort), not a project pin"
                             % (why, pin["model"], pin["effort"]))
            print("ask-claude: " + override_note, file=sys.stderr)
        else:
            print("ask-claude: %s -- running WITHOUT a pin, on the CLI default model"
                  % why, file=sys.stderr)

    executable, error = resolve_claude(claude, project_root)
    if executable is None:
        print("ask-claude: %s" % error, file=sys.stderr)
        return 2
    try:
        done = spawn(build_argv(executable, flags), input=prompt_text,
                     env=build_env(), capture_output=True,
                     text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        print("ask-claude: claude could not be started (%s) -- check the installation"
              % type(exc).__name__, file=sys.stderr)
        return 2

    body, ran_model, envelope_error = parse_envelope(done.stdout)
    verdict = model_verdict(pin, ran_model)
    diagnostic = "ask-claude: " + verdict + "\n"

    failed = done.returncode != 0 or body is None
    try:
        if failed:
            # A failed run's output is diagnostic; the contract still promises a
            # marked artifact, so a blocked part is withheld rather than sinking
            # the file. A SUCCESSFUL run with blocked output still refuses.
            sections = [("stdout", codex.withhold_or_keep(done.stdout, preflight, "stdout")),
                        ("stderr", codex.withhold_or_keep(done.stderr, preflight, "stderr"))]
            body = ""
        else:
            sections = []
    except Exception as exc:
        print("ask-claude: scanning the diagnostic output failed (%s) -- nothing published"
              % type(exc).__name__, file=sys.stderr)
        return 2

    text = render_artifact(pin, ran_model, verdict, done.returncode, body,
                           sections, (contract_note, override_note, envelope_error), codex)
    try:
        for payload in (diagnostic, text):
            out_code, out_message = scan_fn(payload)
            if out_code != 0:
                break
    except Exception as exc:
        print("ask-claude: the output scan itself failed (%s) -- nothing published"
              % type(exc).__name__, file=sys.stderr)
        return 2
    if out_code != 0:
        print("ask-claude: the output did not pass preflight -- %s. "
              "Nothing written." % out_message, file=sys.stderr)
        return 1 if out_code == 1 else 2
    print(diagnostic, end="", file=sys.stderr)
    try:
        written = codex.publish(text, target)
    except OSError as exc:
        print("ask-claude: the review ran but could not be written (%s)"
              % type(exc).__name__, file=sys.stderr)
        return 2
    print(written)
    if failed:
        print("ask-claude: claude exited %s%s -- artifact written and marked"
              % (done.returncode, ("; " + envelope_error) if envelope_error else ""),
              file=sys.stderr)
        return 3
    return 0


def main():
    module = load_codex_executor()
    module._configure_streams()
    parser = argparse.ArgumentParser(prog="ask-claude.py")
    parser.add_argument("prompt_file")
    parser.add_argument("--out", required=True,
                        help="artifact path; nothing is derived, so nothing is claimed "
                             "about where output lands (see SKILL.md for the convention)")
    parser.add_argument("--project-root", default=None,
                        help="project whose pin is read (default: the current directory)")
    parser.add_argument("--claude", default=None,
                        help="path to the installed claude CLI; without it, PATH is "
                             "trusted and results inside cwd/project are refused")
    parser.add_argument("--model", default=None,
                        help="used ONLY when the project has no claude pin; recorded in "
                             "the artifact as the request so the run stays auditable")
    parser.add_argument("--effort", default=None, help="effort for --model (default: high)")
    args = parser.parse_args()
    return run(args.prompt_file, args.project_root or os.getcwd(), args.out,
               args.claude, args.model, args.effort)


if __name__ == "__main__":
    sys.exit(main())
