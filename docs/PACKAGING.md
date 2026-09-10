# Community distribution contract

During the initial standalone packaging phase on 2026-09-10, the owner requested a new
project under C:/dev containing a general-purpose distribution, and the upstream checkout
remained unchanged. The package retains workflow skills, native
hook adapters, safe installer primitives and project templates. Personal SSH aliases,
CLI proxy installation, provider alignment, chosen models, account files, runtime state,
working notes, replay fixtures and Git history are excluded.

The core installer is adapted from the upstream shared Python engine. Its snapshot,
path checks, backup allocation, policy merge and skill ownership rules are retained.
The distribution uses a separate policy marker and state file to preserve unrelated
policy. A content digest over scripts, skills, templates, policy and VERSION replaces
the requirement for an upstream Git commit. Installed bytes are checked against the
captured source before recording state. Files outside that managed scope remain owned
by the receiving user. The baseline identifies content, not a publisher signature.

The alternatives were copying the entire personal checkout, or rebuilding the installer
from scratch. A curated distribution with the existing mutation primitives avoids
shipping personal operational instructions while retaining the established file safety
behavior. Automatic peer propagation is excluded because users have different machines.

Installation configures hooks but cannot grant trust or prove native host delivery.
Model/account/permission choices are never imposed. Repository publication does not
select an open-source license. Native role catalog attestation is still required before
any user-authorized managed delegation.

## Version 0.1.2 update

### Maintenance reliability (2026-09-11, implementation 6e9235c)

The maintenance follow-up addresses four reproduced transitions: nested ZIP sync
acting on an ancestor Git repository; updates failing to reuse the dependency runtime;
in-place rollback restoring files but retaining newer hook source; and diagnostic
Python selection causing false hook drift. Decision rationale and alternatives are
in knowledge/comparisons/maintenance-reliability.md. Local acceptance is complete
for the working tree based on a2efd0a. After explicit authorization, implementation
6e9235cb8ec1cef42d5ed8d2d484b224524339a1 was pushed to public main; local HEAD,
origin/main and live remote main matched. A documentation closeout may advance HEAD.

The sync/bootstrap wrappers require an exact Git root and explicitly refuse status
failures and untracked changes. They retain existing tracking configuration. Platform
installers and onboarding share the standard-library runtime selector; dependency
installation stays in the private runtime and preview does not create it.
Private pip execution disables pip config files and strips destination overrides;
index/find-links and ordinary proxy environment settings remain usable. An index or
proxy supplied only through pip config must be supplied through environment settings.

Installation preserves complete allowlisted source under the recipient's CODEX_HOME.
State schema 2 gains validated recovery_source, recovery_digest and python_executable
fields. Normal source_repo is the update checkout. Rollback activates a preserved
source_repo and retains the editable checkout as update_repo, without modifying Git.
The recovery digest covers preserved source filenames and bytes; recognized Python
caches generated for existing source files are excluded. Sourceless bytecode and
unexpected source files remain invalid. The original source_digest remains the
installed content contract. Interpreter binaries are not
preserved, so the recorded interpreter must remain runnable.

Status defaults to the installed execution source; explicit --repo still compares the
specified source. Hook checks and command probes use the installed interpreter rather
than the checker process's interpreter. A rollback snapshot has no Git history, so its
public revision comparison is unknown. Hook trust and native host delivery remain
outside these checks.

Rollback validates source, runtime and recorded target bytes before restoration.
Legacy state lacking a source snapshot is recoverable only while its previous source
matches. Journal hash adjustments for retargeted hooks/state preserve mismatches from
user edits between installations; they cannot turn those edits into removable output.
Source snapshots, recovery journals and runtime evidence remain local after uninstall.
The existing per-file restoration/concurrent-writer limitations below still apply.

Validation on Windows Python 3.11: the final full suite passed all 68 tests in
247.301 seconds. The 101 pinned code/test inputs were unchanged during that run.
Coverage includes actual PowerShell install/bootstrap/sync with a no-PyYAML base,
private offline-wheel installation with hostile pip destination settings, Git Bash
and PowerShell repository boundaries, same-directory rollback followed by helper
execution, legacy/corrupt-state forward repair, user-edit continuity, and a checker
using a different interpreter. An independent recovery review also passed its 12
focused tests and rechecked the reported fixes. Source lint and lifecycle skill
validation passed. Knowledge lint reported four content pages and zero issues; wiki
lint retained seven medium documentation-coverage advisories and no blocking finding.
Raw receipts remain excluded under dist/review/integration.

