---
title: Portable distribution and recovery decisions
created: 2026-09-10
updated: 2026-09-10
type: comparison
tags: [decision, packaging, portability, installer, security]
sources: [docs/PACKAGING.md, docs/NATIVE_AGENT_CONTRACT.md, codex/AGENTS.md, scripts/lifecycle.py, scripts/package.py, START-HERE.md]
confidence: medium
---

# Portable distribution and recovery decisions

## Context

The requested outcome was a bundle another user could give their Codex to install,
including the knowledge workflow and its preservation mechanisms. A personal checkout
contained useful behavior alongside machine-specific operating choices. Copying the
whole checkout would transfer those choices and make the recipient dependent on an
unrelated account, machine layout or provider. Removing only names would not establish
functional portability: installation, discovery, project initialization and recovery
also need usable entrypoints.

## Decision

Keep a separate community source tree with selected skills, policy, hook adapters,
templates and the shared installer. Use an explicit package allowlist and content
digests rather than requiring the original Git history. Credentials, SSH destinations,
proxy setup, selected models, personal fragments and installation recovery records
are outside the distribution. Initial private source publication and personal backport
were later authorized; public visibility and licensing remain separate decisions.

START-HERE.md gives the receiving Codex a concrete install request. Onboarding checks
prerequisites, previews targets, and applies installation when requested. If PyYAML is
missing it prepares a package-local virtual environment. The interpreter used by hooks
must retain that environment; resolving its executable symlink to a system interpreter
would silently lose the dependency. The extracted directory must remain in a permanent
location because hook commands reference it.

## Knowledge ownership

The installed policy requires timely capture of consequential findings, alternatives,
risks and unresolved questions in projects with knowledge/_fragments/. An explicit
initializer creates missing scaffolding and the empty unit registry without overwriting
existing project files. Project-specific conventions and hook merging still need review.

The agent performs semantic distillation. Scripts prepare drafts, validate selected
provenance, apply reviewed content and archive disposed fragments. Hooks preserve saved
NEXT/plan state and emit recovery context. A saved handoff cannot reconstruct decisions
never written down. Hook-time automatic summarization was rejected because it would add
a new semantic behavior, and hook execution alone provides no guarantee of sound curation.
Preserve reasoning and evidence in the page; a shorter reminder is insufficient when a
future reader needs to decide whether the original tradeoff still applies.

## Portable unit policy and role choices

The 0.1.2 update carries the reusable workflow improvements without the original user's
model assignments. The primary agent owns scope, architecture, integration and acceptance;
configured delegates receive bounded tasks and return evidence tied to current source.
Model and effort names come from the receiving user's choices and host catalog. Copying
the original role pins was rejected because access, capabilities and preferences differ.
Requiring a new choice in every session was also rejected: a valid authorized mapping
can be reused until the user changes it or the catalog no longer supports it.

An optional global mapping is read from the community namespace only, with project
overrides first. Installation does not create, update or remove that user-owned file.
Silently replacing a malformed project mapping with global settings would hide a user's
explicit choice; the routing loader must refuse it instead. Source identity and content
are part of attestation so a previous approval cannot be reused after either changes.

Context economy means supplying all knowledge needed for one verifiable outcome while
excluding unrelated history. Source code establishes current behavior, observed execution
establishes what ran, and user acceptance criteria establish purpose fit. Keeping detailed
behavior descriptions beside every function was rejected because those copies can drift
and repeatedly consume context. A stable file-purpose statement is sufficient in source;
wiki explanations are derived from current code, while knowledge preserves rationale and
alternatives. Relevant evidence and child reports are rechecked after their basis changes.

These are operating contracts and deterministic routing checks. They do not erase history,
guarantee zero context drift or prove that a host delivers a hook's output. The current
test and installation evidence belongs in [[2026-09-10-distribution-readiness]].

## Recovery alternatives and consequences

Whole-profile rollback was rejected. Unrelated instructions, credentials or configuration
may change after installation; restoring an entire directory could erase that work.
The selected design records original bytes and subsequent content hashes only for policy,
hooks, community state and managed skill targets. Later content changes cause refusal.
The same protection applies across upgrades: a user's edit absorbed by the next install
must not disappear when uninstalling several recorded versions at once. Roll back one
version at a time to preserve the intermediate edited baseline.

A recovery journal contains original file bytes and stays local. It is not a shareable
diagnostic attachment. Backups and runtime evidence remain after removal. Releases that
predate snapshots have no reconstructable original uninstall baseline. A caught failure
with a complete after-record can be restored; a crash without that record requires
inspection. Restoration is per-file, so I/O failure or concurrent changes may interrupt
it after some writes. Preserve the journal and inspect the failure before retrying.

Rebuilding the installer from scratch was rejected in favor of adapting existing safety
primitives. Automatically propagating the installation to a peer was excluded because a
recipient may have a different machine topology and did not authorize that action.

## Evidence and remaining limits

The validated source and docs above support these contracts. Validation used a
standalone tree; an authorized private checkout resolves source references against its
current `HEAD`, while the ZIP omits Git history and has no commit pin. The initial commit
cannot self-reference its future SHA, and this record does not claim the external push
or personal backport completed.
The acceptance record [[2026-09-10-distribution-readiness]] separates observed installer
behavior from trust, host dispatch and semantic quality. The local archived fragment
records remain unchanged as historical inputs; this page is a later resolved write-back,
not a claim that the consolidation script promoted those archived deltas.

Return to [[index]] for the knowledge catalog.
