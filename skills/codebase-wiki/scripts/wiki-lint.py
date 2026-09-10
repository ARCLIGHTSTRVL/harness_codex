#!/usr/bin/env python3
"""wiki-lint.py — automated lint for codebase-wiki directories.

Implements the mechanical lint checks specified in SKILL.md:
  - Broken wikilinks, orphan pages, index drift
  - Frontmatter validation, tag-taxonomy audit
  - Stale Layer 1: symbol/range pin re-anchoring + content-change detection
  - Stale Layer 2: heuristic high/medium/low classification
  - Stale Layer 3: trust-decay commit count
  - Documentation-gap detection (recently touched paths not pinned by any page)
  - Page-size, log-rotation, quality-signal checks

Layer 1 re-anchoring follows SKILL.md exactly: pin paths follow `git mv`
renames (walking `git log --diff-filter=R --name-status sha..HEAD`), symbol
pins are re-located by searching the current source for the symbol's
declaration, and range pins are re-located by searching for the pinned
content (as it existed at the pinned SHA) inside the current file. Pure line
shifts and pure file renames are silent (info-only) and can be written back
with --update-pins; only genuine content changes within the re-anchored
range are flagged as stale.

Usage:
  python wiki-lint.py [<wiki-path>]            # auto-discover if omitted
  python wiki-lint.py <wiki-path> --json       # machine-readable output
  python wiki-lint.py <wiki-path> --update-pins  # rewrite range-pin shifts
  python wiki-lint.py <wiki-path> --no-git     # skip git-dependent checks
  python wiki-lint.py <wiki-path> --since 60d  # doc-gap window (default 30d)
  python wiki-lint.py <wiki-path> --severity medium  # only show medium+
  python wiki-lint.py <wiki-path> --check stale-l1,orphans  # subset

Exit codes:
  0 — no critical/high issues
  1 — at least one critical or high issue
  2 — script error (wiki not found, invalid args, missing dependency)

Requires: Python 3.9+, PyYAML, git (for stale and doc-gap checks).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML required. Install with: pip install pyyaml\n")
    sys.exit(2)


# ─── constants ───────────────────────────────────────────────────────────

SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITY_ORDER)}

KNOWLEDGE_DIRS = ("entities", "concepts", "comparisons", "queries")
META_FILE_NAMES = {"AGENTS.md", "SCHEMA.md", "index.md", "log.md"}
ARCHIVE_DIRS = {"_archive", "_meta"}

REQUIRED_FRONTMATTER = ("title", "created", "updated", "type", "tags", "sources")
VALID_TYPES = {"entity", "concept", "comparison", "query"}
VALID_CONFIDENCE = {"high", "medium", "low"}

PAGE_SIZE_LIMIT = 200
TRUST_DECAY_THRESHOLD = 50
DOC_GAP_DEFAULT_DAYS = 30
LOG_ROTATE_THRESHOLD = 500

SYMBOL_BODY_BRACE_LANGS = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".java", ".go", ".rs", ".c", ".cpp", ".cc", ".h", ".hpp",
    ".cs", ".kt", ".scala", ".swift", ".php",
}

NON_SOURCE_DIRS = {".git", "node_modules", "dist", "build", ".next",
                   "target", "vendor", ".venv", "venv", "__pycache__",
                   ".pytest_cache", ".mypy_cache", ".tox", ".idea", ".vscode"}

WIKILINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
HUNK_RE = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")
PIN_RANGE_RE = re.compile(
    r"^(?P<path>[^:]+):(?P<start>\d+)-(?P<end>\d+)(?:@(?P<sha>[0-9a-fA-F]+))?$"
)
PIN_SYMBOL_RE = re.compile(
    r"^(?P<path>[^:]+):(?P<symbol>[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*)"
    r"(?:@(?P<sha>[0-9a-fA-F]+))?$"
)


# ─── data classes ────────────────────────────────────────────────────────

@dataclass
class Pin:
    raw: str
    path: str
    kind: str  # "file" | "symbol" | "range"
    symbol: str | None = None
    start_line: int | None = None  # 1-indexed
    end_line: int | None = None    # 1-indexed inclusive
    sha: str | None = None
    resolved_start: int | None = None
    resolved_end: int | None = None
    relocated: bool = False


@dataclass
class Page:
    rel_path: str
    abs_path: Path
    raw_text: str
    frontmatter: dict
    body: str
    pins: list[Pin] = field(default_factory=list)
    outbound_links: list[tuple[str, int]] = field(default_factory=list)
    inbound_links: set[str] = field(default_factory=set)
    line_count: int = 0
    fm_state: str = "valid"

    @property
    def is_meta(self) -> bool:
        return Path(self.rel_path).name in META_FILE_NAMES

    @property
    def is_knowledge(self) -> bool:
        return any(self.rel_path.startswith(d + "/") for d in KNOWLEDGE_DIRS)


@dataclass
class LintIssue:
    severity: str
    category: str
    page: str
    message: str
    location: str = ""
    suggestion: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WikiContext:
    root: Path
    pages: list[Page]
    pages_by_path: dict[str, Page]
    pages_by_stem: dict[str, list[Page]]
    schema_tags: set[str]
    gap_exclusions: set[str]
    git_root: Path | None
    git_head: str | None
    no_git: bool


# ─── parsing / loading ───────────────────────────────────────────────────

class _DuplicateKeyError(yaml.YAMLError):
    pass


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys instead of last-wins."""

    def construct_mapping(self, node, deep=False):
        # Scan the EXPLICIT pairs only, skipping merge keys (`<<:`): SafeLoader
        # flattens merges inside super(), where a merged default overridden by
        # an explicit key is legal YAML, not a duplicate -- and constructing the
        # merge tag here raised, turning valid merge-using frontmatter into
        # error:yaml (round-1 Major 2).
        seen = set()
        for key_node, _value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=True)
            try:
                dup = key in seen
            except TypeError:
                continue
            if dup:
                raise _DuplicateKeyError("duplicate frontmatter key: %r" % (key,))
            seen.add(key)
        return super().construct_mapping(node, deep)


def _frontmatter_end(lines: list[str]) -> int | None:
    """Index of the closing delimiter: column-zero `---` only. The lenient
    `.strip()` scan let an indented `---` inside a YAML block scalar close the
    block early, silently truncating both frontmatter and body. Shared by the
    parser and the pin writer so reader and writer agree on the boundary."""
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == "---":
            return i
    return None


def split_frontmatter(text: str) -> tuple[str, dict, str]:
    """Return (state, frontmatter_dict, body). state is "absent" | "valid" |
    "error:<unterminated|duplicate-key|non-mapping|yaml>". fm is {} unless
    valid -- malformed input is a NAMED state, never an empty dict that reads
    like deliberate absence (fail-closed; the collapse was reported as a Major
    against the doc-gap exclusions that depend on this boundary)."""
    if not (text.startswith("---\n") or text.startswith("---\r\n")):
        return "absent", {}, text
    lines = text.splitlines(keepends=True)
    end_idx = _frontmatter_end(lines)
    if end_idx is None:
        return "error:unterminated", {}, text
    fm_text = "".join(lines[1:end_idx])
    body = "".join(lines[end_idx + 1:])
    try:
        data = yaml.load(fm_text, Loader=_StrictLoader)
    except _DuplicateKeyError:
        return "error:duplicate-key", {}, body
    except yaml.YAMLError:
        return "error:yaml", {}, body
    if data is None:
        return "valid", {}, body
    if not isinstance(data, dict):
        return "error:non-mapping", {}, body
    return "valid", data, body


def parse_pin(raw: str) -> Pin | None:
    raw = raw.strip()
    if not raw:
        return None
    m = PIN_RANGE_RE.match(raw)
    if m:
        sha = m.group("sha")
        return Pin(
            raw=raw,
            path=m.group("path"),
            kind="range",
            start_line=int(m.group("start")),
            end_line=int(m.group("end")),
            sha=sha.lower() if sha else None,
        )
    m = PIN_SYMBOL_RE.match(raw)
    if m:
        sha = m.group("sha")
        return Pin(
            raw=raw,
            path=m.group("path"),
            kind="symbol",
            symbol=m.group("symbol"),
            sha=sha.lower() if sha else None,
        )
    if "@" in raw:
        path, _, sha = raw.partition("@")
        return Pin(raw=raw, path=path, kind="file", sha=sha.lower() or None)
    return Pin(raw=raw, path=raw, kind="file")


