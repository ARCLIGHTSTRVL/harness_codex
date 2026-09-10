---
consolidates:
  - 01a08c02-e8e2-7b32-afab-122e85dc0334-002
  - 01a08c02-e8e2-7b32-afab-122e85dc0334-003
  - 01a08c02-e8e2-7b32-afab-122e85dc0334-004
  - 01a08c02-e8e2-7b32-afab-122e85dc0334-005
  - 01a08c02-e8e2-7b32-afab-122e85dc0334-006
  - 01a08c02-e8e2-7b32-afab-122e85dc0334-007
  - 01a08c02-e8e2-7b32-afab-122e85dc0334-008
  - 01a08c02-e8e2-7b32-afab-122e85dc0334-009
title: Reliable updates and recovery of execution source
created: 2026-09-11
updated: 2026-09-11
type: comparison
tags: [decision, diagnosis, installer, portability, security]
sources: [scripts/lifecycle.py, scripts/source_recovery.py, scripts/runtime.py, scripts/native-hooks.py, scripts/sync.ps1, scripts/sync.sh]
confidence: medium
---

# Reliable updates and recovery of execution source

## Context and observed failures

The portability boundary in [[portable-distribution]] preserved user files, and
[[public-source-connection]] supplied a public update path. Reviewing the transition
between installation, a later update and recovery exposed gaps that a successful
first install did not exercise. These findings were reproduced at source a2efd0a.

A bundle nested inside another Git checkout inherited the parent's Git discovery.
The Windows sync wrapper successfully pulled that parent and installed the unchanged
nested bundle. The supplied directory layout made the wrong repository reachable;
checking only whether Git discovered any repository was insufficient.

A base Python without PyYAML successfully onboarded through a private .runtime,
but a later sync chose PATH Python again. Pull completed and installer lint then
failed importing yaml. Fresh bootstrap had the same failure. Separately, a status
check of the untouched installation reported hook drift under base Python but
passed under the private runtime. Expected hook commands were being generated from
the diagnostic process's interpreter instead of the installed interpreter.

The recovery journal restored policy, skills, hook configuration and state. During
an upgrade into a different source directory, the old scripts remained available,
which made the existing regression pass. In the ordinary in-place update case,
restored hook commands still referenced the overwritten directory. An isolated
A-to-B installation followed by rollback restored the A skill and returned success,
while the actual hook source remained B and setup-check reported drift. Successful
file restoration was therefore insufficient to restore the harness's execution.

The original reproduction scripts and receipts remain local under dist/review and
dist/review-sync; they are excluded from releases. They exercised Windows and are
not evidence of macOS host execution.

## Decision and alternatives

Updates must require the supplied source directory itself to be the Git root before
status, pull or install. A linked Git worktree remains a real source root even though
its .git is a file. An ancestor checkout cannot confer update identity on a ZIP.
Status failures stop updates explicitly; hidden untracked files still count as dirty.
Existing fork remotes and tracking branches remain recipient-owned.

Onboarding and platform installers share Python selection. Reuse a valid dependency
runtime, preserve a capable explicitly selected virtual environment, and create a
private runtime only during an authorized apply. Preview does not install packages.
Do not overwrite an invalid existing runtime or follow a linked runtime root. The
interpreter path must preserve virtual-environment identity on systems where the
binary itself is a normal symlink.

Independent review showed that requiring a virtual environment does not confine
pip's output: PIP_TARGET redirected an actual local-wheel install outside .runtime,
after which runtime validation failed. Private pip now strips destination overrides
and disables pip configuration files. Index/find-links and proxy environment settings
remain usable; recipients whose index or proxy exists only in pip configuration must
supply it through environment settings. This explicit tradeoff confines dependency
installation without changing their global pip configuration. A local-wheel regression
checks that both environment and configuration destinations remain untouched.

