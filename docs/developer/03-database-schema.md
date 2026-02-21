# Database Schema

This document describes the complete SQLite database schema for the daily-blog pipeline.

## Database Overview

- **Location**: `data/daily-blog.db`
- **Type**: SQLite 3
- **Connection**: All modules use `sqlite3.connect()` with this path
- **Isolation Level**: Default (autocommit disabled, explicit commits)

### Design Principles

1. **Immutable History**: Rows are never deleted (except manual cleanup)
2. **Time-Based Tracking**: All tables include `created_at` timestamps
3. **Run-Based Organization**: Most data is keyed by `run_id` for reproducibility
4. **Soft Relationships**: Foreign keys use text IDs for flexibility

---

## Core Tables

### 1. `mentions`

Raw RSS/Atom feed entries before any processing.

**Created by**: `ingest_rss.py`

| Column | Type | Description |
|--------|------|-------------|
| `entry_id` | TEXT | Primary key, computed from feed URL + entry ID |
| `source` | TEXT | Feed source name (e.g., "reddit") |
| `feed_url` | TEXT | Original RSS feed URL |
| `title` | TEXT | Entry title |
| `url` | TEXT | Entry link URL |
| `published` | TEXT | Publication timestamp (ISO 8601) |
| `summary` | TEXT | Entry summary/content |
| `fetched_at` | TEXT | When this entry was fetched (ISO 8601) |

**Indexes**: Primary key on `entry_id`

**Notes**:
- `entry_id` is SHA256 hash of `feed_url + entry_id` to handle duplicate entries
- `published` may be `NULL` for feeds without timestamps
- Content may contain HTML (use `strip_html()` to clean)

**Related Tables**:
- `canonical_items` (via deduplication logic)
- `claims` (via `entry_id`)

---

### 2. `canonical_items`

Deduplicated content items with tracking of first/last seen.

**Created by**: `score_rss.py`

| Column | Type | Description |
|--------|------|-------------|
| `canonical_key` | TEXT | Primary key, content-based deduplication key |
| `title` | TEXT | Normalized title |
| `url` | TEXT | Canonical URL |
| `source` | TEXT | Source domain |
| `first_seen_at` | TEXT | First occurrence timestamp |
| `last_seen_at` | TEXT | Most recent occurrence timestamp |
| `seen_count` | INTEGER | Number of times this content appeared |

**Indexes**: Primary key on `canonical_key`

**Notes**:
- `canonical_key` computed from normalized title + URL
- Used to detect trending content (high `seen_count`)
- Enables "novelty" scoring based on `first_seen_at`

---

### 3. `candidate_scores`

Scored and ranked candidates per run.

**Created by**: `score_rss.py`

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | TEXT | Pipeline run identifier |
| `entry_id` | TEXT | Reference to `mentions.entry_id` |
| `topic` | TEXT | Assigned topic category |
| `novelty_status` | TEXT | "novel", "recent", or "stale" |
| `novelty_score` | REAL | Novelty component (0-1) |
| `recency_score` | REAL | Recency component (0-1) |
| `corroboration_score` | REAL | Cross-source validation (0-1) |
| `source_diversity_score` | REAL | Domain variety (0-1) |
| `actionability_score` | REAL | Practical utility (0-1) |
| `final_score` | REAL | Weighted composite score (0-1) |
| `rank_index` | INTEGER | Rank within topic (1=best) |
| `created_at` | TEXT | Timestamp of scoring |

**Indexes**: Primary key on (`run_id`, `entry_id`)

**Notes**:
- Scores are computed using rules from `config/rules-engine.json`
- Only top N candidates per topic are stored (configurable)
- Used to generate `data/daily_board.md`

---

### 4. `claims`

Structured claims extracted from mentions.

**Created by**: `extract_claims.py`

| Column | Type | Description |
|--------|------|-------------|
| `claim_id` | TEXT | Primary key, SHA256 hash |
| `entry_id` | TEXT | Reference to `mentions.entry_id` |
| `headline` | TEXT | One-sentence claim summary |
| `who_cares` | TEXT | Why this matters (audience) |
| `problem_pressure` | TEXT | Problem being addressed |
| `proposed_solution` | TEXT | Suggested approach |
| `evidence_type` | TEXT | Type of evidence (e.g., "anecdote", "data") |
| `sources_json` | TEXT | JSON array of source URLs |
| `model_route_used` | TEXT | Which model performed extraction |
| `created_at` | TEXT | Timestamp of extraction |

