---
name: research-kb
description: Scaffold, lint, and capture entries for a project's research knowledge base (`project/knowledge/`) — full-fidelity human-facing research intellect (experiments, findings, decisions), NOT code mechanics. EXPERIMENTAL / thin. Gates on `knowledge/SCHEMA.md`. Use to init a knowledge/ base, run kb-lint, or draft a journal/query/comparison entry from a *resolved* question. For real-time per-decision capture into `knowledge/_fragments/` (before a finding resolves) use knowledge-fragment; for "how the code works" use codebase-wiki. Trigger words include "research kb", "knowledge base", "research-kb", "연구 지식베이스", "지식베이스 정리".
---

# research-kb (experimental)

Helper for the **research knowledge base** convention — a full-fidelity, human-facing,
Obsidian-native store of a project's research *intellect*: experiments run, findings,
decisions. Lives in `<project>/knowledge/`, git-tracked alongside the code.

Full convention spec: `<harness-repo>/specs/deep-interview-knowledge-base.md`.
Read `source_repo` from `CODEX_HOME/dev-setup-codex-community-state.json` (default CODEX_HOME is `~/.codex`). Use that source directory as `<repo>`. Without state, locate the extracted community directory supplied by the user; never guess a personal repository. Read the spec before non-trivial work. Installed script
examples use `~/.codex`; substitute `CODEX_HOME` when that variable is set.

**Status: experimental.** Validated by one project's dogfood (n=1). The convention may
still be domain-shaped; the per-project `knowledge/SCHEMA.md` is the authority, and this
skill only scaffolds / lints / captures — it does **not** ship a full query/refresh
engine. That restraint is on purpose (see *Why this is thin* below).

## Boundary — when this vs codebase-wiki

| | `research-kb` (`knowledge/`) | `codebase-wiki` (`wiki/`) |
|---|---|---|
| content | research intellect (experiments, findings, decisions) | how the code works (architecture, mechanisms) |
| audience | **human**, full-fidelity | AI, terse |
| pinning | raw papers (sha256) / run-data (immutable filename) | code symbols (git SHA) |

They are **separate graphs**. A `knowledge/` page refers to a `wiki/` page by plain path
(`wiki/concepts/foo`), never `[[wikilink]]`. Don't merge them; don't cross-link their graphs.

## Operations

This skill covers three operations. Resume/query and refresh are intentionally NOT
mechanized here — do those by hand following the spec (orient: SCHEMA → index → recent
log → read the relevant journal/synthesis pages).

### 1. init

Create the `knowledge/` skeleton for a project that doesn't have one.

1. Confirm there's no existing `knowledge/SCHEMA.md` (don't clobber).
2. Create the structure:
   ```
   knowledge/{SCHEMA.md, index.md, log.md,
             raw/{papers,data,transcripts,assets}/,
             journal/, synthesis/, comparisons/, queries/, _archive/}
   ```
3. Copy `templates/SCHEMA.md` (sibling to this file) to `knowledge/SCHEMA.md` and
   **customize the tag taxonomy section for this project's domain** (the template ships a
   generic placeholder; a project's tags ≠ another's). Leave the rest as-is.
4. Seed `index.md` (sectioned header, zero entries) and `log.md` (a `create` entry).
5. Tell the user it's ready and suggest the first work-unit to record.

