# Developer Documentation

This section contains technical documentation for contributors and maintainers of the daily-blog pipeline.

## Overview

Daily Blog is an RSS-first content pipeline that:
1. Ingests RSS/Atom feeds
2. Scores and ranks content using configurable rules
3. Extracts structured claims via LLM
4. Clusters claims into topics
5. Enriches topics with supporting evidence
6. Generates editorial-ready outlines

## Documentation Index

### Getting Started

| Document | Description |
|----------|-------------|
| [01-architecture.md](01-architecture.md) | System architecture, data flow, and component responsibilities |
| [02-api-reference.md](02-api-reference.md) | Core API documentation for `orchestrator_utils.py` and LLM integration |
| [03-database-schema.md](03-database-schema.md) | Complete SQLite database schema and table relationships |

### Configuration & Extension

| Document | Description |
|----------|-------------|
| [04-configuration-reference.md](04-configuration-reference.md) | Detailed reference for `rules-engine.json` and `model-routing.json` |
| [05-testing-guide.md](05-testing-guide.md) | Test philosophy, running tests, and writing new tests |
| [06-extending-the-pipeline.md](06-extending-the-pipeline.md) | Guide for adding new stages and extending functionality |

## Quick Reference

### Pipeline Stages

```python
# run_pipeline.py execution order
1. ingest_rss.py      # Fetch and normalize RSS feeds
2. score_rss.py       # Apply scoring rules and rank
3. extract_claims.py  # Extract structured claims
4. lift_topics.py     # Cluster claims into topics
5. enrich_topics.py   # Gather supporting evidence
6. generate_editorial.py  # Create outlines and research packs
```

### Key Files

| File | Purpose |
|------|---------|
| `run_pipeline.py` | Main orchestrator |
| `orchestrator_utils.py` | LLM integration layer |
| `config/rules-engine.json` | Scoring rules and thresholds |
| `config/model-routing.json` | Model selection per stage |
| `feeds.txt` | RSS feed sources |

### Database Location

- **Path**: `data/daily-blog.db`
- **Type**: SQLite
- **Tables**: 7 tables (mentions, canonical_items, claims, topic_clusters, claim_topic_map, enrichment_sources, editorial_candidates, run_metrics)

## Development Workflow

```bash
# Set up environment
make setup

# Run checks
make check          # Run all checks (lint, typecheck, test)
make lint           # Ruff linter
make typecheck      # basedpyright
make test           # Unit tests

# Run pipeline
make run            # Full pipeline
python3 <stage>.py  # Individual stage
```

## Related Documentation

- [Operator Documentation](../operator/README.md) - For running and operating the pipeline
- [Contributing Guide](../../CONTRIBUTING.md) - For contribution guidelines
- [Internal Docs](../internal/) - Design notes and planning documents
