---
last_verified_commit: f626e89450af31cad2abbcbfd796e479594d213f
last_touched: 2026-09-11
writer: codex
unit_paths: scripts/public_source.py scripts/setup-check.py scripts/community.py scripts/package.py tests/test_public_source.py skills/dev-setup skills/sync skills/setup-check README.md START-HERE.md BOOTSTRAP.md
---

# NEXT

## Active Unit

Goal: Closed — public source connection implemented, verified and published.
Current state:
- Community lifecycle skills identify the canonical public distribution, preserve
  existing fork tracking and document a new-clone update path for ZIP recipients.
- Offline setup-check states its scope; --check-updates compares exact-root Git HEAD
  with public main separately from local installation agreement.
- The package gate permits the exact public repository URL while retaining personal-data
  exclusions. Compatibility namespaces and installed-state schemas are unchanged.
- Required tests and a live temporary-profile install/check passed. Full results and
  limits are in docs/PACKAGING.md; rationale is in knowledge/comparisons/public-source-connection.md.
- Implementation commit f626e89450af31cad2abbcbfd796e479594d213f was pushed to public
  main. Local HEAD, origin/main and a live remote-ref readback matched at that checkpoint.
  A later documentation closeout may advance HEAD without changing this implementation.
Blocker:
- None for the completed source unit.
Pointers:
- docs/PACKAGING.md
- knowledge/comparisons/public-source-connection.md
- wiki/index.md
- README.md
Acceptance:
- Public source identity is shipped in the lifecycle skills and accepted by packaging.
- Local checks stay offline; explicit revision checks distinguish equal, different and
  unknown without ancestry or dirty-working-tree claims.
- Required lint/tests, temporary installation, live revision check and package build pass.

## Next Action

No active implementation remains. Before another unit, compare local HEAD and public
main and inspect current source against wiki references. Source publication does not
replace an existing personal harness installation.

## Pending, Not This Unit

- Existing community doctor native-routing STALE and wiki coverage advisories remain
  separate from this unit and the live session's FRESH launch attestation.
- No open-source license has been selected.