def _blank_code(body: str) -> str:
    """Blank out fenced blocks and inline code spans while preserving line
    numbers, so a [[wikilink]] merely *mentioned* in code (e.g. `[[x]]` in
    prose, or inside a ``` fence) isn't scanned as a real link. Fenced regions
    are replaced line-for-line with empty lines; inline spans are removed.

    SHARED RULE — keep this fence/code-span strip identical to
    research-kb/scripts/kb-lint.py:strip_code. They are duplicated on purpose
    (the two linters are otherwise independent; ~90% of this file is git-pin
    stale machinery the KB linter doesn't use). If you change link-extraction
    behavior here, change it there too. Merge into one markdown-graph core only
    if a 3rd KB lands and the generic surface earns the abstraction."""
    lines = body.splitlines()
    in_fence = False
    out: list[str] = []
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append("")          # drop the fence marker line itself
            continue
        if in_fence:
            out.append("")          # keep line count, hide content
        else:
            out.append(_CODE_SPAN.sub("", line))
    return "\n".join(out)


_CODE_SPAN = re.compile(r"`[^`]*`")


def extract_wikilinks(body: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for i, line in enumerate(_blank_code(body).splitlines(), start=1):
        for m in WIKILINK_RE.finditer(line):
            # Strip `|alias` then `#anchor` — same normalization as
            # wiki-pages-for.py — so [[page#anchor]] / [[page#anchor|alias]]
            # resolve to the page they actually target.
            target = m.group(1).split("|", 1)[0].split("#", 1)[0].strip()
            if target:
                out.append((target, i))
    return out


def load_pages(wiki_root: Path) -> list[Page]:
    pages: list[Page] = []
    for md_path in wiki_root.rglob("*.md"):
        rel = md_path.relative_to(wiki_root)
        if rel.parts and rel.parts[0] in ARCHIVE_DIRS:
            continue
        try:
            # newline="": Path.read_text() normalises every terminator to \n, so a
            # byte-preserving WRITER downstream still produced an all-LF page from a
            # CRLF one -- fixing the write alone left the round trip lossy (r1 Major,
            # 2026-09-03). The reader is the other half of that invariant.
            with open(md_path, encoding="utf-8-sig", newline="") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError) as e:
            # A page the linter cannot read was silently DROPPED here: its pins,
            # links and frontmatter simply vanished from every check. Fail
            # closed -- keep a stub page carrying the named error state.
            pages.append(Page(
                rel_path=str(rel).replace("\\", "/"),
                abs_path=md_path,
                raw_text="",
                frontmatter={},
                body="",
                fm_state="error:unreadable-%s" % type(e).__name__,
            ))
            continue
        state, fm, body = split_frontmatter(text)
        pins: list[Pin] = []
        for src in (fm.get("sources") or []):
            if isinstance(src, str):
                p = parse_pin(src)
                if p:
                    pins.append(p)
        pages.append(Page(
            rel_path=str(rel).replace("\\", "/"),
            abs_path=md_path,
            raw_text=text,
            frontmatter=fm,
            body=body,
            pins=pins,
            outbound_links=extract_wikilinks(body),
            line_count=len(text.splitlines()),
            fm_state=state,
        ))
    return pages


def parse_schema_tags(wiki_root: Path) -> set[str]:
    """Heuristic extraction of the tag taxonomy from SCHEMA.md."""
    schema_path = wiki_root / "SCHEMA.md"
    if not schema_path.exists():
        return set()
    text = schema_path.read_text(encoding="utf-8", errors="replace")
    tags: set[str] = set()
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = "tag taxonomy" in stripped.lower()
            continue
        if not in_section:
            continue
        if not stripped.startswith("- "):
            continue
        content = stripped[2:].strip()
        # Skip placeholder text
        if content.startswith("[") and content.endswith("]"):
            continue
        if ":" in content:
            _, _, after = content.partition(":")
            for tok in after.split(","):
                tok = tok.strip().strip("`").strip().lower()
                if re.fullmatch(r"[a-z0-9][\w\-]*", tok):
                    tags.add(tok)
        else:
            tok = content.strip().strip("`").strip().lower()
            if re.fullmatch(r"[a-z0-9][\w\-]*", tok):
                tags.add(tok)
    return tags


GAP_EXCLUSION_KEY = "doc_gap_exclusions"


def parse_schema_gap_exclusions(wiki_root: Path) -> tuple[set[str], list[str]]:
    """(exclusions, problems) from SCHEMA.md's YAML FRONTMATTER.

    Top-level dirs declared out of scope for documentation-gap analysis. A wiki
    pins code; a project whose other knowledge layers live in the same repo
    (research KB, workflow state, harness config) would otherwise have every one
    of their files counted as an undocumented source gap, which cannot be paid
    down without writing wiki pages the layer routing forbids.

    This was a hand-written Markdown section parser and it was wrong three times
    in three ways -- a fenced example, an HTML-commented block, and a directory
    name with a space each silently suppressed a tree nobody meant to exclude,
    and the third round found the fence tracker still wrong for a four-backtick
    outer fence. Each fix reproduced one more corner of CommonMark. Config that
    suppresses coverage cannot live in prose that a human also writes examples
    in: it goes in the structured field, where malformed input is a LINT ISSUE
    rather than an entry that quietly disappears or, worse, matches something
    else.
    """
    schema_path = wiki_root / "SCHEMA.md"
    if not schema_path.exists():
        return set(), []
    # utf-8-sig, not utf-8: a BOM leaves the text starting "﻿---", which
    # split_frontmatter reads as "no frontmatter" -- the whole declaration would
    # vanish with nothing reported. PowerShell 5.1 Set-Content writes one by
    # default. Decoding is identical for BOM-less files. STRICT decode on
    # purpose: errors="replace" turned invalid bytes into U+FFFD that could be
    # accepted as a directory name -- undecodable config is a named problem.
    try:
        text = schema_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return set(), ["SCHEMA.md is not valid UTF-8 -- exclusions unreadable"]
    state, fm, _body = split_frontmatter(text)
    if state.startswith("error:"):
        return set(), ["SCHEMA.md frontmatter did not parse (%s)" % state]
    raw = fm.get(GAP_EXCLUSION_KEY)
    if raw is None:
        return set(), []
    if not isinstance(raw, list):
        return set(), ["SCHEMA.md %s must be a list of directory names"
                       % GAP_EXCLUSION_KEY]
    dirs: set[str] = set()
    problems: list[str] = []
    for entry in raw:
        if not isinstance(entry, str):
            problems.append("%s entry %r is not a string" % (GAP_EXCLUSION_KEY, entry))
            continue
        name = entry.strip().rstrip("/")
        # Exactly one top-level component: anything else is compared against
        # `Path(p).parts[0]` and can never match, i.e. a silently dead entry.
        if not name or "/" in name or "\\" in name:
            problems.append("%s entry %r is not a single top-level directory"
                            % (GAP_EXCLUSION_KEY, entry))
            continue
        dirs.add(name)
    return dirs, problems


def discover_wiki(start: Path) -> Path | None:
    cur = start.resolve()
    while True:
        if (cur / "wiki" / "SCHEMA.md").exists():
            return cur / "wiki"
        if cur.name == "wiki" and (cur / "SCHEMA.md").exists():
            return cur
        parent = cur.parent
        if parent == cur:
            return None
        cur = parent


def resolve_wikilink(target: str, wiki: WikiContext) -> Page | None:
    target = target.strip().strip("/")
    if not target:
        return None
    candidates = [target, target + ".md"]
    for d in KNOWLEDGE_DIRS:
        candidates.append(f"{d}/{target}.md")
        candidates.append(f"{d}/{target}")
    for cand in candidates:
        if cand in wiki.pages_by_path:
            return wiki.pages_by_path[cand]
    stem = Path(target).stem
    cands = wiki.pages_by_stem.get(stem)
    if cands:
        if len(cands) == 1:
            return cands[0]
        knowledge = [p for p in cands if p.is_knowledge]
        if len(knowledge) == 1:
            return knowledge[0]
    return None


