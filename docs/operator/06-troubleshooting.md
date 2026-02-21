# Troubleshooting

This document provides solutions for common issues when running the daily-blog pipeline.

## Quick Diagnostics

### Check Pipeline Status

```bash
# View most recent run metrics
sqlite3 data/daily-blog.db "SELECT run_id, stage_name, status, duration_ms FROM run_metrics ORDER BY started_at DESC LIMIT 20;"

# Check for failures
sqlite3 data/daily-blog.db "SELECT run_id, stage_name, error_message FROM run_metrics WHERE status = 'failed' ORDER BY started_at DESC LIMIT 10;"
```

### Check Model Usage

```bash
# See which models were actually used
sqlite3 data/daily-blog.db "SELECT stage_name, model_route_used, actual_model_used, status FROM run_metrics ORDER BY started_at DESC LIMIT 10;"
```

### Check Database State

```bash
# Count rows in each table
sqlite3 data/daily-blog.db "
SELECT 'mentions' as table_name, COUNT(*) as count FROM mentions
UNION ALL SELECT 'canonical_items', COUNT(*) FROM canonical_items
UNION ALL SELECT 'candidate_scores', COUNT(*) FROM candidate_scores
UNION ALL SELECT 'claims', COUNT(*) FROM claims
UNION ALL SELECT 'topic_clusters', COUNT(*) FROM topic_clusters
UNION ALL SELECT 'editorial_candidates', COUNT(*) FROM editorial_candidates;
"
```

---

## Common Errors

### Model & CLI Errors

#### "CLI tool not found: X"

**Cause**: The specified CLI tool (ollama, codex, gemini) is not installed or not in PATH.

**Solution**:
```bash
# Check if tool is installed
which ollama
which codex
which gemini

# Install missing tools
# For Ollama:
curl -fsSL https://ollama.com/install.sh | sh

# For Codex/Gemini, follow their installation guides
```

#### "CLI returned non-zero status X for model 'Y'"

**Cause**: Model execution failed, model doesn't exist, or invalid parameters.

**Solution**:
```bash
# Test model directly
ollama run qwen2.5:7b "test"  # For Ollama
codex run -m codex-5.3 "test" # For Codex

# List available models
ollama list                    # For Ollama

# Pull missing model
ollama pull qwen2.5:7b
```

#### "CLI call timed out after 120s"

**Cause**: Model took too long to respond (common with large models or slow hardware).

**Solution**:
- Use a smaller/faster model
- Check system resources (CPU/RAM)
- Increase timeout in `orchestrator_utils.py`:
  ```python
  DEFAULT_TIMEOUT_SECONDS = 300  # Increase from 120
  ```

#### "No valid JSON found in CLI output"

**Cause**: LLM returned non-JSON response or malformed JSON.

**Solution**:
```json
// config/prompts.json - Add explicit JSON instructions
{
  "your_stage": {
    "suffix": "Return ONLY valid JSON, no markdown formatting, no explanations."
  }
}
```

Or use a model with better JSON support:
```json
// config/model-routing.json
{
  "your_stage": {
    "primary": "model-with-good-json-support",
    "fallback": "backup-model"
  }
}
```

---

### Configuration Errors

#### "Stage 'X' not found in model-routing.json"

**Cause**: Stage name in code doesn't match config key.

**Solution**:
```json
// config/model-routing.json
{
  "exact_stage_name_from_code": {  // Must match exactly
    "primary": "...",
    "fallback": "..."
  }
}
```

#### "KeyError: 'weights'"

**Cause**: Missing or malformed `config/rules-engine.json`.

**Solution**:
```bash
# Validate JSON syntax
python3 -m json.tool config/rules-engine.json

# Ensure required top-level keys exist:
# hard_rules, weights, topics, evidence_thresholds
```

#### "Config file not found: config/... "

**Cause**: Configuration file missing or incorrect path.

