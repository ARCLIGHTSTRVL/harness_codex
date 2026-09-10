---
name: knowledge-mirror
description: Detect which Obsidian KR mirrors of a project's in-repo knowledge/ layer are stale or missing, then hand-craft the natural-Korean mirror (translation is NEVER automated). Trigger words include "knowledge mirror", "KR mirror", "mirror knowledge", "지식 미러", "옵시디언 미러", "미러 최신화", "미러 갱신".
---

# knowledge-mirror

Keep the user's Korean reading mirror of a project's `knowledge/` (research-kb)
layer in sync with the EN authoritative source — **detection automated, translation
hand-made**.

Why a skill and not auto-translation: per `<knowledge_fidelity>`, `knowledge/` is
human-facing full-fidelity content. A bulk faithful translation reads as
translationese and corrodes what the user reconstructs from. So this skill only
answers *"which pages need a human pass"*; the actual KR writing is done by hand,
one page at a time, per the natural-Korean rubric in `research-kb/SKILL.md`.

This is the successor to the retired `/workflow-mirror` (which mirrored terse
`workflow/*.md`). The user's real Obsidian use is the `knowledge/` mirror.

## When

- The user asks to refresh / update / check the KR knowledge mirror.
- After non-trivial edits to a project's `knowledge/` pages, to see what drifted.
- Not on a schedule — run when asked or at a natural milestone.

## 1. Locate the two trees

The KR mirror lives in an Obsidian `project`-purpose vault (registry
`~/.codex/obsidian.yaml`). There is no per-project pin file — resolve the vault
folder from the registry + project name, reusing an existing folder (case/hyphen
tolerant) rather than creating a duplicate. You need three paths:

- `en_knowledge_dir` — the in-repo EN `knowledge/` dir (authoritative).
- `en_base_dir` — the base that KR `en_source:` paths are relative to (the dev
  root, e.g. `C:/dev`; existing mirrors use `project_<name>/knowledge/...`).
- `kr_mirror_dir` — the vault's KR `knowledge/` mirror dir.

## 2. Detect (the only automated step)

```
python ~/.codex/skills/knowledge-mirror/knowledge-mirror-status.py <en_knowledge_dir> <en_base_dir> <kr_mirror_dir>
```

Read-only. Content-hashes each EN page against the `en_source_sha` recorded in its
KR mirror frontmatter and reports per page:

- `FRESH` — mirror matches the EN source now.
- `STALE` — EN changed since the mirror, or no `en_source_sha` recorded yet.
- `MISSING` — EN page has no KR mirror.
- `ORPHAN` — KR mirror points to an EN page that no longer exists.
- `DUP` — two (or more) KR mirrors claim the same EN page — keep one, retire the rest by hand.
- `IGNORED` — EN page deliberately not mirrored (see exclusions below) — no action.
- `IGNORE-STALE` — an exclusion entry matches no EN page (dangling — clean it up).
- `IGNORE-INVALID` — an absolute, drive-lettered, or escaping exclusion path is unusable; it excludes nothing and needs correction.

Exit 1 if anything needs a pass, 0 if all `FRESH` / `IGNORED`.

### Excluding a page (don't mirror it)

Some EN pages should never get a KR mirror (e.g. KB-system meta that lives in the
harness, not the project's research). List them in `<kr_mirror_dir>/_mirror-ignore.txt`
— one `en_source` path per line, optional `# reason`:

```
project_x/knowledge/queries/meta-note.md  # KB-system meta, not project research
```

They then report `IGNORED` (not `MISSING`). Vault-side so it works even when the EN
source is read-only. Exclusions are always listed (never silent), and a dangling
entry surfaces as `IGNORE-STALE` — so an accidental exclusion can't quietly hide a
page that should be mirrored. **Always give a reason.**

## 3. Hand-craft each STALE / MISSING page

For each flagged page, translate **by hand, one at a time** — do NOT batch-translate.
Do not use machine translation, an automated translation loop, or any bulk pass.

- Apply the natural-Korean rubric in `~/.codex/skills/research-kb/SKILL.md`
  ("KR mirror" section): adapt to Korean word order, finish every sentence, no
  noun-piles, gloss a domain term once. Not a sentence-by-sentence faithful copy.
- Recompute any empirical number from the pinned raw source before writing it
  (per `<knowledge_fidelity>`) — never carry a number over on trust.
- Frontmatter contract on each KR mirror:
  ```
  en_source:     project_<name>/knowledge/<...>.md   # repo-relative to en_base_dir
  en_source_sha: sha256:<hex>                         # of the EN file you mirrored from
  lang: KR
  ```
  Copy the `cur=sha256:<hex>` the status script prints for that page (or compute
  it: `python -c "import hashlib,sys;print('sha256:'+hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <en_file>`).
  This sha is what makes the next `status` run able to detect drift — without it
  the page reports `STALE` forever.
- Never patch facts only in the KR mirror — fix the EN authoritative page in-repo
  first, then hand-remirror the KR page.

## 4. Report

Summarize: which pages were (re)mirrored, which stayed fresh, any ORPHAN to
retire by hand. Do not auto-delete orphans.

## Boundaries

- Translation is hand-made; the script never writes KR content.
- EN `knowledge/` in-repo is authoritative; the vault is a read mirror.
- For terse `workflow/*.md` there is no mirror anymore (KR workflow mirrors were
  retired with `/workflow-mirror`).
