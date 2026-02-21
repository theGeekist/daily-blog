# Pipeline Map

## Stage order

`run_pipeline.py` executes these stages in sequence:

1. `ingest_rss.py`
2. `score_rss.py`
3. `extract_claims.py`
4. `lift_topics.py`
5. `enrich_topics.py`
6. `generate_editorial.py`

## What each stage reads and writes

1) `ingest_rss.py`
- Reads: `feeds.txt`
- Writes tables: `mentions`
- Writes files: `data/mentions.jsonl`

2) `score_rss.py`
- Reads tables: `mentions`
- Writes tables: `canonical_items`, `candidate_scores`
- Writes files: `data/daily_board.md`

3) `extract_claims.py`
- Reads tables: `mentions`
- Writes tables: `claims`

4) `lift_topics.py`
- Reads tables: `claims`
- Writes tables: `topic_clusters`, `claim_topic_map`

5) `enrich_topics.py`
- Reads tables: `topic_clusters`, `claim_topic_map`, `claims`
- Writes tables: `enrichment_sources`

6) `generate_editorial.py`
- Reads tables: `topic_clusters`, `enrichment_sources`
- Writes tables: `editorial_candidates`
- Writes files: `data/top_outlines.md`, `data/research_pack.json`

## Run IDs and metrics

`run_pipeline.py` records each stage into `run_metrics` with:

- stage status
- duration
- model route and actual model
- error context on failures

Use this to debug recurring failures and measure stage performance over time.
