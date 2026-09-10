# Research Knowledge Base — SCHEMA

> Conventions for THIS project's research KB. Instance of the research-KB convention
> (spec: `dev-setup-codex/specs/deep-interview-knowledge-base.md`).
> **This file is project-owned** — customize the taxonomy and any project-specific
> rules here; the skill never overwrites it after init.

## Purpose

Anti-amnesia. Preserve this project's hard-won **research intellect** — literature
understood, experiments run, decisions made — at **full fidelity**, so a forgetful
future (you, or a cold-context agent) can reconstruct the mental picture and avoid
re-deriving settled work. Reconstruct-from-zero is the quality bar, not reminder-level.

This base is simultaneously a git-tracked directory and an Obsidian vault: open the
folder in Obsidian and `[[wikilinks]]`, graph view, and Dataview work directly.

## Layers & folders

```
knowledge/
├── SCHEMA.md      # this file — conventions (meta, no frontmatter)
├── index.md       # sectioned catalog + one-line summaries (meta)
├── log.md         # append-only action log (meta; rotate → log-YYYY.md at 500)
├── raw/           # L1 — immutable sources (read-only; corrections go in L2 pages)
│   ├── papers/    #   paper PDFs / markdown        (frontmatter: source_url, ingested, sha256)
│   ├── data/      #   run outputs, metric dumps, configs (immutable versioned filenames)
│   ├── transcripts/ # captured chat / discussion
│   └── assets/    #   figures, diagrams (Obsidian attachments)
├── journal/       # L2a — TIME axis: one resolved QUESTION → one entry, full 2+3
├── synthesis/     # L2b — TOPIC axis: accreting concept pages, full 2+3
├── comparisons/   # L2  — decisions / ADRs (Context · Decision · Consequences · Alternatives)
├── queries/       # L2  — filed valuable explorations (write-back loop)
└── _archive/      # superseded content
```

- `journal/` = what we did, when (a resolved question, start→conclusion).
- `synthesis/` = what we now know about a topic (accretes across journal entries).
- `comparisons/` = a consequential decision recorded standalone (ADR shape).
- `queries/` = a question you answered, filed so it isn't re-derived (the write-back loop).

## The unit rule (journal)

**One journal entry = one hypothesis/question explored across N runs to a conclusion.**
Not one entry per run. The N runs live in `raw/data/`; dead-ends are one-liners inside
Layer A ("vX–vY tried, rejected: Z"), not separate entries.

## 2+3 entry template (journal & synthesis)

- **Layer A — substrate (structured-lossless):** Hypothesis · Method · Config ·
  Result (every fact & number) · Interpretation · Decision. Nothing material dropped.
  **Key numbers are absorbed into Layer A at write time** so the entry survives even
  if the raw data file is later deleted. **Recompute every number from pinned raw
  before recording it — never draft from recall.**
- **Layer B — overlay (curated narrative):** reasoning, alternatives weighed, concrete
  texture, why-it-matters — prose on top of A. Organization lives here and is additive;
  it never replaces the substrate.

Every page: **≥2 outbound `[[wikilinks]]`**; paragraph provenance `^[raw/...]` on claims
that trace to a specific source.

## Writing quality (readability)

Full fidelity is the *content* bar; these keep the pages *readable*. They govern both
the EN base and the KR mirror. (Earned from a returning-reader audit — a KB can be
lossless and still painful to re-read.)

- **Research only — keep note-taking meta out.** A research page holds the research
  (experiments, findings, decisions). Meta about the KB *convention itself* —
  acceptance-criteria evals, dogfood records, anti-amnesia process narratives,
  pin/confidence commentary — does **not** belong in a research page; it goes to the
  harness repo (living contracts in `dev-setup-codex/specs/`, dogfood/evidence
  records in its `knowledge/`). A one-line provenance caveat on a number is
  fine; a paragraph about the note-taking system is not.
- **Label every number's framing.** State whether a metric is an absolute value
  (`rest`/`out`) or a delta vs a baseline (`Δ`/gain). When a comparison drives the
  conclusion, put the baseline (e.g. a do-nothing / passthrough row) **in the table**
  so the verdict reads off the table, not only from prose.
- **Gloss a domain term once, then use one name.** Introduce jargon with a one-time
  gloss on first use, then keep a single consistent term — don't call the same thing
  three names across pages.
- **Don't over-compress the key mechanism.** The single most important causal step
  (why X causes Y) gets spelled out, not crushed to one line. Full fidelity means the
  *reasoning* is reconstructable, not just the facts listed.
- **Mark what you can't verify.** If a number/claim can't be recomputed from pinned raw,
  say so (unpinned / lower confidence) — don't state it flat.

## Frontmatter

```yaml
---
title: ...
created: YYYY-MM-DD          # when the work happened (journal) / page born (synthesis)
updated: YYYY-MM-DD
type: journal | synthesis | comparison | query
tags: [taxonomy-only]
sources: [raw/data/run-x.csv]   # pins to raw
confidence: high | medium | low      # optional
contested: true                      # optional
---
```

Raw markdown/paper files carry `source_url`, `ingested`, `sha256`. **Non-markdown raw
(CSV, binary) cannot carry frontmatter** → its provenance (origin path, ingested date,
sha256) is recorded in `raw/data/_sources.md` (a meta ledger).

## Pinning (papers vs run-data)

- **Papers** → `raw/papers/`, sha256-pinned; drift is checked by the agent's semantic
  pass during `/research-kb` lint (`kb-lint.py` does not recompute hashes).
- **Run-data** → immutable versioned filenames (`run-v11_2026-06-01.csv`, never
  overwritten). sha256 also recorded in `_sources.md` for tamper/drift check, but the
  immutable filename is the primary guarantee. Decisive numbers are also absorbed into
  the journal Layer A.

## Tag taxonomy (flat, ~10–20 — CUSTOMIZE FOR THIS PROJECT)

> Replace with this project's domain tags. New tags go here FIRST, then get used.
> Freeform tags decay into noise. (`kb-lint.py` reads the backtick-wrapped tokens in
> this section as the allowed set.)

`decision` · `evaluation` · `metrics` · `diagnosis`
<!-- add domain tags, e.g. for ML-audio: `training` · `loss-design` · `phase` · `waveform` … -->

## Boundary with `wiki/` and `workflow/`

`knowledge/` (this) = research **intellect**, full-fidelity, human-facing. It does NOT
overlap with `wiki/` (how the **code** works — terse, AI-facing) or `workflow/` (what
we're doing now). A page that is "how the code does X" belongs in `wiki/`, not here.
Cross-graph references to `wiki/` use a **plain path** (`wiki/concepts/foo`), NOT a
`[[wikilink]]` — wiki and knowledge are separate graphs.

## Naming

- journal: `YYYY-MM-DD-<slug>.md` (date the work happened).
- synthesis: `<topic-slug>.md`.
- raw data: `<descriptor>_<version-or-date>.<ext>` (immutable).

## Lint

`kb-lint.py` (mechanical): broken `[[links]]`, orphans, index completeness, frontmatter
presence, tag audit. Run it before milestones. Semantic checks (Layer A/B quality,
confidence calibration, sha256 source-drift, generative gaps) stay with the agent.

## Splitting

- A journal entry is naturally bounded (one question) — rarely splits.
- A synthesis page accretes → split into subtopic pages under a parent hub (table of
  contents) when it nears ~500 lines.

## Recovery default

Read the EN base directly in Obsidian (graph + Dataview). A KR mirror is generated
on-demand for deep reading only — not constantly synced.