Each installation preserves a full allowlisted source copy. Normal source_repo
continues to name the editable checkout; rollback activates the preserved copy and
retains the original checkout as update_repo. This lets status inspect executed
source while the next sync can return to the update checkout. An activated snapshot
has no Git identity, so public revision comparison remains unknown rather than
misrepresenting the mutable checkout's HEAD as the restored version.

Always executing snapshots was considered: it simplifies immutability but changes
normal source semantics and every source consumer beyond the demonstrated failure.
Resetting the user's checkout was rejected because recovery must preserve uncommitted
work and also support bundles without Git history. Preserving only installed files
was rejected because hook scripts and supporting resources remain external to them.

The recovery digest covers the preserved source filename list and bytes, including
specifications and root skill references outside the narrower installed source digest.
An existing content-addressed copy must be verified before reuse, never overwritten
to hide a mismatch. Snapshot creation precedes installed target changes. A legacy
state without a snapshot can recover only while the original source still matches;
missing old execution source is a refusal before rollback. This condition does not
prohibit a forward update: an installation predating source snapshots must still be
upgradable after its checkout has changed, even when that old version is unrecoverable.

Recognized Python caches for existing source files are excluded from the source
digest. Strictly rejecting all generated caches was tested and rejected: a normal
helper invocation after rollback could generate native_hook_io bytecode and make
the next check treat a valid source as corrupt. Only cache filenames mapped to
existing source files are permitted; arbitrary source files hidden in cache directories,
sourceless bytecode and links remain invalid. The guarantee covers preserved source,
not independently attested interpreter dependencies or compiled runtime bytecode.
Store ancestors are validated before creating directories; a linked parent cannot
redirect source publication outside the intended local store. Historical snapshots
are checked against their own file set and digest, so a later release's changed
package inventory does not invalidate intact older recovery source.

## Journal continuity and runtime identity

Retargeting restored hooks and state changes their bytes. A surviving journal entry
must recognize those transformed bytes for the next rollback or uninstall. Its
after-hash can be updated only if it matched the original, untransformed restoration
bytes. If the user edited hooks or state between installations, that mismatch must
survive. Otherwise a later recovery could silently classify user work as installer
output and erase it. Owned command shapes are retargeted while unrelated hooks and
extension fields are preserved.

The selected installation interpreter is persisted separately from the diagnostic
interpreter. Check and probe must both construct expected commands using that saved
identity. The actual install still uses its currently selected runtime. Missing or
invalid persisted identity must not silently become the checker interpreter.
Reinstalling the same source with a new valid interpreter must refresh state even
when the previous interpreter remains runnable. Genuine legacy hook commands without
the new -B flag remain valid for checks; forward repair normalizes owned legacy
commands even with missing or corrupt state, without duplicating unrelated handlers.
User hook metadata survives safe command retargeting, while journal mismatches still
prevent a later uninstall from erasing edits absorbed between upgrades. Installing
from a new checkout after rollback replaces update authority with that new checkout.

## Consequences and validation boundary

Preserved sources use additional local disk space and remain after uninstall.
Virtual-environment binaries and dependencies are not backed up. Removing the saved
interpreter can block recovery even when source is intact; replacing dependencies
in place is not a claim covered by source integrity. Host trust and event delivery
remain separate from exact command probes.

Recovery preserves the existing per-file transaction limit: preflight catches known
conflicts, but concurrent filesystem mutation or I/O failure can interrupt a sequence
after some writes. Keep the journal and inspect named failures before retrying.
No force-overwrite recovery is added.

Local implementation acceptance completed on the tree based on a2efd0a, subsequently
published as 6e9235cb8ec1cef42d5ed8d2d484b224524339a1 after explicit authorization.
The final Windows suite passed 68 tests in 247.301 seconds, with all 101 pinned
code/test inputs unchanged. This includes actual installer/bootstrap/sync execution,
isolated dependency preparation, rollback and preservation regressions. Independent
recovery review passed 12 focused tests and rechecked its reported fixes. The final
integration log and input hashes are dist/review/integration/unittest.log and
tested-code.json; docs/PACKAGING.md records the broader acceptance boundaries.

