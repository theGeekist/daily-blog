# Configuration Reference

This document provides detailed reference for all configuration files in the daily-blog pipeline.

## Configuration Files

| File | Purpose | Used By |
|------|---------|---------|
| `config/rules-engine.json` | Scoring rules, topic definitions, evidence thresholds | `score_rss.py`, `enrich_topics.py` |
| `config/model-routing.json` | Model selection per pipeline stage | `orchestrator_utils.py` |
| `config/prompts.json` | Runtime prompt modifications | `orchestrator_utils.py` |
| `.env` | Environment variables | All modules |
| `feeds.txt` | RSS feed sources | `ingest_rss.py` |

---

## rules-engine.json

Controls content scoring, topic classification, and evidence validation.

### File Structure

```json
{
  "hard_rules": {...},
  "novelty": {...},
  "weights": {...},
  "topics": {...},
  "actionability_keywords": [...],
  "evidence_thresholds": {...},
  "evidence_fail_states": {...}
}
```

### hard_rules

Content filtering and output limits.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `min_title_length` | integer | 20 | Minimum title characters to process |
| `blocked_title_keywords` | array | `["hiring", "who is hiring", "weekly thread", "daily discussion"]` | Skip entries with these in title |
| `max_candidates` | integer | 12 | Maximum candidates per topic |
| `max_per_topic` | integer | 3 | Maximum candidates per topic in final output |
| `min_final_score` | float | 0.25 | Minimum score to include in output |

**Example:**

```json
{
  "hard_rules": {
    "min_title_length": 20,
    "blocked_title_keywords": ["hiring", "who is hiring", "weekly thread"],
    "max_candidates": 12,
    "max_per_topic": 3,
    "min_final_score": 0.25
  }
}
```

**Tuning Guide:**
- Increase `min_title_length` to filter short/noisy titles
- Add keywords to `blocked_title_keywords` to filter unwanted content
- Decrease `max_candidates` for tighter shortlists
- Increase `min_final_score` for higher quality threshold

### novelty

Time-based scoring for content freshness.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `novel_days` | integer | 3 | Days considered "novel" (never seen before) |
| `recent_days` | integer | 14 | Days considered "recent" |
| `novel_score` | float | 1.0 | Score multiplier for novel content |
| `recent_score` | float | 0.6 | Score multiplier for recent content |
| `stale_score` | float | 0.2 | Score multiplier for stale content |

**Example:**

```json
{
  "novelty": {
    "novel_days": 3,
    "recent_days": 14,
    "novel_score": 1.0,
    "recent_score": 0.6,
    "stale_score": 0.2
  }
}
```

**How it Works:**

```
Content age → Score
0-3 days    → 1.0 (novel)
4-14 days   → 0.6 (recent)
15+ days    → 0.2 (stale)
```

**Tuning Guide:**
- Decrease `novel_days` for faster-moving feeds
- Increase `recent_days` for longer relevance window
- Adjust scores to change novelty impact

### weights

Composite score calculation weights.

| Key | Type | Default | Range | Description |
|-----|------|---------|-------|-------------|
| `novelty` | float | 0.3 | 0-1 | Weight for novelty score |
| `recency` | float | 0.2 | 0-1 | Weight for recency score |
| `corroboration` | float | 0.2 | 0-1 | Weight for cross-source validation |
| `source_diversity` | float | 0.15 | 0-1 | Weight for domain variety |
| `actionability` | float | 0.15 | 0-1 | Weight for practical utility |

**Formula:**

```
final_score =
  (novelty_score × 0.3) +
  (recency_score × 0.2) +
  (corroboration_score × 0.2) +
  (source_diversity_score × 0.15) +
  (actionability_score × 0.15)
```

**Example:**

```json
{
  "weights": {
    "novelty": 0.3,
    "recency": 0.2,
    "corroboration": 0.2,
    "source_diversity": 0.15,
    "actionability": 0.15
  }
}
```

**Tuning Guide:**

