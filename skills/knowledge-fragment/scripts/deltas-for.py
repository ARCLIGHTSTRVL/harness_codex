#!/usr/bin/env python3
"""deltas-for: gather knowledge-fragment deltas by unit_id across session fragments.

The READ side of the knowledge-fragment staging tier
(spec: dev-setup-codex/specs/knowledge-fragment.md). Deltas are captured per
session into knowledge/_fragments/<session_id>.md as fenced-YAML records; this
gathers them by unit_id (resolving units.yml aliases) for consolidation or for the
acceptance-test problem query.

On-demand only -- NOT a persistent index (a persisted index is just another stale
source; mirrors wiki-pages-for). Read-only -- every fragment/curated WRITE lives in
consolidate.py (the draft/apply side); _drafts/ is never scanned for deltas. FAIL-SAFE:
malformed delta blocks are WARNED, never silently dropped (a dropped delta = lost
knowledge).

Delta record grammar (locked, spec §6 lock #4):
  '## delta: <delta_id>' at column 0
  immediately followed by a ```yaml fenced block (the metadata)
  body runs until the next column-0 '## delta:' OUTSIDE balanced code fences.

Default listing and --capture-brief SKIP TERMINALLY DISPOSED deltas; a one-line
stderr note reports how many were skipped. A disposition is terminal when the
delta will never be promoted again:
  consolidated -- promoted into a curated page (spec §6)
  archived     -- reviewed and deliberately NOT page-worthy, kept raw for the record
  superseded   -- revised by a later delta, so promoting it would publish stale content
Capture is cheap and high-recall BY DESIGN, so some captured material is not
page-worthy. Counting those as debt forever would mean the counter can only reach
zero if every scrap becomes curated prose -- which contradicts the tier's own
design and trains the reader to ignore the alarm. Debt = deltas with no terminal
disposition yet (provisional | accepted).

Provenance instruments (additive fields, 2026-06-10, spec §6): optional `informed_by:`
on a delta = the unit's orientation set (what it was worked WITH); optional `parent:`
on a units.yml entry = the containing feature/unit. Both surface as wikilink candidates
(--capture-brief and consolidate --draft) -- ground truth recorded at knowing-time,
because link-reconstruction failure at consolidation is silent.

Usage:
  python deltas-for.py <knowledge|_fragments dir> <unit_id>
                       [--kind=k1,k2 | --kind k1,k2] [--capture-brief] [--include-archive]
  python deltas-for.py <knowledge|_fragments dir> --debt
Exit: 0 (a query aid must not block; problems are in the text);
      2 on an unrecognized/invalid argument.
"""
import hashlib
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

REQUIRED = ("delta_id", "created_at", "unit_id", "kind", "status", "summary")
# A delta is DISPOSED when it will never be promoted again. Everything else is
# outstanding debt. Ask "is this whole file disposed?" through all_disposed() below --
# never by respelling the predicate at the call site.
DISPOSED = ("consolidated", "archived", "superseded")
KINDS = {"decision", "finding", "rejection", "risk",
         "open_question", "constraint", "followup"}
# The kinds spec §8 points at when asking what is still open, as opposed to what was
# settled (`decision`/`finding`). Kept identical to the §8 query
# (`--kind risk,open_question,followup`) so the two agree on the FIELD they select.
# Agreeing on the field is NOT equivalence of measurement, and no description here may
# imply it: §8's bar is what a cold reader can name from the BODIES, and no count of
# kinds can see that.
PROBLEM_KINDS = ("risk", "open_question", "followup")
# Marker carried by warnings that mean "this file may still hold delta records this
# parse did NOT return". Those are categorically different from field-level warnings
# (missing kind, unknown status): a field warning describes a record you have, this
# one says a record is missing. Callers that DISPOSE of a file -- archiving it, moving
# it out of the active set -- must fail closed on it, because a warning nobody consumes
# loses the delta just as silently as no warning at all.
RECORD_LOSS = "[RECORD-LOSS]"


def hides_records(warnings):
    """The subset of `warnings` meaning the file may hold unparsed delta records."""
    return [w for w in warnings or () if RECORD_LOSS in w]


def fragment_damage(path):
    """RECORD-LOSS-class reasons why `path` may HIDE delta records from this
    parser: the [RECORD-LOSS] warnings plus an unreadable file (unreadable
    hides everything). Empty list = every record the file holds is visible to
    parse_fragment -- the file may still be WRONG (bad statuses, bad ids), but
    it is not HIDING, and hiding is the property absence proofs need. The
    parse warnings are the one selector the corruption cannot hide, because
    the corruption is what produces them (delta 081: filename, envelope and
    parsed ids were each hideable; three review rounds died on that)."""
    _env, _deltas, warns = parse_fragment(path)
    return [w for w in warns if RECORD_LOSS in w or ": unreadable" in w]


QUARANTINE_NAME = "quarantine.json"


def quarantine_key(rel, nt=None):
    """Canonical registry key for a path relative to _fragments. Backslash is
    a SEPARATOR only on Windows; on POSIX it is a legal filename byte, and
    normalizing it there made such a file permanently unacknowledgeable
    (round-1 Major). One function for BOTH the registry side and the on-disk
    side -- two spellings of one key is this repo's recorded defect family."""
    nt = (os.name == "nt") if nt is None else nt
    return rel.replace("\\", "/") if nt else rel


