# System Architecture

This document describes the high-level architecture, data flow, and component relationships in the daily-blog pipeline.

## Overview

Daily Blog is a **stage-based content pipeline** that transforms RSS feeds into editorial-ready content through a series of discrete, restartable stages.

### Core Principles

1. **Stage Isolation**: Each stage is independently executable and restartable
2. **State Persistence**: All intermediate results are stored in SQLite
3. **Idempotency**: Re-running a stage produces deterministic results
4. **Fallback Handling**: LLM calls automatically fall back to alternative models
5. **Configuration-Driven**: Behavior controlled via JSON config files

---

## High-Level Data Flow

```
┌─────────────┐
│  feeds.txt  │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│                      RSS FEEDS                              │
└──────┬──────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│  1. INGEST_RSS                                              │
│  ─────────────                                              │
│  • Fetch RSS/Atom feeds                                     │
│  • Normalize to mentions table                              │
│  • Write mentions.jsonl                                     │
│  Output: mentions table                                     │
└──────┬──────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│  2. SCORE_RSS                                               │
│  ────────────                                               │
│  • Deduplicate content (canonical_items)                    │
│  • Apply scoring rules (novelty, recency, etc.)             │
│  • Rank by final_score                                      │
│  Output: canonical_items, candidate_scores, daily_board.md  │
└──────┬──────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│  3. EXTRACT_CLAIMS                                          │
│  ─────────────────                                          │
│  • Extract structured claims via LLM                        │
│  • Store with metadata and evidence types                   │
│  Output: claims table                                       │
└──────┬──────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│  4. LIFT_TOPICS                                             │
│  ──────────────                                             │
│  • Cluster claims into topics via LLM                       │
│  • Generate topic metadata and keywords                     │
│  Output: topic_clusters, claim_topic_map                    │
└──────┬──────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│  5. ENRICH_TOPICS                                           │
│  ───────────────                                            │
│  • Search for supporting evidence                           │
│  • Fetch and verify URLs                                    │
│  • Score credibility                                        │
│  Output: enrichment_sources table                           │
└──────┬──────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│  6. GENERATE_EDITORIAL                                      │
│  ────────────────────                                       │
│  • Create outlines from topics + evidence                   │
│  • Generate title options and talking points                │
│  • Build verification checklists                            │
│  Output: editorial_candidates, top_outlines.md,             │
│          research_pack.json                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Component Responsibilities

### Pipeline Stages

| Stage | Module | Input | Output | LLM Dependency |
|-------|--------|-------|--------|----------------|
| 1. Ingest | `ingest_rss.py` | `feeds.txt` | `mentions` table, `mentions.jsonl` | None |
| 2. Score | `score_rss.py` | `mentions` | `canonical_items`, `candidate_scores`, `daily_board.md` | deterministic-code |
| 3. Extract | `extract_claims.py` | `mentions` | `claims` | ollama:qwen2.5:7b |
| 4. Lift | `lift_topics.py` | `claims` | `topic_clusters`, `claim_topic_map` | ollama:qwen2.5:14b |
| 5. Enrich | `enrich_topics.py` | `topic_clusters`, `claims` | `enrichment_sources` | codex-5.3 |
| 6. Generate | `generate_editorial.py` | `topic_clusters`, `enrichment_sources` | `editorial_candidates`, `top_outlines.md`, `research_pack.json` | ollama:qwen2.5:14b |

### Supporting Components

| Component | Module | Purpose |
|-----------|--------|---------|
| **Orchestrator** | `run_pipeline.py` | Coordinates stage execution, tracks metrics |
| **LLM Integration** | `orchestrator_utils.py` | Model routing, fallback, schema validation |
| **Topic Normalization** | `normalize_topics.py` | Post-processes topic labels |
| **Data Viewer** | `scripts/docs_viewer.py` | Local documentation server |
| **Insights Dashboard** | `scripts/insights_viewer.py` | SQLite-backed data visualization |

---

## State Management

The pipeline maintains state in **SQLite** to enable:

1. **Restartability**: Re-run any stage without re-processing
2. **Historical Analysis**: Track changes over time
3. **Debugging**: Inspect intermediate outputs
4. **Idempotency**: Detect already-processed items

### Database Tables by Stage

```
Stage          Tables Created/Modified
─────────────────────────────────────────────────
ingest_rss     → mentions
score_rss      → canonical_items, candidate_scores
extract_claims → claims
lift_topics    → topic_clusters, claim_topic_map
enrich_topics  → enrichment_sources
generate_editorial → editorial_candidates
─────────────────────────────────────────────────
All stages     → run_metrics (tracking)
```

### State Transitions

```
┌──────────────┐
│   feeds.txt  │  (static config)
└──────┬───────┘
       │
       ▼
┌──────────────┐      ┌─────────────────┐
│   mentions   │ ───→ │ canonical_items │  (deduplicated)
└──────────────┘      └─────────────────┘
       │
       ▼
┌──────────────┐
│    claims    │  (extracted from mentions)
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   topics     │  (clustered from claims)
└──────┬───────┘
       │
       ▼
