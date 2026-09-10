#!/usr/bin/env python3
"""Shared Codex install engine: snapshot, apply, verify, and record."""
import argparse
import collections
import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from io import TextIOWrapper
from typing import NoReturn

ENGINE_DIR = Path(__file__).resolve().parent
SETUP_CHECK = ENGINE_DIR / "setup-check.py"

# Run as a script, sys.path[0] is already scripts/; loaded BY PATH (which is
# how the suites import this engine) it is not, and the shared backup
# primitive would be unimportable.
if str(ENGINE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR.parent))
sys.dont_write_bytecode = True
from scripts.community import source_digest, source_hashes
from scripts import source_recovery
from scripts.installer_support import allocate_backup, is_source_junk            # noqa: E402
from scripts.installer_snapshot import SourceSnapshot, snapshot_matches_commit   # noqa: E402
from scripts.runtime import validate_python

STATE_REL = (".codex", "dev-setup-codex-community-state.json")
# `__pycache__` as an ancestor DIRECTORY, never a leaf file (r4).
JUNK_DIR = re.compile(r"(^|/)__pycache__/")
# ONE list of managed trees, driving the enumeration, the copy, the prune, the
# recorded manifest and the recorded hash. A second list is how a tree ends up
# copied but unmanifested, or manifested but uncopied.
ManagedTree = collections.namedtuple(
    "ManagedTree", "manifest_key hash_key source target label banner")
MANAGED_TREES = (
    ManagedTree("skills_manifest", "skills_tree",
                ("skills",), (".codex", "skills"),
                "Skill", "[4] Codex skills"),
)


class Refusal(Exception):
    """A condition under which no baseline may be recorded and no skip proved."""


def load_setup_check():
    """The checker module, loaded by path (its name carries a hyphen).

    A clone missing it is not something to work around: the producer rules
    and the checker's canonicalization would both have to be re-derived here,
    which is the two-implementations defect this engine exists to remove.
    """
    if not SETUP_CHECK.is_file():
        raise Refusal("scripts/setup-check.py missing from the clone -- "
                      "cannot canonicalize; re-clone or /sync")
    spec = importlib.util.spec_from_file_location("setup_check_engine",
                                                  SETUP_CHECK)
    if spec is None or spec.loader is None:
        raise Refusal("setup-check module loader unavailable")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:                      # noqa: BLE001 - reported, not swallowed
        raise Refusal("scripts/setup-check.py failed to load (%s: %s)"
                      % (type(exc).__name__, exc))
    return module