def load_quarantine(frag_dir):
    """(entries, errors) from `_fragments/quarantine.json` -- the human
    acknowledgment registry for DAMAGED fragment files. Entry shape:
    {path, sha256, reason, date}; `path` relative to the _fragments dir with
    forward slashes; `sha256` over the file's exact current bytes. An entry
    states a human inspected the named damage and accepts that ids inside the
    file sit OUTSIDE every absence proof -- consumers then proceed and REPORT
    the standing quarantine instead of refusing. Absent registry = no entries
    (the normal, zero-friction state). A malformed registry is a hard error,
    mirroring the secrets gate: a tool that silently ignores its exception
    file either blocks known-good runs or invites weakening the checks."""
    path = os.path.join(frag_dir, QUARANTINE_NAME)
    if not os.path.exists(path):
        return {}, []
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        return None, ["quarantine registry unreadable: %s" % type(e).__name__]
    if not isinstance(raw, list):
        return None, ["quarantine registry must be a JSON list"]
    entries, errors = {}, []
    for i, item in enumerate(raw):
        label = "quarantine entry %d" % i
        if not isinstance(item, dict) or set(item) != {
                "path", "sha256", "reason", "date"}:
            errors.append(label + ": exactly path/sha256/reason/date required")
            continue
        if not all(isinstance(item[k], str) and item[k] for k in item):
            errors.append(label + ": all fields must be non-empty strings")
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            errors.append(label + ": sha256 must be 64 lowercase hex chars")
            continue
        key = quarantine_key(item["path"])
        if key in entries:
            errors.append(label + ": duplicate path %s" % key)
            continue
        entries[key] = item
    return (None, errors) if errors else (entries, [])


def archive_md(frag_dir):
    """(paths, errors): every .md under `_fragments/_archive/`, RECURSIVELY,
    sorted -- plus the traversal errors os.walk SWALLOWS by default (round-3
    Critical: its default onerror ignores scandir failures, so an unreadable
    subtree read as an EMPTY archive and absence proofs ran over an
    incomplete listing). Flat enumerations coexisting with recursive ones was
    round 2's Critical; no flat-only layout is enforced anywhere, so none may
    be assumed. One enumerator, every consumer: callers whose claims need
    absence REFUSE on errors, reporting callers PRINT them."""
    arch = os.path.join(frag_dir, "_archive")
    out, errors = [], []

    def _err(exc):
        errors.append("archive traversal failed: %s (%s)"
                      % (getattr(exc, "filename", None) or arch,
                         type(exc).__name__))

    if os.path.isdir(arch):
        for walk_root, _dirs, files in os.walk(arch, onerror=_err):
            out += [os.path.join(walk_root, f) for f in files
                    if f.endswith(".md")]
    return sorted(out), errors


def snapshot_scan(path, frag_dir, entries):
    """(env, deltas, verdict, line) for ONE file, over ONE byte snapshot: the
    hash that validates an acknowledgment and the parse the caller acts on see
    the SAME bytes. Round 2 of the archive-trust review reproduced the split
    version deterministically -- parse read damaged bytes A, the hash read
    acknowledged bytes B, and a stale acknowledgment stood. verdict: None
    (clean) | 'standing' (acknowledged, `line` must be PRINTED) | 'blocking'
    (`line` names the file, the damage and the acknowledgment recipe). The
    sha binding is the point: an acknowledgment covers ONE byte state, so a
    file that changes after inspection goes straight back to refusing."""
    snap, snap_err = None, None
    try:
        with open(path, "rb") as f:
            snap = f.read()
    except OSError as exc:
        snap_err = type(exc).__name__
    if snap is None:
        env, deltas, warns = {}, [], [
            "%s: unreadable (%s)" % (os.path.basename(path), snap_err)]
    else:
        env, deltas, warns = parse_fragment(path, data=snap)
    damage = [w for w in warns if RECORD_LOSS in w or ": unreadable" in w]
    if not damage:
        return env, deltas, None, None
    rel = quarantine_key(os.path.relpath(path, frag_dir))
    entry = (entries or {}).get(rel)
    digest = hashlib.sha256(snap).hexdigest() if snap is not None else None
    if entry and digest == entry["sha256"]:
        return env, deltas, "standing", ("QUARANTINE (acknowledged; ids inside "
                                         "are outside absence proofs): %s" % rel)
    changed = (" [registry entry exists but the file CHANGED since]"
               if entry else "")
    return env, deltas, "blocking", (
        "DAMAGED%s: %s -- %s -- inspect the file, then acknowledge it in "
        "_fragments/%s ({path, sha256, reason, date})"
        % (changed, rel, "; ".join(damage), QUARANTINE_NAME))


def damage_report(frag_dir, paths):
    """(blocking, standing) over fragment files, each read as ONE snapshot.
    `blocking` = damaged and NOT acknowledged -- callers whose claims need
    absence proofs refuse on these. `standing` = acknowledged quarantines,
    which every consumer must PRINT: a quarantine nobody reports is the
    silent gap again, wearing a registry."""
    entries, errors = load_quarantine(frag_dir)
    if entries is None:
        return ["quarantine registry invalid: " + "; ".join(errors)], []
    blocking, standing = [], []
    for path in paths:
        _env, _deltas, verdict, line = snapshot_scan(path, frag_dir, entries)
        if verdict == "standing":
            standing.append(line)
        elif verdict == "blocking":
            blocking.append(line)
    return blocking, standing


HEADER = re.compile(r"^## delta:\s*(.+?)\s*$")
FENCE = re.compile(r"^(```|~~~)")
USAGE = ("usage: python deltas-for.py <knowledge|_fragments dir> <unit_id> "
         "[--kind=k1,k2] [--capture-brief] [--include-archive]\n"
         "       python deltas-for.py <knowledge|_fragments dir> --debt\n"
         "       python deltas-for.py <knowledge|_fragments dir> --next-id <session_id>")
