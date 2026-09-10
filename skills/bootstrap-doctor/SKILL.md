---
name: bootstrap-doctor
description: Read-only audit for optional Codex project bootstrap templates and hook-copy drift across local projects. Use for "bootstrap doctor", "hook drift", "부트스트랩 점검", or "훅 드리프트".
---

# bootstrap-doctor

Audit optional project-local bootstrap files across dev roots. This is
read-only.

Direct Codex does not currently depend on these hooks for normal operation, so
treat findings as project-template maintenance, not installed-harness drift.

## Procedure

1. Read `source_repo` from `CODEX_HOME/dev-setup-codex-community-state.json`
   (default CODEX_HOME: `~/.codex`). Use that directory as `<repo>`.

2. Run:

```bash
python <repo>/scripts/bootstrap-doctor.py
```

3. Report:
   - dev roots scanned
   - projects with `AGENTS.md`, `NEXT.md`, `.codex/hooks`, or `.codex/hooks.json`
   - hook template version/config drift if hooks are present
   - missing plan reader, event matcher coverage, and Windows exit propagation

The shared `scripts/hook_contract.py` recognizes the seeded Codex launchers.
Custom shell commands are reported UNVERIFIED; inspect them directly. File
versions and static configuration checks do not establish `/hooks` trust or
live event delivery. No Claude transcript liveness inference is used.

## vs setup-check

`setup-check` audits this machine's installed `~/.codex` harness. `bootstrap-doctor`
audits optional project-local bootstrap copies.