**Indexes**: Primary key on `claim_id`

**Notes**:
- Extracted via LLM, may contain errors
- `sources_json` is parsed JSON array
- Claims without evidence are filtered downstream

---

### 5. `topic_clusters`

Grouped topics with metadata.

**Created by**: `lift_topics.py`

| Column | Type | Description |
|--------|------|-------------|
| `topic_id` | TEXT | Primary key, UUID |
| `parent_topic_slug` | TEXT | Original topic category |
| `parent_topic_label` | TEXT | Human-readable topic name |
| `normalized_topic_slug` | TEXT | Normalized category (added later) |
| `normalized_topic_label` | TEXT | Normalized label (added later) |
| `curation_notes` | TEXT | Curator's notes (added later) |
| `curator_model_route_used` | TEXT | Model used for curation (added later) |
| `why_it_matters` | TEXT | Importance explanation |
| `time_horizon` | TEXT | "immediate", "near-term", "long-term" |
| `claim_count` | INTEGER | Number of claims in this topic |
| `keywords_json` | TEXT | JSON array of topic keywords |
| `model_route_used` | TEXT | Model used for lifting |
| `created_at` | TEXT | Timestamp of creation |

**Indexes**: Primary key on `topic_id`

**Migration History**:
- `normalized_topic_slug`: Added for topic normalization
- `normalized_topic_label`: Added for topic normalization
- `curation_notes`: Added for manual curation
- `curator_model_route_used`: Added for tracking curation model

**Notes**:
- Topics are hierarchical (parent → normalized)
- `keywords_json` used for matching and enrichment queries

---

### 6. `claim_topic_map`

Many-to-many relationship between claims and topics.

**Created by**: `lift_topics.py`

| Column | Type | Description |
|--------|------|-------------|
| `claim_id` | TEXT | Reference to `claims.claim_id` |
| `topic_id` | TEXT | Reference to `topic_clusters.topic_id` |
| `model_route_used` | TEXT | Model used for assignment (added later) |
| `created_at` | TEXT | Timestamp of assignment |

**Indexes**: Primary key on (`claim_id`, `topic_id`)

**Migration History**:
- `model_route_used`: Added for tracking which model made the assignment

**Notes**:
- Enables claims to appear in multiple topics
- Used by enrichment to find relevant sources

---

### 7. `enrichment_sources`

Evidence sources gathered for topics.

**Created by**: `enrich_topics.py`

| Column | Type | Description |
|--------|------|-------------|
| `topic_id` | TEXT | Reference to `topic_clusters.topic_id` |
| `query_terms_json` | TEXT | JSON array of search terms used |
| `domain` | TEXT | Source domain |
| `url` | TEXT | Full source URL |
| `stance` | TEXT | "supports", "challenges", "neutral" |
| `credibility_guess` | TEXT | "high", "medium", "low" |
| `fetched_ok` | INTEGER | 1 if URL was fetchable, 0 otherwise |
| `created_at` | TEXT | Timestamp of discovery |

**Indexes**: Primary key on (`topic_id`, `url`)

**Notes**:
- Credibility is domain-based heuristic
- `fetched_ok` enables filtering dead links
- Used to compute evidence scores for topics

---

### 8. `editorial_candidates`

Generated outlines and editorial content.

**Created by**: `generate_editorial.py`

| Column | Type | Description |
|--------|------|-------------|
| `topic_id` | TEXT | Primary key, references `topic_clusters` |
| `title_options_json` | TEXT | JSON array of title options |
| `outline_markdown` | TEXT | Structured outline in Markdown |
| `narrative_draft_markdown` | TEXT | Draft narrative content (added later) |
| `talking_points_json` | TEXT | JSON array of key points |
| `verification_checklist_json` | TEXT | JSON array of verification items |
| `angle` | TEXT | Editorial angle/perspective (added later) |
| `audience` | TEXT | Target audience (added later) |
| `model_route_used` | TEXT | Model used for generation |
| `created_at` | TEXT | Timestamp of generation |

**Indexes**: Primary key on `topic_id`

**Migration History**:
- `angle`: Added for editorial angle tracking
- `audience`: Added for audience targeting
- `narrative_draft_markdown`: Added for draft content
- `evidence_status`: Added for evidence validation state
- `evidence_reasons_json`: Added for evidence validation reasons
- `evidence_ui_state`: Added for UI display state

**Notes**:
- All JSON columns are arrays
- `outline_markdown` is the primary deliverable

---

## Operational Tables

