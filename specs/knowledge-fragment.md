> Codex port of the upstream convention at `48480a0`. Historical Claude
> observations remain source history; executable Codex behavior lives in the
> ported skills and `docs/PORT_AUDIT.md`.

# knowledge-fragment — real-time capture of conversation-born knowledge, fanned out to wiki + knowledge

**Status:** BUILT (first scope, §12) + dogfooded — §8 acceptance PASS + first consolidation PASS — 2026-06-05.
**Provenance:** Claude (Opus 4.8) + Codex (gpt-5.5, xhigh, web-grounded). Three Codex consults: (1) how conversation-born knowledge is kept current; (2) fragment granularity (→ Decision D); (3) a Mode-3 implementation review of the first build (→ dropped the infeasible PreToolUse trigger, added the consolidation adapter, fixed the delta format). This revision folds in the wiki fan-out, the real-time-capture discipline, and the cold-reader acceptance test.
**Relation to other specs:** complements `freshness-detection-spine.md` (structural freshness) and `deep-interview-knowledge-base.md` (the `knowledge/` layer this feeds). This is the *write-back* half of the knowledge loop.
**Naming:** the feature is **knowledge-fragment** — do NOT call builds "v1/v2" (`naming-no-version-suffixes` — memory pointer, machine-local, not in this repo); name builds by scope.

---

## 1. Problem

**Before this tier**, the harness kept `knowledge/` (research intellect: experiments, findings, decisions) current by **policy only** — a tier-B nudge: "at a natural pause, OFFER to file a resolved question into `knowledge/`." No mechanical trigger ⇒ it rots (the agent forgets; out-of-band work is never captured). The implicit model — **"knowledge gets documented AFTER the work"** — is backwards.

> **Status 2026-08-05.** The *semantic* half of that sentence still stands: deciding
> that a decision has crystallized, and filing it, remains agent discipline — the Stop
> backstop is still deferred (§12). What is now mechanical is everything AFTER a delta
> exists: parsing, `deltas-for --debt`, `consolidate --draft/--apply`, and the 30-day
> `/doctor` escalation. Those detect unconsolidated debt, never uncaptured decisions.
> Read "policy only" as scoped to the capture trigger, not to the tier as a whole.

## 2. Reframe (keystone)

**Knowledge precedes code.**
1. Knowledge is born in **conversation** — research, weighing alternatives, decisions accumulate through dialogue.
2. Code is the **crystallization at the END of that flow** — the *output* of the knowledge, not its source.
3. So knowledge is **upstream** (foundation); code is **downstream**.
4. In the corrective loop too: when code is wrong / being torn down, the flow returns to the knowledge layer, **corrects the understanding FIRST, then rewrites code** — the rewrite rests on corrected belief, not the same stale one.

**Trigger implication:** capture is NOT "after a code change." It is at the **conversation → implementation boundary** (knowledge just formed; code about to be written) and the **overhaul boundary** (code judged wrong → reconsider knowledge before rewriting). `git diff` is downstream evidence — it says code changed, not whether the *premise* changed.

**Field grounding** *[Established, Codex web search]:* the episodic→semantic consolidation pattern (Generative Agents, Reflexion). Production tools do it: **Cline "Memory Bank"** updates memory *before* coding; **GitHub Copilot Memory** stores cited architectural facts, validates citations against the current branch, expires unused facts after 28 days; **Cursor** does sidecar extraction with user approval; **ADRs** work because they record *why*.

## 3. Naming (the vocabulary)

| Layer | Name | Definition |
|---|---|---|
| feature / subsystem | **knowledge-fragment** | staging tier capturing conversation-born knowledge before main integration; slash command is the full name `knowledge-fragment` |
| file (one per session) | **fragment** | `knowledge/_fragments/<session_id>.md` — the mechanical envelope |
| record (one per decision) | **delta** (Knowledge Delta) | the per-decision capture unit inside a fragment; the join unit for consolidation |
| promotion | **consolidation** | a fragment's deltas → main `knowledge/` (+ wiki signal) |

## 4. Two axes (these are independent — do not conflate)

- **WHEN — capture timing.** Real-time incremental (a delta at each decision boundary) vs end-of-session retrospective (one batch at Stop). The cold-reader acceptance test (§8) **requires real-time** (§7); end-of-session drops the struggle that reveals problems.
- **WHERE — fan-out target.** `knowledge/` only, vs fan-out to `knowledge/` + `wiki/` (§5). A delta's `feeds` field carries this.

The earlier "fan-out (option A)" decision is the **WHERE** axis. The cold-reader ideal is mostly the **WHEN** axis + delta content quality. Keeping them separate is what makes the design tractable.

## 5. Pipeline + fan-out (WHERE)

A session produces a **flow** plus two kinds of knowledge: research/decision (→ `knowledge/`) and code-structure (→ `wiki/`). knowledge-fragment captures all of it as ordered deltas; consolidation fans out to **three targets**:

```
Conversation  (knowledge born)
   │  capture — real-time, cheap, high-recall (§7)
   ▼
fragment   knowledge/_fragments/<session_id>.md      ← STAGING (this tier)
   │  consolidation — at a maturity milestone, human-reviewed
   ├──────────────▶  journal/    (the flow, time-axis)
   ├──────────────▶  synthesis/  (research knowledge, topic-axis)
   └──────────────▶  wiki/       (code facts — SIGNAL only, see asymmetry)
```