The first integration run overlapped an existing test's source-selection correction;
its old loaded expectation failed. Freezing the test inputs and rerunning the entire
suite produced the final evidence above. macOS SSH and direct Tailscale ping timed
out, leaving actual macOS execution for the next platform-validation unit. Windows
and Git Bash execution do not close that gap. The implementation's local HEAD,
origin/main and live remote main matched after push. Personal installation remains
separate; the community bundle was not applied over the installed personal harness.

## MSYS2 recipient compatibility in 0.1.3

A recipient of the downloaded community bundle reported an installation failure with
MSYS2 Python. The exact original command and error text were unavailable, so a missing
MSYS2 installation on the maintainer's computer could neither confirm nor dismiss
the report. An official portable MSYS2 environment was prepared in an excluded test
directory, without changing global Python, PATH, packages or the real user profile.

The published 0.1.2 ZIP failed through its real PowerShell installer with UCRT Python
3.14.7. This interpreter reports os.name nt and sys.platform win32, yet creates
.runtime/bin/python.exe. The installer expected .runtime/Scripts solely from the
calling interpreter's os.name and stopped after creating the venv, before installation
state existed. The official MSYS2 Python documentation also describes its bin-based
venv layout: https://www.msys2.org/docs/python/.

The repair discovers an existing interpreter from the supported layout candidates,
then validates its directory, runtime tree and actual environment prefix before
reusing it. Multiple candidate layouts are refused rather than selecting whichever
appears first. A runtime created by Windows CPython must remain usable when the next
caller is native MSYS2 Python, and the reverse must also work. Merely special-casing
the current caller as MSYS2 was rejected because it would break this cross-caller case.
Removing link validation was rejected: layout compatibility must preserve the existing
pre-import boundary and confined dependency installation.

Native UCRT64/MINGW64 Python and MSYS POSIX Python are distinct. The latter reports
cygwin and an executable under /usr/bin, whose path and process conventions cannot
serve as native Windows hook commands. This unit supports native Windows interpreters;
it does not claim POSIX path translation or native host dispatch from MSYS Python.
The recipient-facing instructions identify the required environment. Actual acceptance
and remaining platform coverage are recorded in docs/PACKAGING.md; historical 0.1.2
checks above are not evidence for the changed 0.1.3 artifact.

The frozen 0.1.3 source passed 73 tests in 227.062 seconds under Windows CPython 3.11.9
with actual UCRT tests enabled, and all 102 pinned inputs were unchanged. A separate
real package-index run built PyYAML 6.0.3, installed successfully with POSIX Python
shadowing UCRT on PATH, passed a CPython status check and then passed reinstall.
Independent guard checks passed five cases under each native runtime before any
probe executed. These results establish the reproduced fix and preservation boundaries;
committed ZIP verification is a separate publication gate. Raw excluded receipts and
the exact remaining platform limitations are cataloged in docs/PACKAGING.md.

Review also found that skipping POSIX Python by command name alone was insufficient:
the first PATH match for both python and python3 could still hide an available native
Python farther down PATH. The Windows wrapper therefore inspects all external-command
matches in its existing name order. A real MSYS POSIX-before-UCRT installation passed.
It does not download or silently configure another global interpreter.

The canonical candidate ZIP then passed real dependency installation and
setup-check --probe-hooks under both native families, with saved runtime paths matching
and the shared portable MSYS2 tree unchanged. A first, deeply nested test profile hit
Windows's existing path-depth limit at a 263-character recovery entry before state
creation; rerunning the identical archive at a shorter depth passed. Shortening the
fixture was appropriate to isolate the runtime-family regression, but does not prove
arbitrarily deep recipient paths work. The failed evidence is retained, and general
long-path support remains outside this compatibility fix.