The first integration run overlapped a one-line update to the existing rollback
test's source-selection expectation and failed that loaded old test. Product code
was unchanged; the final run above used the frozen test and passed. Its log and
input manifest, rather than the overlapping run, are the acceptance evidence.

The release gate rebuilds an allowlisted ZIP with a SHA-256 sidecar. Final artifact
verification compares packaged code/test bytes to that manifest and exercises the
extracted Windows installer, setup-check and hook command probes in a disposable
profile; its receipt is dist/review/integration/package-receipt.json. macOS SSH and
Tailscale ping timed out, so this follow-up has no macOS host execution evidence.
Git Bash coverage is not a substitute. The separate publication readback above does
not establish personal installation or native host delivery.

### Public source connection validation (2026-09-11)

The public source URL and main branch are explicit metadata in scripts/public_source.py.
Normal setup-check remains offline and checks local content; --check-updates adds a
read-only public revision comparison. Different commits do not establish ancestry, and
ZIP folders cannot borrow a parent checkout's revision. Sync preserves existing tracking
configuration, with an explicit clone migration path for ZIP recipients.

The package personal-identifier gate allows only the exact canonical repository URL
token, optionally ending in .git. Other owner-name occurrences, URL suffixes and lookalikes
remain rejected. This change adds public distribution identity, not recipient data.

Validation on Windows Python 3.11: python -m unittest discover -s tests completed all
42 tests in 35.902 seconds with OK. This includes the existing extracted-install and
preservation suite plus the public-source regressions. Source lint, tree secrets gate,
diff whitespace check and knowledge lint passed. Wiki lint retained its existing six
medium documentation-coverage advisories and no blocking finding.

A separate temporary profile passed actual install.py installation, offline setup-check
and setup-check --check-updates, each with exit 0. The live public main tip and local
HEAD were both 68ec2ed8b69a71ba54324990fa51195454ef4aba. That equality does not include
the uncommitted source changes. Both platform wrapper sources were inspected; this new
live installation check ran on Windows. No existing user profile was installed over.

Local raw receipts are dist/validation-public-source/unittest.log and
dist/validation-public-source/live-install-check.log, which are excluded from releases.
The final rebuilt ZIP's SHA-256 sidecar identifies its bytes. These checks establish
neither publication of this change nor native hook trust or host event delivery.

After explicit publication authorization, implementation commit
f626e89450af31cad2abbcbfd796e479594d213f was pushed to public main. Local HEAD,
origin/main and git ls-remote readback matched at that publication checkpoint.
The committed implementation matched the reviewed diff, and staged secret checks
passed. The later documentation closeout updates source references and publication
status; it does not replace any user's installed harness.

The policy now gives an authorized unit complete relevant context, explicit acceptance,
source-based evidence and checkpoints while excluding unrelated history. Source code
defines implementation behavior; code-derived explanations belong in wiki and decision
rationale in knowledge. New prose comments are limited to a stable file-purpose statement.
Touched stale comments are corrected or removed without an unrelated comment cleanup.

Delegates return status/outcome, scope/basis, checks/evidence, findings/unknowns and
parent action. The parent checks current source before accepting a child result.
Changes to code, requirements or dependency contracts invalidate affected evidence;
saved prompts and handoffs cannot guarantee that context never drifts.

Native routing accepts optional declared reasoning efforts and keeps supported selected
roles usable when unrelated catalog entries change. Project choices take precedence
over optional recipient-owned global choices in the community namespace. No model pin
file ships, and installation never creates or replaces those choices. Invalid or linked
explicit settings are refused; fresh attestation remains necessary. See
docs/NATIVE_AGENT_CONTRACT.md for the exact paths and launch/report boundaries.

The existing installer, recovery ownership and public-neutral package allowlist remain
the distribution contract.

### Source publication boundary

