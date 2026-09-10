---
consolidates:
  - 01a08c02-e8e2-7b32-afab-122e85dc0334-001
title: Public distribution discovery and update evidence
created: 2026-09-11
updated: 2026-09-11
type: comparison
tags: [decision, packaging, portability, installer, security]
sources: [scripts/public_source.py, scripts/setup-check.py, scripts/community.py, scripts/package.py, skills/sync/SKILL.md]
confidence: medium
---

# Public distribution discovery and update evidence

## Context and diagnosis

The distribution removed personal machine dependencies but also removed the public
repository's identity from operational skills. A valid existing Git clone could still
pull its configured upstream. A recipient starting with the extracted ZIP, a missing
installation state, or only an installed skill had no explicit public source to use.
The package's blanket personal-name check also rejected the intended public URL.
This distinction extends the isolation decision in [[portable-distribution]].

The previous setup-check success meant that installed policy, skills, hook configuration
and the local source agreed. It did not contact GitHub. Calling this result "In sync"
without a separate freshness statement could be read as a claim about the published
source. A content digest also cannot be compared directly with a Git commit identifier.

## Decision

The canonical public source is https://github.com/ARCLIGHTSTRVL/harness_codex and its
distribution branch is main. Installed-state source_repo remains the first authority
for the local source location. Skills provide explicit clone and download navigation
when no usable source can be found. Existing fork remotes remain recipient-owned;
sync continues to use the checkout's configured tracking branch.

The later [[maintenance-reliability]] decision separates an execution snapshot from
its update checkout after rollback: source_repo names executed source and update_repo
names the checkout used by sync. The original distinction between local content and
public revision evidence remains unchanged.

Normal setup-check remains offline. An explicit --check-updates adds a bounded,
read-only public revision lookup. Report local installation agreement and public
revision equality independently. A different revision is not proof that the clone
is behind: it could be ahead, diverged or on a fork. Even equal revisions do not prove
that a working tree has no edits or that hooks have executed in the native host.

An extracted source has no Git revision, including when a parent directory happens
to be a Git checkout. Keep local content checks usable and state that the online
comparison cannot establish its freshness. The migration path creates a new permanent
clone, applies its onboarding after preview, and verifies the new source before the
recipient retires an older directory still referenced by hooks.

The package gate permits the exact canonical public URL token while retaining its
personal-identifier and credential checks for other content. Public repository
identity enables distribution maintenance; it does not transfer an account,
credential, machine address, provider setting or model assignment.

## Alternatives and consequences

Keeping only a generic "use your configured remote" instruction was rejected because
it cannot recover the missing source for a ZIP recipient. Rewriting every remote to
the public repository was rejected because a recipient may intentionally use a fork.
Fetching on every setup-check was rejected because local installation verification
must remain available offline. A revision comparison is deliberately narrower than
an ancestry or archive-content proof.

The package retains its existing compatibility namespaces. No source-state schema
migration or automatic ZIP replacement is introduced. Publication of a source change
and replacement of an existing personal harness are separate authorized operations.
Use temporary installation profiles for verification. Their success does not establish
native hook trust or host delivery; see [[2026-09-10-distribution-readiness]].

## Evidence boundary

The focused tests exercise the revision comparison and URL gate; the distribution
suite exercises extracted installations and preservation. Current local validation
results belong in docs/PACKAGING.md. Network results identify a point-in-time revision,
and later publication can change it. A successful comparison must never be presented
as a publisher signature or proof that an uncommitted change is deployed.
