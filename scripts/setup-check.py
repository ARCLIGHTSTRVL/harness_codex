#!/usr/bin/env python3
"""Read-only Codex install status and shared baseline canonicalization."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import codecs
import re
import subprocess
import sys
import unicodedata
from io import TextIOWrapper

sys.dont_write_bytecode = True
SCRIPT_REPO = Path(__file__).resolve().parent.parent
if str(SCRIPT_REPO) not in sys.path:
    sys.path.insert(0, str(SCRIPT_REPO))
from scripts.installer_support import is_source_junk
from scripts.native_hook_io import HookRefusal, read_bytes

START_MARKER = "<!-- DEV-SETUP-CODEX:START -->"
END_MARKER = "<!-- DEV-SETUP-CODEX:END -->"
# The installer's early-exit dirty check covers the same set.
MANAGED_SOURCE_PATHS = ("codex", "skills", "scripts", "templates",
                        "knowledge", "specs", "docs", "AGENTS.md", "README.md",
                        "BOOTSTRAP.md", "SKILLS.md", ".gitignore", ".gitattributes",
                        "githooks", ".github", "tests", "secrets-exceptions.json",
                        "model-name-exceptions.json")
HASH_KEYS = ("codex_agents", "skills_tree")
STATE_SCHEMA = 2
HASH_SCOPE = "manifest-v1"


def codex_home(home: Path) -> Path:
    return Path(os.environ.get("CODEX_HOME", str(home / ".codex"))).expanduser()


def is_str_list(value):
    """Manifests are arrays OF STRINGS at every boundary (r11 M1): a nested
    element unrolled to nothing on the producer side and str()'d into a "[]"
    row on the checker side, so the two disagreed forever."""
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def state_schema_current(state):
    """Whether a recorded state is manifest-v1 schema 2.

    ONE gate, called by this checker AND by the install engine
    (scripts/install.py): review r1 of installer-state-plane measured the two
    disagreeing over `2.0` -- a bare `== 2` accepts it (2.0 == 2 is True)
    while an exact type test rejects it, so the checker answered "In sync"
    about state the installer would rewrite. The value must BE the integer 2:
    "2", True, [2] and 2.0 are all corrupt state, not schema 2 (r12 M2 bought
    the type test itself). bool is an int subclass, hence the explicit
    exclusion.
    """
    schema = state.get("state_schema")
    return (isinstance(schema, int) and not isinstance(schema, bool)
            and schema == STATE_SCHEMA
            and state.get("hash_scope") == HASH_SCOPE)


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


# .NET Char.IsWhiteSpace: Unicode Zs/Zl/Zp plus these controls. Notably it
# does NOT include U+001C..U+001F, which Python's str.strip() removes -- the
# divergence review r1 demonstrated.
_DOTNET_WS_CONTROLS = "\t\n\v\f\r\x85"


def _is_dotnet_ws(ch):
    return ch in _DOTNET_WS_CONTROLS or unicodedata.category(ch) in ("Zs", "Zl", "Zp")


def dotnet_trim(text):
    start, end = 0, len(text)
    while start < end and _is_dotnet_ws(text[start]):
        start += 1
    while end > start and _is_dotnet_ws(text[end - 1]):
        end -= 1
    return text[start:end]


def dotnet_trim_end(text):
    """String.TrimEnd() parity -- the END only.

    The installer's block updater needs this half, not `dotnet_trim`: the
    retired PowerShell updater called TrimEnd(), so trimming the START as well
    would delete leading whitespace the user's file is entitled to keep. It
    lives here rather than in the engine because the .NET whitespace set is
    defined here, and a second spelling of that set is how the two drift.
    """
    end = len(text)
    while end > 0 and _is_dotnet_ws(text[end - 1]):
        end -= 1
    return text[:end]


def ordinal_key(text):
    # StringComparer.Ordinal compares UTF-16 code UNITS; UTF-16-BE bytes sort
    # in exactly that order (astral chars via their surrogate pairs).
    return text.encode("utf-16-be", "surrogatepass")


def dotnet_utf8(text):
    """UTF-8 bytes the way Encoding.UTF8.GetBytes produces them: an unpaired
    surrogate becomes U+FFFD instead of raising. JSON permits lone surrogates
    in manifest strings, and review r2 measured a UnicodeEncodeError traceback
    here -- an uncontrolled exit outside the 0/1/2 contract."""
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        return "".join("�" if 0xD800 <= ord(c) <= 0xDFFF else c
                       for c in text).encode("utf-8")


def decode_all_text(data):
    """File.ReadAllText parity for bytes already in hand: BOM-detected
    encoding, default UTF-8.

    Split out from read_all_text so the install engine can decode a source it
    snapshotted BEFORE mutating anything (r2: reopening a source path during
    the copy is a window a concurrent writer can drive). One decoder, two entry
    points -- re-deriving BOM detection in the engine is how the two would
    start disagreeing about one file.

    UTF-32 LE is tested before UTF-16 LE because its BOM starts with the same
    two bytes.
    """
    for bom, enc in ((codecs.BOM_UTF32_LE, "utf-32-le"),
                     (codecs.BOM_UTF32_BE, "utf-32-be"),
                     (codecs.BOM_UTF8, "utf-8"),
                     (codecs.BOM_UTF16_LE, "utf-16-le"),
                     (codecs.BOM_UTF16_BE, "utf-16-be")):
        if data.startswith(bom):
            return data[len(bom):].decode(enc, "replace")
    return data.decode("utf-8", "replace")


def read_all_text(path):
    """File.ReadAllText parity.

    The Windows installer PRESERVES an existing UTF-16/UTF-32 file when its
    decoded block already matches (no rewrite happens), and hashes what .NET
    DECODED -- review r3 measured the UTF-8-only reader returning the empty
    sentinel against exactly that file.
    """
    return decode_all_text(path.read_bytes())


def custom_block_hash(path):
    """Get-CustomBlockHash parity: "" for missing file or markers;
    "<unreadable>" when the bytes cannot be read at all (permission loss or a
    concurrent delete between predicate and read -- review r3's totality
    finding; the recorded state can never contain this sentinel, so it
    surfaces as Drift instead of a traceback)."""
    try:
        if not path.is_file():
            return ""
        text = read_all_text(path)
    except OSError:
        return "<unreadable>"
    return block_hash_from_text(text)


def block_hash_from_text(text):
    """The block-hash rule over text already in hand -- ONE topology rule,
    shared by the checker (custom_block_hash reads the installed file) and the
    engine's expected-baseline side, which hashes the block it is about to
    install (R2-C4's baseline half). A second spelling of the marker topology
    is how the two would drift."""
    ns = text.count(START_MARKER)
    ne = text.count(END_MARKER)
    if ns == 0 and ne == 0:
        return ""
    if ns != 1 or ne != 1:
        # Non-exact topology (duplicate pairs, extra END, lone marker): the
        # first-pair slice hashes IDENTICALLY to a clean block, so stale
        # policy in a second block -- or a mangled append -- survives as In
        # sync (r6 M1 measured the shipped checker doing exactly that; r5 M1
        # was the reversed special case). Like "<unreadable>", no recorded
        # state can contain this sentinel: checker reads Drift, producer
        # refuses. Exactly one ordered pair, or nothing, is recordable.
        return "<invalid-markers>"
    si = text.find(START_MARKER)
    ei = text.find(END_MARKER)
    if ei < si:
        # Reversed pair: the slice would answer sha256("") -- a VALID-looking
        # baseline -- where the retired .NET producer THREW on the negative
        # Substring length (r5 M1).
        return "<invalid-markers>"
    inner = dotnet_trim(text[si + len(START_MARKER):ei])
    return sha256_hex(dotnet_utf8(inner))


def file_hash_or_empty(path):
    try:
        return sha256_hex(path.read_bytes()) if path.is_file() else ""
    except OSError:
        return "<unreadable>"


def managed_tree_hash(root, manifest):
    """Get-ManagedTreeHash parity: ordinal-sorted LF rows, <missing> sentinel."""
    if manifest is None:
        return ""
    rows = tree_rows(root, manifest)
    if not rows:
        return ""
    return sha256_hex(dotnet_utf8("".join(rows)))


def tree_rows(root, manifest):
    """The manifest's canonical rows, shared by the hash and the producer CLI
    (which must SEE an unreadable row to refuse, not bury it in a digest --
    review r4 measured an unreadable target becoming an ordinary-looking
    recorded baseline through the Mac producer)."""
    if manifest is None:
        return []
    rows = []
    for rel in sorted((str(m) for m in manifest), key=ordinal_key):
        target = root / rel.replace("/", os.sep)
        try:
            is_file = target.is_file()
        except (OSError, ValueError):
            # A name this filesystem cannot even represent (lone surrogate,
            # embedded NUL) is not a present managed file -- same verdict
            # Test-Path gave the retired native PowerShell producer.
            is_file = False
        try:
            digest = sha256_hex(target.read_bytes()) if is_file else "<missing>"
        except OSError:
            # Present but unreadable, or deleted between predicate and read:
            # both installers abort without writing state on a refusal, so a
            # recorded state never carries this row -- CHECKER side reads it
            # as Drift, PRODUCER side refuses (main's CLI branch).
            digest = "<unreadable>"
        rows.append(tree_row(rel, digest))
    return rows


def tree_row(rel, digest):
    """One manifest row -- the format shared by the live producer (tree_rows)
    and the content-side producer (content_tree_hash). One spelling."""
    return "%s\t%s\n" % (rel, digest)


def combine_tree_rows(rows):
    """The tree digest over canonical rows -- same sharing rule as tree_row."""
    return "" if not rows else sha256_hex(dotnet_utf8("".join(rows)))


def content_tree_hash(snapshot):
    """Expected-side tree hash from CONTENT already in hand ({rel: bytes},
    the engine's snapshot). R2-C4's baseline half: write_state compares the
    hash it is about to record against this value, so bytes a concurrent
    target writer put there cannot be certified as the baseline. Same row
    format, same ordinal order, same combiner as the live producer."""
    rows = [tree_row(rel, sha256_hex(data))
            for rel, data in sorted(snapshot.items(),
                                    key=lambda kv: ordinal_key(kv[0]))]
    return combine_tree_rows(rows)


class ProducerRefusal(Exception):
    """A value that must never become a recorded baseline.

    The reason text carries NO tool prefix: the CLI branches below print it
    under "setup-check:", the install engine (scripts/install.py) under
    "install:" -- same rules, one implementation, honest process name. Every
    refusal below was bought by a review round; the branches are the reasons,
    not defensive padding.
    """


def produce_block_hash(path):
    """Producer mode for a USER:CUSTOM block target (r4 M1).

    The checker collapses MISSING and MARKERLESS into "", and "" is exactly
    what a recorded "" baseline compares equal to -- so a producer answering
    "" would CREATE the false-in-sync state itself (the installer wrote the
    block moments earlier; either shape here is a broken install moment,
    never a recordable baseline). Checker mode (custom_block_hash) keeps ""
    so an honest absent-state stays comparable against legacy records.
    """
    try:
        block_present = path.is_file()
    except OSError:
        block_present = False
    if not block_present:
        raise ProducerRefusal("block target missing, refusing to produce a "
                              "baseline: %s" % path)
    value = custom_block_hash(path)
    if value == "<unreadable>":
        raise ProducerRefusal("target unreadable, refusing to produce a "
                              "baseline: %s" % path)
    if value == "<invalid-markers>":
        raise ProducerRefusal("corrupt USER:CUSTOM markers (topology is not "
                              "exactly one START then one END) in block "
                              "target, refusing to produce a baseline: %s"
                              % path)
    if value == "":
        raise ProducerRefusal("no USER:CUSTOM markers in block target, "
                              "refusing to produce a baseline: %s" % path)
    return value


def produce_file_hash(path):
    """Raw-byte producer for the whole-file key (ssh_config). No
    canonicalization -- the mode exists so ABSENCE cannot become a recordable
    success: '' is exactly what a recorded '' (or a legacy state) compares
    equal to (r5 M2 measured missing ~/.ssh/config reading In sync forever).
    """
    try:
        file_present = path.is_file()
    except OSError:
        file_present = False
    if not file_present:
        raise ProducerRefusal("file target missing, refusing to produce a "
                              "baseline: %s" % path)
    value = file_hash_or_empty(path)
    if value in ("", "<unreadable>"):
        raise ProducerRefusal("file target unreadable, refusing to produce a "
                              "baseline: %s" % path)
    return value


def produce_tree_hash(root, manifest):
    """Producer mode for a managed tree: refuses MISSING rows too (r5
    reopening r4's finding).

    The installer hashes right after copying, so an absent target there is a
    broken install moment, not a recordable baseline -- the same existence
    assertion the state writer makes. The CHECKER keeps "<missing>" semantics
    (a legitimate drift signal there, and missing_manifest_rows names the
    file). rsplit, because the RELATIVE PATH itself may contain a tab (r5
    minor).
    """
    rows = tree_rows(Path(root), manifest)
    bad = [r.rsplit("\t", 1)[0] for r in rows
           if r.endswith(("\t<unreadable>\n", "\t<missing>\n"))]
    if bad:
        raise ProducerRefusal("%d managed file(s) unreadable or missing, "
                              "refusing to produce a baseline (first: %s)"
                              % (len(bad), bad[0]))
    return combine_tree_rows(rows)


def read_manifest_transport(manifest_file):
    """Parse the LF manifest transport (--hash-tree's file argument).

    The delimiter is exactly LF; one trailing LF is tolerated. NOT
    splitlines(): it also splits U+0085/U+2028/U+2029, which are VALID
    filename characters on NTFS and POSIX, so one present entry became two
    missing ones and every install wedged in refusal (unification r1 M1 --
    the reviewer constructed all three names on this filesystem). LF itself
    cannot appear in a cross-platform-valid name, so the protocol is total
    over the representable domain.

    After the installer-engine unification this is the transport's ONLY
    parser: both state writers build their manifests in-process now, so the
    two Mac heredoc copies and the Windows temp-file adapter that r1/r2 bit
    on no longer exist.
    """
    try:
        # Bytes, not read_text: text mode would ALSO translate CR/CRLF into
        # the delimiter before the split below (r2 measured a CRLF manifest
        # passing where the contract says refuse).
        text = Path(manifest_file).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        # Refusal, not the old ""-success (r3 M1): "" is also the LEGITIMATE
        # empty-manifest hash, so an unreadable manifest file would persist as
        # an ordinary-looking non-verifiable baseline through BOTH state
        # writers -- indistinguishable downstream. UnicodeDecodeError rides
        # the same controlled surface (r4 m1: a non-UTF-8 manifest was a
        # traceback outside the 0/1/2 contract).
        raise ProducerRefusal("manifest file unreadable or not UTF-8, "
                              "refusing to produce a baseline: %s"
                              % manifest_file)
    if text.endswith("\n"):
        text = text[:-1]
    return text.split("\n") if text else []


def git_lines(repo, *args):
    """(returncode, stdout) -- stderr is not relayed (it is git's, not ours).

    A machine without git answers (None, "") rather than raising: the caller
    that NEEDS git maps it to the exit-2 cannot-answer branch, and the
    courtesy callers skip -- review r1 measured a traceback-and-exit-1 here,
    which violated the documented exit contract.
    """
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
    except (OSError, ValueError):
        # ValueError: an embedded NUL in an argument (a corrupt state's
        # applied_commit reached here in review r4's probe before the hex
        # gate below existed; the gate makes this belt-and-suspenders).
        return None, ""
    return proc.returncode, proc.stdout.strip()


def state_provenance_clean(state):
    """Whether a recorded baseline may authorize a skip.

    ONE predicate, called by this checker's note AND by the engine's fast-path
    gate -- review r3 caught the same expression written twice, one rule after
    the duplication r2 removed. The key must EXIST and be exactly `false`: a
    state written before provenance existed carries no field, and its
    provenance is UNKNOWN, not clean (r3 measured the alternative -- an
    unknown-provenance state authorizing a false skip). Absence therefore
    costs one migration install, the same trade schema 2 made.
    """
    return state.get("source_dirty") is False


def managed_sources_dirty(repo):
    """(dirty, provable) for the managed source paths.

    ONE implementation, called by this checker's notes AND by the install
    engine's fast-path gate -- review r2 measured the two spelling the same
    git query separately, which is the divergence this whole unit exists to
    remove. The two surfaces still ANSWER DIFFERENT QUESTIONS with it (the
    checker asks whether the installed artifacts match the recorded install
    and only notes dirtiness; the installer asks whether it may skip work, so
    dirtiness disqualifies the skip) -- what must not differ is how the fact
    is obtained. When git cannot answer, cleanliness is unproven: the caller
    that needs proof treats that as dirty.
    """
    # --untracked-files=all: the command-line flag beats any repo/user config
    # (R2-C1 reproduced `status.showUntrackedFiles no` hiding a brand-new
    # managed source from this exact query -- a false fast path).
    rc, out = git_lines(repo, "status", "--porcelain",
                        "--untracked-files=all", "--",
                        *MANAGED_SOURCE_PATHS)
    if rc != 0:
        return True, False
    if out:
        return True, True
    # Index flags are the second config channel (R2-C1): an assume-unchanged
    # (lowercase tag) or skip-worktree (`S`) managed path never reads dirty in
    # `git status`, so an edit under either flag is invisible to the query
    # above. Cleanliness is then UNPROVABLE, not clean -- fail closed.
    rc, flags = git_lines(repo, "ls-files", "-v", "--", *MANAGED_SOURCE_PATHS)
    if rc != 0:
        return True, False
    for line in flags.splitlines():
        tag = line[:1]
        if tag == "S" or tag.islower():
            return True, False
    rc, ignored = git_lines(repo, "ls-files", "--others", "--ignored",
                            "--exclude-standard", "--", *MANAGED_SOURCE_PATHS)
    if rc != 0:
        return True, False
    if any(not is_source_junk(line) for line in ignored.splitlines() if line):
        return True, True
    return False, True


def human_ago(iso_utc, now=None):
    try:
        applied = datetime.datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return "unknown time"
    applied = applied.replace(tzinfo=datetime.timezone.utc)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    seconds = max(0, int((now - applied).total_seconds()))
    if seconds < 3600:
        return "%dm ago" % (seconds // 60)
    if seconds < 86400:
        return "%dh ago" % (seconds // 3600)
    return "%dd ago" % (seconds // 86400)


def missing_manifest_rows(home, state):
    """Manifest entries whose installed file is gone -- the one tree-drift
    cause that can be NAMED (the state stores no per-row baseline, so an
    edited row is only attributable to its tree)."""
    gone = []
    for root, key in ((codex_home(home) / "skills", "skills_manifest"),):
        for rel in state.get(key) or []:
            target = root / str(rel).replace("/", os.sep)
            try:
                present = target.is_file()
            except (OSError, ValueError):
                present = False
            if not present:
                # Reported through the same U+FFFD mapping the hash uses: a
                # lone surrogate in the name must not crash the REPORT either.
                gone.append("%s/%s" % (root.name,
                                       dotnet_utf8(str(rel)).decode("utf-8")))
    return gone


def native_hook_findings(home: Path, repo: Path, probe: bool = False) -> list[str]:
    helper, mode = ("native-hook-status.py", "probe") if probe else ("native-hooks.py", "check")
    command = [sys.executable, str(SCRIPT_REPO / "scripts" / helper),
               mode, "--home", str(codex_home(home)), "--repo", str(repo)]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=90 if probe else 30)
    except (OSError, subprocess.TimeoutExpired):
        return ["Drift: global native hooks are unverifiable; checker could not run."]
    if result.returncode == 0 and probe:
        try:
            report = json.loads(result.stdout)
        except (ValueError, RecursionError):
            return ["Drift: global native hook probe returned invalid JSON."]
        if (not isinstance(report, dict) or report.get("configuration") != "current"
                or report.get("execution") != "passed"):
            return ["Drift: global native hook command probe did not pass."]
    if result.returncode == 0:
        return []
    if result.returncode == 1:
        return ["Drift: global native hooks missing or incorrectly wired; reinstall."]
    return ["Drift: global native hooks are unverifiable; inspect native-hooks.py check."]


def installed_source_repo(home):
    state_path = codex_home(home) / "dev-setup-codex-community-state.json"
    try:
        raw = read_bytes(state_path)
        if raw is None:
            return SCRIPT_REPO, None
        state = json.loads(raw)
    except (HookRefusal, OSError, ValueError, UnicodeError) as exc:
        return None, "installed state cannot be read: " + str(exc)
    if not isinstance(state, dict) or state.get("distribution") != "community":
        return None, "installed state is not a community baseline"
    value = state.get("source_repo")
    if not isinstance(value, str) or not Path(value).is_absolute():
        return None, "installed state has invalid source_repo"
    return Path(value), None


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "Codex install status").splitlines()[0])
    ap.add_argument("--home", type=Path, default=Path.home(),
                    help="profile root holding .codex/.ssh (tests)")
    ap.add_argument("--repo", type=Path, default=None,
                    help="dev-setup source to compare (default: installed state source_repo)")
    ap.add_argument("--skip-hooks", action="store_true",
                    help="skip global native hook wiring checks; this does not verify hook trust")
    ap.add_argument("--probe-hooks", action="store_true",
                    help="execute only exact owned hook commands with harmless invalid input; not host dispatch")
    ap.add_argument("--check-updates", action="store_true",
                    help="query the canonical public main branch and compare it with this exact checkout")
    ap.add_argument("--hash-block", metavar="FILE", type=Path,
                    help="print the custom-block hash for FILE and exit -- "
                         "the subprocess face of produce_block_hash, which "
                         "the install engine calls in-process, so producer "
                         "and checker share ONE canonicalization (review r2 "
                         "caught the Mac inline copy drifted to Python "
                         "semantics; the unification unit retired the "
                         "Windows native copy)")
    ap.add_argument("--hash-tree", nargs=2, metavar=("ROOT", "MANIFEST_FILE"),
                    help="print the managed-tree hash for the newline-"
                         "separated manifest file and exit (same producer "
                         "surface as --hash-block)")
    ap.add_argument("--hash-file", metavar="FILE", type=Path,
                    help="print the raw-byte sha256 for FILE and exit -- "
                         "producer-required: refuses a missing or unreadable "
                         "target (r5 M2: the native ssh helpers answered '' "
                         "for missing, the same value a recorded '' compares "
                         "equal to); checker mode keeps '' for legacy states")
    args = ap.parse_args(argv)
    if args.skip_hooks and args.probe_hooks:
        ap.error("--skip-hooks and --probe-hooks cannot be combined")

    # Findings can carry manifest-derived text, and the console encoding is
    # the INVOKER's (measured: the same U+FFFD line printed fine under
    # PowerShell and crashed the cp949 pipe under Git Bash). A checker must
    # never crash on its own report -- degrade unencodable chars instead.
    for stream in (sys.stdout, sys.stderr):
        try:
            if isinstance(stream, TextIOWrapper):
                stream.reconfigure(errors="replace")
        except (AttributeError, OSError):
            pass

    # Producer modes FAIL CLOSED on an unreadable target (exit 2): the Mac
    # installer captures these under `set -e`, the Windows installer checks
    # the exit code and refuses its state write -- either way a refusal
    # aborts the install before a poisoned baseline is written. Review r4
    # measured the alternative: an unreadable row buried in an
    # ordinary-looking digest, recorded, and later recomputed identically
    # into a false In sync.
    # The producer rules themselves live in the module-level produce_*
    # helpers, because scripts/install.py calls them IN-PROCESS: one
    # implementation of "what may become a recorded baseline", two callers.
    # These branches are the CLI adapter -- refusal reason to stderr, exit 2.
    if args.hash_block is not None:
        try:
            print(produce_block_hash(args.hash_block))
        except ProducerRefusal as exc:
            print("setup-check: %s" % exc, file=sys.stderr)
            return 2
        return 0
    if args.hash_file is not None:
        try:
            print(produce_file_hash(args.hash_file))
        except ProducerRefusal as exc:
            print("setup-check: %s" % exc, file=sys.stderr)
            return 2
        return 0
    if args.hash_tree is not None:
        tree_root, manifest_file = args.hash_tree
        try:
            print(produce_tree_hash(tree_root,
                                    read_manifest_transport(manifest_file)))
        except ProducerRefusal as exc:
            print("setup-check: %s" % exc, file=sys.stderr)
            return 2
        return 0

    repo, source_error = (args.repo, None) if args.repo is not None else installed_source_repo(args.home)
    if source_error:
        print("Drift: " + source_error)
        return 1
    from scripts.community import status
    return status(sys.modules[__name__], args.home, repo,
                  hooks=not args.skip_hooks, probe=args.probe_hooks,
                  check_updates=args.check_updates)


if __name__ == "__main__":
    sys.exit(main())
