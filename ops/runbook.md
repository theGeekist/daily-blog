## Pipeline Runbook

### Daily operation
- Schedule: `0 8 * * *` local time
- Command: `python3 run_pipeline.py`
- Log file: `data/pipeline.log`

### Stage order
1. `ingest_rss.py`
2. `score_rss.py`
3. `extract_claims.py`
4. `lift_topics.py`
5. `enrich_topics.py`
6. `generate_editorial.py`

### Failure handling
- Retries: 2 retries with exponential backoff (configured in `run_pipeline.py` via `PIPELINE_RETRIES`).
- If a stage fails:
  - check `run_metrics` table for `error_message`
  - inspect `data/pipeline.log`
  - rerun failed stage manually

### Manual commands
- `python3 ingest_rss.py`
- `python3 score_rss.py`
- `python3 extract_claims.py`
- `python3 lift_topics.py`
- `python3 enrich_topics.py`
- `python3 generate_editorial.py`

### Health checks
- `candidate_scores` has rows for latest run
- `claims` has rows and non-empty `headline`, `who_cares`
- `topic_clusters` exists and `misc` ratio is acceptable
- `enrichment_sources` has `fetched_ok=1` rows
- `editorial_candidates` exists with checklist fields
- `data/daily_board.md`, `data/top_outlines.md`, and `data/research_pack.json` are updated

---

## Cron Installation

### Installing the daily pipeline cron job

The cron entry is provided in `ops/cron/daily_pipeline.cron`.

**To install:**

1. Review the cron file first:
   ```bash
   cat ops/cron/daily_pipeline.cron
   ```

2. Add to crontab (this will open your crontab in the default editor):
   ```bash
   crontab -e
   ```

3. Copy the contents of `ops/cron/daily_pipeline.cron` into your crontab.

**Alternative installation (single command):**

```bash
crontab ops/cron/daily_pipeline.cron
```

**To verify installation:**

```bash
crontab -l | grep daily-blog
```

**To remove the cron job:**

1. Edit crontab: `crontab -e`
2. Remove the daily-blog entry
3. Save and exit

---

## Log Rotation

### Using logrotate (recommended for production)

**Installation:**

```bash
# Copy the logrotate configuration
sudo cp ops/logrotate.conf /etc/logrotate.d/daily-blog

# Test immediately (dry-run to verify)
sudo logrotate -d /etc/logrotate.d/daily-blog

# Force rotation now to test
sudo logrotate -f /etc/logrotate.d/daily-blog
```

**Configuration details:**
- Rotates logs daily
- Keeps last 14 days of logs
- Compresses rotated logs (except most recent)
- Uses `copytruncate` to safely handle running processes
- Date-format filenames: `pipeline.log-20250218`, `pipeline.log-20250217.gz`, etc.

**Manual log rotation:**

```bash
sudo logrotate /etc/logrotate.d/daily-blog
```

---

## Failure Notifications

### Setting up email alerts

**Option 1: Configure mail system (postfix/sendmail)**

If your system has a mail agent configured, uncomment the `mail` directives in `ops/logrotate.conf`:

```
mail your-email@example.com
mailfirst
```

**Option 2: Custom notification script**

Create a wrapper script that checks pipeline exit status:

1. Create `scripts/run_with_notification.sh`:

```bash
#!/bin/bash
cd /Users/jasonnathan/Repos/daily-blog
python3 run_pipeline.py
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "Pipeline failed with exit code $EXIT_CODE at $(date)" | mail -s "Daily Blog Pipeline FAILED" your-email@example.com
fi

exit $EXIT_CODE
```

2. Update cron to use the wrapper:
```
0 8 * * * cd /Users/jasonnathan/Repos/daily-blog && ./scripts/run_with_notification.sh >> /Users/jasonnathan/Repos/daily-blog/data/pipeline.log 2>&1
```

**Option 3: Monitoring service integration**

For production use, consider integrating with monitoring services:
- Prometheus/Grafana with alerting
- PagerDuty
- Slack webhooks (via custom script)

---

## Maintenance Tools

### Soak Testing

Run a 7-day soak test to validate pipeline stability:

```bash
# Simulate mode (run all 7 days consecutively)
python3 scripts/soak_test.py --mode simulate --days 7

# Schedule mode (create cron entries)
python3 scripts/soak_test.py --mode schedule --days 7

# View report
cat data/soak_test_report.json
```

The soak test:
- Runs the full pipeline for N consecutive executions
- Compares metrics against historical baseline
- Detects performance anomalies (>2x or <0.5x baseline duration)
- Generates a comprehensive report with stage statistics

### Data Cleanup

Clean up old data artifacts and metrics:

```bash
# Preview changes (dry-run)
python3 scripts/cleanup_data.py --dry-run

# Clean data older than 30 days, metrics older than 90 days (default)
python3 scripts/cleanup_data.py

# Custom retention
python3 scripts/cleanup_data.py --retention-days 60 --metrics-retention-days 120
```

**Safety features:**
- Archives data to `data/archive/` before deletion
- Archives old `run_metrics` rows to JSON before database deletion
- Uses `VACUUM` to reclaim database space
- Dry-run mode to preview changes

**Cleanup behavior:**
- Archives `*.jsonl`, `*.json`, `*.md`, `*.txt`, `*.log` files
- Excludes `daily-blog.db` and `archive/` directory
- Deletes archived metrics rows older than retention period
- Creates timestamped tar.gz archives

---

## Troubleshooting

### Cron job not running

```bash
# Check cron daemon is running
sudo launchctl list | grep cron

# Check cron logs (macOS)
log show --predicate 'process == "cron"' --last 1h

# Verify crontab contents
crontab -l
```

### Log rotation not working

```bash
# Test logrotate configuration
sudo logrotate -d /etc/logrotate.d/daily-blog

# Check file permissions
ls -la /Users/jasonnathan/Repos/daily-blog/data/pipeline.log

# Verify logrotate config syntax
sudo logrotate -v /etc/logrotate.d/daily-blog
```

### Database locked or corrupted

```bash
# Check database integrity
sqlite3 data/daily-blog.db "PRAGMA integrity_check;"

# Recover from backup if needed
cp data/daily-blog.db data/daily-blog.db.backup.$(date +%Y%m%d)

# Use scripts/cleanup_data.py to clean old metrics
python3 scripts/cleanup_data.py --dry-run
```