| Goal | Adjustment |
|------|------------|
| Prioritize new discoveries | Increase `novelty` to 0.4-0.5 |
| Focus on recent content | Increase `recency`, decrease `novelty` |
| Validate with multiple sources | Increase `corroboration` |
| Diverse source domains | Increase `source_diversity` |
| Practical how-to content | Increase `actionability` |

**Important:** Weights don't need to sum to 1.0, but keeping them normalized makes tuning easier.

### topics

Topic keyword buckets for classification.

**Structure:**

```json
{
  "topics": {
    "topic_slug": ["keyword1", "keyword2", ...],
    ...
  }
}
```

**Default Topics:**

```json
{
  "topics": {
    "ai": ["ai", "llm", "model", "gpt", "inference", "agent"],
    "engineering": ["programming", "dev", "bug", "release", "build", "refactor"],
    "web": ["javascript", "react", "css", "html", "frontend", "backend"],
    "business": ["sales", "pricing", "startup", "market", "growth", "revenue"],
    "language": ["linguistics", "etymology", "language", "grammar", "phonology"]
  }
}
```

**Adding New Topics:**

```json
{
  "topics": {
    "ai": [...],
    "security": ["security", "vulnerability", "exploit", "cve", "auth"],
    "devops": ["docker", "kubernetes", "ci/cd", "deployment", "infrastructure"]
  }
}
```

**Tuning Guide:**
- Use lowercase keywords for case-insensitive matching
- Add shorter variants of terms (e.g., both "ai" and "artificial intelligence")
- Avoid overly generic terms that create noise

### actionability_keywords

Keywords that indicate practical, actionable content.

**Default:**

```json
{
  "actionability_keywords": [
    "how to",
    "guide",
    "playbook",
    "template",
    "checklist",
    "workflow",
    "steps"
  ]
}
```

**Adding Keywords:**

```json
{
  "actionability_keywords": [
    "how to", "guide", "playbook", "template", "checklist",
    "tutorial", "example", "walkthrough", "implementation"
  ]
}
```

**Tuning Guide:**
- Add terms that match your content domain
- Remove terms that are too generic
- Use lowercase for case-insensitive matching

### evidence_thresholds

Quality gates for topic enrichment.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `min_sources` | integer | 3 | Minimum evidence sources per topic |
| `min_fetched_ratio` | float | 0.5 | Minimum ratio of successfully fetched URLs |
| `min_avg_credibility_score` | float | 2.0 | Minimum average credibility (1=low, 2=medium, 3=high) |
| `warn_min_fetched_ratio` | float | 0.7 | Warning threshold for fetch ratio |
| `warn_min_avg_credibility_score` | float | 3.0 | Warning threshold for credibility |
| `min_domain_diversity` | integer | 2 | Minimum unique domains required |
| `block_anecdote_without_min_sources` | boolean | true | Block anecdotal evidence below min_sources |

**Example:**

```json
{
  "evidence_thresholds": {
    "min_sources": 3,
    "min_fetched_ratio": 0.5,
    "min_avg_credibility_score": 2.0,
    "warn_min_fetched_ratio": 0.7,
    "warn_min_avg_credibility_score": 3.0,
    "min_domain_diversity": 2,
    "block_anecdote_without_min_sources": true
  }
}
```

**Tuning Guide:**

| Goal | Adjustment |
|------|------------|
| Stricter evidence quality | Increase `min_avg_credibility_score` to 2.5-3.0 |
| More sources required | Increase `min_sources` to 5-10 |
| Allow dead links | Decrease `min_fetched_ratio` to 0.3 |
| Require diverse domains | Increase `min_domain_diversity` to 3-4 |

### evidence_fail_states

UI states for evidence validation results.

```json
{
  "evidence_fail_states": {
    "BLOCK": {
      "ui_state": "BLOCKED: INSUFFICIENT EVIDENCE",
      "output_suppressed": true
    },
    "WARN": {
      "ui_state": "WEAK EVIDENCE",
      "output_suppressed": false
    },
    "PASS": {
      "ui_state": "EVIDENCE VERIFIED",
      "output_suppressed": false
    }
  }
}
```

