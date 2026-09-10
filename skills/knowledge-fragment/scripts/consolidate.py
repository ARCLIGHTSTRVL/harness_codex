#!/usr/bin/env python3
"""consolidate: draft/apply promotion of knowledge-fragment deltas into curated knowledge/.

The WRITE side of the knowledge-fragment staging tier (spec:
dev-setup-codex/specs/knowledge-fragment.md §11-§12). deltas-for.py is the READ
side and stays read-only; every fragment/curated mutation lives here, behind two
strictly separated modes:

  --draft   read-only w.r.t. fragments and curated knowledge/. Gathers a unit's
            unconsolidated deltas, discovers the TARGET KB's earned slices from
            disk (SCHEMA-driven routing -- never assumes journal/+synthesis/
            exist; the harness-meta KB is comparisons/-only), and writes a
            reviewable draft to knowledge/_fragments/_drafts/<unit>.md
            (kb-lint-excluded). The draft frontmatter IS the apply contract:
            target, apply_mode, consolidates manifest. Wikilink candidates are
            seeded from the deltas' optional `informed_by` + the unit's units.yml
            `parent` (provenance instruments, spec §6).
  --apply   the promotion gate's mechanical half. Requires the agent to have
            distilled the draft (the "> DRAFT:" banner line must be gone) and
            the user to have approved it. apply_mode create: atomically writes
            the target page (machine keys stripped; `consolidates:` kept as
            provenance back to the deltas). apply_mode update-existing: the
            agent already merged the content into the existing target page by
            hand; the bookkeeping atomically merges the manifest into the
            target page's `consolidates:`. Both: manifest deltas -> status:
            consolidated using atomic per-file replacement, fully-DISPOSED
            fragments move to _archive/, and the draft remains the recovery
            anchor until every write/archive succeeds. A rerun recognizes an
            identical promoted target or already-recorded manifest and resumes
            idempotently. Remaining SEMANTIC steps are printed (index entry,
            log line, wiki refresh via wiki-pages-for, kb-lint).

SINGLE WRITER, NO LOCK -- the assumption every guarantee below is conditioned on. This
module takes no lock and cannot: the dominant writer of a fragment file is an agent
appending deltas through an editor, per the skill, and that path would never acquire one.
A lock here would exclude only this script -- the one writer already serial -- while
reading as mutual exclusion. So every check here is a check-then-act: it proves the state
it READ, and the window to the matching write is narrowed, never closed. Claims of the
form "this makes the window irrelevant" were written twice in this module and both were
false (Codex Mode 3 rounds 2-3). Under a concurrent writer, read the guarantees as
"verified immediately before", not "true at exit".

Refusals are PREFLIGHTED -- banner present, manifest drift (unknown / duplicate /
foreign-unit ids), unconfined or conflicting targets, missing slice, unflippable
manifest ids, archive collision, an id naming a delta in BOTH an active fragment and
_archive/ -- so a refusal mutates NOTHING. That last one is an IDENTITY check, not a
status one: two `consolidated` copies of an id still mean the promoted page's
`consolidates:` names two different deltas. Its one exemption is a prior append proven by
content (`fragment_already_appended`), because that overlap is a crashed run resuming. Snapshot tests hold
that line and are only ever as strong as their fixtures: the archive-collision
snapshot passed while a fragment carrying one `superseded` delta walked through the
preflight and refused after the page write, because no fixture held a terminal
non-`consolidated` delta for the two predicates to disagree over. One archive
collision is legitimate and handled: a session that continued AFTER its fragment
file was archived recreates the same-named file; if the existing archive is the
same session and the delta-id sets are disjoint, apply APPENDS the new delta
sections to it instead of refusing (anything else still refuses). Known
limitation (deferred, by choice): the draft->apply window is not content-hashed;
if fragments changed meaningfully after drafting, re-run --draft --force and
re-review rather than trusting an old draft.

Exit: 0 success; 1 refusal (nothing mutated) or post-write issue (message says
which); 2 usage error.
"""
import datetime
import importlib.util
import os
import re
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("deltas_for", os.path.join(HERE, "deltas-for.py"))
df = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(df)

BANNER_PREFIX = "> DRAFT:"
BANNER = (BANNER_PREFIX + " distill into full-fidelity prose (2+3 layers), add >=2 "
          "[[wikilinks]], recompute numbers from raw, adjust target/apply_mode, prune the "
          "consolidates manifest if excluding deltas, REMOVE THIS LINE, then run --apply.")
MACHINE_KEYS = ("consolidation_draft", "unit", "target", "apply_mode")
TYPE_BY_SLICE = {"journal": "journal", "synthesis": "synthesis",
                 "comparisons": "comparison", "queries": "query"}
KIND_ORDER = ("decision", "finding", "rejection", "risk",
              "constraint", "open_question", "followup")
USAGE = ("usage: python consolidate.py <knowledge|_fragments dir> <unit_id> --draft [--force]\n"
         "       python consolidate.py <knowledge|_fragments dir> <unit_id> --apply")


def fail(msg, code=1):
    print("consolidate: " + msg, file=sys.stderr)
    return code


