---
title: Community distribution readiness and evidence limits
created: 2026-09-10
updated: 2026-09-10
type: journal
tags: [evaluation, packaging, portability, installer]
sources: [docs/PACKAGING.md, tests/test_distribution.py, tests/test_native_routing.py, docs/NATIVE_AGENT_CONTRACT.md, docs/KNOWLEDGE-WORKFLOW.md, scripts/setup-check.py]
confidence: medium
---

# Community distribution readiness and evidence limits

## Layer A: question, method and result

Question: can a recipient install the curated bundle without the original user's
account or Git history, preserve existing files, and use the knowledge workflow?

Method: build and extract the source ZIP, install into temporary CODEX_HOME directories,
exercise platform launchers, compare preserved files and installed state, and use a
synthetic knowledge fixture for capture through saved handoff recovery. Actual machine
profiles are outside this test method. docs/PACKAGING.md holds the runnable commands
and detailed coverage; tests/test_distribution.py is the executable acceptance suite.

The preceding packaging session recorded all 19 tests passing on Windows Python 3.11
and macOS Python 3.13. It also recorded a macOS install starting without PyYAML, using
the package-local runtime and ending with setup-check reporting In sync. These are
historical session results, not fresh measurements in this knowledge closeout. Their
full raw test logs were not retained in this knowledge tree, so these numerical claims
are unpinned here. Do not treat this page as a replacement for raw CI or runtime evidence.

The exercised boundaries include existing policy and unrelated file preservation,
repeat installation, managed drift/backups, corrupt-state recovery, source changes,
hook retargeting after a directory move, self-contained helper discovery, credential
filename rejection, reproducible archives, preview, onboarding, missing-only project
initialization, rollback/uninstall refusal for user edits, and virtualenv retention.

For knowledge, the fixture supplies a decision, evidence, rejected alternative and risk.
It generates a draft and verifies refusal to apply the untouched DRAFT. An explicitly
authored distilled fixture is applied, then provenance, archival, subsequent delta IDs
and kb-lint are checked. PreCompact saves NEXT and a plan handoff; after NEXT changes,
SessionStart(compact) emits the saved state. This establishes bookkeeping and saved-state
recovery for those inputs. It does not evaluate an actual model's distillation quality.

Decision: deliver the locally built bundle with receiver instructions and the explicit
limits below. The rationale is [[portable-distribution]]. No active implementation or
working plan remains; a recipient's installation is a separate execution in that user's
environment. Publication and licensing were not part of the completed work.

## Version 0.1.2 measured update

Question: can the newer unit/context/report policy and user-owned role choices be
ported while preserving neutral distribution and installation/recovery behavior?

The source was frozen before the acceptance run. Windows Python 3.11 passed all 31
tests in 25.038 seconds; macOS Python 3.13 passed the same 31 tests in 14.223 seconds.
There were 19 distribution tests and 12 native routing/report tests, with no skips.
Both lint runs passed. These are freshly read terminal results for 0.1.2, separate
from the unpinned historical 0.1.1 claims above. The local raw logs are
`.ask-artifacts/v0.1.2-distribution-validation/logs/windows-unittest.log` and
`.ask-artifacts/v0.1.2-distribution-validation/logs/mac-unittest.log`, with sibling
lint/package logs. Raw machine logs are not distribution inputs.

The tested ZIP before final documentation closure was
`3691d26ad0a0d1862bcf0415c249bd3e5759351bea4f26dc6556fa1b16a742c6` (SHA-256),
with 124 entries. The Mac received exactly those bytes. Independent rebuilds on both
platforms matched that hash. A source manifest binds the tested inputs; final closure
changes only documentation and handoff records, so the delivered ZIP gets a new checksum
without claiming that its pre-closure archive hash is still current.

