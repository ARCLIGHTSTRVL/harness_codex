---
name: codebase-wiki
description: Build, query, lint, refresh, and maintain a persistent, compounding markdown knowledge base derived from a software codebase — its architecture, components, mechanisms, and design decisions. Use when the user wants to start or maintain a codebase wiki, ingest a module/PR/design doc into project documentation, answer a codebase architecture or "how does X work" question using an existing wiki, lint/audit/health-check a codebase wiki, refresh stale pages, or work on ADRs, architecture documentation, engineering knowledge bases, or code documentation that stays current. If a wiki/ directory exists at or above cwd, use this skill for codebase documentation and architecture questions; do not trigger it for unrelated implementation or file-editing tasks just because a wiki exists.
---

# Codebase Wiki

Build and maintain a persistent, compounding knowledge base of interlinked markdown files that documents a software codebase.
Inspired by [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f), adapted for code that lives in version control.

The primary motivation is **token efficiency**: most questions about a codebase ("how does auth work?", "what does this module do?", "why did we pick X over Y?") begin with a small relevant set of wiki pages instead of re-exploring source code from scratch. Two to four pages is a useful orientation heuristic, not a completeness proof; read the direct code and dependency contracts needed by the question.
Knowledge is compiled once and kept current. Cross-references are already there. Implemented decision outcomes and code consequences remain discoverable; durable rationale and rejected alternatives belong in `knowledge/`.

**Division of labor:** Engineers do the work; the agent records, summarizes, cross-references, and keeps the wiki consistent.

**Related conventions:** `codebase-wiki` (this skill) is for project-internal documentation that lives alongside code in version control.
Personal or research knowledge bases on external topics (papers, articles, transcripts) are a separate full-fidelity convention — not codebase-wiki's job.

## Wiki Location

The wiki lives at `./wiki/` at the project root and is tracked in version control alongside the code.
To find it, walk up from the current working directory looking for `wiki/SCHEMA.md`, stopping at the git root or filesystem root. No environment variable needed.

```bash
# Pseudocode for discovery
dir=$(pwd)
while [ "$dir" != "/" ]; do
  if [ -f "$dir/wiki/SCHEMA.md" ]; then
    WIKI="$dir/wiki"; break
  fi
  dir=$(dirname "$dir")
done
```

If no wiki is found, treat the user's request as either an init request (create a new wiki at the git root) or out of scope.

## Architecture: Three Layers

```
project-root/
├── src/                         # Layer 1: the codebase itself (the "raw source")
├── docs/                        # other project docs — not wiki-managed
└── wiki/
    ├── AGENTS.md                # Static routing guide for any agent that lands here
    ├── SCHEMA.md                # Conventions, structure rules, page templates
    ├── index.md                 # Sectioned content catalog with one-line summaries
    ├── log.md                   # Chronological action log (append-only, rotated yearly)
    ├── entities/                # Layer 2: modules, services, components, classes, deps
    ├── concepts/                # Layer 2: flows, mechanisms, cross-cutting patterns
    ├── comparisons/             # Layer 2: side-by-side analyses + ADRs
    ├── queries/                 # Layer 2: filed query results worth keeping
    ├── assets/                  # Diagrams and screenshots referenced from pages
    └── sources/                 # Optional: attached non-code material (RFCs, etc.)
```

**Layer 1 — The codebase:** the source tree itself plays the role that `raw/` played in the original pattern and is the behavioral source of truth.
The agent reads code but modifies it only when the accepted task also includes a code change.
**Layer 2 — The wiki:** code-derived markdown files. Created, updated, and cross-referenced. They describe current mechanics and contracts but do not replace code evidence.
**Layer 3 — The schema:** `SCHEMA.md` defines structure, conventions, page templates, and the tag taxonomy.
On team-shared wikis, treat schema changes as deliberate decisions worthy of code review — the schema constrains every team member's agent behavior.

External materials (RFCs, vendor docs, design docs) are linked from wiki pages, not copied. If the user explicitly wants to attach a non-code source, it goes in `wiki/sources/`.

## Resuming an Existing Wiki (CRITICAL — do this every session)

**Always orient yourself before doing anything.**
Skipping this step causes duplicate pages, missed cross-references, and contradictions with prior decisions.

1. **Read `wiki/SCHEMA.md`** — understand the project, conventions, page templates, and tag taxonomy.
2. **Read `wiki/index.md`** — learn what pages exist and their summaries.
3. **Scan recent `wiki/log.md`** — read the last 20-30 lines with **Read** + offset to understand recent activity.
4. **For wikis with 100+ pages**, also **Grep** for the topic at hand before creating anything new.

