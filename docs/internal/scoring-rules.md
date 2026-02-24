## Rules Engine and Scoring Workflow

### Purpose

`score_rss.py` turns ingested mentions into ranked daily candidates using a configurable rules engine.

### Inputs

- SQLite mentions table at `SQLITE_PATH`
- Config file at `RULES_ENGINE_CONFIG` (default `config/rules-engine.json`)

### Outputs

- Ranked candidates table: `candidate_scores`
- Canonical memory table: `canonical_items`
- Daily markdown board: `SCORE_BOARD_PATH` (default `data/daily_board.md`)

### Run Commands

1. Ingest feeds:
   - `python3 ingest_rss.py`
2. Score and rank candidates:
   - `python3 score_rss.py`

### What Is Configurable

- Hard filters (`min_title_length`, `blocked_title_keywords`)
- Topic quotas (`max_candidates`, `max_per_topic`)
- Minimum score threshold (`min_final_score`)
- Novelty windows and novelty score mapping
- Weighting of each score component
- Topic keyword mapping
- Actionability keywords

### Notes on Metadata Limits

In RSS-only mode, likes/shares/upvotes are not reliably present in feed payloads.
The scoring pipeline uses proxy signals (recency, corroboration, source diversity, actionability, novelty memory) instead.
