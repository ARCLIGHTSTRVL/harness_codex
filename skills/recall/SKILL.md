---
name: recall
description: Search past Codex session transcripts for what was said, run, or printed, scoped to this project's cwd by default, with progressive disclosure and secret redaction. Trigger words include "recall", "what did we run", "find in past session", "earlier session", "리콜", "지난 세션", "이전 세션에서", "그때 뭐 나왔지".
---

# recall

Find commands, outputs, user words, or decisions that were never captured in
`knowledge/` or memory. This standalone Codex port scans rollout JSONL in place;
it creates no index, transcript copy, hook, or automatic injection.

## Usage

```text
python <skills>/recall/scripts/recall.py <pattern> [<pattern> ...] [--all]
    [--in text,tool_use,tool_result,summary,thinking|all] [--include-recent]
    [--case] [--limit N]
python <skills>/recall/scripts/recall.py --show <session-file>:<line> [--max-chars N]
```

`<skills>` is `~/.codex/skills` when installed, or `<dev-setup-codex>/skills`.
Patterns are case-insensitive Python regexes; multiple patterns must ALL match
within one block. Use `--case` for case sensitivity and `--` before a pattern
starting with a dash.

## Procedure

1. Search from the project's directory. The default root is
   `$CODEX_HOME/sessions`, falling back to `~/.codex/sessions`. Scope uses
   `session_meta.payload.cwd`, not an encoded Claude project directory.
   `--all` scans all projects; `--cwd PATH` selects a project explicitly.
   `--sessions-dir PATH` selects an alternate Codex sessions tree, including
   an archive or synthetic fixture. It does not select a Claude parser.
2. Read the grouped hit list first: locator, timestamp, role/kind, and a short
   redacted snippet. Sessions and hits are ordered newest first. Spawned
   threads with `source.subagent.thread_spawn.parent_thread_id` are grouped
   with their available parent and retain their own reopenable locator.
3. Rows from the last 120 seconds are excluded to avoid matching the query's
   own transcript. `--include-recent` includes them. `--limit` bounds the
   number of displayed hits per session and names any omitted hits.
4. Open only relevant rows with `--show <session-file>:<line>`. Bodies are
   bounded by `--max-chars` (default 20000); truncation is reported.
5. Relay the evidence with the locator so another reader can reopen it.

## Codex record mapping

`response_item` message content supplies user/assistant text, function/custom
tool calls supply `tool_use`, and their outputs supply `tool_result`.
`event_msg` user/agent messages remain searchable when the same role/text has
no response-item copy in that file; this suppresses Codex's duplicate echoes.
`compacted.payload.message` supplies summaries. Reasoning summaries/content
and assistant messages with `channel=analysis` require `--in thinking` or
`--in all`. Encrypted reasoning cannot be searched. Unsupported record types,
including arbitrary tool telemetry, are not treated as conversation text.

## Redaction and boundaries

The adjacent `skills/ask/scripts/ask-preflight.py` provides the credential
patterns. Missing scanner means exit 2 with no transcript text; there is no
scanner override flag. Bodies, metadata, and locators are redacted before
printing. PEM private keys are hidden through their END marker, and
credential-file diffs are hidden as whole blocks. Redaction precedes snippet
and show truncation so a cut cannot expose a partial token.

`--show` resolves paths and refuses locators outside the selected sessions
root. Search ignores symlink targets outside that root. Malformed JSON rows
and incomplete last lines are counted and skipped; a complete final row
without a newline is still read. Missing project transcripts are a named
empty result. Missing transcript roots and invalid options return exit 2.

## Limits

This port has no Claude transcript fallback. Cwd filtering needs session
metadata; `--all` can inspect records with missing cwd. The scan reads each
rollout to inspect metadata, so a large all-project history can take seconds.
Ordering is recency, not relevance, and matching is regex, not fuzzy.
Redaction is pattern-based and only hides shapes recognized by ask-preflight;
do not treat it as a guarantee that arbitrary sensitive prose is removed.