The final pre-publication 33-test validation ran from a standalone source tree without
Git history. The repository was subsequently published on `main` at
`8237426b6dfcd8810bd3b2f66d6d23021b21c684`; local `HEAD` and `origin/main` matched,
and visibility was verified as private at that initial checkpoint. The user then directed
the repository to be renamed `harness_codex` and made public. The public source URL is
now explicit distribution metadata so recipients can locate updates; private account
and machine data remain excluded. No license is selected by this publication.

After repository initialization, source references are checked against the current
checkout's `HEAD`. The initial commit cannot embed its own future SHA, and the packaged
ZIP deliberately omits `.git`, so the ZIP has no commit pin. Its adjacent SHA-256
sidecar identifies archive bytes instead.

Git source includes the optional repository-only `githooks/pre-commit`. It is not
installed into recipient hook configuration automatically and is excluded from the
distributed ZIP. Git source accounting is 123 distributed source files plus that hook,
124 tracked files total. ZIP accounting remains 123 source entries plus the generated
synthetic seed, also 124 entries total.

### Initial version 0.1.2 validation

Windows Python 3.11 and macOS Python 3.13 each passed all 31 tests: the 19 distribution
checks and 12 native routing/report checks, with no skips. Both platform lint runs passed.
The distribution checks exercise actual platform installers in temporary profiles,
repeat installation, guarded recovery, moved-source upgrades and saved handoff behavior.
They also verify that recipient-owned global routing bytes survive installation and
reinstallation and that no role-pin JSON is included in the ZIP.

The native checks cover absent mappings, project precedence, malformed/linked overrides,
dangling nested boundaries, allowed and scalar-only efforts, catalog compatibility,
source/content invalidation, expiry, report injection and explicit-home isolation.
An independent source review found no material correctness or purpose-fit defects;
additional synthetic probes checked invalid effort lists, namespace isolation and
completion evidence with missing, matching or conflicting effort.

The initial tested archive contained 124 entries. Windows and macOS rebuilds were byte-identical,
and the transferred ZIP hash matched before extraction. The extracted release passed
the secret and personal-data checks. These results predate the additional package/state
boundary corrections and are retained as the initial baseline. Current validation must
include refusal to package a role mapping and refusal of linked state roots/ancestors.
The final ZIP's adjacent SHA-256 file identifies the delivered artifact.
These checks install only into temporary homes and do not prove host trust, event
delivery, provider identity or semantic knowledge quality.

### Final version 0.1.2 validation

Two additional boundary checks were integrated and independently reviewed before
delivery. The packager rejects `agent-routing.json` names case-insensitively before
creating an archive, and native state access rejects linked roots and ancestor
components, including Windows name-surrogate reparse points. Tests reproduce the
previous behavior and verify refusal without changing the external target. Resolved
normal directories remain usable; direct macOS CLI callers must resolve `/tmp` and
`/var` aliases as documented in docs/NATIVE_AGENT_CONTRACT.md.

The corrected source passed all 33 tests on Windows Python 3.11 and macOS Python 3.13:
20 distribution tests and 13 native routing/report tests, with no skips. Both lint
runs passed. Both platforms rebuilt the same transferred 124-entry validation ZIP
byte-for-byte. The bounded follow-up source review passed correctness and purpose fit,
including an actual Windows junction refusal check. This final run supersedes the
initial 31-test acceptance for the corrected boundaries.

After this run, only final results and handoff documentation change. The tested
implementation remains byte-identical, and the delivered ZIP is rebuilt with its own
SHA-256 sidecar. The local raw logs and hash manifests stay outside the release.

### Initial Git publication verification

After canonical Git newline materialization, staged and tree secret checks passed. The
model-name gate passed with exactly the two registered historical-attribution
suppressions. Windows then passed all 33 tests in 25.143 seconds. The resulting
124-entry publication-validation ZIP had SHA-256
`f0f51f26c3d7b3718e02afd667aa09fd5a79010c72113b0a0f69fa83621ef943`.
This artifact predates documentation closeout; the rebuilt post-closeout ZIP receives
its own checksum. Repository publication and Git-only pre-commit availability do not
establish recipient hook installation, trust, event delivery or provider identity.

## Version 0.1.1 historical validation

The 0.1.1 distribution-specific suite has 19 behavioral checks. Windows Python 3.11
and macOS Python 3.13 each passed all 19, including their real PowerShell/Bash installers.
Run them with `python -m unittest discover -s tests -v`.
Tests install the extracted ZIP into temporary CODEX_HOME directories, with spaces
in source/profile paths; they do not install into either machine's normal profile.

