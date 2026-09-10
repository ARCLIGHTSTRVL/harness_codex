# External review configuration

The project owns `.codex/external-review.json`. It is JSON with schema 1,
not a Claude `.claude/agent-routing.yml` file. No migration is implicit.

```json
{
  "schema": 1,
  "external_review": {
    "codex": {
      "model": "selected-provider-model",
      "effort": "high",
      "selected_at": "2026-09-09T00:00:00Z"
    }
  },
  "catalogs": {
    "codex": {
      "selected-provider-model": ["low", "high"]
    }
  }
}
```

The model and timestamp above are placeholders, not a recommendation. Record
the user's actual model/effort selection and the actual selection time.
`external_review` and `catalogs` may each contain `claude` and/or `codex`.
`selected_at` and `catalogs` are optional. Model ids and effort values must be
nonempty slugs. Catalogs map model ids to lists of supported effort values.

Status reads catalogs offline. A project-recorded catalog takes precedence;
Codex can otherwise use `~/.codex/opencodex-catalog.json` when present. Claude
without a project catalog is UNVALIDATED. An empty effort list means the
record contains no effort evidence, so only model membership is checked.

The helper renders the requested flags. Executors compare that request with
the provider's reported model; catalog membership is not proof of what ran.
Missing configuration is UNSET; invalid JSON/schema is INVALID and blocks runs.

The optional `.codex/review-context.md` contains the project's trust boundary
and scope. Executors prepend it before scanning. Do not place secrets there.