### 9. `run_metrics`

Pipeline execution tracking and performance monitoring.

**Created by**: `run_pipeline.py`

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | TEXT | Pipeline run identifier (ISO 8601 timestamp) |
| `stage_name` | TEXT | Pipeline stage name |
| `status` | TEXT | "completed", "failed", "skipped" |
| `started_at` | TEXT | Stage start timestamp |
| `finished_at` | TEXT | Stage end timestamp |
| `duration_ms` | INTEGER | Stage duration in milliseconds |
| `row_count` | INTEGER | Number of rows processed |
| `model_route_used` | TEXT | Intended model from config |
| `actual_model_used` | TEXT | Actual model that responded (added later) |
| `error_message` | TEXT | Error details if failed |

**Indexes**: Primary key on (`run_id`, `stage_name`)

**Migration History**:
- `actual_model_used`: Added to track fallback model usage

**Notes**:
- Use for debugging recurring failures
- Track model usage patterns over time
- Identify performance bottlenecks

---

### 10. `run_config_snapshots`

Configuration snapshots for reproducibility.

**Created by**: `run_pipeline.py`

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | TEXT | Primary key, references run_metrics |
| `snapshot_hash` | TEXT | SHA256 of config content |
| `snapshot_json` | TEXT | Full config as JSON |
| `created_at` | TEXT | Timestamp of snapshot |

**Notes**:
- Enables reproducing runs with exact configuration
- Compare configs across runs to debug changes

---

### 11. `run_deltas`

Differences between consecutive runs.

**Created by**: `run_pipeline.py`

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | TEXT | Primary key |
| `base_run_id` | TEXT | Previous run to compare against |
| `delta_json` | TEXT | JSON representation of changes |
| `created_at` | TEXT | Timestamp |

**Notes**:
- Tracks how outputs change between runs
- Useful for detecting model drift or config changes

---

## Database Diagram

```
mentions (entry_id PK)
    ↓ (1:N)
canonical_items (canonical_key PK)
    ↓ (1:N)
candidate_scores (run_id, entry_id PK)

mentions (entry_id PK)
    ↓ (1:N)
claims (claim_id PK)
    ↓ (N:M via claim_topic_map)
topic_clusters (topic_id PK)
    ↓ (1:N)
enrichment_sources (topic_id, url PK)
    ↓ (1:N)
editorial_candidates (topic_id PK)

All tables → run_metrics (run_id, stage_name PK)
```

---

## Common Queries

### Get Latest Run ID

```sql
SELECT MAX(run_id) FROM run_metrics WHERE status = 'completed';
```

### Get Topics by Score

```sql
SELECT
    cs.topic,
    cs.final_score,
    cs.rank_index,
    m.title,
    m.url
FROM candidate_scores cs
JOIN mentions m ON cs.entry_id = m.entry_id
WHERE cs.run_id = ?
ORDER BY cs.final_score DESC;
```

### Get Topic Enrichment Summary

```sql
SELECT
    tc.parent_topic_label,
    COUNT(DISTINCT es.url) as source_count,
    SUM(es.fetched_ok) as fetched_count,
    AVG(CASE es.credibility_guess
        WHEN 'high' THEN 3
        WHEN 'medium' THEN 2
        WHEN 'low' THEN 1
        ELSE 0
    END) as avg_credibility
FROM topic_clusters tc
LEFT JOIN enrichment_sources es ON tc.topic_id = es.topic_id
GROUP BY tc.topic_id;
```

### Get Run Performance

```sql
SELECT
    stage_name,
    AVG(duration_ms) as avg_duration_ms,
    AVG(row_count) as avg_row_count,
    COUNT(*) as runs,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failures
FROM run_metrics
GROUP BY stage_name
ORDER BY avg_duration_ms DESC;
```

---

## Maintenance

### Database Size Monitoring

```bash
sqlite3 data/daily-blog.db "SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size();"
```

### Vacuum (Reclaim Space)

```sql
VACUUM;
```

### Check Integrity

```sql
PRAGMA integrity_check;
```

---

## Schema Migrations

The database uses gradual migrations via `ALTER TABLE` when new columns are needed. Check each module's `init_*` function for migration logic.

**Adding a New Column:**

```python
# Check if column exists
columns = {row[1] for row in conn.execute("PRAGMA table_info(table_name)").fetchall()}
if "new_column" not in columns:
    conn.execute("ALTER TABLE table_name ADD COLUMN new_column TEXT NOT NULL DEFAULT ''")
```
