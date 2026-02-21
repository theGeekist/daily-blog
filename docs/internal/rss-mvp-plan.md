## RSS-Only MVP Plan

### Goal

Ship a reliable daily ingest pipeline that uses RSS feeds only (including Reddit RSS endpoints) and produces normalized mention records for downstream clustering and editorial work.

### Scope (MVP)

- Ingest from a curated feed list (`feeds.txt`)
- Normalize entries into a consistent JSON schema
- Persist raw normalized items to JSONL and SQLite
- Run from local machine on demand (cron-ready)

### Out of Scope (for now)

- Reddit OAuth/API usage
- X/Twitter browser automation
- Search API integrations
- LLM-based clustering/ranking

### Phase 1: Feed Inputs

1. Create and maintain `feeds.txt` with one URL per line.
2. Include Reddit feeds using:
   - `https://www.reddit.com/r/<subreddit>/hot.rss`
   - `https://www.reddit.com/r/<subreddit>/new.rss`
3. Ignore blank lines and comment lines (`# ...`).

### Phase 2: Ingest + Normalize

1. Fetch each feed over HTTP(S) with a fixed user agent.
2. Parse RSS/Atom entries.
3. Normalize to this schema:
   - `source`
   - `feed_url`
   - `entry_id`
   - `title`
   - `url`
   - `published`
   - `summary`
   - `fetched_at`

### Phase 3: Persistence

1. Append normalized records to `data/mentions.jsonl`.
2. Upsert records to SQLite at `SQLITE_PATH`.
3. Use unique key on `entry_id` to avoid duplicate inserts.

### Phase 4: Operations

1. Run manually first:
   - `python3 ingest_rss.py`
2. Verify row counts and sample output.
3. Add daily cron once output is stable.

### Phase 5: Rules Engine + Scoring

1. Configure hard rules and score weights in `config/rules-engine.json`.
2. Run scoring pipeline:
   - `python3 score_rss.py`
3. Review ranked output in `data/daily_board.md`.
4. Tune config values and rerun without code changes.

### Success Criteria

- Script runs cleanly with no credentials required.
- At least one Reddit RSS feed ingested successfully.
- JSONL and SQLite both contain normalized records.
- Re-runs do not duplicate existing rows in SQLite.
- Ranked candidates are produced deterministically from config.
