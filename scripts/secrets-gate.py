#!/usr/bin/env python3
"""Secrets gate over staged and tracked content, reusing the ask-preflight
pattern set.

Modes -- and what each one actually reads, which is not the same thing:
  secrets-gate.py staged [--repo PATH]   the INDEX, through plumbing only:
                                         `diff-index --raw` for the changed
                                         paths and their exact blob ids, then
                                         `cat-file` for the bytes, with added
                                         lines computed in-process. Plus the
                                         registry blob staged alongside them.
                                         While this gate is the one executing,
                                         it exits 2 before scanning if a
                                         present enforcement source differs
                                         from its index version -- a coherence
                                         check, NOT tamper resistance; see
                                         Gate.enforcement_errors (git
                                         pre-commit)
  secrets-gate.py tree   [--repo PATH]   tracked PATHS from the index, and
                                         regular-file CONTENT from the working
                                         filesystem -- tracked SYMLINK content
                                         comes from the index blob instead, so
                                         both modes hash the committed bytes
                                         (CI backstop); additionally enforces
                                         registry hygiene: expired or unmatched
                                         exception entries fail the run

Neither mode reads history, reflog, or unreachable objects. What that excludes
is content no longer present in what is scanned: a secret still in the current
tree IS scanned by tree mode even if it was committed years ago, while one
removed from the tree survives in history until history is rewritten. Tree mode
covers the checkout it runs on and nothing else -- in CI that is the submitted
tree, where working filesystem and index agree. It is a post-push, current-tree
backstop, not an authority over every commit that got past the local hook.

--repo defaults to this script's own repo checkout; tests point it at fixture
repos. The pattern set is always loaded from the checkout the script lives in.

Exceptions live in the registry secrets-exceptions.json at the scanned repo's
root -- never inline pragmas (a pragma beside a secret is an easy bypass). It is
called "reviewed" for the workflow around it, not for anything the code proves:
what is enforced is registration, entry shape, digest match and expiry. Whether
a human read the entry, and whether its `reason` is true, are outside the tool.
Entry shape: {"path", "rule", "sha256", "reason", "expires"} where
sha256 is over the matched line with trailing whitespace stripped (for the
credential-file path rule: over the repo-relative path string), and expires is
a UTC YYYY-MM-DD date. Expired entries never suppress. Every suppression is
printed, so exceptions stay visible in output.

Findings never print matched content -- only path[:line] (the credential-file
path rule has no line to report), rule name, and the sha256 a registry entry
would need. Registry reasons are validated at load
(control characters and rule-matching content are rejected) because they are
echoed into gate and CI output.

Both modes read bytes as lossily-decoded UTF-8 and apply textual rules, so what
they catch inside a binary payload is an ASCII-compatible known-pattern
sequence -- not a DER certificate body, a UTF-16 payload, or anything
compressed or encrypted. Those reach the credential-file name rule or nothing.

Exit: 0 clean, 1 blocked, 2 HANDLED usage/environment error. An unhandled
exception exits nonzero too (main() catches RuntimeError only), which is why
hook callers treat any nonzero exit as a block rather than reading the code.
"""
import collections
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Literal, overload

SCRIPT_REPO = Path(__file__).resolve().parents[1]
PREFLIGHT_PATH = SCRIPT_REPO / "skills" / "ask" / "scripts" / "ask-preflight.py"
REGISTRY_NAME = "secrets-exceptions.json"
PATH_RULE = "credential-file"
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
DATE_FMT = "%Y-%m-%d"
# Index modes whose object is a blob this tool may read. A gitlink (160000) is
# a commit and a directory entry (040000) a tree, so both are path-scanned and
# never handed to cat-file. Asked of the MODE and asserted again of the object
# type, because the two are independent: an index can record 100644 against a
# commit id, which is how a predicted-fail-closed case turned out to succeed.
BLOB_MODES = ("100644", "100755", "120000")
NULL_OID = "0" * 40

# GIT_* variables the child git KEEPS, as an allowlist. A denylist is the shape
# unit G proved does not converge: every knob is a separate blind spot found
# only by someone who thinks to ask about that knob, so the enumeration that
# has to be complete must be the SMALL one. These six are kept because they
# select which repository and which index the parent operation is working on --
# clearing them would make the gate scan something other than the commit being
# made, which is the same defect as reading the wrong registry, pointed at the
# content instead. Everything else GIT_* is dropped, including the ones the
# gate's own comment used to list as known-open: GIT_DIFF_OPTS,
# GIT_CONFIG_COUNT/KEY/VALUE, GIT_ICASE_PATHSPECS, GIT_ATTR_SOURCE,
# GIT_EXTERNAL_DIFF. Non-GIT_ variables are left alone: HOME and PATH select
# the git binary and its global config, and clearing them would change
# behaviour in ways this gate has no reason to want.
GIT_ENV_KEEP = frozenset((
    "GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
))

