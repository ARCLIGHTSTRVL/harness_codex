# Initializing a New Wiki

This document covers everything needed to bootstrap a new codebase wiki: the init checklist plus the four file templates (`SCHEMA.md`, `index.md`, `log.md`, `wiki/AGENTS.md`). After init, agents work from the project's own `SCHEMA.md` and don't need to revisit this document.

## Init Checklist

When the user asks to create or start a wiki:

1. **Determine location** — `./wiki/` at the git root (or current directory if not in a repo).
2. **Create the directory structure**:

   ```
   wiki/
   ├── AGENTS.md                # Static routing guide for any agent that lands here
   ├── SCHEMA.md                # Conventions, structure rules, page templates
   ├── index.md                 # Sectioned content catalog with one-line summaries
   ├── log.md                   # Chronological action log (append-only, rotated yearly)
   ├── entities/                # Modules, services, components, classes, deps
   ├── concepts/                # Flows, mechanisms, cross-cutting patterns
   ├── comparisons/             # Side-by-side analyses + ADRs
   ├── queries/                 # Filed query results worth keeping
   ├── assets/                  # Diagrams and screenshots referenced from pages
   └── sources/                 # Optional: attached non-code material (RFCs, etc.)
   ```

3. **Ask the user about the project** — name, primary language(s), key domains. Be specific; this anchors every page that follows.
4. **Write `SCHEMA.md`** customized to the project (template below).
5. **Write initial `index.md`** with sectioned header and zero entries.
6. **Write initial `log.md`** with a creation entry.
7. **Write `wiki/AGENTS.md`** from the template below.
   This file is generated **once** at init and is intentionally static thereafter.
8. **Optionally scan for existing documentation** — `README.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md`, `docs/` — and offer to ingest them as seed material. **Ask the user before doing so.**
9. **Optionally offer to add a one-line pointer to the project root's `AGENTS.md`** (if one exists) noting that a wiki is available at `./wiki/`. This helps an agent invoked from the project root discover the wiki.
   **Ask the user before modifying any file outside `wiki/`.**
10. Confirm the wiki is ready and suggest the first module or concept to document.

## SCHEMA.md Template

````markdown
# Wiki Schema

## Project
[Project name and one-paragraph description — what the codebase does, primary language(s), key domains. This anchors every page that follows.]

## Conventions
- File names: lowercase, hyphens, no spaces (e.g., `auth-service.md`)
- Knowledge pages in `entities/`, `concepts/`, `comparisons/`, and `queries/` start with YAML frontmatter (see below)
- Meta pages do not need frontmatter
- Use `[[wikilinks]]` to link between pages (minimum 2 outbound links per page)
- When updating a page, always bump the `updated` date
- Every new page must be added to `index.md` under the correct section
- Every action must be appended to `log.md`

## Decoupling Principle (CRITICAL — read before writing any page)

The single biggest factor in long-term wiki value is **page durability**: pages that survive refactors. To achieve durability:

- Describe **invariants, contracts, and intent** — not specific implementations
- Avoid line numbers and code shape in narrative prose. Pin code locations in a dedicated `Key files` section, not inline
- Prefer the durable framing over the brittle one

**Bad (will rot on the next refactor):**

> On line 42 of `src/auth/oauth.ts`, the `exchangeCode` function calls `redis.set` with TTL 3600 to cache the access token, then awaits the response and returns the bearer token to the client.

**Good (survives refactors):**

> The OAuth callback exchanges the authorization code for a token, then caches it per the [[caching-strategy]]. Tokens are stored with a 1-hour TTL by contract — see `Key files` for the current implementation.

When in doubt, describe **what the system promises**, not **how the current code accomplishes it**.

## Frontmatter

```yaml
---
title: Page Title
created: YYYY-MM-DD
updated: YYYY-MM-DD
type: entity | concept | comparison | query
tags: [from taxonomy below]
sources:
  - src/auth/oauth.ts:exchangeCode@<commit>
  - src/auth/oauth.ts:42-110@<commit>
verified_at: <commit>                  # last commit at which page was reconciled with source
# Optional quality signals:
confidence: high | medium | low        # how well-supported the claims are
contested: true                        # set when the page has unresolved contradictions
contradictions: [other-page-slug]      # pages this one conflicts with
---
```

### `sources:` pin format

Each source pin is one of, in order of preference:

1. `path/to/file.ts:symbolName@<commit>` — **REQUIRED whenever a named symbol encloses the pinned region** (function, class, exported const, type, method). Symbol pins survive line shifts and support `git log -L :symbolName:path` history tracking.
2. `path/to/file.ts:42-110@<commit>` — range-level fallback for regions with no enclosing symbol (config blocks, top-level statements, multi-symbol regions). Use the smallest meaningful range.
3. `path/to/file.ts` — file-level (last resort; flags too aggressively on lint). Avoid except when the page genuinely concerns the whole file.

