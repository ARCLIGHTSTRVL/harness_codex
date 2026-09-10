> Codex port of the upstream convention at `48480a0`. Historical Claude
> observations remain source history; executable Codex behavior lives in the
> ported skills and `docs/PORT_AUDIT.md`.

# Spec: Project Research-Knowledge Base

## Metadata
- Rounds: 7 (+ external research: Karpathy LLM Wiki gist, codebase-wiki SKILL.md, **hermes llm-wiki SKILL.md**)
- Final Ambiguity: ~8%
- Type: brownfield (modifies existing knowledge infrastructure)
- Status: PASSED — scope: the interview's ambiguity gate, NOT build acceptance. The Acceptance
  Criteria boxes below track the live system and were never formally ticked (verified ad hoc as
  the KB was built — truth-down note 2026-06-10, R3).
- Date: 2026-05-30
- Authoritative language: EN (per the in-repo-EN decision); KR mirror is the human reading copy.

## Clarity Breakdown
| Dimension | Score | Weight | Weighted |
|---|---|---|---|
| Goal | 0.92 | 0.35 | 0.32 |
| Constraints | 0.92 | 0.25 | 0.23 |
| Success Criteria | 0.88 | 0.25 | 0.22 |
| Context (brownfield) | 0.92 | 0.15 | 0.14 |
| **Ambiguity** | | | **~8%** |

## Goal
A modular, full-fidelity, navigable knowledge base that preserves a project's hard-won **research intellect** — literature understood, experiments found, decisions made — so a forgetful future (the user, or Claude) can **reconstruct the mental picture and avoid re-deriving settled work.**

Purpose = **anti-amnesia**, not publication, not a thinking canvas. Two main read-moments: (1) resume a research thread with full context restored; (3) avoid re-experimenting / re-deriving settled work.

## Lineage (where this comes from)
- **Karpathy's LLM Wiki** — the abstract pattern (persistent, compounding, interlinked wiki; LLM does the bookkeeping; maintenance cost ≈ 0).
- **hermes llm-wiki** (NousResearch) — the *research implementation* of that pattern: raw = articles/papers/transcripts, Obsidian-native, sha256-pinned sources, provenance markers. **This is our skeleton.**
- **codebase-wiki** — the *code-specialized fork* (source-tree as raw, symbol pins, decoupling, token-efficiency). A sibling, not our parent; we cherry-pick only its mechanical lint.
- **Ours = hermes skeleton + two deltas:** (A) add a **journal** (time-axis work-unit) layer the others lack; (B) **invert the compression posture** (full-fidelity 2+3 instead of 200-line summaries).

## Constraints
- **Full-fidelity (locked):** project knowledge must NOT be compressed/summarized. Quality bar = *reconstruct-from-zero*, not reminder-level. Derived from the anti-amnesia purpose (a forgotten + over-condensed note is "blurry and unrecoverable").
- **Two-layer entry (the quality bar):**
  - **Layer A — substrate (structured-lossless):** hypothesis / method / config / result (every fact & number) / interpretation / decision. Nothing material dropped.
  - **Layer B — overlay (curated narrative):** reasoning, alternatives weighed, concrete texture, why-it-matters, as prose on top of A.
  - Organization lives in B and is **additive**; A keeps everything raw. Summary never *replaces* the raw.
- **Modular boundaries (the true driver):** knowledge decomposition **mirrors work decomposition** (the "Modular by default" code principle — parent/child, scales without collapsing). ~500-line page size is a **split/boundary signal, not a fidelity cap.** No monoliths.
- **Location/language:** in-repo **EN authoritative** (version-controlled, co-located with code) that **doubles as an Obsidian vault** + **Obsidian KR mirror** (full-fidelity) for comfortable reading.
- **Format:** markdown.
- **Build posture:** **convention-first** → **skillified 2026-06-01** after the Hibiki dogfood earned it. A thin, experimental `/research-kb` skill (init / lint / capture only — no query/refresh engine) now exists; the discipline (recompute-from-raw, write-back) lives in CLAUDE.md policy. Per-project `knowledge/SCHEMA.md` remains the authority. (History: this started convention-first — "no skill yet, dogfood manually, skillify only if earned.")