**States:**
- **BLOCK**: Topic fails evidence threshold, excluded from output
- **WARN**: Topic below warning thresholds but included
- **PASS**: Topic meets all quality thresholds

---

## model-routing.json

Controls model selection for each pipeline stage with fallback support.

### File Structure

```json
{
  "stage_name": {
    "primary": "model-name",
    "fallback": "model-name",
    "local_candidates": [...]  // Optional
  }
}
```

### Stage Names

| Stage Name | Used By | Default Primary | Default Fallback |
|------------|---------|-----------------|------------------|
| `coordinator` | run_pipeline.py | codex-5.3 | gemini-3-pro |
| `extractor` | extract_claims.py | ollama:qwen2.5:7b | gemini-3-pro |
| `topic_lifter` | lift_topics.py | ollama:qwen2.5:14b | ollama:qwen2.5:7b |
| `topic_curator` | normalize_topics.py | ollama:qwen2.5:7b | ollama:llama3.1:8b |
| `enrichment` | enrich_topics.py | codex-5.3 | glm5 |
| `editorial` | generate_editorial.py | ollama:qwen2.5:14b | codex-5.3 |
| `ranker` | score_rss.py | deterministic-code | deterministic-code |

### Model Format

```
[tool:]model-name

Examples:
- codex-5.3              → Codex CLI
- ollama:qwen2.5:7b      → Ollama with qwen2.5:7b model
- gemini-3-pro           → Gemini CLI
- opencode:glm5          → OpenCode CLI with glm5 model
- model-name             → OpenCode CLI (default tool)
```

### Example Configuration

```json
{
  "coordinator": {
    "primary": "codex-5.3",
    "fallback": "gemini-3-pro"
  },
  "extractor": {
    "primary": "ollama:qwen2.5:7b",
    "fallback": "ollama:qwen2.5:14b",
    "local_candidates": [
      "ollama:qwen2.5:7b",
      "ollama:qwen2.5:14b",
      "ollama:llama3.1:8b"
    ]
  },
  "topic_lifter": {
    "primary": "ollama:qwen2.5:14b",
    "fallback": "codex-5.3"
  },
  "enrichment": {
    "primary": "codex-5.3",
    "fallback": "glm5"
  },
  "editorial": {
    "primary": "ollama:qwen2.5:14b",
    "fallback": "ollama:llama3.1:8b"
  },
  "ranker": {
    "primary": "deterministic-code",
    "fallback": "deterministic-code"
  }
}
```

### Adding a New Model

1. Install the CLI tool (e.g., `ollama`, `codex`, `gemini`)
2. Pull/download the model if needed
3. Update model-routing.json:

```json
{
  "existing_stage": {
    "primary": "your-tool:your-model",
    "fallback": "existing-backup-model"
  }
}
```

### Model Selection Strategy

| Factor | Recommendation |
|--------|----------------|
| **Speed critical** | Use local models (ollama) |
| **Quality critical** | Use cloud models (codex, gemini) |
| **Cost sensitive** | Use local models for high-volume stages |
| **Reliability** | Always configure a fallback |

### Special Case: deterministic-code

The `ranker` stage uses `deterministic-code` which is a special value indicating no LLM is used—scoring is purely algorithmic based on rules-engine.json.

---

## prompts.json

Optional runtime prompt modifications without code changes.

### File Structure

```json
{
  "stage_name": {
    "template": "... {prompt} ...",
    "prefix": "...",
    "suffix": "..."
  }
}
```

### Template Variables

- `{prompt}`: Replaced with the original prompt

### Example Configuration

```json
{
  "extractor": {
    "template": "You are a claim extraction expert.\n\n{prompt}\n\nReturn valid JSON only.",
    "prefix": "CONTEXT: Analyzing RSS feeds for daily blog content.",
    "suffix": "REMEMBER: Return only valid JSON, no markdown formatting."
  },
  "topic_lifter": {
    "prefix": "You are organizing content into topical clusters.",
    "suffix": "Ensure topics are specific enough to be actionable."
  }
}
```

### Resolution Order

