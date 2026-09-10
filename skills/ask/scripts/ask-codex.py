#!/usr/bin/env python3
"""One-process executor for the `/ask codex` path: scan, pin, spawn, scan, stamp.

WHY THIS EXISTS -- two measured failures, both of delivery, not of design:

1. The LazyCodex/OMO config-migration notices contaminated three review artifacts
   in `resonance` (2026-07-21->30), one with a self-contradicting trailing verdict.
   The fix already existed -- LAZYCODEX_CONFIG_MIGRATION_DISABLED=1 -- and kept
   being LOST, because the documented PowerShell recipe sets it as a separate
   statement and a caller that splits the recipe across two tool calls sends the
   assignment to a shell that has already exited. Here the variable is placed in
   the child's env dict by the same process that spawns it; there is no window.
2. The pin was rendered but splicing it was discipline: measured 2026-08-02, the
   config declared one model and five of six runs used another. Here the flags
   come from `external-review.codex_flags` straight into argv.

WHAT THIS DOES NOT DO, and why the list is deliberate.

Three review rounds produced eleven Criticals. Two of the round-3 ones were
incomplete versions of round-2 fixes, and every single failing area was a
*discovery* feature -- the tool working out for itself where the helper, the CLI
or the output belonged. The core it was justified by never failed.

So the discovery was removed rather than hardened, because a tool that does not
resolve a location cannot resolve it wrongly:

- The output path is REQUIRED (`--out`). Nothing is derived, so nothing is
  claimed about confinement, and there is no resolve-then-reopen window to race.
  The naming convention lives in SKILL.md, where being wrong costs a filename.
- The helper is loaded ONLY from the clone locations `<dev_setup_policy>` names.
  The install-relative candidate was removed: in an installed skill it resolved
  to `~/.codex/scripts/`, which the installer does not own or create, so the
  first "installation-owned" candidate was not installation-owned at all -- and
  the suite could never see it, because tests run from the repo copy where that
  arithmetic happens to be right.
- The CLI is taken from `--codex` when given. Otherwise it is resolved from PATH
  and rejected if it lands in the caller's cwd, the repo, or the project. That
  leaves ONE stated assumption -- that PATH itself is trusted -- rather than a
  guarantee this tool cannot make.

THE RULE TWO ROUNDS WERE SPENT LEARNING: scan the bytes you send, in the form you
send them, never a pathname. `ask-preflight.verdict()` is called in-process on the
exact string; it exists so there is one definition of the answer rather than a
copy here. Round 3 confirmed this one is structural.

SCOPE: the codex path only, and NOT enforcement. `codex exec` by hand still works
and skips every check here. A hook that tried to refuse that was withdrawn after
three rounds and 17 Majors.

DEFERRED, reviewed and accepted as reasonable: publication is exclusive
(`O_EXCL`) but not atomic, so a mid-write failure can leave a partial file; and
files are created with default permissions (the artifacts directory is
gitignored, so this is local readability, not egress).

The Codex port uses .codex/external-review.json and documented Codex clone roots.

Exit: 0 = artifact written, 1 = a payload was BLOCKED, 2 = usage/environment/
refusal, 3 = codex itself failed (artifact still written and marked).
"""
import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PREFLIGHT = HERE / "ask-preflight.py"
MIGRATION_ENV = "LAZYCODEX_CONFIG_MIGRATION_DISABLED"
# codex writes its run header to stderr as `model: <slug>` / `reasoning effort: <x>`.
# The captured value is bounded to a slug grammar: a header is provider-controlled
# text that lands in published YAML, and `model: [x]` would publish as a sequence
# rather than the string it reported.
#
# Named SLUG_GRAMMAR, not SAFE_TOKEN: the first spelling tripped this repo's own
# credential gate, because an identifier containing TOKEN followed by `=` reads as
# a credential assignment. Recorded rather than quietly conformed to.
SLUG_GRAMMAR = re.compile(r"^[A-Za-z0-9._:+-]{1,64}$")
HEADER_MODEL = re.compile(r"(?im)^\s*model:\s*(\S+)\s*$")
HEADER_EFFORT = re.compile(r"(?im)^\s*reasoning effort:\s*(\S+)\s*$")
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
STDERR_KEEP = 40000
STDERR_HEAD_SHARE = 0.75
PROCESS_REPORT = re.compile(r"PID\s+\d+")
# Calibrated against the codepage this machine produces. Other codepages land on
# both sides of it, which is why a line over the bar is set aside rather than cut.
FOREIGN_DENSITY = 0.45


