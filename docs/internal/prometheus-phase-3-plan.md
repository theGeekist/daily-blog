# Prometheus Plan: Phase 3 (Prompt Transparency + Typed Settings UX)

## Mission

Make settings genuinely operable by humans:

- Operators can see default prompts before editing anything.
- Operators can see prompt inputs, output contracts, and examples per stage.
- Model selection fields explain purpose and tradeoffs, not just model names.
- High-value settings stop being raw JSON and become typed/list/map form controls.

## Scope

### In Scope

1. Prompt transparency contract for all model-driven stages.
2. Typed settings forms for highest-impact config paths.
3. Rich explanatory metadata (purpose, impact, ranges, examples).
4. Backward-compatible migration from current settings payloads.

### Out of Scope (Phase 3)

1. Full dashboard rewrite.
2. Replacing every single JSON config field in one pass.
3. Changing core pipeline logic beyond prompt override plumbing and settings application paths.

## Current Problems (Ground Truth)

1. Prompt overrides are editable, but built-in stage prompts are not visible in settings by default.
2. Settings do not provide enough operational context (inputs/outputs/schemas) for safe prompt edits.
3. Model routing explanations are shallow and not stage-purpose specific.
4. Advanced raw JSON is still required for key fields (topics, keyword lists, model candidate lists).

## Prompt Context Contract (New)

For each stage (`extractor`, `topic_lifter`, `topic_curator`, `enrichment`, `editorial`) return a `PromptSpec`:

- `stage_id`: stable identifier.
- `script`: source file path.
- `default_template`: built-in prompt template (read-only).
- `effective_template`: resolved prompt after prefix/suffix/template override.
- `override`: `{prefix, suffix, template}` from `config/prompts.json`.
- `variables`: list of input variables with type and description.
- `inputs_example`: example input payload used to build prompt.
- `output_contract`:
  - JSON schema for strict stages (or structured contract object).
  - validator notes (required fields, enum constraints, quality gates).
- `output_example`: representative valid output.
- `notes`: stage-specific caveats.
- `contract_version`: for compatibility.

### Prompt Override Resolution Rules

1. Built-in stage prompt is always available as `default_template`.
2. If `template` contains `{prompt}`, resolve as `template.replace('{prompt}', built_in_prompt)`.
3. Else resolve as `prefix + built_in_prompt + suffix`.
4. Empty override fields produce `effective_template == default_template`.
5. Validation warnings:
   - Template missing `{prompt}` for full-replacement mode.
   - Known required variables missing from template.

## Typed Settings Coverage (Phase 3 Targets)

### Group A: Prompt and Model Clarity (must ship)

- Prompt overrides per stage: `prefix`, `suffix`, `template` as prompt editor fields.
- Model routing fields: `primary`, `fallback` plus purpose cards per stage.
- `local_candidates` as list editor (not JSON).

### Group B: Rules and Taxonomy (must ship)

- `rules_engine.hard_rules.blocked_title_keywords` -> list editor.
- `rules_engine.actionability_keywords` -> list editor.
- `rules_engine.topics` -> map-of-list editor.

### Group C: Runtime knobs (must ship)

- `PIPELINE_RETRIES` -> integer field.
- `PIPELINE_STAGE_TIMEOUTS` -> stage timeout map editor.
- `EXTRACT_MAX_MENTIONS` -> integer with range.

### Group D: Raw JSON fallback (allowed but de-emphasized)

- Keep hidden/collapsible fallback for obscure keys.
- Track usage telemetry to drive future typed coverage.

## UX Component Plan (Web Components)

Implement reusable settings components in `docs/viewer/components/settings-components.js`:

1. `settings-group`:
   - section title, purpose, impact notes.
2. `settings-field`:
   - typed controls for scalar values with inline help/range.
3. `settings-prompt-editor`:
   - default template panel (read-only), effective template preview, override editor, variable chips, output contract summary.
4. `settings-list-editor`:
   - add/remove/reorder list values with per-item validation.
5. `settings-map-editor`:
   - key/value map, nested list editing when value is list.
6. `settings-model-card`:
   - stage purpose, expected workload, reliability notes, local model guidance.

## Milestones and Gates

### M1 - Prompt Introspection Backend

Deliver:

- Prompt metadata registry for all 5 stages.
- API endpoint(s) returning `PromptSpec` for each stage.

Acceptance:

- Settings UI can render non-empty default prompt for every stage.
- Settings API includes variables + output contract + output example for every stage.

### M2 - Typed Prompt Editor + Model Purpose Cards

Deliver:

- `settings-prompt-editor` and `settings-model-card` integrated in settings page.

Acceptance:

- Operator can answer for each stage:
  - what input variables exist,
  - what output shape is required,
  - what model is for and why.

### M3 - Replace High-Impact Raw JSON

Deliver:

- List editors for keyword lists.
- Map-of-list editor for topic taxonomy.
- List editors for model candidate pools.

Acceptance:

- No raw JSON needed for Group A/B targets.
- Inline validation blocks invalid list/map structures.

### M4 - Runtime Knobs and Validation Hardening

Deliver:

- Typed runtime controls + range validation.
- Field-level error mapping from backend to UI.
- Reset-to-default and diff preview before apply.

Acceptance:

- Every edited field shows type, range, help, and current/default values.
- Apply path is deterministic and emits structured errors.

### M5 - Compatibility + Rollout

Deliver:

- Backward-compatible support for old payload shape.
- Migration notes and feature-flag strategy.

Acceptance:

- Existing clients still function.
- New typed flow is default for settings page.

## Safety and Risk Controls

1. **Config breakage risk**
   - Apply is blocked only on parse/type/range violations.
   - Warnings (non-blocking) for prompt-quality issues.
2. **Schema drift risk**
   - One authoritative metadata source in backend (`settings form + prompt contract`).
3. **Backward compatibility risk**
   - Accept old and new payload forms during transition.
4. **Operator confusion risk**
   - Every field must include purpose and impact text.

## Verification Plan

### Automated

1. Unit tests for prompt metadata extraction and override resolution.
2. Unit tests for typed field coercion and validation.
3. API tests for:
   - `/api/settings/form`
   - `/api/settings/effective`
   - prompt contract endpoint.

### Manual Operator Checks

1. Can view default + effective prompt for each stage without opening code.
2. Can edit prompt with visible variable and output guidance.
3. Can edit list/map configs without touching JSON text.
4. Can understand model purpose cards before switching model.
5. Can validate/apply and understand errors without reading logs.

## Definition of Done

Phase 3 is complete when all conditions are true:

1. Prompt defaults and contracts are visible and non-empty in settings UI.
2. Group A/B/C fields are typed forms (not raw JSON textareas).
3. Model routing includes stage-purpose explanation cards.
4. Field-level validation and error mapping are operational.
5. Raw JSON fallback is optional, collapsible, and no longer required for common operations.