def build_inbound_links(wiki: WikiContext) -> None:
    for page in wiki.pages:
        for target, _ in page.outbound_links:
            r = resolve_wikilink(target, wiki)
            if r is not None and r.rel_path != page.rel_path:
                r.inbound_links.add(page.rel_path)


# ─── git helpers ─────────────────────────────────────────────────────────

def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def get_git_root(start: Path) -> Path | None:
    res = run_git(["rev-parse", "--show-toplevel"], start)
    if res.returncode != 0:
        return None
    out = res.stdout.strip()
    return Path(out) if out else None


def get_git_head(root: Path) -> str | None:
    res = run_git(["rev-parse", "HEAD"], root)
    return res.stdout.strip() if res.returncode == 0 else None


def get_file_at_sha(root: Path, sha: str, rel_path: str) -> str | None:
    res = run_git(["show", f"{sha}:{rel_path}"], root)
    return res.stdout if res.returncode == 0 else None


def get_diff(root: Path, sha: str, *rel_paths: str) -> str | None:
    """Diff sha..HEAD, or None when git could not prove the result.

    Passing both an old and a new path enables git's rename detection (default
    in modern git) to produce a unified diff across a `git mv`.
    """
    if not rel_paths:
        return ""
    res = run_git(["diff", f"{sha}..HEAD", "--", *rel_paths], root)
    return res.stdout if res.returncode == 0 else None


def count_commits_since(root: Path, sha: str, rel_path: str) -> int | None:
    """Count commits or return None when git could not prove the count."""
    res = run_git(["rev-list", "--count", f"{sha}..HEAD", "--", rel_path], root)
    if res.returncode != 0:
        return None
    try:
        return int(res.stdout.strip() or "0")
    except ValueError:
        return None


def valid_commit_ref(root: Path, sha: str) -> bool:
    if not sha:
        return False
    res = run_git(["cat-file", "-e", f"{sha}^{{commit}}"], root)
    return res.returncode == 0


def list_recently_touched_paths(root: Path, since_days: int) -> set[str] | None:
    res = run_git(
        ["log", f"--since={since_days} days ago", "--name-only", "--pretty=format:"],
        root,
    )
    if res.returncode != 0:
        return None
    return {p.strip() for p in res.stdout.splitlines() if p.strip()}


def find_rename_target(root: Path, sha: str, old_path: str) -> str | None:
    """Trace `old_path` forward through git renames between `sha` and HEAD.

    Returns the current path of the file that lived at `old_path` when `sha`
    was made, or None if the file cannot be tracked through renames.

    Uses `git log --diff-filter=R --name-status sha..HEAD` to enumerate every
    rename in the range (newest first), reverses to chronological order, and
    chains them: if `old_path` was renamed to `mid`, and `mid` to `new`, the
    walk yields `new`. The final path must exist in the working tree to be
    returned. Returns None when the file did not exist at `sha`, when the
    file still exists at `old_path` (caller should not have asked), or when
    no chain reaches a present-day path.
    """
    if not sha:
        return None
    if get_file_at_sha(root, sha, old_path) is None:
        return None
    if (root / old_path).exists():
        return None
    res = run_git(
        ["log", "--diff-filter=R", "--name-status",
         "--pretty=format:", f"{sha}..HEAD"],
        root,
    )
    if res.returncode != 0:
        return None
    renames: list[tuple[str, str]] = []
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].startswith("R"):
            renames.append((parts[1], parts[2]))
    if not renames:
        return None
    renames.reverse()  # chronological: oldest rename first
    cur = old_path
    for old, new in renames:
        if old == cur:
            cur = new
    if cur == old_path:
        return None
    if not (root / cur).exists():
        return None
    return cur


# ─── diff parsing ────────────────────────────────────────────────────────

def parse_diff_hunks(diff_text: str) -> list[tuple[int, int, int, int, list[str]]]:
    """Return [(old_start, old_count, new_start, new_count, body_lines), ...]."""
    hunks: list[tuple[int, int, int, int, list[str]]] = []
    cur: tuple[int, int, int, int] | None = None
    cur_lines: list[str] = []
    for line in diff_text.splitlines():
        m = HUNK_RE.match(line)
        if m:
            if cur is not None:
                hunks.append((*cur, cur_lines))
            cur = (
                int(m.group(1)),
                int(m.group(2) or 1),
                int(m.group(3)),
                int(m.group(4) or 1),
            )
            cur_lines = []
            continue
        if cur is None:
            continue
        if line.startswith(("+++", "---", "diff ", "index ", "Binary ")):
            continue
        cur_lines.append(line)
    if cur is not None:
        hunks.append((*cur, cur_lines))
    return hunks


def hunk_changed_lines(old_start: int, new_start: int,
                       body_lines: list[str]) -> tuple[list[int], list[int]]:
    """Return (added_new_lines, removed_old_lines), 1-indexed positions.

    Tracks only `+` and `-` lines; context (` `) lines advance both counters
    but are not reported as changes. The "\\ No newline at end of file"
    marker is skipped without advancing either counter.
    """
    cur_new = new_start
    cur_old = old_start
    added: list[int] = []
    removed: list[int] = []
    for line in body_lines:
        if not line:
            cur_new += 1
            cur_old += 1
            continue
        c = line[0]
        if c == "+":
            added.append(cur_new)
            cur_new += 1
        elif c == "-":
            removed.append(cur_old)
            cur_old += 1
        elif c == "\\":
            continue
        else:
            cur_new += 1
            cur_old += 1
    return added, removed


# ─── symbol resolution ───────────────────────────────────────────────────

def find_symbol_decl_line(content: str, symbol: str, ext: str) -> int | None:
    """Return 1-indexed line of the symbol's declaration, or None."""
    if not symbol:
        return None
    if "." in symbol:
        # Qualified pin (`Class.method`): match on the last dotted component.
        # When the parent declaration is cheaply locatable, search only from
        # its line onward so a same-named symbol earlier in the file doesn't
        # shadow the method; otherwise fall back to a whole-file search.
        parent, _, leaf = symbol.rpartition(".")
        parent_line = find_symbol_decl_line(content, parent, ext)
        if parent_line is not None:
            tail = "\n".join(content.splitlines()[parent_line - 1:])
            leaf_line = find_symbol_decl_line(tail, leaf, ext)
            return parent_line - 1 + leaf_line if leaf_line is not None else None
        return find_symbol_decl_line(content, leaf, ext)
    name = re.escape(symbol)
    if ext == ".py":
        pattern = re.compile(
            rf"^\s*(?:async\s+)?def\s+{name}\s*\(|"
            rf"^\s*class\s+{name}\s*[\(:]|"
            rf"^\s*{name}\s*[:=]",
            re.M,
        )
    elif ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        pattern = re.compile(
            rf"(?:^|[\s;])"
            rf"(?:export\s+(?:default\s+)?)?"
            rf"(?:async\s+)?"
            rf"(?:function\s*\*?|class|const|let|var|interface|type|enum|namespace)"
            rf"\s+{name}\b"
            # Class methods / accessors / arrow-fn class fields carry no
            # declaration keyword. As in the Java branch, gate on the trailing
            # body opener — `{` after the parameter list (and optional return
            # type), or `=> ` for arrow fields — so plain calls like
            # `name(arg);` or `name(arg).then(...)` don't match.
            rf"|^\s*(?:(?:public|private|protected|static|readonly|override|"
            rf"abstract|async|get|set)\s+)*"
            rf"(?:{name}\s*(?:<[^>]*>)?\s*\([^)]*\)\s*(?::[^{{;]+)?\s*\{{"
            rf"|{name}\s*=\s*(?:async\s+)?\([^)]*\)\s*(?::[^=]+)?=>)"
        )
    elif ext == ".go":
        pattern = re.compile(
            rf"^(?:func(?:\s+\([^)]*\))?\s+{name}\b|"
            rf"type\s+{name}\b|var\s+{name}\b|const\s+{name}\b)",
            re.M,
        )
    elif ext == ".rs":
        pattern = re.compile(
            rf"^\s*(?:pub(?:\([^)]*\))?\s+)?"
            rf"(?:async\s+)?(?:unsafe\s+)?"
            rf"(?:fn|struct|enum|trait|type|const|static|mod|impl)"
            rf"\s+{name}\b",
            re.M,
        )
    elif ext in (".java", ".kt", ".scala"):
        pattern = re.compile(
            rf"\b(?:class|interface|enum|record|object|trait)\s+{name}\b|"
            rf"\b{name}\s*\([^)]*\)\s*[{{;]"
        )
    elif ext == ".cs":
        # C# needs `record` (incl. the brace-less `public abstract record X;`
        # form the generic fallback misses) plus the fallback's loose tail so
        # every pin that resolved under the old default keeps resolving.
        pattern = re.compile(
            rf"\b(?:class|interface|enum|record|struct|delegate)\s+{name}\b|"
            rf"\b{name}\s*(?:<[^>]*>)?\s*\([^)]*\)\s*(?:\{{|;|=>)|"
            rf"\b{name}\b\s*[=:({{<]"
        )
    elif ext in (".c", ".cpp", ".cc", ".h", ".hpp"):
        # A wrapped prototype (`API int32_t  name(arg,\n  arg);`) never shows
        # `name(...) {` on one line, so also accept a declaration-START line:
        # one or more type-ish tokens (not statement keywords, so call sites
        # like `return name(...)` don't match) directly before `name(`.
        pattern = re.compile(
            rf"\b(?:class|struct|enum|union|typedef\s+\w+)\s+{name}\b|"
            rf"\b{name}\s*\([^)]*\)\s*\{{|"
            rf"^\s*(?:(?!return\b|goto\b|case\b|else\b|new\b|delete\b|throw\b|"
            rf"if\b|while\b|for\b|switch\b|do\b)[\w\*]+\s+)+\**{name}\s*\("
        )
    else:
        pattern = re.compile(
            rf"\b(?:def|fn|func|function|class|struct|enum|trait|"
            rf"interface|type|const|let|var)\b[^\n]*\b{name}\b|"
            rf"\b{name}\b\s*[=:({{<]"
        )
    for i, line in enumerate(content.splitlines()):
        if pattern.search(line):
            return i + 1
    return None