## Non-Goals
- NOT codebase-wiki's job (code mechanics stay there, AI-facing/terse/source-pinned/separate).
- NOT operational external facts (Electron signing, winget, library/API truths) — those stay in `memory/`, re-searchable.
- NOT a publication pipeline (#2 output processed separately/immediately).
- NOT a thinking canvas (#4 thinking happens in chat; only its valuable *results* file back — see ①).
- NOT reminder-level / compressed notes.
- ~~NOT a built skill (yet)~~ — superseded 2026-06-01: a thin `/research-kb` skill shipped after the Hibiki dogfood earned it (see Build posture above; contradiction caught by the 2026-06-10 cold eval).

## Concrete Structure
The base is a single markdown folder that is simultaneously a git-tracked directory and an Obsidian vault:

```
<project>/knowledge/              # in-repo · EN authoritative · IS an Obsidian vault
├── SCHEMA.md                     # conventions, 2+3 entry template, tag taxonomy (10–20 top-level)
├── index.md                      # sectioned catalog + one-line summaries
│                                 #   (split a section >50 entries; add _meta/topic-map.md at 200+ pages)
├── log.md                        # append-only action log (rotate → log-YYYY.md at 500)
├── raw/                          # L1 — immutable sources, sha256-pinned (read-only; corrections go in wiki pages)
│   ├── papers/                   #   paper PDFs / markdown      (frontmatter: source_url, ingested, sha256)
│   ├── data/                     #   raw experiment outputs, metric dumps, configs
│   ├── transcripts/              #   captured chat / discussion
│   └── assets/                   #   figures, diagrams (Obsidian attachment folder)
├── journal/                      # L2a — TIME axis: one work-unit → one entry, full 2+3, append-only, ~500 split
├── synthesis/                    # L2b — TOPIC axis: accreting concept pages ("all we now know about X"), full 2+3
├── comparisons/                  # L2  — decisions / ADRs (Context · Decision · Consequences · Alternatives)
├── queries/                      # L2  — filed valuable explorations (write-back loop ①)
└── _archive/                     # superseded content
```

**Where the three knowledge types live:**
- Type 1 (literature) → `synthesis/` topic pages + the PDFs in `raw/papers/`.
- Type 2 (experiment findings) → `journal/` entries (per work-unit) + `synthesis/` rollups.
- Type 4 (decisions) → inline in `journal/` (Layer A `decision` + Layer B reasoning) + a standalone `comparisons/` ADR for cross-cutting ones.
- (Type 3 operational facts stays out — in `memory/`.)

**Frontmatter:**
```yaml
# wiki page (journal/synthesis/comparison/query)
---
title: ...
created: YYYY-MM-DD
updated: YYYY-MM-DD
type: journal | synthesis | comparison | query
tags: [taxonomy-only]
sources: [raw/papers/foo.md, raw/data/run-42.md]   # pins
confidence: high | medium | low      # optional
contested: true                      # optional
contradictions: [other-page-slug]    # optional
---

# raw source
---
source_url: https://...        # or local origin
ingested: YYYY-MM-DD
sha256: <hex digest of body>   # papers only; drift detection (⑤). Run-data uses
                              # immutable versioned filenames, not sha256 (see Revisions #4)
---
```

**2+3 entry template (journal):**
- *Layer A (substrate):* Hypothesis · Method · Config · Result (every number) · Interpretation · Decision.
- *Layer B (overlay):* curated narrative — reasoning, alternatives weighed, texture, why-it-matters.
- ≥2 outbound `[[wikilinks]]`; paragraph provenance `^[raw/papers/foo.md]` on multi-source claims (⑥).

## Operations (the flow)
1. **Ingest source** — save paper/data to `raw/` with `sha256` frontmatter → discuss takeaways → update/create the `synthesis/` page that absorbs it, with provenance markers.
2. **Record a work-unit** (fires at Continuity unit-boundaries) — write a `journal/` entry in full 2+3, pin to its `raw/` sources, cross-link, and update the `synthesis/` pages it touches.
3. **Resume / query** (anti-amnesia) — orient (SCHEMA → index → recent log) → read the relevant `journal/` entries + `synthesis/` pages → reconstruct context. `raw/` is the fallback, not the starting point.
4. **Write-back ①** — valuable chat-thinking after a resume is filed back as a new `journal/` entry, a `synthesis/` update, or a `queries/` page. The base grows from the thinking it enables.
5. **Lint** — mechanical (orphans, broken links, index completeness, frontmatter validation, tag audit, ~500 split warning, log rotation) + **sha256 source-drift ⑤** + **date-based stale (page `updated` >90d older than newer sources on the same entities)** + **generative ④** (gaps: "findings on X and Y but no synthesis linking them"; stale threads to revisit). *(sha256-drift, date-stale, ~500-line split, log rotation: agent pass — not mechanized in kb-lint.)*
6. **Mirror** — EN base → full-fidelity KR copy in Obsidian for comfortable reading. (The EN base is *already* an Obsidian vault, so graph/Dataview work on it directly — the KR mirror is a convenience copy, not the only navigable surface.)

## Mechanisms
- **Cross-referencing** — every page ≥2 `[[links]]`, backlinks enforced. Connections are as valuable as content (Memex); for anti-amnesia, the links rebuild the mental picture.
- **① Write-back loop** — explorations compound back into the base (closes the #4 thinking loop).
- **② Obsidian-native (⑦)** — the wiki folder *is* an Obsidian vault: `[[wikilinks]]` render, **graph view** = a live monolith/navigability check (you can SEE parent/child + clusters), **Dataview** queries frontmatter ("all `confidence: low`", "all phase-6 journal entries"), `raw/assets/` holds attachments. Leverages the user's currently-underused Obsidian as the real exploration surface.
- **③+⑤ Raw-source pins with content hashing** — journal/synthesis `sources:` pin to papers/data/commits; each raw file carries a `sha256` of its body. Lint recomputes and flags drift → the research analogue of codebase-wiki's git-commit stale detection (papers have no commits, so hash instead). Reconstructability guaranteed down to the source.
- **⑥ Paragraph provenance markers** — `^[raw/papers/foo.md]` appended to synthesis paragraphs that trace to a specific source (multi-source pages). Fine-grained claim-tracing; supports full-fidelity + "where did this claim come from."
- **④ Generative + mechanical lint** — surfaces investigation gaps and missing connections (generative), plus the mechanical hermes/codebase-wiki checks, plus scaling discipline (`_archive/`, tag taxonomy 10–20, index section split at 50, `_meta/topic-map.md` at 200+ pages).

## Division of Labor (Karpathy)
- **Human (you):** curate sources, direct analysis, ask questions, **own meaning/direction.**
- **Claude:** all grunt work — summarize, cross-reference, maintain consistency, draft synthesis, run lint.
- **Why feasible now:** maintenance cost ≈ 0 (Claude doesn't get bored or forget) → full-fidelity is sustainable (humans abandon wikis when upkeep outgrows value), and it won't re-monolith (Claude maintains + modular boundaries enforce splitting).

## Acceptance Criteria
- [ ] A forgotten thread reconstructs from its `journal/` entry + linked `synthesis/`, without re-reading `raw/`.
- [ ] No single file is exhausting; everything reachable via `index.md` + Obsidian graph.
- [ ] "Did we already try X / what did we conclude?" answerable from `synthesis/`.
- [ ] Layer A preserves every fact/number (lossless); Layer B makes it understandable.
- [ ] Boundaries mirror work units; pages near ~500 lines trigger a parent/child split.
- [ ] Valuable chat-branches get filed back (loop closes).
- [ ] Raw paper sources are sha256-pinned; lint catches source drift. (Run-data: immutable versioned filenames or numbers absorbed into Layer A — Revisions #4.)
- [ ] Synthesis paragraphs carry provenance markers to their raw sources.
- [ ] EN base is in-repo + Obsidian-navigable; KR mirror generated on-demand for deep reading (Revisions #7).

## Assumptions Exposed & Resolved
| Assumption | Challenge | Resolution |
|---|---|---|
| All knowledge types need the same treatment | Round 1 | No — 1/2/4 (intellect) is the target; 3 (operational) stays in `memory` |
| "Don't compress" is arbitrary | Round 2/3 | No — *forced* by the anti-amnesia purpose (reconstruct-from-zero) |
| `memory/` already does this | Round 4 Contrarian | No — memory = compressed pointer-index; base = full fidelity; memory links IN |
| The real problem is fidelity | Round 4 | No — it's **modularity/boundaries** (the monolith pain); fidelity is a requirement |
| Borrow from codebase-wiki | Karpathy fetch | No — parent is the LLM-Wiki line; codebase-wiki is the code fork |
| Karpathy abstract is the parent | hermes fetch | Refined — **hermes llm-wiki** is the concrete research skeleton; Karpathy is the abstract pattern above it |
| Build a skill now | Round 6 Simplifier | No — convention-first |
| Obsidian = final-tidy dump | Karpathy ② / hermes ⑦ | Upgraded — the EN base *is* an Obsidian vault (graph/Dataview direct); KR mirror is a reading copy |

## Technical Context (brownfield)
- **codebase-wiki** — code mechanics, AI-facing, source-pinned. Separate; cherry-pick mechanical lint only.
- **hermes llm-wiki** — our structural skeleton (research + Obsidian-native + sha256 + provenance). We add journal + invert fidelity.
- **knowledge_fidelity policy** — AI-facing (terse) vs human-facing (preserve). This base = human-facing/preserve. Continuity clause = "when to record" (unit boundaries).
- **memory/** — compressed cross-session pointer-index; links INTO this base; stays terse.
- **workflow/*.md + workflow-mirror** — EN→KR mirror pattern (terse). This base reuses the pattern at full fidelity (needs a fidelity-preserving variant).
- **Obsidian** — was the KR final-tidy destination; now the navigable reading layer + the EN base is itself a vault.
- **`knowledge/` vs `wiki/` + `workflow/` authority boundary** — the global CLAUDE.md (then `<obsidian_project_organization>`, now retired; `<project_wiki_layer>`) at the time named `workflow/*.md` + `wiki/` as Claude's only authoritative in-repo layers. This base adds a THIRD authoritative in-repo layer, `knowledge/`, with a distinct role: `wiki/` = how the code works (AI-facing, terse, source-pinned); `workflow/` = what we're doing now; `knowledge/` = research intellect at full fidelity (human-facing). Non-overlapping by design. **Integrating this distinction into the global policy is deliberately deferred until the dogfood validates the convention** — pinning `knowledge/` as authoritative globally before it earns it would over-commit. *(Resolved since: the dogfood validated, and `<project_wiki_layer>` now names `knowledge/` as the third layer with `_fragments/` routing; this paragraph is kept as design history — dead section ref corrected 2026-06-10.)*

## Open Items (resolve in the convention phase)
1. ~~Exact folder layout~~ → resolved above (subject to dogfood tuning).
2. Migration: do existing Hibiki memory files (`project_hibiki_phase6`, `project_hibiki_phase7_session21`) migrate into `journal/`, or is the base forward-only with memory linking back?
3. The full-fidelity EN→KR mirror mechanism (workflow-mirror is terse-tuned — needs a fidelity-preserving variant, or read the EN base directly in Obsidian).
4. Per-project `SCHEMA.md` instances (Hibiki tag taxonomy ≠ Tidal's).
5. First dogfood target: a concrete Hibiki work unit, end-to-end.

## Next Step (convention-first; do NOT auto-build a skill)
Pick one real Hibiki work unit. In a draft `knowledge/` folder, write: its **journal entry** (full 2+3), the **synthesis page(s)** it updates, the **`raw/` sources** (with sha256), and **provenance markers**. Open the folder in Obsidian, check the **graph view**, evaluate against the acceptance criteria, iterate the convention. **Skillify only after it earns it — and when you do, fork hermes llm-wiki** (research + Obsidian-native already done; add the journal layer, invert the 200-line summary posture to full-fidelity 2+3, drop nothing else) rather than building from scratch or forking codebase-wiki.

## Revisions — Cold Simulation + Product Scope (2026-05-31)

A 3-month forward cold-simulation (Hibiki usage) plus the revealed product scope (a serviced, Roon-like integrated audio program with Hibiki embedded) produced these corrections. Where they conflict with earlier text, they win.

### Cold-sim fixes (research pillar)
1. **journal trigger is NOT silent-auto** ★. "Auto at unit boundary" has no real automation — Claude only writes while in a response, so the journal silently develops gaps that bite exactly at the cold-start payoff. Fix: an explicit-but-lightweight trigger — the user says "log it" at a unit boundary, or Claude proposes "closing this unit, writing the entry" at a natural pause and the user nods. Deliberate, not silent. (Supersedes the earlier "journal = auto" split.)
2. **Unit granularity for ML = a resolved QUESTION, not a run.** One journal entry = one hypothesis explored across N runs to a conclusion. The N runs are `raw/data`; dead-ends are one-liners in Layer A ("v9–v14 tried, rejected: X"), not separate entries. Dissolves both over/under-journaling and the live-append-vs-batch dilemma.
3. **Absorb key numbers into Layer A before raw cleanup.** Lazy migration's "reconstruct from surviving raw" fails when ML run artifacts get cleaned up. Fix: the entry's Layer A captures the decisive numbers at write time, so it survives even when the raw data file is deleted. Permanent raw retention is selective.
4. **Papers vs run-data pinning split.** sha256 fits immutable papers, not versioned run outputs. Papers → sha256-pinned in `raw/papers/`. Run data → immutable versioned filenames (`run-v11.json`, never overwritten) OR numbers absorbed into Layer A (no file pinned).
5. **Synthesis splitting ≠ journal splitting.** A journal entry is naturally bounded (one question); a synthesis page accretes and is the re-monolith risk. Fix: split a synthesis page into subtopic pages under a parent hub (table of contents) — a different rule from journal's ~500 split.
6. **Batch the synthesis confirms.** Per-finding confirmation becomes the new maintenance burden. Fix: Claude drafts synthesis updates as it goes, surfaces them in ONE batch at session end, not one prompt per finding.
7. **Recovery default = read the EN base directly in Obsidian** (graph/Dataview); KR mirror generated on-demand for deep reading only. Avoids constant-sync burden and stale-KR-at-resume. (Resolves Open Item #3.)

**Open Item #2 (migration) resolved → lazy / migrate-on-touch:** KB is forward-only; `memory/` keeps the compressed past and links into the KB; when an old topic is re-engaged, its KB page is reconstructed from *surviving raw* (not the lossy memory note), and the old memory file is demoted to a pointer. Bulk migration is rejected (it would produce false-fidelity from already-compressed notes).

### Boundary rules (from the usage-scenario sort)
- **memory vs KB is layered, not partitioned.** A fact coupled to a finding's validity lives full in the KB entry's Layer A; if it's *also* a recurring cross-session trap, a compressed pointer also goes in `memory/`. Pure standalone re-searchable ops facts → `memory/` only.
- **Write-back is the Continuity trigger, routed by content** (research → KB; cross-session pointer → memory). The journal record fires at the lightweight unit-boundary trigger (fix #1); synthesis/decision *meaning* is drafted by Claude and confirmed by the user (the human owns meaning).

### Decision records — explicit trigger + design-session scope (closes harness-agenda ⓑ)
The `comparisons/` decision-record type (Context · Decision · Consequences · Alternatives) existed in the structure but lacked a *write trigger* and was implicitly scoped to in-project research decisions only. Three refinements:

- **Explicit trigger, ceremony-guarded.** A standalone decision record fires when a design decision is **consequential / hard-to-reverse / crosses a unit boundary** — the *same* threshold as the "full treatment" in the `Design-first` policy. Small two-way picks (naming, local style) do NOT get a record; they stay in chat. Reusing an existing policy line introduces no new judgment, and it guards both failure modes: the ceremony explosion (a record per trivial pick) and the pain it fixes (consequential exploration evaporating).
- **Scope = design/brainstorming sessions, including harness-meta.** A design/brainstorming session's output — alternatives weighed, cold risks named, why X won — *is* a decision record, not only a research-internal choice. This applies to **harness-meta design work** (the harness's own evolution) too, whose domain instance is `upstream-harness/knowledge/` (thin: only `comparisons/` populated until other slices are earned).
- **memory = pointer, never the record (the pain-kill).** A consequential design decision's full exploration goes to the `comparisons/` record at full fidelity; `memory/` holds only a one-line pointer to it. This closes the failure the user feels — design/brainstorming knowledge compressing into memory and becoming unreconstructable. Same layered rule as research; stated explicitly for decisions because that is where the leak was.

This **closes ⓑ** ("브레인스토밍 세션 / 문서화") of the harness foundation agenda: the *mode* half was already covered (always-on `Design-first` + `/deep-interview`); this supplies the *documentation* half. First dogfood record: this very session, at `upstream-harness/knowledge/comparisons/harness-knowledge-foundation.md`.

### Product scope — multi-domain (thin skeleton now, fill later)
The real target is a serviced Roon-like audio product with Hibiki embedded. Knowledge spans THREE domains, not one:
- **Research** (Hibiki AI) → this KB (designed).
- **Engineering** (the app) → `codebase-wiki` (first-class once app code exists).
- **Product/Service** (features, decisions, ops, incidents, user feedback) → a future KB instance of the SAME convention.

The convention is **domain-general**: instantiate it per domain (separate `knowledge/` folders, identical structure). The load-bearing new piece at multi-domain scale is a **cross-domain index** — tracing a research-finding → product-decision → code → service-incident chain — so the system doesn't trade the monolith problem for a fragmentation problem. **Designed thin now (the slot is named); detailed only when the product materializes its domains.** Do NOT over-design the cross-index against hypothetical chains.

### Dogfood iterations (2026-05-31, v9+v10 Hibiki) — these win on conflict
The convention was dogfooded end-to-end on two real Hibiki units (the v9
phase-collapse diagnosis and the v10 Step-A phase fix). Five refinements emerged;
where they conflict with earlier text, they win.

1. **Non-markdown raw needs a `_sources.md` ledger (named mechanism, not improvisation).**
   The frontmatter pinning scheme (`source_url` / `ingested` / `sha256`) assumes a
   markdown raw file, but CSV/binary raw **cannot carry frontmatter**. Rule: each
   `raw/<kind>/` directory holding non-markdown sources carries a `_sources.md`
   ledger — a table of `file | origin | ingested | sha256 | what it is` — and the
   actual binary/CSV lives only in the EN authoritative base (the KR mirror records
   the ledger, not the data file).
2. **Label every metric number as absolute (`rest`) or delta (`gain`).** The first
   anti-amnesia catch was a recalled table that labeled a complex-SDR *delta*
   (−19…−36) as if it were the absolute output (≈ −1.6). Recording rule: any
   metric figure in Layer A or synthesis states which framing it is; tables name
   the columns (`out` vs `Δ`); ambiguity is a defect, not a style choice.
3. **Page-level `confidence` = the lowest of its sections.** When a page mixes
   pinned and recalled content (e.g. a synthesis page with a pinned v9 section and
   a recalled-but-unpinned v10/streaming section), a single page-level
   `confidence: high` overclaims. Rule: set page confidence to the lowest section's,
   keep an inline note marking which subsection is still recall, and promote when
   the raw is pinned. (Splitting the unpinned part into its own page is an
   acceptable alternative.)
4. **Lint strips code spans/fences before extracting `[[links]]`.** Prose that
   *mentions* a wikilink inside backticks (e.g. `` `[[wikilinks]]` `` in SCHEMA)
   must not be reported as a broken link. Any lint (manual or future script)
   removes code spans and fenced blocks before scanning for links.
5. **The "1 entry = 1 resolved question" unit rule validated — no change.** Across
   v9 (a diagnosis) and v10 (its corrective confirmation), the rule held cleanly:
   N runs lived in `raw/data`, dead-ends were Layer-A one-liners, and v9↔v10 formed
   a natural failure-and-confirmation pair without any entry bloating. Recorded as
   validated.

Process note (not a spec rule): the dogfood repeatedly caught recall/fabrication
by **recomputing from the pinned raw before writing** (wrong song names, a wrong
data path, fabricated v10 numbers). This is the convention working as intended —
the pinned raw + recompute discipline is the anti-amnesia guarantee in action.

### Status: foundation track
This spec is the **research pillar of the harness knowledge foundation**, now locked. The full product — and its engineering + product-service knowledge pillars + the cross-domain index — is a SEPARATE track, started when the user explicitly begins product work, built on this completed foundation skeleton-first. Discipline: a *thin-but-complete* skeleton (every part has a defined place; contents stubbed and filled incrementally) — avoiding both the bottom-up monolith and top-down analysis-paralysis.

## Interview Transcript
<details><summary>Full Q&A (7 rounds + external research)</summary>

**R1 — Goal (knowledge type).** Primary = 1·2·4 (literature + findings + decisions); NOT 3 (operational, stays in memory). 100→54%.
**R2 — Success (purpose).** Main = 1 (resume thread) + 3 (avoid re-derivation) = anti-amnesia. #2 separate, #4 downstream (→ write-back). "Don't compress" forced by purpose. 54→36%.
**R3 — Constraints (quality bar).** 2+3 dual-layer (lossless substrate + curated narrative). Organize in B, raw in A. 36→30%.
**R4 — CONTRARIAN (why not memory?).** New base needed, BUT real pain = monolithic management; true driver = **modularity** (knowledge mirrors work decomposition, parent/child). 30→22%.
**R5 — Decomposition axis.** Both (journal time-axis + synthesis topic-axis), strict boundaries. 22→17%.
**R6 — SIMPLIFIER (skill?).** Convention-first. Fork tradeoffs: right skeleton, wrong philosophy. 17→14%.
**R7 — Location/language.** in-repo EN authoritative + Obsidian KR mirror. 14→~13%.
**External — Karpathy gist.** Original is a closer parent than codebase-wiki. Adopted ①write-back ②Obsidian-nav ③raw-sources+pins ④generative-lint. ~13→~10%.
**External — hermes llm-wiki.** The concrete research implementation; becomes the skeleton. Adopted ⑤sha256 source-drift ⑥paragraph provenance ⑦Obsidian-native vault ⑧raw-frontmatter+date-stale+scaling. Parent template updated; ② refined. ~10→~8%.

</details>
