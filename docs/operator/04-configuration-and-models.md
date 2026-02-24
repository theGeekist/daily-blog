# Configuration and Models

## Main configuration files

- `.env` (runtime paths and retry knobs)
- `config/rules-engine.json` (ranking behavior)
- `config/model-routing.json` (which model each stage uses)

## `.env` knobs you will likely tune

- `INGEST_FEEDS_FILE`: RSS source list path
- `INGEST_MAX_ITEMS_PER_FEED`: ingest depth
- `SQLITE_PATH`: main database
- `RULES_ENGINE_CONFIG`: scoring config location
- `SCORE_BOARD_PATH`, `EDITORIAL_OUTLINES_PATH`, `EDITORIAL_RESEARCH_PACK_PATH`: output destinations
- `PIPELINE_RETRIES`: retry count for stage failures
- `PIPELINE_STAGE_TIMEOUTS`: optional JSON map of stage timeout overrides

Example stage timeout override:

```bash
PIPELINE_STAGE_TIMEOUTS='{"enrich_topics":420,"generate_editorial":420}'
```

## How model integration works

Model selection is stage-based in `config/model-routing.json`:

- `extractor`
- `topic_lifter`
- `enrichment`
- `editorial`

Execution flow:

1. stage calls `orchestrator_utils.call_model(...)`
2. primary model is used first
3. on failure, fallback model is attempted
4. route + actual model are written to `run_metrics`

## How to tweak ranking behavior

Edit `config/rules-engine.json`:

- `hard_rules`: candidate caps and hard filters
- `weights`: relative weight of score components
- `novelty`: freshness windows
- `topics`: keyword taxonomy

Practical tuning examples:

- too many weak items -> raise `hard_rules.min_final_score`
- too repetitive topics -> tighten novelty window and lower `max_per_topic`
- too little breadth -> lower source/topic caps and rebalance weights
