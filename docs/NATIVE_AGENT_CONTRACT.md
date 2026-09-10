# Native agent routing and reports

`scripts/native-agent-contract.py` adapts five portable roles to Codex native
function hooks. It validates user-selected model and reasoning-effort tuples,
adds the applicable role instructions to delegated tasks, and records bounded
local evidence about launches and completions. It does not choose models,
install native profiles, or prove which runtime identity served a request.

## Roles and configuration

Every routing configuration contains exactly these roles:

| Role | Purpose | May edit assigned files |
|---|---|---|
| `worker` | Bounded implementation and verification | Yes |
| `reviewer` | Correctness and purpose-fit review | No |
| `explore` | Focused codebase exploration | No |
| `plan` | Architecture, contract, and dependency analysis | No |
| `general` | Bounded routine execution | Yes |

The effective configuration is selected in this order:

1. `<project>/.codex/agent-routing.json`
2. `CODEX_HOME/dev-setup-codex-community/agent-routing.json`

The second path is an optional, user-owned global default. This distribution
does not ship, install, repair, or overwrite it. When neither file exists,
routing reports `UNSET` and leaves model selection to the host.

Resolution starts at the event's absolute working directory and stops at the
nearest routing configuration or Git root. A present malformed configuration,
linked configuration path, or linked `.codex` directory fails closed. An
invalid project override never falls back to the global file.

Schema 1 maps each role to three required fields: `agent_type`, `model`, and
`reasoning_effort`. Every `agent_type` must be distinct and must be a profile
offered by the active native spawn tool.

Schema 2 replaces `agent_type` with `task_name_prefix`. Each prefix must be the
role name plus an underscore: `worker_`, `reviewer_`, `explore_`, `plan_`, or
`general_`. The suffix makes the task name unique. Schema 2 supports hosts whose
spawn tool does not expose specialized agent profiles.

Both schemas also contain `schema_version`, a 64-character
`catalog_fingerprint`, and all five role rows. A role may add
`allowed_reasoning_efforts`, a nonempty list of unique efforts that includes
the scalar `reasoning_effort`. The scalar remains the default when a launch
omits the effort. An explicit effort in the list is preserved and recorded for
completion checks. Without the list, the scalar value is the only allowed
effort. Explicit model or effort values outside the selected role's mapping are
denied instead of rewritten.

No model names or role pins are built into this distribution. Choose values
from the catalog reported by the active Codex installation.

## Session attestation

SessionStart discovers the active catalog through the configured Codex CLI's
`app-server` protocol. It starts no thread or inference request. The catalog
fingerprint covers the exact model slugs and their advertised reasoning
efforts.

An attestation records the effective configuration's absolute source path and
content hash. Adding or removing a project override, switching between project
and global sources, editing the effective file, or removing it invalidates the
old attestation. A source change invalidates even when both files have identical
JSON.

`FRESH` means every configured model and every allowed effort is currently
advertised, the source and content hash still match, and the attestation is no
more than 24 hours old. An exact catalog fingerprint match reports
`catalog_matches`. If unrelated catalog entries changed while all selected
tuples remain available, the session stays `FRESH` and reports
`selected_models_supported`. A missing selected model or effort reports
`STALE: selected_tuple_unavailable`.

SessionStart revokes the previous session lease before discovery. A usable
`FRESH` result requires a lease matching the completed attestation, and the
lease is written only after the related state records succeed. Missing,
revoked, expired, changed, or incomplete state denies launches for a managed
role. An attestation expires after 24 hours.

These checks establish local configuration and catalog compatibility. They do
not establish hook trust or delivery, provider routing, account identity, or
the model that actually executed a child task.

## Launch and report behavior

PreToolUse supplies an omitted selected model and default effort, preserves an
allowed explicit effort, and prepends the applicable role instructions to the
native `message`. Applying the hook twice does not duplicate those
instructions. Full-history forks are denied because the native tool cannot
accept model and effort overrides for that form. A schema 2 launch receives
`fork_turns: none` when the caller omitted it.

Every delegated role receives the same compact parent-report contract. Its
response must distinguish:

- `Status/outcome`: complete, partial, or blocked, and whether work is proposed,
  implemented, or accepted by evidence.
- `Scope/basis`: changed and inspected files or symbols, plus the relevant
  source revision and dirty state when available.
- `Checks/evidence`: only checks actually run and concise evidence locations.
- `Findings/unknowns`: reachable findings, risks, and unknowns with their
  trigger conditions.
- `Parent action`: remaining integration, verification, or decisions.

The report is addressed to the parent orchestrator. It does not claim final
user acceptance, dump full logs or diffs, expose hidden reasoning, or infer an
unobserved runtime identity.

PreToolUse records the requested tuple without storing the task text.
PostToolUse associates that launch with a returned native child ID when the
response provides one. SubagentStop compares available native event and child
transcript identity with the request. Complete agreeing evidence can be marked
`VERIFIED_RUNTIME`; missing evidence remains `UNVERIFIED`; contradictory
evidence becomes `MISMATCH`. Reasoning effort is not present in every native
event, so configuration alone is never substituted for observed effort.

## Command and state paths

The adapter supports these modes:

```text
python scripts/native-agent-contract.py session
python scripts/native-agent-contract.py pre
python scripts/native-agent-contract.py post
python scripts/native-agent-contract.py subagent-stop
python scripts/native-agent-contract.py status --cwd PROJECT
```

The default state directory remains
`CODEX_HOME/dev-setup-codex/native-agents` for compatibility with existing hook
commands and state. `--home CODEX_HOME` scopes both the optional global routing
file and the default state directory. A canonical explicit `--state-dir` ending
in `dev-setup-codex/native-agents` infers the same Codex home. An arbitrary
`--state-dir` has no global fallback unless `--home` is also supplied. This
prevents isolated tests or alternate state roots from reading ambient user
routing settings.

State roots and their ancestors must be real directories, not links or Windows
name-surrogate reparse points. For direct CLI calls on macOS, resolve `/tmp` and
`/var` to their `/private/...` paths before supplying `--home` or `--state-dir`.
Installed hook commands already use the resolved home path.

`--codex-bin EXE` selects the executable used for SessionStart catalog
discovery. `status` never starts Codex. Without `--session-id`, `status --cwd`
uses the latest session recorded for the resolved project; an explicit session
ID selects that session.

Configuration and state files are size-bounded, local paths are checked against
their owned roots, and linked routing or state paths are rejected. These local
records are diagnostic evidence. Only observed, matching native completion
evidence supports a runtime identity claim.
