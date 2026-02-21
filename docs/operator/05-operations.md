# Operations

## Daily run

```bash
python3 run_pipeline.py
```

## Insights dashboard

Run the visualizer:

```bash
python3 scripts/insights_viewer.py
```

Open:

- `http://127.0.0.1:8877/docs/viewer/dashboard.html`

Use it to connect ranked candidates, topics, sources, and run health in one place.

## Cron schedule

Template is in `ops/cron/daily_pipeline.cron`.

Current schedule in that template:

- `0 8 * * *` local time

Install:

```bash
crontab ops/cron/daily_pipeline.cron
```

Verify:

```bash
crontab -l | grep daily-blog
```

## Logs and metrics

- file log: `data/pipeline.log`
- db metrics: `run_metrics` table in `data/daily-blog.db`

Useful checks:

```bash
sqlite3 data/daily-blog.db "SELECT run_id, stage_name, status, duration_ms, model_route_used, actual_model_used FROM run_metrics ORDER BY started_at DESC LIMIT 20;"
sqlite3 data/daily-blog.db "SELECT stage_name, COUNT(*) FROM run_metrics WHERE status='failed' GROUP BY stage_name;"
```

## Maintenance

Soak test:

```bash
python3 scripts/soak_test.py --mode simulate --days 7
```

Cleanup:

```bash
python3 scripts/cleanup_data.py --dry-run
python3 scripts/cleanup_data.py
```

## Troubleshooting quick map

- Pipeline exits early -> inspect `data/pipeline.log` and latest failed row in `run_metrics`
- Stage timeout -> increase timeout via `PIPELINE_STAGE_TIMEOUTS`
- Empty outputs -> confirm upstream tables have rows before downstream stage
- Repeated weak candidates -> tune `config/rules-engine.json`

For detailed operational procedures, use `ops/runbook.md`.
