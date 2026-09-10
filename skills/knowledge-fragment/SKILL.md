---
name: knowledge-fragment
description: "Capture conversation-born knowledge in real time as per-decision \"delta\" records into a session fragment (`project/knowledge/_fragments/session-id.md`), before it crystallizes into code — the write-back / staging half of the knowledge loop (the `_fragments/` staging tier is the disambiguator vs research-kb, which captures already-*resolved* findings straight into curated `knowledge/`). Use to file a delta when a decision/finding/risk lands, to query deltas for a unit (`deltas-for`), or to consolidate a unit's deltas into the curated `knowledge/` (+ a wiki refresh signal). Gates on a project having `knowledge/`. Trigger words: \"knowledge-fragment\", \"capture delta\", \"fragment 캡처\", \"델타 기록\", \"지식 파편\"."
---

# knowledge-fragment

Staging tier that captures the knowledge born in a conversation **as it forms** — per
session, per decision — so it is retained before (and during) the code that crystallizes
from it. The cheap, high-recall capture half; curation happens later at **consolidation**.

Full design, locked on-disk schema and rationale: `<harness-repo>/specs/knowledge-fragment.md`. Read `source_repo` from `CODEX_HOME/dev-setup-codex-community-state.json` (default CODEX_HOME is `~/.codex`). Use that source directory as `<repo>`. Without state, locate the extracted community directory supplied by the user; never guess a personal repository. Read the spec before non-trivial work; it is the authority. Resolve installed skill scripts from `CODEX_HOME/skills` when set, otherwise `~/.codex/skills`; examples below use the default.

**Keystone:** knowledge precedes code (born in dialogue → crystallizes into code at the end). So capture at the **conversation→code boundary**, not after a `git diff`.

## Boundary — what goes here vs not

| | `knowledge/_fragments/` (this) | `knowledge/` curated | `NEXT.md` | `wiki/` |
|---|---|---|---|---|
| holds | raw per-decision deltas (pre-integration) | distilled rationale, research, and findings | the single state pointer | code-derived mechanics and contracts |
| trigger | conversation decision boundary | consolidation (reviewed) | each unit handoff | validated code change |

Deltas are **transient** (consolidated, then archived). They do NOT `[[wikilink]]` into the curated graph; `kb-lint` skips `_fragments/`.

## Operation 1 — capture a delta (the part that makes or breaks this)

**When (real-time discipline, spec §7):** file a delta right after a decision *crystallizes* — most reliably at a **user approval / option pick** ("go" / chosen option) or the **about-to-implement** boundary. A few per session, at natural pauses. NOT every turn (over-capture), NOT only at session end (loses the trajectory).

