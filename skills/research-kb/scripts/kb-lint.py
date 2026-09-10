#!/usr/bin/env python3
"""Mechanical lint for a research knowledge base (`knowledge/`).

Checks the durable, structural invariants the research-KB convention relies on:
  - broken [[wikilinks]]      (a link whose target page does not exist)
  - orphan pages             (a content page nothing links to and the index omits)
  - index completeness       (every content page appears in index.md)
  - tag-taxonomy audit       (every frontmatter tag is declared in SCHEMA.md)
  - frontmatter presence     (content pages have a YAML frontmatter block)
  - citations                (every `consolidates:` id is a consolidated fragment delta --
                              an issue; a backticked commit hash the enclosing repo cannot
                              resolve, or an `.ask-artifacts/` path absent on this machine --
                              ADVISORY, listed and never counted; what could not be checked
                              at all is named)

Code spans / fenced blocks are stripped before extracting `[[links]]`, so a page
that *mentions* a wikilink inside backticks (e.g. `` `[[wikilinks]]` `` in SCHEMA)
does not produce a false "broken link" — this is the generic markdown-graph rule
shared in spirit with the wiki linter; keep it identical if the two ever merge.

This is intentionally the SMALL mechanical core. It does NOT do git-pinned stale
detection or doc-gap analysis (research raw is pinned by immutable filename +
sha256 in `_sources.md`, not by git symbol pins). Semantic judgement (Layer A/B
quality, confidence calibration) stays with the agent.

Usage:
    python kb-lint.py [<knowledge-path>]   # default: ./knowledge discovered from cwd

Exit codes: 0 = clean, 1 = issues found, 2 = script/usage error.
"""
import glob
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")  # avoid cp949 console crashes on Windows
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

META = {"SCHEMA", "index", "log", "_sources"}

# The allowed tag set is ALWAYS the project's own knowledge/SCHEMA.md "Tag taxonomy"
# section. There is deliberately NO built-in default taxonomy — hardcoding one project's
# domain tags would silently audit a different project against the wrong vocabulary. If the
# taxonomy can't be parsed, the tag audit is SKIPPED (with a warning), not run against a
# substitute set.


def find_kb(start):
    """Walk up from `start` looking for a `knowledge/` dir (preferring one with SCHEMA.md)."""
    d = os.path.abspath(start)
    while True:
        cand = os.path.join(d, "knowledge")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def strip_code(body):
    """Blank fenced blocks (preserving line count) and remove inline code spans.

    SHARED RULE — keep identical to codebase-wiki/scripts/wiki-lint.py:_blank_code
    (same fence/code-span strip, so a `[[link]]` mentioned in backticks isn't a
    false positive). Duplicated on purpose: the two linters are otherwise
    independent. If you change link-extraction here, change it there too. Merge
    into one markdown-graph core only when a 3rd KB earns the abstraction."""
    out, in_fence = [], False
    for line in body.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    text = "\n".join(out)
    return re.sub(r"`[^`]*`", "", text)


def parse_taxonomy(kb):
    """Return the project's tag set from SCHEMA.md's taxonomy section, or None if it
    can't be parsed (→ the tag audit is skipped, never run against a substitute set)."""
    schema = os.path.join(kb, "SCHEMA.md")
    if not os.path.isfile(schema):
        return None
    text = open(schema, encoding="utf-8").read()
    m = re.search(r"#+\s*Tag taxonomy.*?(?=\n#+\s|\Z)", text, re.I | re.S)
    if not m:
        alt = re.search(r"^#+\s*Tags\b.*$", text, re.M | re.I)
        if alt:
            print("kb-lint: SCHEMA.md has heading '%s' but the tag audit needs one containing "
                  "'Tag taxonomy' (e.g. '## Tag taxonomy') -- rename it to enable the audit."
                  % alt.group(0).strip(), file=sys.stderr)
        return None
    # tags are written as `backtick-wrapped` tokens in the taxonomy section; strip
    # HTML comments first so commented-out examples don't join the allowed set.
    section = re.sub(r"<!--.*?-->", "", m.group(0), flags=re.S)
    tags = set(re.findall(r"`([a-z][a-z0-9-]*)`", section))
    return tags or None

