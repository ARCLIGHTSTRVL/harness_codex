#!/usr/bin/env python3
"""KR guide staleness detection: which system-vault Guides/ notes trail their
EN authoritative source.

The KR guides are hand-written Korean commentary on this repo's policy blocks,
specs, and docs. Translation is NEVER automated (<knowledge_fidelity>); this
tool only answers "which guides need a human pass" by content-hashing each
declared EN source and comparing against the hash recorded in the guide's
frontmatter at its last human restamp.

Guide frontmatter contract (authored by hand, hashes filled by `stamp`):

    en_sources:
      - codex/AGENTS.md#operating_style sha256:<64hex>
      - README.md sha256:<64hex>
    guide_body_sha: sha256:<64hex>

A source ref is a repo-relative path, optionally `#block_id` to pin one
`<block_id>...</block_id>` region of that file. Files without XML policy blocks
use level-two Markdown headings: `## Operating Style` becomes `#operating_style`.
Fenced examples are ignored and duplicate heading IDs are unverifiable. Hashes are
over CANONICALIZED text (CRLF/CR -> LF, NFC, per-line rstrip, outer blank
lines dropped, single trailing newline) so the same content hashes identically
on Windows and Mac -- this repo checks out with different line endings per
machine, so a raw byte hash would report permanent false staleness.

States (per guide):
  FRESH        every declared source matches, and the body matches its record
  STALE        a declared source changed since the stamp -> needs a KR pass
  BODY-DRIFT   sources match but the guide body changed since its stamp; the
               record trails the note (benign -- re-stamp to re-sync)
  UNSTAMPED    no en_sources declared -> never verified against any source
  UNVERIFIED   frontmatter/stamp unparseable, malformed sha, duplicate or
               unsafe ref, ambiguous source block -> cannot decide, fail safe
  ORPHAN-SOURCE a declared source path or block no longer exists

States (per guide, vault integrity -- a synced vault can fork a note behind
your back, and freshness alone cannot see it):
  DUPLICATE     two or more guides share the same body under the canonical
                comparison above (so a CRLF/LF fork still counts as a twin);
                both carry the same valid stamp, so both read FRESH forever
                while edits to one never reach the other. Declared source sets
                are NOT part of this test -- two guides legitimately explaining
                the same policy block are not duplicates
  CONFLICT-COPY the filename has a sync-artifact shape: a bare trailing number
                (`Note 2`), a parenthesised number (`Note (1)`), a `- Copy`
                suffix, a `(conflicted copy...` marker, or `.sync-conflict-`.
                The bare number is flagged even with no surviving sibling,
                because that is exactly how the incident that motivated this
                check presented; the cost is one convention -- a guide in this
                directory must not be titled with a bare trailing number

State (per policy block):
  UNCOVERED    a block in the policy source that no guide claims -> a policy
               change there would have no KR guide obligation to fire

Vault resolution: the first `purpose: system` vault in ~/.codex/obsidian.yaml
(per-machine registry; never guessed; HARNESS_OBSIDIAN_REGISTRY overrides the
location for tests and diagnostics). No registry or no system vault ->
UNCONFIGURED, which is informational: a machine legitimately may hold no vault.
A registry that exists but cannot be trusted is UNVERIFIED, never quietly
folded into "this machine has no vault".

Usage:
  kr-guide-status.py status [--repo PATH] [--vault PATH]
  kr-guide-status.py stamp <guide.md> [--repo PATH] [--allow-unchanged-body REASON]

`stamp` rewrites only the en_sources/guide_body_sha lines of the frontmatter
(surgical splice -- a YAML round-trip would reformat hand-written notes) and
refuses when a source changed but the guide body did not, because that is the
signature of a restamp without a real KR pass. It writes into the vault, so it
is human-invoked only, never automatic.

Exit: 0 nothing needs a pass, 1 attention states present, 2 usage/environment.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import sys
import unicodedata
from typing import TypedDict


class GuideError(TypedDict):
    error: str


class ParsedGuide(TypedDict):
    refs: list[tuple[str, str | None]]
    body_sha: str | None
    stamped: bool
    body: str

SCRIPT_REPO = Path(__file__).resolve().parents[1]
POLICY_SOURCE = "codex/AGENTS.md"
GUIDES_SUBDIR = "Guides"
BLOCK_LINE = re.compile(r"^<(/?)([a-z][a-z0-9_]*)>$")
SHA_VALUE = re.compile(r"^sha256:[0-9a-f]{64}$")
ATTENTION_STATES = ("STALE", "UNSTAMPED", "UNVERIFIED", "ORPHAN-SOURCE", "UNCOVERED",
                    "DUPLICATE", "CONFLICT-COPY")
# Filename shapes a sync client leaves behind. The bare trailing number is the
# one iCloud produced here; it is treated as a conflict artifact unconditionally
# because a note in this directory should not be titled with a bare number --
# cheap convention, and the failure it catches is otherwise silent.
CONFLICT_NAMES = (
    (re.compile(r"\s\d+$"), "trailing number -- looks like a sync conflict copy"),
    (re.compile(r"\s\(\d+\)$"), "parenthesised number -- looks like a copy"),
    (re.compile(r"(?i)\s-\s*copy$"), "'- Copy' suffix"),
    (re.compile(r"(?i)\(conflicted copy"), "conflicted-copy marker"),
    (re.compile(r"(?i)\.sync-conflict-"), "sync-conflict marker"),
)


def canonical(text):
    """Machine-independent canonical form -- see the module docstring."""
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n" if lines else ""


def sha_of(text):
    return "sha256:" + hashlib.sha256(canonical(text).encode("utf-8")).hexdigest()


def parse_blocks(text):
    """Return (blocks, problems) for `<tag>`-delimited regions.

    A tag that is duplicated, unclosed, or nested is NOT returned as content:
    it lands in problems so the caller reports UNVERIFIED instead of hashing a
    guess."""
    blocks, problems = {}, {}
    open_tag, buffer = None, []
    for line in canonical(text).split("\n"):
        match = BLOCK_LINE.match(line)
        if not match:
            if open_tag:
                buffer.append(line)
            continue
        closing, tag = match.group(1), match.group(2)
        # First problem recorded for a tag wins: the specific cause (nested,
        # duplicated) is more useful than the stray-close it cascades into.
        if not closing:
            if open_tag:
                problems.setdefault(tag, "opened inside <%s>" % open_tag)
                problems.setdefault(open_tag, "contains a nested <%s>" % tag)
                blocks.pop(open_tag, None)
                open_tag = None
                continue
            if tag in blocks or tag in problems:
                problems.setdefault(tag, "defined more than once")
                blocks.pop(tag, None)
                open_tag = None
                continue
            open_tag, buffer = tag, []
        else:
            if open_tag != tag:
                problems.setdefault(tag, "closing tag without a matching open")
                if open_tag:
                    # The enclosing block's extent is now ambiguous -- hashing
                    # what is left would hash a guess.
                    problems.setdefault(open_tag, "contains a stray </%s>" % tag)
                    blocks.pop(open_tag, None)
                    open_tag = None
                continue
            if tag not in problems:
                blocks[tag] = "\n".join(buffer)
            open_tag = None
    if open_tag:
        problems[open_tag] = "never closed"
        blocks.pop(open_tag, None)
    if not blocks and not problems:
        return parse_headings(text)
    return blocks, problems


def parse_headings(text: str) -> tuple[dict[str, str], dict[str, str]]:
    blocks: dict[str, str] = {}
    problems: dict[str, str] = {}
    heading: str | None = None
    buffer: list[str] = []
    fence: str | None = None
    for line in canonical(text).split("\n") + ["## "]:
        stripped = line.lstrip()
        if fence:
            if stripped.startswith(fence) and not stripped[len(fence):].strip():
                fence = None
        elif stripped.startswith(("```", "~~~")):
            marker = re.match(r"(`{3,}|~{3,})", stripped)
            assert marker is not None
            fence = marker.group(0)
        elif line.startswith("## "):
            if heading and heading not in problems:
                blocks[heading] = "\n".join(buffer).strip("\n")
            title = re.sub(r"\s+#+\s*$", "", line[3:]).lower()
            heading = re.sub(r"[^a-z0-9]+", "_", title).strip("_")
            if heading in blocks:
                problems[heading] = "defined more than once"
                blocks.pop(heading)
            buffer = []
            continue
        if heading:
            buffer.append(line)
    return blocks, problems


def split_ref(ref):
    """('path', block_or_None) or (None, reason) for an unsafe/malformed ref."""
    path, _, block = ref.partition("#")
    path = path.strip().replace("\\", "/")
    block = block.strip()
    if not path or path.startswith("/") or ".." in path.split("/") \
            or re.match(r"^[A-Za-z]:", path):
        return None, "unsafe source path"
    if "#" in ref and not re.match(r"^[a-z][a-z0-9_]*$", block):
        return None, "malformed block id"
    return path, (block or None)


def within(child, parent):
    """True when `child` resolves inside `parent` -- symlinks included, so a
    linked-in source cannot smuggle out-of-repo content into a hash."""
    try:
        child, parent = Path(child).resolve(), Path(parent).resolve()
    except OSError:
        return False
    return child == parent or parent in child.parents


def source_sha(repo, ref, cache):
    """('ok', sha) | ('orphan', reason) | ('unverified', reason)."""
    path, block = split_ref(ref)
    if path is None:
        return "unverified", block
    full = repo / path
    if path not in cache:
        if full.exists() and not within(full, repo):
            cache[path] = ValueError("resolves outside the repo")
        else:
            try:
                cache[path] = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                cache[path] = exc
    text = cache[path]
    if isinstance(text, FileNotFoundError):
        return "orphan", "source file missing"
    if isinstance(text, (OSError, ValueError)):
        # A directory, a permission error, a symlink escape: not "gone", just
        # not verifiable -- those must never share a verdict.
        return "unverified", "source unreadable (%s)" % type(text).__name__
    if isinstance(text, UnicodeDecodeError):
        return "unverified", "source not valid UTF-8"
    if block is None:
        return "ok", sha_of(text)
    blocks, problems = parse_blocks(text)
    if block in problems:
        return "unverified", "block <%s> %s" % (block, problems[block])
    if block not in blocks:
        return "orphan", "block <%s> not in %s" % (block, path)
    return "ok", sha_of(blocks[block])


def split_frontmatter(text):
    """(frontmatter_text, body_text) or (None, reason)."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, "no frontmatter"
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:])
    return None, "unterminated frontmatter"