**How (harvest, don't author):** a delta files the conclusion *just reached* — the cold-risk read, why-rejected, the open risk that design-first already produced. Near-zero extra work; you are not writing new analysis.

**What earns a delta:** something that changes what a cold reader would *do* — a `decision`, `finding`, `rejection` (with why), `risk`, `open_question`, `constraint`, `followup`. Preferences / transient task-state go to `memory/` or `workflow/`, not here.

**The kinds are NOT equals — capture is aimed at the acceptance test (spec §8).** The bar is *"a cold session, given this unit's fragments alone, can name the unit's improvement points and problems."* Against that bar the kinds split in two:

- `decision` · `finding` · `constraint` — what got **settled**. Necessary, and the easy half: they are what you have just finished thinking, so they write themselves.
- `rejection` · `risk` · `open_question` · `followup` — what is still **weak, open, or deliberately dropped**. This is the half §8 actually asks for, and the half that evaporates: at the moment of capture it feels like the part you did *not* accomplish, so it goes unwritten.

So the working question is not only "what changed?" but **"what is still wrong, unresolved, or rejected — and why?"** Capture those items when they actually exist. Do not invent a rejection, risk, or open question to satisfy a kind count or make a unit look thorough. Composition reports are review signals, not quotas.

**Steps:**
1. Pick the `unit_id` from `knowledge/_fragments/units.yml` (an immutable slug + aliases). If the unit is new, add a `canonical_id` there first — **never coin a fresh slug for an existing unit** (that silently splits `deltas-for`). Register the hierarchy while you still know it: a new unit under a known feature/unit gets `parent: <canonical_id>`.
2. Append a delta to `knowledge/_fragments/<session_id>.md` (create the file lazily on the first delta — envelope frontmatter below). `<session_id>` is the conversation's id; the filename is the id alone (date is a field, never in the filename).
2b. **Get the delta id from the tool, never by eyeballing the live file:**
   `python ~/.codex/skills/knowledge-fragment/scripts/deltas-for.py <knowledge-dir> --next-id <session_id>`
   It prints the whole `<prefix>-NNN` — paste it verbatim into both the `## delta:` header and `delta_id:`. It counts `_archive/` as well as the live file, which is the entire point: consolidation **moves** the live file to `_archive/`, so a session that keeps capturing afterwards sees no live file and restarts at **001**. That makes one id name two different deltas, turns every `consolidates:` reference in the reused range ambiguous, and leaves `consolidate.py`'s `same_session_disjoint` — written for exactly a post-archive continuation — unable to ever fire, since renumbering guarantees the id sets overlap.
3. Provenance is required: a delta with no human statement / command output / source / code pointer in `evidence` stays `status: provisional` (cannot be `accepted`).
4. On the unit's **first** delta, fill `informed_by: [refs]` with the orientation set — the knowledge pages/docs loaded for this unit (KB page stem preferred, repo path ok). It seeds the page's `[[wikilinks]]` at consolidation; reconstructing them later fails silently (spec §6).

**Locked format (spec §6 — do not improvise; the parser depends on it):**

Envelope (once per file):
```yaml
---
fragment_schema: 1
session_id: <id>
date: <iso>
---
```
Each delta — header MUST equal `delta_id`, a ```yaml block immediately follows, body runs until the next column-0 `## delta:`:
```
## delta: <session_id>-001

​```yaml
delta_id: <session_id>-001
created_at: <ISO-8601 UTC>
unit_id: <slug from units.yml>
kind: decision        # decision|finding|rejection|risk|open_question|constraint|followup
status: provisional   # provisional|accepted|superseded|consolidated|archived
summary: <one line>
feeds: [knowledge]    # add wiki when the delta also names code structure
informed_by: [<kb-page-stem>, specs/x.md]   # optional — unit's FIRST delta: the orientation set
evidence:
  - {type: transcript, ref: "<what was said / decided>"}
  - {type: code, ref: "path/to/file.py:Symbol"}   # type:code drives the wiki signal
​```

<freeform body: reasoning, why-rejected, the cold-risk read. Do NOT put a column-0
"## delta:" line here except inside a fenced code block.>
```

## Operation 2 — query (`deltas-for`)

```
python ~/.codex/skills/knowledge-fragment/scripts/deltas-for.py <knowledge-dir> <unit_id> [flags]
```
- default: chronological listing of the unit's deltas (aliases resolved).
- `--kind=risk,open_question` → the deltas **typed** as problems. This selects a FIELD; the §8 acceptance test asks what a cold reader can name from the bodies, which no kind count can see.
- `--capture-brief` → a grouped brief pre-filled for `/research-kb capture` (the consolidation adapter), with `type:code` evidence surfaced as wiki-pages-for refs and `informed_by` + units.yml `parent` surfaced as wikilink candidates.
- `--include-archive` → also read consolidated `_fragments/_archive/`.
- `--next-id <session_id>` → the next unused delta id for that session, counting live **and** `_archive/` (capture step 2b). A file is claimed by its stem or envelope `session_id` too, so deltas wearing a legacy/abbreviated prefix still count — a prefix match alone would answer `001` for a session that already holds deltas.

Malformed deltas are WARNED, never dropped — fix the warning, don't ignore it.

## Operation 3 — consolidate (the load-bearing step)

When a unit matures (alpha/beta, or the user declares it), promote its deltas into curated `knowledge/`. This is the correctness gate; if it never happens the fragments become shadow docs (spec §10 🔴). The mechanical half is scripted as a **draft → distill → review → apply** boundary (`scripts/consolidate.py`); only distillation stays with the agent:

1. **Draft (read-only):**
   ```
   python ~/.codex/skills/knowledge-fragment/scripts/consolidate.py <knowledge-dir> <unit_id> --draft
   ```
   writes `_fragments/_drafts/<unit>.md`: the unit's unconsolidated deltas grouped by kind (full bodies + evidence), provisional deltas flagged, `type:code` refs as wiki candidates, wikilink candidates seeded from `informed_by` + the unit's `parent`, and a **SCHEMA-driven target recommendation** — only slices that exist on disk are offered (a thin KB may be `comparisons/`-only; `journal/`+`synthesis/` are never assumed). The draft frontmatter is the apply contract: `target`, `apply_mode` (`create` | `update-existing`), `consolidates` manifest. Touches nothing else.
2. **Distill (agent, in place):** edit the draft into the full-fidelity page — 2+3 layers, ≥2 `[[wikilinks]]`, recompute numbers from raw. Adjust `target`/`apply_mode`, prune the manifest if excluding deltas, and **remove the `> DRAFT:` banner line** — apply refuses while it is present (the proof-of-distillation gate).
3. **Review:** review the distilled draft for fidelity and scope. If promotion is already authorized for the unit, do not ask again; otherwise prepare this concrete draft and its checks before requesting the needed promotion approval (currency ≠ correctness, spec §10).
4. **Apply (mutating):** same command with `--apply`. `create` WRITES the target from the distilled draft (machine keys stripped) and deletes the draft afterwards -- it is a transform plus a delete, not a move (machine keys stripped; `consolidates:` kept as provenance back to the deltas); `update-existing` means you already merged into the existing page by hand — bookkeeping, which includes merging the manifest into the **target page's** `consolidates:` (the draft is the manifest's only home; a target whose frontmatter can't carry the list refuses pre-mutation). Both: manifest deltas → `status: consolidated` (old `provisional`/`superseded` preserved as a trailing comment), fragment files whose deltas have ALL reached a terminal disposition (`consolidated` | `archived` | `superseded`, across all units) move to `_fragments/_archive/` (a same-session post-archive continuation with disjoint delta ids APPENDS to the existing archive file; any other collision refuses), and the remaining **semantic** steps are printed: index.md entry, log line, feeding the `type:code` refs to `wiki-pages-for` (the semantic wiki staleness signal `git diff` misses; no `wiki/` ⇒ graceful no-op), kb-lint.

### Multi-unit batches

When several reviewed unit drafts feed one target page, use
`scripts/batch-promote.py` with the batch specification described in
`<harness-repo>/specs/knowledge-fragment.md` section 12. Run `--check`,
then `--transition` when carriers need conversion, `--init`, and `--execute`,
each with `--spec <spec.json>`. `--init` records the baseline; `--execute`
requires it and verifies target bytes, manifests, and fragment status changes
after each apply. Keep a single writer active. Failed witnesses stop the batch;
retain its state and drafts for recovery instead of editing around the failure.

## Terminal dispositions — what "zero debt" actually means

Capture is cheap and **high-recall by design**, so some captured material is not
page-worthy. "Debt at zero" therefore cannot mean "every delta became a page" — it
means **every delta reached a terminal disposition**:

| status | meaning | counted as debt? |
|---|---|---|
| `provisional` / `accepted` | still outstanding | **yes** |
| `consolidated` | promoted into a curated page (set by `--apply`) | no |
| `archived` | reviewed and deliberately NOT page-worthy; kept raw for the record | no |
| `superseded` | revised by a later delta; promoting it would publish stale content | no |

`archived` and `superseded` are set **by hand** in the delta's metadata fence (there
is no command, same as `superseded` has always worked); write the reason into the
delta body. `--draft` never re-collects a disposed delta, `--apply` refuses a
manifest that names one, and a fragment file archives once every delta in it is
disposed — not only when all were promoted.

