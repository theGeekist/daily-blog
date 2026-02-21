# Backend Modular Refactor: From Scripts to Package

## TL;DR

> **Quick Summary**: Refactor the monolithic script-based backend into a structured internal Python package (`daily_blog/`) to improve maintainability and readability, while strictly preserving CLI and API contracts.
> 
> **Deliverables**:
> - Internal package `daily_blog/` with specialized sub-modules for core, pipeline, domain, and insights.
> - Thin CLI wrappers for existing stage scripts (<150 SLOC each).
> - Refactored `insights_viewer.py` and `run_pipeline.py` adhering to <=500 SLOC per module.
> 
> **Estimated Effort**: Medium (7 phases)
> **Parallel Execution**: Limited (sequential phases to prevent dependency cycles)
> **Critical Path**: Phase 1 (Foundation) → Phase 2 (Orchestration) → Phase 5 (Insights)

---

## Context

### Original Request
The user expressed "SHOCK" at the 2k+ line `insights_viewer.py` and the "absurd" script-heavy nature of the backend. They demand a refactor with proper consistent naming, modular structure, and a limit of roughly <=500 SLOC per module.

### Refactor Objective (Hard Constraints)
- Keep modules roughly `<=500` SLOC.
- Preserve userspace contracts:
  - same stage IDs
  - same env vars (`PIPELINE_*`, `ENRICH_*`, `EDITORIAL_*`, etc.)
  - same DB table/column names
  - same output files (`data/*`)
  - same viewer API payload keys/routes

