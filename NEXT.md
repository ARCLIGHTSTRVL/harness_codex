---
last_verified_commit: UNCOMMITTED
last_touched: 2026-09-10
writer: codex
unit_paths: codex/AGENTS.md scripts/native_agents scripts/native-agent-contract.py tests/test_native_routing.py templates skills
---

# NEXT

## Active Unit

Goal: Closed — 0.1.2 policy, routing/report and package/state boundary update verified.
Current state:
- Corrected source passed all 33 tests and lint on Windows and macOS, without skips.
- Independent initial and bounded follow-up reviews passed correctness and purpose fit.
- Model choices remain user-owned; optional community global choices are never installed.
- Rebuilt and transferred validation ZIPs matched byte-for-byte; final checksums are beside dist artifacts.
- Validation ran from a standalone tree without Git history. Initial private source
  publication and the user's personal backport are now authorized, but this handoff
  does not claim that commit, push or installation has completed.
- Knowledge decisions and evidence limits are filed in knowledge/index.md.
Blocker:
- None for local packaging. Public visibility and license selection remain separate.
Pointers:
- docs/PACKAGING.md
- START-HERE.md
- docs/KNOWLEDGE-WORKFLOW.md
- knowledge/index.md
- docs/NATIVE_AGENT_CONTRACT.md
Acceptance:
- Isolated installation, repeat installation, drift detection and user-data preservation pass.
- ZIP is reproducible and contains no private machine configuration.

## Next Action

No active implementation remains. Use dist/dev-setup-codex-community-0.1.2.zip and
its SHA-256 sidecar with START-HERE.md. The readiness journal separates initial and
corrected validation. Under the existing authorization, initialize the private source
repository on `main`, push it, and perform the personal backport without treating those
external receipts as already complete. In a Git checkout verify source references at
that checkout's `HEAD`; the ZIP contains no Git history or commit pin.

## Pending, Not This Unit

- Public repository visibility and license selection are not authorized. Initial
  private hosting and push are authorized independently of local packaging.