VALUE_FLAGS = ("--kind", "--next-id")                        # take a value (= or space form)
BOOL_FLAGS = ("--capture-brief", "--include-archive", "--debt")


def all_disposed(deltas, pending=()):
    """True iff every delta in a fragment file is terminally DISPOSED -- i.e. the file
    is archivable. Ids in `pending` count as about-to-be-consolidated, which is what a
    caller asking the question BEFORE its own status flips needs.

    One spelling, imported rather than restated. consolidate.py's archive PREFLIGHT
    asked `status == "consolidated"` while its archive STEP asked `status in DISPOSED`,
    so a fragment holding a single `superseded` delta skipped the preflight and refused
    only AFTER the page write and the status flips -- falsifying that module's
    documented "a refusal mutates NOTHING". Two sites answering one question with two
    definitions of disposed is this tool's recorded defect family; this is its fix.
    """
    pending = set(pending)
    return bool(deltas) and all(
        d.get("status") in DISPOSED
        or (d.get("delta_id") or d.get("_header_id")) in pending
        for d in deltas)


def find_fragments(start):
    """Locate _fragments/ from a knowledge dir, a repo dir, or _fragments itself."""
    start = os.path.abspath(start)
    if os.path.basename(start) == "_fragments":
        return start
    for cand in (os.path.join(start, "_fragments"),
                 os.path.join(start, "knowledge", "_fragments")):
        if os.path.isdir(cand):
            return cand
    return None


def load_units(frag_dir):
    """alias -> canonical map from units.yml (hand-parsed; absent => identity-only)."""
    path = os.path.join(frag_dir, "units.yml")
    alias2canon, canon, aliases = {}, None, []

    def flush():
        if canon:
            alias2canon[canon] = canon
            for a in aliases:
                alias2canon[a] = canon

    if not os.path.exists(path):
        return alias2canon
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                m = re.match(r"\s*-\s*canonical_id:\s*(\S+)", ln)
                if m:
                    flush()
                    canon = m.group(1).strip().strip('"\'')
                    aliases = []
                    continue
                m = re.match(r"\s*aliases:\s*\[(.*)\]", ln)
                if m and canon:
                    aliases = [a.strip().strip('"\'')
                               for a in m.group(1).split(",") if a.strip()]
        flush()
    except OSError:
        pass
    return alias2canon


def unit_parents(frag_dir):
    """canon -> parent from optional `parent:` lines in units.yml (additive, spec §6).
    A parent is the containing feature/unit, recorded at registration time while the
    hierarchy is still known; it seeds wikilink candidates and is never traversed."""
    path = os.path.join(frag_dir, "units.yml")
    parents, canon = {}, None
    if not os.path.exists(path):
        return parents
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                m = re.match(r"\s*-\s*canonical_id:\s*(\S+)", ln)
                if m:
                    canon = m.group(1).strip().strip('"\'')
                    continue
                m = re.match(r"\s*parent:\s*(\S+)", ln)
                if m and canon:
                    parents[canon] = m.group(1).strip().strip('"\'')
    except OSError:
        pass
    return parents


def parse_meta(yaml_lines):
    """Hand-parse the fenced metadata block: scalars, [inline] lists, block lists."""
    meta, key = {}, None
    for ln in yaml_lines:
        if re.match(r"^\s+-\s", ln) and key:                 # block-list item
            if isinstance(meta.get(key), list):
                meta[key].append(ln.strip()[1:].strip())
            continue
        m = re.match(r"^(\w+):\s*(.*)$", ln)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val == "":
            meta[key] = []                                   # block list follows
        elif val.startswith("[") and val.endswith("]"):
            meta[key] = [x.strip() for x in val[1:-1].split(",") if x.strip()]
        else:
            if not val.startswith(("'", '"')):           # strip trailing YAML comment (unquoted scalar)
                val = re.sub(r"\s+#.*$", "", val).rstrip()
            meta[key] = val.strip('"\'')
    return meta