**Solution**:
```bash
# Check .env file
cat .env | grep CONFIG_PATH

# Create missing config
cp config/rules-engine.json.example config/rules-engine.json

# Or verify path
ls -la config/
```

---

### Database Errors

#### "SQLite database is locked"

**Cause**: Another process is using the database, or previous run crashed.

**Solution**:
```bash
# Check for running processes
ps aux | grep python

# Kill stuck pipeline processes
pkill -f run_pipeline.py

# If database is truly stuck, make a backup and reset:
cp data/daily-blog.db data/daily-blog.db.backup
rm data/daily-blog.db
# Then re-run pipeline
```

#### "no such table: X"

**Cause**: Database schema not initialized, or wrong database file.

**Solution**:
```bash
# Verify database path
echo $DATABASE_PATH

# Check if database exists and has tables
sqlite3 data/daily-blog.db ".tables"

# If missing tables, re-run from ingest stage
python3 ingest_rss.py
```

#### "UNIQUE constraint failed: mentions.entry_id"

**Cause**: Attempting to insert duplicate entry_id (shouldn't happen with INSERT OR IGNORE).

**Solution**: This is typically a code issue. Check that upsert logic is correct:
```python
# Should use INSERT OR IGNORE
conn.execute("INSERT OR IGNORE INTO mentions ...")
```

---

### Feed Errors

#### "HTTP Error 404: Not Found"

**Cause**: Feed URL is invalid or no longer exists.

**Solution**:
```bash
# Test feed URL directly
curl -I "https://example.com/feed.rss"

# Update feeds.txt with valid URLs
# Comment out problematic feeds with #
```

#### "RSS parsing failed"

**Cause**: Feed is not valid RSS/Atom format.

**Solution**:
```bash
# Validate feed with online tool
# https://validator.w3.org/feed/

# Check feed content
curl "https://example.com/feed.rss" | head -20

# Remove invalid feed from feeds.txt
```

#### "Timeout while fetching feed"

**Cause**: Network issues or slow feed server.

**Solution**:
```bash
# Test connectivity
ping example.com

# Increase timeout in ingest_rss.py
# or remove problematic feed
```

---

### Scoring Issues

#### "All scores are zero"

**Cause**: Weights config error or scoring not applied.

**Solution**:
```json
// config/rules-engine.json
{
  "weights": {
    "novelty": 0.3,
    "recency": 0.2,
    // Ensure all weights are positive numbers
  }
}
```

#### "No candidates meet threshold"

**Cause**: `min_final_score` set too high.

**Solution**:
```json
// config/rules-engine.json
{
  "hard_rules": {
    "min_final_score": 0.1  // Lower from 0.25
  }
}
```

---

### Enrichment Issues

#### "BLOCKED: INSUFFICIENT EVIDENCE"

**Cause**: Topic doesn't meet evidence thresholds.

**Solution**:
```json
// config/rules-engine.json
{
  "evidence_thresholds": {
    "min_sources": 2,              // Lower from 3
    "min_avg_credibility_score": 1.5, // Lower from 2.0
    "min_domain_diversity": 1      // Lower from 2
  }
}
```

#### "WEAK EVIDENCE on all topics"

**Cause**: Evidence fetching failing or low-quality sources.

**Solution**:
```bash
# Check enrichment_sources table
sqlite3 data/daily-blog.db "
SELECT topic_id, fetched_ok, credibility_guess
FROM enrichment_sources
LIMIT 20;
"

# Increase search terms or adjust queries
```

---

### Output Issues

#### "daily_board.md is empty"

**Cause**: Scoring stage failed or no candidates passed thresholds.

**Solution**:
```bash
# Check if candidate_scores has data
sqlite3 data/daily-blog.db "SELECT COUNT(*) FROM candidate_scores;"

# Check scoring stage status
sqlite3 data/daily-blog.db "SELECT * FROM run_metrics WHERE stage_name = 'score' ORDER BY started_at DESC LIMIT 1;"

# Lower thresholds in rules-engine.json
```

#### "top_outlines.md missing sections"

**Cause**: Editorial stage failed or no topics passed evidence checks.

**Solution**:
```bash
# Check editorial_candidates table
sqlite3 data/daily-blog.db "SELECT COUNT(*) FROM editorial_candidates;"

# Check for evidence_status filtering
sqlite3 data/daily-blog.db "SELECT evidence_status, COUNT(*) FROM editorial_candidates GROUP BY evidence_status;"

# Temporarily disable evidence blocking in rules-engine.json
```

---

## Performance Issues

### Pipeline is slow

**Symptoms**: Individual stages take > 5 minutes

**Diagnosis**:
```bash
# Check stage durations
sqlite3 data/daily-blog.db "
SELECT stage_name, AVG(duration_ms) as avg_ms
FROM run_metrics
GROUP BY stage_name
ORDER BY avg_ms DESC;
"
```

**Solutions**:

1. **Use local models** for high-volume stages:
   ```json
   {
     "extractor": {
       "primary": "ollama:qwen2.5:7b",  // Local
       "fallback": "codex-5.3"          // Cloud
     }
   }
   ```

2. **Reduce input size**:
   ```json
   {
     "hard_rules": {
       "max_candidates": 8  // Reduce from 12
     }
   }
   ```

3. **Use faster model** for experimentation

### Memory issues

**Symptoms**: Pipeline crashes with out-of-memory error

**Solutions**:

1. **Process in smaller batches**
2. **Use smaller models** (7B instead of 14B)
3. **Close database connections** when done

---

## Debugging Tips

### Enable Debug Logging

```bash
# Set environment variable
export LOG_LEVEL=DEBUG

# Or modify code
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Test Individual Stages

```bash
# Run stages separately to isolate issues
python3 ingest_rss.py
python3 score_rss.py
python3 extract_claims.py
# etc.
```

### Inspect Intermediate Outputs

```bash
# Check mentions after ingest
sqlite3 data/daily-blog.db "SELECT * FROM mentions LIMIT 5;"

# Check scores after scoring
sqlite3 data/daily-blog.db "SELECT * FROM candidate_scores ORDER BY final_score DESC LIMIT 5;"

# Check claims after extraction
sqlite3 data/daily-blog.db "SELECT * FROM claims LIMIT 5;"

# Check topics after lifting
sqlite3 data/daily-blog.db "SELECT * FROM topic_clusters LIMIT 5;"
```

### Use the Insights Dashboard

```bash
# Launch dashboard
python3 scripts/insights_viewer.py

# Open in browser
# http://127.0.0.1:8877/docs/viewer/dashboard.html
```

---

## Getting Help

### Collect Diagnostic Information

```bash
# System info
python3 --version
pip list | grep -E "feedparser|sqlite"

# Config validation
python3 -m json.tool config/rules-engine.json
python3 -m json.tool config/model-routing.json

# Recent errors
sqlite3 data/daily-blog.db "SELECT run_id, stage_name, error_message FROM run_metrics WHERE status = 'failed' ORDER BY started_at DESC LIMIT 5;"

# Model status
ollama list
which codex
which gemini
```

### Useful Commands

```bash
# Reset database (last resort)
rm data/daily-blog.db

# Clear specific stage data
sqlite3 data/daily-blog.db "DELETE FROM candidate_scores WHERE run_id = '20260101T120000Z';"

# Re-run specific stage
python3 score_rss.py

# Check logs
tail -f /var/log/syslog  # Or wherever logs are written
```

### When to Report Issues

Report a bug if:
- Error persists after checking all above solutions
- Error message is unclear/unhelpful
- Stage consistently fails with valid inputs
- Database corruption occurs

Include in bug report:
- Full error message
- Run metrics for failed stage
- Configuration files (redact sensitive data)
- Python version and OS