def load_yaml():
    try:
        import yaml
        return yaml
    except ImportError:
        return None


class DuplicateKey(Exception):
    pass


_LOADER_CACHE = {}


def unique_key_loader(yaml_module):
    """SafeLoader that rejects duplicate mapping keys.

    PyYAML resolves duplicates last-wins, so a second `en_sources` or
    `guide_body_sha` would silently override the real one and a stale guide
    could read FRESH. A regex over key lines cannot do this job: `en_sources :`
    and flow mappings are valid YAML that no line pattern catches."""
    key = id(yaml_module)
    if key in _LOADER_CACHE:
        return _LOADER_CACHE[key]

    class Loader(yaml_module.SafeLoader):
        pass

    def construct(loader, node, deep=False):
        # Scan the EXPLICIT keys before delegating: SafeLoader.construct_mapping
        # flattens `<<` merges into node.value, after which a merged key
        # legitimately repeats an explicit one (explicit wins). Checking first,
        # and skipping the merge key itself, keeps standard merge semantics
        # while still rejecting a genuine duplicate.
        seen = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            item = loader.construct_object(key_node, deep=deep)
            try:
                duplicate = item in seen
            except TypeError:
                raise DuplicateKey("unhashable key")
            if duplicate:
                raise DuplicateKey(str(item))
            seen.add(item)
        return yaml_module.SafeLoader.construct_mapping(loader, node, deep=deep)

    Loader.add_constructor(yaml_module.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
                           construct)
    _LOADER_CACHE[key] = Loader
    return Loader


