#!/usr/bin/env python3
import json
import os
import sqlite3
import time
from pathlib import Path

from daily_blog.core.env import load_env_file
from daily_blog.core.env_parsing import env_bool, env_int
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


def _format_seconds(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    rem = seconds - (minutes * 60)
    return f"{minutes}m {rem:.1f}s"


def _print_pipeline_header(
    *,
    run_id: str,
    sqlite_path: Path,
    retries: int,
    stages: list[str],
    stage_timeouts: dict[str, int],
) -> None:
    print("=" * 78)
    print(f"Daily Blog Pipeline | run_id={run_id}")
    print(f"DB: {sqlite_path}")
    print(f"Stages: {len(stages)} | Retries per stage: {retries}")
    print("Stage plan:")
    for index, stage in enumerate(stages, start=1):
        timeout = stage_timeouts.get(stage, DEFAULT_STAGE_TIMEOUT_SECONDS)
        print(f"  {index:>2}. {stage:<18} timeout={timeout}s")
    print("=" * 78)


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
    default_timeout = env_int(
        "PIPELINE_STAGE_TIMEOUT_SECONDS",
        DEFAULT_STAGE_TIMEOUT_SECONDS,
        minimum=1,
    )
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


def _pending_extract_mentions(conn: sqlite3.Connection) -> int:
    max_mentions = env_int("EXTRACT_MAX_MENTIONS", 300, minimum=1)
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT m.entry_id
            FROM mentions m
            LEFT JOIN claims c ON c.entry_id = m.entry_id
            WHERE c.entry_id IS NULL
            ORDER BY m.fetched_at DESC
            LIMIT ?
        ) q
        """,
        (max_mentions,),
    ).fetchone()
    return int((row[0] if row else 0) or 0)


def _pending_lift_claims(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM claims").fetchone()
    return int((row[0] if row else 0) or 0)


def _dynamic_stage_timeout_seconds(
    *,
    conn: sqlite3.Connection,
    stage_name: str,
    configured_timeout: int,
) -> tuple[int, str]:
    if not env_bool("PIPELINE_DYNAMIC_TIMEOUTS", default=True):
        return configured_timeout, "static"

    max_timeout = env_int("PIPELINE_TIMEOUT_MAX_SECONDS", 7200, minimum=60)
    buffer_seconds = env_int("PIPELINE_DYNAMIC_TIMEOUT_BUFFER_SECONDS", 90, minimum=0)
    timeout = configured_timeout
    detail = "configured"

    try:
        if stage_name == "extract_claims":
            pending = _pending_extract_mentions(conn)
            per_unit = env_int("EXTRACT_TIMEOUT_PER_MENTION_SECONDS", 8, minimum=1)
            estimated = (pending * per_unit) + buffer_seconds
            timeout = max(configured_timeout, estimated)
            detail = f"pending_mentions={pending} per={per_unit}s buffer={buffer_seconds}s"
        elif stage_name == "lift_topics":
            pending = _pending_lift_claims(conn)
            per_unit = env_int("LIFT_TIMEOUT_PER_CLAIM_SECONDS", 9, minimum=1)
            estimated = (pending * per_unit) + buffer_seconds
            timeout = max(configured_timeout, estimated)
            detail = f"pending_claims={pending} per={per_unit}s buffer={buffer_seconds}s"
    except sqlite3.OperationalError:
        timeout = configured_timeout
        detail = "configured (introspection unavailable)"

    timeout = min(timeout, max_timeout)
    return max(1, timeout), detail


def main() -> int:
    load_env_file(Path(".env"))
    sqlite_path = Path(os.getenv("SQLITE_PATH", DEFAULT_SQLITE_PATH))
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_path)
    init_run_metrics(conn)
    init_run_config_tables(conn)

    run_id = run_id_now()
    retries = env_int("PIPELINE_RETRIES", 2, minimum=1)
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
    _print_pipeline_header(
        run_id=run_id,
        sqlite_path=sqlite_path,
        retries=retries,
        stages=[stage.name for stage in stages],
        stage_timeouts=stage_timeouts,
    )

    summary_rows: list[tuple[str, bool, int, str, str]] = []
    pipeline_started = time.time()

    for index, stage in enumerate(stages, start=1):
        stage_name = stage.name
        configured_timeout = stage_timeouts.get(stage_name, DEFAULT_STAGE_TIMEOUT_SECONDS)
        effective_timeout, timeout_detail = _dynamic_stage_timeout_seconds(
            conn=conn,
            stage_name=stage_name,
            configured_timeout=configured_timeout,
        )
        started = now_iso()
        t0 = time.time()
        print(
            f"\n[{index}/{len(stages)}] START {stage_name} | "
            f"timeout={effective_timeout}s "
            f"| retries={retries}"
        )
        if effective_timeout != configured_timeout:
            print(
                f"[{stage_name}] timeout adjusted from {configured_timeout}s "
                f"to {effective_timeout}s ({timeout_detail})"
            )
        ok, out, error_message, route_used, model_used = run_stage(
            stage_name=stage_name,
            command=stage.command,
            retries=retries,
            timeout_seconds=effective_timeout,
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

        status_label = "OK" if ok else "FAIL"
        print(
            f"[{index}/{len(stages)}] {status_label} {stage_name} | "
            f"elapsed={_format_seconds(duration_ms / 1000)} | "
            f"route={route_used} | model={model_used}"
        )
        if out:
            print(out)
        summary_rows.append((stage_name, ok, duration_ms, route_used, model_used))
        if not ok:
            persist_run_delta(conn, run_id, current_snapshot)
            conn.close()
            print("\nPipeline aborted due to stage failure.\n")
            print("Summary:")
            for name, stage_ok, stage_duration_ms, route, model in summary_rows:
                marker = "OK  " if stage_ok else "FAIL"
                print(
                    f"  {marker} {name:<18} "
                    f"{_format_seconds(stage_duration_ms / 1000):>8}  "
                    f"route={route:<8} model={model}"
                )
            return 1

    persist_run_delta(conn, run_id, current_snapshot)
    conn.close()
    pipeline_elapsed = _format_seconds(time.time() - pipeline_started)
    print("\nPipeline complete.\n")
    print("Summary:")
    for name, stage_ok, stage_duration_ms, route, model in summary_rows:
        marker = "OK  " if stage_ok else "FAIL"
        print(
            f"  {marker} {name:<18} "
            f"{_format_seconds(stage_duration_ms / 1000):>8}  route={route:<8} model={model}"
        )
    print(f"\nRun complete: {run_id} | total_elapsed={pipeline_elapsed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
