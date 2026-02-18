# Intelligence Layer Implementation Plan

## Why this exists

Current implementation shipped ingest + baseline scoring only. The original internal goals require LLM-backed claim extraction, topic lifting, enrichment, and editorial generation with MCP tools and model routing. This plan adds the intelligence layer and operational hardening to complete the E2E target.

## Goal Alignment: Planned vs Current

- Implemented now:
  - RSS ingest and persistence (`ingest_rss.py`)
  - Configurable scoring baseline (`score_rss.py`)
  - Daily board output (`data/daily_board.md`)
- Not yet implemented (required for original E2E intent):
  - claim extraction artefacts (`headline`, `who_cares`, `problem`, `solution`, `evidence`, `sources`)
  - parent-topic lifting with strict schema (`slug`, `label`, `why_it_matters`, `time_horizon`)
  - enrichment with validated citations
  - editorial generation (titles, outlines, talking points, verification checklist)
  - evaluation framework and regression dataset
  - orchestrator-driven multi-agent stage execution with model routing
  - cronized full pipeline with retries, alerts, and runbook

## End-to-End Stages (Required)

1) Collector
- Input: `feeds.txt`
- Output: `mentions` table + `mentions.jsonl`
- Gate: zero parser crashes, deterministic dedupe by key

2) Extractor
- Input: `mentions`
- Output table: `claims`
- Required fields:
  - `claim_id`, `entry_id`, `headline`, `who_cares`, `problem_pressure`, `proposed_solution`, `evidence_type`, `sources_json`
- Gate: >= 95% rows produce non-empty `headline` and `who_cares`

3) Topic-lifter
- Input: `claims`
- Output tables: `topic_clusters`, `claim_topic_map`
- Required fields per topic:
  - `parent_topic_slug`, `parent_topic_label`, `why_it_matters`, `time_horizon`
- Gate: <= 20% claims in `misc`, stable cluster IDs run-to-run on fixed dataset

4) Researcher (enrichment)
- Input: `topic_clusters`
- Output table: `enrichment_sources`
- Required fields:
  - `topic_id`, `query_terms_json`, `domain`, `url`, `stance`, `credibility_guess`, `fetched_ok`
- Gate: no citation appears unless tool-fetched (`fetched_ok=1`)

5) Editor
- Input: enriched topics
- Output table: `editorial_candidates`
- Required fields:
  - `topic_id`, `title_options_json`, `outline_markdown`, `talking_points_json`, `verification_checklist_json`
- Gate: each candidate includes verification checklist + at least 3 outline sections

6) Ranker
- Input: editorial candidates + scoring features
- Output table: `candidate_scores`
- Gate: deterministic ranking from config + explainable component breakdown persisted

7) Publisher-ready report
- Input: top-ranked candidates
- Output files:
  - `data/daily_board.md`
  - `data/top_outlines.md`
  - `data/research_pack.json`
- Gate: every top item has source evidence and anti-duplication pass

## Staged Implementation Plan

### Stage A (foundation hardening)
- Keep current ingest + score path
- Add test harness + fixtures
- Deliverables:
  - `tests/test_ingest.py`
  - `tests/test_scoring.py`
  - fixture DB and fixture feeds

### Stage B (claims + topics)
- Add extractor and topic-lifter modules
- Persist claim and topic tables
- Deliverables:
  - `extract_claims.py`
  - `lift_topics.py`
  - schema migration script `scripts/migrate_v2.sql`

### Stage C (enrichment + editorial outputs)
- Add enrichment worker and editor generator
- Enforce citation validity
- Deliverables:
  - `enrich_topics.py`
  - `generate_editorial.py`
  - output specs in `docs/internal/output-schemas.md`

### Stage D (orchestration and model routing)
- Add orchestrator-runner that calls stages in order and persists stage status
- Integrate preconfigured OpenClaw/OpenCode model routing for specific stages
- Deliverables:
  - `run_pipeline.py`
  - `config/model-routing.json`

### Stage E (cron + observability)
- Daily cron to run full pipeline
- Add run metrics and failure notifications
- Deliverables:
  - `ops/cron/daily_pipeline.cron`
  - `ops/runbook.md`
  - `data/run_metrics` table

### Test Strategy (Non-optional)

- Unit tests:
  - URL normalization, dedupe, novelty buckets, score math, quota rules
- Integration tests:
  - ingest -> score
  - ingest -> extract -> topic
  - topic -> enrich -> editorial
- E2E tests:
  - full pipeline on fixed fixture dataset
  - assert deterministic top-N list under fixed config
- Quality tests:
  - citation validity rate
  - title diversity
  - duplicate suppression across days

### Acceptance Criteria by Milestone

- M1 (current + tests): scoring baseline is green, tests pass in CI/local
- M2 (claims/topics): >= 80% useful topic assignment on fixture dataset
- M3 (enrichment/editorial): every output has references + checklist
- M4 (orchestration): one command runs all stages with stage-level retry
- M5 (operations): cron runs daily for 7 days without manual intervention

### Model Integration Plan (OpenClaw/OpenCode + Local)

- Coordinator (deterministic control): Codex-5.3
- Extractor/topic-lifter (cost-sensitive batch): Gemini-3-Pro or local Ollama model
- Editorial drafting (quality-sensitive): Codex-5.3 primary, GLM5 fallback
- Expensive fallback only when required: Opuse-4.5

Routing rules:
- Ranker remains deterministic code-path (no LLM-only score fields)
- LLM outputs must validate against strict JSON schema before persistence
- If model call fails, retry with fallback route and mark `model_route_used`

### Cron and Operations Plan

- Schedule:
  - `0 8 * * *` local time: full pipeline run
- Runtime sequence:
  - `python3 ingest_rss.py`
  - `python3 score_rss.py`
  - `python3 extract_claims.py`
  - `python3 lift_topics.py`
  - `python3 enrich_topics.py`
  - `python3 generate_editorial.py`
- Retry policy:
  - transient failures: 2 retries with backoff
  - hard failures: mark run failed, keep partial outputs isolated by `run_id`
- Required run logs:
  - stage start/end, row counts, failure reason, model route, duration

### Output Design Contract (final content)

- `data/daily_board.md`:
  - ranked shortlist with component scores and novelty reasons
- `data/top_outlines.md`:
  - per-topic title options + outline + angle and audience
- `data/research_pack.json`:
  - machine-readable citations and evidence map for verification

### Next Action Order

1. Add test harness + fixtures and lock deterministic baseline.
2. Implement claims and topic-lifting modules with schema migrations.
3. Implement enrichment and editorial generation with citation checks.
4. Add orchestrator runner and model routing config.
5. Add cron + runbook + run metrics, then run 7-day soak test.