1. If `template` exists, replace `{prompt}` with original prompt
2. If `template` doesn't exist, use original prompt
3. Prepend `prefix` if defined
4. Append `suffix` if defined

### Use Cases

- **Add system instructions** without modifying code
- **Enforce output format** (JSON, specific structure)
- **Add context** relevant to your use case
- **A/B test** prompts by changing config only

---

## Environment Variables (.env)

Runtime configuration via environment variables.

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_PATH` | SQLite database file path | `data/daily-blog.db` |
| `FEEDS_PATH` | RSS feeds list file | `feeds.txt` |
| `CONFIG_PATH` | Rules engine config | `config/rules-engine.json` |
| `MODEL_ROUTING_PATH` | Model routing config | `config/model-routing.json` |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `LOG_LEVEL` | Logging verbosity | `INFO` |
| `MAX_CONCURRENT_FEEDS` | Parallel feed fetch limit | `10` |
| `REQUEST_TIMEOUT_SECONDS` | HTTP request timeout | `20` |

### Example .env

```bash
# Database
DATABASE_PATH=data/daily-blog.db

# Feeds
FEEDS_PATH=feeds.txt

# Configuration
CONFIG_PATH=config/rules-engine.json
MODEL_ROUTING_PATH=config/model-routing.json

# Logging
LOG_LEVEL=INFO

# Performance
MAX_CONCURRENT_FEEDS=10
REQUEST_TIMEOUT_SECONDS=20
```

---

## feeds.txt

List of RSS/Atom feed URLs to ingest.

### Format

One URL per line:

```
https://www.reddit.com/r/programming/hot.rss
https://www.reddit.com/r/MachineLearning/new.rss
https://hnrss.org/frontpage
```

### Comments

Lines starting with `#` are ignored:

```
# Tech feeds
https://www.reddit.com/r/programming/hot.rss

# ML feeds
https://www.reddit.com/r/MachineLearning/new.rss
```

### Adding Feeds

Simply append URLs:

```
https://news.ycombinator.com/rss
https://github.com/blog/feed
```

### Feed Requirements

- Must be valid RSS or Atom format
- Must be publicly accessible (no authentication)
- HTTP/HTTPS supported
- Redirects are followed

---

## Configuration Validation

### Validate JSON Syntax

```bash
# Check rules-engine.json
python3 -m json.tool config/rules-engine.json

# Check model-routing.json
python3 -m json.tool config/model-routing.json
```

### Validate Against Schema

No automatic validation currently, but you can manually check:

```bash
# Check for required keys
python3 -c "
import json
rules = json.load(open('config/rules-engine.json'))
required = ['hard_rules', 'weights', 'topics', 'evidence_thresholds']
missing = [k for k in required if k not in rules]
if missing:
    print(f'Missing keys: {missing}')
else:
    print('All required keys present')
"
```

---

## Configuration Best Practices

1. **Version Control**: Commit configuration files to git
2. **Documentation**: Add comments via JSON schema or separate docs
3. **Validation**: Test configuration changes in development first
4. **Backups**: Keep previous working configurations
5. **Incremental Changes**: Change one parameter at a time
6. **Monitoring**: Track impact of configuration changes via run_metrics

---

## Troubleshooting Configuration

### "Stage 'X' not found"

**Cause**: Stage name in code doesn't match model-routing.json

**Fix**: Ensure exact match between stage name and config key

```json
{
  "exact_stage_name": {  // Must match code exactly
    "primary": "...",
    "fallback": "..."
  }
}
```

### "KeyError: 'weights'"

**Cause**: Missing or malformed rules-engine.json

**Fix**: Ensure all top-level keys exist

```json
{
  "hard_rules": {},
  "weights": {},
  "topics": {},
  "evidence_thresholds": {}
}
```

### Scores All Zero

**Cause**: Weights sum to zero or not applied

**Fix**: Check weights are positive numbers and stage is using config

### Model Not Used

**Cause**: model-routing.json not loaded or wrong path

**Fix**: Check `MODEL_ROUTING_PATH` in .env matches file location
