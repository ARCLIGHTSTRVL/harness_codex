#!/usr/bin/env python3
"""wiki-pages-for: reverse-lookup wiki pages by the code they pin.

Given the code paths / symbols you are about to touch, report which wiki pages
document them (via their `sources:` pins) + the 1-hop [[link]] ripple
neighborhood (outgoing links AND backlinks = dependents). A blast-radius SCOPING
aid for refactors -- "if I change X, what does the wiki say is affected" -- not
just page retrieval.

FAIL-SAFE (per specs/freshness-detection-spine.md: under-scoping the blast
radius is the dangerous error). Every input ends in exactly ONE visible state:
  DOCUMENTED by <pages>   |   NOT DOCUMENTED (wiki is blind here -> grep the code)
Pages that could not be read / parsed are surfaced as WARNINGS, never silently
dropped (they may hold the only relevant pin). The map only covers what the wiki
documents, so the true blast radius can be larger -- cross-check undocumented
inputs against the actual code (callers / imports). This tool narrows where to
look; it is not a complete dependency oracle.

Read-only. Pin format (lines under `sources:` in page frontmatter; block list
or inline `[a, b]`):
  <code-path>:<symbol>@<sha>      or      <code-path>:<line-range>@<sha>
  (a bare <code-path>@<sha> file-level pin is also accepted)

Usage:
  python wiki-pages-for.py <wiki_dir> <path | path:symbol | path:line | symbol> [...]
Exit: always 0 (a scoping aid must not block); coverage holes are in the text.
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Meta/navigation pages: still parsed for pins (never skipped, per fail-safe), but
# excluded from the ripple -- linking to them is navigation, not a code dependency
# (index.md is a catalog that links everything, so it is never a real dependent).
META_SLUGS = {"SCHEMA", "index", "log", "AGENTS", "README"}

# Archived/meta trees are not live documentation: pruned from the walk entirely
# (mirrors wiki-lint's ARCHIVE_DIRS) so a pin that survives only in _archive/
# reports NOT DOCUMENTED rather than masking a real coverage hole.
SKIP_DIRS = {"_archive", "_meta"}


def norm(p):
    """POSIX-normalise a path/locator for matching. Strips surrounding quotes and
    a single leading './' only (NOT arbitrary dots -> '.github' is preserved)."""
    p = p.strip().strip('"').strip("'").replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p


def _split_pin(raw):
    """`scripts/x.py:Sym@sha` -> ('scripts/x.py','Sym',raw). None if empty."""
    raw = raw.strip().strip('"').strip("'")
    if not raw:
        return None
    body = raw.rsplit("@", 1)[0] if "@" in raw else raw   # drop @sha
    body = norm(body)
    # locator = text after the FIRST colon, but only if it is not a path tail
    # (guards Windows drive colons / paths: a locator never contains '/').
    if ":" in body:
        path, locator = body.split(":", 1)
        if "/" not in locator:
            return (norm(path), locator.strip(), raw)
    return (body, None, raw)


def parse_page(md_path):
    """(title, pins, links, warn). title is None ONLY when the file is unreadable
    (warn carries the reason). warn is also set for malformed frontmatter."""
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        return None, [], set(), "unreadable (%s)" % type(e).__name__
    lines = text.splitlines()
    title, pins, warn = os.path.basename(md_path), [], None
    if lines and lines[0].strip() == "---":
        i, in_sources, closed = 1, False, False
        while i < len(lines):
            ln = lines[i]
            s = ln.strip()
            if s == "---":
                closed = True
                break
            if s.startswith("title:"):
                title = s[len("title:"):].strip()
            if s.startswith("sources:"):
                rest = s[len("sources:"):].strip()
                if rest.startswith("["):                       # inline list
                    inner = rest[1:rest.rfind("]")] if "]" in rest else rest[1:]
                    for item in inner.split(","):
                        pin = _split_pin(item)
                        if pin:
                            pins.append(pin)
                    in_sources = False
                else:                                          # block list follows
                    in_sources = True
            elif in_sources:
                if s.startswith("- "):
                    pin = _split_pin(s[2:])
                    if pin:
                        pins.append(pin)
                elif s and not ln[:1].isspace():               # next top-level key
                    in_sources = False
            i += 1
        if not closed:
            warn = "frontmatter not closed by '---' (parse may be unreliable)"
    # body [[target]] links (target before any | alias or # anchor)
    links, idx = set(), 0
    while True:
        a = text.find("[[", idx)
        if a < 0:
            break
        b = text.find("]]", a + 2)
        if b < 0:
            break
        tgt = text[a + 2:b].split("|")[0].split("#")[0].strip()
        if tgt:
            links.add(tgt)
        idx = b + 2
    return title, pins, links, warn


def _path_match(a, b):
    """Component-boundary suffix match only -- 'a.py' must NOT match 'xa.py'."""
    a, b = norm(a), norm(b)
    return a == b or b.endswith("/" + a) or a.endswith("/" + b)


def _line_in_range(q, loc):
    if not q.isdigit():
        return False
    q = int(q)
    if "-" in loc:
        try:
            lo, hi = loc.split("-", 1)
            return int(lo) <= q <= int(hi)
        except ValueError:
            return False
    return loc.isdigit() and int(loc) == q


def matches(inp, code_path, locator):
    """Does input match this pin? Fail-safe: prefers over- to under-matching, but
    never across different files (component boundary)."""
    inp = norm(inp)
    if ":" in inp:
        ipath, isym = inp.split(":", 1)
        if "/" not in isym:                       # genuine path:symbol / path:line
            if not _path_match(ipath, code_path):
                return False
            if locator is None:                   # file-level pin documents the file
                return True
            return isym.strip() == locator or _line_in_range(isym.strip(), locator)
        # else: ':' was a drive colon / path -> fall through to path handling
    if "/" in inp or "." in os.path.basename(inp):
        return _path_match(inp, code_path)        # path form
    # bare token: try as a symbol AND as an extensionless filename (e.g. Makefile)
    return (locator is not None and inp == locator) or _path_match(inp, code_path)


def slug_of(rel):
    return rel.rsplit("/", 1)[-1][:-3]            # basename without .md


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip().splitlines()[0])
        print("usage: python wiki-pages-for.py <wiki_dir> <path|path:symbol|symbol> [...]")
        return 0
    wiki_dir, inputs = sys.argv[1], sys.argv[2:]
    if not os.path.isdir(wiki_dir):
        print("wiki-pages-for: not a directory: %s" % wiki_dir)
        return 0

    pages, link_graph, warnings, n = [], {}, [], 0
    for root, dirs, files in os.walk(wiki_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not fn.endswith(".md"):
                continue
            mp = os.path.join(root, fn)
            rel = os.path.relpath(mp, wiki_dir).replace("\\", "/")
            title, pins, links, warn = parse_page(mp)
            if title is None:
                warnings.append((rel, warn))      # unreadable -> surfaced, not skipped
                continue
            n += 1
            if warn:
                warnings.append((rel, warn))
            link_graph[slug_of(rel)] = links       # ALL pages (for backlinks)
            if pins:
                pages.append((rel, title, pins, links))

    wiki_label = "/".join(os.path.abspath(wiki_dir).replace("\\", "/").rstrip("/").split("/")[-2:])
    print("=== wiki-pages-for (blast-radius scoping; wiki: %s, %d pinned/%d pages) ==="
          % (wiki_label, len(pages), n))
    print("FAIL-SAFE: NOT-DOCUMENTED inputs are coverage holes -> grep the code; the wiki")
    print("map only covers what is documented (true blast radius may be larger).\n")

    if warnings:
        print("WARNINGS (pages not fully parsed -- may hide pins; check by hand):")
        for rel, w in warnings:
            print("  ! %s -- %s" % (rel, w))
        print("")

    documented = {}     # rel -> links
    holes = 0
    for inp in inputs:
        hits = []
        for rel, title, pins, links in pages:
            matched = [p for p in pins if matches(inp, p[0], p[1])]
            if matched:
                hits.append((rel, title, matched))
                documented[rel] = links
        print("INPUT %s" % inp)
        if hits:
            print("  DOCUMENTED by:")
            for rel, title, matched in hits:
                tag = ", ".join(sorted({m[1] or "(file)" for m in matched}))
                print("    - %s  (%s)  [pin %s]" % (title, rel, tag))
        else:
            holes += 1
            print("  NOT DOCUMENTED -- wiki blind here; grep the code for callers/imports (fail-safe).")
        print("")

    # 1-hop ripple = outgoing links of documented pages UNION backlinks (dependents)
    doc_slugs = {slug_of(rel) for rel in documented}
    ripple = set()
    for _rel, links in documented.items():
        ripple |= links
    for slug, links in link_graph.items():
        if slug not in doc_slugs and (links & doc_slugs):
            ripple.add(slug)                      # backlink = page that depends on a doc page
    ripple -= doc_slugs | META_SLUGS
    if ripple:
        print("RIPPLE (1-hop neighborhood -- outgoing links + backlinks/dependents -- also check):")
        print("  " + " ".join("[[%s]]" % t for t in sorted(ripple)))
        print("")

    print("COVERAGE: %d/%d inputs documented; %d hole(s)%s.%s"
          % (len(inputs) - holes, len(inputs), holes,
             " -> grep those in code" if holes else "",
             "  (%d parse warning(s) above)" % len(warnings) if warnings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