Covered: preservation of existing policy, SSH, Codex configuration, auth file bytes,
system skills, unrelated skills and custom hooks; idempotent reinstall; installed
skill drift and backups; corrupt-state recovery; source changes; upgrade to a different
source directory without duplicate hooks; installed review-helper discovery; credential
filename rejection; byte-identical ZIP rebuilds. The setup-check command and its exact
hook-command probes also run against the temporary installation.

Added coverage: read-only previews, onboarding, non-overwriting knowledge initialization,
rollback to the previous install, uninstall to the original baseline, refusal of later
user edits and edits between upgrades, recovery after a caught installation failure,
and virtual-environment interpreter retention. A separate macOS smoke started without
PyYAML, ran `onboard.py --apply`, and verified that the package-local dependency runtime
produced an installation reported as In sync by setup-check.

The knowledge fixture captures a decision with evidence, an alternative and a risk;
queries it; generates a draft; proves untouched DRAFT apply is refused; applies an
explicitly authored distilled page; checks provenance, archival and continued delta IDs;
then runs kb-lint. PreCompact saves NEXT/plan state, and SessionStart(compact) emits
that saved state after live NEXT changes. This verifies the pipeline with synthetic
content. It does not measure a model's semantic distillation quality or host delivery.

The first Windows launcher test exposed short/long path spelling differences in hook
definitions. Canonicalizing generated command paths fixed the mismatch. A moved-release
test exposed retained old source paths; installation now retargets only handlers that
match the previous community baseline. On macOS, temporary /var paths must be resolved
through /private, and versioned Homebrew Python requires its libexec/bin on PATH.
These environment conditions are documented; link rejection has not been weakened.

Correctness: the checks above pass for the exercised installer and package boundaries.
Purpose fit: the resulting ZIP needs neither the original owner's account nor Git history,
and contains no SSH aliases, proxy configuration, pinned models, original Git history,
personal journals or replay fixtures. The original upstream repository remained unchanged
during the initial standalone packaging phase described above.

Limits: the complete upstream regression suite is not claimed as revalidated. Native
host dispatch, trust and model identity are not established by hook command probes.
No external reviewer was invoked. Package checksums identify content but are unsigned.
The repository is public under the display name `harness_codex`; no open-source license
has been selected.

## Readiness decisions and recovery boundary

Version 0.1.1 restores the explicit installed-policy duty to capture consequential
decisions as they form and consolidate them at unit boundaries. Capture must preserve
evidence, rejected alternatives and open risks; saving a shortened reminder alone loses
the basis for future decisions. The empty unit registry and explicit project initializer
make the workflow usable on a recipient's project without importing personal journals.
The agent owns meaning and distillation, matching the original harness; hooks only
preserve saved handoff state. Adding automatic hook-time summarization was rejected:
it would introduce a new semantic behavior and still could not recover unrecorded intent.
See docs/KNOWLEDGE-WORKFLOW.md for the operational steps.

Whole-profile restore was rejected because unrelated user instructions and configuration
could have changed. Instead, lifecycle.py records only the original policy, hooks, state
and managed skill targets, and checks recorded content hashes before restoration. It
also rejects discontinuous history: an edit absorbed between two upgrades must not be
lost in a combined uninstall. Single-version rollback preserves that intermediate state.
Recovery records contain original bytes and stay local; they are never release inputs.
The maintenance follow-up additionally preserves execution source for new installations,
as described above; the historical installed-file journal alone could not undo an
in-place source replacement.

Recovery cannot reconstruct the baseline of an older release without snapshots. A crash
without complete post-install hashes requires manual inspection; a caught failure with
a complete record can be rolled back. Restoration is per-file, not a filesystem-wide
transaction. A concurrent edit or I/O failure can stop it after some files were restored;
retain the journal, inspect the named failure, and retry only after resolving it. Backups
and runtime evidence remain after uninstall. No force-overwrite option is provided.

START-HERE.md supplies the recipient's installation request and environment/preview/apply
sequence. The package must remain at its installation path because hooks reference it;
upgrading from another directory requires running that copy's installer. No original
owner account, proxy, model choice, SSH destination or Git history is required.