### Target Backend Structure
\`\`\`text
daily_blog/
  core/
    env.py
    json_utils.py
    time_utils.py
    db.py
  pipeline/
    definitions.py
    stage_runner.py
    metrics.py
    snapshots.py
    model_routing.py
    app.py
  enrichment/
    fetch.py
    discovery.py
    model.py
    store.py
    service.py
  editorial/
    evidence.py
    templates.py
    model.py
    store.py
    service.py
  insights/
    config_service.py
    settings_service.py
    prompt_specs.py
    queries.py
    run_control.py
\`\`\`

---

## Work Objectives

### Core Objective
Transform the backend from a collection of oversized scripts into a modular Python package while ensuring zero functional regression for operators and the frontend.

### Concrete Deliverables
- `daily_blog/` package with the sub-modules defined above.
- CLI wrappers in root: `run_pipeline.py`, `ingest_rss.py`, etc.
- Unified naming convention across all extracted services/stores.

### Definition of Done
- [ ] `python3 -m unittest discover -s tests` passes.
- [ ] No backend Python module exceeds 500 SLOC.
- [ ] CLI scripts in root are thin wrappers delegating to the package.
- [ ] API responses from `insights_viewer.py` are identical to pre-refactor state.

### Must Have
- Backwards compatibility for all environment variables.
- Preservation of current SQLite schema and data integrity.
- Consistent naming across all extracted services/stores.

### Must NOT Have (Guardrails)
- NO breaking changes to `docs/viewer/` (frontend assets).
- NO re-ordering of pipeline stages.
- NO introduction of heavy frameworks (e.g., FastAPI, Flask).

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Strategy
- Preserve subprocess-based test execution to ensure CLI "userspace" remains unbroken.
- Smoke test key endpoints (`/api/summary`, `/api/settings/effective`) against a temporary fixture DB.

### QA Policy
Every task includes agent-executed QA scenarios using `bash` and `python3`.

---

## Execution Strategy

### Parallel Execution Waves

\`\`\`
Wave 1 (Foundation):
├── Task 1: Package scaffolding [quick]
├── Task 2: Core utilities extraction [quick]
└── Task 3: DB and JSON logic extraction [quick]

Wave 2 (Orchestration):
└── Task 4: run_pipeline.py decomposition [unspecified-high]

Wave 3 (Domain Logic):
├── Task 5: enrich_topics.py modularization [unspecified-high]
└── Task 6: generate_editorial.py modularization [unspecified-high]

Wave 4 (Insights Monolith):
└── Task 7: insights_viewer.py backend split [ultrabrain]

Wave 5 (Consistency):
├── Task 8: Unified naming and logging pass [quick]
└── Task 9: Contract and test audit [unspecified-high]
\`\`\`

Critical Path: Task 1 → Task 4 → Task 7
Max Concurrent: 2 (Wave 3)

---

## TODOs

- [ ] 1. Foundation Package Scaffolding

  **What to do**:
  - Create `daily_blog/` directory with `__init__.py`.
  - Create `daily_blog/core/` with `__init__.py`.
  - Define `PROJECT_ROOT` in `daily_blog/core/env.py` for stable path resolution.

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: [`git-master`]

  **Acceptance Criteria**:
  - [ ] Directory structure exists.
  - [ ] `python3 -c "import daily_blog.core"` succeeds.

  **QA Scenarios**:
  \`\`\`
  Scenario: Import validation
    Tool: Bash
    Steps:
      1. python3 -c "from daily_blog.core.env import PROJECT_ROOT; print(PROJECT_ROOT)"
    Expected Result: Prints absolute path to the repo root.
    Evidence: .sisyphus/evidence/task-1-import.txt
  \`\`\`

- [ ] 2. Core Utilities and JSON Extraction

  **What to do**:
  - Move `load_env_file` from scripts to `daily_blog/core/env.py`.
  - Move `_load_json_file`, `_canonical_json`, and `_snapshot_hash` to `daily_blog/core/json_utils.py`.
  - Move time helpers to `daily_blog/core/time_utils.py`.

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: [`git-master`]

  **Acceptance Criteria**:
  - [ ] `daily_blog/core/env.py` contains `load_env_file`.
  - [ ] `daily_blog/core/json_utils.py` contains JSON helpers.

  **QA Scenarios**:
  \`\`\`
  Scenario: Env Loading check
    Tool: Bash
    Steps:
      1. Run ingest_rss.py (after updating to import from core) with a modified .env variable.
    Expected Result: Exit code 0, respects the env change.
    Evidence: .sisyphus/evidence/task-2-env.txt
  \`\`\`

- [ ] 3. Database Logic Extraction

  **What to do**:
  - Extract common SQLite patterns (conn management, common queries) to `daily_blog/core/db.py`.
  - Standardize `init_*_table` patterns into a more cohesive store pattern if possible without schema change.

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: [`git-master`]

  **Acceptance Criteria**:
  - [ ] `daily_blog/core/db.py` contains shared logic.

  **QA Scenarios**:
  \`\`\`
  Scenario: DB connectivity
    Tool: Bash
    Steps:
      1. python3 -c "from daily_blog.core.db import get_db_connection; conn=get_db_connection(':memory:'); print(conn)"
    Expected Result: Prints sqlite3.Connection object.
    Evidence: .sisyphus/evidence/task-3-db.txt
  \`\`\`

- [ ] 4. Orchestrator Decomposition (run_pipeline.py)

  **What to do**:
  - Split `run_pipeline.py` into:
    - `daily_blog/pipeline/definitions.py` (stage definitions, defaults).
    - `daily_blog/pipeline/stage_runner.py` (subprocess logic, retries).
    - `daily_blog/pipeline/metrics.py` (run_metrics writes).
    - `daily_blog/pipeline/snapshots.py` (config snapshot + delta).
    - `daily_blog/pipeline/model_routing.py` (routing logic).
  - Turn `run_pipeline.py` into a thin CLI wrapper calling `daily_blog.pipeline.main()`.

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: [`git-master`]

  **Acceptance Criteria**:
  - [ ] `run_pipeline.py` is < 150 SLOC.
  - [ ] Pipeline still records identical `run_metrics` rows.
  - [ ] `tests/test_pipeline_stages.py` passes.

  **QA Scenarios**:
  \`\`\`
  Scenario: Full pipeline run
    Tool: Bash
    Steps:
      1. Run PIPELINE_SKIP_STAGES='["score","extract_claims","lift_topics","normalize_topics","enrich_topics","generate_editorial"]' python3 run_pipeline.py
    Expected Result: Runs only 'ingest', records metrics, exit code 0.
    Evidence: .sisyphus/evidence/task-4-pipeline.txt
  \`\`\`

- [ ] 5. Enrichment Domain Split (enrich_topics.py)

  **What to do**:
  - Modularize `enrich_topics.py` into `daily_blog/enrichment/`:
    - `fetch.py` (URL normalize, verify fetch).
    - `discovery.py` (Scraping logic).
    - `model.py` (Prompt/schema/normalization).
    - `store.py` (Persistence).
    - `service.py` (Orchestration loop).
  - Turn `enrich_topics.py` into a wrapper.

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: [`git-master`]

  **Acceptance Criteria**:
  - [ ] `enrich_topics.py` is a thin wrapper.
  - [ ] `tests/test_enrich_topics.py` passes.

  **QA Scenarios**:
  \`\`\`
  Scenario: Enrichment run
    Tool: Bash
    Steps:
      1. Run enrich_topics.py with a known topic.
    Expected Result: Writes to enrichment_sources table, exit code 0.
    Evidence: .sisyphus/evidence/task-5-enrichment.txt
  \`\`\`

- [ ] 6. Editorial Domain Split (generate_editorial.py)

  **What to do**:
  - Modularize `generate_editorial.py` into `daily_blog/editorial/`:
    - `evidence.py` (Scoring/assessment).
    - `templates.py` (Markdown builders).
    - `model.py` (Prompt/validation).
    - `store.py` (DB writes).
    - `service.py` (Topic loop).
  - Turn `generate_editorial.py` into a wrapper.

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: [`git-master`]

  **Acceptance Criteria**:
  - [ ] `generate_editorial.py` is a thin wrapper.
  - [ ] `tests/test_generate_editorial.py` passes.

  **QA Scenarios**:
  \`\`\`
  Scenario: Editorial generation
    Tool: Bash
    Steps:
      1. Run generate_editorial.py with a mock fixture DB.
    Expected Result: Writes files to data/ as expected, exit code 0.
    Evidence: .sisyphus/evidence/task-6-editorial.txt
  \`\`\`

- [ ] 7. Insights Monolith Split (insights_viewer.py)

  **What to do**:
  - Decompose the massive `insights_viewer.py` into `daily_blog/insights/`:
    - `queries.py`: SQL query definitions.
    - `settings_service.py`: Config/Settings mutation and validation.
    - `prompt_specs.py`: Prompt transparency logic.
    - `run_control.py`: Pipeline process management.
  - Keep `InsightsHandler` in a small script.

  **Recommended Agent Profile**:
  - **Category**: `ultrabrain`
  - **Skills**: [`git-master`]

  **Acceptance Criteria**:
  - [ ] `scripts/insights_viewer.py` is < 500 SLOC.
  - [ ] Endpoints respond with same JSON structure.

  **QA Scenarios**:
  \`\`\`
  Scenario: API smoke test
    Tool: Bash (curl)
    Steps:
      1. Start insights_viewer.py in background.
      2. curl http://localhost:8877/api/summary
    Expected Result: Returns valid JSON with counts, exit code 0.
    Evidence: .sisyphus/evidence/task-7-api.txt
  \`\`\`

- [ ] 8. Naming and Consistency Pass

  **What to do**:
  - Enforce consistent naming patterns: `*_service.py` for orchestration, `*_store.py` for DB, `*_model.py` for LLM IO.
  - Normalize logging and error handling across new package.

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: [`git-master`]

  **Acceptance Criteria**:
  - [ ] Unified naming style across all files.

  **QA Scenarios**:
  \`\`\`
  Scenario: Naming audit
    Tool: Bash
    Steps:
      1. find daily_blog -name "*.py"
    Expected Result: All files follow the specified naming suffixes.
    Evidence: .sisyphus/evidence/task-8-naming.txt
  \`\`\`

---

## Final Verification Wave

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Verify all "Must Have" requirements are met. Check that all scripts are wrappers. Ensure no module > 500 SLOC.
- [ ] F2. **Full Regression Suite** — `unspecified-high`
  Run `python3 -m unittest discover -s tests`.
- [ ] F3. **API Integrity Check** — `unspecified-high`
  Smoke test key endpoints against a temporary fixture DB.
- [ ] F4. **Import Cycle Check** — `unspecified-high`
  Verify no circular imports exist in the `daily_blog/` package.

---

## Commit Strategy

| After Task | Message | Files | Verification |
|------------|---------|-------|--------------|
| 1-3 | `refactor(core): establish foundation package and move utilities` | daily_blog/core/* | tests |
| 4 | `refactor(pipeline): modularize pipeline orchestration` | daily_blog/pipeline/* | tests |
| 5-6 | `refactor(domain): split enrichment and editorial logic` | daily_blog/domain/* | tests |
| 7 | `refactor(insights): break down insights_viewer monolith` | daily_blog/insights/* | tests |
| 8 | `refactor(style): naming and consistency pass` | daily_blog/* | tests |

---

## Success Criteria

### Verification Commands
\`\`\`bash
python3 -m unittest discover -s tests # All tests pass
ls -l scripts/insights_viewer.py # Thin wrapper check
find daily_blog -name "*.py" | xargs wc -l # SLOC check
\`\`\`
