# daily-blog

RSS-first pipeline for daily topic discovery, evidence gathering, and editorial drafting.

## What this repo does

The pipeline reads RSS feeds, ranks items by configurable rules, lifts them into topics, enriches them with research links, and generates editorial-ready output.

Primary outputs:

- `data/daily_board.md` (ranked shortlist)
- `data/top_outlines.md` (title options and outlines)
- `data/research_pack.json` (structured sources/evidence)

## Current state

- End-to-end scripts and orchestration are implemented.
- Model routing is stage-based via `config/model-routing.json`.
- Rules/scoring are configurable via `config/rules-engine.json`.
- Tests, linting, and type-checking are available for local validation.

## Documentation

Start with `docs/README.md`.

Operator reading order:

1. `docs/operator/01-quickstart.md`
2. `docs/operator/02-pipeline-map.md`
3. `docs/operator/03-outputs-and-decisions.md`
4. `docs/operator/04-configuration-and-models.md`
5. `docs/operator/05-operations.md`

Internal design/planning references remain under `docs/internal/`.

## Optional docs viewer

Launch a simple local docs viewer:

```bash
python3 scripts/docs_viewer.py
```

Default URL:

- `http://127.0.0.1:8765/docs/viewer/index.html`

## Insights dashboard (interconnected visualizer)

Launch the local dashboard server backed by SQLite:

```bash
python3 scripts/insights_viewer.py
```

Dashboard URL:

- `http://127.0.0.1:8877/docs/viewer/dashboard.html`

What it shows:

- run health (`run_metrics`)
- top candidates with score context (`candidate_scores` + `mentions`)
- topic-level aggregation (`topic_clusters`)
- source credibility and fetch status (`enrichment_sources`)

## Requirements

- Python 3.11+

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements-dev.txt
cp .env.example .env
```

## Configure feeds

Edit `feeds.txt` and add one RSS/Atom URL per line.

## Run the pipeline

Full pipeline:

```bash
python3 run_pipeline.py
```

Stage-by-stage (manual):

```bash
python3 ingest_rss.py
python3 score_rss.py
python3 extract_claims.py
python3 lift_topics.py
python3 enrich_topics.py
python3 generate_editorial.py
```

## Key configuration

- Runtime/env: `.env` (template: `.env.example`)
- Scoring rules: `config/rules-engine.json`
- Model routing: `config/model-routing.json`

## Environment Variables

All env vars used by the code are documented in:

- `/Users/jasonnathan/Repos/daily-blog/.env.example` (full template with defaults)
- `/Users/jasonnathan/Repos/daily-blog/.env` (local runtime values)

Primary groups:

- Core paths:
  - `SQLITE_PATH`, `INGEST_FEEDS_FILE`, `INGEST_OUTPUT_JSONL`, `SCORE_BOARD_PATH`
  - `EDITORIAL_OUTLINES_PATH`, `EDITORIAL_RESEARCH_PACK_PATH`, `EDITORIAL_DOSSIER_DIR`
- Config file overrides:
  - `RULES_ENGINE_CONFIG`, `MODEL_ROUTING_CONFIG`, `PROMPTS_CONFIG`, `PIPELINE_TIMEOUTS_PATH`
- Pipeline control:
  - `PIPELINE_RETRIES`, `PIPELINE_STAGE_TIMEOUT_SECONDS`, `PIPELINE_STAGE_TIMEOUTS`
  - `PIPELINE_SKIP_STAGES`, `PIPELINE_STREAM_SUBPROCESS_OUTPUT`, `PIPELINE_TRACE`
- Extraction:
  - `EXTRACT_MAX_MENTIONS`, `EXTRACT_PROGRESS_EVERY`
- Topic lifting/curation:
  - `TOPIC_LIFTER_BATCH_SIZE`, `TOPIC_LIFTER_TIMEOUT_BUFFER_SECONDS`
  - `TOPIC_LIFTER_FAILFAST_ON_TIMEOUT`, `TOPIC_CURATOR_BATCH_SIZE`, `FORCE_TOPIC_RECURATION`
- Enrichment:
  - `ENRICH_SKIP_MODEL`, `ENRICH_FETCH_TIMEOUT_SECONDS`, `ENRICH_FETCH_RETRIES`
  - `ENRICH_FETCH_BACKOFF_SECONDS`, `ENRICH_FETCH_USER_AGENT`
  - `ENRICH_DISCOVER_LIMIT`, `ENRICH_MAX_KNOWN_CLAIM_URLS`, `ENRICH_MAX_TOPICS`
  - `ENRICH_MIN_DOMAIN_DIVERSITY`, `ENRICH_MAX_PER_DOMAIN`, `ENRICH_MIN_CREDIBLE_COUNT`
  - `ENRICH_PROGRESS_EVERY`, `ENRICH_SEARCH_BACKEND`, `SEARXNG_BASE_URL`, `SEARXNG_ENGINES`
- Editorial:
  - `EDITORIAL_INCLUDE_MISC`, `EDITORIAL_STATIC_ONLY`, `TOPIC_CONFIDENCE_THRESHOLD`
- Model provider timeouts:
  - `OLLAMA_TIMEOUT_SECONDS`, `GEMINI_TIMEOUT_SECONDS`, `GEMINI_CLI_TIMEOUT_SECONDS`, `MODEL_CLI_TIMEOUT_SECONDS`
- Gemini/Google auth:
  - `GOOGLE_API_KEY`
  - `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`
- Internal runtime-set (not typically user-configured):
  - `RUN_ID`, `PIPELINE_RUN_ID`, `MODEL_NAME`, `MODEL_ROUTE`, `MODEL_ROUTING_STAGE`, `STAGE_TIMEOUT_SECONDS`

## Validate locally

```bash
ruff check .
basedpyright
python3 -m unittest discover -s tests
```

## Operations

- Cron template: `ops/cron/daily_pipeline.cron`
- Operations runbook: `ops/runbook.md`
- Soak test: `scripts/soak_test.py`
- Cleanup/archive: `scripts/cleanup_data.py`