**The asymmetry (load-bearing — "fan-out" means different things per target):**
- **→ knowledge/**: the delta IS ~the content. Consolidation distils deltas into `journal/`+`synthesis/`. Near-finished material distributed.
- **→ wiki/**: the delta is a **signal, not content**. Wiki pages are code-pinned (`path:symbol@sha`); their content must be re-derived from the code. A code-touch delta supplies **which pages are at risk + the semantic intent** — it does NOT write the wiki page. knowledge-fragment routes *attention + intent* to the wiki, not finished prose.

**Why the wiki signal earns its keep (it closes Chapter-9 #1; Chapter-9 = dogfood residue from a Windows-machine project's KB — cross-project pointer, not resolvable in this repo; pin to that project's source when next on that machine):** the wiki's own anti-rot (pins, `wiki-lint`, `change-impact`) catches **structural** rot (pin sha drift) but misses **semantic** rot — code unchanged-enough to stay lint-green while the wiki *prose* is now wrong. That is exactly the Chapter-9 #1 failure mode (structurally green, semantically drifted). A code-touch delta ("restructured parser to streaming; the old buffering invariant is gone") is the semantic signal that flags the prose, which `git diff` alone cannot.

**Low build cost — reuse, don't invent:** a code-touch delta puts a code pointer (`path:symbol`) in its `evidence`; consolidation feeds those pointers to the existing **`wiki-pages-for`** to compute the at-risk page set. No new wiki machinery — knowledge-fragment only *feeds* `wiki-pages-for`. (If the project has no `wiki/` — e.g. a config/setup repo like this one — the wiki arm is a **graceful no-op**: the `type:code` refs route nowhere; confirmed in the first consolidation dogfood.)

## 6. Decision D + the locked schema

**Decision D:** the **fragment file** is a mechanical *envelope* (per session — `session_id` is deterministic, hooks/agents can key on it); the real capture unit is the per-decision **delta** *inside* it, each carrying its own `unit_id`. The write boundary is mechanical (session); the consolidation boundary is semantic (unit). A session touching 3 units → 3 deltas with different `unit_id`s in one file; a unit spanning 10 sessions → deltas gathered across files by `unit_id`.

### Forward-stability is the whole game

What is catastrophic to change is the **persisted on-disk format**, because once fragments accumulate, a format change = transform every fragment. So the rule: **additive changes** (new optional field, new enum value, new file) are non-breaking; **structural changes** (rename/remove a field, change file identity, change the record delimiter, repurpose a field's meaning) are breaking. Everything below is locked NOW (the only cheap moment is before accumulation); everything deferred (§12) must remain reachable by *additive* change only.

### The locked schema points (write-safe before accumulation — Codex blocking review folded in)

1. **Delta identity = `delta_id` + `created_at` (Codex Critical — THE landmine).** Every delta carries a required durable id `delta_id: <session_id>-<NNN>` (`NNN` = zero-padded sequence within the fragment; globally unique because `session_id` is) and `created_at: <ISO-8601 UTC>`. The record header is exactly `## delta: <delta_id>`. A human slug is optional display only, **never identity**. *Without this, the deferred `supersedes`/`invalidated_by` linkage is not additive — it has nothing stable to reference. This is the must-fix-before-writing.*
2. **File identity = `session_id` alone, grammar-locked (Codex M1+M4).** `knowledge/_fragments/<session_id>.md`; `session_id` matches `[A-Za-z0-9._-]+` (no path separators). Date is a frontmatter field, never the filename (a later-day resume/compact must not split the file). Collision rule: a write to an existing fragment **appends**; a `session_id` match with mismatched envelope frontmatter **fails loudly** (never silently overwrite).
3. **`unit_id` stability + a canonicalization registry (Codex M1).** `unit_id` is an **immutable opaque slug**, assigned at first delta, never renamed (the display title lives in the consolidated page). A project-local **`knowledge/_fragments/units.yml`** holds `canonical_id` + `aliases`; capture MUST pick an existing id before coining a new one. Aliases make later repair **additive** (no retag of written deltas); genuine split/merge is retagged at consolidation. Without the registry, two sessions coin `staging-tier` vs `staging-tier-design` and `deltas-for` silently under-returns. `NEXT.md` unit sync deferred.
4. **Delta = fenced YAML block, with a locked split grammar (Codex M2+M3).** `## delta: <delta_id>` at column 0; a ```yaml fence immediately after; the body runs until the next **column-0** `## delta:` **outside balanced fences**. A details body must not contain a column-0 `## delta:`. Raw `key: value` after a header is rejected. This lets a simple parser (no markdown lib) split records reliably — the reason `wiki-pages-for` parses bounded frontmatter cleanly.
5. **Typed `evidence` records (Codex M2).** Each evidence item is `{type: code|transcript|command-output|source, ref: <string>}`. Only `type: code` items (`ref` in `wiki-pages-for` grammar: `path` / `path:symbol` / `path:line`, **no `@sha`**) are passed to `wiki-pages-for` for the wiki signal. Untyped prose cannot drive the fan-out; typing is the lock that makes machine routing possible. (`feeds` routes the delta; `evidence` typing routes the wiki refs.)
6. **`fragment_schema: <n>` on the envelope** — forward-compat insurance so a future breaking change is *detectable and automatable*, not grep-and-guess. (Data versioning, NOT a name version-suffix — distinct from `naming-no-version-suffixes`.)
7. **`feeds` routing field** on each delta (`knowledge` | `wiki`, list, default `knowledge`) — the WHERE axis (§5). Must exist from the start or every delta needs retagging to enable the fan-out.

> **Demoted from required (Codex m3 — over-lock):** `units_touched` on the envelope is **derived cache, non-authoritative** (it can drift from the deltas' actual `unit_id`s). Compute it on demand from the deltas; never treat a written value as truth.

### On-disk shape

Envelope frontmatter:
```yaml
fragment_schema: 1
session_id: <id>             # = filename stem; matches [A-Za-z0-9._-]+
date: <iso>                  # informational; NOT part of the filename
# units_touched: DERIVED CACHE ONLY (non-authoritative) — compute from deltas, never stored as truth
```
Each delta:
```md
## delta: <delta_id>               # delta_id = <session_id>-<NNN>; header MUST equal delta_id

​```yaml
delta_id: <session_id>-001         # durable identity (lock #1) — allocate via
                                   # `deltas-for --next-id <session_id>`, which counts
                                   # _archive/ too. Reading the live file alone breaks
                                   # lock #1: consolidation MOVES that file, so a session
                                   # that keeps capturing restarts at 001 and one id then
                                   # names two deltas (2026-08-02).
                                   # LEGACY EXCEPTION (2026-08-02): the prefix must
                                   # IDENTIFY the session, normally `<session_id>`
                                   # verbatim. One archived fragment predates that and
                                   # uses an abbreviated prefix (`a8a9fa5b-001..033`
                                   # under the full-UUID filename/envelope), so
                                   # --next-id continues under the FILE's own prefix
                                   # rather than mixing two spellings in one file —
                                   # internal resolvability is what lock #1 protects,
                                   # and a mixed file loses it.
created_at: <ISO-8601 UTC>         # ordering key (lock #1) — powers chronological deltas-for
unit_id: staging-tier-design       # immutable slug from units.yml (lock #3)
kind: decision                     # decision | finding | rejection | risk | open_question | constraint | followup
status: provisional                # provisional | accepted | superseded | consolidated | archived
                                   # TERMINAL (not debt): consolidated | archived | superseded
                                   # archived = reviewed, deliberately not page-worthy, kept raw
                                   # (2026-07-31: high-recall capture means "zero debt" = every
                                   #  delta has a disposition, NOT every delta became a page)
summary: <one line>
feeds: [knowledge]                 # knowledge | wiki ; default knowledge (lock #7)
evidence:                          # typed records (lock #5); type:code refs drive the wiki signal
  - {type: code, ref: "skills/x.py:Func"}
  - {type: transcript, ref: "..."}
​```

<freeform details body — reasoning, why-rejected, the cold-risk read; runs until the next "## delta:" header>
```

- **`details` is the body, not a schema field** (Codex m1). The locked metadata fields are `delta_id, created_at, unit_id, kind, status, summary, feeds, evidence`.
- **`kind` and `status` enums are append-only** (grow-only = additive). `risk` is in the initial set because the acceptance test (§8) makes "known weakness of the current design" first-class and queryable. `status: consolidated` marks a delta as promoted so the debt count / `deltas-for` can skip it.
- **Parser contract (locked):** lenient — tolerate missing optional keys, preserve unknown keys. This is what guarantees deferred fields (§12) stay additive.
- **Value grammar (locked — the hand-parser is stdlib-only, a YAML *subset*; Codex T1 review):** scalar values are **single-line** (multi-line content goes in the body, never a folded `>`/`|` scalar); `evidence` is a **block-list** of `- {type:…, ref:…}` items (inline `[{…}]` is warned, not parsed); trailing ` # comment` on an unquoted scalar is stripped; **leading-`_` field names are reserved** for parser internals. These keep the hand-parser additive-safe for every real (non-`_`, scalar / block-list) field. `deltas-for` **WARNS on drift** — inline-list evidence, reserved-`_` keys, duplicate `delta_id` (within / across files) — rather than failing silently. The migration-critical claim (a future scalar field / new `kind` value never forces migrating accumulated deltas) is proven by `skills/knowledge-fragment/scripts/test_deltas_for.py`. PyYAML was considered and **rejected** (adds a dependency against the stdlib-only convention; changes type coercion).

### Additive provenance instruments (2026-06-10 — first real use of the additive path)

Two **optional** fields, added with no schema bump (the lenient-parser lock above is what makes this safe; both follow the locked value grammar):

- **`informed_by: [refs]`** (delta) — the **orientation set**: the knowledge pages/docs the unit was worked WITH, recorded on the unit's first delta at orientation time. Free-form refs (KB page stem preferred, repo path ok) — a wikilink seed for consolidation, **never a foreign key** (pages move; no lint enforcement).
- **`parent: <canonical_id>`** (units.yml entry) — the containing feature/unit, recorded at registration time while the hierarchy is still in context. Never traversed (no cycle risk); `deltas-for` warns on undeclared / self / alias-valued parents, and `--draft` canonicalizes an alias value before the page lookup.

**Rationale (instrument-first, the signal-layer doctrine applied to this spec):** the unit↔knowledge relationship exists in the agent's context at work time but evaporates with the session; at consolidation the distiller must *reconstruct* the page's `[[wikilinks]]`, and reconstruction failure is **silent** — kb-lint catches broken links, not absent ones, so a "wait until reconstruction visibly fails" trigger can never fire. These fields record the ground truth at knowing-time, which is what makes the failure measurable at all: **fill-rate** (units whose first delta carries `informed_by`) and **link drift** (distilled `[[links]]` vs the recorded candidates). Both surface as **wikilink candidates** in `deltas-for --capture-brief` and `consolidate --draft` — suggestion only; auto-linking stays a non-goal. They are also the first shipped slice of the roadmap's graph/index identity-contract direction (stable unit↔page edges); the contract doc itself stays deferred.

PreToolUse "first code-write of a unit" is **not mechanically implementable** (hooks are stateless per invocation; a unit is a semantic boundary spanning sessions) — Codex C1. So the trigger is not a hook watching code. It is a **discipline**, made cheap by two moves:

- **Move 1 — anchor capture to discrete *decision boundaries*, not continuous vigilance.** A decision crystallizing is already marked in the conversation: **user approval/selection points** ("go" / picking an option) and the **conversation→code boundary** (about to implement). Drop a delta there — bounded (a few per session), at a natural pause. Not "notice every inflection" (that rots like any vigilance rule); **"file a delta right after a decision is approved."**
- **Move 2 — harvest, don't author.** The evaluative content the acceptance test needs (cold-risk reads, why-rejected, open risks) is **already produced** by the design-first ritual. A delta = *filing the conclusion just reached*, not new analysis. Marginal cost ≈ 0 — this dissolves the friction at the root.

**Stop = backstop only.** A Stop command hook (matcher `""`, reusing the `stop-handoff-gate.sh` `session_id` sentinel + `stop_hook_active` guard, one nudge/session, fail-open) catches "real work happened, zero deltas filed." It is the net, not the primary capture — capturing at Stop means reconstructing from memory/transcript, which loses recall (Codex C1). **The Stop hook is deferred out of the first build** (§12); the first build proves the discipline + format by hand.

**Residual risk (cold read):** anchoring to approval boundaries can miss **silently-settled decisions** (agent-internal, no explicit approval). The conversation→code boundary + Stop backstop catch most; 100% is not claimed — **dogfood decides** whether the gap matters.

### 7a. Why no hook or auto-scrape can *replace* the discipline (capture-axis decomposition)

Capture = **Trigger × Selection × Extraction**, and the three axes differ in whether they mechanize — conflating them is what makes "just use a hook" sound plausible:
- **Trigger (when to attempt)** — mechanizable for *mechanical* events (a tool ran, a prompt arrived, the turn stopped) via a command hook; NOT for the *semantic* event "a decision just crystallized" (it is in no event payload). So a hook's only honest role is a **deterministic nudge** (e.g. Stop `additionalContext`: "decisions settled, zero deltas — file them?"). It reduces *forgetting*, not *friction*; the write is still the in-loop model.
- **Selection (what to keep)** — irreducibly semantic. The rubric (keep = "changes what a cold reader would DO"; the 7 `kind`s) is judgment, not a threshold, with two logged failure modes (over-capture §9.8, under-capture §9.7). It cannot be reduced to a non-semantic algorithm without losing the discrimination that gives it value. **Mechanizable only as *scaffolding***: deterministic **anchors** (approval / ExitPlanMode / commit / unit-boundary → a "consider capturing" nudge) and **guards** (over-capture rate-limit/dedupe, a `units.yml` coining lint). Neither replaces the keep/drop call.
- **Extraction (write the delta)** — needs a model; cheapest by the **in-loop agent** already present (≈0 marginal cost). A model-in-hook (`claude -p` over the transcript) *can* fully automate capture but is blind to the in-flight "which decision was load-bearing" judgment and pays a model call + latency every turn → legitimate as a **recall audit net**, wrong as **primary**. An auto-scrape skill is the same end-of-session summarizer already rejected (§4) — fine as audit, never primary.

**⇒ The capture architecture is a HYBRID, in priority:** (1) in-loop agent = primary (semantic trigger + selection + extraction at ≈0 cost; the open bet is whether the *discipline* survives real work); (2) hook-nudge = trigger assist; (3) guards/lint = selection assist; (4) optional transcript scrape = recall audit. The reframe that justifies it: the friction is not the *write* (harvest makes it cheap) — it is the **vigilance to notice the boundary**, which is exactly what a hook-nudge offloads.

**So "is the selection algorithm complete?" — no, and it was never going to be a closed algorithm.** What is completable is the scaffolding above (deferred, §12); selection quality is only measurable empirically, and §8 passed under *ideal batch* conditions (the tested fragment was authored as a batch, not captured live), so real-time low-friction capture still has **N=0** data. The next verification is the *process*, not the output.

## 8. Acceptance test (the verify: criterion for the whole feature)

> A cold session that knows nothing, given the relevant KB + **the knowledge-fragment KF alone**, can identify the feature's **improvement points and problems**.

This is `<knowledge_fidelity>` reconstructability applied to an in-flight feature, and it is the success definition. It demands: (1) real-time capture (§7) so the trajectory survives; (2) deltas that carry *evaluative state* (weaknesses/why), not just conclusions; (3) problems queryable — `deltas-for <unit> --kind risk,open_question,followup` returns the deltas so **typed**. That is a field selection, not a reading of the bodies; §8's bar is what a cold reader can name, and the query is a way in, not a measurement of it.

**How it is run (first dogfood):** capture *this design conversation's* deltas, then spawn a cold sub-agent, give it the KB + this feature's KF only, ask "what are knowledge-fragment's improvement points / problems?" — **pass = it answers from KF alone.** Fail ⇒ delta quality or the real-time discipline is insufficient. (Goal-driven `verify:` per `<coding_principles>`.)

**Standing proxy (2026-08-02; claim corrected 2026-08-05).** The cold-reader run above is manual and has happened once, so §7a's warning stood: the *process* was never verified and drifted unobserved. `deltas-for --debt` now reports **kind-field composition** — the share of outstanding deltas whose `kind` is one of `risk|open_question|followup` — per unit and overall, and flags units with no delta so typed; `consolidate --draft` prints the same count before a unit becomes a permanent page. This does not replace the cold-reader test, and it is **not that test's precondition either**: the code itself records that a unit with zero so-typed deltas may still have captured every risk it met, and that zero can be legitimate. It is a **field-level queryability signal** — cheap, continuous, and capable only of prompting the question the cold-reader test actually answers. What was missing was any continuous signal at all, not this one's authority.

> It is a **metadata** proxy and nothing more: it counts the `kind` field and never opens a delta body. It was originally described here with two labels that named the delta *content* — one about how evaluative the deltas were, one about units said to have recorded conclusions only — both claims about prose, derived from a field. Measured 2026-08-05: a unit whose bodies carried a rejected design, a shipped-unresolved risk and a platform coverage limit scored 2 of 19, because those deltas were typed `finding` / `rejection` / `constraint`. Teaching the counter to read bodies was rejected — that puts an inference-shaped heuristic inside the automation layer — so the numbers stayed and the claims shrank. **The measurement that motivated it:** across all 227 deltas ever written, problem kinds were **10.6%** and `rejection` was **2** — i.e. the tier had become a log of what was settled, while every mechanical gate (parse, lint, 81% consolidation into 23 pages) stayed green. The chain purpose → rubric → code had a stated purpose and a capable query with nothing joining them.

## 9. Failure modes + mitigations

1. **Mixed-session ambiguity** — `unit_id` per-delta, never only per-file. (Resolved by D.)
2. **Contradictory/revised deltas** — conversation revises itself. `status` is mandatory; mark supersession (`superseded`), never silently overwrite. (`supersedes`/`invalidated_by` linkage is deferred-additive.)
3. **Garbage recall** — high recall → noise. `kind` enum mandatory (no freeform blobs); preferences / transient task-state go to `workflow/` or `memory/`, not here.
4. **Hallucinated knowledge** — agent persists a guess as fact. **Provenance required:** a delta with no human statement / command output / source / code pointer **cannot be `accepted`** (stays `provisional`). Direct guard on the "stale context → input → output → trusted memory" drift loop.
5. **"Record instead of decide"** (a *green ≠ correct* cousin) — agent dumps a delta to clear the nudge instead of resolving. A delta existing ≠ a decision made well. `kind: open_question` lets it honestly record "still open"; the human consolidation gate filters half-baked deltas.
6. **Unit rename/split/merge drift** — handled by lock #2 (immutable slug + retag-at-consolidation).
7. **Missed silent decisions** (§7 residual) — approval-anchored capture can skip agent-internal decisions; conversation→code boundary + Stop backstop reduce, dogfood measures.
8. **Over-capture** — every turn becomes a delta. Mitigation: capture only what *changes what a cold reader would do* (decision/finding/rejection/risk/constraint that affects code or future decisions); the rest is conversation, not KF.

## 10. Honest risks (load-bearing — read before building)

- **🔴 Consolidation is the single point of failure.** The whole 2-stage value depends on consolidation *actually happening*. If it doesn't, `_fragments/` becomes shadow documentation that drifts from main — **strictly worse than no tier.** Mitigations: (a) make consolidation *cheap* — `consolidate.py <dir> <unit> --draft` pre-fills a reviewable draft (deltas grouped + SCHEMA-routed target + manifest); the agent distills, the user approves, `--apply` does the bookkeeping (edit, not author); (b) tie it to a milestone the user already recognizes (alpha/beta); (c) a **consolidation-debt signal** counting *unconsolidated deltas* (+ pending drafts) — surfaced in `/doctor` (age×kind weighting deferred).
- **🟡 Real-time-capture friction is a second SPOF.** If filing deltas mid-conversation is heavy, it won't happen — same death as today's policy nudge, one layer up. §7's two moves (boundary-anchored + harvest-not-author) are the mitigation; whether they suffice is **the** dogfood question.
- **Currency ≠ correctness.** This tier makes knowledge *current* and *provenanced*; it does not verify it is *true*. The human at consolidation is the correctness check. Under future autonomy, that promotion gate is where semantic verification attaches — the staging→main boundary is the trust boundary (`harness-autonomy-roadmap` — memory pointer, machine-local, not in this repo).
- **🟡 Over-build.** The harness fitness eval concluded the binding constraint is *use > build*. The Hibiki pain is real evidence the tier is needed, but "deltas get used and consolidated" is unvalidated. → **Build the smallest dogfoodable thing, capture this conversation, run §8, then add machinery.** Do NOT build the full spec up front.

## 11. Mechanization split (tier model)

| Step | Who | Tier |
|---|---|---|
| fragment file exists | **lazy — agent creates on first delta write** (no envelope hook; Codex M1) | A — deterministic once triggered |
| Capture deltas (real-time, §7) | agent, boundary-anchored + harvest | B — judgment |
| Nudge if work but zero deltas | Stop hook (deferred; reuse `stop-handoff-gate`) | A — deterministic |
| Decide a delta is worth persisting | agent, strict `kind`/provenance | B — judgment |
| Validate delta block well-formed | **`deltas-for` warns on malformed** (NOT `kb-lint`; Codex M3) | A — deterministic |
| Maturity → consolidate | human declares / debt surfaces | C / B |
| Consolidation draft (gather unit deltas + SCHEMA-routed target + `consolidates` manifest) | `consolidate.py --draft` (read-only; draft to `_fragments/_drafts/`) | A |
| Distil draft → full-fidelity page; user approves | agent edits the draft in place (banner removed = distilled); human review | B + human |
| Apply (promote page w/ `consolidates:` provenance, flip statuses, archive) | `consolidate.py --apply` (banner-gated; refuses on any inconsistency) | A |
| Archive the fragment file — only when every delta in it (across all units) has a TERMINAL disposition (`consolidated` \| `archived` \| `superseded`); otherwise the file stays live | `--apply` does this | A |
| Consolidation-debt count | `/doctor` | A |
| Multi-unit batch promotion (one create + N update-existing carriers into ONE target page) with raw-byte/status witnesses around each apply | `batch-promote.py --check/--transition/--init/--execute` (wraps `consolidate.py --apply` per unit; fourth build, §12) | A |

The skeleton (create / query / validate / archive / count) mechanizes cleanly; only the *content* (capture, consolidate) is judgment — which is why a fragment lifecycle mechanizes *better* than raw "knowledge update."

## 12. First build (scope) vs deferred

**Build now — no hook, smallest dogfoodable set (Codex m2):**
- `knowledge/_fragments/` convention + **lazy fragment creation** on first delta (keyed by `session_id`).
- the **fenced-YAML delta format** (envelope `fragment_schema`+`session_id`+`date`; delta fields `delta_id, created_at, unit_id, kind, status, summary, feeds, evidence` + body; typed `evidence`) + the **`knowledge/_fragments/units.yml`** unit registry (canonical id + aliases).
- **`deltas-for <unit_id>`** — on-demand query over `_fragments/*.md` (NOT a persistent index; mirrors `wiki-pages-for`), with **(a) malformed-block warnings**, **(b) `--capture-brief`** (grouped brief for `/research-kb capture` — the consolidation adapter, Codex C2), **(c) `--kind <list>`** filter (powers the §8 problem query), **(d) chronological output by `created_at`** (the §8 trajectory needs order — Codex m2), resolving `units.yml` aliases so a query never under-returns.
- **`kb-lint` exclusion** for `_fragments/` — prune at the `os.walk` collection loop (`kb-lint.py:93-97`, Codex M4); path-prefix skip is sufficient.
- the slash command **`knowledge-fragment`** (full name) wrapping capture + `deltas-for`.

**Second build (2026-06-10) — consolidation draft/apply (`consolidate.py`; Codex roadmap adopted items):** the WRITE side of the tier, split at a hard boundary. `--draft` is read-only w.r.t. fragments and curated `knowledge/`: it gathers the unit's unconsolidated deltas, discovers the target KB's **earned slices from disk** (the SCHEMA-driven routing this list previously deferred — never assumes `journal/`+`synthesis/`; the harness-meta KB is `comparisons/`-only), and writes a reviewable draft to `_fragments/_drafts/<unit>.md` (kb-lint-excluded; `deltas-for` never scans it for deltas) whose frontmatter is the apply contract (`target`, `apply_mode: create|update-existing`, `consolidates` manifest). The agent distills the draft in place and must remove the `> DRAFT:` banner — `--apply` refuses while it is present (a mechanical proof-of-distillation gate), and refuses on any inconsistency — manifest drift (unknown / duplicate / foreign-unit ids — duplicates are counted across active fragments **and** `_archive/`, because an id living in both names two different deltas and status agreement between the copies is not identity; the one exempt overlap is a prior append proven by content — proven over **parsed top-level records**, never a raw substring, since a fenced code sample in the archive satisfies a text match while its actual records say otherwise; **archive trust (register item 9, closed):** the check reasons from what an archive parses to, which is sound because apply GATES the archive on damage first — a file whose parse warns it may HIDE records (RECORD-LOSS: unbalanced body fence, the once-silent unterminated metadata fence, an unreadable file) refuses the run BY NAME, and the only escape is a human, sha-bound acknowledgment in `_fragments/quarantine.json`, which every consumer (apply, `--next-id`, `--debt`, the query) then PRINTS as a standing `QUARANTINE` line; a damaged same-session twin is refused in the preflight, never appended into (an append lands at EOF where an unclosed fence absorbs records on arrival), and a damaged twin proves NOTHING — round 3 falsified the presence-proof tolerance (an unterminated metadata fence lets `parse_meta` absorb later yaml into the first record, SYNTHESIZING the equality the proof requires), so `fragment_already_appended` refuses a damaged dest outright and recovery is repairing the twin; relevance-scoping selectors stay rejected: the parse warnings are the one signal the corruption produces rather than hides), unconfined or conflicting targets (paths confined to earned slices under `knowledge/`), missing slice, archive collision — all **preflighted**, so a refusal mutates nothing. On apply: `create` promotes the draft to the target keeping **`consolidates:` as provenance** (claim→delta traceability — the cheap half of the roadmap's audit-trail item); statuses flip to `consolidated` with the old `provisional`/`superseded` value preserved as a parse-invisible trailing comment (history survives the flip); the flip is then VERIFIED by re-parsing the fragment -- `flip_statuses` keeps only a POSITION scan (the reader's `parse_meta` decides identity, coherence and status — its second-grammar semantics were retired after the differential harness `test_two_grammars.py` found five live divergences) and still cannot witness its own effect, so exit 0 means the authoritative parser reads every manifest delta as `consolidated`, not that the writer reported it did -- verified per-file after each flip AND once manifest-wide (active fragments + `_archive/`, conflicting copies counted as unverified) immediately before the draft, the only recovery anchor, is deleted, because ids the pre-scan already read as consolidated and ids recovered from `_archive/` never pass through the flip at all (the tool takes NO LOCK and assumes a single writer, so under a concurrent writer that guarantee reads "verified immediately before the draft was deleted", not "true at exit" -- a lock was REJECTED, not deferred: the dominant writer of a fragment is an agent appending deltas through an editor, which cannot take one, so a lock in `consolidate.py` would exclude only `consolidate.py`, the one writer already serial); and a terminal disposition is refused against the snapshot the flip is about to rewrite, not only in the stale pre-scan -- narrowing that window, NOT closing it: the read and the write are still separate steps, so a writer that shelves a delta between them is overwritten from the stale snapshot (Codex Mode 3 round 3, Major -- the earlier "the window carries no risk" here was false);  fully-DISPOSED fragment files move to `_archive/`; the remaining semantic steps (index entry, log line, `wiki-pages-for` refresh, kb-lint) are printed, not automated. `--debt` now also surfaces pending drafts. Proven by `test_consolidate.py` (originally 62 assertions: read-only draft, refusal-mutates-nothing snapshots, path confinement, both apply modes, locked-grammar status flips, archive rules); a same-day Codex Mode-3 review (1 Critical: path confinement; 3 Major: archive preflight, manifest unit/dup validation, `flip_statuses` fence-depth parity with the locked split grammar) is folded in. Deliberately deferred from that review: a draft→apply content hash (the stale-draft window) — if fragments changed after drafting, re-run `--draft --force` and re-review instead. **Cold-eval fixes (2026-06-10, delta `a8a9fa5b-022`):** `update-existing` previously recorded provenance *nowhere* (the draft — the manifest's only home — is deleted at apply; `comparisons/knowledge-fragment.md`'s 25 delta ids were backfilled from `_archive/`); it now merges the manifest into the target page's `consolidates:`, refusing pre-mutation when the target frontmatter can't carry it. And the one legitimate archive collision — a session that continued after its fragment file was archived (same `session_id`, disjoint delta ids) — now APPENDS to the existing archive file instead of permanently refusing; every other collision still refuses. `test_consolidate.py` grew again. NO COUNT IS RECORDED HERE: run the suite, which prints its own. Three figures have gone stale in this sentence alone (80, then 140/109, then 149), each recounted only because someone happened to look -- which is the same rule NEXT.md states for its own numbers (3B audit 2026-09-02).

**Fourth build (2026-08-31) — witnessed batch promotion (`batch-promote.py`):** born from the resonance `library-core-consolidation-v1` review sequence, where eleven external rounds proved that PROSE acting as the executable byte contract for seven single-unit applies is the unstable layer (R11-N-M1: a create transform specified as text plus an asserted raw-byte equality reads a healthy create as corruption once a cold Windows runner materializes the expectation through newline translation). The executor runs one create draft plus N `update-existing` carriers into ONE target page, wrapping `consolidate.py --apply` per unit (never reimplementing it) and owning only the surrounding witnesses, all computed over raw bytes: expected create output = the shared `create_text_from_draft()` `.encode("utf-8")` compared byte-for-byte; an integrity digest over the target minus only its `consolidates:` block, invariant across every carrier; exact manifest growth against the reviewed `--init` baseline; a full status map over every delta in the derived source fragment files (per record: unit_id, status, and a content fingerprint over every other parsed field including the body), whose changed set must equal exactly the applying unit's ids; a per-source projection witness — `--init` records the sha of the bytes the authoritative flip transform itself would produce once every batch id is flipped, and at every later point (cross-process included) projecting the current bytes through the still-unflipped ids must reproduce it, so any byte not written by an approved flip (envelope fields, whitespace, bodies, metadata, bytes inside a status line beyond its parsed value) halts the batch; and an in-process positional byte witness (line count preserved; every differing line a bounded status flip). Batch spec and state are JSON (no third hand-parsed YAML grammar); `--init` is the one declared state mutation outside applies, so every refusal elsewhere mutates nothing; resume is idempotent with named-verdict stops (expected post-state + missing draft = verify and record; present transitioned draft = idempotent rerun, its own ids tolerated mid-flip; anything else = stop for an explicit repair decision). Tool identity: `PINNED` sha256 of `consolidate.py` + `deltas-for.py` embedded in the executor, verified before those modules load and before every apply, with the suite recomputing the pins so an unreviewed sibling edit turns the repo red; `.gitattributes` forces `eol=lf` on these scripts so the pinned worktree bytes are identical on both machines. The completion witness (target sha, integrity digest, manifest, per-source sha/location, deleted drafts; the per-source projection expectations live in the state's `final_expected` map) is persisted in state and re-verified field-by-field read-only by `--check`, which reports COMPLETE only after the whole-batch proof passes and never before `--execute` has recorded the witness. No Git operations and no auto-rollback live in the tool — recovery and commits remain outer-plan choreography under user approval, same single-writer/no-lock charter as `consolidate.py` (windows narrowed, never claimed closed — the check-then-act read→write gap is the one remaining unwitnessed interval, as for every consumer of this tier). Proven by `test_batch_promote.py` (every witness carries an in-suite tamper red); external Mode 3 sequence in `workflow/reviews/batch-promotion-executor-v1.md`.

**Deferred until the first build shows the need (reachable by additive change only):**
- the **Stop backstop hook**; `supersedes`/`invalidated_by` linkage; retag tooling; weighted/aged debt metric; persistent delta index; `NEXT.md` unit_id sync; the overhaul-specific "refresh-before-rewrite" blocking gate.
- the **full apply audit trail** (a `knowledge/_consolidations/` ledger: reviewer, approver, timestamp, commit per promotion — Codex roadmap item) — the promoted page's `consolidates:` frontmatter already covers claim→delta traceability; the ledger waits for a real need. *(SCHEMA-driven consolidation target moved from this list to the second build, above.)*
- **capture scaffolding** (the mechanizable half of §7a) — deterministic anchors (approval / ExitPlanMode / commit / unit-boundary nudge) + over-capture guards (rate-limit / unit+kind dedupe) + a `units.yml` coining lint. None of these *select*; they bound the failure modes around the judgment.
- **decision-scope queryability** (Codex T3 cold-reader meta-finding) — "is this permanent policy / a temporary workaround / a hypothesis-under-test" is only partially encoded today (`constraint`≈policy, `open_question`≈hypothesis, `status: provisional`≈under-test), and for a `finding`-typed workaround it lives only in body prose. Make it first-class/queryable via a new optional `scope` field or a new `kind` value — additive (T1-proven migration-free), so deferred until a real query needs it.

## 13. Composition with the existing harness

- **Location:** `knowledge/_fragments/` (the `_` prefix matches the `_archive/` meta convention — pre-integration, excluded from the curated graph). Consolidated fragments → `knowledge/_fragments/_archive/`.
- **vs `NEXT.md`:** `NEXT.md` is the single-writer *state pointer* (where I am / next action at unit level; when an active plan file exists, NEXT names the unit + plan and the plan's `Handoff` owns the in-unit action — coding_principles plan-file rule). A delta is *knowledge content* (what was decided / learned). Distinct layers; `NEXT.md` may reference a delta, never duplicate it.
- **vs `wiki/`:** `wiki/` (how code works) stays **commit-driven** (pins, lint, change-impact). knowledge-fragment **feeds it a signal** at consolidation (§5) — it does not take over wiki authorship. Two layers; the fragment adds the *semantic* staleness signal the commit-driven path misses.
- **Graph hygiene:** deltas do not `[[wikilink]]` into the main knowledge graph (pre-integration); cross-refs use plain paths. `kb-lint` skips `_fragments/` for orphan/index/link checks.

## 14. Status / next

**Done this session** (Claude Opus 4.8 + Codex gpt-5.5): Codex blocking review folded in (1 Critical delta-identity landmine + 4 Major + 1 over-lock); spec renamed+revised, committed+pushed; first build (§12 — `deltas-for` +brief/+kind/+warn/+chrono, `SKILL.md`, `kb-lint` exclusion, `units.yml`, `knowledge-fragment` command); **§8 acceptance PASS** (a cold sub-agent surfaced the feature's own problems from the KF alone); **first consolidation PASS** (12 deltas → a `comparisons/` decision record → archived; the 🔴 SPOF loop closed once); the **capture-axis architecture** (§7a) added after the hook/scrape/selection probe.

**Pre-validation (T1+T3, Codex-reviewed):** T1 = `skills/knowledge-fragment/scripts/test_deltas_for.py` proves the migration-critical additive-stability + parser fail-safety; the Codex T1 review found capture-time robustness gaps (the hand-parser is a YAML subset), hardened (reserve-`_` keys; warn on inline-evidence / duplicate `delta_id` / stripped trailing comments). T3 = a replay backtest of 3 diverse past sessions (Hibiki / Tidal / freshness) run through an **independent Codex cold-reader §8** — passed; the 7-kind taxonomy generalizes across domains; one additive gap (decision-scope: policy vs workaround vs hypothesis) deferred.

**Proven:** tooling + mechanical loop; **schema additive-stability** (T1, the migration-critical layer); **taxonomy generalization across domains** (T3). **NOT proven (both behavioral, cheap-to-change, NO migration cost):** real-time low-friction capture (N=0 *live* — the §8 fragments were authored, not captured live); *habitual / unprompted* consolidation (every run so far was user-prompted — `demonstrated-once-when-prompted ≠ solved`).

**Second build done 2026-06-10:** `consolidate.py` draft/apply + SCHEMA-driven target routing (§12) — the WRITE side scripted, the draft→review→apply boundary locked, `--debt` extended with pending drafts. First live-captured unit (`harness-signal-layer-fix`) drafted the same day.

**Third build done 2026-06-10:** additive provenance instruments — `informed_by` (delta) + `parent` (units.yml), surfaced as wikilink candidates in `--capture-brief` and `--draft` (§6). Adopted *before* measurement by deliberate reversal of the defer-until-need default: reconstruction failure is silent, so the ground truth must exist for the link-drift measure to be measurable at all (instrument ≠ automation; the user's argument, accepted). Codex advisory review 0C/1M/2m, all folded in: no `[[..]]` syntax in generated draft guidance (the candidates section is not banner-gated, so a literal link could survive distillation), parent alias values warned + canonicalized before the page lookup, parent candidate emitted as a bare token with context on a separate line. Both suites have grown since; their current sizes are what they print when run, and are deliberately not copied here (the figure recorded at that build, 79/80, was already two builds behind when it was corrected in 2026-08).

**Next, in order:**
1. **Real-use measurement** (the verification §7a names — *not* more design): capture a real working unit **live** and measure over/under-capture + whether consolidation happens unprompted. (Capture half measured 2026-06-10 — live capture worked, delta a8a9fa5b-007; *unprompted consolidation* still N=0. Third build adds two measurables: `informed_by` fill-rate + link drift at distillation; first link-drift data point recorded same day in `comparisons/provenance-fields.md` — candidates are a floor not a ceiling; miss classes = pages born after capture, alias-stem parents. Second point (kfd second wave, same day): pre-instrument deltas carry 0 candidates by construction — both final links were pages born after capture, confirming that miss class; and the fourth scripted `--apply` was again user-prompted, so unprompted-consolidation N stays 0.)
2. ~~First **`--apply` dogfood**: distill a drafted unit, user-review, apply~~ — **done 2026-06-10**: `harness-signal-layer-fix` (8 deltas) promoted to `comparisons/`; the user gate fired for real (a genuine include/exclude call on provisional 007 — the draft's PROVISIONAL section earned its place); flip preserved history (`# was: provisional`), the mixed-unit file correctly stayed live (7 deltas remain), debt 27→19, kb-lint clean on the promoted page.
3. Build the deferred **capture scaffolding** (§12 — anchors + guards + `units.yml` lint) only if step 1 shows the discipline needs it.
4. ~~Add the CLAUDE.md `project_wiki_layer` `_fragments/` routing clause~~ — shipped 2026-06-10.