Do NOT auto-ingest existing notes. Migration of old memory/notes into `journal/` is a
deliberate, per-item decision (spec Open Item #2), not an init step.

### 2. lint

Run the mechanical linter:
```bash
python ~/.codex/skills/research-kb/scripts/kb-lint.py [<knowledge-path>]
```
Checks: broken `[[wikilinks]]`, orphans, index completeness, frontmatter presence, tag
audit (against the `knowledge/SCHEMA.md` taxonomy), and citations — a `consolidates:` id
that no fragment carries as consolidated is an issue; a backticked commit hash the
enclosing repository cannot resolve, or an `.ask-artifacts/` path absent on this machine,
is listed as ADVISORY and never counted, and whatever could not be checked at all (no git,
no `_fragments/`, no artifacts directory) is named. Exit 0 clean / 1 issues / 2 error —
suitable as a CI gate. Code spans/fences are stripped before link extraction, so a
`` `[[wikilink]]` `` mentioned in prose is not a false positive.

After the script, the agent still does the **semantic** pass the script can't: Layer A/B
quality, confidence calibration, sha256 source-drift on papers, and generative gaps
("findings on X and Y but no synthesis linking them"). Append a lint line to `log.md`.

### 3. capture

Draft a KB entry from a resolved research/design question (the **write-back loop** — the
convention's compounding value). Fires when the user says "log it" / "file this", or when
you propose it at a natural pause and they agree. Never auto-file silently; never file
trivial lookups.

1. Pick the type: `journal/` (a resolved work-unit, full 2+3), `synthesis/` (an accreting
   topic page — update the existing one or start a new "all we now know about X"), `queries/`
   (a question you answered — even with no new fact), or `comparisons/` (a consequential
   decision, ADR shape). A finding usually lands in `journal/` AND updates a `synthesis/` page.
2. Draft with frontmatter (`title/created/updated/type/tags/sources` + optional
   `confidence`). **Recompute every empirical number from the pinned raw source before
   writing it** — never from recall. If a number can't be verified against raw, mark it
   `unpinned` / lower the page `confidence`, don't state it flat. (This is the policy rule;
   it is the single most load-bearing discipline — recall-drafted numbers drift.)
3. Add ≥2 outbound `[[wikilinks]]`, paragraph provenance `^[raw/...]` on sourced claims.
4. Update `index.md` (add the page) and `log.md` (append the action).
5. Run `lint` before considering it done.

### KR mirror (on-demand, natural Korean)

The `knowledge/` KR mirror is generated by hand for deep reading, only when asked — never
by a bulk translation pass. A faithful sentence-by-sentence translation of dense
English reads as translationese in Korean (noun-piles, subject-dropped 명사형 종결,
copied em-dash insertions). Instead:

- **Adapt to natural Korean** — restructure for Korean word order; break English em-dash
  insertions into separate sentences; finish every sentence (no 명사형 파편 종결); avoid
  noun-piles; gloss a domain term once then keep one term.
- **Register: 평어체** — end sentences in plain declarative `-다/-이다`; never 합니다/해요체.
  Uniform across all mirror pages. A project's `knowledge/SCHEMA.md` may override; absent
  an override this is the default.
- **Apply the SCHEMA "Writing quality" rubric** — it governs EN and KR both; the KR
  *additionally* must avoid translationese.
- Keep numbers / tables / links / frontmatter identical to the EN authoritative; mirror
  prose only. Then verify: a cold read reconstructs the finding, and EN↔KR carry the
  same facts (no drift, no KR-invented claims).

## Why this is thin (do not grow it into codebase-wiki)

The discipline that makes the KB valuable — *recompute numbers from raw, file questions
back* — lives in the always-on global Codex policy, not here, because it must fire whenever
a durable number is written, not only when this skill is invoked. This skill is just the
scaffolding/lint/capture mechanics. Resist re-deriving codebase-wiki's init/ingest/query/
refresh flow here — if it grows to mirror that skill, the two will drift (a duplicate
source of truth, which this harness specifically avoids). If a richer linter is ever
wanted, share a markdown-graph core with `wiki-lint.py` rather than forking a second full
parser.

## Pitfalls

- **Don't clobber a project's `knowledge/SCHEMA.md`** — it's project-owned after init.
- **Don't cross-link the wiki and knowledge graphs** with `[[ ]]` — plain paths only.
- **Don't draft numbers from recall** — recompute from pinned raw (policy rule).
- **Don't auto-file** write-back entries silently — propose, get a nod, then capture.
- **Don't add a query/refresh engine** here without a reason — thinness is the design.
