#!/usr/bin/env python3
"""knowledge-mirror status: detect stale / missing / orphan / duplicate KR mirrors
of an in-repo knowledge/ layer.

Read-only. Translation is NEVER automated (per <knowledge_fidelity> the KR mirror
is hand-crafted natural Korean, not a bulk translation). This script only answers
"which mirrors need a human pass" by content-hashing the EN authoritative source
against the sha recorded in each KR mirror's frontmatter.

Usage:
    python knowledge-mirror-status.py <en_knowledge_dir> <en_base_dir> <kr_mirror_dir>

  en_knowledge_dir  in-repo EN knowledge/ dir (authoritative), e.g. C:/dev/project_hibiki/knowledge
  en_base_dir       base that KR `en_source:` paths are relative to, e.g. C:/dev
  kr_mirror_dir     vault KR mirror dir, e.g. C:/archive/Obsidian/DEV/hibiki/knowledge

KR mirror frontmatter contract:
  en_source:     <path relative to en_base_dir>          (required to be a mirror)
  en_source_sha: sha256:<64 hex of EN file bytes at mirror time>   (added by this convention)

States:
  FRESH    KR mirror exists and its en_source_sha matches the EN file now
  STALE    KR mirror exists but sha differs / missing / malformed; needs a hand pass
  MISSING  EN content page has no KR mirror
  ORPHAN   KR mirror points to an EN page that no longer exists
  DUP      two KR mirrors claim the same EN page
  IGNORED  EN page deliberately not mirrored (listed in <kr_dir>/_mirror-ignore.txt) -- no action
  IGNORE-STALE  an _mirror-ignore.txt entry matches no EN page (dangling exclusion -- clean it up)
  IGNORE-INVALID  an _mirror-ignore.txt line is not a usable en_source path (absolute,
                  drive-lettered or escaping via ..) -- it excludes nothing and is listed

Exclusion: a vault-side `<kr_mirror_dir>/_mirror-ignore.txt` lists en_source paths NOT to
mirror (one per line, optional `# reason`). Vault-side so it works even when the EN source
is read-only. Exclusions are always listed (IGNORED) so an accidental/stale one is auditable
-- never a silent suppression.
"""
import sys
import os
import re
import hashlib

try:
    sys.stdout.reconfigure(encoding="utf-8")  # avoid cp949 console crashes on Windows
except Exception:
    pass