def load_native_hooks():
    path = ENGINE_DIR / "native-hooks.py"
    spec = importlib.util.spec_from_file_location("community_native_hooks", path)
    if spec is None or spec.loader is None:
        raise Refusal("native-hooks module loader unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- state shape gates ----------------------------------------------------
# Python's `==` on str is ordinal and its `isinstance` does not coerce, so the
# r9/r10/r12 comparison classes cannot be spelled wrong here the way they
# could in PowerShell. The gates about a VALUE's shape -- which no language
# makes free -- live in setup-check.py (state_schema_current, is_str_list) and
# are called from here: r1 of this unit measured the alternative, a local copy
# of the schema gate disagreeing with the checker's over `2.0`.

def load_state(state_path):
    """The recorded state as a dict, or None when it cannot be one.

    Corrupt/truncated state must not brick every later install: absent or
    unreadable simply means not-in-sync, and the full run rewrites it.
    """
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


# --- repo facts -----------------------------------------------------------
# No git wrapper of its own: `sc.git_lines` and `sc.managed_sources_dirty` are
# the checker's, and the engine calls them (review r2 found the dirty-source
# query spelled separately in both -- the same duplication class one rule over
# from the schema gate r1 caught).

def current_commit(sc, repo):
    """HEAD as a full object id, or "" when that cannot be established.

    The shape is verified here rather than trusted: setup-check REFUSES a
    recorded applied_commit that is not an object id (it is handed to git as a
    revision), so a state write carrying anything else would produce a
    baseline the checker reports as unreadable forever.
    """
    rc, out = sc.git_lines(repo, "rev-parse", "HEAD")
    if rc != 0 or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", out or ""):
        return ""
    return out


# --- managed trees --------------------------------------------------------
# `IsReparseTagNameSurrogate` -- Windows' own documented predicate for "this
# reparse point stands in for another NAME", which is precisely what this
# engine means by a link. Symlinks and junctions/mount points carry the bit;
# reparse points that are not redirections (cloud placeholders, dedup) do not,
# so this refuses links without refusing an un-hydrated OneDrive file.
NAME_SURROGATE = 0x20000000


def stat_is_link(st):
    """True if this entry redirects to another name (r4, Critical 1).

    `os.path.islink` is NARROWER than the rule it was asked to enforce: on
    Windows it answers False for a junction. Measured on this machine --
    `mklink /J`, then islink False, DirEntry.is_symlink() False, isdir True,
    reparse tag 0xA0000003 -- and `managed_files` duly enumerated
    `linked/smuggled.md` from OUTSIDE the source tree as a managed file.

    That defeats the decided policy at its own terms: total refusal was chosen
    (deltas 093/094) precisely so that no dereference semantics enter this
    engine, and a junction is the Windows way to spell the thing being refused.
    """
    return (stat.S_ISLNK(st.st_mode)
            or bool(getattr(st, "st_reparse_tag", 0) & NAME_SURROGATE))


def path_is_link(path, what):
    """`stat_is_link` for a path, refusing when the answer cannot be had."""
    try:
        return stat_is_link(os.lstat(path))
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise Refusal("%s could not be classified (%s: %s) -- refusing, "
                      "because an entry this engine cannot prove is not a link "
                      "may not be traversed or read: %s"
                      % (what, type(exc).__name__,
                         getattr(exc, "strerror", exc), path))


def scan_tree(root, what, skip_dir=None):
    """Every entry under `root`, classified, or a Refusal -- NOT `os.walk`.

    Returns `[(rel, st), ...]`, /-separated, for every entry that was not
    descended into: files, links of any kind, and nothing else. Directories
    this engine traverses are absent from the result because they were opened;
    directories `skip_dir` excludes are absent because they were skipped.

    Absence must only ever be derived from a traversal that COMPLETED (r3,
    Critical 1). `os.walk` cannot express that, which is what r3's fix missed
    and r4 found: its `onerror` hook fires only when `scandir()` itself fails,
    while an `entry.is_dir()` that raises is swallowed BY DESIGN -- the entry
    is recorded as a non-directory and its whole subtree silently disappears.
    Measured: with `is_dir()` raising on one directory the enumeration returned
    `['blocked', 'ok/a.md']` -- the children gone, the directory itself listed
    as a FILE -- and `onerror` was never called once.

    So the traversal is written out. Every classification below is made from a
    stat this function asked for and got, and every failure to get one refuses
    rather than being absorbed into "not a directory".
    """
    def refuse(exc, where) -> NoReturn:
        raise Refusal("%s could not be enumerated completely (%s: %s) -- "
                      "refusing, because an incomplete walk is "
                      "indistinguishable from a complete one and would "
                      "authorize pruning files it never saw: %s"
                      % (what, type(exc).__name__,
                         getattr(exc, "strerror", exc), where))

    entries = []
    pending = [(Path(root), "")]
    while pending:
        current, prefix = pending.pop()
        try:
            with os.scandir(current) as scan:
                found = list(scan)
        except OSError as exc:
            refuse(exc, current)
        for entry in found:
            rel = prefix + entry.name
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError as exc:
                refuse(exc, entry.path)
            if not stat_is_link(st) and stat.S_ISDIR(st.st_mode):
                if skip_dir is not None and skip_dir(rel):
                    continue
                pending.append((Path(entry.path), rel + "/"))
                continue
            entries.append((rel, st))
    return entries


def managed_files(sc, root):
    """THE enumeration of a managed source tree -- one function, both domains.

    Returns relative paths, /-separated, ordinal-sorted. The COPY phase and the
    MANIFEST are the same list by construction: this is the whole point of the
    slice, because every predicate that used to differ between the two
    enumerations put a file in one domain and not the other, and the stale
    target was then hashed and recorded as the commit's baseline.

    The junk filter is code-point exact (r9 M1): linguistic filters treated
    `.py<U+00AD>c` as `.pyc` and `__PYCACHE__` as `__pycache__`, silently
    dropping committed files from one platform's manifest but not the other's.
    The sort is the engine's ordinal key -- UTF-16 code units, the order every
    recorded baseline was written under.
    """
    # A managed source tree contains NO symlinks, at any level -- root,
    # directory, or non-junk file. DECIDED 2026-08-12 (user pick; deltas
    # 093/094), promoting slice 1's temporary refusal into the permanent
    # semantic now that this function owns the copy too.
    #
    # Measured before deciding, three selectors over one constructed tree: a
    # symlink-to-FILE was installed by the Windows copy (`Get-ChildItem
    # -Recurse -File`), SKIPPED by the Mac copy (`find -type f`, no -L), and
    # manifested by os.walk; a symlinked ROOT gave Windows every file, Mac
    # nothing, os.walk every file. So the asymmetry was Mac-side and Windows
    # -- the development platform -- is why it went unnoticed.
    #
    # Not narrowed to the subset where the old selectors disagreed (a nested
    # symlinked DIRECTORY was skipped by all three): after this slice there is
    # ONE traversal, so "the traversals agree" is not a fact that exists and
    # cannot justify a narrower rule. One traversal can only state a total one.
    #
    # Dereference-with-containment was rejected (delta 094): git records a
    # symlink as a blob whose content is the target PATH STRING, so a manifest
    # hashing the referent and `managed_sources_dirty` reading git would
    # describe one path two ways -- re-creating, at another layer, the very
    # class this slice deletes.
    if path_is_link(root, "managed source root"):
        raise Refusal("managed source root is a symlink or junction, which a "
                      "managed source tree may not contain: %s" % root)
    if not root.is_dir():
        raise Refusal("managed source missing: %s" % root)
    rels = []
    for rel, st in scan_tree(
            root, "managed source tree",
            skip_dir=lambda r: r.rsplit("/", 1)[-1] == "__pycache__"):
        # Junk is excluded FIRST, then the survivors are validated (review r3):
        # junk is installed by nothing, so refusing a symlink named `x.pyc`
        # aborted every full install over an entry that would never have been
        # installed -- an availability regression with no baseline to poison.
        if is_source_junk(rel):
            continue
        # A directory reaches this loop only when it was NOT descended, which
        # for a non-skipped entry means exactly one thing: it is a link.
        if stat_is_link(st):
            raise Refusal(
                "managed source contains a symlink or junction, which a "
                "managed source tree may not contain: %s" % rel)
        rels.append(rel)
    return refuse_casefold_collisions(sorted(rels, key=sc.ordinal_key))


def refuse_casefold_collisions(rels):
    """Two manifest rows whose names differ only by case identify ONE file on
    the case-insensitive filesystems this engine installs onto (R2-M5): no
    correct install exists for both, so the enumeration refuses before
    anything is written. Only a case-SENSITIVE checkout can even hold the
    collision, which is exactly why the machine that installs it never sees
    it coming. This is also what makes prune_tree's case-alias rename
    unambiguous: a manifest can never carry two casefold-equal rows."""
    seen = {}
    for rel in rels:
        folded = str(rel).casefold()
        if folded in seen and seen[folded] != rel:
            raise Refusal("managed sources %r and %r differ only by case -- "
                          "one file on a case-insensitive target; fix the "
                          "repo; aborting before any write"
                          % (seen[folded], rel))
        seen[folded] = rel
    return rels


def refuse_linked_path(root, path, what="managed source"):
    """Refuse if `path`, or ANY component between `root` and it, is a link.

    `root` ITSELF is never checked, and that is the rule, not an oversight: a
    profile directory or a managed tree may legitimately BE a link (a `~/.codex`
    kept in a dotfiles repo is an ordinary setup). What may not happen is a link
    appearing INSIDE, because then two relative paths can name one file, the
    manifest and the backups describe a tree the bytes did not go to, and prune's
    link exemption skips what the copy just wrote through.

    Review r2 on the source side: the leaf check was not enough. Replace an
    intermediate DIRECTORY with a link and the leaf is still an ordinary file,
    so the read follows the link and installs content from outside the tree past
    a policy that had already refused links. Same shape as the ancestor-symlink
    finding `run-suites.py` records: checking the leaf answers about the leaf.

    Review r5 on the TARGET side, where there was no check at all: r4 exempted
    links from PRUNING and stopped there, so all three writers still followed
    one. Measured, each returning success while a file outside the target was
    overwritten: `sync_tree` through a junction (`alpha/victim.md`), and
    `copy_config` and `update_custom_block` through their own. The asymmetry --
    every source component proved, no target component proved -- is the defect;
    the same function now answers both sides.
    """
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if path_is_link(current, "%s path" % what):
            raise Refusal("%s path crosses a symlink or junction, which it may "
                          "not: %s" % (what, current.relative_to(root).as_posix()))


def read_source(sc, repo, *parts):
    """One source file's bytes, read BEFORE any mutation.

    The block sources and the ssh config were still being reopened at mutation
    time after r1's fix covered only the managed trees (r2: the reviewer
    changed `ssh/config.windows` after provenance, let the copy read it,
    restored it, and got `source_dirty=False` over the transient bytes). Every
    source this install can write now enters through here or through
    `snapshot_tree`, and nothing downstream is given a path.
    """
    path = repo.joinpath(*parts)
    refuse_linked_path(repo, path)
    if not path.is_file():
        raise Refusal("Source missing: %s -- aborting before state write."
                      % path)
    return path.read_bytes()


def snapshot_tree(sc, root):
    """{rel: bytes} for a managed source tree, read ONCE, before any write.

    Holding bytes prevents later source edits from reaching targets. The caller
    must separately prove that these captured names and bytes belong to HEAD;
    capturing after a clean status sample alone cannot establish provenance.

    The symlink refusal is RE-CHECKED immediately before each open, over EVERY
    component of the path -- r2 found the first version leaf-only, and a
    replaced intermediate DIRECTORY leaves the leaf an ordinary file. The
    decided policy is about what gets installed, and a path that was clean
    during enumeration can be, or can sit under, a link by the time it is read.
    """
    snapshot = {}
    for rel in managed_files(sc, root):
        full = root.joinpath(*rel.split("/"))
        refuse_linked_path(root, full)
        snapshot[rel] = full.read_bytes()
    return snapshot


def refuse_unsupported_source_modes(sc, repo):
    """A TRACKED managed source must be a regular 100644 blob.

    Content is all that is copied and all that is hashed, so a 100755 source
    would install non-executable on a fresh POSIX profile and no recorded
    baseline would ever show the drift (review r1's closing note). Git is
    asked rather than the filesystem because a Windows checkout does not carry
    the bit at all -- the platform this repo is developed on cannot answer this
    question locally, which is exactly how such a source would ship unnoticed.

    Untracked files carry no mode claim and are not judged here. 120000 is
    unreachable (the enumeration refuses symlinks first) but is named so the
    message stays truthful if that ever changes.
    """
    roots = ["/".join(tree.source) for tree in MANAGED_TREES]
    rc, out = sc.git_lines(repo, "ls-files", "-s", "--", *roots)
    if rc != 0:
        return
    for line in out.splitlines():
        head, _, path = line.partition("\t")
        mode = head.split(" ", 1)[0]
        if mode and mode != "100644" and not is_source_junk(path):
            raise Refusal("managed source is recorded as mode %s; only a "
                          "regular 100644 blob installs faithfully (content "
                          "is copied and hashed, mode is not): %s"
                          % (mode, path))


def ignored_managed_sources(sc, repo):
    """(paths, provable) for managed source files git IGNORES.

    R3-M2's surviving half. One enumeration closed the copy-vs-manifest half
    of that finding, but not this one: `git status` never reports an ignored
    file, so an edit to an ignored managed source cannot make the tree read
    dirty. The install would then record a proven-clean provenance, grant every
    later run the fast path, and keep serving the stale target forever -- the
    false-in-sync class, reached without anything being wrong with the copy.

    Asked ONCE per install and answered by forfeiting the SKIP, not by
    refusing: the install still runs in full and installs current content, so
    the condition costs the fast path and nothing else. Unprovable counts the
    same way, matching managed_sources_dirty's direction.

    Filtered by the enumeration's own junk predicate, or `__pycache__` --
    legitimately ignored and legitimately present -- would forfeit the fast
    path on every machine forever. A non-ASCII path git chooses to quote
    (core.quotePath) fails that predicate and is therefore counted as a real
    ignored source: the conservative direction, one lost fast path.
    """
    roots = ["/".join(tree.source) for tree in MANAGED_TREES]
    rc, out = sc.git_lines(repo, "ls-files", "--others", "--ignored",
                           "--exclude-standard", "--", *roots)
    if rc != 0:
        return [], False
    return [line for line in out.splitlines()
            if line and not is_source_junk(line)], True


def install_provenance(sc, repo):
    """(source_dirty, reason) -- may an install off this tree earn a skip?

    THE provenance question, asked by every caller that has one: the fast-path
    gate, the standalone state writer, and the install flow. Review r1 found it
    asked in two different depths -- `sync_reason` consulted only
    `managed_sources_dirty`, so an ignored managed source appearing after a
    clean baseline left the fast path granting a skip forever while the file
    was never installed at all. A gate that only the WRITE path consults cannot
    forfeit a skip the READ path grants.

    `managed_sources_dirty` is asked first and short-circuits: a tree already
    dirty needs no second query and the answer would not change.

    Anything but a proven-clean answer counts dirty, and a reason is ALWAYS
    returned with it -- a forfeited skip that cannot say why is how a gate gets
    mistaken for a different gate. One extra idempotent full install is the
    cost; a false skip is permanent and silent.
    """
    dirty, provable = sc.managed_sources_dirty(repo)
    if dirty:
        return True, ("uncommitted managed-source edits in the repo" if provable
                      else "managed-source cleanliness cannot be proven "
                           "(git failed, or assume-unchanged/skip-worktree "
                           "flags hide edits)")
    ignored, listable = ignored_managed_sources(sc, repo)
    if ignored:
        return True, ("%d managed source file(s) are git-ignored, so an edit "
                      "to one can never read as dirty (first: %s)"
                      % (len(ignored), ignored[0]))
    if not listable:
        return True, "git could not list ignored managed sources"
    return False, None


def produced_hashes(sc, home, manifests):
    """The three recorded hashes, every one through the producer helpers.

    The tree producer refuses a MISSING or UNREADABLE row, which IS the
    "managed target missing after copy" existence assertion the two state
    writers used to spell separately -- one implementation, and a strictly
    wider one (it also catches present-but-unreadable). A refusal propagates:
    a broken install moment is never a recordable baseline.
    """
    values = {
        "codex_agents": sc.produce_block_hash(sc.codex_home(home) / "AGENTS.md"),
    }
    for tree in MANAGED_TREES:
        values[tree.hash_key] = sc.produce_tree_hash(
            sc.codex_home(home).joinpath(*tree.target[1:]), manifests[tree.manifest_key])
    return values


# --- check-sync -----------------------------------------------------------
def sync_reason(sc, home, repo, platform):
    from scripts.community import findings
    issues = findings(sc, home, repo, platform, hooks=False)
    return "; ".join(issues) if issues else None


def cmd_check_sync(args):
    sc = load_setup_check()
    # --platform is required here for the same reason it is required inside
    # sync_reason (r3, Critical 2): a command that authorizes an installer skip
    # cannot be indifferent to which platform's install it is authorizing.
    reason = sync_reason(sc, args.home, args.repo, args.platform)
    if reason is None:
        return 0
    print("  Not in sync: %s" % reason)
    return 1


# --- write-state ----------------------------------------------------------
def expected_hashes(sc, snapshots, block_texts):
    """The recorded hashes this run's ENGINE-PRODUCED content must yield --
    R2-C4's baseline half. write_state compares what it is about to record
    against these values, so bytes a concurrent target writer put there after
    the sync cannot be certified as the commit's baseline. The content-side
    producers live in the checker beside the live ones: one row format, one
    combiner, one block-topology rule."""
    values = {
        "codex_agents": sc.block_hash_from_text(block_texts["codex"]),
    }
    for tree in MANAGED_TREES:
        values[tree.hash_key] = sc.content_tree_hash(snapshots[tree.manifest_key])
    return values


def write_state(sc, home, repo, platform, manifests=None, source_dirty=None,
                head=None, expected=None, recovery_source=None,
                recovery_digest=None, python_executable=None, update_repo=None):
    """Record the baseline from facts the install flow already established.

    `manifests`, `source_dirty` and `head` are all passed in, and all three are
    the same fix in three fields: ONE install fact, sampled once, before
    anything was written.

    `head` in particular (r2, Critical 2): re-reading HEAD here recorded
    whatever commit existed at STATE-WRITE time, while the bytes installed came
    from the snapshot taken earlier. The reviewer captured commit A's bytes,
    committed B mid-install, and got a state naming B over a target holding A
    -- with `sync_reason` returning None. The recorded commit must name the
    tree the installed content came from, so the caller that took the snapshot
    is the one that supplies it.

    There is no standalone caller any more; this is reached through
    `cmd_install` alone.
    """
    if head is None:
        head = current_commit(sc, repo)
    # Provenance, recorded rather than refused: the hashes below describe what
    # this run actually installed, which stays the truth worth recording (and
    # keeps the checker's drift detection honest) -- what a dirty-source
    # install may NOT do is earn a later skip, because the sources it applied
    # are not recoverable from the commit it names. Unprovable cleanliness
    # counts as dirty: the conservative direction is one extra full install.
    if source_dirty is None:
        # The full gate, not `git status` alone (review r1, Critical 1): a
        # standalone write over an already-installed ignored managed source
        # would otherwise record proven-clean provenance for content no commit
        # contains. Reproduced in that exact sequence before this changed.
        source_dirty, _reason = install_provenance(sc, repo)

    if manifests is None:
        manifests = {tree.manifest_key: managed_files(sc, repo.joinpath(*tree.source))
                     for tree in MANAGED_TREES}
    try:
        files = produced_hashes(sc, home, manifests)
    except sc.ProducerRefusal as exc:
        # A producer refusal right after copying is a broken install moment,
        # never a recordable baseline: refuse the write so the next run
        # re-applies instead of early-exiting over it.
        raise Refusal("%s -- state file NOT written." % exc)
    # R2-C4's baseline half: whatever produced_hashes just read from the live
    # targets must equal the content THIS RUN produced, or the record would
    # certify a concurrent writer's bytes as the commit's baseline (reproduced:
    # arbitrary target bytes recorded, sync_reason None). cmd_install always
    # passes `expected`; test stand-ins may verify a subset.
    for key, digest in sorted((expected or {}).items()):
        if files.get(key) != digest:
            raise Refusal("live target for %s no longer matches the "
                          "engine-produced content (concurrent target writer) "
                          "-- state file NOT written" % key)
    if expected != source_hashes(sc, repo):
        raise Refusal("Source no longer matches captured install content; state not written")

    state = {
        "distribution": "community",
        "source_repo": str(repo.resolve()),
        "source_digest": source_digest(repo),
        "state_schema": sc.STATE_SCHEMA,
        "hash_scope": sc.HASH_SCOPE,
        "platform": platform,
        "applied_at": datetime.datetime.now(datetime.timezone.utc)
                              .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "applied_commit": head,
        "source_dirty": bool(source_dirty),
        "applied_version": ("source:" + sc.sha256_hex(json.dumps(expected, sort_keys=True).encode("utf-8"))
                            if source_dirty else "git:" + head),
        "files": {key: files[key] for key in sc.HASH_KEYS},
        "skills_manifest": manifests["skills_manifest"],
    }
    if recovery_source is not None or recovery_digest is not None:
        if recovery_source is None or recovery_digest is None:
            raise Refusal("recovery source and digest must be recorded together")
        state["recovery_source"] = str(recovery_source)
        state["recovery_digest"] = recovery_digest
    if python_executable is not None:
        state["python_executable"] = str(python_executable)
    if update_repo is not None:
        state["update_repo"] = str(update_repo)
    state_path = sc.codex_home(home) / STATE_REL[-1]
    state_path.parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii keeps the file 7-bit: a manifest name may hold a lone
    # surrogate (the filesystem permits what UTF-8 does not encode), and an
    # escaped \uXXXX round-trips where raw bytes would raise mid-write.
    # Atomic temp + replace, so an interrupted install cannot leave truncated
    # JSON for the next read to choke on.
    staged_write(state_path, (json.dumps(state, indent=2) + "\n").encode("utf-8"),
                 sample_target(state_path))
    print("  State: %s" % state_path)
    return 0


# There is deliberately NO `write-state` subcommand (r2, Critical 3). It had no
# production caller once `install` subsumed it, and as a public entry point it
# was a way to MINT a clean baseline: called without manifests it enumerates
# source names but hashes whatever bytes happen to sit at the targets, never
# proving those bytes came from the source. Reproduced by filling every target
# with unrelated content and obtaining `source_dirty=False` followed by
# `sync_reason() is None`. Deleting the surface is the fix; `write_state` is
# reached through `cmd_install`, which has the snapshot that makes the record
# true.


# --- mutation plane -------------------------------------------------------
# Everything below was spelled TWICE until this slice -- once in PowerShell,
# once in bash -- and the two source ENUMERATIONS are what the transferred
# finding family was made of: any predicate that differed put a file in the
# COPY domain or the MANIFEST domain but not both, and the stale target was
# then hashed and recorded as the commit's baseline. `sync_tree` is handed the
# list `managed_files` produced, so the two domains are the same list rather
# than two traversals kept in step. That is the class ending by deletion.
#
# Platform residue is PARAMETERIZED, never forked: the ssh source name, the
# POSIX mode applied to it, and the recorded `platform` field. Nothing else
# below may ask which platform it is on.

MARKER_START = "<!-- DEV-SETUP-CODEX:START -->"
MARKER_END = "<!-- DEV-SETUP-CODEX:END -->"
BACKUP_KEEP = 3
PREREQS = ("codex",)
SSH_SOURCE = {"windows": ("ssh", "config.windows"),
              "mac": ("ssh", "config.mac")}
SSH_POSIX_MODE = 0o600


_UNREADABLE = object()


def sample_target(target):
    """The ONE raw read of an install target: the same bytes are decided
    over, backed up verbatim, and compared by the staged writer. None when
    the target does not exist; an unreadable existing target is a Refusal,
    because its exact bytes cannot be backed up (R2-C4) -- aborting here is
    before any write."""
    try:
        if not target.is_file():
            return None
        return target.read_bytes()
    except OSError as exc:
        raise Refusal("cannot read install target %s (%s) -- its exact bytes "
                      "cannot be backed up; aborting before any write"
                      % (target, type(exc).__name__))


def staged_write(target, content, sampled):
    """Temp-in-directory + atomic replace -- the R2-C4 / delta-107 write shape.

    * A NEW inode: a hard link to the old target keeps the old bytes at its
      own name, instead of watching managed content change under it (the old
      in-place truncate propagated installer bytes through `mklink /H`).
    * Conflict-detecting: the target is re-read just before the replace and
      compared to `sampled` -- the bytes the caller read, decided over, and
      backed up. An intervening writer is a Refusal with nothing replaced. A
      true compare-and-swap does not exist on either filesystem, so the
      residual window is the read-to-replace gap, named rather than claimed
      away; write_state's expected-hash gate covers the post-write half.
    * Mode-preserving on POSIX: an in-place truncate kept the target's mode,
      a fresh temp file must copy it; a NEW target gets 0o644 (the umask
      default the old write produced).
    """
    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".staged.",
                                    dir=str(target.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        mode = None
        try:
            current = target.read_bytes() if target.is_file() else None
            if current is not None and os.name == "posix":
                mode = stat.S_IMODE(os.stat(target).st_mode)
        except OSError:
            current = _UNREADABLE
        if current != sampled:
            raise Refusal("%s changed between sampling and write (concurrent "
                          "writer) -- nothing replaced; re-run the install"
                          % target)
        if os.name == "posix":
            os.chmod(tmp, mode if mode is not None else 0o644)
        os.replace(tmp, target)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def write_exact(path, text, sampled):
    """UTF-8, no BOM, no newline translation -- WriteAllText's semantics,
    through the staged writer. Encoding to BYTES here is what makes the write
    translation-free by construction (the retired text-mode open needed an
    explicit newline='' guard for the same property). A changed UTF-16 target
    is rewritten as UTF-8, which is what the retired PowerShell updater did
    too; an UNCHANGED one is never written at all, so its original bytes
    survive.
    """
    staged_write(path, text.encode("utf-8"), sampled)


def prune_backups(sc, target, keep=BACKUP_KEEP):
    """Keep the newest `keep` of `<target>.bak.*`.

    Name-sorted descending, as both installers did -- but on the engine's
    ORDINAL key, because PowerShell's Sort-Object is culture-aware while the
    Mac side sorted bytes, and this file does not keep two orders.
    `installer_support.backup_file` ranks by mtime for a different caller;
    adopting that here would change retention this migration is not entitled
    to change.
    """
    try:
        olds = [p for p in target.parent.glob(target.name + ".bak.*")
                if p.is_file()]
    except OSError:
        return
    olds.sort(key=lambda p: sc.ordinal_key(p.name), reverse=True)
    for old in olds[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def backup(sc, target, stamp, content):
    """Write `content` -- the exact bytes the caller sampled and decided
    over -- aside, and trim the old backups.

    shutil.copyfile here was a SECOND read of a live target (R2-C4): an
    editor landing between the sample and the copy put ITS bytes in the
    backup while the sampled bytes -- the ones about to be destroyed -- went
    nowhere. The backup now holds what the replace replaces, by construction.

    allocate_backup is installer_support's. Each installer carried its own
    re-spelling of it "for parity"; parity maintained by hand across two
    languages is the thing being deleted here.
    """
    spare = allocate_backup(target, stamp)
    spare.write_bytes(content)
    prune_backups(sc, target)
    return spare


def update_custom_block(sc, source, target, stamp):
    """Replace the USER:CUSTOM region of `target`, or append it.

    Only two topologies are writable: NO markers (append) or exactly one
    ordered pair (replace). Anything else -- reversed, duplicate pairs, an
    extra END, a lone marker -- refuses EARLY, before any write, because a
    lone START made the append path produce a two-START mangle that the
    producer then recorded as the baseline.

    Ordinal by construction: `str.find`/`str.count`/`==` are code-point exact
    in Python, where the PowerShell original had to say so explicitly at four
    sites (one-argument IndexOf is culture-sensitive and matched pseudo-markers
    containing default-ignorable characters, and string -eq is linguistic, so
    a casing-only policy change read "No changes" and the stale block stayed
    installed as this commit's clean baseline).
    """
    # sc.dotnet_trim_end, never str.rstrip (review r1, Critical 3): Python treats
    # U+001C..U+001F as whitespace and .NET's Char.IsWhiteSpace does not, so
    # rstrip() DELETES those characters from a markerless user file that ends
    # in one. The checker already defines the .NET-compatible set for exactly
    # this reason; spelling it again here is how the two would drift.
    new_block = sc.dotnet_trim_end(sc.decode_all_text(source))
    # The leaf may not be a link (r5). Its directory may be -- the root rule in
    # refuse_linked_path -- but a linked leaf means `backup` renames the LINK
    # while the write lands a regular file at the original path, silently
    # replacing the user's arrangement and backing up the wrong thing.
    refuse_linked_path(target.parent, target, "install target")
    target.parent.mkdir(parents=True, exist_ok=True)
    # ONE raw read (R2-C4): the sampled bytes are decoded for the merge,
    # backed up verbatim, and compared by the staged writer -- through the
    # checker's one decoder, which is BOM-detected (review r1, Major 5: a
    # UTF-8-only reader aborted over a UTF-16 target the checker hashes fine)
    # and newline-translation-free by construction because it decodes bytes.
    raw = sample_target(target)
    current = sc.decode_all_text(raw) if raw is not None else None

    if current is None:
        updated = new_block + "\n"
    else:
        start, end = current.find(MARKER_START), current.find(MARKER_END)
        starts, ends = current.count(MARKER_START), current.count(MARKER_END)
        if (starts, ends) != (0, 0) and not (starts == 1 and ends == 1
                                             and end > start):
            raise Refusal("Corrupt USER:CUSTOM markers (topology is not "
                          "exactly one START then one END) in %s -- fix the "
                          "file; aborting before any write." % target)
        if start >= 0 and end >= 0:
            updated = (current[:start] + new_block
                       + current[end + len(MARKER_END):])
        else:
            updated = sc.dotnet_trim_end(current) + "\n\n" + new_block + "\n"

    if current == updated:
        print("  No changes: %s" % target)
        return new_block
    if raw is not None:
        backup(sc, target, stamp, raw)
    write_exact(target, updated, raw)
    print("  Updated: %s" % target)
    return new_block


def copy_config(sc, content, target, stamp, posix_mode=None):
    """Whole-file install from bytes taken before any mutation began.

    Takes CONTENT, not a path: r2 reproduced the path version by changing
    `ssh/config.windows` after provenance was sampled, letting the copy read
    it, and restoring the source -- `source_dirty=False` was recorded over
    bytes no commit contains. A missing source is refused where it is READ
    (`read_source`), which is before anything has been written.
    """
    # Same leaf rule as update_custom_block (r5): measured, this wrote
    # "INSTALLER BYTES" through a junction into a file outside the profile and
    # returned success.
    refuse_linked_path(target.parent, target, "install target")
    target.parent.mkdir(parents=True, exist_ok=True)
    sampled = sample_target(target)
    if sampled == content:
        print("  No changes: %s" % target)
    else:
        if sampled is not None:
            backup(sc, target, stamp, sampled)
        staged_write(target, content, sampled)
        print("  Copied: %s" % target)
    # Applied on every run, not only when the copy happened -- the mode is a
    # property of the target, and the Mac installer enforced it unconditionally
    # after copy_config for exactly that reason.
    if posix_mode is not None and os.name == "posix":
        # A failed chmod is REFUSED, never swallowed (r3, Major 3). The mode is
        # a declared part of what this install applies, and the recorded hashes
        # cover content only -- so a swallowed failure ships a world-readable
        # ssh config that every later run then certifies as in sync.
        try:
            os.chmod(target, posix_mode)
        except OSError as exc:
            raise Refusal("could not set mode %04o on %s (%s) -- state file "
                          "NOT written; nothing downstream records the mode, "
                          "so a swallowed failure would never be reported"
                          % (posix_mode, target, type(exc).__name__))


def sync_tree(sc, target_root, snapshot, recorded, label, stamp):
    """Install the snapshot, then prune within the recorded scope.

    The snapshot's KEYS are the manifest -- the same list this run records --
    and its VALUES are the bytes that get written. There is no second
    traversal to disagree with the manifest (R1-M1/R2-M1/R3-M1/R4-M1 and the
    copy half of R3-M2 were each an instance of that), and no source path is
    reopened here at all, which is what closes r1's Critical 2. This function
    cannot reach the source tree: it is not given it.

    A missing source root is not re-checked here: `managed_files` refused it
    while the snapshot was built, before any target was touched.
    """
    target_root.mkdir(parents=True, exist_ok=True)
    changes = 0
    for rel, content in snapshot.items():
        target = target_root.joinpath(*rel.split("/"))
        # Before the mkdir, before the write: nothing under this root may be a
        # link (r5). The root may be one; see refuse_linked_path.
        refuse_linked_path(target_root, target, "install target")
        target.parent.mkdir(parents=True, exist_ok=True)
        sampled = sample_target(target)
        if sampled == content:
            continue
        if sampled is not None:
            backup(sc, target, stamp, sampled)
        staged_write(target, content, sampled)
        print("  %s updated: %s" % (label, rel))
        changes += 1
    changes += prune_tree(sc, target_root, set(snapshot), recorded, label, stamp)
    if changes == 0:
        print("  No %s changes" % label.lower())


def prune_tree(sc, target_root, installed, recorded, label, stamp):
    """Remove target files this repo installed and no longer ships.

    Scope is the PREVIOUS install's recorded manifest: a file this repo never
    proved it managed is left untouched, and with no recorded manifest at all
    non-junk pruning is skipped for that run. Pruned managed files are BACKED
    UP, never bare-deleted; junk is removed only inside managed roots.

    Membership is decided against `installed` -- the very list just copied --
    rather than by re-testing the source filesystem, so a source entry the
    enumeration excluded cannot read as "still shipped" here.
    """
    # TWO PHASES (r3, Critical 1): the target is enumerated COMPLETELY, and any
    # traversal error refuses, BEFORE a single file is touched. Deriving
    # "absent from the source" out of a walk that silently skipped a subtree is
    # how an unreadable directory leaves a retired policy live while its prune
    # authority drops out of the new manifest -- and pruning as we went would
    # additionally have mutated the tree before the error surfaced.
    managed_roots = {rel.split("/", 1)[0] for rel in installed | (recorded or set())}
    entries = scan_tree(target_root, "managed target tree",
                        skip_dir=lambda rel: rel.split("/", 1)[0] not in managed_roots)

    changes = unmanaged = skipped = 0
    installed_folded = {k.casefold(): k for k in installed}
    for rel, st in entries:
        # A LINK in a target is never ours. This engine writes regular files
        # and only regular files, so nothing it recorded can be a link today
        # without someone else having put it there -- and following one is how
        # a junction in the target turns prune into a delete OUTSIDE the tree
        # (r4: `os.walk` does not descend a symlink but does descend a
        # junction, because it asks `os.path.islink`). Not descended, not
        # pruned, not backed up.
        if stat_is_link(st):
            unmanaged += 1
            continue
        if rel.split("/", 1)[0] not in managed_roots:
            continue
        full = target_root / rel
        name = full.name
        if rel in installed:
            continue
        # R2-M5: on a case-insensitive filesystem this disk entry and an
        # installed manifest row can be ONE file under two spellings, and a
        # case-only source rename made this loop move the just-installed file
        # to backup. The manifest never carries two casefold-equal rows
        # (refuse_casefold_collisions), so the alias is unambiguous: adopt the
        # manifest's exact spelling, never prune. On a case-SENSITIVE target
        # holding BOTH spellings the stale one is a genuinely distinct file
        # and falls through to the ordinary prune below.
        alias = installed_folded.get(rel.casefold())
        if alias is not None:
            alias_path = target_root / alias
            try:
                distinct = alias_path.exists() and not os.path.samefile(full, alias_path)
            except OSError:
                distinct = True
            if not distinct:
                full.replace(alias_path)
                print("  %s case-renamed: %s -> %s" % (label, rel, alias))
                changes += 1
                continue
        # ORDER IS THE RULE (review r1, Major 4). The `.bak.` exemption
        # used to run FIRST, which made it beat both of the guarantees
        # below: `__pycache__/x.bak.old` survived "junk is always removed",
        # and a managed file whose own name contains `.bak.` -- proven ours
        # by the recorded manifest -- could never be pruned once dropped
        # from the repo, so a retired skill kept firing forever and the new
        # state no longer listed it for anything to notice. Both installers
        # had that ordering; unifying them is what made it one rule worth
        # fixing rather than two.
        if (JUNK_DIR.search(rel) or rel.endswith(".pyc")) and recorded is not None and rel in recorded:
            # A failed deletion is REFUSED, never swallowed (r2, Major 6).
            # Junk is absent from every manifest, so no later hash can
            # notice that it is still there: the run would print nothing,
            # report zero changes, write state and fast-path forever over a
            # contract ("junk is always removed") it had just broken. A
            # read-only or locked file reproduces it.
            try:
                full.unlink()
            except OSError as exc:
                raise Refusal("junk could not be removed (%s): %s -- "
                              "state file NOT written, because nothing "
                              "downstream can detect that it is still "
                              "there" % (type(exc).__name__, rel))
            print("  Junk pruned: %s" % rel)
            changes += 1
            continue
        if recorded is not None and rel in recorded:
            full.replace(allocate_backup(full, stamp))
            prune_backups(sc, full)
            print("  %s pruned (backed up): %s" % (label, rel))
            changes += 1
            continue
        # Only now: a file that is neither shipped, nor junk, nor ever
        # recorded as ours. OUR OWN backups live here -- matched on the
        # NAME, ordinally. PowerShell matched a case-insensitive regex on
        # the name while the Mac side glob-matched the whole PATH, so a
        # file under a directory named `x.bak.y/` was exempt on one
        # platform only; the name is the property that means "backup".
        if ".bak." in name:
            continue
        if recorded is None:
            skipped += 1
            continue
        unmanaged += 1
    if skipped:
        print("  Migration run (no manifest recorded yet): skipped pruning %d "
              "file(s); next run is manifest-scoped" % skipped)
    if unmanaged:
        print("  Left untouched: %d file(s) not managed by this repo"
              % unmanaged)
    # Do not sweep the whole target tree: unmanaged empty directories belong to
    # other generators. Empty parents of pruned managed files are harmless.
    return changes


def recorded_manifest(sc, state, key):
    """The previous run's prune authority, or None when it cannot be proven.

    Fail-closed at the same boundary both installers guarded: only a real list
    OF STRINGS is authority, because a coerced scalar or a nested array would
    authorize pruning a file the repo never proved it managed.
    """
    value = state.get(key)
    return set(value) if sc.is_str_list(value) else None


# --- helper processes -----------------------------------------------------
def python_exe():
    return os.path.abspath(sys.executable)


def run_helper(*argv):
    """Run a harness helper with stdio inherited, so its own report reaches
    the user exactly as it did when the shells invoked it."""
    return subprocess.run([str(item) for item in argv]).returncode


def check_prereqs():
    missing = [name for name in PREREQS if shutil.which(name) is None]
    if missing:
        print("Prereq warning: missing -> %s" % ", ".join(missing))
        print("  See BOOTSTRAP.md for install steps. Continuing anyway.\n")


def run_lint(repo):
    quiet = subprocess.run([python_exe(), "-c", "import yaml"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if quiet.returncode != 0:
        print("WARNING: PyYAML missing for '%s' -- wiki-lint will not run "
              "until it is installed for that interpreter." % python_exe())
    if run_helper(python_exe(), repo / "scripts" / "lint.py"):
        raise Refusal("Lint failed. Fix above before installing.")


def _absolute_state_path(state, key, required=False):
    if key not in state:
        if required:
            raise Refusal("installation state is missing " + key)
        return None
    value = state[key]
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise Refusal("installation state has invalid " + key)
    return Path(value)


def prepare_install_recovery(args):
    sc = load_setup_check()
    root = sc.codex_home(args.home).absolute()
    state_path = root / STATE_REL[-1]
    original_state = sample_target(state_path)
    original_hooks = sample_target(root / "hooks.json")
    state = load_state(state_path)
    update_repo = None

    if isinstance(state, dict) and state.get("distribution") == "community" and sc.state_schema_current(state):
        prior_snapshot = source_recovery.state_snapshot(state, root, verify=False)
        prior_repo = _absolute_state_path(state, "source_repo", required=True)
        prior_update = _absolute_state_path(state, "update_repo")
        if "python_executable" in state and (not isinstance(state["python_executable"], str)
                                               or not Path(state["python_executable"]).is_absolute()):
            raise Refusal("installation state has invalid python_executable")
        if prior_snapshot is not None and os.path.normcase(os.path.abspath(prior_repo)) == os.path.normcase(
                os.path.abspath(prior_snapshot)) and os.path.normcase(os.path.abspath(args.repo)) == os.path.normcase(
                os.path.abspath(prior_snapshot)):
            update_repo = prior_update

    current_python = validate_python(python_exe(), require_yaml=True)
    prepared = source_recovery.prepare(args.repo)
    recovery_source = source_recovery.publish(root, prepared)
    args.recovery_source = recovery_source
    args.recovery_digest = prepared.digest
    args.python_executable = current_python
    args.update_repo = update_repo
    args.prior_state_expected = original_state
    args.prior_hooks_expected = original_hooks


# --- install --------------------------------------------------------------
def apply_install(args):
    sc = load_setup_check()
    home, repo, platform = args.home, args.repo, args.platform
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

    print("=== dev-setup-codex install (%s) ===" % platform)
    print("Repo: %s\n" % repo)
    check_prereqs()
    print("[0] Lint")
    run_lint(repo)
    print("")

    print("[0a] Native hooks")
    if run_helper(python_exe(), ENGINE_DIR / "native-hooks.py", "install",
                   "--home", sc.codex_home(home), "--repo", repo,
                   "--python", args.python_executable):
        raise Refusal("Native hook installation failed; managed outputs were not applied.")

    if not args.force:
        reason = sync_reason(sc, home, repo, platform)
        installed = load_state(sc.codex_home(home) / STATE_REL[-1]) or {}
        saved_python = installed.get("python_executable")
        if reason is None and (not isinstance(saved_python, str)
                               or os.path.normcase(os.path.abspath(saved_python)) != os.path.normcase(
                                   os.path.abspath(args.python_executable))):
            reason = "installed Python differs; refreshing hooks and state"
        if reason is None:
            print("In sync: community source content -- skipping. Use --force to re-apply.")
            return 0
        print("  Not in sync: %s" % reason)

    # Capture before mutation, then bind the captured names and bytes to HEAD.
    # Status checks cannot detect an edit captured and reverted between checks.
    refuse_unsupported_source_modes(sc, repo)
    source_dirty, note = True, "content-addressed community distribution"
    if note:
        print("  Provenance: %s -- recording this install as unprovable, "
              "which forfeits the fast path" % note)
    head = current_commit(sc, repo)
    initial_digest = source_digest(repo)
    snapshots = {tree.manifest_key: snapshot_tree(sc, repo.joinpath(*tree.source))
                 for tree in MANAGED_TREES}
    sources = {
        "codex_block": read_source(sc, repo, "codex", "AGENTS.md"),
    }
    # HEAD is read once, BEFORE the snapshot, and that value is what gets
    # recorded -- the recorded commit has to name the tree the installed bytes
    # came from. If it moved while the snapshot was being taken, the snapshot
    # straddles two commits and belongs to neither, which is exactly what
    # "unprovable" means (r2, Critical 2).
    captured = SourceSnapshot(
        {**{"/".join((*tree.source, rel)): content
            for tree in MANAGED_TREES
            for rel, content in snapshots[tree.manifest_key].items()},
         "codex/AGENTS.md": sources["codex_block"]},
        tuple("/".join(tree.source) for tree in MANAGED_TREES)
        + ("codex/AGENTS.md",),
    )
    if (current_commit(sc, repo) != head
            or (not source_dirty and not snapshot_matches_commit(repo, head, captured))):
        source_dirty = True
        print("  Provenance: captured sources cannot be attributed to HEAD -- recording "
              "it as unprovable, which forfeits the fast path")
    manifests = {key: sorted(snapshot, key=sc.ordinal_key)
                 for key, snapshot in snapshots.items()}
    recorded = load_state(sc.codex_home(home) / STATE_REL[-1]) or {}

    print("[1] Codex AGENTS.md DEV-SETUP-CODEX block")
    codex_block = update_custom_block(sc, sources["codex_block"],
                                      sc.codex_home(home) / "AGENTS.md", stamp)


    for tree in MANAGED_TREES:
        print("\n%s" % tree.banner)
        sync_tree(sc, sc.codex_home(home).joinpath(*tree.target[1:]),
                  snapshots[tree.manifest_key],
                  recorded_manifest(sc, recorded, tree.manifest_key),
                  tree.label, stamp)
    if source_digest(repo) != initial_digest:
        raise Refusal("Source changed during installation; state not written")
    if source_recovery.prepare(repo).digest != args.recovery_digest:
        raise Refusal("Recovery source changed during installation; state not written")
    print("\n[5] State file")
    write_state(sc, home, repo, platform, manifests, source_dirty, head,
                expected=expected_hashes(sc, snapshots,
                                         {"codex": codex_block}),
                recovery_source=args.recovery_source,
                recovery_digest=args.recovery_digest,
                python_executable=args.python_executable,
                update_repo=args.update_repo)

    print("\n=== Done ===")
    return 0


def cmd_install(args):
    from scripts import lifecycle
    if getattr(args, "dry_run", False):
        return lifecycle.preview(sys.modules[__name__], args)
    run_lint(args.repo)
    prepare_install_recovery(args)
    return lifecycle.install(sys.modules[__name__], args, apply_install)


def cmd_preview(args):
    from scripts import lifecycle
    return lifecycle.preview(sys.modules[__name__], args)


def cmd_restore(args):
    from scripts import lifecycle
    return lifecycle.restore(sys.modules[__name__], args, args.command == "uninstall")


def main(argv=None):
    if sys.version_info < (3, 11):
        print("Python 3.11+ is required; no installation changes were made.", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(description=(__doc__ or "Codex install engine").splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    for name, handler in (("check-sync", cmd_check_sync),
                          ("install", cmd_install), ("preview", cmd_preview),
                          ("rollback", cmd_restore), ("uninstall", cmd_restore)):
        parser = sub.add_parser(name)
        parser.add_argument("--home", type=Path, required=True,
                            help="profile root holding .codex/.ssh; CODEX_HOME overrides .codex")
        parser.add_argument("--repo", type=Path, required=True,
                            help="the dev-setup clone being applied")
        # Both subcommands require it: `install` records it, `check-sync`
        # compares it, and neither may decide about a skip without it.
        parser.add_argument("--platform", required=True,
                            choices=("windows", "mac"),
                            help="recorded in, and compared against, the state")
        if name in ("rollback", "uninstall"):
            parser.add_argument("--apply", action="store_true", help="apply the displayed recovery plan")
        if name == "install":
            parser.add_argument("--dry-run", action="store_true", help="preview without writing")
            parser.add_argument("--force", action="store_true",
                                help="re-apply even when proven in sync")
        parser.set_defaults(handler=handler)
    args = ap.parse_args(argv)

    # Findings can carry manifest-derived text and the console encoding is the
    # INVOKER's; a tool must never crash on its own report.
    for stream in (sys.stdout, sys.stderr):
        try:
            if isinstance(stream, TextIOWrapper):
                stream.reconfigure(errors="replace")
        except (AttributeError, OSError):
            pass

    # Only the named refusals are converted to a message + exit 1. Anything
    # else propagates as a traceback and still exits nonzero -- which both
    # call sites read as "do not skip" / "do not record", so an unforeseen
    # failure lands on the safe side WITHOUT this file having to anticipate
    # it. Nothing here may return 0 on an error path.
    try:
        return args.handler(args)
    except (Refusal, ValueError, OSError, RuntimeError) as exc:
        print("  %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