def _strip_strings_and_line_comments(line: str) -> str:
    out: list[str] = []
    i = 0
    in_string: str | None = None
    while i < len(line):
        ch = line[i]
        if in_string:
            if ch == "\\" and i + 1 < len(line):
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            in_string = ch
            i += 1
            continue
        if ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
            break
        if ch == "#" and (i == 0 or line[i - 1] != "$"):
            break
        out.append(ch)
        i += 1
    return "".join(out)


def estimate_symbol_body_end(content: str, decl_line: int, ext: str) -> int:
    """Return 1-indexed end line of the body (inclusive)."""
    lines = content.splitlines()
    decl_idx = decl_line - 1
    if decl_idx >= len(lines) or decl_idx < 0:
        return decl_line
    if ext == ".py":
        decl = lines[decl_idx]
        decl_indent = len(decl) - len(decl.lstrip())
        end_idx = decl_idx
        for i in range(decl_idx + 1, len(lines)):
            ln = lines[i]
            if not ln.strip():
                continue
            ln_indent = len(ln) - len(ln.lstrip())
            if ln_indent <= decl_indent:
                break
            end_idx = i
        return end_idx + 1
    if ext in SYMBOL_BODY_BRACE_LANGS:
        depth = 0
        seen = False
        for i in range(decl_idx, min(len(lines), decl_idx + 2000)):
            for ch in _strip_strings_and_line_comments(lines[i]):
                if ch == "{":
                    depth += 1
                    seen = True
                elif ch == "}":
                    depth -= 1
                    if seen and depth == 0:
                        return i + 1
        return min(decl_line + 50, len(lines))
    # Generic fallback: fixed window of up to 79 lines past the declaration,
    # capped at end of file (no decl-aware early stop is attempted).
    end_idx = decl_idx
    for i in range(decl_idx + 1, min(len(lines), decl_idx + 80)):
        end_idx = i
    return end_idx + 1


# ─── range pin re-anchoring ──────────────────────────────────────────────

def relocate_range(repo_root: Path, pin: Pin,
                   cur_content: str) -> tuple[int, int, bool] | None:
    """Re-locate a range pin. Returns (new_start, new_end, shifted) or None."""
    if pin.sha is None or pin.start_line is None or pin.end_line is None:
        return None
    old_content = get_file_at_sha(repo_root, pin.sha, pin.path)
    if old_content is None:
        return None
    old_lines = old_content.splitlines()
    if pin.start_line < 1 or pin.end_line > len(old_lines) or pin.start_line > pin.end_line:
        return None
    pinned_block = "\n".join(old_lines[pin.start_line - 1: pin.end_line])
    if not pinned_block.strip():
        return None
    cur_text = "\n".join(cur_content.splitlines())
    idx = cur_text.find(pinned_block)
    if idx == -1:
        return None
    new_start = cur_text.count("\n", 0, idx) + 1
    new_count = pinned_block.count("\n") + 1
    new_end = new_start + new_count - 1
    shifted = (new_start != pin.start_line or new_end != pin.end_line)
    return new_start, new_end, shifted


# ─── stale checks ────────────────────────────────────────────────────────

def check_stale_layer1(wiki: WikiContext) -> list[LintIssue]:
    if wiki.no_git or wiki.git_root is None:
        return []
    issues: list[LintIssue] = []
    for page in wiki.pages:
        if not page.is_knowledge:
            continue
        for pin in page.pins:
            if pin.kind == "file" and ":" in pin.path:
                # parse_pin fell through to a file pin whose "path" still
                # contains ':' — the pin matched no known shape. Surface it
                # instead of misreporting a missing file.
                issues.append(LintIssue(
                    severity="low",
                    category="malformed-pin",
                    page=page.rel_path,
                    location=pin.raw,
                    message="Pin did not parse as file/symbol/range (path contains ':')",
                    suggestion="Rewrite as path, path:symbol@<sha>, or path:start-end@<sha>",
                ))
                continue
            if not pin.sha:
                issues.append(LintIssue(
                    severity="low",
                    category="unpinned-sha",
                    page=page.rel_path,
                    location=pin.raw,
                    message="Pin has no @<sha> suffix; stale detection skipped for it",
                    suggestion="Re-pin with the current commit SHA (git rev-parse HEAD)",
                ))
                continue
            if not valid_commit_ref(wiki.git_root, pin.sha):
                issues.append(LintIssue(
                    severity="high",
                    category="invalid-pin-ref",
                    page=page.rel_path,
                    location=pin.raw,
                    message=f"Pin commit {pin.sha!r} does not resolve in this repository",
                    suggestion="Re-pin with a resolvable commit SHA (git rev-parse HEAD)",
                ))
                continue
            issues.extend(_check_pin_layer1(page, pin, wiki))
    return issues