┌──────────────┐      ┌─────────────────────┐
│ enrichment   │ ───→ │ editorial_candidates │
│  _sources    │      └─────────────────────┘
└──────────────┘
```

---

## Model Routing Architecture

The `orchestrator_utils.py` module implements a **fallback chain** for LLM calls:

```
┌──────────────────────────────────────────────────────────────┐
│                       call_model()                           │
│                         │                                    │
│                         ▼                                    │
│              ┌─────────────────────┐                         │
│              │ Load model-routing  │                         │
│              │    config JSON      │                         │
│              └─────────┬───────────┘                         │
│                        │                                     │
│                        ▼                                     │
│              ┌─────────────────────┐                         │
│              │  Try PRIMARY model  │ ──fail──→ ┐            │
│              └─────────┬───────────┘           │            │
│                        │ success               │            │
│                        ▼                       │            │
│              ┌─────────────────────┐           │            │
│              │  Validate Response  │           ▼            │
│              │     (if schema)     │   ┌────────────────┐  │
│              └─────────┬───────────┘   │ Try FALLBACK   │  │
│                        │ success       │    model       │  │
│                        ▼               └────────┬───────┘  │
│              ┌─────────────────────┐            │          │
│              │   Return Content    │ ──fail─────┘          │
│              └─────────────────────┘                        │
│                        │                                    │
│                        ▼                                    │
│              ┌─────────────────────┐                        │
│              │ Raise ModelCallError│                        │
│              └─────────────────────┘                        │
└──────────────────────────────────────────────────────────────┘
```

### Model Resolution

Models are specified with a **tool prefix** format:

```
tool:model-name

Examples:
- codex-5.3          → Codex CLI
- ollama:qwen2.5:7b  → Ollama CLI
- gemini-3-pro       → Gemini CLI
- model-name         → OpenCode CLI (default)
```

---

## Configuration Architecture

Two configuration files control pipeline behavior:

### rules-engine.json

```json
{
  "hard_rules": {...},      // Filtering and limits
  "novelty": {...},         // Time-based scoring
  "weights": {...},         // Composite score weights
  "topics": {...},          // Topic keyword buckets
  "actionability_keywords": [...],  // Practical content detection
  "evidence_thresholds": {...},     // Enrichment quality gates
  "evidence_fail_states": {...}     // Error handling
}
```

**Used by**: `score_rss.py`, `enrich_topics.py`

### model-routing.json

```json
{
  "stage_name": {
    "primary": "model-name",
    "fallback": "model-name",
    "local_candidates": [...]  // Optional auto-selection pool
  }
}
```

**Used by**: `orchestrator_utils.py` (all LLM calls)

---

## Error Handling Strategy

### Stage-Level

Each stage implements a **try-catch-commit** pattern:

```python
try:
    # Do work
    conn.commit()  # Only commit on success
except Exception as e:
    logger.error("Stage failed", exc_info=True)
    raise  # Let orchestrator handle
```

### LLM-Level

Model calls use **automatic fallback**:

```python
try:
    result = call_model(...)  # Internal fallback logic
except ModelCallError as e:
    # Both primary and fallback failed
    # Error includes details for debugging
```

### Run-Level

The orchestrator tracks **run_metrics** for each stage:

```
status: "completed" | "failed" | "skipped"
error_message: <details if failed>
duration_ms: <performance tracking>
```

---

## Performance Considerations

### Bottlenecks

| Stage | Typical Duration | Primary Bottleneck |
|-------|------------------|---------------------|
| ingest_rss | 10-30s | Network I/O |
| score_rss | 1-5s | Database queries |
| extract_claims | 2-5min | LLM calls |
| lift_topics | 30s-2min | LLM calls |
| enrich_topics | 5-15min | URL fetching + LLM |
| generate_editorial | 1-3min | LLM calls |

### Optimization Strategies

1. **Parallel Feeds**: `ingest_rss` fetches feeds concurrently
2. **Batch Processing**: LLM calls batch when possible
3. **Local Models**: Use Ollama for low-latency stages
4. **Caching**: `canonical_items` prevents re-scoring seen content

---

## Extension Points

### Adding a New Stage

```python
# new_stage.py
from orchestrator_utils import call_model

def main():
    result = call_model(
        stage_name="new_stage",
        prompt="...",
        schema={...}
    )
    # Store to SQLite

if __name__ == "__main__":
    main()
```

### Adding a New Model

```json
// config/model-routing.json
{
  "existing_stage": {
    "primary": "new:model-format",
    "fallback": "existing-model"
  }
}
```

### Adding Scoring Rules

```json
// config/rules-engine.json
{
  "weights": {
    "new_dimension": 0.1
  }
}
```

---

## Data Lifecycle

```
┌────────────────────────────────────────────────────────────┐
│                     INPUT                                  │
│  • feeds.txt (static)                                      │
│  • rules-engine.json (configurable)                        │
│  • model-routing.json (configurable)                       │
└────────────────────────┬───────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────┐
│                  PROCESSING                                │
│  • Stage 1 → Stage 2 → ... → Stage 6                       │
│  • State persisted to SQLite after each stage              │
└────────────────────────┬───────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────┐
│                     OUTPUTS                                 │
│  • daily_board.md (ranked candidates)                      │
│  • top_outlines.md (editorial outlines)                    │
│  • research_pack.json (evidence packs)                     │
│  • SQLite database (full history)                          │
└────────────────────────────────────────────────────────────┘
```

---

## Monitoring & Observability

### Run Metrics

```sql
SELECT stage_name, status, duration_ms, error_message
FROM run_metrics
WHERE run_id = ?
ORDER BY started_at;
```

### Model Usage

```sql
SELECT
    model_route_used,
    actual_model_used,
    COUNT(*) as calls,
    AVG(duration_ms) as avg_duration
FROM run_metrics
WHERE actual_model_used != ''
GROUP BY model_route_used, actual_model_used;
```

### Stage Performance Trends

```sql
SELECT
    stage_name,
    DATE(created_at) as date,
    AVG(duration_ms) as avg_duration_ms,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failures
FROM run_metrics
GROUP BY stage_name, DATE(created_at)
ORDER BY date DESC, stage_name;
```