The commit suffix is the SHA at which this pin was last verified.
Lint re-resolves each pin to its current location before checking for content changes (see Stale Detection, Layer 1) — pins are self-healing for pure line shifts.

**Choosing between symbol and range:** if the documented behavior lives inside a named function/class, pin the symbol — even if your prose only references a few lines of it. The symbol's identity is what should be tracked. Use a range pin only when no symbol encloses the region.

### `verified_at:`

The commit at which the page was last reviewed against current source.
Used by the trust-decay layer of stale detection.

`confidence` and `contested` are optional but recommended for fast-moving or opinion-heavy areas.
Lint surfaces `contested: true` and `confidence: low` pages so weak claims don't silently harden into accepted wiki fact.

## Tag Taxonomy
[Define 10-20 top-level tags for this project. Add new tags here BEFORE using them.]

Example:
- Layers: frontend, backend, infra, build, test
- Cross-cutting: auth, persistence, observability, performance, security
- Surface: api, cli, ui, sdk
- Meta: comparison, adr, timeline, deprecation

Rule: every tag on a page must appear in this taxonomy. If a new tag is needed, add it here first, then use it. This prevents tag sprawl.

## Page Thresholds
- **Create a page** when an entity/concept appears in 2+ places in the codebase OR is central to one significant component
- **Add to existing page** when new information extends something already covered
- **DON'T create a page** for passing mentions, single-use helpers, or things peripheral to the project's core
- **Split a page** when it exceeds ~200 lines — break into sub-topics with cross-links
- **Archive a page** when content is fully superseded — move to `_archive/`, remove from index

## Page Templates

The templates below describe section patterns that work well for each page type — treat them as starting points, not rules. Keep the sections that genuinely help readers, rename them to match the project's vocabulary, drop sections that don't apply, and add new ones when a page calls for them. Consistency across pages of the same type aids navigation, but a forced section is worse than no section.

### Entity pages
Modules, services, components, classes, data models, external dependencies. Typical sections:

- **Purpose** — one sentence
- **Public interface** — what this entity exposes (functions, endpoints, events, exported types). Names primarily; full signatures only when stable
- **Key files** — paths in the codebase. Symbol-level pins where appropriate (e.g. `src/auth/oauth.ts:exchangeCode`)
- **Dependencies** — which other entities ([[wikilinks]]) and external libraries this relies on
- **Invariants and constraints** — assumptions that must not be broken
- **Common usage patterns** — how callers typically use it
- **Gotchas** — counterintuitive behavior, pitfalls

### Concept pages
Flows, mechanisms, cross-cutting patterns. Typical sections:

- **What it is** — one paragraph
- **Trigger / entry point** — where the flow begins
- **Step-by-step flow** — linking [[entity]] pages along the way.
  **Mermaid diagrams encouraged** where structure aids comprehension (mermaid is markdown-native and renders in many viewers including Obsidian and GitHub)
- **Failure modes and edge cases**
- **When to read source instead** — explicit pointers to cases the wiki cannot summarize faithfully

### Comparison pages
Side-by-side analyses. Typical sections:

- **What is being compared and why**
- **Dimensions of comparison** (table format preferred)
- **Verdict or synthesis**
- **Sources**

### Comparison — ADR variant
For design decisions. Typical sections:

- **Context** — what situation drove the decision
- **Decision** — what was chosen
- **Consequences** — what this choice implies (good and bad)
- **Alternatives considered** — what was rejected and why
- **Status** — proposed | accepted | deprecated | superseded-by [[other-adr]]

## Update Policy
When new information conflicts with existing content:
1. Check the dates and the `verified_at` commits — newer data generally supersedes older
2. If genuinely contradictory, note both positions with dates and sources
3. Mark the contradiction in frontmatter: `contradictions: [page-name]`, `contested: true`
4. Flag for user review in the lint report

## Stale Detection (five layers)

A codebase wiki goes stale when source code changes faster than pages are reconciled.
Five layers protect against this; lint and `refresh` operations exercise them.

**Layer 1 — Symbol/range pins with re-anchoring (REQUIRED).** Frontmatter `sources:` accepts symbol- or range-level pins with commit suffixes; symbol pins are required wherever a symbol encloses the region.