def _check_pin_layer1(page: Page, pin: Pin, wiki: WikiContext) -> list[LintIssue]:
    repo_root = wiki.git_root
    assert repo_root is not None
    abs_src = repo_root / pin.path

    # Path resolution: if the pinned file is missing, try to follow a rename
    # before declaring the pin dead. A successful rename detection switches
    # the rest of re-anchoring to the new path; the rename itself is recorded
    # as an info-level shift and applied on --update-pins.
    renamed_to: str | None = None
    if not abs_src.exists():
        renamed_to = find_rename_target(repo_root, pin.sha or "", pin.path)
        if renamed_to is None:
            was_present = get_file_at_sha(repo_root, pin.sha or "", pin.path) is not None
            return [LintIssue(
                severity="high",
                category="stale-l1-file-missing",
                page=page.rel_path,
                location=pin.raw,
                message=("Pinned file no longer exists in the working tree"
                         if was_present else
                         "Pinned file does not exist (and never did at this SHA)"),
                suggestion="Update the pin to the file's new location, or remove if obsolete",
            )]
        abs_src = repo_root / renamed_to
    effective_path = renamed_to or pin.path

    issues: list[LintIssue] = []

    def _emit_rename(new_pin_str: str) -> None:
        new_sha = wiki.git_head or pin.sha
        sha_note = ""
        if new_sha and pin.sha and new_sha != pin.sha:
            sha_note = f" and SHA {pin.sha[:7]} -> {new_sha[:7]}"
        issues.append(LintIssue(
            severity="info",
            category="stale-l1-rename",
            page=page.rel_path,
            location=pin.raw,
            message=(f"Pin file renamed: {pin.path} -> {renamed_to}{sha_note}"),
            suggestion="Run with --update-pins to rewrite the pin path",
            extra={"new_pin": new_pin_str, "old_path": pin.path,
                   "new_path": renamed_to},
        ))

    if pin.kind == "file":
        if renamed_to:
            new_sha = wiki.git_head or pin.sha
            new_pin_str = effective_path + (f"@{new_sha}" if new_sha else "")
            _emit_rename(new_pin_str)
            return issues
        n = count_commits_since(repo_root, pin.sha or "", pin.path)
        if n is None:
            issues.append(LintIssue(
                severity="high",
                category="git-history-failed",
                page=page.rel_path,
                location=pin.raw,
                message=f"Could not count commits touching {pin.path}",
                suggestion="Resolve the git error and rerun wiki-lint",
            ))
        elif n > 0:
            issues.append(LintIssue(
                severity="medium",
                category="stale-l1-file",
                page=page.rel_path,
                location=pin.raw,
                message=f"File pin: {n} commits touched {pin.path} since {(pin.sha or '')[:7]}",
                suggestion="Refresh the page or pin at symbol/range level",
            ))
        return issues

    try:
        cur_content = abs_src.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return issues
    ext = abs_src.suffix

    if pin.kind == "symbol":
        decl_line = find_symbol_decl_line(cur_content, pin.symbol or "", ext)
        if decl_line is None:
            issues.append(LintIssue(
                severity="high",
                category="stale-l1-symbol-missing",
                page=page.rel_path,
                location=pin.raw,
                message=(f"Symbol {pin.symbol!r} not found in {effective_path}"
                         + (f" (renamed from {pin.path})" if renamed_to else "")),
                suggestion="The symbol was removed or renamed; refresh the page or update the pin",
            ))
            return issues
        body_end = estimate_symbol_body_end(cur_content, decl_line, ext)
        pin.resolved_start = decl_line
        pin.resolved_end = body_end
        old_start, old_end = decl_line, body_end
        old_content = get_file_at_sha(repo_root, pin.sha or "", pin.path)
        if old_content is not None:
            o_decl = find_symbol_decl_line(old_content, pin.symbol or "", ext)
            if o_decl is not None:
                old_start = o_decl
                old_end = estimate_symbol_body_end(old_content, o_decl, ext)
        if renamed_to:
            new_sha = wiki.git_head or pin.sha
            new_pin_str = f"{effective_path}:{pin.symbol}" + (f"@{new_sha}" if new_sha else "")
            _emit_rename(new_pin_str)
        issues.extend(_check_range_touched(
            page, pin, repo_root,
            decl_line, body_end, old_start, old_end, "symbol",
            new_path=renamed_to,
        ))
        return issues

    if pin.kind == "range":
        relocated = relocate_range(repo_root, pin, cur_content)
        if relocated is None:
            issues.append(LintIssue(
                severity="high",
                category="stale-l1-range-missing",
                page=page.rel_path,
                location=pin.raw,
                message=(f"Range {pin.start_line}-{pin.end_line} content not "
                         f"locatable in current {effective_path}"
                         + (f" (renamed from {pin.path})" if renamed_to else "")),
                suggestion="The pinned region was rewritten; refresh the page or update the pin",
            ))
            return issues
        new_start, new_end, shifted = relocated
        pin.resolved_start = new_start
        pin.resolved_end = new_end
        pin.relocated = shifted
        if renamed_to:
            new_sha = wiki.git_head or pin.sha
            new_pin_str = f"{effective_path}:{new_start}-{new_end}" + (f"@{new_sha}" if new_sha else "")
            _emit_rename(new_pin_str)
        elif shifted:
            # Silent shift: content unchanged, only location moved. We rewrite
            # both the line range AND the SHA — keeping the old SHA would
            # leave the new range pointing into an unrelated region of the
            # file as it existed at the old SHA. Bumping to HEAD records that
            # the same content has been re-confirmed at this commit.
            new_sha = wiki.git_head or pin.sha
            new_pin_str = f"{pin.path}:{new_start}-{new_end}"
            if new_sha:
                new_pin_str += f"@{new_sha}"
            sha_note = ""
            if new_sha and pin.sha and new_sha != pin.sha:
                sha_note = f" and SHA {pin.sha[:7]} -> {new_sha[:7]}"
            issues.append(LintIssue(
                severity="info",
                category="stale-l1-shift",
                page=page.rel_path,
                location=pin.raw,
                message=(f"Pin shifted silently: {pin.start_line}-{pin.end_line} "
                         f"-> {new_start}-{new_end}{sha_note} (content unchanged)"),
                suggestion="Run with --update-pins to rewrite the pin",
                extra={"new_pin": new_pin_str},
            ))
        issues.extend(_check_range_touched(
            page, pin, repo_root,
            new_start, new_end,
            pin.start_line or new_start, pin.end_line or new_end,
            "range",
            new_path=renamed_to,
        ))
        return issues

    return issues


def _check_range_touched(page: Page, pin: Pin, repo_root: Path,
                         new_start: int, new_end: int,
                         old_start: int, old_end: int,
                         kind_label: str,
                         new_path: str | None = None) -> list[LintIssue]:
    """Check whether the resolved range was actually modified.

    Counts only `+` lines whose new-file position falls within the resolved
    new range, and `-` lines whose old-file position falls within the old
    resolved range. Pure context (` `) lines do NOT count as a touch — this
    is what makes the line-shift case (insertions above the pin) silent.

    When `new_path` is set (file was renamed), both old and new paths are
    passed to git diff so rename detection produces a unified diff and the
    new-file line numbers in hunks line up with `new_start..new_end`.
    """
    if new_path and new_path != pin.path:
        diff = get_diff(repo_root, pin.sha or "", pin.path, new_path)
    else:
        diff = get_diff(repo_root, pin.sha or "", pin.path)
    if diff is None:
        return [LintIssue(
            severity="high",
            category="git-history-failed",
            page=page.rel_path,
            location=pin.raw,
            message=f"Git could not diff {pin.sha or '<missing>'}..HEAD for {pin.path}",
            suggestion="Repair the git repository/ref and rerun wiki-lint",
        )]
    if not diff.strip():
        return []
    hunks = parse_diff_hunks(diff)
    intersecting: list[tuple[int, int, list[str]]] = []
    for h_old_s, _h_old_c, h_new_s, h_new_c, body_lines in hunks:
        added, removed = hunk_changed_lines(h_old_s, h_new_s, body_lines)
        added_in = [n for n in added if new_start <= n <= new_end]
        removed_in = [n for n in removed if old_start <= n <= old_end]
        if added_in or removed_in:
            intersecting.append((h_new_s, h_new_c, body_lines))
    if not intersecting:
        return []
    severity, label = _classify_diff(intersecting)
    rename_note = f" (in renamed {new_path})" if new_path and new_path != pin.path else ""
    return [LintIssue(
        severity=severity,
        category=f"stale-l1-{kind_label}-touched-{label}",
        page=page.rel_path,
        location=pin.raw,
        message=(f"{kind_label.capitalize()} pin: range {new_start}-{new_end} "
                 f"touched by {len(intersecting)} hunk(s); classification {label}"
                 f"{rename_note}"),
        suggestion="Run refresh to reconcile the page with current source",
        extra={"hunks": [{"new_start": hs, "new_count": hc} for hs, hc, _ in intersecting]},
    )]


def _classify_diff(intersecting: list[tuple[int, int, list[str]]]) -> tuple[str, str]:
    """Heuristic Layer 2: returns (severity, label)."""
    high_signals = 0
    body_changes = 0
    only_low = True
    for _, _, lines in intersecting:
        for raw in lines:
            if not raw or raw[0] not in ("+", "-"):
                continue
            content = raw[1:]
            stripped = content.strip()
            if not stripped:
                continue
            if stripped.startswith(("//", "#", "/*", "*", "*/", "<!--", "-->")):
                continue
            only_low = False
            body_changes += 1
            if re.search(r"\b(?:export|public|pub)\b", stripped):
                high_signals += 1
            if re.search(r"\b(?:function|def|fn|func|class|struct|interface|type|enum|trait)\b",
                         stripped):
                high_signals += 1
            if re.search(r"\)\s*(?:->|:)", stripped):
                high_signals += 1
    if only_low:
        return "low", "low"
    if high_signals >= 2 or body_changes > 25:
        return "high", "high"
    return "medium", "medium"