def atomic_write(path, text):
    """Durably replace one text file; an interruption never truncates the target."""
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".%s." % os.path.basename(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def gather(frag_dir, canon, alias2canon):
    """All OUTSTANDING deltas of the unit, chronological. Mirrors deltas-for
    (skip every terminal disposition -- consolidated/archived/superseded; _archive/
    and _drafts/ excluded; warnings surfaced). An archived delta was reviewed and
    deliberately not promoted, and a superseded one would publish stale content,
    so neither may be pulled back into a draft."""
    md = []
    for root, dirs, files in os.walk(frag_dir):
        dirs[:] = [d for d in dirs if d not in ("_archive", "_drafts")]
        md += [os.path.join(root, f) for f in files if f.endswith(".md")]
    hits, warnings = [], []
    for path in sorted(md):
        env, deltas, warns = df.parse_fragment(path)
        df.warn_envelope(env, path)
        warnings += warns
        for d in deltas:
            if alias2canon.get(d.get("unit_id"), d.get("unit_id")) != canon:
                continue
            if d.get("status") in df.DISPOSED:
                continue
            d["_path"] = path
            hits.append(d)
    hits.sort(key=lambda d: d.get("created_at", ""))
    return hits, warnings


def earned_slices(kdir):
    """Curated slice dirs that EXIST on disk -- the SCHEMA-driven routing input.
    (`_*` is meta/staging, `raw/` is L1 sources; neither is a consolidation target.)"""
    out = []
    for d in sorted(os.listdir(kdir)):
        if d.startswith("_") or d == "raw":
            continue
        if os.path.isdir(os.path.join(kdir, d)):
            out.append(d)
    return out


def resolve_target(kdir, target_rel, slices):
    """(abs_target, error). Confine an edited `target:` inside kdir under an earned
    slice -- the draft frontmatter is agent/user-edited text, so it gets the same
    distrust as any input (Codex review: path confinement)."""
    if (not target_rel or "\\" in target_rel or target_rel.startswith("/")
            or re.match(r"^[A-Za-z]:", target_rel)):
        return None, ("target '%s' must be a relative /-separated path inside knowledge/"
                      % target_rel)
    parts = target_rel.split("/")
    if len(parts) < 2 or any(p in ("", ".", "..") for p in parts):
        return None, ("target '%s' must be <slice>/<page>.md with no empty/./.. segments"
                      % target_rel)
    if parts[0] not in slices:
        return None, ("target slice '%s' not earned (on disk: %s) -- slices are earned: "
                      "create the dir deliberately or re-route"
                      % (parts[0], ", ".join(slices) or "none"))
    target = os.path.join(kdir, *parts)
    # Confinement must be resolved, not lexical. `abspath` only normalizes the STRING,
    # so a symlinked slice dir (`knowledge/comparisons` -> anywhere) satisfied it while
    # the write landed outside knowledge/ -- reproduced, exit 0, no warning. `realpath`
    # follows the links, and resolving a not-yet-existing leaf still resolves the
    # existing parents, which is where a redirect can hide.
    real_k, real_t = os.path.realpath(kdir), os.path.realpath(target)
    if os.path.commonpath([real_t, real_k]) != real_k:
        return None, ("target '%s' escapes the knowledge dir once symlinks are resolved "
                      "(resolves to '%s')" % (target_rel, real_t))
    return target, None


def route(kdir, canon, slices):
    """(target_rel, apply_mode, candidate_note). Exact page-stem match => update-existing;
    a stem-prefix relative => suggested in a note; default create in comparisons/ (ADR
    shape suits decision-heavy units) or the first earned slice."""
    candidate = None
    for s in slices:
        for fn in sorted(os.listdir(os.path.join(kdir, s))):
            if not fn.endswith(".md"):
                continue
            stem = fn[:-3]
            rel = s + "/" + fn
            if stem == canon:
                return rel, "update-existing", None
            if (canon.startswith(stem) or stem.startswith(canon)) and not candidate:
                candidate = rel
    default_slice = "comparisons" if "comparisons" in slices else slices[0]
    return default_slice + "/" + canon + ".md", "create", candidate


def draft(kdir, frag_dir, canon, query, hits, force):
    drafts_dir = os.path.join(frag_dir, "_drafts")
    out_path = os.path.join(drafts_dir, canon + ".md")
    if os.path.exists(out_path) and not force:
        return fail("draft already exists: %s (it may carry agent edits -- delete it or pass --force)"
                    % out_path)
    slices = earned_slices(kdir)
    if not slices:
        return fail("no earned slices under %s -- create one deliberately (e.g. comparisons/) first"
                    % kdir)
    target, mode, candidate = route(kdir, canon, slices)
    today = datetime.date.today().isoformat()
    created = (hits[0].get("created_at") or today)[:10]
    provisional = [d for d in hits if d.get("status") == "provisional"]

    lines = ["---",
             "consolidation_draft: 1",
             "unit: %s" % canon,
             "target: %s" % target,
             "apply_mode: %s" % mode,
             "consolidates:"]
    lines += ["  - %s" % (d.get("delta_id") or d.get("_header_id")) for d in hits]
    lines += ["title: %s" % canon,
              "created: %s" % created,
              "updated: %s" % today,
              "type: %s" % TYPE_BY_SLICE.get(target.split("/", 1)[0], "TODO"),
              "tags: []          # fill from knowledge/SCHEMA.md taxonomy",
              "sources: []",
              "---",
              "",
              BANNER,
              "",
              "# %s -- consolidation draft" % canon,
              "",
              "Routing (earned slices on disk: %s): %s -> `%s` (%s)."
              % (", ".join(slices), "recommended" if mode == "create" else "existing page",
                 target, mode)]
    if candidate:
        lines.append("Candidate existing page `%s` -- consider `apply_mode: update-existing` "
                     "with `target: %s`." % (candidate, candidate))
    if provisional:
        lines += ["",
                  "PROVISIONAL (%d): %s -- provenance incomplete; keep in the manifest only if approved."
                  % (len(provisional),
                     ", ".join((d.get("delta_id") or d.get("_header_id")) for d in provisional))]
    # Spec §8 prompt, on the same METADATA proxy `--debt` uses: it counts the `kind`
    # field and never reads a body, so it can only ask a question, not assert an
    # absence. The page about to be written is permanent, which is why the question is
    # worth asking here even though the signal is weak.
    problems = [d for d in hits if d.get("kind") in df.PROBLEM_KINDS]
    rejections = [d for d in hits if d.get("kind") == "rejection"]
    if not problems:
        lines += ["",
                  "NO DELTAS TYPED risk|open_question|followup (spec 8, metadata only):"
                  " 0 of %d. This counts the kind FIELD and has not read the bodies, so it"
                  " may be wrong -- but if it is right, the promoted page will state what was"
                  " decided and nothing about what stays weak. Check the bodies; then either"
                  " capture what remains open or say plainly in the page that nothing does."
                  % len(hits)]
    if not rejections:
        lines.append("NO DELTAS TYPED rejection: no alternative is RECORDED AS SUCH as"
                     " considered-and-dropped (again, the field, not the prose). If"
                     " alternatives were weighed, check the page does not lose why-not.")

    inf = sorted({r for d in hits for r in df.informed_refs(d)})
    parent = df.unit_parents(frag_dir).get(canon)
    if parent:                                  # canonicalize an alias value (Codex m)
        parent = df.load_units(frag_dir).get(parent, parent)
    # guidance text carries NO [[..]] syntax (Codex M: this section is not banner-gated,
    # so a literal wikilink here could survive into the promoted page)
    lines += ["", "## wikilink candidates (seed the required >=2 wikilinks)"]
    lines += ["- %s" % r for r in inf]
    if parent:
        ppage = next((s + "/" + parent + ".md" for s in slices
                      if os.path.exists(os.path.join(kdir, s, parent + ".md"))), None)
        lines += ["- %s" % parent,
                  "  (parent unit%s)" % ("; promoted page: %s" % ppage
                                         if ppage else "; no promoted page yet")]
    if not inf and not parent:
        lines.append("(none -- informed_by unfilled and no units.yml parent; record the "
                     "orientation set on the unit's first delta next time)")

    by_kind = {}
    for d in hits:
        by_kind.setdefault(d.get("kind", "?"), []).append(d)
    for k in KIND_ORDER + tuple(sorted(set(by_kind) - set(KIND_ORDER))):
        if k not in by_kind:
            continue
        lines += ["", "## %s" % k]
        for d in by_kind[k]:
            did = d.get("delta_id") or d.get("_header_id")
            lines += ["",
                      "### %s -- %s" % (did, d.get("summary", "")),
                      "(%s, %s)" % (d.get("status", "?"), d.get("created_at", "?"))]
            if d.get("_body"):
                lines += ["", d["_body"]]
            ev = d.get("evidence") or []
            if ev:
                lines.append("")
                lines += ["- evidence: %s" % item for item in ev]

    refs = [(d.get("delta_id") or d.get("_header_id"), r) for d in hits for r in df.code_refs(d)]
    lines += ["", "## wiki refresh candidates"]
    if refs:
        lines += ["- %s  (from %s)" % (r, did) for did, r in refs]
        lines.append("(feed to wiki-pages-for at apply; no wiki/ in the project => graceful no-op)")
    else:
        lines.append("(none -- no type:code evidence in this unit)")

    os.makedirs(drafts_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("draft written: %s" % out_path)
    print("  unit: %s%s | deltas: %d (%d provisional) | target: %s (%s)"
          % (canon, "" if canon == query else " (via alias '%s')" % query,
             len(hits), len(provisional), target, mode))
    print("next: distill the draft in place, get it reviewed, then run --apply")
    return 0


def split_draft(path):
    """(front_lines, body_text) of a draft file; None on malformed frontmatter."""
    with open(path, encoding="utf-8") as f:
        return split_draft_text(f.read())


def split_draft_text(text):
    """split_draft over already-loaded text -- the same one split, so a caller
    preflighting a PROJECTED draft (batch-promote assessing a not-yet-transitioned
    carrier) parses it with the grammar apply will use."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], "\n".join(lines[i + 1:])
    return None


def create_text_from_draft(front_lines, body):
    """The exact create-mode page text for a split draft: machine keys stripped,
    remaining frontmatter order kept, LF-joined. THE one spelling of the create
    transform -- batch-promote.py derives its raw expected-target bytes from this
    same function (`.encode("utf-8")`), so a drifted reimplementation cannot
    reintroduce the false-corruption class (resonance R10-N-M1/R11-N-M1)."""
    kept = [ln for ln in front_lines
            if not re.match(r"^(%s):" % "|".join(MACHINE_KEYS), ln)]
    return "---\n" + "\n".join(kept) + "\n---\n\n" + body.strip("\n") + "\n"


def flip_statuses(path, ids, dry_run=False, return_text=False):
    """Set status: consolidated on the given delta_ids inside their METADATA fences,
    byte-preserving everything else. Mirrors parse_fragment's locked split grammar
    (Codex review M3): only the first fence after a header is metadata, and a body's
    col-0 fences toggle depth so a fenced '## delta:' inside a body never desyncs the
    scan. Old non-accepted status survives as a trailing comment (parse-invisible:
    deltas-for strips ` # ...` on unquoted scalars).

    Returns the ids actually rewritten; `dry_run` reports them without writing, which
    is what makes the flip preflightable. That return value is a REPORT, not a verdict:
    whether the flip took is settled by re-reading the file through parse_fragment
    (`not_consolidated`), because this scan is a second grammar for the same format and
    a writer cannot witness its own effect.

    A record is flipped only when its identity is COHERENT -- `delta_id` absent, or
    a scalar equal to the header; a present-but-empty or non-scalar claim (quoted
    empty, bare `delta_id:`, a block list) is refused, never read as absent.
    parse_fragment keys a record by `delta_id or header`, this
    scan sees the header, and matching on the header alone is not merely lossy, it
    flips the WRONG RECORD: with records (header sid-999 / delta_id sid-001) and
    (header sid-001 / delta_id sid-002), a manifest holding sid-001 flipped the
    second -- a different delta, in a different unit -- reported one flip, and passed
    a set-membership check (Codex Mode 3, Critical). An incoherent record is skipped
    instead, so the manifest id it owns reports unflippable and apply refuses."""
    # newline="" keeps \r\n in `text`; read with universal newlines no
    # terminator is ever seen and every flip silently rewrote the file as LF.
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    # Two views of one split: content for the scan, keepends for the rewrite.
    # The previous single file-wide EOL choice re-terminated EVERY line, so a
    # one-line status flip rewrote a mixed-EOL file uniform (round-3 Major 2,
    # POST-CAP); keeping each line's own terminator makes the write a
    # one-line delta by construction.
    lines = text.splitlines()
    keep = text.splitlines(keepends=True)
    out, flipped = list(keep), []
    i, n = 0, len(lines)
    while i < n:
        h = df.HEADER.match(lines[i])
        if not h:
            i += 1
            continue
        hid = h.group(1).strip()
        i += 1
        while i < n and lines[i].strip() == "":                  # blanks before fence
            i += 1
        if i < n and df.FENCE.match(lines[i].strip()):           # metadata fence
            i += 1
            fence, at = [], None
            while i < n and not df.FENCE.match(lines[i].strip()):
                # POSITION only: the last col-0 status line carrying a value,
                # the same line parse_meta's own last-wins col-0 rule crowns.
                # Nothing is read OUT of it -- decision and provenance both
                # come from parse_meta (round 2: a raw capture truncated the
                # `# was:` history at the first '#', which the reader keeps
                # inside quoted and unspaced values).
                sm = re.match(r"^(status:\s*)\S", lines[i])
                if sm:
                    at = (i, sm)
                fence.append(lines[i])
                i += 1
            i += 1                                               # past closing fence
            # The reader's OWN grammar decides identity, coherence and status.
            # This scan used to re-derive all three from raw line tokens, and
            # every difference was a defect: `^\s*`-tolerant regexes read
            # INDENTED nested lines the reader never reads (the D1e decoy; the
            # wrong-record flip reborn through an indented delta_id), the raw
            # token treated `status: []` / `""` / `[superseded]` as flippable
            # scalars, a bare `delta_id:` read as ABSENT rather than as an
            # empty claim, and the terminal set was a third spelling of
            # df.DISPOSED (Codex Mode 3 round 1 of this unit, Majors 1-3).
            # test_two_grammars.py generates the whole surface.
            meta = df.parse_meta(fence)
            did, status = meta.get("delta_id"), meta.get("status")
            rid = did if isinstance(did, str) and did else hid   # reader identity rule
            coherent = "delta_id" not in meta or did == hid      # empty/non-scalar claim: NOT coherent
            # A deliberate disposition is refused HERE, against the snapshot this
            # function is about to rewrite -- not only in apply()'s pre-scan, which
            # reads the file once at the top of the run, before the page write and
            # every other flip. That scan is stale by the time the write lands; this
            # one is the state being overwritten. An id skipped here reports
            # unflippable, so the run refuses rather than passing silently.
            # It does NOT make the window irrelevant, which this comment and the spec
            # both claimed until Codex Mode 3 round 3 falsified it: the read and the
            # atomic_write below are still separate steps, so a writer that shelves
            # the delta between them is overwritten from the stale snapshot. Closing
            # that needs a lock every writer honors, which this tool does not have and
            # deliberately does not pretend to (see the module docstring).
            if (rid in ids and coherent and at
                    and isinstance(status, str) and status
                    and status not in df.DISPOSED):
                j, sm = at
                tail = lines[j][sm.end(1):]
                # What the READER calls a trailing comment -- `\s+#...` on an
                # UNQUOTED scalar only; inside quotes '#' is data (R2-M1) --
                # must survive the rewrite: round-3 Major 1 (POST-CAP) found
                # the reconstruction deleting it.
                cm = (None if tail.startswith(("'", '"'))
                      else re.search(r"\s+#.*$", tail))
                # Provenance from the PARSED value: the raw token loses
                # everything after a '#' the reader treats as data.
                suffix = "" if status == "accepted" else "  # was: %s" % status
                out[j] = (sm.group(1) + "consolidated" + suffix
                          + (cm.group(0) if cm else "")
                          + keep[j][len(lines[j]):])
                flipped.append(rid)
        depth = 0                                                # body: col-0 fences toggle
        while i < n:
            ln = lines[i]
            if df.FENCE.match(ln):
                depth ^= 1
            if depth == 0 and df.HEADER.match(ln):
                break
            i += 1
    if flipped and not dry_run:
        atomic_write(path, "".join(out))
    if return_text:
        return flipped, "".join(out)
    return flipped


def not_consolidated(path, ids):
    """Which of `ids` do NOT read `status: consolidated` when `path` is parsed by
    parse_fragment. The STATE, read through the module's one authoritative grammar --
    never flip_statuses' own report of what it did.

    flip_statuses re-implements the metadata scan (it needs line positions, which
    parse_fragment discards), and a second grammar for one format drifts from the first.
    It HAD: flip's `^\\s*status:` also matched an INDENTED nested line where parse_meta
    keys on col-0 `^(\\w+):`, so flip rewrote the indented line, reported the id
    flipped, and parse_fragment still read the col-0 status -- apply() archived the
    file and deleted the recovery draft at exit 0 over a delta that never moved. That
    instance is closed (flip matches col-0 only now, and test_two_grammars.py generates
    the divergence surface), but this read-back stays, because it is what holds for
    the NEXT drift: flip may write however it likes, the run only succeeds when the
    authoritative reader confirms it.

    It also decides the benign race correctly in both directions: an id another run
    already consolidated is accounted for (flip reports nothing, state says done ⇒ pass),
    while an id flip claims but the parser cannot see is caught (⇒ refuse)."""
    _env, deltas, _w = df.parse_fragment(path)
    got = {(d.get("delta_id") or d.get("_header_id")): d.get("status") for d in deltas}
    return sorted(i for i in ids if got.get(i) != "consolidated")


def manifest_unverified(frag_dir, ids):
    """The manifest ids that do NOT read `consolidated` anywhere on disk right now --
    active fragments AND `_archive/`, re-walked, `_drafts/` excluded.

    The step-2 check covers only what THIS run flipped. Two classes of manifest id skip
    it entirely: ids the pre-scan already read as `consolidated` (dropped from `by_file`)
    and ids a prior interrupted run left in `_archive/` (their status is synthesized, not
    re-read). For those, the newest evidence is a parse from the top of the run, and what
    happens at the bottom of the run is the deletion of the only recovery anchor there is
    (Codex Mode 3 round 1, Major 1). So the manifest is verified as a WHOLE, adjacent to
    that irreversible step -- the same placement principle as the disposition guard in
    flip_statuses: check where the damage happens, not where it is convenient.

    An id whose copies disagree is unverifiable, not verified: two files claiming one id
    with different statuses is exactly the ambiguity the run must not resolve by picking
    one. Copies that AGREE on `consolidated` still pass HERE -- status agreement is not
    identity -- which is why the identity question is asked in the PRE-SCAN instead
    (`cross_archive_dups`), where it refuses before the page is written. This function
    answers "did the statuses land", not "is the id unambiguous".

    This is a check-then-act and the window to the draft deletion is NOT closed (Codex
    Mode 3 round 2, Major). No lock is taken, deliberately: a lock only means something
    if every writer honors it, and the dominant writer of a fragment is an agent
    appending deltas through an editor, which cannot take one. A lock here would exclude
    only consolidate.py -- the one writer that is already serial -- while reading as
    mutual exclusion. The tool assumes a single writer and says so in the spec instead."""
    got, conflict = {}, set()
    for root, dirs, files in os.walk(frag_dir):
        dirs[:] = [d for d in dirs if d != "_drafts"]
        for name in sorted(files):
            if not name.endswith(".md"):
                continue
            _env, deltas, _w = df.parse_fragment(os.path.join(root, name))
            for d in deltas:
                did = d.get("delta_id") or d.get("_header_id")
                st = d.get("status")
                if did in got and got[did] != st:
                    conflict.add(did)
                got.setdefault(did, st)
    return sorted(i for i in ids if i in conflict or got.get(i) != "consolidated")


def merge_consolidates(target, ids, text=None):
    """(new_text, added, error). Merge manifest ids into the target page's frontmatter
    `consolidates:` block list (created before the closing --- when absent), preserving
    every other byte. The update-existing provenance fix: the draft is deleted at apply
    and it is the manifest's only home, so without this merge the delta->page direction
    is recorded nowhere. Fail-closed: a target whose frontmatter cannot carry the list
    (missing/unterminated/inline-style) is an error -> the caller refuses pre-mutation."""
    if text is None:
        try:
            with open(target, encoding="utf-8", newline="") as f:   # newline="": see flip_statuses
                text = f.read()
        except OSError as e:
            return None, 0, "cannot read target: %s" % e
    # keepends, not one file-wide EOL: rejoining on a single chosen terminator
    # rewrote every line of a mixed-EOL page during a bookkeeping-only merge
    # (3B audit 2026-09-02). Only the inserted lines are new bytes.
    kept = text.splitlines(True)
    lines = [l.rstrip("\r\n") for l in kept]
    eol = "\r\n" if "\r\n" in text else "\n"
    if not lines or lines[0].strip() != "---":
        return None, 0, "target has no frontmatter block to record consolidates: in"
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return None, 0, "target frontmatter is unterminated (no closing ---)"
    keys = [i for i in range(1, end) if re.match(r"^consolidates:", lines[i])]
    if len(keys) > 1:
        # parse_meta (the consumer) takes the LAST key while this merge writes into
        # the FIRST -- a duplicate therefore splits provenance invisibly; refuse.
        return None, 0, ("target carries more than one 'consolidates:' key -- "
                         "repair the frontmatter by hand first")
    key_at = None
    for i in range(1, end):
        if re.match(r"^consolidates:\s*#", lines[i]):
            # parse_meta strips a comment only after WHITESPACE on an unquoted
            # scalar; a comment starting the value is read AS the scalar, so this
            # shape splits the witness and consumer grammars -- refuse it.
            return None, 0, ("target 'consolidates:' key line carries a comment -- "
                             "parse_meta would read it as a scalar value; repair "
                             "the frontmatter by hand first")
        if re.match(r"^consolidates:\s*$", lines[i]):
            key_at = i
            break
        if re.match(r"^consolidates:\s*\S", lines[i]):
            return None, 0, ("target 'consolidates:' uses inline style -- convert it to "
                             "a block list by hand first")
    existing, insert_at = set(), end
    if key_at is not None:
        j = key_at + 1
        while j < end:
            m = re.match(r"^\s+-\s+(\S+)\s*$", lines[j])
            if not m:
                break
            existing.add(m.group(1))
            j += 1
        # A list-shaped line the loop refused is still CONSUMED by parse_meta as a
        # manifest item, so stopping silently would split the witness and consumer
        # grammars (a trailing comment or extra token rides into provenance).
        if j < end and re.match(r"^\s+-\s", lines[j]):
            return None, 0, ("target 'consolidates:' block contains a noncanonical "
                             "item line -- repair it by hand first")
        k = j
        while k < end and not re.match(r"^\w+:", lines[k]):
            if re.match(r"^\s+-\s", lines[k]):
                return None, 0, ("target 'consolidates:' block resumes after a "
                                 "comment/blank gap -- parse_meta reads the later "
                                 "item(s) as manifest items; repair by hand first")
            k += 1
        insert_at = j
    add = [i for i in ids if i not in existing]
    if not add:
        return text, 0, None
    # Inserted lines take the terminator of the line they follow, so a page that is
    # LF in its body and CRLF in its frontmatter stays exactly that.
    def _term(i):
        ref = kept[i - 1] if 0 < i <= len(kept) else (kept[i] if i < len(kept) else "")
        for end in ("\r\n", "\n", "\r"):
            if ref.endswith(end):
                return end
        return eol

    term = _term(insert_at)
    block = ([] if key_at is not None else ["consolidates:" + term]) + \
            ["  - %s%s" % (i, term) for i in add]
    out = kept[:insert_at] + block + kept[insert_at:]
    return "".join(out), len(add), None


def delta_section(path):
    """Return the fragment's delta section with LF line endings, or None."""
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    start, depth = None, 0
    for i, ln in enumerate(lines):
        if df.FENCE.match(ln):
            depth ^= 1
        if depth == 0 and df.HEADER.match(ln):
            start = i
            break
    return None if start is None else "\n".join(lines[start:])


def fragment_already_appended(dest, src):
    """Prove a prior append wrote src into dest before crashing before src removal.

    The proof is over PARSED, top-level records -- for every delta in src, dest must
    hold a delta with the same id and the same content. It used to be a raw substring
    test of src's delta section against dest's text, which a balanced fenced code sample
    in dest satisfies while its parsed records say something else entirely (Codex Mode 3,
    Critical): the caller then deletes src as "already archived" and the records in it
    are gone. A record boundary is a col-0 header outside balanced fences -- that is what
    parse_fragment computes, and asking it is the only way to compare records rather than
    characters."""
    # A damaged dest NEVER proves a prior append (round-3 Critical, CAP): an
    # unterminated metadata fence makes parse_meta absorb LATER yaml into the
    # FIRST record -- last wins -- so corruption can SYNTHESIZE a parsed
    # record equal to a valid empty-body source. "Hiding only removes
    # evidence" was this function's callers' premise, and it is FALSE for
    # this proof; the refusal lives here so no caller ordering can reopen it.
    # Recovery from a damaged twin is repairing the twin, then resuming.
    if df.fragment_damage(dest):
        return False
    senv, sdeltas, _sw = df.parse_fragment(src)
    denv, ddeltas, _dw = df.parse_fragment(dest)
    if (not ddeltas or not senv.get("session_id")
            or senv.get("session_id") != denv.get("session_id")
            or not df.all_disposed(sdeltas)):
        return False
    strip = lambda d: {k: v for k, v in d.items() if k != "_file"}   # noqa: E731 (_file is the source name)
    dst_by_id = {(d.get("delta_id") or d.get("_header_id")): d for d in ddeltas}
    for d in sdeltas:
        twin = dst_by_id.get(d.get("delta_id") or d.get("_header_id"))
        if twin is None or strip(twin) != strip(d):
            return False
    return True


def append_archive(dest, src):
    """Append src's delta sections to an existing same-session archive file, then
    remove src. Handles the legitimate archive collision: a session that continued
    after its fragment file was archived (filename = session id, locked). The src
    envelope and any preamble before the first delta header are dropped; sections
    are appended verbatim (fence-aware header scan, mirroring the locked grammar).
    Caller has verified same session_id + disjoint delta-id sets. False = no
    appendable section found (caller treats as a collision error)."""
    section = delta_section(src)
    if section is None:
        return False
    with open(dest, encoding="utf-8", newline="") as f:          # newline="": see flip_statuses
        dtext = f.read()
    eol = "\r\n" if "\r\n" in dtext else "\n"
    if eol == "\r\n":
        section = section.replace("\n", "\r\n")
    if dtext.endswith(eol * 2):
        sep = ""
    elif dtext.endswith(eol):
        sep = eol
    else:
        sep = eol * 2
    atomic_write(dest, dtext + sep + section + eol)
    os.remove(src)
    return True


def same_session_disjoint(env, deltas, dest):
    """True iff dest parses as a fragment of the SAME session with a delta-id set
    disjoint from `deltas` -- the only archive collision apply may resolve (by
    appending). Anything else (junk file, different session, overlapping ids)
    stays a hard refusal."""
    denv, ddeltas, _dw = df.parse_fragment(dest)
    if not ddeltas:
        return False
    sid = env.get("session_id")
    if not sid or denv.get("session_id") != sid:
        return False
    src_ids = {(d.get("delta_id") or d.get("_header_id")) for d in deltas}
    dst_ids = {(d.get("delta_id") or d.get("_header_id")) for d in ddeltas}
    return not (src_ids & dst_ids)


def cross_archive_dups(frag_dir, ids, where):
    """Manifest ids that name a delta record in more than one place once `_archive/` is
    counted. The pre-scan's `dups` walks ACTIVE fragments only, so an id living in both
    an active fragment and the archive passed every check -- and `manifest_unverified`
    let it through too, because it only objects when the copies' STATUSES disagree.
    Status agreement is not identity: two `consolidated` copies of one id still mean the
    promoted page's `consolidates:` names two different deltas (Codex Mode 3 round 3,
    Major). Answered here, in the pre-scan, so the ambiguity refuses BEFORE the page is
    written rather than after.

    One overlap is legitimate and exempt: a prior run that appended an active fragment
    into its same-named archive file and crashed before removing the source, which
    `fragment_already_appended` proves by content. The disjoint-continuation append is
    not a case at all -- its id sets do not intersect by construction.

    Deliberately does NOT feed `where`/`status_of`/`unit_of`: folding the archive into
    that scan would shrink `missing` and change the archive-recovery path, which is not
    what this closes.

    This reasons from what an archive file PARSES to, which is sound only because
    apply()'s pre-scan now GATES the archive on damage first (the unit delta 081 split
    out): a file that may hide records -- an unbalanced col-0 fence absorbs the very id
    being hunted -- either refuses the run by name or proceeds under an explicit
    sha-bound quarantine acknowledgment, printed every run. The rejected frames stay
    rejected: relevance-scoping selectors (filename, envelope, parsed ids) are hideable
    by the corruption itself, so the gate keys on the parse WARNINGS, the one signal
    corruption produces rather than hides. Ids inside an acknowledged quarantined file
    are outside this check's proof, and the standing QUARANTINE line says so."""
    arch_dir = os.path.join(frag_dir, "_archive")
    if not os.path.isdir(arch_dir):
        return [], []
    homes = {}
    # errors ignored HERE only because apply's early gate refuses on them
    # before this runs and the pre-mutation recheck refuses again after.
    arch_paths, _arch_errs = df.archive_md(frag_dir)
    for p in arch_paths:
        _env, deltas, _w = df.parse_fragment(p)
        for d in deltas:
            homes.setdefault(d.get("delta_id") or d.get("_header_id"), []).append(p)
    resumed, crossed, multi = {}, [], []
    for i in ids:
        where_archived = homes.get(i, [])
        if not where_archived:
            continue                                  # active only -- `dups` owns that
        active = where.get(i)
        if active is None:
            if len(where_archived) > 1:               # two archive files claim one id
                multi.append(i)
            continue                                  # archive only -- the recovery path
        if active not in resumed:
            dest = os.path.join(arch_dir, os.path.basename(active))
            resumed[active] = (dest if os.path.exists(dest)
                               and fragment_already_appended(dest, active) else None)
        if where_archived == [resumed[active]]:
            continue
        crossed.append(i)
    return sorted(crossed), sorted(multi)


def active_md(frag_dir):
    """(paths, errors): every ACTIVE fragment .md (`_archive/`/`_drafts/` skipped),
    sorted, plus the traversal errors os.walk swallows by default -- the active-side
    mirror of df.archive_md, for the same reason (an unreadable subtree read as an
    EMPTY set and absence proofs ran over an incomplete listing). Shared with
    batch-promote.py so both sides reason from the same enumeration."""
    out, errors = [], []

    def _err(exc):
        errors.append("active traversal failed: %s (%s)"
                      % (getattr(exc, "filename", None) or frag_dir,
                         type(exc).__name__))

    for root, dirs, files in os.walk(frag_dir, onerror=_err):
        dirs[:] = [d for d in dirs if d not in ("_archive", "_drafts")]
        out += [os.path.join(root, f) for f in files if f.endswith(".md")]
    return sorted(out), errors


def damage_gate(frag_dir, md):
    """(error, standing_quarantine_lines): the damage preflight apply() runs before
    any check that reasons from the parsed set -- shared with batch-promote.py's
    assessment so the batch layer cannot drift weaker than apply (its R2-M5/R3-M5
    recurrence class). ACTIVE files refuse on any RECORD-LOSS with no quarantine
    escape -- they are the run's working set, flips and archiving write into them,
    so "proceed around it" is not a coherent ask; the ARCHIVE refuses on traversal
    errors and unacknowledged damage, while sha-bound acknowledged quarantines are
    returned for the caller to PRINT (a quarantine nobody reports is the silent gap
    again, wearing a registry)."""
    for path in sorted(md):
        loss = df.fragment_damage(path)
        if loss:
            return ("fragment may hold delta records this parse did not return -- "
                    "refusing before any check that reasons from the parsed set "
                    "(repair the file, then re-run): %s" % "; ".join(loss)), []
    arch_paths, arch_errors = df.archive_md(frag_dir)
    if arch_errors:
        return ("archive traversal failed -- the archive cannot be "
                "enumerated, so absence proofs are unsound: %s"
                % "; ".join(arch_errors)), []
    arch_blocking, arch_standing = df.damage_report(frag_dir, arch_paths)
    if arch_blocking:
        return ("archive file(s) may hide delta records -- absence proofs are "
                "unsound until each named file is inspected: %s"
                % " | ".join(arch_blocking)), arch_standing
    return None, arch_standing


def apply_preflight(kdir, frag_dir, canon, target_text=None, verbose=True,
                    draft_text=None):
    """(plan, error, exit_code): EVERY read-only check apply() runs before its first
    write, extracted whole so batch-promote.py's assessment executes the same
    contract instead of a weaker parallel copy (the R2-M5/R3-M5/R4-M3/R5-M2
    recurrence family ends here). `plan` carries everything the mutation half
    consumes. `target_text` overrides the target's on-disk content for existence,
    equality and merge checks -- a batch assessing carriers BEFORE the create has
    landed passes the projected create output. `verbose=False` suppresses the
    standing-quarantine and already-consolidated prints (they stay in `plan` as
    `standing` / `already`); apply() keeps verbose=True so its output contract is
    unchanged, including on refusals. `draft_text` overrides reading the draft file
    -- a batch projecting a not-yet-transitioned carrier passes the projected
    content, so the same preflight runs before the transition mutates anything."""
    draft_path = os.path.join(frag_dir, "_drafts", canon + ".md")
    if draft_text is None:
        if not os.path.exists(draft_path):
            return None, "no draft at %s -- run --draft first" % draft_path, 2
        parts = split_draft(draft_path)
    else:
        parts = split_draft_text(draft_text)
    if not parts:
        return None, "draft frontmatter malformed (expected --- ... ---): %s" % draft_path, 1
    front_lines, body = parts
    meta = df.parse_meta(front_lines)
    if any(ln.lstrip().startswith(BANNER_PREFIX) for ln in body.splitlines()):
        return None, ("the '%s' banner is still in the draft -- distill it first "
                      "(the banner is the proof-of-distillation gate); nothing mutated"
                      % BANNER_PREFIX), 1
    ids = meta.get("consolidates") or []
    if isinstance(ids, str):
        ids = [ids]
    if not ids:
        return None, "empty consolidates manifest in %s; nothing mutated" % draft_path, 1
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        return None, ("duplicate id(s) in the consolidates manifest: %s; nothing mutated"
                      % ", ".join(dupes)), 1
    if meta.get("unit") and meta["unit"] != canon:
        return None, ("draft unit '%s' != requested unit '%s'; nothing mutated"
                      % (meta["unit"], canon)), 1
    target_rel, mode = meta.get("target", ""), meta.get("apply_mode", "")
    if mode not in ("create", "update-existing"):
        return None, "apply_mode must be create|update-existing (got '%s'); nothing mutated" % mode, 1
    target, why = resolve_target(kdir, target_rel, earned_slices(kdir))
    if not target:
        return None, why + "; nothing mutated", 1
    if not os.path.isdir(os.path.dirname(target)):                # nested sub-dir in a slice
        return None, ("parent dir missing for '%s' -- create it deliberately or re-route; "
                      "nothing mutated" % target_rel), 1
    create_text = create_text_from_draft(front_lines, body)
    target_exists = os.path.exists(target) if target_text is None else True
    target_already_applied = False
    if mode == "create" and target_exists:
        if target_text is None:
            try:
                with open(target, encoding="utf-8") as f:
                    target_already_applied = f.read() == create_text
            except (OSError, UnicodeDecodeError):
                target_already_applied = False
        else:
            target_already_applied = target_text == create_text
        if not target_already_applied:
            return None, ("target already exists: %s (use apply_mode: update-existing after merging "
                          "by hand); nothing mutated" % target_rel), 1
    if mode == "update-existing" and not target_exists:
        return None, "apply_mode update-existing but target missing: %s; nothing mutated" % target_rel, 1

    # update-existing provenance PREFLIGHT: compute the consolidates: merge now so a
    # target that cannot carry it (no/unterminated/inline frontmatter) refuses before
    # any write -- silently skipping the merge would recreate the lost-provenance defect.
    merged_text, merged_added = None, 0
    if mode == "update-existing":
        merged_text, merged_added, merr = merge_consolidates(target, ids, text=target_text)
        if merr:
            return None, merr + "; nothing mutated", 1

    # locate every manifest delta among ACTIVE fragments; refuse on manifest drift
    alias2canon = df.load_units(frag_dir)
    md, md_errors = active_md(frag_dir)
    if md_errors:
        return None, ("active traversal failed -- the working set cannot be "
                      "enumerated, so manifest/absence reasoning is unsound: %s; "
                      "nothing mutated" % "; ".join(md_errors)), 1
    # RECORD-LOSS preflight, FIRST among the fragment checks (rationale + the
    # active-vs-archive asymmetry: damage_gate's docstring; the checks moved there
    # verbatim so batch-promote.py runs the same gate instead of a weaker copy).
    where, status_of, refs_of, unit_of, dups = {}, {}, {}, {}, set()
    gate_error, gate_standing = damage_gate(frag_dir, md)
    if verbose:
        for line in gate_standing:
            print("consolidate: " + line)
    if gate_error:
        return None, gate_error + "; nothing mutated", 1
    for path in sorted(md):
        _env, deltas, _w = df.parse_fragment(path)
        for d in deltas:
            did = d.get("delta_id") or d.get("_header_id")
            if did in where:
                dups.add(did)
            where.setdefault(did, path)
            status_of.setdefault(did, d.get("status"))
            refs_of.setdefault(did, df.code_refs(d))
            unit_of.setdefault(did, d.get("unit_id"))
    missing = [i for i in ids if i not in where]
    if missing:
        # Recovery path: a prior apply may have completed the archive move but
        # crashed before deleting the draft. Prove every missing id exists as
        # consolidated in _archive before treating it as already finished.
        archived = {}
        rec_paths, _rec_errs = df.archive_md(frag_dir)   # gate above refused errors
        for path in rec_paths:
            _env, deltas, _warns = df.parse_fragment(path)
            for d in deltas:
                did = d.get("delta_id") or d.get("_header_id")
                archived[did] = d.get("status")
                unit_of.setdefault(did, d.get("unit_id"))
                refs_of.setdefault(did, df.code_refs(d))
        unresolved = [i for i in missing if archived.get(i) != "consolidated"]
        if unresolved:
            return None, ("manifest delta(s) not found in active fragments: %s; nothing mutated"
                          % ", ".join(unresolved)), 1
        for i in missing:
            status_of[i] = "consolidated"
    ambiguous = sorted(set(ids) & dups)
    if ambiguous:
        return None, ("manifest delta_id(s) duplicated across active fragments (ambiguous flip): "
                      "%s; nothing mutated" % ", ".join(ambiguous)), 1
    crossed, multi = cross_archive_dups(frag_dir, ids, where)
    if crossed:
        return None, ("manifest delta_id(s) name a delta in BOTH an active fragment and "
                      "_archive/ (ambiguous provenance -- `consolidates:` would point at two "
                      "different deltas): %s; nothing mutated" % ", ".join(crossed)), 1
    if multi:                                      # distinct shape, distinct repair
        return None, ("manifest delta_id(s) name a delta in MORE THAN ONE _archive/ file "
                      "(ambiguous provenance): %s; nothing mutated" % ", ".join(multi)), 1
    foreign = [i for i in ids
               if alias2canon.get(unit_of.get(i), unit_of.get(i)) != canon]
    if foreign:
        return None, ("manifest delta(s) belong to another unit (drafted manifest drifted?): "
                      "%s; nothing mutated" % ", ".join(foreign)), 1
    already = [i for i in ids if status_of.get(i) == "consolidated"]
    if already and verbose:
        print("consolidate: note: already consolidated, skipping: %s" % ", ".join(already))
    # A draft can no longer collect these (gather skips them), so their presence
    # means a hand-edited manifest. Promoting a delta that was deliberately shelved
    # or revised is a mistake, and flip_statuses would silently rewrite it to
    # consolidated -- so refuse before touching anything.
    disposed = [i for i in ids if status_of.get(i) in ("archived", "superseded")]
    if disposed:
        return None, ("manifest delta(s) already disposed (archived/superseded) and must "
                      "not be promoted: %s; nothing mutated" % ", ".join(sorted(disposed))), 1

    # manifest ids grouped by the fragment file that holds them -- the input to BOTH
    # preflights below and to the flip loop in step 2.
    by_file = {}
    for i in ids:
        if i not in already:
            by_file.setdefault(where[i], []).append(i)

    # flip PREFLIGHT: prove every manifest id is reachable by flip_statuses before any
    # write. `where` keys by delta_id, flip_statuses scans by '## delta:' header id, and
    # a delta with no `status:` line answers to neither -- each ends as a promoted page
    # with an unflipped delta and the recovery draft deleted, at exit 0.
    unflippable = sorted({i for path, fids in by_file.items()
                          for i in set(fids) - set(flip_statuses(path, set(fids), dry_run=True))})
    if unflippable:
        return None, ("manifest delta(s) have no flippable 'status:' line in their fragment "
                      "(header/delta_id mismatch, or malformed metadata): %s; nothing mutated"
                      % ", ".join(unflippable)), 1

    # archive PREFLIGHT (Codex review M1): a collision must refuse BEFORE any write --
    # except the one legitimate case (same session continued post-archive, disjoint
    # delta ids), which step 3 resolves by appending. Include fully-disposed
    # active files from a prior interrupted run, even though their ids need no flip.
    archive_paths = set(by_file)
    for i in already:
        path = where.get(i)
        if not path:
            continue
        _env, deltas, _w = df.parse_fragment(path)
        if df.all_disposed(deltas):
            archive_paths.add(path)
    # Acknowledgment digests re-verified ADJACENT to the first mutation, not
    # only at the top of the pre-scan (the archive-trust round-1 race): the
    # heavy checks above take time, and a stale acknowledgment must not carry
    # a file that changed under it into the write phase. The residual
    # read-then-write window matches the flip window: real, narrow,
    # documented, closable only by a lock every writer honors -- which this
    # tool does not have and does not pretend to.
    late_paths, late_errors = df.archive_md(frag_dir)
    if late_errors:
        return None, ("archive traversal failed at the write phase: %s; "
                      "nothing mutated" % "; ".join(late_errors)), 1
    late_blocking, _late_standing = df.damage_report(frag_dir, late_paths)
    if late_blocking:
        return None, ("archive damage (re)appeared between the pre-scan and the "
                      "write phase: %s; nothing mutated" % " | ".join(late_blocking)), 1
    for path in sorted(archive_paths):
        env, deltas, _w = df.parse_fragment(path)
        # Same predicate as step 3, imported not respelled: this asked
        # `status == "consolidated"` while step 3 asked `status in DISPOSED`, so one
        # `superseded` delta in the file skipped the collision check below and refused
        # after the page write and the flips.
        would = df.all_disposed(deltas, by_file.get(path, ()))
        dest = os.path.join(frag_dir, "_archive", os.path.basename(path))
        if not (would and deltas and os.path.exists(dest)):
            continue
        # Step 3's decision tree, asked BEFORE any write (round-1 Major: a
        # damaged twin was refused only AFTER the page write and the status
        # flips). DAMAGE FIRST (round-3 Critical): a damaged twin can
        # SYNTHESIZE prior-append equality, so no proof outranks the damage
        # refusal; an append also lands at EOF where an unclosed fence
        # ABSORBS records on arrival, and disjointness is an absence proof a
        # hiding file cannot carry. Only a clean twin gets the resume or the
        # plain collision test.
        twin_damage = df.fragment_damage(dest)
        if twin_damage:
            return None, ("archive twin may hide records (no proof stands over "
                          "it -- prior-append equality is forgeable, an append "
                          "risks absorption): %s -- %s; nothing mutated"
                          % (dest, "; ".join(twin_damage))), 1
        if fragment_already_appended(dest, path):
            continue
        if not same_session_disjoint(env, deltas, dest):
            return None, ("archive collision: %s already exists and is neither a disjoint "
                          "continuation nor a verified prior append of the same session "
                          "(would archive %s); nothing mutated"
                          % (dest, os.path.basename(path))), 1

    return {"draft_path": draft_path, "ids": ids, "mode": mode, "target": target,
            "target_rel": target_rel, "create_text": create_text,
            "target_already_applied": target_already_applied,
            "merged_text": merged_text, "merged_added": merged_added,
            "by_file": by_file, "archive_paths": archive_paths, "already": already,
            "refs_of": refs_of, "standing": gate_standing}, None, 0


def apply(kdir, frag_dir, canon):
    plan, err, code = apply_preflight(kdir, frag_dir, canon)
    if err:
        return fail(err, code)
    draft_path, ids, mode = plan["draft_path"], plan["ids"], plan["mode"]
    target, target_rel = plan["target"], plan["target_rel"]
    create_text = plan["create_text"]
    target_already_applied = plan["target_already_applied"]
    merged_text, merged_added = plan["merged_text"], plan["merged_added"]
    by_file, archive_paths = plan["by_file"], plan["archive_paths"]
    refs_of = plan["refs_of"]

    # 1. Promote/verify the page atomically. A byte-identical create target or an
    # already-updated consolidates manifest is a prior partial apply, not a conflict.
    if mode == "create":
        if not target_already_applied:
            atomic_write(target, create_text)
            print("promoted: %s" % target_rel)
        else:
            print("promoted earlier (verified byte-identical): %s" % target_rel)
    else:
        if merged_added:
            atomic_write(target, merged_text)
        note = ("recorded %d delta id(s) in consolidates:" % merged_added
                if merged_added else "consolidates: already up to date")
        print("update-existing: %s already merged by hand -- bookkeeping (%s)"
              % (target_rel, note))

    # 2. flip statuses (by_file precomputed at the archive preflight). The result is
    # ASSERTED, not merely reported: this printed `consolidated N delta(s)` without ever
    # comparing N to the manifest, so a promotion that flipped nothing still returned
    # success and deleted the draft. Asserted against the FILE, re-read through
    # parse_fragment -- not against flip_statuses' return value, which is the same code
    # that just did the writing and cannot be a witness to its own effect (see
    # not_consolidated). That is also what makes the preflight's read-then-write window
    # harmless: the check that decides the exit code runs after the last mutation.
    unflipped = []
    for path, file_ids in sorted(by_file.items()):
        flipped = flip_statuses(path, set(file_ids))
        unflipped += not_consolidated(path, file_ids)
        print("consolidated %d delta(s) in %s" % (len(set(flipped)), os.path.basename(path)))
    if unflipped:
        print("consolidate: status flip incomplete -- manifest delta(s) did not flip: %s"
              % ", ".join(unflipped), file=sys.stderr)
        print("consolidate: draft retained for recovery: %s" % draft_path, file=sys.stderr)
        return 1

    # 3. archive fragment files that are now fully DISPOSED (all units) -- consolidated,
    # archived or superseded; NOT 'all consolidated', which no call site has ever meant
    issues = 0
    for path in sorted(archive_paths):
        env, deltas, _w = df.parse_fragment(path)
        if df.all_disposed(deltas):
            arch_dir = os.path.join(frag_dir, "_archive")
            os.makedirs(arch_dir, exist_ok=True)
            dest = os.path.join(arch_dir, os.path.basename(path))
            if os.path.exists(dest):
                # DAMAGE FIRST (round-3 Critical, CAP): "prior-append is a
                # presence proof a hiding dest cannot fake" was FALSE -- an
                # unterminated metadata fence lets parse_meta absorb later
                # yaml into the first record and SYNTHESIZE the equality the
                # proof requires. So a damaged twin satisfies NOTHING here:
                # no resume, no append (which lands at EOF, inside an
                # unclosed fence, absorbed on arrival), no disjointness (an
                # absence proof a hiding file cannot carry). The same rule is
                # enforced inside fragment_already_appended itself, so no
                # caller ordering can reopen it.
                twin_damage = df.fragment_damage(dest)
                if twin_damage:
                    print("consolidate: ERROR: archive twin may hide records "
                          "(no proof stands over it), NOT touching: %s -- %s"
                          % (dest, "; ".join(twin_damage)), file=sys.stderr)
                    issues += 1
                elif fragment_already_appended(dest, path):
                    os.remove(path)
                    print("archived earlier (verified prior append): %s"
                          % os.path.basename(path))
                elif same_session_disjoint(env, deltas, dest) and append_archive(dest, path):
                    print("archived (appended to same-session archive): %s"
                          % os.path.basename(path))
                else:
                    print("consolidate: ERROR: archive collision, NOT moving: %s" % dest,
                          file=sys.stderr)
                    issues += 1
                continue
            os.replace(path, dest)
            print("archived (all deltas disposed): %s" % os.path.basename(path))
        else:
            live = sum(1 for d in deltas if d.get("status") not in df.DISPOSED)
            print("kept live (%d unconsolidated delta(s) remain): %s" % (live, os.path.basename(path)))

    # Draft is the recovery anchor: delete it only after target, status flips, and
    # archives all completed successfully -- and only after the WHOLE manifest is
    # re-read from disk, because deleting the draft is the step that cannot be undone.
    if issues:
        print("consolidate: draft retained for recovery: %s" % draft_path, file=sys.stderr)
        return 1
    unverified = manifest_unverified(frag_dir, ids)
    if unverified:
        print("consolidate: manifest delta(s) do not read `consolidated` on disk: %s"
              % ", ".join(unverified), file=sys.stderr)
        print("consolidate: draft retained for recovery: %s" % draft_path, file=sys.stderr)
        return 1
    os.remove(draft_path)

    refs = sorted({r for i in ids for r in refs_of.get(i, [])})
    print("\nNEXT (semantic -- not automated):")
    print("  - add an index.md entry for %s" % target_rel)
    if os.path.exists(os.path.join(kdir, "log.md")):
        print("  - append a log.md line")
    if refs:
        print("  - wiki refresh: feed to wiki-pages-for: %s" % " ".join(sorted(set(refs))))
        print("    (no wiki/ in the project => graceful no-op)")
    print("  - run kb-lint")
    return 0


def main():
    argv = sys.argv[1:]
    flags, pos = set(), []
    for a in argv:
        if a.startswith("--"):
            if a not in ("--draft", "--apply", "--force"):
                print("consolidate: unrecognized argument '%s'" % a, file=sys.stderr)
                print(USAGE, file=sys.stderr)
                return 2
            flags.add(a)
        else:
            pos.append(a)
    if len(pos) != 2 or ("--draft" in flags) == ("--apply" in flags):
        print(USAGE, file=sys.stderr)
        return 2
    if "--force" in flags and "--draft" not in flags:
        print("consolidate: --force is only valid with --draft", file=sys.stderr)
        return 2

    frag_dir = df.find_fragments(pos[0])
    if not frag_dir:
        return fail("no _fragments/ directory under %s" % pos[0], 2)
    kdir = os.path.dirname(frag_dir)
    alias2canon = df.load_units(frag_dir)
    query = pos[1]
    if query not in alias2canon:
        print("consolidate: warning: unit_id '%s' not declared in units.yml" % query,
              file=sys.stderr)
    canon = alias2canon.get(query, query)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", canon) or not canon.strip("."):
        return fail("unit id '%s' is not a safe slug ([A-Za-z0-9._-]+, not all dots) -- "
                    "it becomes the draft filename" % canon, 2)

    if "--apply" in flags:
        return apply(kdir, frag_dir, canon)

    # --draft is read-only, so damage never BLOCKS it -- but "every consumer
    # prints standing quarantines" includes this surface (round-3 Major): a
    # draft silently gathered past an acknowledged gap reads as completeness.
    d_paths, d_errors = df.archive_md(frag_dir)
    d_blocking, d_standing = df.damage_report(frag_dir, d_paths)
    for line in d_standing + d_blocking + d_errors:
        print("consolidate: warning: " + line, file=sys.stderr)

    hits, warnings = gather(frag_dir, canon, alias2canon)
    if warnings:
        print("WARNINGS (malformed deltas -- surfaced, never dropped):")
        for w in warnings:
            print("  ! " + w)
    if not hits:
        return fail("no unconsolidated deltas for unit '%s' -- nothing to draft" % canon)
    return draft(kdir, frag_dir, canon, query, hits, "--force" in flags)


if __name__ == "__main__":
    sys.exit(main())
