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