def check_stale_layer3(wiki: WikiContext) -> list[LintIssue]:
    if wiki.no_git or wiki.git_root is None:
        return []
    issues: list[LintIssue] = []
    repo_root = wiki.git_root
    for page in wiki.pages:
        if not page.is_knowledge:
            continue
        verified_at = page.frontmatter.get("verified_at")
        if not verified_at:
            continue
        paths = {pin.path for pin in page.pins if pin.path}
        if not paths:
            continue
        verified_ref = str(verified_at)
        if not valid_commit_ref(repo_root, verified_ref):
            issues.append(LintIssue(
                severity="high",
                category="invalid-verified-ref",
                page=page.rel_path,
                message=f"verified_at commit {verified_ref!r} does not resolve in this repository",
                suggestion="Set verified_at to a resolvable commit after reconciling the page",
            ))
            continue
        counts = [count_commits_since(repo_root, verified_ref, p) for p in paths]
        if any(n is None for n in counts):
            issues.append(LintIssue(
                severity="high",
                category="git-history-failed",
                page=page.rel_path,
                message="Could not count source-history commits for Layer 3 trust decay",
                suggestion="Resolve the git error and rerun wiki-lint",
            ))
            continue
        total = sum(n for n in counts if n is not None)
        if total >= TRUST_DECAY_THRESHOLD:
            cur_conf = page.frontmatter.get("confidence")
            new_conf = "medium" if cur_conf == "high" else (cur_conf or "medium")
            issues.append(LintIssue(
                severity="medium",
                category="stale-l3-trust-decay",
                page=page.rel_path,
                message=(f"{total} commits touched pinned sources since "
                         f"verified_at={str(verified_at)[:7]} (threshold {TRUST_DECAY_THRESHOLD})"),
                suggestion=(f"Refresh the page; demote confidence: "
                            f"{cur_conf or '<unset>'} → {new_conf}"),
                extra={"commit_count": total, "current_confidence": cur_conf,
                       "demote_to": new_conf},
            ))
    return issues


# ─── non-stale checks ────────────────────────────────────────────────────

def check_broken_wikilinks(wiki: WikiContext) -> list[LintIssue]:
    issues: list[LintIssue] = []
    for page in wiki.pages:
        for target, lineno in page.outbound_links:
            if resolve_wikilink(target, wiki) is None:
                issues.append(LintIssue(
                    severity="critical",
                    category="broken-wikilink",
                    page=page.rel_path,
                    location=f"line {lineno}",
                    message=f"[[{target}]] — target not found",
                    suggestion="Create the target page or fix the wikilink",
                ))
    return issues


def check_orphans(wiki: WikiContext) -> list[LintIssue]:
    issues: list[LintIssue] = []
    for page in wiki.pages:
        if page.is_meta or not page.is_knowledge:
            continue
        if not page.inbound_links:
            issues.append(LintIssue(
                severity="medium",
                category="orphan",
                page=page.rel_path,
                message="No inbound wikilinks from any other page",
                suggestion="Link to this page from related pages (the convention's minimum-2-links rule is outbound, per page), or archive if obsolete",
            ))
    return issues


def check_index_completeness(wiki: WikiContext) -> list[LintIssue]:
    index_page = wiki.pages_by_path.get("index.md")
    if index_page is None:
        return [LintIssue(
            severity="high",
            category="meta-missing",
            page="index.md",
            message="index.md is missing",
        )]
    referenced: set[str] = set()
    for target, _ in index_page.outbound_links:
        r = resolve_wikilink(target, wiki)
        if r:
            referenced.add(r.rel_path)
    for m in MD_LINK_RE.finditer(index_page.body):
        href = m.group(2).strip()
        if href.startswith(("http://", "https://", "#", "mailto:")):
            continue
        # Strip only a literal leading "./" (mirrors wiki-pages-for.py's norm);
        # lstrip("./") would also mangle "../x" and dotfile paths.
        href_norm = href.replace("\\", "/")
        if href_norm.startswith("./"):
            href_norm = href_norm[2:]
        if href_norm in wiki.pages_by_path:
            referenced.add(href_norm)
        elif (href_norm + ".md") in wiki.pages_by_path:
            referenced.add(href_norm + ".md")
    issues: list[LintIssue] = []
    for page in wiki.pages:
        if page.is_meta or not page.is_knowledge:
            continue
        if page.rel_path not in referenced:
            issues.append(LintIssue(
                severity="medium",
                category="index-missing",
                page=page.rel_path,
                message="Page is not listed in index.md",
                suggestion="Add an entry to the appropriate section of index.md",
            ))
    return issues


def frontmatter_error_issues(wiki: WikiContext) -> list[LintIssue]:
    """Error states fire for EVERY non-archive page, meta included: an
    unreadable file or a malformed frontmatter construct is affirmatively
    broken, unlike absence (meta pages legitimately carry none). Emitted once
    for ANY requested check that consumes frontmatter-derived state -- a page
    whose parse errored presents fm={} / pins=[] to those checks, so an
    isolated `--check tags` run exiting 0 on it would be the old fail-open
    collapse with extra steps (round-1 Major 1). The 2026-09-02 probe measured
    zero such states across all live wikis, so this is a live no-op today."""
    issues: list[LintIssue] = []
    for page in wiki.pages:
        if page.fm_state.startswith("error:unreadable"):
            issues.append(LintIssue(
                severity="critical",
                category="page-unreadable",
                page=page.rel_path,
                message="File could not be read (%s)" % page.fm_state,
                suggestion="Fix the file's encoding or permissions; its pins and links are invisible to every check",
            ))
        elif page.fm_state.startswith("error:"):
            issues.append(LintIssue(
                severity="critical",
                category="frontmatter-yaml",
                page=page.rel_path,
                message="Frontmatter failed strict parse (%s)" % page.fm_state,
                suggestion="Fix the frontmatter block: terminate it with a column-zero ---, remove duplicate keys, keep it a YAML mapping",
            ))
    return issues


def check_frontmatter(wiki: WikiContext) -> list[LintIssue]:
    issues: list[LintIssue] = []
    for page in wiki.pages:
        if page.fm_state.startswith("error:"):
            continue
        if page.is_meta or not page.is_knowledge:
            continue
        fm = page.frontmatter
        if not fm:
            issues.append(LintIssue(
                severity="critical",
                category="frontmatter-missing",
                page=page.rel_path,
                message="Knowledge page has no frontmatter",
                suggestion="Add YAML frontmatter with required fields per SCHEMA.md",
            ))
            continue
        for fld in REQUIRED_FRONTMATTER:
            if fld not in fm:
                issues.append(LintIssue(
                    severity="high",
                    category="frontmatter-missing-field",
                    page=page.rel_path,
                    message=f"Required frontmatter field missing: {fld}",
                ))
        t = fm.get("type")
        if t and t not in VALID_TYPES:
            issues.append(LintIssue(
                severity="high",
                category="frontmatter-invalid-type",
                page=page.rel_path,
                message=f"type: {t!r} is not in {sorted(VALID_TYPES)}",
            ))
        conf = fm.get("confidence")
        if conf is not None and conf not in VALID_CONFIDENCE:
            issues.append(LintIssue(
                severity="medium",
                category="frontmatter-invalid-confidence",
                page=page.rel_path,
                message=f"confidence: {conf!r} is not in {sorted(VALID_CONFIDENCE)}",
            ))
    return issues


def check_tag_taxonomy(wiki: WikiContext) -> list[LintIssue]:
    if not wiki.schema_tags:
        return []
    issues: list[LintIssue] = []
    for page in wiki.pages:
        if not page.is_knowledge:
            continue
        tags = page.frontmatter.get("tags") or []
        if not isinstance(tags, list):
            continue
        for t in tags:
            if not isinstance(t, str):
                continue
            t_norm = t.strip().lower()
            if t_norm and t_norm not in wiki.schema_tags:
                issues.append(LintIssue(
                    severity="medium",
                    category="tag-not-in-taxonomy",
                    page=page.rel_path,
                    message=f"tag {t!r} is not in SCHEMA.md taxonomy",
                    suggestion=f"Add {t!r} to SCHEMA.md's Tag Taxonomy or remove it",
                ))
    return issues


