#!/usr/bin/env python3
"""batch-promote: witnessed multi-unit consolidation batch -- one create draft plus N
update-existing carriers into ONE target page, with every expected-output, manifest and
status witness computed over RAW BYTES by shared code (spec:
dev-setup-codex/specs/knowledge-fragment.md section 12, fourth build).

Born from resonance `library-core-consolidation-v1` R11: prose specified the create
transform as text while asserting raw-byte equality, so a cold Windows runner could
materialize the expectation through newline translation and read a healthy create as
corruption (R11-N-M1). Here the expectation is `consolidate.create_text_from_draft()`
output `.encode("utf-8")`, every comparison reads files with `"rb"`, and no witness
value ever passes through a text-mode file write.

Commands (one per run; `<dir>` = knowledge dir or `_fragments` itself):
  --check       read-only: classify every unit's state, verify manifests/counts/
                disjointness/coverage/anchors/pins/damage, derive the source fragment
                set and expected create bytes; a fully-landed batch is re-verified
                against its state (final manifest, integrity digest, consolidated
                statuses, completion-witness sha) before COMPLETE is printed; exit 0
                iff the batch is executable from the current state or verified
                complete.
  --init        the ONE deliberate state mutation outside applies: write the JSON
                state file (spec sha, unit manifests, derived source files, initial
                status map, expected create sha) while every draft is still present.
                Refuses an existing state file and any assessment problem. --execute
                REQUIRES the state file and never creates it, so a downstream apply
                refusal mutates nothing.
  --execute     ordered applies through `consolidate.apply` with per-step witnesses:
                a PROJECTION witness -- --init records, per source file, the sha of
                the bytes the authoritative flip transform itself would produce once
                every batch id is flipped (`flip_statuses` dry-run text); at every
                later point, cross-process included, projecting the CURRENT bytes
                through the still-unflipped ids must reproduce that sha, so any byte
                not written by an approved flip (envelope fields including a col-0
                `status:` envelope line, whitespace, bodies, metadata, even bytes
                inside a status line beyond its parsed value) halts the batch --
                plus the full status-map diff over every delta in the derived source
                files (per record: unit_id + status + a content fingerprint over
                every other parsed field including the body; changed set must equal
                exactly that unit's ids; batch ids may already read consolidated
                from a partial apply, each unit's landing verified at its own row),
                a positional byte witness per touched fragment (same line count,
                every differing line a status-scalar flip), raw-byte expected-target
                equality (create), integrity digest over the target minus its
                `consolidates:` block (carriers), exact manifest growth against the
                --init baseline, draft-vanished, landed-state persisted after every
                step; idempotent resume; any mismatch stops with a named verdict and
                mutates nothing further. No Git, no auto-rollback -- recovery stays
                outer-plan choreography.
  --map f...    print a status-map snapshot (per-file sha256/location + id ->
                [unit, status, fingerprint]) of the named fragment files, for
                hand-edited close steps.
  --diff a b    compare two --map snapshots: ids in --expect-changed must END at
                --expect-to (their content may change -- hand edits append rationale);
                every other id keeps status AND fingerprint; a file with no expected
                id inside must be byte-identical.

Tool identity: sha256 pins of consolidate.py + deltas-for.py are embedded below,
verified before those modules are even loaded and again before every apply; the suite
recomputes them, so editing either tool without a re-review-and-re-pin turns the repo
red (R11-N-m1). The tool cannot pin itself; it prints its own sha256 every run so the
invoking transcript carries the identity.

Exit: 0 success/complete; 1 refusal or witness failure (message says which);
2 usage or malformed spec. SINGLE WRITER, NO LOCK -- same charter and same residual
read->write windows as consolidate.py; guarantees read "verified immediately before".
"""
import datetime
import hashlib
import importlib.util
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))

PINNED = {
    "consolidate.py": "8cd39bac2518b0cad1350c421c4475fffc18c08f3558b9c0598b1887f954bd0c",
    "deltas-for.py": "2b11d9c17d2748c2fecde5537e7587b6759cf94a88be7cf338d2ca2d50891c3d",
}

ANCHOR = re.compile(r'^- landed in: "(.+)"\s*$')
BANNER_PREFIX = "> DRAFT:"
USAGE = ("usage: python batch-promote.py <knowledge|_fragments dir> --check|--transition|--init|--execute"
         " --spec <spec.json> [--state <state.json>]\n"
         "       python batch-promote.py <knowledge|_fragments dir> --map <fragment.md> [...]\n"
         "       python batch-promote.py <knowledge|_fragments dir> --diff <before.json> <after.json>"
         " [--expect-changed id1,id2 --expect-to <status>]")

df = None
con = None


def fail(msg, code=1):
    print("batch-promote: " + msg, file=sys.stderr)
    return code


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def verify_pins():
    """(got, drifted): current sibling hashes vs the reviewed baseline."""
    got = {fn: sha256_file(os.path.join(HERE, fn)) for fn in sorted(PINNED)}
    return got, sorted(fn for fn in PINNED if got[fn] != PINNED[fn])


def load_tools():
    global df, con
    for name, fn in (("deltas_for", "deltas-for.py"), ("consolidate", "consolidate.py")):
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, fn))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if name == "deltas_for":
            df = mod
        else:
            con = mod