def _configure_streams():
    for stream in (sys.stdout, sys.stderr):
        try:
            if isinstance(stream, io.TextIOWrapper):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover
            pass


def helper_candidates():
    """The helper ships alongside this trusted executor."""
    return [HERE / "external-review.py"]


def load_module_at(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_review_helper(candidates=None):
    """The FIRST existing trusted candidate, or None. An import failure is
    terminal, never a fall-through to a weaker candidate."""
    for candidate in (helper_candidates() if candidates is None else candidates):
        if Path(candidate).is_absolute() and Path(candidate).is_file():
            return load_module_at(candidate, "community_external_review")
    return None


def load_preflight():
    return load_module_at(PREFLIGHT, "community_ask_preflight")


def scan(text, preflight=None):
    """(exit_code, message) for a string, decided IN PROCESS. No temp file, no
    pathname, no window between the scan and the send."""
    return (preflight or load_preflight()).verdict(text)


REVIEW_CONTEXT_REL = Path(".codex") / "review-context.md"


def compose_review_context(prompt_text, project_root):
    """(text, note). The project's review context -- its trust boundary and review scope --
    is prepended to the prompt by code, before the preflight scan, so every /ask on that
    project carries it and what is scanned is what is sent. Absence is reported, not
    silent: a review audited against the reviewer's default boundary is a different
    review (deltas 076, 119, 121)."""
    path = Path(project_root) / REVIEW_CONTEXT_REL
    try:
        context = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return prompt_text, ("no review context at %s -- the prompt was sent WITHOUT the "
                             "project's trust boundary and review scope" % path)
    if not context.strip():
        return prompt_text, "the review context at %s is empty -- sent WITHOUT it" % path
    return context.rstrip("\n") + "\n\n---\n\n" + prompt_text, None


def resolve_codex(explicit, repo, project_root):
    """(absolute path, error).

    `shutil.which` puts the current directory first on Windows, and a same-named
    file in the repo or the project would be just as wrong, so all three are
    rejected. What remains is the stated assumption that PATH is trusted; a caller
    who does not want to make it passes `--codex`."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            return None, "the --codex path does not exist: %s" % path
        return str(path.resolve()), None
    found = shutil.which("codex", path=os.environ.get("PATH", ""))
    if not found:
        return None, "codex is not on PATH (pass --codex to name it explicitly)"
    path = Path(found).resolve()
    for label, directory in (("the current directory", Path.cwd()),
                             ("the repo under review", Path(repo)),
                             ("the project under review", Path(project_root))):
        try:
            resolved = Path(directory).resolve()
        except OSError:
            continue
        if path == resolved or resolved in path.parents:
            return None, ("the codex on PATH resolves inside %s (%s) -- refusing. "
                          "Pass --codex to name the installed CLI." % (label, path))
    return str(path), None


def build_argv(executable, repo, flags):
    """`-` makes codex read the prompt from stdin, which keeps a long or
    multi-line prompt off the command line entirely."""
    return [str(executable), "exec", "-C", str(repo), "-s", "read-only"] + list(flags) + ["-"]


def build_env(base=None):
    env = dict(os.environ if base is None else base)
    # Assignment, not setdefault: an ambient "0" is exactly the case that has to
    # lose, and setdefault would let it through.
    env[MIGRATION_ENV] = "1"
    return env


def clean(text):
    return CONTROL_CHARS.sub("", text or "")


def partition_foreign_lines(text):
    """(body, set_aside) -- lines that look like OS-tool teardown, MOVED, never deleted.

    The child's process-tree teardown runs OS tools that write the console OEM
    codepage into the same pipe codex writes UTF-8 to. One decode cannot be right
    for both, so those lines arrive already mangled and no encoding recovers them.

    They are identified by three agreeing signals -- a replacement character, a
    process-report shape, and a line made mostly of replacement characters -- and
    then set aside rather than dropped. Identification CANNOT be made exact: a
    review that quotes a teardown line verbatim is byte-identical to an injected
    one, so no content signal can separate them and a stricter test only moves the
    boundary. Relocation is what makes that acceptable. The review body comes out
    clean, a misjudged line is still in the artifact under a heading that says what
    was assumed, and nothing this channel carried is ever destroyed -- which
    matters because it is the channel that salvaged rounds the provider refused.

    Split on newline only. `splitlines` also breaks on separators that can occur
    inside review text, and rejoining would silently rewrite them."""
    kept, aside = [], []
    for line in (text or "").split("\n"):
        stripped = line.strip()
        if (stripped and PROCESS_REPORT.search(line)
                and line.count("�") / len(stripped) >= FOREIGN_DENSITY):
            aside.append(line)
            # A numbered placeholder holds the position. Bytes alone are not the
            # whole of what a line carries: a quotation moved to the end of the
            # document loses the finding it was evidence for.
            kept.append("[set aside: teardown candidate %d]" % len(aside))
            continue
        kept.append(line)
    return "\n".join(kept), aside


def parse_run_header(stderr):
    """(model, effort) as codex reported them. A value that is not a plain slug is
    treated as UNREPORTED: a header that does not look like a model name is not a
    trustworthy report, and it must not become live YAML."""
    text = clean(stderr)
    out = []
    for pattern in (HEADER_MODEL, HEADER_EFFORT):
        found = pattern.search(text)
        value = found.group(1) if found else None
        out.append(value if value and SLUG_GRAMMAR.match(value) else None)
    return tuple(out)


def header_verdict(pin, model, effort):
    if model is None and effort is None:
        return "UNREPORTED -- codex printed no usable run header; the model that ran is unknown"
    reported = "%s at %s effort" % (model or "?", effort or "?")
    if pin is None:
        return "UNPINNED -- ran on %s; nothing was requested" % reported
    if model == pin["model"] and effort == pin["effort"]:
        return "MATCH -- " + reported
    return "MISMATCH -- requested %s at %s effort, codex reported %s" % (
        pin["model"], pin["effort"], reported)


def keep_both_ends(text: str) -> str:
    """Both ends of an over-long stream, with the gap stated where it happens.

    A FAILED run puts the provider's ANSWER on stderr, and an answer orders its
    findings worst-first -- so a tail-only cap discarded exactly the part worth
    reading (measured 2026-08-25: a Mode 3 review lost 35,683 characters and with
    them its first two Critical findings). A crash traceback is the opposite shape:
    its useful end is the last line. One stream carries both kinds, so keep both
    ends and say what fell out between them.
    """
    if len(text) <= STDERR_KEEP:
        return text.rstrip()
    head = int(STDERR_KEEP * STDERR_HEAD_SHARE)
    tail = STDERR_KEEP - head
    return "%s\n\n_(%d characters omitted from the middle)_\n\n%s" % (
        text[:head].rstrip(), len(text) - STDERR_KEEP, text[-tail:].lstrip())


def withhold_or_keep(text, preflight, label):
    """A diagnostic block for a FAILED run, or a note in its place.

    Applied to stdout as well as stderr: withholding only stderr still let blocked
    stdout sink the artifact the contract promises. Truncation states what it
    dropped rather than cutting silently. A FAILED run publishes stdout through
    this path, so the teardown partition runs here too. The set-aside lines are
    appended when the payload publishes. When the scan BLOCKS they are withheld
    with it and their count is stated: the guarantee is that nothing vanishes
    unremarked, not that everything is published."""
    text, aside = partition_foreign_lines(clean(text or ""))
    if not text.strip() and not aside:
        return None
    code, _ = preflight.verdict(text)
    if code == 1:
        extra = ((" %d set-aside line(s) withheld with it." % len(aside)) if aside else "")
        return ("_%s withheld: it did not pass the egress scan. "
                "%d characters not published.%s_" % (label, len(text), extra))
    kept, note = keep_both_ends(text), ""
    if aside:
        note += ("\n_%d line(s) set aside from %s as OS-tool teardown:_\n```\n%s\n```\n"
                 % (len(aside), label, "\n".join(aside)))
    return "```\n%s\n```\n%s" % (kept, note)


def render_artifact(pin, model, effort, verdict, returncode, body, sections=()):
    """The COMPLETE published text. Every dynamic scalar is JSON-quoted, which is
    also valid YAML, so provider-controlled values cannot reshape the document."""
    fields = [
        ("backend", "codex"),
        ("requested", ("%s at %s effort" % (pin["model"], pin["effort"])) if pin else "(unpinned)"),
        ("reported_model", model or "(unreported)"),
        ("reported_effort", effort or "(unreported)"),
        ("header_verdict", verdict),
        ("exit_code", str(returncode)),
    ]
    text = "---\n" + "".join("%s: %s\n" % (k, json.dumps(v)) for k, v in fields) + "---\n\n"
    body_text, aside = partition_foreign_lines(clean(body))
    text += body_text.rstrip() + "\n"
    for title, section in sections:
        if section:
            text += "\n## %s\n\n%s\n" % (title, section)
    if aside:
        # Last, and kept: the identification cannot be exact, so a misjudged line
        # must still be readable rather than gone.
        text += ("\n## Set aside from stdout\n\n%d line(s) matched OS-tool teardown"
                 " -- codex's process tree writing another codepage into this pipe."
                 " Kept because a review quoting such a line is indistinguishable"
                 " from one.\n\n```\n%s\n```\n" % (len(aside), "\n".join(aside)))
    return text


def publish(text, target):
    """Exclusive, never clobbering. Returns the path actually used.
    NOT atomic -- see the DEFERRED note in the module docstring."""
    target.parent.mkdir(parents=True, exist_ok=True)
    candidate, n = target, 0
    while True:
        try:
            fd = os.open(str(candidate), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            n += 1
            candidate = target.with_name("%s-%d%s" % (target.stem, n, target.suffix))
            continue
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        return candidate


def read_pin(review, project_root):
    """(state, pin, error). Wraps every call into the helper: `pin_state` imports
    provider configuration lazily, so failures must stay inside this boundary."""
    try:
        state, pin = review.pin_state(project_root, "codex")
        flags = review.codex_flags(pin) if state == "pinned" else []
    except Exception as exc:
        return None, None, "the external-review helper failed (%s)" % type(exc).__name__
    return state, (pin, flags), None


def run(prompt_file, repo, project_root, out, codex=None, spawn=None, scan_fn=None):
    spawn = spawn or subprocess.run
    repo = str(Path(repo).expanduser().resolve())  # once: cwd and -C must agree
    project_root = Path(project_root).expanduser().resolve()
    target = Path(out).expanduser()

    try:
        preflight = load_preflight()
    except Exception as exc:
        print("ask-codex: the egress scanner could not be loaded (%s) -- refusing"
              % type(exc).__name__, file=sys.stderr)
        return 2
    scan_fn = scan_fn or (lambda text: scan(text, preflight))

    try:
        prompt_text = Path(prompt_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print("ask-codex: could not read the prompt (%s)" % type(exc).__name__, file=sys.stderr)
        return 2

    prompt_text, context_note = compose_review_context(prompt_text, project_root)
    if context_note:
        print("ask-codex: " + context_note, file=sys.stderr)

    try:
        code, message = scan_fn(prompt_text)
    except Exception as exc:  # a gate that crashes must not read as a pass
        print("ask-codex: the preflight scan itself failed (%s) -- nothing sent"
              % type(exc).__name__, file=sys.stderr)
        return 2
    if code != 0:
        print("ask-codex: prompt did not pass preflight -- %s" % message, file=sys.stderr)
        return 1 if code == 1 else 2

    try:
        review = load_review_helper()
    except Exception as exc:
        print("ask-codex: the trusted external-review helper failed to load (%s) -- "
              "refusing rather than falling back" % type(exc).__name__, file=sys.stderr)
        return 2
    if review is None:
        print("ask-codex: no external-review helper at a documented clone location. "
              "Refusing.", file=sys.stderr)
        return 2
    state, found, error = read_pin(review, project_root)
    if error:
        print("ask-codex: %s -- refusing" % error, file=sys.stderr)
        return 2
    if state == "invalid":
        print("ask-codex: the review config cannot be read -- fix it before reviewing",
              file=sys.stderr)
        return 1
    assert found is not None
    pin, flags = found
    if state != "pinned":
        print("ask-codex: %s -- running WITHOUT a pin" % (
            "no review config for this project" if state == "missing"
            else "no codex pin for this project"), file=sys.stderr)

    executable, error = resolve_codex(codex, repo, project_root)
    if executable is None:
        print("ask-codex: %s" % error, file=sys.stderr)
        return 2
    try:
        done = spawn(build_argv(executable, repo, flags), input=prompt_text,
                     env=build_env(), cwd=repo, capture_output=True,
                     text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        print("ask-codex: codex could not be started (%s) -- check the installation"
              % type(exc).__name__, file=sys.stderr)
        return 2

    model, effort = parse_run_header(done.stderr)
    verdict = header_verdict(pin, model, effort)
    diagnostic = "ask-codex: " + verdict + "\n"

    failed = done.returncode != 0
    try:
        if failed:
            # A failed run's output is diagnostic: the contract promises the
            # marked artifact, so a blocked part is withheld rather than sinking
            # the whole file. A SUCCESSFUL run with blocked output still refuses.
            body, sections = "", [("stdout", withhold_or_keep(done.stdout, preflight, "stdout")),
                                  ("stderr", withhold_or_keep(done.stderr, preflight, "stderr"))]
        else:
            body, sections = done.stdout, []
    except Exception as exc:
        print("ask-codex: scanning the diagnostic output failed (%s) -- nothing published"
              % type(exc).__name__, file=sys.stderr)
        return 2
    text = render_artifact(pin, model, effort, verdict, done.returncode, body, sections)
    try:
        for payload in (diagnostic, text):
            out_code, out_message = scan_fn(payload)
            if out_code != 0:
                break
    except Exception as exc:
        print("ask-codex: the output scan itself failed (%s) -- nothing published"
              % type(exc).__name__, file=sys.stderr)
        return 2
    if out_code != 0:
        print("ask-codex: the output did not pass preflight -- %s. "
              "Nothing written." % out_message, file=sys.stderr)
        return 1 if out_code == 1 else 2
    print(diagnostic, end="", file=sys.stderr)
    try:
        written = publish(text, target)
    except OSError as exc:
        print("ask-codex: the review ran but could not be written (%s)"
              % type(exc).__name__, file=sys.stderr)
        return 2
    print(written)
    if failed:
        print("ask-codex: codex exited %s -- artifact written and marked"
              % done.returncode, file=sys.stderr)
        return 3
    return 0


def main():
    _configure_streams()
    parser = argparse.ArgumentParser(prog="ask-codex.py")
    parser.add_argument("prompt_file")
    parser.add_argument("--repo", required=True, help="trusted git repo dir passed to codex -C")
    parser.add_argument("--out", required=True,
                        help="artifact path; nothing is derived, so nothing is claimed "
                             "about where output lands (see SKILL.md for the convention)")
    parser.add_argument("--project-root", default=None,
                        help="project whose pin is read (default: --repo)")
    parser.add_argument("--codex", default=None,
                        help="path to the installed codex CLI; without it, PATH is "
                             "trusted and results inside cwd/repo/project are refused")
    args = parser.parse_args()
    return run(args.prompt_file, args.repo, args.project_root or args.repo,
               args.out, args.codex)


if __name__ == "__main__":
    sys.exit(main())