# Executed from the WORKING TREE on every staged run, so an unstaged edit to
# any of them changes the verdict without appearing in the commit.
ENFORCEMENT_SOURCES = ("githooks/pre-commit", "scripts/secrets-gate.py",
                       "skills/ask/scripts/ask-preflight.py")


def load_preflight():
    spec = importlib.util.spec_from_file_location("ask_preflight", PREFLIGHT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ask-preflight.py owns the pattern set, but this gate applies it by hand:
# line_rules() below plus CREDENTIAL_PATH. A pattern added there and not
# classified here is silently unenforced at commit time, so every preflight
# pattern must appear in one of the two or be named EGRESS_ONLY. DIFF_PATH is
# egress-only because it recovers a path out of diff *text*; the gate is handed
# real paths by git and never has to parse them back. The suite fails on an
# unclassified pattern -- the parity is checked, not remembered.
EGRESS_ONLY = ("DIFF_PATH",)


def line_rules(pf):
    return {
        "private-key": pf.PRIVATE_KEY,
        "known-credential": pf.KNOWN_SECRET,
        "url-credential": pf.URL_CREDENTIAL,
        "assignment": pf.ASSIGNMENT,
        "npm-auth": pf.NPM_AUTH,
        "bearer": pf.BEARER,
    }


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_registry(raw_text, today):
    """Return (entries, errors) for registry text (None = no registry).
    Malformed registry is a hard error: a gate that silently ignores its
    exception file either blocks known-good commits or -- worse -- someone
    'fixes' that by weakening the patterns."""
    if raw_text is None:
        return [], []
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return None, ["registry unreadable: %s" % type(exc).__name__]
    if not isinstance(raw, list):
        return None, ["registry must be a JSON list"]
    errors = []
    entries = []
    seen = set()
    for i, item in enumerate(raw):
        label = "entry %d" % i
        if not isinstance(item, dict) or set(item) != {
                "path", "rule", "sha256", "reason", "expires"}:
            errors.append(label + ": exactly path/rule/sha256/reason/expires required")
            continue
        if not all(isinstance(item[k], str) and item[k] for k in item):
            errors.append(label + ": all fields must be non-empty strings")
            continue
        if not SHA256_HEX.match(item["sha256"]):
            errors.append(label + ": sha256 must be 64 lowercase hex chars")
            continue
        try:
            expires = datetime.datetime.strptime(item["expires"], DATE_FMT).date()
        except ValueError:
            errors.append(label + ": expires must be YYYY-MM-DD")
            continue
        key = (item["path"], item["rule"], item["sha256"])
        if key in seen:
            errors.append(label + ": duplicate of an earlier entry")
            continue
        seen.add(key)
        entries.append({"key": key, "reason": item["reason"], "expires": expires,
                        "expired": expires < today, "used": False})
    return entries, errors


def nul_split(blob):
    # Strict, and a hard error rather than a replacement character: git stores
    # paths as bytes, and a lossy decode yields a DIFFERENT pathname.
    #
    # The original reason is now weaker than it was, and the note is kept
    # narrowed rather than deleted: the old parser fed that decoded name back to
    # git as a pathspec, so a lossy decode matched nothing, exited 0 empty, and
    # skipped the staged content in silence. Content now arrives by destination
    # OID, so it can no longer vanish that way. What a bad decode still corrupts
    # is the path RULE and every reported path and digest -- the finding would
    # name a file that does not exist, and its registry entry could never be
    # written. POSIX-only in practice (Windows filenames are UTF-16 and git
    # stores them as UTF-8), which is why it fails closed rather than being
    # assumed away on this machine.
    try:
        return [p.decode("utf-8") for p in blob.split(b"\0") if p]
    except UnicodeDecodeError:
        raise RuntimeError("path is not valid UTF-8; rename it before committing")


def _newlines(text):
    return None if text is None else text.replace("\r\n", "\n")


def blob_lines(data):
    """Blob bytes -> scannable lines, identically for both modes.

    LF-only split: str.splitlines() also breaks on \\x85 / \\u2028 etc., which
    git does not treat as line separators -- the fragment after such a byte
    would silently escape scanning. Shared rather than written twice because
    the two modes must agree on where a line ends: they hash the line they
    matched, and a registry entry written from one mode has to resolve in the
    other.

    Binary payloads land here too, lossily decoded, so what is caught inside
    one is an ASCII-compatible known-pattern sequence -- not a DER certificate
    body, a UTF-16 payload, or anything compressed or encrypted.
    """
    lines = data.decode("utf-8", "replace").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


class Gate:
    def __init__(self, mode, root):
        self.mode = mode
        self.root = root
        self.today = datetime.datetime.now(datetime.timezone.utc).date()
        self.notes = []
        self._base = None
        # FIRST, before load_preflight() below imports and EXECUTES the pattern
        # module. Checking a file for drift after running it verifies nothing
        # about the run that already happened, and the pattern module is the one
        # enforcement source whose "execution" is an import rather than a
        # subprocess -- which is what made the ordering easy to get wrong. Held
        # rather than raised so run() reports it beside any registry error.
        self.blocking_errors = self.enforcement_errors() if mode == "staged" else []
        self.findings, self.suppressed = [], []
        # The registry is READ either way -- it reads an index blob and parses
        # JSON, executing nothing from the working tree, so it is safe on the
        # refusal path and its diagnostics are exactly what a user hitting that
        # refusal needs. Skipping it made this comment's own promise false.
        raw, read_errors = self.read_registry()
        if read_errors:
            self.entries, self.registry_errors = None, read_errors
        else:
            self.entries, self.registry_errors = load_registry(raw, self.today)
        if self.blocking_errors:
            # Return before load_preflight(), which IMPORTS the pattern module
            # from the working tree. Recording the error and carrying on would
            # still execute the unverified module -- the whole defect, not a
            # tidiness point: a refusal has to STOP execution, not annotate it.
            # Only the reason-validation loop below is lost, and it is the one
            # part that needs the unverified patterns to run at all.
            return
        preflight = load_preflight()
        self.rules = line_rules(preflight)
        self.path_pattern = preflight.CREDENTIAL_PATH
        # Reasons are printed verbatim in suppression lines and CI logs: reject
        # control characters and anything the scan rules themselves would flag.
        # The guarantee is exactly as wide as the rules -- a mistaken reason
        # cannot re-leak a secret these patterns would catch in content, and a
        # shape they miss in content they miss in a reason too. It is the same
        # finite pattern set, not an independent check.
        for entry in self.entries or []:
            label = "entry %s %s" % (entry["key"][0], entry["key"][1])
            reason = entry["reason"]
            if any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in reason):
                self.registry_errors.append(label + ": reason contains control characters")
                continue
            for rule, pattern in self.rules.items():
                if pattern.search(reason):
                    self.registry_errors.append(
                        label + ": reason matches scan rule %s" % rule)
                    break

    @overload
    def git(self, args: list[str], stdin: bytes | None = None,
            allow_fail: Literal[False] = False) -> bytes: ...

    @overload
    def git(self, args: list[str], stdin: bytes | None = None,
            *, allow_fail: Literal[True]) -> bytes | None: ...

    def git(self, args: list[str], stdin: bytes | None = None,
            allow_fail: bool = False) -> bytes | None:
        # What this gate READS is no longer shaped by repository configuration,
        # because it no longer asks git to render anything. `diff-index --raw`
        # reports modes and object ids; `cat-file` returns the bytes those ids
        # name. Neither is affected by textconv, diff drivers, the -diff or
        # binary attributes, hunk layout, -U, or GIT_DIFF_OPTS -- there is no
        # patch for them to shape. That is why --text, --no-textconv,
        # --no-ext-diff and -U0 are gone rather than pinned: the surface they
        # were covering does not exist here.
        #
        # What remains config-shaped is which OBJECTS are compared, not what
        # they contain, and it is pinned:
        #   --literal-pathspecs   the registry name is fed back as a pathspec;
        #                         pathspec magic in a filename (":(exclude)x",
        #                         POSIX-only) must not redirect it.
        #   --no-replace-objects  refs/replace/* rewrites what git HANDS BACK,
        #                         by object id, so it reaches cat-file too.
        #                         Measured: replacing the staged blob makes the
        #                         gate read harmless bytes while the index and
        #                         the commit keep the secret, and replacing the
        #                         registry blob supplies exceptions that the
        #                         commit does not contain.
        #   --find-renames -l0    at the call sites: without detection an R
        #                         record degrades to a plain add and the OLD
        #                         path -- a pure rename's only signal -- is
        #                         never scanned. diff.renames=false and
        #                         diff.renameLimit each switch that off from
        #                         inside the guarded repo; both measured.
        #   --ignore-submodules=none  a committed .gitmodules `ignore = all`
        #                         drops a gitlink from the change set entirely.
        #   -c core.fsmonitor=false   the one knob here that EXECUTES rather
        #                         than reshapes. Set to a command, git runs it
        #                         with the worktree as cwd on any index read --
        #                         measured: `-c 'core.fsmonitor=printf X >&2'
        #                         ls-files` prints X, and so does the same value
        #                         in .git/config. Command-line -c outranks repo
        #                         config, also measured. This is what makes
        #                         "reading the index executes nothing from the
        #                         working tree" true rather than merely
        #                         plausible -- the claim came first and was
        #                         false, which is the failure this file keeps
        #                         having. cat-file does NOT read the index and
        #                         never triggered it.
        #                         The fsmonitor regression carries a POSITIVE
        #                         CONTROL, because the first version of it used
        #                         a helper that silently never ran and so passed
        #                         whether or not the pin was there.
        #   --no-lazy-fetch       a partial clone would otherwise demand-fetch
        #                         over the network mid-hook. Previously listed
        #                         as known-open; failing closed is the whole
        #                         point of a gate, so it is pinned rather than
        #                         enumerated. Stated plainly: git accepts the
        #                         flag (verified) but there is NO regression for
        #                         its effect -- a partial-clone fixture is out
        #                         of scope here, so this one is pinned on
        #                         reasoning, not measurement. It also sets an
        #                         implicit floor of git >= 2.36; an older git
        #                         rejects the flag and every run exits 2, which
        #                         is loud and fail-closed rather than silently
        #                         unprotected. Measured here on 2.53.
        # Environment is handled by allowlist above (GIT_ENV_KEEP) rather than
        # by naming knobs, which is the part unit G showed cannot be finished.
        #
        # The EXECUTING class was swept rather than left as a worry, because
        # "one satisfying flag and no pressure to ask what else is in the
        # class" is how the previous unit missed six knobs in a row. Measured
        # against ls-files / diff-index / cat-file / rev-parse / hash-object as
        # invoked here: an alias cannot shadow a builtin; filter.<drv>.clean
        # and .smudge never fire (nothing is materialised or staged);
        # post-index-change never fires (nothing writes the index);
        # diff.<drv>.textconv and diff.external shape a PATCH, and --raw
        # produces none; core.pager needs a tty and stdout is captured. Only
        # core.fsmonitor fired. Unlike the rendering class -- open by
        # construction -- this one is bounded by which commands git shells out
        # from, so it is closed for THESE commands. Adding a subcommand to this
        # tool re-opens the question; re-run that sweep.
        #
        # Still true, and not fixable at this layer: include/includeIf can
        # redirect core.hooksPath, which takes effect BEFORE this process
        # exists. A gate cannot guarantee it ran. `core.precomposeUnicode`
        # still alters Mac pathnames.
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("GIT_") or k in GIT_ENV_KEEP}
        proc = subprocess.run(["git", "--literal-pathspecs", "--no-replace-objects",
                               "--no-lazy-fetch", "-c", "core.fsmonitor=false",
                               "-C", str(self.root), *args],
                              input=stdin, capture_output=True, text=False, env=env)
        if proc.returncode != 0:
            if allow_fail:
                return None
            # Subcommand and exit code only. git's stderr is not this tool's
            # own text: a failing textconv/diff driver writes ITS output there,
            # so relaying it would break the one rule this scanner never
            # breaks -- findings never print matched content. The cost is real:
            # diagnosing a git failure means rerunning the subcommand by hand.
            raise RuntimeError("git %s failed (exit %d)" % (args[0], proc.returncode))
        return proc.stdout

    def base(self):
        """The tree the index is compared against: HEAD, or the empty tree.

        `git diff --cached` special-cases an unborn HEAD; `diff-index` does not
        and dies on the initial commit, which is a commit the hook has to be
        able to gate. The sentinel is ASKED FOR rather than written down
        because a SHA-256 repository's empty tree has a different id.
        """
        if self._base is None:
            head = self.git(["rev-parse", "--verify", "--quiet", "HEAD"],
                            allow_fail=True)
            if head:
                self._base = "HEAD"
            else:
                self._base = self.git(["hash-object", "-t", "tree", "--stdin"],
                                      stdin=b"").decode("ascii").strip()
        return self._base

    def read_blobs(self, oids):
        """{oid: bytes} for the given object ids, in ONE cat-file call.

        Batched because a full candidate-index rescan is every tracked file,
        and process spawn dominates that on Windows. --batch also reports each
        object's TYPE, which is asserted rather than assumed: an index mode and
        the object it names are independent, so a 100644 entry can point at a
        commit. Anything that is not a blob is a hard error -- unreadable is
        not clean.
        """
        wanted = sorted(set(oids))
        if not wanted:
            return {}
        out = self.git(["cat-file", "--batch"],
                       stdin=("\n".join(wanted) + "\n").encode("ascii"))
        blobs = {}
        pos = 0
        for oid in wanted:
            end = out.find(b"\n", pos)
            header = out[pos:end].decode("ascii", "replace").split(" ") if end >= 0 else []
            if len(header) != 3 or header[0] != oid or header[1] != "blob":
                raise RuntimeError("cat-file did not return a blob for %s" % oid[:12])
            try:
                size = int(header[2])
            except ValueError:
                raise RuntimeError("cat-file gave a malformed size for %s" % oid[:12])
            pos = end + 1
            blobs[oid] = out[pos:pos + size]
            # Both edges are checked, not just the length. Trusting the size and
            # skipping ahead means a response of "<oid> blob 1\nXQ" is read as
            # blob "X" with the stray "Q" silently absorbed into the next
            # record's framing -- the parser would resynchronise on garbage
            # instead of failing. The stream must be exactly as long as it says.
            if len(blobs[oid]) != size or out[pos + size:pos + size + 1] != b"\n":
                raise RuntimeError("cat-file framing is wrong for %s" % oid[:12])
            pos += size + 1
        if pos != len(out):
            raise RuntimeError("cat-file returned %d unexpected trailing bytes"
                               % (len(out) - pos))
        return blobs

    def read_registry(self):
        """Return (registry text or None, errors).

        Staged mode resolves the registry from the INDEX, never the working
        tree. A worktree-sourced registry lets an unstaged edit suppress a
        staged finding: the commit then carries the secret and no record of the
        exception that excused it, which defeats "the reviewed registry is the
        only sanctioned escape" outright. Reading the index makes the registry
        coherent with the commit that is about to be made. The converse is
        accepted: an unstaged *tightening* of the registry does not apply
        either, because it is not part of the commit.

        scan_staged() otherwise walks the DELTA -- staged paths and added
        lines -- so a line already in HEAD under an exception would never be
        revisited when the index removes it, narrows it, or edits its expiry
        date. That is why a change to the registry BLOB, deletion included,
        promotes the run to a full candidate-index scan (registry_changed /
        scan_index). The passage of time is NOT such a change: an entry that
        expired today does not promote an unrelated commit, and unchanged
        expired entries are caught by tree mode's hygiene pass instead. The delta remains
        the unit of work for every other commit, so the cost is paid only by
        commits that move the registry.

        Tree mode keeps reading the working tree, which is the content it
        scans.
        """
        path = self.root / REGISTRY_NAME
        if self.mode != "staged":
            if not path.exists():
                return None, []
            try:
                return path.read_text(encoding="utf-8"), []
            except (OSError, UnicodeDecodeError) as exc:
                return None, ["registry unreadable: %s" % type(exc).__name__]
        staged, errors = self.index_registry()
        if errors:
            return None, errors
        worktree = None
        if path.exists():
            try:
                worktree = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                worktree = None
        # Newline-normalised: core.autocrlf checks out LF blobs as CRLF, so a
        # byte comparison would fire this note on every commit on Windows.
        if _newlines(worktree) != _newlines(staged):
            self.notes.append(
                "registry: read from the index; the working-tree copy differs "
                "-- stage %s for your edit to apply" % REGISTRY_NAME)
        return staged, []

    def index_registry(self):
        """Return (blob text or None, errors) for the registry in the index."""
        # "<mode> <sha> <stage>\t<path>" per NUL-terminated record. Stage 0 is
        # the resolved entry; anything else means an unresolved merge, where
        # falling back to "no registry" would silently drop every suppression.
        blob = None
        records = nul_split(self.git(["ls-files", "-s", "-z", "--", REGISTRY_NAME]))
        for record in records:
            meta = record.split("\t", 1)[0].split(" ")
            if len(meta) == 3 and meta[2] == "0":
                # The mode is load-bearing, not decoration. A symlink entry
                # (120000) is still a blob, and its content is the link TARGET
                # text -- which can be made to be valid registry JSON, so
                # cat-file succeeds and the exception suppresses a real
                # finding. Reading a blob by sha without asking what kind of
                # entry produced it is the bug; regular files only.
                if meta[0] not in ("100644", "100755"):
                    return None, ["registry is not a regular file in the index "
                                  "(mode %s)" % meta[0]]
                blob = meta[1]
        if blob is None:
            if records:
                return None, ["registry has an unresolved merge conflict in the index"]
            return None, []
        try:
            return self.git(["cat-file", "blob", blob]).decode("utf-8"), []
        except UnicodeDecodeError:
            return None, ["registry unreadable: UnicodeDecodeError"]

    def enforcement_errors(self):
        """Errors when the code DECIDING this commit is not the code in it.

        The hook shim, this gate and the preflight pattern module are executed
        from the WORKING TREE, so an unstaged edit to any of them changes the
        verdict while the commit shows nothing. That is the same worktree/index
        incoherence the registry read closed one layer down -- there it was a
        suppression, here it is the enforcement itself, which is strictly
        worse: a weakened pattern set needs no exception entry at all.

        Only files present in the scanned repo's working tree are compared.
        With --repo pointed at a fixture there is nothing to compare and the
        executed gate belongs to a different checkout; in the hook path root IS
        that checkout (`git rev-parse --show-toplevel` feeds both), which is
        the case this exists for. A source present but untracked is refused
        rather than skipped -- code in no commit at all is the wider version of
        the same problem.

        What this does NOT do, stated because the wording invites the stronger
        reading: it is checked BY the working-tree gate it is checking, so an
        edit that removes this method is not caught by it. It closes the
        accident -- an edit you forgot to stage, which is this repository's
        actual threat model -- and not a deliberate weakening, which owns the
        running process either way. The property it really provides is that the
        enforcement code and the commit agree WHENEVER THE CHECK RUNS, which is
        strictly less than "the commit was gated by the committed gate".
        """
        errors = []
        index = self.index_blobs()
        wanted = {}
        for rel in ENFORCEMENT_SOURCES:
            if not (self.root / rel).is_file():
                continue
            if rel not in index:
                errors.append("%s runs from the working tree but is not in the "
                              "index -- stage it before committing" % rel)
                continue
            mode, oid = index[rel]
            if mode not in ("100644", "100755"):
                errors.append("%s is not a regular file in the index (mode %s)"
                              % (rel, mode))
                continue
            wanted[rel] = oid
        blobs = self.read_blobs(wanted.values())
        for rel, oid in wanted.items():
            try:
                live = (self.root / rel).read_bytes()
            except OSError as exc:
                errors.append("%s cannot be read from the working tree: %s"
                              % (rel, type(exc).__name__))
                continue
            # Compared on bytes with newlines normalised: core.autocrlf checks
            # LF blobs out as CRLF, so a raw comparison would refuse every
            # commit on Windows -- the same trap the registry note hit, which
            # is why it is measured here rather than assumed away.
            if live.replace(b"\r\n", b"\n") != blobs[oid].replace(b"\r\n", b"\n"):
                errors.append("%s differs from its index version -- stage the "
                              "edit, or restore the file, before committing" % rel)
        return errors

    def exception_for(self, path, rule, digest):
        assert self.entries is not None
        for entry in self.entries:
            if entry["key"] == (path, rule, digest):
                return entry
        return None

    def report(self, path, line_no, rule, hashed):
        digest = sha256_text(hashed)
        entry = self.exception_for(path, rule, digest)
        where = "%s:%s" % (path, line_no) if line_no else path
        if entry and not entry["expired"]:
            entry["used"] = True
            self.suppressed.append("%s %s (reason: %s; expires %s)" % (
                where, rule, entry["reason"], entry["expires"].isoformat()))
            return
        note = " [registry entry EXPIRED %s]" % entry["expires"].isoformat() if entry else ""
        self.findings.append("%s rule=%s sha256=%s%s" % (where, rule, digest, note))

    def scan_path_name(self, path):
        if self.path_pattern.search("/" + path):
            self.report(path, None, PATH_RULE, path)

    def scan_line(self, path, line_no, line):
        text = line.rstrip()
        for rule, pattern in self.rules.items():
            if pattern.search(text):
                self.report(path, line_no, rule, text)

    def run(self):
        # Before the error gate: a divergence note is often what explains the
        # error or the block that follows it.
        for note in self.notes:
            print(note)
        # Before the registry gate: if the enforcement code is not the code in
        # the commit, nothing this run goes on to say about that commit means
        # anything -- a clean verdict included.
        errors = list(self.blocking_errors)
        if self.mode == "staged" and not errors:
            errors = ["%s is unmerged in the index -- resolve the conflict "
                      "before committing" % path
                      for path in self.unmerged_paths()]
        if errors or self.entries is None or self.registry_errors:
            for err in errors + (self.registry_errors or []):
                print("SECRETS GATE ERROR: " + err)
            return 2
        if self.mode == "staged":
            self.scan_staged()
        else:
            self.scan_tree()
        problems = list(self.findings)
        if self.mode == "tree":
            for entry in self.entries:
                if entry["expired"]:
                    problems.append("registry entry expired %s: %s %s" % (
                        entry["expires"].isoformat(), entry["key"][0], entry["key"][1]))
                elif not entry["used"]:
                    problems.append("registry entry matched nothing (stale): %s %s" % (
                        entry["key"][0], entry["key"][1]))
        for line in self.suppressed:
            print("suppressed by registry: " + line)
        if problems:
            print("SECRETS GATE BLOCKED (%s): %d problem(s)" % (self.mode, len(problems)))
            for item in problems:
                print("  " + item)
            print("Remove/redact the value, or add a reviewed entry "
                  "(path+rule+sha256+reason+expires) to secrets-exceptions.json.")
            return 1
        print("SECRETS GATE OK (%s)" % self.mode)
        return 0

    def staged_changes(self):
        """[(names to path-scan, path, status, srcoid, dstmode, dstoid)].

        The raw format is the whole point: ":<srcmode> <dstmode> <srcoid>
        <dstoid> <status>" then the path(s). It reports object IDS, so nothing
        downstream has to parse a rendered patch, and no attribute, diff driver
        or -U setting can shape what is read. R/C records carry two paths,
        everything else one.

        Both names are path-scanned. A pure rename carries no content change,
        so the OLD name is its only signal, and reporting the destination alone
        let a credential file be renamed to an ordinary name past every rule.
        A pure deletion stays out of scope (D is not in the filter) -- removing
        a file is not hiding it -- with the registry as the one exception, see
        registry_changed().

        --find-renames -l0 is explicit because rename detection has TWO config
        knobs and both switch this protection off from inside the repo being
        guarded. `diff.renames=false` turns the whole R branch into a plain add
        of the destination; `diff.renameLimit` skips detection once a change
        exceeds it, with the same result. Both measured -- at renameLimit=1 with
        four renames the credential rename passed again. -l0 lifts the limit,
        which restores git's O(n^2) rename comparison on very large change sets:
        a deliberate trade of pre-commit latency for a signal that cannot be
        turned off by editing a config file.
        """
        # T (typechange): a symlink replaced by a regular file carries new
        # content and must be scanned like a modification of it.
        fields = nul_split(self.git(["diff-index", "--cached", "--raw", "-z",
                                     "--find-renames", "-l0",
                                     "--ignore-submodules=none",
                                     "--diff-filter=ACMRT", self.base()]))
        changes = []
        i = 0
        while i < len(fields):
            meta = fields[i]
            # "::" is a combined record, which diff-index against a single tree
            # does not emit. Refusing an unrecognised shape keeps a format
            # surprise from being read as an empty change set.
            if not meta.startswith(":") or meta.startswith("::"):
                raise RuntimeError("diff-index: unrecognised record shape")
            parts = meta[1:].split(" ")
            if len(parts) != 5:
                raise RuntimeError("diff-index: malformed raw record")
            srcmode, dstmode, srcoid, dstoid, status = parts
            width = 2 if status[:1] in ("R", "C") else 1
            if i + 1 + width > len(fields):
                raise RuntimeError("diff-index: truncated raw record")
            paths = fields[i + 1:i + 1 + width]
            # Both modes are carried. Asking only about the destination is a
            # bug in the T direction: replacing a SUBMODULE with a regular file
            # leaves srcoid naming a commit, which cat-file would refuse -- a
            # legitimate change turned into a hard error rather than a scan.
            changes.append((paths, paths[-1], status[:1],
                            srcmode, srcoid, dstmode, dstoid))
            i += 1 + width
        return changes

    def added_lines(self, old, new):
        """[(line_no, text)] for what `new` adds over `old`, by MULTISET.

        A line is skipped only when the previous version of THIS path already
        held at least as many copies of it; every occurrence beyond that count
        is scanned. So the property enforced is exactly:

            skipped  =>  this exact line was already committed at this path,
                         at least this many times.

        which makes it impossible for content absent from the previous version
        to escape, whatever else changed around it.

        No alignment is consulted, and that is the point rather than a
        simplification. The first version of this used difflib opcodes and lost
        a detection: for HEAD [SECRET, plain] -> index [plain, SECRET], difflib
        calls SECRET *equal* and scans only `plain`, while `git diff` renders
        -SECRET/+SECRET and would have scanned it. The instinct is to "match
        git", but the mirror input disproves that: for [plain, SECRET] ->
        [SECRET, plain] git renders -plain/+plain and misses SECRET while
        difflib catches it. Both edit scripts cost one delete plus one insert;
        the two algorithms merely break the tie on opposite lines. Neither set
        contains the other, so there is no stricter reference to match -- and
        letting an outside algorithm's tie-breaking decide the scanned set is
        the exact dependence this whole mode was rewritten to remove.

        What this gives up, stated because it is a real narrowing: a pure
        REORDER of an already-committed line is not re-flagged. It is given up
        consistently, as a property, rather than accidentally depending on
        which line an aligner happened to anchor. Such a line is by definition
        already in HEAD at this path, tree mode still scans it, and any change
        to the registry promotes this run to a full index scan.

        It also removes a measured pathology: SequenceMatcher's cost is driven
        by line repetition, and 20k identical lines took 22 seconds -- the same
        stall shape unit A had to remove -- which had needed a work-estimate
        budget and a whole-blob fallback. This is linear and needs neither.
        """
        if not old:
            return list(enumerate(new, 1))
        remaining = collections.Counter(old)
        added = []
        for line_no, line in enumerate(new, 1):
            if remaining[line]:
                remaining[line] -= 1
            else:
                added.append((line_no, line))
        return added

    def registry_changed(self):
        """True when the staged change set touches the registry at all.

        Deliberately unfiltered, where staged_changes() drops D: a registry
        DELETION is the sharpest form of the gap this closes, since dropping an
        exception while leaving the line it protected untouched changes what
        the commit is allowed to contain without changing the line.
        """
        return bool(self.git(["diff-index", "--cached", "--raw", "-z",
                              self.base(), "--", REGISTRY_NAME]).strip())

    def scan_index(self, already_named):
        """Path rule and every line of every stage-0 index entry."""
        index = self.index_blobs()
        blobs = self.read_blobs(oid for mode, oid in index.values()
                                if mode in BLOB_MODES)
        for path in sorted(index):
            mode, oid = index[path]
            if path not in already_named:
                already_named.add(path)
                self.scan_path_name(path)
            if mode not in BLOB_MODES:
                continue
            for line_no, line in enumerate(blob_lines(blobs[oid]), 1):
                self.scan_line(path, line_no, line)

    def comparable(self, status, srcmode, srcoid):
        """Whether the source side is a blob worth diffing the destination
        against. A and R/C are scanned WHOLE either way -- for a rename that is
        the conservative direction and the pre-existing behaviour, since the
        old parser excluded the source from the pathspec and git rendered the
        destination as an add. A non-blob source (a submodule replaced by a
        file) is likewise scanned whole rather than read as content."""
        return (status in ("M", "T") and srcmode in BLOB_MODES
                and srcoid != NULL_OID)

    def unmerged_paths(self):
        """Paths with a conflict in the candidate index.

        Nothing else notices them. `--diff-filter=ACMRT` drops the `U` records
        diff-index emits, and index_blobs() keeps only stage 0, so a
        three-stage conflict reaches the scan as an EMPTY change set and the
        gate prints OK -- measured, exit 0. Git normally refuses such a commit
        itself, which is exactly why this went unseen: the false clean is
        masked by a different tool's check rather than by anything here.
        Unmeasurable must not read as clean, so it is refused here too.

        Records are "<mode> <sha> <stage>\\t<path>" and a conflicted path emits
        up to THREE of them, so the path is taken out before deduplicating --
        deduplicating the records themselves would report the same file once
        per stage.
        """
        return sorted({record.split("\t", 1)[-1]
                       for record in nul_split(self.git(["ls-files", "-u", "-z"]))})

    def scan_staged(self):
        changes = self.staged_changes()
        named = set()
        for change in changes:
            for name in change[0]:
                if name not in named:
                    named.add(name)
                    self.scan_path_name(name)
        if self.registry_changed():
            self.scan_index(named)
            return
        wanted = []
        for _, _, status, srcmode, srcoid, dstmode, dstoid in changes:
            if dstmode not in BLOB_MODES:
                # A gitlink or a tree: path-scanned above, never read as a
                # blob. Its content is another repository's problem.
                continue
            wanted.append(dstoid)
            if self.comparable(status, srcmode, srcoid):
                wanted.append(srcoid)
        blobs = self.read_blobs(wanted)
        for _, path, status, srcmode, srcoid, dstmode, dstoid in changes:
            if dstmode not in BLOB_MODES:
                continue
            old = (blob_lines(blobs[srcoid])
                   if self.comparable(status, srcmode, srcoid) else [])
            for line_no, line in self.added_lines(old, blob_lines(blobs[dstoid])):
                self.scan_line(path, line_no, line)

    def index_blobs(self):
        """{path: (mode, oid)} for stage-0 index entries."""
        out = {}
        for record in nul_split(self.git(["ls-files", "-s", "-z"])):
            meta, _, path = record.partition("\t")
            fields = meta.split(" ")
            if len(fields) == 3 and fields[2] == "0" and path:
                out[path] = (fields[0], fields[1])
        return out

    def scan_tree(self):
        staged_blobs = self.index_blobs()
        for path in nul_split(self.git(["ls-files", "-z"])):
            self.scan_path_name(path)
            full = self.root / path
            mode, oid = staged_blobs.get(path, (None, None))
            try:
                if mode == "120000":
                    # Read the BLOB, not the working-tree link. git-for-windows
                    # materialises a symlink with "\" separators while the blob
                    # holds "/", so os.readlink() and the committed bytes differ
                    # mid-string -- where rstrip() cannot absorb it the way it
                    # absorbs autocrlf's line endings. The rule still fires
                    # either way, but the two modes then produce DIFFERENT
                    # sha256 digests for the same secret, so a registry entry
                    # written from one mode reads as stale in the other and the
                    # exception contract breaks. Measured on a git-materialised
                    # checkout, not on a Python-created link, which does keep
                    # the separator and hid this.
                    data = self.git(["cat-file", "blob", oid])
                elif full.is_symlink():
                    # Fallback for a link with no stage-0 index entry (a
                    # conflicted path). The reason symlinks need a branch at
                    # all: git stores one as a blob whose CONTENT is the target
                    # path string, and read_bytes() follows the link and scans
                    # the REFERENT instead -- so the committed bytes went
                    # unscanned, and a secret in the target text passed tree
                    # mode while staged mode blocked it. A dangling link always
                    # failed closed below, which is why only the resolvable
                    # case was invisible. Note core.symlinks=false does NOT
                    # reach here either: it changes how the link is
                    # materialised, not the index mode, so the entry is still
                    # 120000 and the blob branch above takes it.
                    data = os.readlink(str(full)).encode("utf-8", "surrogateescape")
                else:
                    data = full.read_bytes()
            except OSError:
                self.findings.append("%s rule=unreadable sha256=%s" % (
                    path, sha256_text(path)))
                continue
            for line_no, line in enumerate(blob_lines(data), 1):
                self.scan_line(path, line_no, line)


def main():
    args = sys.argv[1:]
    root = SCRIPT_REPO
    if len(args) == 3 and args[1] == "--repo":
        root = Path(args[2])
        args = args[:1]
    if len(args) != 1 or args[0] not in ("staged", "tree"):
        print("usage: secrets-gate.py {staged|tree} [--repo PATH]", file=sys.stderr)
        return 2
    if not root.is_dir():
        print("SECRETS GATE ERROR: repo root not a directory: %s" % root)
        return 2
    try:
        return Gate(args[0], root).run()
    except RuntimeError as exc:
        print("SECRETS GATE ERROR: %s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
