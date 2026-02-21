# Prometheus Plan: Phase 2

## Goal

Deliver a stable, modular operator dashboard and a validated settings system where:

- panels do not jump when dynamic content updates,
- reusable container behavior is centralized for scale,
- configuration changes are validated and explainable,
- model/prompt edits are manageable from UI,
- run-to-run result deltas are attributable to specific config changes.

## Scope

### In scope

- Dashboard layout stabilization via reusable web components.
- Fixed-height panel containers with internal scrolling.
- Responsive stacking/container layout behavior.
- New settings page for validated config editing.
- Model routing and prompt configuration controls.
- Config snapshotting and run-to-run delta analytics.

### Out of scope (this phase)

- Full framework migration.
- Paid third-party observability/config products.
- Replacing existing pipeline stage logic.

## Current-State Findings

1. `docs/viewer/dashboard.html` is monolithic and heavily relies on `innerHTML` rewrites for table/detail updates.
2. Dynamic sections expand/shrink without strict panel body boundaries, causing visible layout shifts.
3. Config lives across `.env`, `config/rules-engine.json`, and `config/model-routing.json` without one consolidated validation/editing flow.
4. `run_metrics` captures execution status, but not full effective config snapshots and result deltas tied to specific changes.

## Architecture Direction

### UI composition

- Introduce web components as stable primitives:
  - `db-shell`
  - `db-split-layout`
  - `db-panel`
  - `db-table-panel`
  - `db-detail-panel`
  - `db-filter-bar`
- Keep first rollout in light DOM for easier style integration; use Shadow DOM selectively when style isolation is needed.

### Panel behavior contract

Each reusable panel supports:

- fixed/min-height config,
- scrollable body region,
- loading/empty/error states,
- data binding via explicit setters.

### Config system contract

- Build an "effective config" model from all active sources.
- Enforce schema validation before apply.
- Persist versioned config snapshots linked to each run.
- Show run-to-run config and output deltas in UI.

## Milestones

### P0: Baseline Contracts and Instrumentation

Deliverables:

- Versioned API payload contract (`schema_version`).
- Canonical frontend state object and update flow.
- Layout-shift instrumentation (panel height changes per action).

Acceptance:

- A single state source drives rendering.
- Height-shift baseline is measurable and logged.

### P1: Reusable Component Foundation

Deliverables:

- Implement `db-panel` and `db-split-layout`.
- Migrate two pilot panels (Candidates, Detail) to component-based rendering.

Acceptance:

- No direct cross-panel DOM mutation.
- Pilot panels render with parity vs legacy.

### P2: Stable Layout and Scroll Strategy

Deliverables:

- Fixed workspace height policy.
- Internal panel scrolling with `min-height: 0` container correctness.
- Responsive stack behavior for narrow widths.
- Containment tuning (`contain: layout paint`) where safe.

Acceptance:

- No visible panel jump on candidate select/filter/refresh.
- Mobile and desktop layouts preserve readability and interaction.

### P3: Settings Page v1 (Validated Editing)

Deliverables:

- New settings UI with grouped fields and help text.
- Validation for type/range/enum constraints.
- Dry-run validation endpoint and apply workflow.

Acceptance:

- Invalid settings cannot be applied.
- Every editable field has help and validation feedback.

### P4: Model and Prompt Control Surface

Deliverables:

- Stage-level model selector (`primary`, `fallback`, candidates).
- Prompt editor for supported stages with variable hints.
- "Validate + Apply for next run" flow.

Acceptance:

- Model/prompt changes are persisted and visible before execution.
- Next run reflects selected route/prompt version.

### P5: Config Snapshot and Delta Analytics

Deliverables:

- Persist effective config snapshot/hash per run.
- Compute run-to-run config diffs and output metric diffs.
- Add dashboard delta panel (what changed vs what moved).

Acceptance:

- User can inspect: changed config keys, changed outputs, and directional impact.

### P6: Rollout and Hardening

Deliverables:

- Feature flag for v2 UI.
- Backward-compatible API strategy while migrating.
- Regression checks for schema validation and panel rendering.

Acceptance:

- v2 reaches parity for core workflows.
- Legacy fallback remains available during stabilization window.

## Data and Schema Additions

### Recommended DB additions

- `run_config_snapshots`:
  - `run_id`
  - `snapshot_json`
  - `snapshot_hash`
  - `created_at`
- `run_deltas`:
  - `run_id`
  - `base_run_id`
  - `config_diff_json`
  - `metrics_diff_json`
  - `created_at`

### Effective config shape

Suggested sections:

- `pipeline`
- `rules_engine`
- `model_routing`
- `prompts`
- `runtime`

## UI/UX Rules

1. Reserve panel geometry before data arrival.
2. Use skeleton placeholders instead of collapse/expand toggles.
3. Keep scroll inside panel body, not page body.
4. Avoid whole-panel `innerHTML` replacement after initial mount.
5. Render diff badges and explanatory hints on settings changes.

## Risk Register

1. **Style conflicts while introducing components**
   - Mitigation: start with light DOM components; isolate only when necessary.
2. **Schema drift between backend and settings UI**
   - Mitigation: backend-driven schema + typed validation response.
3. **Noisy or non-actionable deltas**
   - Mitigation: canonical JSON snapshots and curated metric-diff set.
4. **Secrets leakage in snapshots**
   - Mitigation: explicit redaction policy for sensitive runtime values.

## Success Metrics

### Stability

- Panel height-shift events per interaction reduced by >= 80% from baseline.
- No full-page vertical jump on async detail/source refresh.

### Operability

- 100% editable settings fields have validation + help text.
- 100% runs have config snapshot hash and linked delta record.

### Explainability

- Operator can answer in one screen:
  - what changed,
  - what moved,
  - and whether change direction was favorable.

## Execution Order Recommendation

1. P0 -> P1 -> P2 (stability first)
2. P3 -> P4 (safe control surface)
3. P5 -> P6 (impact visibility + rollout)

## Immediate Next Actions

1. Create `docs/viewer/components/` with initial `db-panel` and `db-split-layout`.
2. Introduce schema-backed settings endpoint in `scripts/insights_viewer.py`.
3. Add config snapshot write path in pipeline orchestration.
4. Add delta panel API and first comparative query.