Only after orientation should you ingest, query, lint, or refresh. This is a
starting set; extend it to current source, callers, tests, and direct dependency
contracts when the operation depends on them.

## Initializing a New Wiki

When the user asks to create or start a wiki, follow `references/initialization.md` — it contains the full init checklist plus templates for `SCHEMA.md`, `index.md`, `log.md`, and `wiki/AGENTS.md`.

After init, agents work from the project's own `SCHEMA.md` (which embeds the conventions, frontmatter format, page templates, decoupling principle, tag taxonomy, and stale-detection layers — all customized for the project) rather than from this skill's templates. The templates are bootstrap material, not running reference.

## Core Operations

### 1. Ingest

Ingest paths differ by source type. In all cases, follow the orientation step first.

**Ingesting a module/component (the most common case):**

1. **Read the relevant source files.** Identify the entities (modules, classes, services, exported types) and concepts (flows, mechanisms) present.
2. **Identify the takeaways** — what matters for the accepted task and project. Proceed directly within an authorized unit; ask only when this reveals a genuinely new decision or scope expansion.
3. **Check what already exists** — search `index.md` and **Grep** for entity/concept names. This is the difference between a growing wiki and a pile of duplicates.
4. **Write or update wiki pages** following the templates in `SCHEMA.md`:
   - Apply the **decoupling principle** rigorously. Describe contracts, not code shape.
   - For new pages, ensure they meet the page thresholds (2+ places in code OR central to one significant component).
   - Pin sources at symbol level (or range level only when no symbol encloses the region) with commit SHA in frontmatter.
   - Set `verified_at` to the current commit (`git rev-parse HEAD`).
   - Cross-reference: every page links to at least 2 others via `[[wikilinks]]`.
   - Tags only from the taxonomy in `SCHEMA.md`.
   - For pages synthesizing 3+ sources, append `^[src/foo.ts:42-100]` provenance markers to paragraphs whose claims trace to a specific code region.
   - For opinion-heavy or single-source claims, set `confidence: medium` or `low`.
5. **Update navigation** — add new pages to `index.md`, bump "Last updated" and "Total pages", append a log entry listing every file created or updated.
6. **Report what changed** — list every file created or updated to the user.

A single module ingest can touch 5-15 wiki pages. This is normal and desired — it's the compounding effect.

**Ingesting a design decision / PR:**

Read the PR description, diff, and any linked discussion.
Create or update a comparison page using the **ADR variant** template. Describe the implemented contract outcome and consequences; link the durable `knowledge/` record for rationale and rejected alternatives rather than duplicating it.
Update affected entity and concept pages where the decision changes their behavior or contracts.

**Ingesting external documentation (RFC, vendor docs, design doc):**

Create a wiki page that summarizes the relevant takeaways and link to the original source.
**Do not copy the source into the wiki** unless it's small and the user explicitly requests it. If they do, it goes in `wiki/sources/`.

### 2. Query

When the user asks a question that the wiki could answer:

1. **Orient** (SCHEMA → index → recent log).
2. **Read `index.md`** to identify relevant entity/concept pages.
3. **For wikis with 100+ pages**, also **Grep** across all `.md` files for key terms.
4. **Start with 2-4 relevant wiki pages.** Read more pages and current source
   when needed to validate a behavioral claim or complete the dependency context.
5. **Synthesize an answer** citing the wiki pages: "Based on [[page-a]] and [[page-b]]…"
6. If a page you relied on has `confidence: low` or has gone past the trust-decay threshold, add a caveat to your answer noting that the claim should be verified against current source.
7. **File valuable answers back** — substantial comparisons, deep dives, or novel synthesis go in `queries/` or `comparisons/`. Don't file trivial lookups.
8. **Update `log.md`** with the query and whether it was filed.

### 3. Lint

When the user asks to lint, health-check, or audit the wiki:

> Most checks below are mechanically implemented in `scripts/wiki-lint.py` (shipped alongside this `SKILL.md`). Prefer running the script and acting on its output over walking the checklist by hand. See **Automated lint** below for usage. Checks that require semantic judgment (Layer 2 severity beyond heuristics, AGENTS/SCHEMA drift) still need an agent pass.