Lint **re-resolves each pin to its current location before diffing**:
- **File rename detection**: if the pinned file is missing in the working tree but did exist at `<sha>`, walk `git log --diff-filter=R --name-status <sha>..HEAD` to chain renames forward and find the file's current path. If the chain resolves to an existing path, switch to that path for the rest of re-anchoring; the rename is reported as `info` and rewritten on `--update-pins`. (Edge case: a rename combined with a wholesale rewrite of the same file in one commit may fall below git's rename-detection threshold and surface as file-missing; the page needs a manual pin update there.)
- **Symbol pin** (`path:symbolName@<sha>`): locate `symbolName` in the current source. If it has moved to a different line range, silently update the pin's resolved range — no stale flag.
- **Range pin** (`path:42-110@<sha>`): try to re-locate the pinned content (as it existed at `<sha>`) in the current file. If found at a shifted location, update the resolved range silently.
- If none of the above relocate, the page is genuinely stale (file deleted, symbol removed/renamed, or range content rewritten).

After re-anchoring, lint checks whether the *resolved* range was touched between `<sha>` and `HEAD`. Re-anchoring eliminates false positives caused by pure line shifts upstream of the pin and by `git mv` operations. When a rename was detected, both old and new paths are passed to `git diff` so rename-aware hunks line up correctly with the resolved range.

**Layer 2 — Change classification (RECOMMENDED).** When lint detects a touched pin, read the diff and classify severity:
- High: public signature change, exported member added/removed, control-flow change
- Medium: internal logic change
- Low: comments, formatting, renames with no behavioral effect

Group results by severity. Low-severity changes are mentioned but not flagged as action items.

**Layer 3 — Trust decay (RECOMMENDED).** When a configurable threshold of commits (default 50) has landed touching any pinned source since `verified_at`, lint reports a demotion suggestion for `confidence: high` → `medium` (apply manually or via the agent pass; the script does not write back).
Pages past the threshold should carry a verification caveat when their content is used to answer a query.

**Layer 4 — Decoupling guidance (REQUIRED).** Already covered above.
Pages that don't depend on code shape don't go stale from refactors.
This is the most important stale-resistance lever because it operates *before* drift can accumulate.

**Layer 5 — `refresh` operation (REQUIRED).** A first-class operation alongside ingest/query/lint that turns stale findings into actual updates. Detail in the skill body.
````

## index.md Template

```markdown
# Wiki Index

> Content catalog. Every wiki page listed under its type with a one-line summary.
> Read this first to find relevant pages for any query.
> Last updated: YYYY-MM-DD | Total pages: N

## Entities
<!-- Alphabetical within section -->

## Concepts

## Comparisons

## Queries
```

**Scaling:** When any section exceeds 50 entries, split into sub-sections by sub-domain or first letter.
When the index exceeds 200 entries total, create a `_meta/topic-map.md` that groups pages by theme.

## log.md Template

```markdown
# Wiki Log

> Chronological record of all wiki actions. Append-only.
> Format: `## [YYYY-MM-DD] action | subject`
> Actions: ingest, update, query, lint, refresh, create, archive, delete
> When this file exceeds 500 entries, rotate: rename to log-YYYY.md, start fresh.

## [YYYY-MM-DD] create | Wiki initialized
- Project: [name]
- Structure created with SCHEMA.md, index.md, log.md, AGENTS.md
```

## wiki/AGENTS.md Template

`wiki/AGENTS.md` is **generated once at init** and serves as a static routing guide for any agent that lands in this wiki. It deliberately does not need YAML frontmatter.
Do not modify it during normal wiki operation. Modifications happen only on explicit user request.
Hard cap: 50 lines.

```markdown
# Wiki Routing Guide

This is the [PROJECT NAME] codebase wiki.
It documents architecture, components, mechanisms, and design decisions so questions can be answered without re-exploring the source code.

## At session start, orient first

1. Read `SCHEMA.md` — conventions, page templates, tag taxonomy
2. Read `index.md` — what pages exist and their summaries
3. Read the last 30 lines of `log.md` — recent activity

## To answer a codebase question

1. Use `index.md` — it lists all pages with one-line summaries; pick the relevant ones
2. Read the relevant concept page(s) — these describe how things work
3. Read the relevant entity page(s) — these describe specific modules/components
4. Read source code only as a fallback or when a page explicitly points there

Most questions can be answered from 2-4 wiki pages. If you find yourself reading source heavily, the wiki may have a documentation gap worth filing.

## Modifications

Modifications to this wiki should go through the `codebase-wiki` skill.
If the skill is not available in your environment, follow `SCHEMA.md` directly — especially the page templates, the decoupling principle, and the requirement to update `index.md` and `log.md` for every change.

## What not to do

- **Do not modify this AGENTS.md.** It is intentionally static. Running edits go to `index.md`, `log.md`, or individual pages instead.
- **Do not modify code while in wiki-maintenance mode** unless the user explicitly asks.
- **Do not create pages for passing mentions.** Follow the page thresholds in `SCHEMA.md`.
```