def parse_guide(path, yaml_module) -> GuideError | ParsedGuide:
    """Return a dict: {'error': reason} or {'refs': [(ref, sha_or_None)],
    'body_sha': sha_or_None, 'stamped': bool}."""
    if yaml_module is None:
        return {"error": "PyYAML not installed for this interpreter"}
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {"error": "unreadable (%s)" % type(exc).__name__}
    front, body = split_frontmatter(raw)
    if front is None:
        return {"error": body}
    try:
        data = yaml_module.load(front, Loader=unique_key_loader(yaml_module))
    except DuplicateKey as exc:
        return {"error": "duplicate frontmatter key `%s`" % exc}
    except Exception as exc:
        return {"error": "frontmatter not valid YAML (%s)" % type(exc).__name__}
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return {"error": "frontmatter is not a mapping"}
    body_sha = data.get("guide_body_sha")
    if body_sha is not None and (not isinstance(body_sha, str)
                                 or not SHA_VALUE.match(body_sha.strip())):
        return {"error": "malformed guide_body_sha"}
    entries = data.get("en_sources")
    if entries is None:
        return {"stamped": False, "refs": [], "body_sha": None, "body": body}
    if not isinstance(entries, list) or not entries:
        return {"error": "en_sources must be a non-empty list"}
    refs, seen = [], set()
    for entry in entries:
        if not isinstance(entry, str) or not entry.strip():
            return {"error": "en_sources entry is not a string"}
        parts = entry.split()
        if len(parts) > 2:
            return {"error": "en_sources entry must be `ref [sha256:...]`"}
        ref, sha = parts[0], (parts[1] if len(parts) == 2 else None)
        if sha is not None and not SHA_VALUE.match(sha):
            return {"error": "malformed sha for %s" % ref}
        if ref in seen:
            return {"error": "duplicate source ref %s" % ref}
        seen.add(ref)
        refs.append((ref, sha))
    return {"stamped": True, "refs": refs,
            "body_sha": body_sha.strip() if body_sha else None, "body": body}


