# Codebase wiki

See docs/PACKAGING.md for the distribution boundary and installation contract.
No historical upstream wiki claims have been imported.

## Current source contracts (verified at `8237426`)

- `scripts/onboard.py:main@8237426`: environment checks, read-only preview, optional private
  dependency runtime, install and setup-check. Receiver entrypoint: START-HERE.md.
- `scripts/lifecycle.py:install@8237426`, `scripts/lifecycle.py:restore@8237426`: scoped before/after records and guarded
  rollback/uninstall; user edits between upgrades prevent combined removal.
- `scripts/init-knowledge.py:scaffold@8237426`: missing-only project scaffolding and optional
  hook files; existing definitions require explicit merging.
- `skills/knowledge-fragment/scripts/consolidate.py:main@8237426`: draft/apply bookkeeping around
  agent-authored distillation; workflow in docs/KNOWLEDGE-WORKFLOW.md.
- `scripts/native-hooks.py:handlers@8237426`: saved handoff capture/recovery wiring, distinct from host trust
  and actual model-visible dispatch.
- `tests/test_distribution.py:DistributionTests@8237426`: extracted-release installation and knowledge lifecycle
  acceptance; results and limits in docs/PACKAGING.md.
- `scripts/native_agents/routing.py:load@8237426`, `scripts/native_agents/routing.py:attest@8237426`, `scripts/native_agents/routing.py:pre@8237426`: recipient-owned project/global choices, declared
  effort selection and fresh source-bound attestation; contract in docs/NATIVE_AGENT_CONTRACT.md.
- `scripts/native_agents/boundary.py:project_root@8237426`: explicit linked routing boundaries
  remain visible to the loader's refusal checks.
- `scripts/native_agents/boundary.py:Store.path@8237426`: rejects linked state roots and ancestor
  components before a state read/write can follow them.
- `scripts/package.py:build@8237426`: rejects role-mapping filenames from the allowlisted inputs.
- `scripts/native_agents/roles.py:instruction@8237426`: bounded parent report contract, preserving
  the delegated task without duplicate role injection.
- `tests/test_native_routing.py:NativeRoutingTests@8237426`: neutral synthetic-catalog regression checks for those
  routing and report contracts.

The initial source commit was verified at local `HEAD` and `origin/main` before the
repository was renamed `harness_codex` and made public. These pins identify that
implementation even if a later documentation-only closeout advances `HEAD`. Distributed
ZIPs omit Git history and therefore have no commit pin. The repository-only pre-commit
hook is excluded from the ZIP and is not evidence of native host trust or runtime delivery.

## Public source connection (verified at `f626e89`)

These implementation references identify the public source commit verified by remote readback.
Decision rationale: knowledge/comparisons/public-source-connection.md.

- `scripts/public_source.py:report@f626e89`: identifies the canonical public source, stays offline
  by default and optionally compares the exact checkout root's HEAD to public main.
  Equality is a revision result; differences do not establish ancestry, and missing Git
  identity or a failed remote lookup is unknown. Parent checkouts cannot identify ZIPs.
- `scripts/community.py:status@f626e89` and `scripts/setup-check.py:main@f626e89`: preserve local content
  and hook checks, add the explicit --check-updates option and report network freshness
  independently. Hash helper modes keep their existing output contract.
- `scripts/package.py:has_personal_identifier@f626e89`: permits the exact public repository URL
  token, optionally ending in .git, while keeping other personal identifiers blocked.
- `skills/sync/SKILL.md@f626e89`: resolves the installed source directory, checks existing Git
  tracking, uses the platform wrapper and verifies installation afterward. ZIP migration
  uses a new permanent clone and preserves the old source until hook retargeting is verified.

The Windows and macOS sync wrappers retain their existing pull/install behavior and
configured tracking source. No remotes, account settings or installed-state schema change.

## Maintenance reliability (6e9235c)

These contracts at 6e9235c supersede the affected historical entrypoint/recovery
claims above. Local acceptance passed 68 tests on the frozen working tree; evidence
and platform limits are in docs/PACKAGING.md. Decision context:
knowledge/comparisons/maintenance-reliability.md.

- `scripts/sync.ps1`, `scripts/sync.sh`, `scripts/bootstrap-windows.ps1` and
  `scripts/bootstrap-mac.sh`: exact source-root discovery and successful explicit
  untracked-file status precede pull/install. Valid linked Git worktrees retain their
  own root identity. Existing tracking configuration is unchanged.
- `scripts/runtime.py:select_python`: shares dependency-runtime selection across
  onboarding and both installer wrappers. It validates runtime boundaries before
  probing packages and isolates pip's destination during apply. Preview creates no venv.
- `scripts/source_recovery.py:prepare`, `scripts/source_recovery.py:publish` and
  `scripts/source_recovery.py:validate`: capture the current release allowlist, publish
  a content-addressed local source, and verify historical copies against their own
  complete file content identity rather than a newer release's required file list.
- `scripts/install.py:prepare_install_recovery` and `scripts/lifecycle.py:activate_source`:
  new installations record source recovery and interpreter identity. Rollback retargets
  exact owned hook commands to preserved source while retaining the editable update
  checkout. The journal retains user-edit mismatches across successive restorations.
- `scripts/setup-check.py:installed_source_repo`, `scripts/native-hooks.py:installed_contract`
  and `scripts/native-hook-status.py:probe`: status defaults to installed execution
  source; checks and command probes use the installation interpreter. Explicit --repo
  retains comparison behavior, and snapshots have no public Git revision identity.

Source recovery does not preserve interpreter binaries, establish host trust or prove
native host event delivery. Packaging and platform acceptance remain in docs/PACKAGING.md.