**Promotion test** (from the 2026-07-31 design consultation): *would a future
maintainer change a design, avoid a mistake, understand a constraint, or recover a
decision because of this delta?* Yes ⇒ promote or merge it. No ⇒ `archived`.
"Dropped" means dropped from curated promotion, **never erased** — the raw delta
stays. Only actually delete for duplication, invalidity, or sensitive content, and
record that disposition.

## Acceptance test (the success bar — spec §8)

A cold session given the KB + a unit's KF alone must be able to name that unit's **actual improvement points / problems**, including that none remain when the record supports it. When independent cold-reader validation is authorized and available, use it; otherwise inspect the capture brief directly. If the reader cannot recover real known concerns, the deltas lack evaluative content or the real-time discipline slipped. Never add fictional concerns to make this test pass.

## Status

First build (no hook): convention + format + `units.yml` + `deltas-for` (+ `--debt`) + `kb-lint` exclusion. Second build (2026-06-10): `consolidate.py` draft/apply with SCHEMA-driven target routing (Operation 3 above). Third build (2026-06-10): additive provenance instruments — `informed_by` (delta) + `parent` (units.yml), surfaced as wikilink candidates across Operations 1–3. The Stop-hook backstop and `supersedes` linkage are **deferred** until dogfooding shows the need (spec §12). Capture is an always-on policy trigger in projects with `knowledge/_fragments/`.