Acceptance now includes preservation of recipient-owned optional global routing bytes,
no shipped role-pin JSON, project override precedence, malformed/link refusal, declared
efforts, compatible catalog drift, source and content invalidation, expiry, home isolation
and single report injection. The existing extracted-release checks still cover actual
platform launchers and recovery boundaries. An independent source review passed
correctness and purpose fit with no material findings; it also exercised synthetic
namespace, malformed-effort and completion-evidence boundaries. This is source review
and local test evidence, not cross-provider independence or observed host dispatch.

The decision is to deliver 0.1.2 as a neutral local ZIP, retain the older releases, and
leave receiving-user model choices untouched. [[portable-distribution]] explains why
reusable role choices belong to the recipient and why code-derived knowledge is kept
separate from durable rationale.

## Final 0.1.2 boundary verification

A late source comparison identified two further gaps in the intended boundary:
the package builder could include a role-mapping file added under an allowed tree,
and native state writes could follow a linked state root. The initial acceptance
did not cover those corrections. The preserved pre-correction archive reproduced
both behaviors; the new checks reject them before a package or external state write.
The case-insensitive filename check preserves neutral releases, while the state-path
check covers root and ancestor links, including an independently exercised Windows
junction. Canonical real directories remain valid. Direct macOS CLI users must resolve
the `/tmp` and `/var` aliases; installed hooks already use resolved home paths.

After bounded integration and independent review, a new frozen-source run passed all
33 tests on Windows in 24.659 seconds and macOS in 13.778 seconds, with no skips. The
suite consists of 20 distribution tests and 13 native routing/report tests. Both lint
runs passed. These results supersede the initial 31-test acceptance for the final
source. The terminal logs are
`.ask-artifacts/v0.1.2-boundary-validation/logs/windows-unittest.log` and
`.ask-artifacts/v0.1.2-boundary-validation/logs/mac-unittest.log`.

The corrected validation ZIP before final documentation closure had SHA-256
`f439a063ea7c8274b07ec74f0bbb8b2d58d71b48873f4a2dcf24fa24048fe3dc`, with 124 entries.
Its transferred bytes and both-platform rebuilds matched. Source manifests distinguish
this corrected basis from the earlier one. Subsequent closure edits are limited to
documentation; final artifact identity comes from the regenerated checksum sidecar.
Retaining the earlier artifact without correction was rejected because it would retain
the reproduced boundary gaps. Both fixes and their explicit compatibility effects are
accepted, with no remaining material review finding. [[portable-distribution]] owns the
distribution and preservation rationale.

After this validation, the user authorized an initial private repository on `main`, its
push, and a personal backport. These actions were not part of the 33-test run, and this
record does not claim their completion. A resulting Git checkout verifies source
references at its current `HEAD`; the initial commit cannot self-pin its future SHA.
The distributed ZIP remains free of Git history and therefore has no commit pin. Public
visibility and license selection remain outside this authorization.

## Layer B: why the checks matter

File presence is a weak portability criterion. A moved bundle initially retained old
hook paths; canonical path handling and retargeting against the previous managed
baseline addressed that failure. On macOS, resolving a venv Python symlink to the base
interpreter discarded the dependency environment; retaining the venv executable path
addressed that case. These failures explain why actual launchers and extracted archives
were tested in addition to installer helpers.

Rollback must be judged against the user's edits, not merely the last installed version.
An edit between upgrades can become the next version's before-state. A combined uninstall
that ignores this discontinuity could erase valid instructions even when its current
files match the latest install hashes. The accepted refusal behavior preserves that
intermediate state rather than claiming every uninstall can be automatic.

## What remains unproved

Installed bytes and successful command probes do not establish Codex hook trust, actual
host event dispatch, model-visible delivery or delegated model identity. The recipient
must review supported hook definitions and observe runtime activation in their host.
No claim is made that the complete upstream regression suite was rerun, that a
cross-provider review occurred, or that unsigned checksums authenticate the publisher. A checksum
identifies bytes and must be regenerated when packaged documentation changes.

Use [[index]] to resume from the decision and evidence records; consult source and actual
host observations before extending these conclusions to a different environment.