1. **Orphan pages** — pages with no inbound `[[wikilinks]]` from other pages.
2. **Broken wikilinks** — `[[links]]` pointing to pages that don't exist.
3. **Index completeness** — every wiki page should appear in `index.md`. Compare the filesystem against index entries.
4. **Frontmatter validation** — knowledge pages in `entities/`, `concepts/`, `comparisons/`, and `queries/` have all required fields (title, created, updated, type, tags, sources). Tags must be in the taxonomy. Meta pages do not need frontmatter.
5. **Stale (Layer 1 — symbol/range pins with re-anchoring).** For each pin, first re-resolve it to the current location:
   - **File rename detection**: if the pinned file is missing in the working tree but existed at `<sha>`, walk `git log --diff-filter=R --name-status <sha>..HEAD` to chain renames forward and find the file's current path. If found, switch to that path for the rest of re-anchoring and report the rename as `info` (auto-applied on `--update-pins`). If no rename can be tracked, flag stale: "file no longer exists".
   - **Symbol pin**: locate `symbolName` in the current source (Grep for the declaration, or LSP/AST when available). If the resolved range differs from what was last recorded, update the pin's resolved range silently — a location-only change is **not** stale. If the symbol is missing, flag stale: "symbol removed or renamed".
   - **Range pin**: extract the pinned content as it existed at `<sha>` (`git show <sha>:<path>`, slice the recorded line range), then search for that content in the current file. If found at a shifted location, update the resolved range silently. If not found, flag stale: "range content removed or rewritten".

   Then check whether the *resolved* range was touched between `<sha>` and `HEAD`. When a rename was detected, the diff command is given both old and new paths so git's rename-aware hunks line up with the resolved range:

   ```bash
   git log --oneline <pinned-commit>..HEAD -- <path>
   git diff <pinned-commit>..HEAD -- <path>
   ```

   For range pins, restrict the diff to the resolved (post-re-anchor) line range. Re-anchoring eliminates false positives caused by pure line shifts upstream of the pin; only genuine content changes within the resolved range are reported. Pins without an `@<sha>` suffix cannot be stale-checked at all; lint emits a LOW `unpinned-sha` finding for each (SHAs are required on every pin).
6. **Stale (Layer 2 — change classification, optional).** For each touched pin, read the diff and classify high / medium / low. Group results by severity.
7. **Stale (Layer 3 — trust decay, optional).** For each page, count commits since `verified_at` that touched any pinned source. If past threshold (default 50), demote `confidence: high` to `medium` and note the demotion in the report.
8. **Documentation gap detection** — recently touched source paths (configurable window, default 30 days, `--since`) that no wiki page pins:

   ```bash
   git log --since="30 days ago" --name-only --pretty=format: | sort -u
   ```

   A touched path counts as covered when **any** page pins it, regardless of when that page was last updated. Uncovered paths are grouped by top-level directory, and only groups with 3+ touched files in the window are surfaced as "potential documentation debt" with suggested investigation areas.
9. **AGENTS.md / SCHEMA.md drift** — warn when `wiki/AGENTS.md`'s described directory structure or operations diverge from what `SCHEMA.md` defines.
10. **Quality signals** — list pages with `confidence: low`, `contested: true`, or single-source pages with no confidence field set (candidates for either corroboration or demotion).
11. **Page size** — flag pages over 200 lines as candidates for splitting.
12. **Tag audit** — list all tags in use; flag any not in the `SCHEMA.md` taxonomy.
13. **Log rotation** — if `log.md` exceeds 500 entries, rotate it.
14. **Report findings** with specific file paths and suggested actions, grouped by severity: broken links > stale (high-severity diffs) > stale (medium) > orphans > documentation gaps > stale (low/style) > contested pages.
15. **Append to `log.md`:** `## [YYYY-MM-DD] lint | N issues found`

#### Automated lint: `scripts/wiki-lint.py`

The skill ships with a Python implementation of the mechanical lint checks at `scripts/wiki-lint.py` (sibling to this `SKILL.md`).
Run it on demand, in a pre-commit hook, or in CI — by hand it's the right starting point for any audit or refresh request before the agent steps in for semantic work.

For the implemented check coverage, command-line flags, exit codes, and `--update-pins` semantics, see `references/lint-script.md`.

After running the script, agents should still:

- Walk through each non-info finding and decide whether to refresh, archive, or accept.
- Run lint check 9 (AGENTS/SCHEMA drift) by reading both files and comparing the described structure against `SCHEMA.md`.
- For Layer 2 stale results, re-classify when the heuristic seems off (e.g., a one-line change that actually breaks an invariant).
- Append the lint log entry per step 15 above.

### 4. Refresh

Stale detection without a follow-up action just accumulates noise in lint reports.
Refresh is the action that turns findings into updates.

When the user says "refresh stale pages" (or asks to refresh a specific page):

