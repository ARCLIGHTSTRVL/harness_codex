---
name: ask
description: Route an explicitly authorized consultation or review to a local Codex CLI with pre-egress scanning, project model pins, and reusable artifacts. Use for "ask codex", "external review", or "second opinion".
---

# ask

Run a separate Codex consultation only when requested or authorized by the task.
It is same-family review, not cross-provider independence. Do not start or require
a Claude session through this skill; Claude Code uses the separate harness.
Missing review availability does not block local correctness and purpose-fit checks.

## Procedure

1. Verify the requested scope and trusted installed Codex CLI.
2. Write a complete UTF-8 prompt with the task, intent, constraints, necessary
   context, and expected output. A mode label is not a contract. For a review,
   explicitly require read-only behavior, correctness and purpose-fit verdicts,
   file/line evidence, triggering scenarios, and coverage limits. Keep credential
   files and private data out of the scope.
3. Use the executor below. It scans the exact composed prompt in memory before
   spawning, so scanned text is the text sent on stdin. Do not replace it with
   a hand-assembled CLI invocation.
4. Report the actual artifact path, the reported model/effort verdict, and findings.

Read `source_repo` from `CODEX_HOME/dev-setup-codex-community-state.json` (default CODEX_HOME is `~/.codex`). Use that source directory as `<repo>`. Without state, locate the extracted community directory supplied by the user; never guess a personal repository. The review helper is shipped beside the installed executor; it is never loaded from the project under review.

```bash
python <clone>/skills/ask/scripts/ask-codex.py <prompt-file> \
  --repo <trusted-git-repo> --project-root <project-root> \
  --out <project-root>/.ask-artifacts/codex-<slug>-<timestamp>.md
```

The executor prepends the project's optional `.codex/review-context.md` before
scanning. Missing or empty context is reported. The prompt must still contain
the review role and scope; it does not depend on an installed caller contract.

Execution uses the read-only sandbox, stdin, explicit UTF-8 subprocess encoding,
and `LAZYCODEX_CONFIG_MIGRATION_DISABLED=1` in the child's environment.
Executables inside cwd or the reviewed project/repository are refused.
Use `--codex` only to select a trusted installed CLI explicitly.

## Project model pins

Read [the config contract](references/external-review-config.md). Pins live in
`.codex/external-review.json`. They are user/project choices: do not invent a
model, write a pin without a selection, or infer runtime identity from local config.
Native subagent role pins do not automatically pin this separate CLI executor.

```bash
python <clone>/scripts/external-review.py status <project-root> codex
python <clone>/scripts/external-review.py flags <project-root> codex
```

Missing pins run without model flags and are marked UNPINNED. Invalid configuration
blocks execution. The Codex stderr header supplies reported model and effort.
Artifacts distinguish MATCH, MISMATCH, UNREPORTED, and UNPINNED. Mismatch is visible,
not an enforced rejection. Offline catalog status may be UNVALIDATED; availability
in a catalog does not prove the requested model ran.

## Egress and artifact handling

The executor scans the entire rendered artifact, including frontmatter, before
writing. A successful run with blocked content writes nothing. Failed-run stdout
and stderr are scanned separately and withheld when blocked; the marked artifact
is scanned again. No matching secret snippets are printed.

```bash
python <clone>/skills/ask/scripts/ask-preflight.py <prompt-file>
```

Only exit 0 permits sending. Remove credential-file hunks or use explicit
`<redacted>` values and rebuild after a block. Standalone scanning cannot prevent
a later caller from sending different bytes.

`--out` is required. Use a slug of at most 40 alphanumeric/dash characters and a
timestamp. The executor never overwrites; it prints the actual filename, which may
have a numeric suffix. Publication is exclusive but not atomic; an I/O failure
can leave a partial file. Add `.ask-artifacts/` to the project's existing
`.gitignore` when missing.

Exit codes: 0 artifact written; 1 blocked payload; 2 usage/environment/scanner
error; 3 provider failure with marked artifact. Missing CLI or helper is a named
refusal. Never persist unscanned raw output by hand after a failed call.
