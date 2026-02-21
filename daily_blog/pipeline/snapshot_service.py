import json
import os
import sqlite3
from typing import Any

from daily_blog.core.json_utils import canonical_json, snapshot_hash
from daily_blog.core.time_utils import now_iso


def _effective_env_config() -> dict[str, Any]:
    tracked_keys = [
        "PIPELINE_RETRIES",
        "PIPELINE_STAGE_TIMEOUT_SECONDS",
        "PIPELINE_STAGE_TIMEOUTS",
        "EXTRACT_MAX_MENTIONS",
        "ENRICH_FETCH_TIMEOUT_SECONDS",
        "ENRICH_FETCH_RETRIES",
        "ENRICH_DISCOVER_LIMIT",
        "ENRICH_MAX_KNOWN_CLAIM_URLS",
        "ENRICH_MAX_TOPICS",
        "ENRICH_SKIP_MODEL",
        "TOPIC_CURATOR_BATCH_SIZE",
        "FORCE_TOPIC_RECURATE",
        "EDITORIAL_STATIC_ONLY",
    ]
    return {key: os.getenv(key, "") for key in tracked_keys if key in os.environ}


def effective_config_snapshot(
    *,
    run_id: str,
    model_routing: dict[str, Any],
    rules_engine: dict[str, Any],
    prompts: dict[str, Any],
    stage_timeouts: dict[str, int],
    retries: int,
) -> dict[str, Any]:
    return {
        "schema_version": "prometheus-v2",
        "run_id": run_id,
        "pipeline": {
            "retries": retries,
            "stage_timeouts": stage_timeouts,
        },
        "rules_engine": rules_engine,
        "model_routing": model_routing,
        "prompts": prompts,
        "runtime": {
            "env": _effective_env_config(),
        },
    }


def _flatten_dict(value: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            out.update(_flatten_dict(child, child_prefix))
        return out
    if isinstance(value, list):
        for idx, child in enumerate(value):
            child_prefix = f"{prefix}[{idx}]"
            out.update(_flatten_dict(child, child_prefix))
        if not value:
            out[prefix] = []
        return out
    out[prefix] = value
    return out


def _compute_config_diff(current: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    current_flat = _flatten_dict(current)
    base_flat = _flatten_dict(base)
    keys = sorted(set(current_flat.keys()) | set(base_flat.keys()))
    added: dict[str, Any] = {}
    removed: dict[str, Any] = {}
    changed: dict[str, dict[str, Any]] = {}
    for key in keys:
        in_current = key in current_flat
        in_base = key in base_flat
        if in_current and not in_base:
            added[key] = current_flat[key]
            continue
        if in_base and not in_current:
            removed[key] = base_flat[key]
            continue
        if current_flat[key] != base_flat[key]:
            changed[key] = {"from": base_flat[key], "to": current_flat[key]}
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "changed_count": len(changed) + len(added) + len(removed),
    }


def _run_output_metrics(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    candidate_rows = conn.execute(
        "SELECT COUNT(*) AS n, AVG(final_score) AS avg_score "
        "FROM candidate_scores WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    counts = conn.execute(
        """
        SELECT
          SUM(CASE WHEN evidence_status = 'PASS' THEN 1 ELSE 0 END) AS pass_count,
          SUM(CASE WHEN evidence_status = 'WARN' THEN 1 ELSE 0 END) AS warn_count,
          SUM(CASE WHEN evidence_status = 'BLOCK' THEN 1 ELSE 0 END) AS block_count
        FROM editorial_candidates
        """
    ).fetchone()
    source_rows = conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN fetched_ok = 1 THEN 1 ELSE 0 END) AS fetched "
        "FROM enrichment_sources"
    ).fetchone()
    return {
        "candidate_count": int((candidate_rows[0] if candidate_rows else 0) or 0),
        "candidate_avg_score": round(float((candidate_rows[1] if candidate_rows else 0) or 0.0), 6),
        "evidence_pass_count": int((counts[0] if counts else 0) or 0),
        "evidence_warn_count": int((counts[1] if counts else 0) or 0),
        "evidence_block_count": int((counts[2] if counts else 0) or 0),
        "source_total": int((source_rows[0] if source_rows else 0) or 0),
        "source_fetched": int((source_rows[1] if source_rows else 0) or 0),
    }


def _compute_metrics_diff(current: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(set(current.keys()) | set(base.keys()))
    out: dict[str, Any] = {}
    for key in keys:
        cur = current.get(key)
        old = base.get(key)
        if cur == old:
            continue
        if isinstance(cur, (int, float)) and isinstance(old, (int, float)):
            out[key] = {"from": old, "to": cur, "delta": round(cur - old, 6)}
        else:
            out[key] = {"from": old, "to": cur}
    return out


def persist_run_snapshot(conn: sqlite3.Connection, run_id: str, snapshot: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO run_config_snapshots
        (run_id, snapshot_hash, snapshot_json, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (run_id, snapshot_hash(snapshot), canonical_json(snapshot), now_iso()),
    )
    conn.commit()


def persist_run_delta(
    conn: sqlite3.Connection, run_id: str, current_snapshot: dict[str, Any]
) -> None:
    base_row = conn.execute(
        """
        SELECT run_id, snapshot_json
        FROM run_config_snapshots
        WHERE run_id != ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    if not base_row:
        conn.execute(
            """
            INSERT OR REPLACE INTO run_deltas
            (run_id, base_run_id, config_diff_json, metrics_diff_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, "", canonical_json({}), canonical_json({}), now_iso()),
        )
        conn.commit()
        return

    base_run_id = str(base_row[0] or "")
    try:
        base_snapshot = json.loads(str(base_row[1] or "{}"))
    except json.JSONDecodeError:
        base_snapshot = {}

    config_diff = _compute_config_diff(current_snapshot, base_snapshot)
    current_metrics = _run_output_metrics(conn, run_id)
    base_metrics = _run_output_metrics(conn, base_run_id)
    metrics_diff = _compute_metrics_diff(current_metrics, base_metrics)

    conn.execute(
        """
        INSERT OR REPLACE INTO run_deltas
        (run_id, base_run_id, config_diff_json, metrics_diff_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            run_id,
            base_run_id,
            canonical_json(config_diff),
            canonical_json(metrics_diff),
            now_iso(),
        ),
    )
    conn.commit()
