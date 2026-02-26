#!/usr/bin/env python3
import os
import sqlite3
import time
from pathlib import Path

from daily_blog.config import load_app_config, resolve_stage_timeouts
from daily_blog.core.env import load_env_file
from daily_blog.core.json_utils import load_json_file
from daily_blog.core.time_utils import now_iso, run_id_now
from daily_blog.pipeline.definitions import configured_stages
from daily_blog.pipeline.metrics_store import (
    init_run_config_tables,
    init_run_metrics,
    insert_metric,
)
from daily_blog.pipeline.snapshot_service import (
    effective_config_snapshot,
    persist_run_delta,
    persist_run_snapshot,
)
from daily_blog.pipeline.stage_runner import run_stage

DEFAULT_STAGE_TIMEOUT_SECONDS = 300


def main() -> int:
    load_env_file(Path(".env"))
    project_root = Path(__file__).resolve().parent
    app_cfg = load_app_config(project_root=project_root, environ=os.environ)
    sqlite_path = app_cfg.paths.sqlite_path
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_path)
    init_run_metrics(conn)
    init_run_config_tables(conn)

    run_id = run_id_now()
    retries = app_cfg.pipeline.retries
    skip_stages = app_cfg.pipeline.skip_stages
    stages = configured_stages(skip_stages)

    stage_timeouts = resolve_stage_timeouts([stage.name for stage in stages], app_cfg)
    model_routing = load_json_file(app_cfg.paths.model_routing_config)
    rules_engine = load_json_file(app_cfg.paths.rules_engine_config)
    prompts = load_json_file(app_cfg.paths.prompts_config)
    current_snapshot = effective_config_snapshot(
        run_id=run_id,
        model_routing=model_routing,
        rules_engine=rules_engine,
        prompts=prompts,
        stage_timeouts=stage_timeouts,
        retries=retries,
    )
    persist_run_snapshot(conn, run_id, current_snapshot)

    for stage in stages:
        stage_name = stage.name
        started = now_iso()
        t0 = time.time()
        ok, out, error_message, route_used, model_used = run_stage(
            stage_name=stage_name,
            command=stage.command,
            retries=retries,
            timeout_seconds=stage_timeouts.get(stage_name, DEFAULT_STAGE_TIMEOUT_SECONDS),
            routing=model_routing,
            stage_route_key=stage.route_key,
            default_model=stage.default_model,
            run_id=run_id,
        )
        finished = now_iso()
        duration_ms = int((time.time() - t0) * 1000)

        insert_metric(
            conn,
            run_id,
            stage_name,
            "ok" if ok else "failed",
            started,
            finished,
            duration_ms,
            0,
            route_used,
            model_used,
            "" if ok else error_message,
        )

        print(f"[{stage_name}] {'OK' if ok else 'FAIL'}")
        if out:
            print(out)
        if not ok:
            persist_run_delta(conn, run_id, current_snapshot)
            conn.close()
            return 1

    persist_run_delta(conn, run_id, current_snapshot)
    conn.close()
    print(f"Pipeline run complete: {run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