def check_quality_signals(wiki: WikiContext) -> list[LintIssue]:
    issues: list[LintIssue] = []
    for page in wiki.pages:
        if not page.is_knowledge:
            continue
        # An errored page already carries its parse critical
        # (frontmatter_error_issues); judging its quality from fm={} would
        # re-shape error as absence for this one consumer (r2 Minor).
        if page.fm_state.startswith("error:"):
            continue
        fm = page.frontmatter
        if fm.get("contested"):
            issues.append(LintIssue(
                severity="info",
                category="contested",
                page=page.rel_path,
                message="Page marked contested",
                extra={"contradictions": fm.get("contradictions") or []},
            ))
        if fm.get("confidence") == "low":
            issues.append(LintIssue(
                severity="info",
                category="confidence-low",
                page=page.rel_path,
                message="Page marked confidence: low",
            ))
        sources = fm.get("sources") or []
        if len(sources) <= 1 and "confidence" not in fm:
            issues.append(LintIssue(
                severity="info",
                category="quality-uncorroborated",
                page=page.rel_path,
                message="Single-source page has no confidence field set",
                suggestion="Set confidence: medium or low, or add corroborating sources",
            ))
    return issues


def check_page_size(wiki: WikiContext) -> list[LintIssue]:
    return [
        LintIssue(
            severity="low",
            category="page-too-large",
            page=page.rel_path,
            message=f"Page is {page.line_count} lines (limit {PAGE_SIZE_LIMIT})",
            suggestion="Consider splitting into sub-topic pages with cross-links",
        )
        for page in wiki.pages
        if page.line_count > PAGE_SIZE_LIMIT
    ]


def check_log_rotation(wiki: WikiContext) -> list[LintIssue]:
    log = wiki.pages_by_path.get("log.md")
    if log is None:
        return []
    entries = sum(1 for ln in log.body.splitlines() if ln.startswith("## ["))
    if entries <= LOG_ROTATE_THRESHOLD:
        return []
    return [LintIssue(
        severity="low",
        category="log-rotation",
        page="log.md",
        message=f"log.md has {entries} entries (threshold {LOG_ROTATE_THRESHOLD})",
        suggestion=(f"Rotate to log-{datetime.now().year - 1}.md and start "
                    f"a fresh log.md"),
    )]


def check_documentation_gaps(wiki: WikiContext, since_days: int) -> list[LintIssue]:
    if wiki.no_git or wiki.git_root is None:
        return []
    repo_root = wiki.git_root
    touched = list_recently_touched_paths(repo_root, since_days)
    if touched is None:
        return [LintIssue(
            severity="high",
            category="git-history-failed",
            page="",
            message="Git could not enumerate recently touched paths for documentation-gap analysis",
            suggestion="Repair the git repository and rerun wiki-lint",
        )]
    if not touched:
        return []
    covered: set[str] = set()
    for page in wiki.pages:
        for pin in page.pins:
            covered.add(pin.path)
    try:
        wiki_rel = wiki.root.resolve().relative_to(repo_root.resolve())
        wiki_prefix = str(wiki_rel).replace("\\", "/").rstrip("/") + "/"
    except ValueError:
        wiki_prefix = None
    by_top: dict[str, set[str]] = defaultdict(set)
    for p in touched:
        if p in covered:
            continue
        if wiki_prefix and p.startswith(wiki_prefix):
            continue
        parts = Path(p).parts
        if any(seg in NON_SOURCE_DIRS for seg in parts):
            continue
        top = parts[0] if parts else p
        if top in wiki.gap_exclusions:
            continue
        by_top[top].add(p)
    issues: list[LintIssue] = []
    for top, paths in sorted(by_top.items()):
        if len(paths) < 3:
            continue
        issues.append(LintIssue(
            severity="medium",
            category="documentation-gap",
            page="",
            message=(f"{top}/: {len(paths)} files touched in last {since_days} days "
                     f"but no wiki page pins them"),
            suggestion="Investigate whether a wiki page should cover this area",
            extra={"sample_paths": sorted(paths)[:5], "count": len(paths)},
        ))
    return issues


# ─── reporting ───────────────────────────────────────────────────────────

SEVERITY_LABEL = {"critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM",
                  "low": "LOW", "info": "INFO"}

CATEGORY_PRIORITY = [
    "broken-wikilink",
    "invalid-pin-ref",
    "invalid-verified-ref",
    "git-history-failed",
    "page-unreadable",
    "frontmatter-yaml",
    "frontmatter-missing",
    "stale-l1-file-missing",
    "stale-l1-symbol-missing",
    "stale-l1-range-missing",
    "stale-l1-symbol-touched-high",
    "stale-l1-range-touched-high",
    "frontmatter-missing-field",
    "frontmatter-invalid-type",
    "meta-missing",
    "stale-l1-symbol-touched-medium",
    "stale-l1-range-touched-medium",
    "stale-l1-file",
    "orphan",
    "documentation-gap",
    "index-missing",
    "tag-not-in-taxonomy",
    "stale-l3-trust-decay",
    "frontmatter-invalid-confidence",
    "stale-l1-symbol-touched-low",
    "stale-l1-range-touched-low",
    "unpinned-sha",
    "malformed-pin",
    "page-too-large",
    "log-rotation",
    "contested",
    "confidence-low",
    "quality-uncorroborated",
    "stale-l1-shift",
    "stale-l1-rename",
]


def print_report(issues: list[LintIssue], wiki: WikiContext,
                 args: argparse.Namespace) -> None:
    cat_rank = {c: i for i, c in enumerate(CATEGORY_PRIORITY)}
    issues_sorted = sorted(issues, key=lambda x: (
        SEVERITY_RANK.get(x.severity, 99),
        cat_rank.get(x.category, 999),
        x.page,
        x.location,
    ))
    min_rank = SEVERITY_RANK.get(args.severity, len(SEVERITY_ORDER))
    visible = [i for i in issues_sorted
               if SEVERITY_RANK.get(i.severity, 99) <= min_rank]
    counts: dict[str, int] = defaultdict(int)
    for i in issues_sorted:
        counts[i.severity] += 1
    print(f"Wiki lint: {wiki.root}")
    print("=" * 60)
    parts = [f"{counts[s]} {s}" for s in SEVERITY_ORDER if counts[s]]
    print(f"Summary: {', '.join(parts) if parts else 'no issues'}")
    git_state = "enabled" if (not wiki.no_git and wiki.git_root) else "disabled"
    head = wiki.git_head[:7] if wiki.git_head else "n/a"
    print(f"Pages: {len(wiki.pages)} | Git: {git_state} (HEAD={head})")
    if wiki.gap_exclusions:
        print(f"Not covered: doc-gap analysis skips "
              f"{', '.join(sorted(wiki.gap_exclusions))} (SCHEMA.md exclusions)")
    print()
    if not visible:
        if issues_sorted:
            print(f"(no issues at severity ≥ {args.severity}; total {len(issues_sorted)} suppressed)")
        return
    by_cat: dict[str, list[LintIssue]] = defaultdict(list)
    for i in visible:
        by_cat[i.category].append(i)
    ordered_cats: list[str] = [c for c in CATEGORY_PRIORITY if c in by_cat]
    for c in sorted(by_cat):
        if c not in ordered_cats:
            ordered_cats.append(c)
    for cat in ordered_cats:
        items = by_cat[cat]
        if not items:
            continue
        sev = items[0].severity
        print(f"[{SEVERITY_LABEL[sev]}] {cat} ({len(items)})")
        for issue in items:
            head_label = issue.page or "(global)"
            loc = f"  ·  {issue.location}" if issue.location else ""
            print(f"  {head_label}{loc}")
            print(f"    {issue.message}")
            if issue.suggestion:
                print(f"    → {issue.suggestion}")
        print()