HASH_RE = re.compile(r"`([0-9a-f]{7,40})`")
ARTIFACT_RE = re.compile(r"\.ask-artifacts/[^\s`'\")\]]+")
BRACE_RE = re.compile(r"\{([^{}]*)\}")


def expand_braces(name):
    m = BRACE_RE.search(name)
    if not m:
        return [name]
    inner = m.group(1)
    rng = re.fullmatch(r"(\d+)\.\.(\d+)", inner)
    alts = [str(i) for i in range(int(rng.group(1)), int(rng.group(2)) + 1)] if rng else inner.split(",")
    out = []
    for alt in alts:
        out.extend(expand_braces(name[:m.start()] + alt + name[m.end():]))
    return out


def _delta_blocks(text):
    """Record bodies, split on `## delta: ` headers that are NOT inside a fence.

    A fenced sample carrying its own header -- the shape this repo's own docs use
    to SHOW what a record looks like -- was read as a real record, so a page could
    cite a delta that exists only as an example (3B audit 2026-09-02, row A9).
    Fenced CONTENT is kept: a record's metadata block is itself a ```yaml fence,
    so dropping fenced lines would delete the very fields this reads.
    """
    blocks, current, fence = [], None, None
    for line in text.split("\n"):
        stripped = line.strip()
        if fence is None and (stripped.startswith("```") or stripped.startswith("~~~")):
            fence = stripped[0] * 3
        elif fence is not None and stripped.startswith(fence):
            fence = None
        elif fence is None and line.startswith("## delta: "):
            if current is not None:
                blocks.append("\n".join(current))
            current = [line[len("## delta: "):]]
            continue
        if current is not None:
            current.append(line)
    if current is not None:
        blocks.append("\n".join(current))
    return blocks


def fragment_statuses(kb):
    frag = os.path.join(kb, "_fragments")
    if not os.path.isdir(frag):
        return None
    statuses = {}
    for root, _dirs, files in os.walk(frag):
        for f in files:
            if not f.endswith(".md"):
                continue
            text = open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
            for block in _delta_blocks(text):
                did = re.search(r"(?m)^delta_id:\s*(\S+)", block)
                status = re.search(r"(?m)^status:\s*(\S+)", block)
                if did:
                    full = did.group(1)
                    value = status.group(1) if status else "(no status)"
                    statuses[full] = value
                    if len(full) > 36 and full[8] == "-" and full[36] in "-.":
                        statuses.setdefault(full[:8] + full[36:], value)
    return statuses


def session_prefixes(kb):
    frag = os.path.join(kb, "_fragments")
    if not os.path.isdir(frag):
        return set()
    out = set()
    for root, _dirs, files in os.walk(frag):
        for f in files:
            stem = os.path.splitext(f)[0]
            if re.match(r"^[0-9a-f]{8}", stem):
                out.add(stem[:8])
    return out


def commit_shaped(token, prefixes):
    if token in prefixes:
        return False
    if token.isdigit() and len(token) > 8:
        return False
    return len(token) <= 12 or len(token) == 40