def registry_path():
    """Vault registry location. HARNESS_OBSIDIAN_REGISTRY overrides it (same
    role as HARNESS_POWERSHELL for the installer suite): tests must be able to
    point at a fixture registry WITHOUT overriding HOME, because on the Mac
    PyYAML lives in the HOME-keyed user site-packages and a redirected HOME
    silently removes it."""
    override = os.environ.get("HARNESS_OBSIDIAN_REGISTRY")
    if override:
        return Path(override)
    return Path(os.path.expanduser("~")) / ".codex" / "obsidian.yaml"


def body_digest(path):
    """Canonical hash of a guide's body for twin detection.

    Deliberately independent of the frontmatter parser and of decodability: a
    conflict twin must still be recognised when its frontmatter is damaged or
    its bytes do not decode, so this splits on the `---` delimiters only and
    decodes lossily. With no terminated frontmatter the body boundary is
    unknowable, so the whole file is compared -- two copies of the same damaged
    note still match each other."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    text = raw.decode("utf-8", "replace")
    front, body = split_frontmatter(text)
    return sha_of(text if front is None else body)


def conflict_reason(stem):
    for pattern, reason in CONFLICT_NAMES:
        if pattern.search(stem):
            return reason
    return None


def resolve_vault(yaml_module, registry=None):
    """(vault_path, state, reason) with state in ok | unconfigured | unverified.

    Absent registry / no system vault are legitimate machine states
    (unconfigured, informational). A registry that exists but cannot be
    trusted is `unverified` and must reach attention -- otherwise a broken
    registry reads exactly like a machine that holds no vault."""
    registry = Path(registry or registry_path())
    # One guarded read decides existence: a stat()-based precheck would report
    # a permission-denied or otherwise unreadable registry as "this machine has
    # no vault", which is the exact false-informational this tri-state exists
    # to prevent.
    try:
        raw = registry.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "unconfigured", "no vault registry at %s" % registry
    except (OSError, UnicodeDecodeError) as exc:
        return None, "unverified", "registry unreadable (%s)" % type(exc).__name__
    if yaml_module is None:
        return None, "unverified", "PyYAML not installed -- cannot read the vault registry"
    try:
        data = yaml_module.load(raw, Loader=unique_key_loader(yaml_module))
    except DuplicateKey as exc:
        return None, "unverified", "duplicate registry key `%s`" % exc
    except Exception as exc:
        return None, "unverified", "registry not valid YAML (%s)" % type(exc).__name__
    if data is not None and not isinstance(data, dict):
        return None, "unverified", "registry root is not a mapping"
    vaults = (data or {}).get("vaults")
    if vaults is None:
        return None, "unverified", "registry has no vaults key"
    if not isinstance(vaults, list):
        return None, "unverified", "registry vaults is not a list"
    for item in vaults:
        if isinstance(item, dict) and item.get("purpose") == "system":
            path = item.get("path")
            if not isinstance(path, str) or not path.strip():
                return None, "unverified", "system vault entry has no path"
            return Path(os.path.expandvars(path.strip())), "ok", None
    return None, "unconfigured", "registry declares no purpose: system vault"


def evaluate(repo, vault):
    """Return rows of (state, key, detail)."""
    repo = Path(repo)          # callers (doctor) pass a str root
    yaml_module = load_yaml()
    if vault is None:
        vault, vault_state, reason = resolve_vault(yaml_module)
        if vault is None:
            return [("UNCONFIGURED" if vault_state == "unconfigured" else "UNVERIFIED",
                     "vault", reason)]
    guides_dir = Path(vault) / GUIDES_SUBDIR
    if not guides_dir.is_dir():
        return [("UNVERIFIED", "vault", "no %s/ in %s" % (GUIDES_SUBDIR, vault))]

    rows, cache, claimed = [], {}, set()
    guide_paths = sorted(guides_dir.rglob("*.md"))
    for path in guide_paths:
        key = path.relative_to(guides_dir).as_posix()
        guide = parse_guide(path, yaml_module)
        if "error" in guide:
            rows.append(("UNVERIFIED", key, guide["error"]))
            continue
        if not guide["stamped"]:
            rows.append(("UNSTAMPED", key, "no en_sources declared"))
            continue
        for ref, _ in guide["refs"]:
            path_part, block = split_ref(ref)
            if path_part == POLICY_SOURCE and block:
                claimed.add(block)
        state, details = "FRESH", []
        for ref, recorded in guide["refs"]:
            status, value = source_sha(repo, ref, cache)
            if status == "unverified":
                state = "UNVERIFIED"
                details.append("%s: %s" % (ref, value))
            elif status == "orphan":
                if state != "UNVERIFIED":
                    state = "ORPHAN-SOURCE"
                details.append("%s: %s" % (ref, value))
            elif recorded is None:
                if state == "FRESH":
                    state = "UNVERIFIED"
                details.append("%s: no sha recorded (run stamp)" % ref)
            elif recorded != value:
                if state == "FRESH":
                    state = "STALE"
                details.append("%s changed" % ref)
        if state == "FRESH":
            current_body = sha_of(guide["body"])
            if guide["body_sha"] is None:
                state = "UNVERIFIED"
                details.append("no guide_body_sha recorded (run stamp)")
            elif guide["body_sha"] != current_body:
                state = "BODY-DRIFT"
                details.append("guide edited since its stamp")
        rows.append((state, key, "; ".join(details) or "up to date"))

    # Vault-integrity pass over the same walk. A sync conflict shows up either
    # as a byte-identical twin (both copies carry the same valid stamp, so both
    # read FRESH forever while edits to one never reach the other) or as a
    # silent rename of the original. Freshness alone is blind to both.
    by_body = {}
    for path in guide_paths:
        digest = body_digest(path)
        if digest is not None:
            by_body.setdefault(digest, []).append(
                path.relative_to(guides_dir).as_posix())
    for keys in sorted(by_body.values()):
        if len(keys) > 1:
            for key in keys:
                rows.append(("DUPLICATE", key, "identical body to %s"
                             % ", ".join(k for k in keys if k != key)))
    for path in guide_paths:
        reason = conflict_reason(path.stem)
        if reason:
            rows.append(("CONFLICT-COPY", path.relative_to(guides_dir).as_posix(),
                         reason))

    policy_path = repo / POLICY_SOURCE
    try:
        # Containment applies to the canonical policy source too, not only to
        # guide-declared refs: a symlinked policy file would otherwise drive
        # coverage from outside the repo.
        if policy_path.exists() and not within(policy_path, repo):
            raise ValueError("resolves outside the repo")
        blocks, problems = parse_blocks(policy_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        # A policy source we cannot trust means coverage cannot be computed at
        # all -- a row, not a footnote, or the run reports clean while blind.
        blocks, problems = {}, {}
        rows.append(("UNVERIFIED", POLICY_SOURCE,
                     "policy source unreadable or outside the repo (%s) -- "
                     "coverage not checked" % type(exc).__name__))
    for tag in sorted(problems):
        rows.append(("UNVERIFIED", POLICY_SOURCE + "#" + tag, problems[tag]))
    for tag in sorted(set(blocks) - claimed):
        rows.append(("UNCOVERED", POLICY_SOURCE + "#" + tag,
                     "no KR guide declares this policy block"))
    order = {"DUPLICATE": 0, "CONFLICT-COPY": 1, "UNVERIFIED": 2, "STALE": 3,
             "ORPHAN-SOURCE": 4, "UNSTAMPED": 5, "UNCOVERED": 6, "BODY-DRIFT": 7,
             "FRESH": 8, "UNCONFIGURED": 9}
    rows.sort(key=lambda r: (order.get(r[0], 9), r[1]))
    return rows


def summarize(rows):
    counts = {}
    for state, _, _ in rows:
        counts[state] = counts.get(state, 0) + 1
    return counts


def stamp(repo, guide_path, allow_unchanged_body, vault=None):
    """Refresh the recorded hashes in one guide. Human-invoked: it writes into
    the vault."""
    repo, guide_path = Path(repo), Path(guide_path)
    yaml_module = load_yaml()
    if vault is None:
        vault, _, vault_reason = resolve_vault(yaml_module)
        if vault is None:
            print("STAMP REFUSED: %s -- stamping needs a configured system vault"
                  % vault_reason)
            return 1
    if not within(guide_path, Path(vault) / GUIDES_SUBDIR):
        print("STAMP REFUSED: %s is not inside the system vault's %s/"
              % (guide_path, GUIDES_SUBDIR))
        return 1
    guide = parse_guide(guide_path, yaml_module)
    if "error" in guide:
        print("STAMP REFUSED: %s" % guide["error"])
        return 1
    if not guide["refs"]:
        print("STAMP REFUSED: declare en_sources refs by hand first "
              "(one `- path[#block]` per source this guide documents)")
        return 1
    cache, fresh_lines, changed = {}, [], []
    for ref, recorded in guide["refs"]:
        status, value = source_sha(repo, ref, cache)
        if status != "ok":
            print("STAMP REFUSED: %s -- %s" % (ref, value))
            return 1
        if recorded != value:
            changed.append(ref)
        fresh_lines.append("  - %s %s" % (ref, value))
    body_sha = sha_of(guide["body"])
    if changed and guide["body_sha"] is not None and guide["body_sha"] == body_sha \
            and not allow_unchanged_body:
        print("STAMP REFUSED: %s changed but the guide body did not -- that is a "
              "restamp without a KR pass. Update the guide, or pass "
              "--allow-unchanged-body \"<reason>\" if the change genuinely needs no "
              "KR edit." % ", ".join(changed))
        return 1
    try:
        # read_text() applies universal newlines, so CRLF detection must look at
        # the raw bytes -- otherwise every stamp silently rewrites the file to LF.
        crlf = b"\r\n" in guide_path.read_bytes()
        text = guide_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print("STAMP REFUSED: could not re-read the guide (%s)" % type(exc).__name__)
        return 2
    front, body = split_frontmatter(text)
    if front is None:
        print("STAMP REFUSED: guide frontmatter changed while stamping")
        return 2
    kept, carried, skipping = [], [], False
    for line in front.split("\n"):
        if line.startswith("en_sources:"):
            skipping = True
            continue
        if skipping:
            if line.lstrip().startswith("- ") or not line.strip():
                continue        # a list entry we are regenerating
            if line.startswith((" ", "\t")):
                carried.append(line)   # a hand-written comment inside the list
                continue
        skipping = False
        if line.startswith("guide_body_sha:"):
            continue
        kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    new_front = (kept + ["en_sources:"] + carried + fresh_lines
                 + ["guide_body_sha: " + body_sha])
    new_text = "---\n" + "\n".join(new_front) + "\n---\n" + body
    # Preserve the note's existing line-ending style: these are hand-kept vault
    # files, and rewriting every line is a mutation nobody asked for. Hashes are
    # canonical, so this never affects a verdict.
    if crlf:
        new_text = new_text.replace("\n", "\r\n")
    try:
        _atomic_write(guide_path, new_text)
    except OSError as exc:
        print("STAMP FAILED: could not write the guide (%s)" % type(exc).__name__)
        return 2
    verify = parse_guide(guide_path, yaml_module)
    if "error" in verify or not verify["stamped"] \
            or [r for r, _ in verify["refs"]] != [r for r, _ in guide["refs"]]:
        print("STAMP WROTE AN UNPARSEABLE RESULT -- inspect %s" % guide_path)
        return 1
    print("STAMPED %s (%d source%s%s)" % (guide_path.name, len(fresh_lines),
                                          "" if len(fresh_lines) == 1 else "s",
                                          "; refreshed: " + ", ".join(changed)
                                          if changed else "; no source changed"))
    if allow_unchanged_body and changed:
        print("  body left unchanged by explicit reason: %s" % allow_unchanged_body)
    return 0


def _atomic_write(path, text):
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _pop_flag(args, name):
    if name in args:
        i = args.index(name)
        if i + 1 >= len(args):
            return args, None, True
        return args[:i] + args[i + 2:], args[i + 1], False
    return args, None, False


def main():
    args = sys.argv[1:]
    args, repo_arg, bad = _pop_flag(args, "--repo")
    if bad:
        print("--repo needs a path", file=sys.stderr)
        return 2
    args, vault_arg, bad = _pop_flag(args, "--vault")
    if bad:
        print("--vault needs a path", file=sys.stderr)
        return 2
    args, reason_arg, bad = _pop_flag(args, "--allow-unchanged-body")
    if bad:
        print("--allow-unchanged-body needs a reason", file=sys.stderr)
        return 2
    repo = Path(repo_arg) if repo_arg else SCRIPT_REPO

    if args[:1] == ["stamp"]:
        if len(args) != 2:
            print("usage: kr-guide-status.py stamp <guide.md> [--repo PATH] "
                  "[--vault PATH] [--allow-unchanged-body REASON]", file=sys.stderr)
            return 2
        target = Path(args[1])
        if not target.is_file():
            print("STAMP REFUSED: no such guide: %s" % target)
            return 2
        return stamp(repo, target, reason_arg,
                     Path(vault_arg) if vault_arg else None)

    if args[:1] != ["status"] or len(args) != 1:
        print("usage: kr-guide-status.py {status|stamp <guide.md>} [--repo PATH] "
              "[--vault PATH]", file=sys.stderr)
        return 2
    rows = evaluate(repo, Path(vault_arg) if vault_arg else None)
    print("KR guide status")
    width = max((len(r[1]) for r in rows), default=10)
    for state, key, detail in rows:
        print("  %-13s %-*s  %s" % (state, width, key, detail))
    counts = summarize(rows)
    print("summary: " + ("  ".join("%s=%d" % (s, counts[s]) for s in sorted(counts))
                         or "no guides found"))
    return 1 if any(counts.get(s) for s in ATTENTION_STATES) else 0


if __name__ == "__main__":
    sys.exit(main())