def write_page_text(abs_path: Path, text: str) -> None:
    """Write a page's text back byte for byte.

    Path.write_text() applies the platform's newline translation, so a pin-only
    update rewrote every LF in an LF page to CRLF on Windows -- whole-file churn
    on a one-line edit (3B audit 2026-09-02). newline="" disables translation;
    the terminators in `text` are the terminators on disk. Kept as a named
    function so the invariant has something to hold, and Path.write_text(newline=)
    is deliberately not used: it is 3.10+ and this harness runs on 3.9 too.
    """
    with open(abs_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def apply_pin_updates(issues: list[LintIssue], wiki: WikiContext) -> int:
    by_page: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for issue in issues:
        if issue.category not in ("stale-l1-shift", "stale-l1-rename"):
            continue
        new_pin = issue.extra.get("new_pin")
        if not new_pin or not issue.location:
            continue
        by_page[issue.page].append((issue.location, new_pin))
    modified = 0
    for rel_path, replacements in by_page.items():
        page = wiki.pages_by_path.get(rel_path)
        if not page:
            continue
        text = page.raw_text
        for old, new in replacements:
            updated = _replace_pin_in_frontmatter(text, old, new)
            if updated == text:
                sys.stderr.write(f"  WARN: could not write {old} → {new} in {rel_path}\n")
                continue
            text = updated
            sys.stderr.write(f"  UPDATED {rel_path}: {old} → {new}\n")
        if text != page.raw_text:
            write_page_text(page.abs_path, text)
            modified += 1
    return modified


def _replace_pin_in_frontmatter(text: str, old: str, new: str) -> str:
    if not (text.startswith("---\n") or text.startswith("---\r\n")):
        return text
    lines = text.splitlines(keepends=True)
    end_idx = _frontmatter_end(lines)
    if end_idx is None:
        return text
    out = list(lines)
    for i in range(1, end_idx):
        if old in out[i]:
            out[i] = out[i].replace(old, new, 1)
            return "".join(out)
    return text


# ─── CLI ─────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Automated lint for codebase-wiki directories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("wiki_path", nargs="?", default=None,
                   help="Path to wiki/ directory (auto-discovered if omitted)")
    p.add_argument("--json", action="store_true",
                   help="Output JSON instead of text")
    p.add_argument("--update-pins", action="store_true",
                   help="Write back silent line-shift pin updates")
    p.add_argument("--no-git", action="store_true",
                   help="Skip git-dependent checks (Layer 1, Layer 3, doc-gap)")
    p.add_argument("--since", default=f"{DOC_GAP_DEFAULT_DAYS}d",
                   help=f"Doc-gap window, e.g. 30d/8w/3m (default {DOC_GAP_DEFAULT_DAYS}d)")
    p.add_argument("--severity", choices=list(SEVERITY_ORDER), default="info",
                   help="Minimum severity to display (default: info)")
    p.add_argument("--check", default="all",
                   help=("Comma-separated subset of checks, or 'all'. "
                         "Available: broken-wikilinks, orphans, index, frontmatter, "
                         "tags, stale-l1, stale-l3, doc-gaps, "
                         "page-size, log-rotation, quality"))
    return p.parse_args(argv)


def parse_since(s: str) -> int:
    s = s.strip().lower()
    m = re.fullmatch(r"(\d+)\s*([dwm]?)", s)
    if not m:
        sys.stderr.write(f"WARN: bad --since {s!r}; using {DOC_GAP_DEFAULT_DAYS}d\n")
        return DOC_GAP_DEFAULT_DAYS
    n = int(m.group(1))
    unit = m.group(2) or "d"
    return n * {"d": 1, "w": 7, "m": 30}[unit]


ALL_CHECKS = {
    "broken-wikilinks", "orphans", "index", "frontmatter", "tags",
    "stale-l1", "stale-l3", "doc-gaps",
    "page-size", "log-rotation", "quality",
}

# Checks that read page.frontmatter or page.pins: each sees fm={} / pins=[] on
# a page whose parse ERRORED, so any of them being requested pulls in the
# frontmatter error criticals (frontmatter_error_issues). Same scoping rule as
# the doc-gap exclusion problems: findings follow the check that reads the data.
FM_DEPENDENT_CHECKS = {
    "frontmatter", "tags", "quality", "stale-l1", "stale-l3", "doc-gaps",
}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = parse_args(argv)

    if args.wiki_path:
        wiki_path = Path(args.wiki_path).resolve()
        if wiki_path.name != "wiki" and (wiki_path / "wiki" / "SCHEMA.md").exists():
            wiki_path = wiki_path / "wiki"
    else:
        discovered = discover_wiki(Path.cwd())
        if discovered is None:
            sys.stderr.write("ERROR: wiki/ not found (no path given and discovery from cwd failed)\n")
            return 2
        wiki_path = discovered

    if not (wiki_path / "SCHEMA.md").exists():
        sys.stderr.write(f"ERROR: {wiki_path}/SCHEMA.md not found; not a valid wiki\n")
        return 2

    pages = load_pages(wiki_path)
    pages_by_path = {p.rel_path: p for p in pages}
    pages_by_stem: dict[str, list[Page]] = defaultdict(list)
    for p in pages:
        pages_by_stem[Path(p.rel_path).stem].append(p)
    schema_tags = parse_schema_tags(wiki_path)
    gap_exclusions, gap_exclusion_problems = parse_schema_gap_exclusions(wiki_path)
    git_root = None if args.no_git else get_git_root(wiki_path)
    git_head = None if (args.no_git or git_root is None) else get_git_head(git_root)

    wiki = WikiContext(
        root=wiki_path,
        pages=pages,
        pages_by_path=pages_by_path,
        pages_by_stem=pages_by_stem,
        schema_tags=schema_tags,
        gap_exclusions=gap_exclusions,
        git_root=git_root,
        git_head=git_head,
        no_git=args.no_git or git_root is None,
    )
    build_inbound_links(wiki)

    if args.check == "all":
        requested = set(ALL_CHECKS)
    else:
        requested = {c.strip() for c in args.check.split(",") if c.strip()}
        unknown = requested - ALL_CHECKS
        if unknown:
            sys.stderr.write(f"ERROR: unknown checks: {sorted(unknown)}\n"
                             f"       known: {sorted(ALL_CHECKS)}\n")
            return 2

    issues: list[LintIssue] = []
    if requested & FM_DEPENDENT_CHECKS:
        issues.extend(frontmatter_error_issues(wiki))
    if "broken-wikilinks" in requested:
        issues.extend(check_broken_wikilinks(wiki))
    if "orphans" in requested:
        issues.extend(check_orphans(wiki))
    if "index" in requested:
        issues.extend(check_index_completeness(wiki))
    if "frontmatter" in requested:
        issues.extend(check_frontmatter(wiki))
    if "tags" in requested:
        issues.extend(check_tag_taxonomy(wiki))
    if "stale-l1" in requested:
        issues.extend(check_stale_layer1(wiki))
    if "stale-l3" in requested:
        issues.extend(check_stale_layer3(wiki))
    if "doc-gaps" in requested:
        # Scoped to the check it configures. Appended unconditionally, a malformed
        # exclusion made `--check broken-wikilinks` emit a schema-config issue and
        # exit 1, so a caller could not isolate a check. A malformed exclusion is
        # still REPORTED, never silently dropped -- an entry that disappears reads
        # exactly like one that was never written, and this field's whole job is to
        # remove things from coverage.
        for problem in gap_exclusion_problems:
            issues.append(LintIssue(
                severity="high",
                category="schema-config",
                page="SCHEMA.md",
                message=problem,
                suggestion="Fix the frontmatter entry; it is currently excluding nothing",
            ))
        issues.extend(check_documentation_gaps(wiki, parse_since(args.since)))
    if "page-size" in requested:
        issues.extend(check_page_size(wiki))
    if "log-rotation" in requested:
        issues.extend(check_log_rotation(wiki))
    if "quality" in requested:
        issues.extend(check_quality_signals(wiki))

    if args.json:
        if "doc-gaps" in requested and wiki.gap_exclusions:
            issues.append(LintIssue(
                severity="info",
                category="documentation-gap-exclusion",
                page="SCHEMA.md",
                message="Doc-gap analysis skipped declared top-level directories",
                extra={"excluded": sorted(wiki.gap_exclusions)},
            ))
        print(json.dumps([i.to_dict() for i in issues], indent=2, default=str))
    else:
        print_report(issues, wiki, args)

    if args.update_pins:
        n = apply_pin_updates(issues, wiki)
        sys.stderr.write(f"Updated {n} page(s) with silent shifts\n")

    has_critical_or_high = any(i.severity in ("critical", "high") for i in issues)
    return 1 if has_critical_or_high else 0


if __name__ == "__main__":
    sys.exit(main())