1. Run a fresh lint pass to identify stale candidates (Layer 1 + Layer 2 results).
2. For each candidate:
   - Read current source at the pin's *resolved* location (lint's re-anchoring step has already resolved symbol pins to their current line range and re-located range pins where the content shifted; refresh therefore deals only with genuine content changes, not pure line shifts)
   - Diff it against the wiki page's claims
   - Determine the updates required by current source
3. If refresh is already part of the authorized unit, proceed without asking
   again. Ask only before expanding beyond that scope. Then:
   - Update the wiki page text where claims diverged
   - Bump the `updated` date
   - Update each pin's commit SHA to current `HEAD`
   - Set `verified_at` to current `HEAD`
   - Append a log entry: `## [YYYY-MM-DD] refresh | <page>`
4. When refreshing many pages, batch the updates and write a single summary log entry.

Refresh is the inverse of ingest: ingest brings new knowledge in, refresh reconciles existing knowledge with the current state of the code.

## Working with the Wiki

### Searching

- Find pages by content → **Grep** with pattern, `path=<wiki>`, `glob="*.md"`
- Find pages by filename → **Glob** with `pattern="**/*.md"`, `path=<wiki>`
- Find pages by tag → **Grep** with pattern `"tags:.*auth"`, `path=<wiki>`, `glob="*.md"`
- Recent activity → **Read** `<wiki>/log.md` with offset for the last 20-30 lines

### Scoping a code change (blast-radius) — `scripts/wiki-pages-for.py`

Before editing or refactoring code, find which wiki pages document the symbols you are about to touch — so you read the right contracts first, and know which pages to refresh after. The reverse of lint: lint asks "did the code drift from the pins?", this asks "which pages pin this code?".

```bash
python3 ~/.codex/skills/codebase-wiki/scripts/wiki-pages-for.py <wiki_dir> <path | path:symbol | symbol> [...]
```

(Windows: `python`.) Read-only. For each input it prints `DOCUMENTED by <pages>` or `NOT DOCUMENTED`, plus the 1-hop `[[link]]` ripple neighborhood (dependent pages to also check) and a coverage count.

