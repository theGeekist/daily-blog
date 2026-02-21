#!/usr/bin/env python3
import json
import os
import sqlite3
import time
from pathlib import Path

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

DEFAULT_SQLITE_PATH = "./data/daily-blog.db"
DEFAULT_MODEL_ROUTING_PATH = Path(__file__).resolve().parent / "config" / "model-routing.json"
DEFAULT_RULES_ENGINE_PATH = Path(__file__).resolve().parent / "config" / "rules-engine.json"
DEFAULT_PROMPTS_PATH = Path(__file__).resolve().parent / "config" / "prompts.json"
DEFAULT_PIPELINE_TIMEOUTS_PATH = (
    Path(__file__).resolve().parent / "config" / "pipeline-timeouts.json"
)
DEFAULT_STAGE_TIMEOUT_SECONDS = 300


def _read_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _read_stage_skip_set() -> set[str]:
    raw = os.getenv("PIPELINE_SKIP_STAGES", "").strip()
    if not raw:
        return set()
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        loaded = None
    if isinstance(loaded, list):
        return {str(v).strip() for v in loaded if str(v).strip()}
    return {part.strip() for part in raw.split(",") if part.strip()}


def _load_stage_timeouts(stage_names: list[str]) -> dict[str, int]:
    default_timeout = _read_int_env("PIPELINE_STAGE_TIMEOUT_SECONDS", DEFAULT_STAGE_TIMEOUT_SECONDS)
    timeouts = {stage: default_timeout for stage in stage_names}

    path = Path(os.getenv("PIPELINE_TIMEOUTS_PATH", str(DEFAULT_PIPELINE_TIMEOUTS_PATH)))
    config_timeouts = load_json_file(path)
    for key, value in config_timeouts.items():
        if key in timeouts and isinstance(value, int) and value > 0:
            timeouts[key] = value

    env_overrides = os.getenv("PIPELINE_STAGE_TIMEOUTS")
    if env_overrides:
        try:
            loaded = json.loads(env_overrides)
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            for key, value in loaded.items():
                if key in timeouts and isinstance(value, int) and value > 0:
                    timeouts[key] = value

    return timeouts


def main() -> int:
    load_env_file(Path(".env"))
    sqlite_path = Path(os.getenv("SQLITE_PATH", DEFAULT_SQLITE_PATH))
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_path)
    init_run_metrics(conn)
    init_run_config_tables(conn)

    run_id = run_id_now()
    retries = int(os.getenv("PIPELINE_RETRIES", "2"))
    skip_stages = _read_stage_skip_set()
    stages = configured_stages(skip_stages)

    stage_timeouts = _load_stage_timeouts([stage.name for stage in stages])
    model_routing = load_json_file(DEFAULT_MODEL_ROUTING_PATH)
    rules_engine = load_json_file(
        Path(os.getenv("RULES_ENGINE_CONFIG", str(DEFAULT_RULES_ENGINE_PATH)))
    )
    prompts = load_json_file(Path(os.getenv("PROMPTS_CONFIG", str(DEFAULT_PROMPTS_PATH))))
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