def load_spec(path):
    """(spec, error). Validated shape:
    {batch_promotion_schema: 1, target: <slice/page.md>,
     create: {unit, manifest}, carriers: [{unit, manifest, landed_in}, ...]}"""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return None, "cannot read spec: %s" % e
    try:
        spec = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        return None, "spec is not valid UTF-8 JSON: %s" % e
    if not isinstance(spec, dict) or spec.get("batch_promotion_schema") != 1:
        return None, "spec must be an object with batch_promotion_schema: 1"
    tgt = spec.get("target")
    if not isinstance(tgt, str) or not tgt:
        return None, "spec.target must be a non-empty string"
    cr = spec.get("create")
    if not isinstance(cr, dict):
        return None, "spec.create must be an object"
    carriers = spec.get("carriers")
    if not isinstance(carriers, list):
        return None, "spec.carriers must be a list"
    units = []
    for label, entry, need_anchor in ([("create", cr, False)]
                                      + [("carriers[%d]" % i, c, True)
                                         for i, c in enumerate(carriers)]):
        if not isinstance(entry, dict):
            return None, "spec.%s must be an object" % label
        u = entry.get("unit")
        if not isinstance(u, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", u or "") or not u.strip("."):
            return None, "spec.%s.unit is not a safe slug" % label
        n = entry.get("manifest")
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            return None, "spec.%s.manifest must be a positive integer" % label
        if need_anchor:
            li = entry.get("landed_in")
            if not isinstance(li, str) or not li:
                return None, "spec.%s.landed_in must be a non-empty string" % label
            if "\n" in li or "\r" in li:
                return None, ("spec.%s.landed_in must be a single line -- the anchor "
                              "is one literal line in the carrier draft" % label)
        if not need_anchor and "landed_in" in entry:
            return None, "spec.create takes no landed_in"
        units.append(u)
    if len(units) != len(set(units)):
        return None, "spec units must be distinct"
    spec["_sha256"] = hashlib.sha256(raw).hexdigest()
    return spec, None


def norm(s):
    """Anchor-label normalization -- keep byte-identical with resonance
    scripts/draft_freshness.py norm() (accepted duplication; this side is the
    authority for batch anchors)."""
    s = s.replace("—", "-").replace("–", "-").replace("--", "-")
    s = s.replace("’", "'").replace("`", "").replace('"', "").replace("*", "")
    return re.sub(r"\s+", " ", s).strip().lower()


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def split_keepends(raw):
    """(lines_keepends, error) -- raw bytes decoded strictly; every terminator kept."""
    try:
        return raw.decode("utf-8").splitlines(keepends=True), None
    except UnicodeDecodeError as e:
        return None, "not valid UTF-8: %s" % e


def frontmatter_span(lines):
    """(start, end) line indexes of the first frontmatter block's delimiters, or None."""
    if not lines or lines[0].rstrip("\r\n").strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n").strip() == "---":
            return 0, i
    return None


def consolidates_span(lines, fm_end):
    """(key_line, first_after_items) inside the frontmatter, or (None, error-or-None).
    Strict two-space block items only -- the shape consolidate.py writes and merges.
    More than one col-0 `consolidates:` key (any style mix) is an error: parse_meta,
    the consumer, takes the LAST key while the merge writes into the FIRST, so a
    duplicate splits provenance invisibly."""
    keys = [i for i in range(1, fm_end)
            if re.match(r"^consolidates:", lines[i].rstrip("\r\n"))]
    if len(keys) > 1:
        return None, "frontmatter carries more than one consolidates: key"
    for i in keys:
        c = lines[i].rstrip("\r\n")
        if re.match(r"^consolidates:\s*#", c):
            return None, ("consolidates key line carries a comment -- the consumer "
                          "grammar reads it as a scalar value")
        if re.match(r"^consolidates:\s*$", c):
            j = i + 1
            while j < fm_end and re.match(r"^  - \S+\s*$", lines[j].rstrip("\r\n")):
                j += 1
            if j < fm_end and re.match(r"^\s+-\s", lines[j].rstrip("\r\n")):
                return None, ("consolidates block contains a noncanonical item line "
                              "(the consumer grammar would still read it as an id)")
            k = j
            while k < fm_end and not re.match(r"^\w+:", lines[k].rstrip("\r\n")):
                if re.match(r"^\s+-\s", lines[k].rstrip("\r\n")):
                    return None, ("consolidates block resumes after a comment/blank "
                                  "gap (the consumer grammar reads the later item(s) "
                                  "as manifest items)")
                k += 1
            return (i, j), None
        return None, "target consolidates: uses inline style"
    return None, None


def integrity_digest(raw):
    """(sha256-hex, error): the target bytes minus ONLY the `consolidates:` key line and
    its contiguous two-space id items -- every other byte and line ending preserved, so
    the digest is invariant under the one mutation a carrier apply is allowed to make."""
    lines, err = split_keepends(raw)
    if err:
        return None, err
    span = frontmatter_span(lines)
    if not span:
        return None, "target has no terminated frontmatter block"
    cspan, err = consolidates_span(lines, span[1])
    if err:
        return None, err
    drop = set(range(cspan[0], cspan[1])) if cspan else set()
    kept = "".join(l for i, l in enumerate(lines) if i not in drop)
    return hashlib.sha256(kept.encode("utf-8")).hexdigest(), None


def target_manifest(raw):
    """(ordered id list, error) from the target's frontmatter consolidates: block."""
    lines, err = split_keepends(raw)
    if err:
        return None, err
    span = frontmatter_span(lines)
    if not span:
        return None, "target has no terminated frontmatter block"
    cspan, err = consolidates_span(lines, span[1])
    if err:
        return None, err
    if not cspan:
        return [], None
    return [re.match(r"^  - (\S+)", lines[i].rstrip("\r\n")).group(1)
            for i in range(cspan[0] + 1, cspan[1])], None


def parse_draft(path, unit, text=None):
    """(info, error): frontmatter fields + manifest + banner/anchor facts of one
    draft; `text` parses a PROJECTED draft instead of reading `path`."""
    parts = con.split_draft_text(text) if text is not None else con.split_draft(path)
    if not parts:
        return None, "draft frontmatter malformed: %s" % path
    front, body = parts
    meta = df.parse_meta(front)
    ids = meta.get("consolidates") or []
    if isinstance(ids, str):
        ids = [ids]
    if meta.get("unit") != unit:
        return None, "draft unit %r != %r in %s" % (meta.get("unit"), unit, path)
    if not ids:
        return None, "empty consolidates manifest in %s" % path
    if len(ids) != len(set(ids)):
        return None, "duplicate manifest id(s) in %s" % path
    body_lines = body.splitlines()
    banners = [ln for ln in body_lines if ln.lstrip().startswith(BANNER_PREFIX)]
    anchors = [ANCHOR.match(ln).group(1) for ln in body_lines if ANCHOR.match(ln)]
    return {"path": path, "front": front, "body": body, "ids": ids,
            "target": meta.get("target", ""), "mode": meta.get("apply_mode", ""),
            "banners": len(banners), "anchors": anchors}, None


def classify(frag_dir, spec, state):
    """(units, error): per-unit dicts {unit, role, state, ids, detail} in batch order.
    States: ready|undistilled (create) · fresh|transitioned (carrier) · absent
    (draft gone -- landed-ness is decided against target+fragments by the caller) ·
    inconsistent (named)."""
    out = []
    recorded = (state or {}).get("units", {})
    for role, entry in [("create", spec["create"])] + [("carrier", c) for c in spec["carriers"]]:
        unit = entry["unit"]
        row = {"unit": unit, "role": role, "ids": recorded.get(unit), "detail": ""}
        dpath = os.path.join(frag_dir, "_drafts", unit + ".md")
        if not os.path.exists(dpath):
            row["state"] = "absent" if row["ids"] else "inconsistent"
            if not row["ids"]:
                row["detail"] = "draft missing and no state record carries its manifest"
            out.append(row)
            continue
        info, err = parse_draft(dpath, unit)
        if err:
            row["state"], row["detail"] = "inconsistent", err
            out.append(row)
            continue
        row["ids"], row["path"] = info["ids"], dpath
        if len(info["ids"]) != entry["manifest"]:
            row["state"] = "inconsistent"
            row["detail"] = ("manifest holds %d id(s), spec says %d"
                             % (len(info["ids"]), entry["manifest"]))
        elif role == "create":
            if info["mode"] != "create" or info["target"] != spec["target"]:
                row["state"] = "inconsistent"
                row["detail"] = ("create draft must carry apply_mode: create + target %s "
                                 "(got %s / %s)" % (spec["target"], info["mode"], info["target"]))
            else:
                row["state"] = "undistilled" if info["banners"] else "ready"
        else:
            if info["banners"] > 1:
                row["state"], row["detail"] = "inconsistent", "more than one DRAFT banner line"
            elif info["banners"] == 1:
                row["state"] = "fresh"
            elif (info["anchors"] == [entry["landed_in"]]
                  and info["mode"] == "update-existing" and info["target"] == spec["target"]):
                row["state"] = "transitioned"
            else:
                row["state"] = "inconsistent"
                row["detail"] = ("no banner, but target/mode/anchor are not the transitioned "
                                 "contract (target=%s mode=%s anchors=%r)"
                                 % (info["target"], info["mode"], info["anchors"]))
        out.append(row)
    return out, None


def source_files(frag_dir, all_ids):
    """(sorted relpaths, missing ids, error): the active fragment files holding the
    batch ids -- the derived touched set the witnesses observe and the outer plan
    stages -- plus the ids not found in any active fragment."""
    md, errors = con.active_md(frag_dir)
    if errors:
        return None, None, "; ".join(errors)
    where, dups = {}, set()
    for path in md:
        _env, deltas, _w = df.parse_fragment(path)
        for d in deltas:
            did = d.get("delta_id") or d.get("_header_id")
            if did in where and where[did] != path:
                dups.add(did)
            where.setdefault(did, path)
    hit = sorted({os.path.relpath(where[i], frag_dir).replace("\\", "/")
                  for i in all_ids if i in where})
    bad = sorted(set(all_ids) & dups)
    if bad:
        return None, None, "batch id(s) duplicated across active fragments: %s" % ", ".join(bad)
    return hit, sorted(i for i in all_ids if i not in where), None


def resolve_source(frag_dir, rel):
    """(abspath, where, error): a recorded source file, live or moved to _archive/ by a
    fully-disposed apply step. Exactly one location may hold it."""
    live = os.path.join(frag_dir, rel)
    arch = os.path.join(frag_dir, "_archive", os.path.basename(rel))
    if os.path.exists(live) and os.path.exists(arch):
        return None, None, "%s exists both live and in _archive/ -- ambiguous" % rel
    if os.path.exists(live):
        return live, "live", None
    if os.path.exists(arch):
        return arch, "_archive", None
    return None, None, "%s is neither live nor in _archive/" % rel


def record_fp(d):
    """Content fingerprint of one parsed delta: every field except the one allowed
    to change (`status`) and the parser's file label. Body included."""
    return hashlib.sha256(json.dumps(
        {k: v for k, v in d.items() if k not in ("status", "_file")},
        sort_keys=True).encode("utf-8")).hexdigest()


def full_manifest(state):
    return [i for u in state["unit_order"] for i in state["units"][u]]


def manifest_state_ok(man, state):
    """Violations: the target's manifest must be an EXACT boundary prefix of the
    full initialized batch manifest. Junk, reorder, duplicate or a mid-unit length
    is corruption to stop on BEFORE more recovery drafts are consumed -- a bare
    landed-prefix check let a corrupt tail ride to final verification (R5-M1)."""
    full = full_manifest(state)
    out = []
    if man != full[:len(man)]:
        out.append("target manifest %r is not a prefix of the initialized batch manifest"
                   % (man,))
    bounds, n = {0}, 0
    for u in state["unit_order"]:
        n += len(state["units"][u])
        bounds.add(n)
    if len(man) not in bounds:
        out.append("target manifest length %d is not a unit boundary" % len(man))
    return out


def projected_sha(path, remaining_ids):
    """sha256 of the bytes this file WOULD hold once `remaining_ids` are flipped --
    computed by the one authoritative flip grammar itself (`flip_statuses` in
    dry-run, returning its transformed text), never by a respelled mask. Because
    the flip transform is deterministic in (bytes, ids), `projected_sha(current,
    still-unflipped batch ids)` equals the value recorded at --init from the
    initial bytes iff NOTHING outside the approved flips ever changed: envelope
    fields (a col-0 `status:` envelope line included -- the flip scan only rewrites
    a record's authoritative status line), whitespace, bodies, metadata, and even
    bytes inside a status line beyond its parsed value all break the equality,
    cross-process included. At the final state the remaining set is empty and the
    projection pins the exact final bytes."""
    _flipped, text = con.flip_statuses(path, set(remaining_ids),
                                       dry_run=True, return_text=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def projection_check(frag_dir, state, snap):
    """Violations of the per-file final-bytes projection recorded at --init."""
    batch_ids = {i for ids in state["units"].values() for i in ids}
    out = []
    for rel in state["source_files"]:
        path, _w, err = resolve_source(frag_dir, rel)
        if err:
            return [err]
        remaining = [i for i, val in snap[rel]["deltas"].items()
                     if i in batch_ids and val[1] != "consolidated"]
        if projected_sha(path, remaining) != state["final_expected"].get(rel):
            out.append("file %s does not project to the expected final bytes "
                       "(non-status mutation since --init)" % rel)
    return out


def snapshot(frag_dir, rels):
    """(map, error): {rel: {sha256, where, deltas: {id: [unit, status, fp]}}} for the
    recorded source files -- the full-map witness (every delta, co-tenants included)."""
    out = {}
    for rel in rels:
        path, where, err = resolve_source(frag_dir, rel)
        if err:
            return None, err
        raw = read_bytes(path)
        _env, deltas, warns = df.parse_fragment(path, data=raw)
        loss = [w for w in warns if df.RECORD_LOSS in w or ": unreadable" in w]
        if loss:
            return None, "%s may hide records -- the map is unsound: %s" % (rel, "; ".join(loss))
        m = {}
        for d in deltas:
            did = d.get("delta_id") or d.get("_header_id")
            if did in m:
                return None, "%s holds duplicate id %s" % (rel, did)
            m[did] = [d.get("unit_id"), d.get("status"), record_fp(d)]
        out[rel] = {"sha256": hashlib.sha256(raw).hexdigest(), "where": where, "deltas": m}
    return out, None


def flat(snap):
    """{id: [unit, status]} across a snapshot; duplicate ids across files refused
    upstream (source_files) and here defensively."""
    out = {}
    for rel in sorted(snap):
        for did, val in snap[rel]["deltas"].items():
            if did in out:
                return None
            out[did] = val
    return out


def map_diff(before, after, expect_changed, expect_to,
             allow_partial=False, expected_content_stable=True):
    """Violations comparing two snapshots. Ids in `expect_changed` must END at
    `expect_to` (an already-there id is a legitimate resumed no-op; with
    `allow_partial`, keeping the before-status is also legitimate -- the
    partially-applied-unit resume). Every other id keeps status AND content
    fingerprint; expected ids keep their fingerprint too unless
    `expected_content_stable` is False (hand edits may append rationale). No id
    appears, disappears, or changes unit_id. File level: a file with no expected id
    inside must keep its exact bytes and location."""
    b, a = flat(before), flat(after)
    if b is None or a is None:
        return ["duplicate id across files inside a snapshot"]
    out = []
    for rel in sorted(set(before) & set(after)):
        holds = any(i in expect_changed
                    for i in set(before[rel]["deltas"]) | set(after[rel]["deltas"]))
        if before[rel]["sha256"] != after[rel]["sha256"] and not holds:
            out.append("file %s bytes changed with no expected id inside" % rel)
        if before[rel].get("where") != after[rel].get("where") and not holds:
            out.append("file %s moved (%s -> %s) with no expected id inside"
                       % (rel, before[rel].get("where"), after[rel].get("where")))
    for gone in sorted(set(b) - set(a)):
        out.append("id %s disappeared" % gone)
    for new in sorted(set(a) - set(b)):
        out.append("id %s appeared" % new)
    for i in sorted(set(b) & set(a)):
        if b[i][0] != a[i][0]:
            out.append("id %s unit_id changed %r -> %r" % (i, b[i][0], a[i][0]))
        if i in expect_changed:
            if a[i][1] != expect_to and not (allow_partial and a[i][1] == b[i][1]):
                out.append("id %s reads %r, expected %r" % (i, a[i][1], expect_to))
            if expected_content_stable and b[i][2] != a[i][2]:
                out.append("id %s content changed under a status-only operation" % i)
        else:
            if b[i][1] != a[i][1]:
                out.append("id %s changed %s -> %s outside the expected set"
                           % (i, b[i][1], a[i][1]))
            if b[i][2] != a[i][2]:
                out.append("id %s content changed outside the expected set" % i)
    for i in sorted(set(expect_changed) - (set(b) & set(a))):
        out.append("expected id %s is not present in both snapshots" % i)
    return out


def lines_changed_ok(pre, post, allowed):
    """Positional byte witness for ONE fragment file across ONE apply: flips rewrite
    lines in place, so the line count is preserved and every differing line must be
    a status-scalar rewrite to consolidated -- at most `allowed` of them."""
    a, b = pre.split(b"\n"), post.split(b"\n")
    if len(a) != len(b):
        return ["line count changed %d -> %d across the apply" % (len(a), len(b))]
    out, hits = [], 0
    for i, (x, y) in enumerate(zip(a, b)):
        if x == y:
            continue
        if (re.match(rb"^status:\s*\S", x)
                and re.match(rb"^status:\s*consolidated(\s+#[^\r]*)?\r?$", y)):
            hits += 1
            continue
        out.append("line %d changed and is not a status flip" % (i + 1))
    if hits > allowed:
        out.append("%d status line(s) flipped, at most %d expected" % (hits, allowed))
    return out


def snap_shape_error(snap, label):
    """Named shape error for a snapshot mapping, or None."""
    if not isinstance(snap, dict):
        return "%s must be an object" % label
    for rel, entry in snap.items():
        if not isinstance(rel, str) or not isinstance(entry, dict):
            return "%s entry %r malformed" % (label, rel)
        if not (isinstance(entry.get("sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
            return "%s[%s].sha256 must be 64 hex chars" % (label, rel)
        if entry.get("where") not in ("live", "_archive"):
            return "%s[%s].where must be live|_archive" % (label, rel)
        deltas = entry.get("deltas")
        if not isinstance(deltas, dict):
            return "%s[%s].deltas must be an object" % (label, rel)
        for did, val in deltas.items():
            if not (isinstance(did, str) and isinstance(val, list) and len(val) == 3
                    and all(v is None or isinstance(v, str) for v in val)):
                return "%s[%s].deltas[%r] must be [unit, status, fp]" % (label, rel, did)
    return None


def hex64(v):
    return isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) is not None


def safe_rel(p):
    return (isinstance(p, str) and p and "\\" not in p and not p.startswith("/")
            and not re.match(r"^[A-Za-z]:", p)
            and not any(seg in ("", ".", "..") for seg in p.split("/")))


def id_list(v):
    return (isinstance(v, list) and v
            and all(isinstance(i, str) and i for i in v))


def validate_state(state):
    """Named shape error for a loaded state, or None. Every nested field a later
    step indexes is proven here, so malformed state is a refusal, not a traceback."""
    fields = (("spec_sha256", str), ("target", str), ("created_utc", str),
              ("unit_order", list), ("source_files", list), ("units", dict),
              ("landed", list))
    for key, typ in fields:
        if not isinstance(state.get(key), typ):
            return "state.%s missing or not %s" % (key, typ.__name__)
    if not hex64(state.get("expected_create_sha256")):
        return "state.expected_create_sha256 must be 64 hex chars"
    if not hex64(state.get("initial_map_sha256")):
        return "state.initial_map_sha256 must be 64 hex chars"
    if not (state.get("integrity_sha256") is None or hex64(state["integrity_sha256"])):
        return "state.integrity_sha256 must be null or 64 hex chars"
    if not all(isinstance(u, str) and u for u in state["unit_order"]):
        return "state.unit_order must be a list of unit names"
    if len(state["unit_order"]) != len(set(state["unit_order"])):
        return "state.unit_order must not repeat a unit"
    if not all(safe_rel(p) for p in state["source_files"]):
        return "state.source_files must be confined relative paths"
    if len(state["source_files"]) != len(set(state["source_files"])):
        return "state.source_files must not repeat a path"
    for u, ids in state["units"].items():
        if not (isinstance(u, str) and id_list(ids)):
            return "state.units[%r] must map to a non-empty list of ids" % (u,)
    if set(state["units"]) != set(state["unit_order"]):
        return "state.units keys must equal state.unit_order exactly"
    fe = state.get("final_expected")
    if not (isinstance(fe, dict) and set(fe) == set(state["source_files"])
            and all(hex64(v) for v in fe.values())):
        return "state.final_expected must map every source file to 64 hex chars"
    for key in ("initial_map", "last_map"):
        if not isinstance(state.get(key), dict) \
                or set(state[key]) != set(state["source_files"]):
            return "state.%s keys must equal state.source_files exactly" % key
    for rec in state["landed"]:
        if not (isinstance(rec, dict) and isinstance(rec.get("unit"), str)
                and id_list(rec.get("ids")) and isinstance(rec.get("at_utc"), str)):
            return "state.landed entry malformed: %r" % (rec,)
    for key in ("initial_map", "last_map"):
        err = snap_shape_error(state.get(key), "state." + key)
        if err:
            return err
    w = state.get("witness")
    if w is not None:
        if not (isinstance(w, dict) and w.get("batch_witness_schema") == 1
                and isinstance(w.get("target"), str) and hex64(w.get("target_sha256"))
                and hex64(w.get("integrity_sha256")) and id_list(w.get("manifest"))
                and isinstance(w.get("source_files"), list)
                and isinstance(w.get("deleted_drafts"), list)
                and isinstance(w.get("completed_utc"), str)):
            return "state.witness malformed"
        for e in w["source_files"]:
            if not (isinstance(e, dict) and safe_rel(e.get("path"))
                    and hex64(e.get("sha256"))
                    and e.get("where") in ("live", "_archive")):
                return "state.witness.source_files entry malformed: %r" % (e,)
    for name, ok in STATE_CROSS:
        try:
            good = ok(state)
        except Exception:
            good = False
        if not good:
            return "state cross-check failed: %s" % name
    return None


STATE_CROSS = (
    ("landed sequence follows unit_order",
     lambda s: [l["unit"] for l in s["landed"]] == s["unit_order"][:len(s["landed"])]),
    ("landed ids equal the units baseline",
     lambda s: all(l["ids"] == s["units"].get(l["unit"]) for l in s["landed"])),
    ("witness manifest equals the initialized batch manifest",
     lambda s: s.get("witness") is None
     or s["witness"]["manifest"] == full_manifest(s)),
    ("witness deleted_drafts equal the batch units",
     lambda s: s.get("witness") is None
     or sorted(s["witness"]["deleted_drafts"])
     == sorted("_drafts/%s.md" % u for u in s["unit_order"])),
    ("witness target equals the state target",
     lambda s: s.get("witness") is None or s["witness"]["target"] == s["target"]),
    ("witness source paths equal the source files",
     lambda s: s.get("witness") is None
     or sorted(e["path"] for e in s["witness"]["source_files"])
     == sorted(s["source_files"])),
    ("witness requires every unit landed",
     lambda s: s.get("witness") is None or len(s["landed"]) == len(s["unit_order"])),
    ("initial_map matches its recorded digest (Git history of the state file is "
     "the immutability anchor a coordinated edit still cannot forge)",
     lambda s: hashlib.sha256(json.dumps(s["initial_map"], sort_keys=True)
                              .encode("utf-8")).hexdigest() == s["initial_map_sha256"]),
    ("a witness pins the state integrity digest",
     lambda s: s.get("witness") is None
     or s["integrity_sha256"] == s["witness"]["integrity_sha256"]),
)


def load_state(path):
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, "rb") as f:
            state = json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        return None, "state file unreadable: %s" % e
    if not isinstance(state, dict) or state.get("batch_state_schema") != 1:
        return None, "state file must be an object with batch_state_schema: 1"
    err = validate_state(state)
    if err:
        return None, "state file invalid: %s" % err
    return state, None


def save_state(path, state):
    con.atomic_write(path, json.dumps(state, indent=2, sort_keys=True) + "\n")


def assess(kdir, frag_dir, spec, state):
    """(report, error): everything --check verifies and --execute preconditions on.
    Read-only. report = {units, target, all_ids, sources, expected_create_sha,
    problems, notes, complete}."""
    slices = con.earned_slices(kdir)
    target, why = con.resolve_target(kdir, spec["target"], slices)
    if not target:
        return None, why
    units, err = classify(frag_dir, spec, state)
    if err:
        return None, err
    problems, notes = [], []
    for row in units:
        if row["state"] == "inconsistent":
            problems.append("%s: %s" % (row["unit"], row["detail"]))
        if row["state"] == "undistilled":
            problems.append("%s: create draft still carries the DRAFT banner" % row["unit"])
    ids_known = [r for r in units if r["ids"]]
    all_ids = [i for r in ids_known for i in r["ids"]]
    if len(all_ids) != len(set(all_ids)):
        seen, overlap = set(), set()
        for i in all_ids:
            (overlap if i in seen else seen).add(i)
        problems.append("unit manifests overlap: %s" % ", ".join(sorted(overlap)))
    if state and state.get("spec_sha256") != spec["_sha256"]:
        problems.append("state was recorded for a different spec (sha mismatch)")

    md, md_errors = con.active_md(frag_dir)
    for e in md_errors:
        problems.append(e)
    gate_error, gate_standing = con.damage_gate(frag_dir, md)
    for line in gate_standing:
        notes.append(line)
    if gate_error:
        problems.append(gate_error)

    alias2canon = df.load_units(frag_dir)
    canon_units = {alias2canon.get(r["unit"], r["unit"]): r for r in units}
    outstanding, where, status_of, unit_of = {}, {}, {}, {}
    for path in md:
        _env, deltas, _w = df.parse_fragment(path)
        for d in deltas:
            did = d.get("delta_id") or d.get("_header_id")
            where.setdefault(did, path)
            status_of.setdefault(did, d.get("status"))
            unit_of.setdefault(did, d.get("unit_id"))
            cu = alias2canon.get(d.get("unit_id"), d.get("unit_id"))
            if cu in canon_units and d.get("status") not in df.DISPOSED:
                outstanding.setdefault(cu, set()).add(did)
    for cu, row in canon_units.items():
        if row["ids"] is None:
            continue
        if state and row["state"] != "absent":
            base = state["units"].get(row["unit"])
            if base is None:
                problems.append("%s: missing from the state.units baseline" % row["unit"])
            elif row["ids"] != base:
                problems.append("%s: draft manifest %r != the initialized baseline %r -- "
                                "re-check, re-approve, and re-init deliberately"
                                % (row["unit"], row["ids"], base))
        foreign = sorted(i for i in row["ids"] if i in unit_of
                         and alias2canon.get(unit_of[i], unit_of[i]) != cu)
        if foreign:
            problems.append("%s: manifest id(s) belong to another unit: %s"
                            % (row["unit"], ", ".join(foreign)))
        disposed = sorted(i for i in row["ids"]
                          if status_of.get(i) in ("archived", "superseded"))
        if disposed:
            problems.append("%s: manifest id(s) already disposed and must not be "
                            "promoted: %s" % (row["unit"], ", ".join(disposed)))
        if row["state"] == "absent":
            left = sorted(outstanding.get(cu, set()))
            if left:
                problems.append("%s: draft consumed but outstanding delta(s) remain: %s"
                                % (row["unit"], ", ".join(left)))
            continue
        extra = sorted(outstanding.get(cu, set()) - set(row["ids"]))
        if extra:
            problems.append("%s: outstanding delta(s) NOT in its manifest: %s"
                            % (row["unit"], ", ".join(extra)))
        unseen = sorted(i for i in row["ids"] if i not in where)
        if unseen:
            problems.append("%s: manifest id(s) in no ACTIVE fragment -- the batch "
                            "witnesses cannot observe them (repair, or hand-finish "
                            "that unit per consolidate's own recovery): %s"
                            % (row["unit"], ", ".join(unseen)))

    create_row = units[0]
    expected_sha, create_body, ct = None, None, None
    if create_row.get("path"):
        info, err = parse_draft(create_row["path"], create_row["unit"])
        if err:
            return None, err
        create_body = info["body"]
        ct = con.create_text_from_draft(info["front"], info["body"])
        cb = ct.encode("utf-8")
        expected_sha = hashlib.sha256(cb).hexdigest()
        man_c, err_m = target_manifest(cb)
        if err_m:
            problems.append("create draft fails the target witness grammar: %s -- "
                            "use a two-space block-list consolidates" % err_m)
        elif man_c != create_row["ids"]:
            problems.append("create frontmatter consolidates block %r != its parsed "
                            "manifest %r -- use a two-space block-list consolidates"
                            % (man_c, create_row["ids"]))
        else:
            _dig_c, err_d = integrity_digest(cb)
            if err_d:
                problems.append("create draft fails the integrity-digest grammar: %s"
                                % err_d)
    for row, entry in [(units[0], spec["create"])] + list(zip(units[1:], spec["carriers"])):
        if row["role"] == "create":
            if row["state"] != "ready":
                continue
            _plan, err_p, _code = con.apply_preflight(kdir, frag_dir, row["unit"],
                                                      verbose=False)
        elif (row["state"] in ("fresh", "transitioned")
                and (create_row["state"] == "absent" or ct is not None)):
            dtext = None
            if row["state"] == "fresh":
                dtext, err_t = transitioned_text(read_bytes(row["path"]),
                                                 spec["target"], entry["landed_in"])
                if err_t:
                    problems.append("%s: transition projection: %s"
                                    % (row["unit"], err_t))
                    continue
                pinfo, err_t = parse_draft(row["path"], row["unit"], text=dtext)
                if err_t or pinfo["banners"] != 0 \
                        or pinfo["anchors"] != [entry["landed_in"]] \
                        or pinfo["mode"] != "update-existing" \
                        or pinfo["target"] != spec["target"]:
                    problems.append("%s: projected draft fails the post-transition "
                                    "contract (%s)" % (row["unit"],
                                                       err_t or "banner/anchor/"
                                                       "mode/target mismatch"))
                    continue
            override = ct if create_row["state"] != "absent" else None
            _plan, err_p, _code = con.apply_preflight(kdir, frag_dir, row["unit"],
                                                      target_text=override,
                                                      verbose=False, draft_text=dtext)
        else:
            continue
        if err_p:
            problems.append("%s: apply preflight: %s" % (row["unit"], err_p))
    target_raw = read_bytes(target) if os.path.exists(target) else None
    for row, entry in zip(units[1:], spec["carriers"]):
        label = entry["landed_in"]
        hay = create_body if create_body is not None else (
            target_raw.decode("utf-8", "replace") if target_raw is not None else None)
        if hay is None:
            problems.append("%s: no create draft and no target page to verify anchor %r against"
                            % (row["unit"], label))
        elif norm(label) not in norm(hay):
            problems.append("%s: anchor label not found (post-norm) in the %s: %r"
                            % (row["unit"], "create draft" if create_body is not None
                               else "target page", label))

    sources = None
    if all_ids and not any(r["ids"] is None for r in units):
        sources, _miss, err = source_files(frag_dir, all_ids)
        if err:
            problems.append(err)
    if sources is not None:
        snap_w, err_w = snapshot(frag_dir, sources)
        if err_w:
            problems.append("witness layer: %s" % err_w)
        elif flat(snap_w) is None:
            problems.append("witness layer: duplicate id across source files -- "
                            "the status map cannot key them")
    if state and sources is not None and sorted(state.get("source_files", [])) != sources:
        stated = state.get("source_files", [])
        if set(sources) - set(stated):
            problems.append("state source_files miss batch id home(s): %s"
                            % ", ".join(sorted(set(sources) - set(stated))))
        for rel in sorted(set(stated) - set(sources)):
            _p, _w, err2 = resolve_source(frag_dir, rel)
            if err2:
                problems.append("state source file: %s" % err2)

    if state and target_raw is not None:
        man_t, err_t = target_manifest(target_raw)
        if err_t:
            problems.append("target: %s" % err_t)
        else:
            for b in manifest_state_ok(man_t, state):
                problems.append("target: " + b)
    landed_states = {"absent"}
    complete = (all(r["state"] in landed_states for r in units)
                and target_raw is not None and not problems)
    if create_row["state"] == "ready" and target_raw is not None:
        if expected_sha == hashlib.sha256(target_raw).hexdigest():
            notes.append("target already byte-equals the expected create output "
                         "(prior partial apply; execute resumes idempotently)")
        else:
            problems.append("target already exists and does not equal the expected create "
                            "bytes: %s" % spec["target"])
    return {"units": units, "target": target, "all_ids": all_ids, "sources": sources,
            "expected_create_sha": expected_sha, "problems": problems, "notes": notes,
            "complete": complete}, None


def print_report(spec, rep, state):
    print("batch: target %s | %d unit(s) | %d id(s)"
          % (spec["target"], len(rep["units"]), len(rep["all_ids"])))
    for row in rep["units"]:
        print("  %-12s %-20s %s%s" % (row["role"], row["unit"], row["state"],
                                      ("  -- " + row["detail"]) if row["detail"] else ""))
    if rep["sources"] is not None:
        print("  source fragment file(s): %s" % ", ".join(rep["sources"]))
    if rep["expected_create_sha"]:
        print("  expected create sha256: %s" % rep["expected_create_sha"])
    if state:
        print("  state: %d unit(s) landed" % len(state.get("landed", [])))
    for n in rep["notes"]:
        print("  note: " + n)
    for p in rep["problems"]:
        print("  PROBLEM: " + p)


def check(kdir, frag_dir, spec, state_path):
    state, err = load_state(state_path)
    if err:
        return fail(err)
    rep, err = assess(kdir, frag_dir, spec, state)
    if err:
        return fail(err)
    print_report(spec, rep, state)
    if rep["complete"]:
        landed = {l["unit"] for l in (state or {}).get("landed", [])}
        missing = [r["unit"] for r in rep["units"] if r["unit"] not in landed]
        _witness, problems = final_verification(frag_dir, spec, state, rep["units"],
                                                rep["target"])
        if problems:
            for p in problems:
                print("  PROBLEM: " + p)
            print("verdict: NOT VERIFIED -- landed state does not survive re-verification")
            return 1
        if missing:
            print("verdict: disk state verifies; run --execute to record missing "
                  "landed record(s): %s" % ", ".join(missing))
            return 0
        if not state.get("witness"):
            print("verdict: disk state verifies; run --execute to record the "
                  "completion witness")
            return 0
        print("verdict: COMPLETE (all units landed; final state re-verified)")
        return 0
    if state and not rep["complete"]:
        snap, err = snapshot(frag_dir, state["source_files"])
        bad = [err] if err else projection_check(frag_dir, state, snap)
        if bad:
            for b in bad:
                print("  PROBLEM: " + b)
            print("verdict: NOT VERIFIED -- sources do not project to the "
                  "initialized expectation")
            return 1
    if rep["problems"]:
        print("verdict: NOT EXECUTABLE (%d problem(s) above)" % len(rep["problems"]))
        return 1
    fresh = [r["unit"] for r in rep["units"] if r["state"] == "fresh"]
    if fresh:
        print("verdict: EXECUTABLE after --transition (%s)" % ", ".join(fresh))
    else:
        print("verdict: EXECUTABLE from here")
    return 0


def transition(kdir, frag_dir, spec, state_path):
    state, err = load_state(state_path)
    if err:
        return fail(err)
    rep, err = assess(kdir, frag_dir, spec, state)
    if err:
        return fail(err)
    if rep["problems"]:
        print_report(spec, rep, state)
        return fail("refusing to transition -- %d problem(s); nothing mutated"
                    % len(rep["problems"]))
    edits = []
    for row, entry in zip(rep["units"][1:], spec["carriers"]):
        if row["state"] == "transitioned":
            print("already transitioned: %s" % row["unit"])
            continue
        if row["state"] != "fresh":
            return fail("%s is %s, not fresh; nothing mutated" % (row["unit"], row["state"]))
        text, err = transitioned_text(read_bytes(row["path"]), spec["target"],
                                      entry["landed_in"])
        if err:
            return fail("%s: %s; nothing mutated" % (row["unit"], err))
        edits.append((row, text))
    for row, text in edits:
        con.atomic_write(row["path"], text)
        info, err = parse_draft(row["path"], row["unit"])
        entry = next(c for c in spec["carriers"] if c["unit"] == row["unit"])
        ok = (not err and info["banners"] == 0 and info["anchors"] == [entry["landed_in"]]
              and info["mode"] == "update-existing" and info["target"] == spec["target"])
        if not ok:
            return fail("%s: transition did not converge (%s) -- inspect the draft"
                        % (row["unit"], err or "post-state mismatch"))
        print("transitioned: %s -> %s (update-existing, anchored)"
              % (row["unit"], spec["target"]))
    if not edits:
        print("nothing to transition")
    return 0


def transitioned_text(raw, target_rel, label):
    """(text, error): the ONE carrier transition transform -- --transition writes
    with it, and assessment PROJECTS a still-fresh carrier through the shared apply
    preflight with it, so the executable verdict covers the post-transition shape
    before anything mutates."""
    lines, err = split_keepends(raw)
    if err:
        return None, err
    span = frontmatter_span(lines)
    if not span:
        return None, "no terminated frontmatter"
    tgt_at = [i for i in range(1, span[1])
              if re.match(r"^target:", lines[i].rstrip("\r\n"))]
    mode_at = [i for i in range(1, span[1])
               if re.match(r"^apply_mode:", lines[i].rstrip("\r\n"))]
    ban_at = [i for i in range(span[1] + 1, len(lines))
              if lines[i].rstrip("\r\n").lstrip().startswith(BANNER_PREFIX)]
    if len(tgt_at) != 1 or len(mode_at) != 1 or len(ban_at) != 1:
        return None, ("expected exactly one target/apply_mode/banner line "
                      "(got %d/%d/%d)" % (len(tgt_at), len(mode_at), len(ban_at)))

    def rewrite(i, content):
        eol = lines[i][len(lines[i].rstrip("\r\n")):]
        lines[i] = content + eol
    rewrite(tgt_at[0], "target: %s" % target_rel)
    rewrite(mode_at[0], "apply_mode: update-existing")
    rewrite(ban_at[0], '- landed in: "%s"' % label)
    return "".join(lines), None


def landed_ok(target, row, state, cur_map, exp_man):
    """Verify a draft-consumed unit against disk -- the plan's resume rule 'exact
    expected post-state plus missing draft means complete'. `exp_man` is the expected
    manifest through and including this unit. On a create whose landing predates any
    recorded integrity digest (crash between apply and state save), the create-bytes
    sha is the witness and the digest is computed and stored here."""
    fm = flat(cur_map)
    for i in row["ids"]:
        if fm.get(i, [None, None])[1] != "consolidated":
            return "unit %s id %s does not read consolidated" % (row["unit"], i)
    if not os.path.exists(target):
        return "unit %s recorded landed but the target page is missing" % row["unit"]
    raw = read_bytes(target)
    man, err = target_manifest(raw)
    if err:
        return err
    bad = manifest_state_ok(man, state)
    if bad:
        return "; ".join(bad)
    if man[:len(exp_man)] != exp_man:
        return ("target manifest prefix %r does not match the expected landed sequence %r"
                % (man[:len(exp_man)], exp_man))
    dig, err = integrity_digest(raw)
    if err:
        return err
    if state.get("integrity_sha256") is None:
        if row["role"] != "create":
            return "no integrity digest in state but a carrier is recorded landed"
        if man == exp_man and hashlib.sha256(raw).hexdigest() != state["expected_create_sha256"]:
            return ("landed create does not byte-equal the derived expectation "
                    "(sha mismatch) -- stop for an explicit repair decision")
        state["integrity_sha256"] = dig
    elif dig != state["integrity_sha256"]:
        return ("integrity digest drifted from state (%s != %s)"
                % (dig, state["integrity_sha256"]))
    return None


def init_state(kdir, frag_dir, spec, state_path):
    """--init: the one deliberate state mutation outside applies. Written only while
    every draft is still present, so --execute can require the file and refuse to
    create anything -- a downstream apply refusal then mutates nothing."""
    if os.path.exists(state_path):
        return fail("state file already exists: %s -- --init never overwrites "
                    "(delete it deliberately if the batch is being restarted)" % state_path)
    rep, err = assess(kdir, frag_dir, spec, None)
    if err:
        return fail(err)
    print_report(spec, rep, None)
    if rep["problems"]:
        return fail("refusing to init -- %d problem(s); nothing written" % len(rep["problems"]))
    fresh = [r["unit"] for r in rep["units"] if r["state"] == "fresh"]
    if fresh:
        return fail("carrier draft(s) not transitioned: %s -- run --transition first; "
                    "nothing written" % ", ".join(fresh))
    if any(r["state"] == "absent" for r in rep["units"]):
        return fail("draft(s) already consumed -- state must be initialized while "
                    "every draft is present; nothing written")
    snap0, err = snapshot(frag_dir, rep["sources"])
    if err:
        return fail(err + "; nothing written")
    batch_ids = {i for r in rep["units"] for i in r["ids"]}
    fe = {}
    for rel in rep["sources"]:
        path, _w, err = resolve_source(frag_dir, rel)
        if err:
            return fail(err + "; nothing written")
        remaining = [i for i, val in snap0[rel]["deltas"].items()
                     if i in batch_ids and val[1] != "consolidated"]
        fe[rel] = projected_sha(path, remaining)
    state = {"batch_state_schema": 1, "spec_sha256": spec["_sha256"],
             "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
             "target": spec["target"],
             "units": {r["unit"]: r["ids"] for r in rep["units"]},
             "unit_order": [r["unit"] for r in rep["units"]],
             "source_files": rep["sources"],
             "expected_create_sha256": rep["expected_create_sha"],
             "initial_map": snap0, "last_map": snap0, "final_expected": fe,
             "initial_map_sha256": hashlib.sha256(
                 json.dumps(snap0, sort_keys=True).encode("utf-8")).hexdigest(),
             "integrity_sha256": None, "landed": []}
    save_state(state_path, state)
    print("state initialized: %s" % state_path)
    return 0


def execute(kdir, frag_dir, spec, state_path):
    state, err = load_state(state_path)
    if err:
        return fail(err)
    if state is None:
        return fail("no state file at %s -- run --check, get approval, then --init "
                    "before --execute (execute never creates state)" % state_path)
    rep, err = assess(kdir, frag_dir, spec, state)
    if err:
        return fail(err)
    print_report(spec, rep, state)
    if rep["problems"]:
        return fail("refusing to execute -- %d problem(s); nothing mutated" % len(rep["problems"]))
    fresh = [r["unit"] for r in rep["units"] if r["state"] == "fresh"]
    if fresh:
        return fail("carrier draft(s) not transitioned: %s -- run --transition; "
                    "nothing mutated" % ", ".join(fresh))
    if state.get("unit_order") != [r["unit"] for r in rep["units"]]:
        return fail("state unit order does not match the spec; nothing mutated")

    target = rep["target"]
    if state.get("witness") is not None:
        _w, problems = final_verification(frag_dir, spec, state, rep["units"], target)
        if problems:
            return fail("recorded completion witness does not verify: %s -- no "
                        "state write" % " | ".join(problems))
        print("BATCH COMPLETE (recorded witness verified and preserved; no state write)")
        print(json.dumps(state["witness"], indent=2, sort_keys=True))
        return 0

    exp_man = []
    batch_ids = {i for r in rep["units"] for i in r["ids"]}
    for row in rep["units"]:
        exp_man = exp_man + [i for i in row["ids"] if i not in exp_man]
        cur, err = snapshot(frag_dir, state["source_files"])
        if err:
            return fail("witness halt (%s): %s" % (row["unit"], err))
        if row["state"] == "absent":
            drift = map_diff(state["last_map"], cur, expect_changed=batch_ids,
                             expect_to="consolidated", allow_partial=True)
            drift += projection_check(frag_dir, state, cur)
            if drift:
                return fail("out-of-band drift at landed %s: %s -- stop for an "
                            "explicit repair decision" % (row["unit"], " | ".join(drift)))
            pre_int = state.get("integrity_sha256")
            err = landed_ok(target, row, state, cur, exp_man)
            if err:
                return fail("witness halt: %s -- stop for an explicit repair decision"
                            % err)
            changed = state.get("integrity_sha256") != pre_int
            if not any(l["unit"] == row["unit"] for l in state["landed"]):
                state["landed"].append({"unit": row["unit"], "ids": row["ids"],
                                        "at_utc": "verified-post-hoc"})
                changed = True
            if state["last_map"] != cur:
                state["last_map"] = cur
                changed = True
            if changed:
                save_state(state_path, state)
            print("landed (verified): %s" % row["unit"])
            continue

        prev = state["last_map"]
        drift = map_diff(prev, cur, expect_changed=batch_ids,
                         expect_to="consolidated", allow_partial=True)
        drift += projection_check(frag_dir, state, cur)
        if drift:
            return fail("out-of-band drift since the last recorded step (%s): %s"
                        % (row["unit"], " | ".join(drift)))
        got, drifted = verify_pins()
        if drifted:
            return fail("tool baseline drifted before apply (%s): %s"
                        % (row["unit"], ", ".join(drifted)))
        holding, pending_flips = {}, {}
        for rel in state["source_files"]:
            if set(cur[rel]["deltas"]) & set(row["ids"]):
                path, _w, err = resolve_source(frag_dir, rel)
                if err:
                    return fail("witness halt (%s): %s" % (row["unit"], err))
                holding[rel] = read_bytes(path)
                pending_flips[rel] = sum(
                    1 for i in row["ids"]
                    if cur[rel]["deltas"].get(i, [None, None, None])[1] != "consolidated")

        expected = None
        if row["role"] == "create":
            info, err = parse_draft(row["path"], row["unit"])
            if err:
                return fail(err)
            expected = con.create_text_from_draft(info["front"], info["body"]).encode("utf-8")
            if hashlib.sha256(expected).hexdigest() != state["expected_create_sha256"]:
                return fail("create draft changed since state init (expected sha "
                            "mismatch) -- re-check and re-approve; nothing mutated")
        else:
            raw0 = read_bytes(target)
            pre_man, err = target_manifest(raw0)
            if err:
                return fail(err)
            bad = manifest_state_ok(pre_man, state)
            if bad:
                return fail("target manifest invalid before %s: %s -- stop for an "
                            "explicit repair decision" % (row["unit"], "; ".join(bad)))
            pre_dig, err = integrity_digest(raw0)
            if err:
                return fail(err)
            if pre_dig != state["integrity_sha256"]:
                return fail("integrity digest mismatch before %s: %s != %s"
                            % (row["unit"], pre_dig, state["integrity_sha256"]))

        print("-- apply: %s (%s) --" % (row["unit"], row["role"]))
        rc = con.apply(kdir, frag_dir, row["unit"])
        if rc != 0:
            return fail("consolidate.apply exited %d for %s -- draft is the recovery "
                        "anchor; state not advanced" % (rc, row["unit"]))

        post, err = snapshot(frag_dir, state["source_files"])
        if err:
            return fail("witness halt after %s: %s" % (row["unit"], err))
        bad = map_diff(cur, post, expect_changed=set(row["ids"]), expect_to="consolidated")
        if bad:
            return fail("status-map witness failed after %s: %s" % (row["unit"], " | ".join(bad)))
        for rel in sorted(holding):
            path, _w, err = resolve_source(frag_dir, rel)
            if err:
                return fail("witness halt after %s: %s" % (row["unit"], err))
            bad = lines_changed_ok(holding[rel], read_bytes(path), pending_flips[rel])
            if bad:
                return fail("positional byte witness failed after %s in %s: %s"
                            % (row["unit"], rel, " | ".join(bad)))
        bad = projection_check(frag_dir, state, post)
        if bad:
            return fail("projection witness failed after %s: %s"
                        % (row["unit"], " | ".join(bad)))

        raw = read_bytes(target)
        if row["role"] == "create":
            if raw != expected:
                return fail("create output does not byte-equal the derived expectation "
                            "(target %s) -- diagnose before any reconstruction" % spec["target"])
            dig, err = integrity_digest(raw)
            if err:
                return fail(err)
            state["integrity_sha256"] = dig
        else:
            man, err = target_manifest(raw)
            if err:
                return fail(err)
            if man[:len(pre_man)] != pre_man or man[len(pre_man):] != [
                    i for i in row["ids"] if i not in pre_man]:
                return fail("manifest growth wrong after %s: %r -> %r (unit ids %r)"
                            % (row["unit"], pre_man, man, row["ids"]))
            bad = manifest_state_ok(man, state)
            if bad:
                return fail("target manifest invalid after %s: %s"
                            % (row["unit"], "; ".join(bad)))
            dig, err = integrity_digest(raw)
            if err:
                return fail(err)
            if dig != state["integrity_sha256"]:
                return fail("integrity digest changed across %s apply: %s != %s -- the "
                            "carrier touched non-manifest bytes" % (row["unit"], dig,
                                                                    state["integrity_sha256"]))
        if os.path.exists(os.path.join(frag_dir, "_drafts", row["unit"] + ".md")):
            return fail("draft still present after successful apply of %s" % row["unit"])

        state["last_map"] = post
        state["landed"].append({"unit": row["unit"],
                                "at_utc": datetime.datetime.now(
                                    datetime.timezone.utc).isoformat(),
                                "ids": row["ids"]})
        save_state(state_path, state)
        print("landed: %s (+%d id(s))" % (row["unit"], len(row["ids"])))

    witness, problems = final_verification(frag_dir, spec, state, rep["units"], target)
    if problems:
        return fail("final verification failed: %s" % " | ".join(problems))
    state["witness"] = witness
    save_state(state_path, state)
    print("BATCH COMPLETE")
    print(json.dumps(witness, indent=2, sort_keys=True))
    return 0


def final_verification(frag_dir, spec, state, units, target):
    """(witness, problems): the whole-batch post-state proof, one mode -- the
    initial-to-final map comparison always runs, and a recorded completion witness
    is always verified field-by-field (and never minted here). Used by --execute
    (before the unit loop when a witness exists, and at the end to mint one) and
    by --check on a fully-landed batch."""
    problems = []
    expected_man = [i for r in units for i in r["ids"]]
    if not os.path.exists(target):
        return None, ["target page is missing: %s" % spec["target"]]
    raw = read_bytes(target)
    man, err = target_manifest(raw)
    if err:
        return None, [err]
    if man != expected_man:
        problems.append("final manifest %r != expected batch order %r" % (man, expected_man))
    dig, err = integrity_digest(raw)
    if err:
        return None, [err]
    prior = state.get("witness")
    if dig != state.get("integrity_sha256"):
        crash_tolerated = (prior is None
                          and state.get("integrity_sha256") is None
                          and man == expected_man
                          and hashlib.sha256(raw).hexdigest()
                          == state.get("expected_create_sha256"))
        if not crash_tolerated:
            problems.append("integrity digest %s != state %s"
                            % (dig, state.get("integrity_sha256")))
    unverified = con.manifest_unverified(frag_dir, expected_man)
    if unverified:
        problems.append("whole-disk verification failed for: %s" % ", ".join(unverified))
    still = [r["unit"] for r in units
             if os.path.exists(os.path.join(frag_dir, "_drafts", r["unit"] + ".md"))]
    if still:
        problems.append("draft(s) still present: %s" % ", ".join(still))
    final_map, err = snapshot(frag_dir, state["source_files"])
    if err:
        return None, [err]
    problems += projection_check(frag_dir, state, final_map)
    foreign = map_diff(state["initial_map"], final_map,
                       expect_changed=set(expected_man), expect_to="consolidated")
    if foreign:
        problems.append("co-tenant witness failed vs the initial map: %s"
                        % " | ".join(foreign))
    if prior:
        if hashlib.sha256(raw).hexdigest() != prior.get("target_sha256"):
            problems.append("target bytes changed since the completion witness -- "
                            "verify through Git history, not this tool")
        if prior.get("target") != spec["target"]:
            problems.append("witness target %r != spec target %r"
                            % (prior.get("target"), spec["target"]))
        if prior.get("integrity_sha256") != dig:
            problems.append("witness integrity_sha256 does not match the rederived "
                            "digest")
        if prior.get("manifest") != man:
            problems.append("witness manifest does not match the rederived target "
                            "manifest")
        expected_drafts = sorted("_drafts/%s.md" % r["unit"] for r in units)
        if sorted(prior.get("deleted_drafts", [])) != expected_drafts:
            problems.append("witness deleted_drafts does not match the batch units")
        wit_paths = [e.get("path") for e in prior.get("source_files", [])]
        if len(wit_paths) != len(set(wit_paths)):
            problems.append("witness source_files repeats a path")
        if state.get("last_map") != final_map:
            problems.append("state.last_map does not equal the re-derived final map")
        recorded = {e.get("path"): e for e in prior.get("source_files", [])}
        if sorted(recorded) != sorted(final_map):
            problems.append("source file set differs from the completion witness")
        for rel in sorted(set(recorded) & set(final_map)):
            for key in ("sha256", "where"):
                if recorded[rel].get(key) != final_map[rel].get(key):
                    problems.append("source %s %s changed since the completion witness "
                                    "-- verify through Git history, not this tool"
                                    % (rel, key))
    if problems:
        return None, problems
    witness = {"batch_witness_schema": 1, "target": spec["target"],
               "target_sha256": hashlib.sha256(raw).hexdigest(),
               "integrity_sha256": state["integrity_sha256"],
               "manifest": man,
               "source_files": [{"path": rel, "where": final_map[rel]["where"],
                                 "sha256": final_map[rel]["sha256"]}
                                for rel in sorted(final_map)],
               "deleted_drafts": ["_drafts/%s.md" % r["unit"] for r in units],
               "completed_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    return witness, []


def cmd_map(frag_dir, files):
    rels = []
    for f in files:
        p = os.path.abspath(f)
        if not os.path.exists(p):
            return fail("no such file: %s" % f, 2)
        rels.append(os.path.relpath(p, frag_dir).replace("\\", "/"))
    snap, err = snapshot(frag_dir, rels)
    if err:
        return fail(err)
    print(json.dumps({"batch_promote_map": 1, "files": snap}, indent=2, sort_keys=True))
    return 0


def cmd_diff(before_path, after_path, expect_changed, expect_to):
    maps = []
    for p in (before_path, after_path):
        try:
            with open(p, "rb") as f:
                doc = json.loads(f.read().decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as e:
            return fail("cannot read map %s: %s" % (p, e), 2)
        if not isinstance(doc, dict) or doc.get("batch_promote_map") != 1:
            return fail("%s is not a --map snapshot" % p, 2)
        err = snap_shape_error(doc.get("files"), "%s files" % p)
        if err:
            return fail(err, 2)
        maps.append(doc["files"])
    if sorted(maps[0]) != sorted(maps[1]):
        return fail("snapshots cover different files: %r vs %r"
                    % (sorted(maps[0]), sorted(maps[1])))
    bad = map_diff(maps[0], maps[1], expect_changed, expect_to,
                   expected_content_stable=False)
    if bad:
        for b in bad:
            print("  VIOLATION: " + b)
        return fail("%d violation(s)" % len(bad))
    if expect_changed:
        print("diff OK: %d expected id(s) read %r; everything else stable"
              % (len(expect_changed), expect_to))
    else:
        print("diff OK: no status changed")
    return 0


def main():
    argv = sys.argv[1:]
    modes = ("--check", "--transition", "--init", "--execute", "--map", "--diff")
    flags, pos, i = {}, [], 0
    while i < len(argv):
        a = argv[i]
        if a in ("--spec", "--state", "--expect-changed", "--expect-to"):
            if i + 1 >= len(argv):
                print(USAGE, file=sys.stderr)
                return 2
            i += 1
            flags[a] = argv[i]
        elif a in modes:
            flags[a] = True
        elif a.startswith("--"):
            print("batch-promote: unrecognized argument %r" % a, file=sys.stderr)
            print(USAGE, file=sys.stderr)
            return 2
        else:
            pos.append(a)
        i += 1
    mode = [m for m in modes if m in flags]
    if len(mode) != 1 or not pos:
        print(USAGE, file=sys.stderr)
        return 2
    mode = mode[0]

    got, drifted = verify_pins()
    print("batch-promote: self sha256=%s" % sha256_file(os.path.abspath(__file__)),
          file=sys.stderr)
    for fn in sorted(got):
        print("batch-promote: %s sha256=%s [%s]"
              % (fn, got[fn], "DRIFTED" if fn in drifted else "pinned"),
              file=sys.stderr)
    if drifted:
        return fail("tool baseline drift: %s changed since the reviewed pin -- "
                    "re-review and re-pin before any batch operation" % ", ".join(drifted))
    load_tools()

    frag_dir = df.find_fragments(pos[0])
    if not frag_dir:
        return fail("no _fragments/ directory under %s" % pos[0], 2)
    kdir = os.path.dirname(frag_dir)

    if mode == "--map":
        if len(pos) < 2:
            return fail("--map needs at least one fragment file", 2)
        return cmd_map(frag_dir, pos[1:])
    if mode == "--diff":
        if len(pos) != 3:
            return fail("--diff needs exactly <before.json> <after.json>", 2)
        expect = set()
        if flags.get("--expect-changed"):
            expect = {x for x in flags["--expect-changed"].split(",") if x}
        if expect and not flags.get("--expect-to"):
            return fail("--expect-changed requires --expect-to <status>", 2)
        return cmd_diff(pos[1], pos[2], expect, flags.get("--expect-to"))

    if len(pos) != 1 or "--spec" not in flags:
        print(USAGE, file=sys.stderr)
        return 2
    spec, err = load_spec(flags["--spec"])
    if err:
        return fail(err, 2)
    state_path = flags.get("--state") or flags["--spec"] + ".state.json"
    if mode == "--check":
        return check(kdir, frag_dir, spec, state_path)
    if mode == "--transition":
        return transition(kdir, frag_dir, spec, state_path)
    if mode == "--init":
        return init_state(kdir, frag_dir, spec, state_path)
    return execute(kdir, frag_dir, spec, state_path)


if __name__ == "__main__":
    sys.exit(main())