**Fail-safe for refactor scoping** — under-scoping the blast radius is the dangerous error, so a `NOT DOCUMENTED` input is surfaced, never silently dropped: it means the wiki is blind there → grep the code for callers/imports. The map only covers what the wiki documents; the true blast radius can be larger. Use it to *narrow* where to look, then cross-check undocumented inputs against the code. It earns its keep most as the wiki grows past eyeball size; on a small wiki it mainly guards against missing a non-obvious documented dependent (e.g. a symbol that turns out to be pinned by 6 pages, not the 2 you'd recall).

### Change-impact protocol (before editing code)

The discipline that keeps a change coherent with the structure it lives in (parent contracts, child dependents) — engineered code, not vibe-coded tangle. **Fires by default.** Skip ONLY for changes that provably cannot affect a runtime contract: typo, formatting, comment, private test-only fixture, proven-dead-code removal. Anything touching an exported/shared symbol, config, schema, API/CLI, persistence, error/lifecycle semantics, or a file with callers/importers → run it. When unsure whether a change is local, assume it is **not** (under-scoping the blast radius is the dangerous error → default wide).

**1. Classify the change kind** — the kind sets the required rigor:

| kind | what it is | orientation required | wiki after |
|---|---|---|---|
| leaf implementation | code behind an unchanged contract; no caller sees a difference | confirm the contract you implement against | update the entity page if behavior is documented |
| contract-preserving extension | adds capability, keeps every existing promise | verify existing callers stay valid (contract unchanged) | extend the page |
| **contract change** | changes a signature / behavior / invariant a promise rests on | **find ALL dependents** (ripple + caller search), migrate/verify each — the dangerous kind | update the contract + ADR if consequential |
| dependent migration | updates callers to an already-changed contract | orient on the new contract + each caller | update affected pages |
| docs / format / dead-code | no runtime contract effect | none | none (unless a doc page) |

**2. Map the blast radius** — `wiki-pages-for` on the touched files/symbols → documenting pages (contracts) + ripple (dependents). NOT-DOCUMENTED touched symbols → search callers/importers/references in the code. The wiki covers only what it documents; default wide.

**3. Contracts are hypotheses** — the wiki is derived from code and does not prove current behavior (freshness catches structural, not semantic, drift). Desired behavior comes from the user's acceptance criteria; decision rationale belongs in `knowledge/`; observed execution is separate evidence. Validate every depended-on contract against current code/callers. If wiki and code diverge, resolve the drift within the authorized unit and record any genuinely new decision instead of silently choosing a side.

**4. State the coherence constraints** before coding: "to not tangle — conform to <contract>, preserve <dependents>' assumptions <A1..>, blast radius = <files/pages>." On a real decision, surface for the pick (design-first).

**5. Implement surgically** within those constraints.

**6. Capture (loops back to keeping the wiki current)** — after a non-trivial change, refresh the affected wiki pins/contracts (re-pin symbols, `verified_at`→HEAD, update contract prose, ADR if consequential) as part of the authorized unit; do not ask again for that refresh. A new public/shared symbol with no page is a future blind spot → document it. Backstop: `wiki-lint`'s doc-gap + stale-pin checks (run via `/doctor`) surface what you forgot — the tier-A net under this otherwise agent-driven loop.

Any committed or dirty change to a pinned source invalidates the affected wiki
claim until rechecked. It also invalidates prior execution evidence or delegated
results that depended on the old bytes. Re-read the current diff and rerun the
meaningful checks before accepting those results.

Ceiling: this makes the *process* reliable; it cannot make the judgment correct (which contract matters, whether the wiki is complete) — that needs current source and sound judgment, and depends on the capture step (6) actually happening.

### Bulk Ingest

When ingesting multiple modules at once, batch the updates:
1. Read all relevant source first
2. Identify all entities and concepts across the batch
3. Check existing pages for all of them in one search pass (not N)
4. Create/update pages in one pass (avoids redundant updates)
5. Update `index.md` once at the end
6. Write a single log entry covering the batch

### Archiving

When content is fully superseded or the project drops a component:
1. Create `_archive/` if it doesn't exist
2. Move the page to `_archive/` preserving its original sub-path (e.g., `_archive/entities/old-service.md`)
3. Remove from `index.md`
4. Update any pages that linked to it — replace the wikilink with plain text + "(archived)"
5. Log the archive action

### Sync via Git

The wiki is a git-tracked directory. Synchronization between machines and team members happens through normal git workflows — commit, push, pull. There is no special sync tooling.

For team-shared wikis, treat `SCHEMA.md` changes as deliberate decisions worthy of code review, since the schema constrains every team member's agent behavior. Page churn is expected; schema churn should be deliberate.

`wiki/assets/` holds diagrams and screenshots referenced from pages (e.g., `![flow](assets/auth-flow.png)`). Mermaid diagrams render natively in many viewers and don't need this folder.

## Pitfalls

- **Always orient first** — read SCHEMA + index + recent log before any operation in a new session. Skipping this causes duplicates and missed cross-references.
- **Always update `index.md` and `log.md`** — these are the navigational backbone. A wiki without them is just a folder of files.
- **Decouple from code shape** — write about contracts and intent, not line numbers and call graphs. This is the single biggest factor in long-term wiki value.
- **Don't create pages for passing mentions** — follow the page thresholds. A name appearing once in a footnote doesn't warrant an entity page.
- **Don't create pages without cross-references** — isolated pages are invisible. At least 2 outbound `[[wikilinks]]` per page.
- **Frontmatter is required for knowledge pages** — it powers search, lint, and stale detection for `entities/`, `concepts/`, `comparisons/`, and `queries/`. Meta pages do not need frontmatter.
- **Tags must come from the taxonomy** — freeform tags decay into noise. Add new tags to `SCHEMA.md` first, then use them.
- **Prefer symbol pins; fall back to range pins** — symbol pins (`path:symbolName@<sha>`) are required wherever a symbol encloses the region and are immune to line shifts. Range pins are a fallback for regions with no enclosing symbol; file-level pins flag too aggressively and should be avoided. Lint re-resolves pins on each pass, so pure code movement (insertions above the pin, file reorganization) does not trigger false positives. Pin paths also follow `git mv` operations: when the pinned file is missing, lint walks `git log --diff-filter=R --name-status` to track the file forward through renames and reports the move as an info-level shift that `--update-pins` rewrites in place.
- **Set `verified_at` whenever you reconcile a page with current source** — this is what trust decay reads.
- **Keep pages scannable** — readable in 30 seconds. Split pages over 200 lines.
- **Respect the authorized scope** — update all affected pages already inside the unit. Ask only when a large update would expand the agreed scope or require a genuinely new decision.
- **Rotate the log** at 500 entries.
- **Handle contradictions explicitly** — don't silently overwrite. Note both claims with dates, mark in frontmatter, flag in lint.
- **Never modify `wiki/AGENTS.md` during normal operation** — it is intentionally static.
- **Don't modify code in a wiki-only task.** When the accepted unit includes code and affected wiki updates, complete both without reopening authorization.