# Root-level EN files that are structural, not content to mirror (matched at en_dir root only).
ROOT_SKIP = {"index.md", "log.md", "schema.md"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_frontmatter(path):
    """Return {key: value} from a leading --- ... --- block, requiring a close. Else {}."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out = {}
    closed = False
    for line in lines[1:]:
        if line.strip() == "---":
            closed = True
            break
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out if closed else {}


def normalize_src(src):
    """Normalize a hand-stamped en_source: backslashes -> /, strip ./, return None if unsafe."""
    s = src.strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    if not s or s.startswith("/") or ".." in s.split("/") or re.match(r"^[A-Za-z]:", s):
        return None
    return s


def parse_sha(raw):
    """Return ('ok', hex) | ('bad', None) | ('none', None) from an en_source_sha value."""
    if not raw:
        return ("none", None)
    v = raw.strip().lower()
    if v.startswith("sha256:"):
        v = v[7:].strip()
    return ("ok", v) if HEX64.match(v) else ("bad", None)


def rel_key(path, base):
    return os.path.relpath(path, base).replace(os.sep, "/")


def is_content(rel):
    """rel is forward-slash relpath from en_dir; skip root structural + any path with a
    _-prefixed segment (file or dir: _fragments/, _fragments/_archive/, _consolidations/)."""
    parts = rel.split("/")
    if any(p.startswith("_") for p in parts) or not parts[-1].lower().endswith(".md"):
        return False
    if "/" not in rel and parts[-1].lower() in ROOT_SKIP:  # structural only at root
        return False
    return True


def load_ignore(kr_dir):
    """Read <kr_dir>/_mirror-ignore.txt -> ({normalized en_source: reason}, [unusable raw line]).

    The second element exists because dropping an unusable line was a SILENT
    suppression of a suppression: the file promised the exclusion, the tool
    excluded nothing, and no row said so (3B audit, 2026-09-02).
    Lines: `en_source` or `en_source  # reason`; blank / #-comment lines skipped."""
    out, bad = {}, []
    try:
        with open(os.path.join(kr_dir, "_mirror-ignore.txt"), "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "#" in line:
                    src, reason = line.split("#", 1)
                    src, reason = src.strip(), reason.strip()
                else:
                    src, reason = line, ""
                norm = normalize_src(src)
                if norm:
                    out[norm] = reason
                else:
                    bad.append(src or line)
    except OSError:
        pass
    return out, bad


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    en_dir, en_base, kr_dir = (os.path.abspath(p) for p in sys.argv[1:4])
    for label, d in (("en_knowledge_dir", en_dir), ("kr_mirror_dir", kr_dir)):
        if not os.path.isdir(d):
            print("ERROR: %s not a directory: %s" % (label, d))
            return 2

    # Index KR mirrors by the (normalized) EN page they claim. Keep all claimants -> DUP.
    mirrors = {}  # norm_src -> list of (kr_relpath, sha_state, sha_hex)
    for root, _, files in os.walk(kr_dir):
        for name in files:
            if not name.lower().endswith(".md"):
                continue
            fm = parse_frontmatter(os.path.join(root, name))
            src = fm.get("en_source")
            if not src:
                continue
            norm = normalize_src(src)
            kr_rel = rel_key(os.path.join(root, name), kr_dir)
            state, sha = parse_sha(fm.get("en_source_sha", ""))
            if norm is None:
                mirrors.setdefault("?" + src, []).append((kr_rel, "unsafe", None))
            else:
                mirrors.setdefault(norm, []).append((kr_rel, state, sha))

    rows = []  # (state, key, detail)

    # KR mirrors -> ORPHAN / STALE / FRESH (+ DUP). Visible regardless of EN skip rules.
    for norm, claimants in mirrors.items():
        if len(claimants) > 1:
            rows.append(("DUP", norm, "%d KR mirrors claim this: %s"
                         % (len(claimants), ", ".join(c[0] for c in claimants))))
        kr_rel, sha_state, sha = claimants[0]
        if norm.startswith("?"):
            rows.append(("STALE", norm[1:], "unsafe en_source path in %s" % kr_rel))
            continue
        en_path = os.path.join(en_base, norm.replace("/", os.sep))
        if not os.path.exists(en_path):
            rows.append(("ORPHAN", norm, "KR mirror %s; EN gone" % kr_rel))
            continue
        cur = sha256_file(en_path)
        if sha_state == "none":
            rows.append(("STALE", norm, "no en_source_sha recorded; cur=sha256:%s" % cur))
        elif sha_state == "bad":
            rows.append(("STALE", norm, "malformed en_source_sha; cur=sha256:%s" % cur))
        elif sha != cur:
            rows.append(("STALE", norm, "EN changed since mirror; cur=sha256:%s" % cur))
        else:
            rows.append(("FRESH", norm, "up to date"))

    # EN content pages with no KR mirror -> MISSING, unless deliberately excluded -> IGNORED.
    # raw/ holds pinned sources, not curated reading content -> no mirror required.
    ignore, unusable_ignore = load_ignore(kr_dir)   # normalized en_source -> reason
    used_ignore = set()
    raw_skipped = 0
    for root, _, files in os.walk(en_dir):
        for name in files:
            en_path = os.path.join(root, name)
            rel = rel_key(en_path, en_dir)
            if rel.startswith("raw/"):
                raw_skipped += 1
                continue
            if not is_content(rel):
                continue
            key = rel_key(en_path, en_base)
            if key in mirrors:
                continue
            if key in ignore:
                used_ignore.add(key)
                rows.append(("IGNORED", key, "excluded: " + (ignore[key] or "no reason given")))
            else:
                rows.append(("MISSING", key, "no KR mirror; cur=sha256:%s" % sha256_file(en_path)))

    # ignore entries that matched no EN page -> dangling exclusion (auditable; clean it up).
    for key in ignore:
        if key not in used_ignore:
            rows.append(("IGNORE-STALE", key, "_mirror-ignore.txt entry matches no EN content page"))

    # Lines the ignore file offered that are not usable en_source paths. They excluded
    # nothing; printing them is the whole point of "never a silent suppression".
    for raw in unusable_ignore:
        rows.append(("IGNORE-INVALID", raw,
                     "not a usable en_source path (absolute, drive-lettered, or escaping via ..)"))

    order = {"MISSING": 0, "STALE": 1, "ORPHAN": 2, "DUP": 3, "IGNORE-INVALID": 4,
             "IGNORE-STALE": 5, "IGNORED": 6, "FRESH": 7}
    rows.sort(key=lambda r: (order.get(r[0], 9), r[1]))

    counts = {}
    for state, _, _ in rows:
        counts[state] = counts.get(state, 0) + 1

    print("knowledge-mirror status")
    print("  EN : %s" % en_dir)
    print("  KR : %s" % kr_dir)
    print("")
    width = max((len(r[1]) for r in rows), default=10)
    for state, key, detail in rows:
        print("  %-12s  %-*s  %s" % (state, width, key, detail))
    print("")
    summary = "  ".join("%s=%d" % (s, counts.get(s, 0))
                        for s in ("MISSING", "STALE", "ORPHAN", "DUP", "IGNORE-INVALID",
                                  "IGNORE-STALE", "IGNORED", "FRESH"))
    if raw_skipped:
        print("note: skipped %d file(s) under raw/ (pinned sources, not mirror content)" % raw_skipped)
    print("summary: " + summary)
    # IGNORED is deliberate (no action); everything else uncertain/wrong needs a pass.
    needs_pass = any(counts.get(s) for s in ("MISSING", "STALE", "ORPHAN", "DUP",
                                             "IGNORE-INVALID", "IGNORE-STALE"))
    return 1 if needs_pass else 0


if __name__ == "__main__":
    sys.exit(main())
