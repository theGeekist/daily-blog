# Intelligence Layer Execution Plan

## Why this exists

Previous plan defined intelligence stages but not executed. This plan begins systematic implementation: Stage A (test harness + fixtures), Stage B (real claims + topics), Stage C (enrichment + editorial), Stage D (orchestration + routing), Stage E (cron + ops).

## Stages

### Stage A: Test Harness + Fixtures (Foundation)
- [ ] Create fixture DB with baseline mentions
- [ ] Add `tests/test_ingest.py` to test `ingest_rss.py`
- [ ] Extend `tests/test_scoring_baseline.py` for more edge cases
- [ ] Add `tests/test_extract_claims.py` with schema validation checks
- [ ] Add `tests/test_lift_topics.py` for topic stability
- [ ] Add `tests/test_enrich_topics.py` for citation validity
- [ ] Add `tests/test_generate_editorial.py` for output structure
- [ ] Create E2E fixture dataset (fixed DB with predetermined mentions + expected outputs)

### Stage B: Real Claims Extraction + Topic Lifting
- [ ] Refactor `extract_claims.py` to use OpenCode/OpenClaw with model routing
- [ ] Add strict JSON schema validation before persistence
- [ ] Implement claim completeness quality gate (non-empty headline/who_cares)
- [ ] Refactor `lift_topics.py` to use clustering model or LLM (not just keywords)
- [ ] Enforce <= 20% misc threshold in tests
- [ ] Add topic stability verification (deterministic IDs on fixed dataset)
- [ ] Persist model_route_used per claim/topic run

### Stage C: MCP-Backed Enrichment + Model-Based Editorial
- [ ] Implement `enrich_topics.py` with session-managed web browsing (MCP tools)
- [ ] Enforce `fetched_ok=1` gating for all citations
- [ ] Add credibility scoring based on source patterns
- [ ] Refactor `generate_editorial.py` to call LLM models via model routing
- [ ] Add editorial quality gates (tone, angle consistency, outline structure)
- [ ] Implement verification checklist enforcement (must have >= 3 sections)

### Stage D: Orchestration + Model Routing
- [ ] Wire model routing in `run_pipeline.py` for extractor/topic-lifter/editorial
- [ ] Add stage-level timeout configuration
- [ ] Implement per-stage retry with fallback route logging
- [ ] Enhance `run_metrics` with model_route_used tracking
- [ ] Add failure context capture (error messages, stack traces)

### Stage E: Cron + Observability
- [ ] Install `ops/cron/daily_pipeline.cron` on host machine
- [ ] Configure log rotation for `data/pipeline.log`
- [ ] Add failure notification hooks (webhook/email placeholder)
- [ ] Implement 7-day soak test with baseline comparison
- [ ] Create data cleanup/archive script for generated artifacts

### Quality Gates & Acceptance Criteria
- [ ] All tests pass: `python3 -m unittest discover -s tests`
- [ ] Lint clean: `ruff check .` (0 errors)
- [ ] Typecheck clean: `basedpyright` (0 errors)
- [ ] >= 95% claims have non-empty headline/who_cares
- [ ] <= 20% claims in misc bucket
- [ ] All editorial candidates have >= 3 outline sections
- [ ] All citations have fetched_ok=1
- [ ] Full pipeline run completes without hard failures
- [ ] E2E test on fixed fixture produces deterministic top-N

### Ops Niceties
- [ ] Add Makefile with setup/test/run targets
- [ ] Add pre-commit hooks for lint/typecheck
- [ ] Add LICENSE file
- [ ] Add CONTRIBUTING.md guide
- [ ] Add data cleanup/archive script
