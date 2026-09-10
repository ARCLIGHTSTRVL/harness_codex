# `scripts/wiki-lint.py` Reference

Detailed reference for the automated lint script. The skill body (`SKILL.md`) covers when to run it and what to do with its output; this file documents *what* it implements, the CLI surface, and the semantics of pin auto-updates.

## Implemented checks (1–8, 10–13)

The script covers the mechanical checks from the lint operation in `SKILL.md`:

- Broken wikilinks, orphans, index completeness
- Frontmatter validation (required fields, type/confidence enums)
- Tag audit
- Layer 1 stale detection with file-rename tracking (chained `git log --diff-filter=R`), symbol-pin re-resolution, and range-pin content-anchored re-anchoring
- Layer 3 trust decay (commit-count threshold)
- Documentation-gap detection (recent-activity window vs. pinned coverage)
- Page size and log rotation
- Quality signals (`contested: true`, `confidence: low`)
- Unpinned-sha pins (LOW `unpinned-sha`): `sources:` entries missing the `@<sha>` suffix — stale detection cannot run on them
- Invalid commit refs (HIGH `invalid-pin-ref` / `invalid-verified-ref`): a pin or `verified_at` SHA that does not resolve — never treated as zero changes
- Git-history failures (HIGH `git-history-failed`): a commit-count operation failed after ref validation — never treated as zero
- Malformed pins (LOW `malformed-pin`): entries that parse as a path containing `:` instead of a valid file/symbol/range pin

**Layer 2 severity** is implemented as a heuristic — signature-token presence (`function`/`class`/`export`/return-type annotations), change volume, and comment-only detection drive a high/medium/low label. Deeper semantic classification, **lint check 9 (AGENTS.md / SCHEMA.md drift)**, and the entire **refresh** operation still require an agent pass.

## Usage

```bash
python3 <skill>/scripts/wiki-lint.py [<wiki-path>]
  --json                # machine-readable; suitable for CI consumption
  --update-pins         # auto-apply silent shifts: rewrites range pin AND bumps SHA to HEAD
  --no-git              # skip git-dependent checks (Layers 1, 3, doc-gap)
  --severity {critical,high,medium,low,info}   # filter by minimum severity
  --check broken-wikilinks,orphans,...         # comma-separated subset of checks
  --since 30            # doc-gap window in days (default 30)
```

`<wiki-path>` defaults to `./wiki/` discovered from cwd. Requires Python 3.9+, `PyYAML`, and `git` on `PATH`. (Windows: invoke with `python` instead of `python3`.)

## Exit codes

- `0` — clean (no critical/high)
- `1` — issues found at or above high
- `2` — script error

Suitable as a CI gate.

## `--update-pins` semantics

When a range pin's content has moved but is unchanged, the script rewrites the pin to its new line range *and* bumps the commit SHA to `HEAD`. When a pinned file has been renamed (and any in-place content matches), the pin's path is rewritten to the new location (and the SHA is bumped). Bumping only the range/path while keeping the old SHA is semantically wrong (at the old SHA the new range or path points to unrelated content), so both are updated together.

Without this flag, silent shifts and renames surface as info-level findings only and the page is left untouched.

Pin updates are applied only for findings whose content was unchanged; if a renamed pin's resolved range was *also* modified, the script still emits a separate touched-{severity} issue and refresh remains a manual step.