def git_toplevel(kb):
    try:
        r = subprocess.run(["git", "-C", kb, "rev-parse", "--show-toplevel"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def unresolved_commits(repo, hashes):
    if not hashes:
        return set()
    r = subprocess.run(["git", "-C", repo, "cat-file", "--batch-check"],
                       input="\n".join(h + "^{commit}" for h in sorted(hashes)) + "\n",
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    missing = set()
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] in ("missing", "ambiguous"):
            missing.add(parts[0].split("^")[0])
    return missing


def consolidates_of(text):
    if not text.lstrip().startswith("---"):
        return []
    lines = text.lstrip().split("\n")[1:]
    ids, inside = [], False
    for line in lines:
        if line.strip() == "---":
            break
        if line.startswith("consolidates:"):
            # Inline style is valid YAML and this returned [] for it, so a page
            # citing an id that does not exist was indistinguishable from a page
            # citing nothing -- and passed (3B audit 2026-09-02, row A9).
            rest = line[len("consolidates:"):].strip()
            if rest.startswith("[") and rest.endswith("]"):
                ids.extend(part.strip().strip("'\"")
                           for part in rest[1:-1].split(",") if part.strip())
                continue
            if rest:
                ids.append(rest.strip("'\""))
                continue
            inside = True
            continue
        if inside:
            m = re.match(r"^\s+-\s+(\S+)\s*$", line)
            if m:
                ids.append(m.group(1))
                continue
            if not line.startswith((" ", "\t")):
                inside = False
    return ids


def check_citations(kb, md_files, content):
    """Issues: a `consolidates:` id no fragment carries as consolidated. Advisory (never an
    issue): a backticked commit hash the enclosing repository cannot resolve (pages cite other
    repositories' commits), an `.ask-artifacts/` path absent on this machine (the directory is
    gitignored). Notes name what could not be verified at all."""
    issues, advisory, notes = [], [], []
    statuses = fragment_statuses(kb)
    if statuses is None:
        notes.append("consolidates ids not verified (no _fragments/ under %s)" % kb)
    repo = git_toplevel(kb)
    if repo is None:
        notes.append("commit hashes not verified (no git repository encloses %s)" % kb)
    art_root = repo if repo else os.path.dirname(os.path.abspath(kb))
    art_dir = os.path.join(art_root, ".ask-artifacts")
    if not os.path.isdir(art_dir):
        notes.append("artifact paths not verified (no .ask-artifacts/ at %s)" % art_root)
        art_dir = None
    hashes = {}
    prefixes = session_prefixes(kb)
    for f in md_files:
        base = os.path.splitext(os.path.basename(f))[0]
        if base not in content:
            continue
        rel = os.path.relpath(f, kb)
        text = open(f, encoding="utf-8", errors="replace").read()
        if statuses is not None:
            for cid in consolidates_of(text):
                status = statuses.get(cid)
                if status != "consolidated":
                    issues.append((rel, cid, status or "absent from _fragments"))
        for h in set(HASH_RE.findall(text)):
            if commit_shaped(h, prefixes):
                hashes.setdefault(h, []).append(rel)
        if art_dir is not None:
            for ref in set(ARTIFACT_RE.findall(text)):
                ref = ref.rstrip(".,;:")
                for name in expand_braces(ref[len(".ask-artifacts/"):]):
                    if any(ch in name for ch in "*?["):
                        if not glob.glob(os.path.join(art_dir, name)):
                            advisory.append((rel, ".ask-artifacts/" + name, "no file matches on this machine"))
                    elif not os.path.isfile(os.path.join(art_dir, name)):
                        advisory.append((rel, ".ask-artifacts/" + name, "absent on this machine"))
    if repo is not None:
        for h in sorted(unresolved_commits(repo, set(hashes))):
            for rel in hashes[h]:
                advisory.append((rel, h, "does not resolve to a commit in %s" % repo))
    return issues, sorted(set(advisory)), notes


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    kb = find_kb(args[0]) if args else find_kb(os.getcwd())
    if not kb or not os.path.isdir(kb):
        print("kb-lint: no knowledge/ directory found.", file=sys.stderr)
        sys.exit(2)

    md_files = []
    for root, dirs, files in os.walk(kb):
        # knowledge-fragment staging lives in _fragments/ (pre-integration, orphan by
        # design); _archive/ and _consolidations/ hold superseded/consumed content.
        # Prune all three (at any depth) so the linter never flags them as orphans / bad-fm.
        dirs[:] = [d for d in dirs if d not in ("_fragments", "_archive", "_consolidations")]
        for f in files:
            if f.endswith(".md"):
                md_files.append(os.path.join(root, f))

    pages = {os.path.splitext(os.path.basename(f))[0]: f for f in md_files}
    content = set(pages) - META
    # raw/ holds pinned sources (referenced via `sources:` frontmatter and plain paths,
    # never wikilinked) -- exempt from the missing-from-index and orphan checks.
    raw_dir = os.path.join(kb, "raw") + os.sep
    raw_pages = {s for s, f in pages.items() if f.startswith(raw_dir)}

    broken, linked, no_fm = [], set(), []
    for f in md_files:
        base = os.path.splitext(os.path.basename(f))[0]
        text = open(f, encoding="utf-8").read()
        body = strip_code(text)
        for tgt in re.findall(r"\[\[([^\]]+)\]\]", body):
            tgt = tgt.split("|")[0].strip()
            if base != "index":
                linked.add(tgt)
            if tgt not in pages:
                broken.append((os.path.relpath(f, kb), tgt))
        if base in content and not text.lstrip().startswith("---"):
            no_fm.append(os.path.relpath(f, kb))

    idx_path = os.path.join(kb, "index.md")
    idx = open(idx_path, encoding="utf-8").read() if os.path.isfile(idx_path) else ""
    # membership accepts both [[slug]] and the alias form [[slug|Title]]
    idx_targets = {t.split("|")[0].strip() for t in re.findall(r"\[\[([^\]]+)\]\]", idx)}
    missing = sorted(s for s in content - raw_pages if s not in idx_targets)
    orphans = sorted(s for s in content - raw_pages if s not in linked and s not in idx_targets)

    taxonomy = parse_taxonomy(kb)
    bad_tags = []
    if taxonomy is None:
        print("kb-lint: no parseable Tag-taxonomy section in SCHEMA.md — skipping tag audit.",
              file=sys.stderr)
    for f in (md_files if taxonomy is not None else []):
        base = os.path.splitext(os.path.basename(f))[0]
        if base in META:
            continue
        text = open(f, encoding="utf-8").read()
        m = re.search(r"^tags:\s*\[([^\]]*)\]", text, re.M)
        if m:
            for t in (t.strip() for t in m.group(1).split(",")):
                if t and t not in taxonomy:
                    bad_tags.append((os.path.relpath(f, kb), t))

    cite_issues, cite_advisory, cite_notes = check_citations(kb, md_files, content)

    issues = 0

    def report(label, items, fmt):
        nonlocal issues
        if items:
            issues += len(items)
            print(f"[{label}] {len(items)}")
            for it in items:
                print(f"  - {fmt(it)}")

    report("broken-wikilink", broken, lambda x: f"{x[0]}: [[{x[1]}]] target not found")
    report("missing-from-index", missing, lambda x: f"{x} not listed in index.md")
    report("orphan", orphans, lambda x: f"{x} (no inbound link, absent from index)")
    report("missing-frontmatter", no_fm, lambda x: f"{x} (content page without frontmatter)")
    report("unknown-tag", bad_tags, lambda x: f"{x[0]}: tag '{x[1]}' not in SCHEMA taxonomy")
    report("citation", cite_issues, lambda x: f"{x[0]}: consolidates {x[1]} is {x[2]}")
    if cite_advisory:
        print(f"[advisory:citation] {len(cite_advisory)} (not counted as issues)")
        for rel, what, why in cite_advisory:
            print(f"  - {rel}: {what} {why}")
    for note in cite_notes:
        print("kb-lint: citations: " + note)

    if issues:
        print(f"\nkb-lint: {issues} issue(s) in {kb}", file=sys.stderr)
        sys.exit(1)
    print(f"kb-lint OK: {len(content)} content pages, 0 issues ({kb})")


if __name__ == "__main__":
    main()
