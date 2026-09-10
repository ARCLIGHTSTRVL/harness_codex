# Codebase wiki

See docs/PACKAGING.md for the distribution boundary and installation contract.
No historical upstream wiki claims have been imported.

## Current source contracts (verify at checkout HEAD)

- `scripts/onboard.py:main`: environment checks, read-only preview, optional private
  dependency runtime, install and setup-check. Receiver entrypoint: START-HERE.md.
- `scripts/lifecycle.py:install`, `restore`: scoped before/after records and guarded
  rollback/uninstall; user edits between upgrades prevent combined removal.
- `scripts/init-knowledge.py:scaffold`: missing-only project scaffolding and optional
  hook files; existing definitions require explicit merging.
- `skills/knowledge-fragment/scripts/consolidate.py`: draft/apply bookkeeping around
  agent-authored distillation; workflow in docs/KNOWLEDGE-WORKFLOW.md.
- `scripts/native-hooks.py`: saved handoff capture/recovery, distinct from host trust
  and actual model-visible dispatch.
- `tests/test_distribution.py`: extracted-release installation and knowledge lifecycle
  acceptance; results and limits in docs/PACKAGING.md.
- `scripts/native_agents/routing.py`: recipient-owned project/global choices, declared
  effort selection and fresh source-bound attestation; contract in docs/NATIVE_AGENT_CONTRACT.md.
- `scripts/native_agents/boundary.py:project_root`: explicit linked routing boundaries
  remain visible to the loader's refusal checks.
- `scripts/native_agents/boundary.py:Store.path`: rejects linked state roots and ancestor
  components before a state read/write can follow them.
- `scripts/package.py:build`: rejects role-mapping filenames from the allowlisted inputs.
- `scripts/native_agents/roles.py:instruction`: bounded parent report contract, preserving
  the delegated task without duplicate role injection.
- `tests/test_native_routing.py`: neutral synthetic-catalog regression checks for those
  routing and report contracts.

Validation used a standalone source tree. After initial private publication, resolve
these navigation references against the current checkout's `HEAD`; an initial commit
cannot contain its own future SHA. Distributed ZIPs omit Git history and therefore have
no commit pin. Publication completion is established by the external Git receipt, not
by this index.