def parse_fragment(path, data=None):
    """(envelope, [delta], [warning]). Fail-safe: unreadable => warning, never raise.
    `data` (bytes) parses that snapshot instead of reading `path` -- a caller
    binding a hash and a parse to ONE byte state passes the bytes it hashed
    (the next-id check/use race fix); `path` then only names the file in
    warnings."""
    fn = os.path.basename(path)
    try:
        if data is None:
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
        else:
            lines = data.decode("utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        return {}, [], ["%s: unreadable (%s)" % (fn, type(e).__name__)]

    warns, env, i, n = [], {}, 0, len(lines)
    if lines and lines[0].strip() == "---":                  # envelope frontmatter
        i = 1
        while i < n and lines[i].strip() != "---":
            if ":" in lines[i]:
                k, v = lines[i].split(":", 1)
                env[k.strip()] = v.strip()
            i += 1
        if i >= n:
            # Unterminated envelope: the scan ran to EOF, so EVERY delta in the file
            # was read as frontmatter and the function returned zero records with zero
            # warnings -- silent loss, in the module whose contract is that a dropped
            # delta is lost knowledge. Recover by treating the file as having no
            # envelope, so the delta scan still sees the records, and warn loudly.
            warns.append(RECORD_LOSS + " %s: envelope frontmatter is UNTERMINATED (no closing '---'); "
                         "parsing the whole file for deltas and ignoring the envelope "
                         "-- session_id/schema are unavailable, fix the file" % fn)
            env, i = {}, 0
        else:
            i += 1

    deltas, seen_ids = [], set()
    while i < n:
        h = HEADER.match(lines[i])
        if not h:
            i += 1
            continue
        header_id = h.group(1).strip()
        i += 1
        while i < n and lines[i].strip() == "":              # skip blanks before fence
            i += 1
        meta = {}
        if i < n and FENCE.match(lines[i].strip()):
            i += 1
            yl = []
            while i < n and not FENCE.match(lines[i].strip()):
                yl.append(lines[i])
                i += 1
            if i >= n:
                # The METADATA fence never closed: the scan just consumed to
                # EOF, so every later '## delta:' header sits in `yl` as YAML
                # -- absorbed records, the body-fence case's twin, and
                # previously with NO warning at all. The damage classifier
                # keys on warnings, so this shape passed every gate and
                # next-id minted an id the file already holds (round-1
                # Critical of the archive-trust unit).
                eaten = [HEADER.match(y).group(1).strip() for y in yl
                         if HEADER.match(y)]
                warns.append(RECORD_LOSS + " %s: delta '%s' has an UNTERMINATED metadata "
                             "fence; the scan ran to EOF%s" %
                             (fn, header_id,
                              " and ABSORBED %d later delta(s): %s" %
                              (len(eaten), ", ".join(eaten))
                              if eaten else " (no later delta was absorbed)"))
            i += 1                                            # past closing fence
            meta = parse_meta(yl)
            if any(re.match(r"^evidence:\s*\[.*\{", y) for y in yl):  # inline-list evidence drift
                warns.append("%s: delta '%s' inline-list evidence (use block-list '- {type:...}')"
                             % (fn, header_id))
        else:
            warns.append("%s: delta '%s' has no ```yaml block" % (fn, header_id))

        body, depth = [], 0
        while i < n:
            ln = lines[i]
            if FENCE.match(ln):                               # col-0 fence toggles depth
                depth ^= 1
            if depth == 0 and HEADER.match(ln):
                break
            body.append(ln)
            i += 1
        # An odd number of col-0 fences in a body leaves depth stuck at 1, so every
        # later '## delta:' is read as prose and ABSORBED -- previously with no warning
        # at all. Worse than losing them: the file then parses as fully disposed and
        # consolidate.py archives it, taking the unpromoted records with it. Report the
        # ids that were swallowed rather than only the fence, because those ids are the
        # knowledge at risk. Detection only -- the file must be repaired by hand.
        if depth and i >= n:
            eaten = [HEADER.match(b).group(1).strip() for b in body if HEADER.match(b)]
            warns.append(RECORD_LOSS + " %s: delta '%s' has an UNBALANCED col-0 code fence in its body; "
                         "the scan never closed it%s" %
                         (fn, header_id,
                          " and ABSORBED %d later delta(s): %s" % (len(eaten), ", ".join(eaten))
                          if eaten else " (no later delta was absorbed)"))

        reserved = sorted(k for k in meta if k.startswith("_"))   # leading-_ keys are parser-internal
        if reserved:
            warns.append("%s: delta '%s' uses reserved key(s) %s (leading '_' is parser-internal)"
                         % (fn, header_id, ",".join(reserved)))
        meta["_header_id"], meta["_body"], meta["_file"] = header_id, "\n".join(body).strip(), fn
        did_raw = meta.get("delta_id")
        if "delta_id" in meta and not (isinstance(did_raw, str) and did_raw):
            # A present-but-empty or non-scalar delta_id (quoted-empty, bare
            # `delta_id:`, a block list) cannot NAME the record -- it matches
            # no manifest id, and as a list it is unhashable: `did in seen_ids`
            # below raised TypeError, one screen under the docstring promising
            # "never raise". Identity falls back to the header; the CLAIM
            # survives as a parser-internal marker plus a warning, because the
            # writer-side coherence question -- did the author claim an
            # identity that is not the header? -- must stay answerable, and a
            # silently-dropped key would read as "absent, coherent".
            del meta["delta_id"]
            meta["_malformed_delta_id"] = True
            warns.append("%s: delta '%s' has an empty/non-scalar delta_id; "
                         "identity falls back to the header" % (fn, header_id))
        missing = [k for k in REQUIRED if not meta.get(k)]
        if missing:
            warns.append("%s: delta '%s' missing %s" % (fn, header_id, ",".join(missing)))
        # spec §9.4: provenance is REQUIRED for `accepted` -- a delta with no human
        # statement, command output, source or code pointer cannot be accepted and
        # stays `provisional`. That is the direct guard on the "agent persists a guess
        # as fact" drift loop, and it was stated in the spec and in SKILL.md while no
        # code ever checked it. Warned, not blocked: the rule is the author's to apply,
        # and refusing to parse an existing delta would drop the record this module
        # exists to preserve.
        if meta.get("status") == "accepted" and not (meta.get("evidence") or []):
            warns.append("%s: delta '%s' is `accepted` with no evidence -- spec 9.4 says "
                         "provenance is required to accept; use `provisional` or add "
                         "evidence" % (fn, header_id))
        if meta.get("delta_id") and meta["delta_id"] != header_id:
            warns.append("%s: header '%s' != delta_id '%s'" % (fn, header_id, meta["delta_id"]))
        if meta.get("kind") and meta["kind"] not in KINDS:
            warns.append("%s: delta '%s' unknown kind '%s'" % (fn, header_id, meta["kind"]))
        did = meta.get("delta_id") or header_id
        if did in seen_ids:
            warns.append("%s: duplicate delta_id '%s' within file" % (fn, did))
        seen_ids.add(did)
        deltas.append(meta)
    return env, deltas, warns


def code_refs(meta):
    """Extract `ref` of `{type: code, ref: ...}` evidence items (for the wiki signal)."""
    out = []
    for item in meta.get("evidence", []) or []:
        m = re.search(r"type:\s*code\b.*?ref:\s*([^,}]+)", item)
        if m:
            out.append(m.group(1).strip().strip('"\'}'))
    return out


def informed_refs(meta):
    """`informed_by` as a list -- the optional orientation-set field (spec §6):
    free-form refs (KB page stem preferred, repo path ok). A wikilink seed at
    consolidation, never a foreign key (pages move; the hint stays)."""
    v = meta.get("informed_by")
    if not v:
        return []
    return [v] if isinstance(v, str) else [x for x in v if x]


def warn_envelope(env, path):
    """Stderr-warn on envelope drift: fragment_schema absent/!=1, stem != session_id."""
    fn = os.path.basename(path)
    schema = env.get("fragment_schema")
    if schema != "1":
        print("deltas-for: warning: %s: fragment_schema %s (expected 1; parsing anyway)"
              % (fn, "missing" if schema is None else "'%s'" % schema), file=sys.stderr)
    sid = env.get("session_id")
    stem = os.path.splitext(fn)[0]
    if sid and sid != stem:
        print("deltas-for: warning: %s: session_id '%s' != filename stem '%s' (identity lock)"
              % (fn, sid, stem), file=sys.stderr)


def next_id(frag_dir, session_id):
    """--next-id: the next unused `<session_id>-NNN`, counting live AND _archive/.

    The counter was read off the live fragment alone. Archiving MOVES that file, so a
    session that kept capturing afterwards saw nothing and restarted at 001 -- one id
    then named two different deltas, every `consolidates:` reference into that range
    became ambiguous, and consolidate.py's one sanctioned collision path
    (same_session_disjoint, written for exactly a post-archive continuation) could
    never fire, because renumbering guarantees the id sets overlap.

    Counting the archive is therefore the point, not an optimization. Prints the whole
    delta_id because the locked format needs it verbatim in two places (the '## delta:'
    header and `delta_id:`), and hand-concatenation is a way to get them out of sync.

    Matching on the `<session_id>-` prefix ALONE is not safe: one fragment on disk
    carries `a8a9fa5b-001..033` under the filename and envelope
    `a8a9fa5b-03ef-4370-8ae1-60b8d65d293a`, so a prefix query answers 001 for a session
    already holding 33 deltas -- silently recreating the very collision this prevents.
    A file is therefore claimed by stem OR envelope session_id too, and every delta in
    a claimed file counts whatever prefix it wears.

    SNAPSHOT-ONLY, NOT A RESERVATION (Codex Mode 3, Major). This module is read-only by
    charter, so it cannot atomically claim the id it returns: two allocators racing on
    one session both get the same number, and a consolidation archiving a file mid-walk
    can hide ids from the scan. Neither is reachable in the intended flow -- ids are
    per session_id and one session appends its own fragment serially -- but a caller
    that parallelizes capture, or captures during an --apply, must serialize externally
    or move allocation to the write side.
    """
    id_pat = re.compile(r"^(.*)-(\d+)$")
    md, nums, prefixes, archived = [], [], {}, 0
    walk_errors = []

    def _walk_err(exc):
        walk_errors.append("traversal failed: %s (%s)"
                           % (getattr(exc, "filename", None) or frag_dir,
                              type(exc).__name__))

    for root, dirs, files in os.walk(frag_dir, onerror=_walk_err):
        dirs[:] = [d for d in dirs if d != "_drafts"]      # _drafts never holds deltas
        md += [os.path.join(root, f) for f in files
               if f.endswith(".md") and f != "units.yml"]
    if walk_errors:
        # os.walk's default is to SWALLOW scandir failures (round-3 Critical),
        # so an unreadable subtree read as empty -- and an id hidden inside it
        # got re-minted. An allocation cannot stand on a listing it cannot
        # prove complete.
        for line in walk_errors:
            print("deltas-for: " + line, file=sys.stderr)
        print("deltas-for: cannot prove the next id unused -- refusing to "
              "allocate", file=sys.stderr)
        return 2
    # "Next unused" is an ABSENCE claim over every file walked, live and
    # archived alike -- a file that may hide records can hide exactly the id
    # about to be handed out, which is the recorded collision class this
    # command exists to prevent. Refusal names the ONE file to inspect; an
    # acknowledged quarantine proceeds with the gap reported, not silently.
    entries, reg_errors = load_quarantine(frag_dir)
    if entries is None:
        for line in reg_errors:
            print("deltas-for: " + line, file=sys.stderr)
        print("deltas-for: cannot prove the next id unused -- refusing to "
              "allocate", file=sys.stderr)
        return 2
    blocking, standing = [], []
    counted = 0
    for path in sorted(md):
        # ONE byte snapshot per file, via the shared scan (round-1 Critical:
        # hash-then-reopen let a mid-run writer swap the file under a
        # still-valid acknowledgment; round 2 found the split surviving in a
        # second spelling -- so there is now exactly one).
        env, deltas, verdict, line = snapshot_scan(path, frag_dir, entries)
        if verdict == "standing":
            standing.append(line)
        elif verdict == "blocking":
            blocking.append(line)
        owns = (os.path.splitext(os.path.basename(path))[0] == session_id
                or env.get("session_id") == session_id)
        # ancestry, not immediate parent: _archive/nested/ files COUNT (the
        # walk is recursive) and must be reflected in the archive note too
        # (round-3 Minor: counted but unreported reads as a live-file count).
        arch_prefix = os.path.normpath(os.path.join(frag_dir, "_archive")) + os.sep
        in_archive = os.path.normpath(path).startswith(arch_prefix)
        for d in deltas:
            hit = False
            # BOTH ids of a record are burned. A malformed record (header 'sid-002',
            # delta_id 'sid-001') is keyed by delta_id, so counting only that returns
            # 'sid-002' next -- an id the header already occupies (Codex Mode 3, Major).
            for cand in (d.get("delta_id"), d.get("_header_id")):
                m = id_pat.match(cand or "")
                if not m or not (owns or m.group(1) == session_id):
                    continue
                nums.append(int(m.group(2)))
                prefixes[m.group(1)] = prefixes.get(m.group(1), 0) + 1
                hit = True
            counted += 1 if hit else 0
            archived += 1 if (hit and in_archive) else 0
    for line in standing:
        print("deltas-for: " + line, file=sys.stderr)
    if blocking:
        for line in blocking:
            print("deltas-for: " + line, file=sys.stderr)
        print("deltas-for: cannot prove the next id unused -- refusing to "
              "allocate", file=sys.stderr)
        return 2
    if archived:
        print("deltas-for: note: %d of this session's %d delta(s) live in _archive/ -- "
              "counted, because the live file alone would restart at 001"
              % (archived, counted), file=sys.stderr)
    other = sorted(p for p in prefixes if p != session_id)
    if other:                       # legacy/abbreviated prefix: keep the FILE consistent
        print("deltas-for: warning: this session's deltas use prefix(es) %s, not '%s' -- "
              "numbering continues under '%s' so ids inside the file stay consistent"
              % (", ".join(repr(p) for p in other), session_id,
                 max(prefixes, key=lambda p: prefixes[p])), file=sys.stderr)
    prefix = session_id if session_id in prefixes or not prefixes else max(
        prefixes, key=lambda p: prefixes[p])
    print("%s-%03d" % (prefix, (max(nums) + 1) if nums else 1))
    return 0


def debt(frag_dir):
    """--debt: deterministic consolidation-debt summary over ACTIVE fragments
    (excludes _archive/). Plain text; stable ordering (units sorted by unit_id).

    Also reports KIND-FIELD COMPOSITION, a METADATA proxy for spec §8 -- "a cold
    session given the KF alone can name the unit's improvement points and problems".
    §8 is the tier's success bar, `--kind` could always measure it, and until
    2026-08-02 nothing ever ran that query: across 227 deltas the problem kinds were
    10.6% and `rejection` was 2, i.e. the tier had drifted into a log of conclusions.

    It counts the `kind` FIELD and never opens a body, so it cannot see evaluative
    content and must not be described as if it could -- measured 2026-08-05, a unit
    whose bodies carried a rejected design, a shipped risk and a coverage limit scored
    2 of 19, because those deltas were typed finding/rejection/constraint. The signal
    is still worth having; the claim around it just has to stay this size.

    STDOUT IS A CONSUMED CONTRACT, not just a report. `scripts/doctor.py` parses three
    line prefixes out of this output -- "unconsolidated deltas" (it reads the integer
    after the last ':'), "oldest unconsolidated created_at:", and "oldest unconsolidated
    delta:". Neither side declared that dependency, and doctor's test builds those strings
    by hand instead of invoking this function, so a rename here would break /doctor with
    every suite still green. Keep all three prefixes stable, or change doctor.py and its
    fixture in the same edit."""
    md = []
    for root, dirs, files in os.walk(frag_dir):
        dirs[:] = [d for d in dirs if d not in ("_archive", "_drafts")]
        md += [os.path.join(root, f) for f in files if f.endswith(".md")]
    total, provisional, by_unit, oldest, oldest_ref = 0, 0, {}, "", ""
    disposed = {}
    problem_by_unit, kinds_seen = {}, {}
    # Reporting, not allocation, so damage WARNS instead of refusing -- but a
    # damaged active fragment under-reports debt (its hidden deltas are debt
    # nobody counts), and a silent under-report reads as "all captured". The
    # ARCHIVE is in the damage scope even though it is outside the debt scope:
    # "every consumer prints standing quarantines" includes the default
    # commands, not only the ones that scan the archive (round 2, Major).
    arch_paths, arch_errors = archive_md(frag_dir)
    blocking, standing = damage_report(
        frag_dir, sorted(set(md) | set(arch_paths)))
    for line in standing + blocking + arch_errors:
        print("deltas-for: warning: " + line, file=sys.stderr)
    for path in sorted(md):
        env, deltas, _warns = parse_fragment(path)
        warn_envelope(env, path)
        for d in deltas:
            status = d.get("status")
            if status in DISPOSED:
                disposed[status] = disposed.get(status, 0) + 1
                continue
            total += 1
            uid = d.get("unit_id") or "?"
            by_unit[uid] = by_unit.get(uid, 0) + 1
            k = d.get("kind")
            kinds_seen[k] = kinds_seen.get(k, 0) + 1
            if k in PROBLEM_KINDS:
                problem_by_unit[uid] = problem_by_unit.get(uid, 0) + 1
            if d.get("status") == "provisional":
                provisional += 1
            ts = d.get("created_at") or ""
            if ts and (not oldest or ts < oldest):
                oldest = ts
                oldest_ref = "%s (%s)" % (
                    d.get("delta_id") or d.get("_header_id") or "?",
                    os.path.relpath(path, frag_dir).replace("\\", "/"),
                )
    drafts_dir = os.path.join(frag_dir, "_drafts")
    pending = (sorted(f for f in os.listdir(drafts_dir) if f.endswith(".md"))
               if os.path.isdir(drafts_dir) else [])
    print("=== knowledge-fragment debt: %s ===" % frag_dir)
    print("active fragment files: %d" % len(md))
    if pending:
        print("pending consolidation drafts: %d (%s)" % (len(pending), ", ".join(pending)))
    # The parenthetical states the ACTUAL predicate. It read "status != consolidated",
    # which this loop has never computed -- it skips every DISPOSED status -- and the
    # false label was itself quoted back as fact in a handoff note.
    print("unconsolidated deltas (no terminal disposition): %d" % total)
    for uid in sorted(by_unit):
        p = problem_by_unit.get(uid, 0)
        # "typed" is load-bearing: this is the kind FIELD, not a judgement about what
        # the unit recorded. A unit with none may still have captured every risk it
        # met, under another kind.
        print("  %s: %d%s" % (uid, by_unit[uid],
                              "   [!] 0 deltas typed risk|open_question|followup"
                              if not p else "  (%d so typed)" % p))
    print("provisional: %d" % provisional)
    # A METADATA proxy for spec §8, and the wording below is careful about which.
    # This counts the `kind` FIELD; it never reads a delta body. It cannot tell whether
    # a page's prose records what is weak or open -- measured 2026-08-05, a unit whose
    # bodies were dense with recorded risks and rejections scored 2 of 19, because the
    # deltas carrying them were typed `finding`, `rejection` and `constraint`.
    # Teaching it to read bodies is deliberately NOT the fix: that puts an
    # inference-shaped heuristic inside the automation layer, which is the boundary
    # this whole pipeline exists to hold. So the number stays and the CLAIM shrinks to
    # what the number supports. Reported, never enforced: a unit can legitimately have
    # none. Silence is what let it reach 10.6% unnoticed.
    if total:
        prob = sum(problem_by_unit.values())
        print("kind-field composition (metadata proxy for spec 8, NOT a read of the "
              "bodies): %d of %d outstanding are typed risk|open_question|followup "
              "= %.0f%%" % (prob, total, 100.0 * prob / total))
        if kinds_seen:
            print("  kinds: " + ", ".join("%s=%d" % (k or "?", kinds_seen[k])
                                          for k in sorted(kinds_seen, key=lambda x: (x or ""))))
        blind = sorted(u for u in by_unit if not problem_by_unit.get(u))
        if blind:
            # The label this replaced asserted what the prose contains, from a field
            # this loop counted. These units typed no delta
            # risk|open_question|followup; their bodies may still be full of both.
            print("  units with no delta typed risk|open_question|followup: "
                  + ", ".join(blind))
    # Disposed deltas are NOT debt, but they are printed so "0 debt" can be read
    # as "everything has a disposition" rather than "everything became a page".
    if disposed:
        print("disposed (not debt): "
              + ", ".join("%s=%d" % (s, disposed[s]) for s in sorted(disposed)))
    print("oldest unconsolidated created_at: %s" % (oldest or "(none)"))
    print("oldest unconsolidated delta: %s" % (oldest_ref or "(none)"))
    return 0


def usage_error(msg):
    print("deltas-for: " + msg, file=sys.stderr)
    print(USAGE, file=sys.stderr)
    return 2


def main():
    argv = sys.argv[1:]
    flags, pos, i = {}, [], 0
    while i < len(argv):                                     # strict: unknown args exit 2
        a = argv[i]
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            if name in VALUE_FLAGS:
                if "=" in a:
                    flags[name] = a.split("=", 1)[1]
                elif i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                    i += 1
                    flags[name] = argv[i]                    # space form: --kind k1,k2
                else:
                    return usage_error("%s requires a value (--kind=k1,k2 or --kind k1,k2)" % name)
            elif a in BOOL_FLAGS:
                flags[a] = True
            else:
                return usage_error("unrecognized argument '%s'" % a)
        else:
            pos.append(a)
        i += 1

    if "--next-id" in flags:
        if len(flags) > 1 or len(pos) != 1:
            return usage_error("--next-id takes the knowledge dir and a session id, "
                               "no other flags")
        frag_dir = find_fragments(pos[0])
        if not frag_dir:                       # no fragments yet: this is delta 001
            print("%s-001" % flags["--next-id"])
            return 0
        return next_id(frag_dir, flags["--next-id"])

    if "--debt" in flags:
        if len(flags) > 1 or len(pos) != 1:
            return usage_error("--debt takes exactly one argument (the knowledge dir), no other flags")
        frag_dir = find_fragments(pos[0])
        if not frag_dir:
            print("deltas-for: no _fragments/ directory under %s" % pos[0])
            return 0
        return debt(frag_dir)

    if len(pos) > 2:
        return usage_error("unrecognized argument '%s'" % pos[2])
    if "--capture-brief" in flags and "--include-archive" in flags:
        return usage_error("--capture-brief cannot combine with --include-archive "
                           "(briefs consume unconsolidated deltas only)")
    if len(pos) < 2:
        print(USAGE)
        return 0

    frag_dir = find_fragments(pos[0])
    if not frag_dir:
        print("deltas-for: no _fragments/ directory under %s" % pos[0])
        return 0
    query = pos[1]
    kinds = set(flags["--kind"].split(",")) if isinstance(flags.get("--kind"), str) else None

    alias2canon = load_units(frag_dir)
    if query not in alias2canon:                             # under-return hazard (lock #3)
        print("deltas-for: warning: unit_id '%s' not declared in units.yml "
              "(no alias resolution -- results may under-return)" % query, file=sys.stderr)
    canon = alias2canon.get(query, query)                    # resolve query to canonical
    aliases = {a for a, c in alias2canon.items() if c == canon} | {canon, query}
    parent = unit_parents(frag_dir).get(canon)
    if parent and parent not in alias2canon:
        print("deltas-for: warning: parent '%s' of unit '%s' not declared in units.yml"
              % (parent, canon), file=sys.stderr)
    elif parent and alias2canon.get(parent) == canon:
        print("deltas-for: warning: unit '%s' is its own parent" % canon, file=sys.stderr)
    elif parent and alias2canon.get(parent) != parent:                 # Codex m: alias drift
        print("deltas-for: warning: parent '%s' of unit '%s' is an alias of '%s' -- "
              "use the canonical_id" % (parent, canon, alias2canon.get(parent)),
              file=sys.stderr)

    md = []
    for root, dirs, files in os.walk(frag_dir):
        skip = {"_drafts"} | (set() if "--include-archive" in flags else {"_archive"})
        dirs[:] = [d for d in dirs if d not in skip]                 # _drafts/ never holds deltas
        md += [os.path.join(root, f) for f in files if f.endswith(".md") and f != "units.yml"]

    # A query never blocks (exit-0 charter), but "every consumer PRINTS a
    # standing quarantine" includes this one -- an acknowledged gap that a
    # listing silently reads past looks exactly like completeness. The archive
    # is in the DAMAGE scope even when it is outside the RESULT scope (round
    # 2, Major: the default query printed nothing that --include-archive
    # printed).
    q_arch_paths, q_arch_errors = archive_md(frag_dir)
    q_blocking, q_standing = damage_report(
        frag_dir, sorted(set(md) | set(q_arch_paths)))
    for line in q_standing + q_blocking + q_arch_errors:
        print("deltas-for: warning: " + line, file=sys.stderr)

    hits, warnings, seen_global, skipped = [], [], {}, 0
    for path in sorted(md):
        env, deltas, warns = parse_fragment(path)
        warn_envelope(env, path)
        warnings += warns
        for d in deltas:
            did = d.get("delta_id") or d.get("_header_id")
            if did in seen_global and seen_global[did] != d.get("_file"):
                warnings.append("duplicate delta_id '%s' across files (%s, %s)"
                                % (did, seen_global[did], d.get("_file")))
            seen_global.setdefault(did, d.get("_file"))
            if alias2canon.get(d.get("unit_id"), d.get("unit_id")) != canon:
                continue
            if kinds and d.get("kind") not in kinds:
                continue
            if d.get("status") in DISPOSED and "--include-archive" not in flags:
                skipped += 1            # terminally disposed (spec §6); --include-archive
                continue                # re-includes them (post-disposition trajectory)
            hits.append(d)
    hits.sort(key=lambda d: d.get("created_at", ""))         # chronological (lock #1)
    if skipped:
        print("skipped %d disposed delta(s) (consolidated/archived/superseded)"
              % skipped, file=sys.stderr)

    label = "%s" % canon + ("" if canon == query else " (via alias '%s')" % query)
    if parent:
        label += " (parent: %s)" % parent
    print("=== deltas-for %s -- %d delta(s) across %d fragment file(s)%s ==="
          % (label, len(hits), len(md), ("; aliases: " + ", ".join(sorted(aliases - {canon}))) if len(aliases) > 1 else ""))
    if warnings:
        print("\nWARNINGS (malformed deltas -- surfaced, never dropped):")
        for w in warnings:
            print("  ! " + w)

    if not hits:
        print("\n(no deltas for this unit -- check the unit_id / units.yml aliases)")
        return 0

    if "--capture-brief" in flags:                           # consolidation adapter (Codex C2)
        print("\n--- capture brief for /research-kb capture (unit: %s) ---" % canon)
        cand = sorted({r for d in hits for r in informed_refs(d)})
        if cand:                                             # bare tokens; no link syntax
            print("wikilink candidates (seed the page's links): " + "; ".join(cand))
        if parent:
            print("parent unit: %s" % parent)
        if not cand and not parent:
            print("(no informed_by on this unit's deltas -- record the orientation set "
                  "on the unit's first delta)")
        by_kind = {}
        for d in hits:
            by_kind.setdefault(d.get("kind", "?"), []).append(d)
        for k in ("decision", "finding", "rejection", "risk",
                  "constraint", "open_question", "followup"):
            for d in by_kind.get(k, []):
                print("\n[%s] %s  (%s, %s)" % (k, d.get("summary", ""),
                                               d.get("status", "?"), d.get("created_at", "?")))
                if d.get("_body"):
                    print("  " + d["_body"].replace("\n", "\n  "))
                refs = code_refs(d)
                if refs:
                    print("  wiki-signal (feed to wiki-pages-for): " + " ".join(refs))
        return 0

    for d in hits:                                           # default chronological listing
        print("\n## %s  [%s/%s]  %s" % (d.get("_header_id", "?"), d.get("kind", "?"),
                                        d.get("status", "?"), d.get("created_at", "")))
        print("   %s" % d.get("summary", ""))
        if "wiki" in (d.get("feeds") or []):
            refs = code_refs(d)
            if refs:
                print("   -> wiki signal: %s" % " ".join(refs))
        inf = informed_refs(d)
        if inf:
            print("   -> informed_by: %s" % "; ".join(inf))
    return 0


if __name__ == "__main__":
    sys.exit(main())
