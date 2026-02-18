#!/usr/bin/env python3
import json
import os
import re
import sqlite3
import subprocess
import time
import traceback
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_SQLITE_PATH = "./data/daily-blog.db"
DEFAULT_MODEL_ROUTING_PATH = Path(__file__).resolve().parent / "config" / "model-routing.json"
DEFAULT_RULES_ENGINE_PATH = Path(__file__).resolve().parent / "config" / "rules-engine.json"
DEFAULT_PROMPTS_PATH = Path(__file__).resolve().parent / "config" / "prompts.json"
DEFAULT_PIPELINE_TIMEOUTS_PATH = (
    Path(__file__).resolve().parent / "config" / "pipeline-timeouts.json"
)
DEFAULT_STAGE_TIMEOUT_SECONDS = 300


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_id_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def init_run_metrics(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run_metrics (
            run_id TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            row_count INTEGER NOT NULL,
            model_route_used TEXT NOT NULL,
            actual_model_used TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL,
            PRIMARY KEY (run_id, stage_name)
        )
        """
    )
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(run_metrics)").fetchall() if len(row) > 1
    }
    if "actual_model_used" not in columns:
        conn.execute(
            "ALTER TABLE run_metrics ADD COLUMN actual_model_used TEXT NOT NULL DEFAULT ''"
        )
    conn.commit()


def init_run_config_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run_config_snapshots (
            run_id TEXT PRIMARY KEY,
            snapshot_hash TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run_deltas (
            run_id TEXT PRIMARY KEY,
            base_run_id TEXT NOT NULL,
            config_diff_json TEXT NOT NULL,
            metrics_diff_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def insert_metric(
    conn: sqlite3.Connection,
    run_id: str,
    stage_name: str,
    status: str,
    started_at: str,
    finished_at: str,
    duration_ms: int,
    row_count: int,
    model_route_used: str,
    actual_model_used: str,
    error_message: str,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO run_metrics (
            run_id, stage_name, status, started_at, finished_at,
            duration_ms, row_count, model_route_used, actual_model_used, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            stage_name,
            status,
            started_at,
            finished_at,
            duration_ms,
            row_count,
            model_route_used,
            actual_model_used,
            error_message,
        ),
    )
    conn.commit()


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    return loaded


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _snapshot_hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()


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


def _effective_config_snapshot(
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
        "SELECT COUNT(*) AS n, AVG(final_score) AS avg_score FROM candidate_scores WHERE run_id = ?",
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
        "SELECT COUNT(*) AS total, SUM(CASE WHEN fetched_ok = 1 THEN 1 ELSE 0 END) AS fetched FROM enrichment_sources"
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


def _persist_run_snapshot(conn: sqlite3.Connection, run_id: str, snapshot: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO run_config_snapshots (run_id, snapshot_hash, snapshot_json, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (run_id, _snapshot_hash(snapshot), _canonical_json(snapshot), now_iso()),
    )
    conn.commit()


def _persist_run_delta(
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
            INSERT OR REPLACE INTO run_deltas (run_id, base_run_id, config_diff_json, metrics_diff_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, "", _canonical_json({}), _canonical_json({}), now_iso()),
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
        INSERT OR REPLACE INTO run_deltas (run_id, base_run_id, config_diff_json, metrics_diff_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            run_id,
            base_run_id,
            _canonical_json(config_diff),
            _canonical_json(metrics_diff),
            now_iso(),
        ),
    )
    conn.commit()


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


def _canonical_model_name(model_name: str) -> str:
    normalized = model_name.strip()
    if not normalized:
        return "unknown"
    if normalized.startswith("opencode:"):
        return f"opencode/{normalized.split(':', 1)[1]}"
    if normalized.startswith("openclaw:"):
        return f"openclaw/{normalized.split(':', 1)[1]}"
    if normalized.startswith("ollama:"):
        return f"ollama/{normalized.split(':', 1)[1]}"
    if ":" in normalized and "/" not in normalized:
        provider, model = normalized.split(":", 1)
        if provider and model:
            return f"{provider}/{model}"
    if normalized.startswith("openclaw/") or normalized.startswith("opencode/"):
        return normalized
    if "/" in normalized:
        return normalized
    return f"opencode/{normalized}"


def _extract_model_from_output(output: str, fallback_model: str) -> str:
    if not output:
        return fallback_model

    keyed = re.search(r'"model_used"\s*:\s*"([^"]+)"', output)
    if keyed:
        return _canonical_model_name(keyed.group(1))

    for pattern in (
        r"\b(?:opencode|openclaw|ollama)/[A-Za-z0-9_.:-]+\b",
        r"\b(?:opencode|openclaw|ollama):[A-Za-z0-9_.-]+\b",
        r"\bmodel\s*[=:]\s*([A-Za-z0-9_.:/-]+)",
    ):
        match = re.search(pattern, output, flags=re.IGNORECASE)
        if not match:
            continue
        token = match.group(1) if match.groups() else match.group(0)
        return _canonical_model_name(token)

    return fallback_model


def _coerce_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _load_stage_timeouts(stage_names: list[str]) -> dict[str, int]:
    default_timeout = _read_int_env("PIPELINE_STAGE_TIMEOUT_SECONDS", DEFAULT_STAGE_TIMEOUT_SECONDS)
    timeouts = {stage: default_timeout for stage in stage_names}

    path = Path(os.getenv("PIPELINE_TIMEOUTS_PATH", str(DEFAULT_PIPELINE_TIMEOUTS_PATH)))
    config_timeouts = _load_json_file(path)
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


def _build_error_context(
    *,
    stage_name: str,
    command: list[str],
    attempt: int,
    total_attempts: int,
    route_used: str,
    model_used: str,
    timeout_seconds: int,
    returncode: int | None,
    stdout: str,
    stderr: str,
    exception: Exception | None = None,
) -> str:
    details = [
        f"stage={stage_name}",
        f"attempt={attempt}/{total_attempts}",
        f"route={route_used}",
        f"model={model_used}",
        f"timeout_seconds={timeout_seconds}",
        f"command={' '.join(command)}",
    ]
    if returncode is not None:
        details.append(f"returncode={returncode}")
    if stdout.strip():
        details.append(f"stdout={stdout.strip()}")
    if stderr.strip():
        details.append(f"stderr={stderr.strip()}")
    if exception is not None:
        details.append("traceback=" + "".join(traceback.format_exception(exception)).strip())
    return " | ".join(details)


def _resolve_route_for_attempt(
    routing: dict[str, Any],
    stage_route_key: str,
    default_model: str,
    attempt: int,
) -> tuple[str, str]:
    stage_routes = routing.get(stage_route_key, {}) if isinstance(routing, dict) else {}
    primary = stage_routes.get("primary") if isinstance(stage_routes, dict) else None
    fallback = stage_routes.get("fallback") if isinstance(stage_routes, dict) else None

    primary_name = primary if isinstance(primary, str) and primary.strip() else default_model
    fallback_name = fallback if isinstance(fallback, str) and fallback.strip() else primary_name
    if attempt == 1:
        return "primary", _canonical_model_name(primary_name)
    return "fallback", _canonical_model_name(fallback_name)


def run_stage(
    stage_name: str,
    command: list[str],
    retries: int,
    timeout_seconds: int,
    routing: dict[str, Any],
    stage_route_key: str,
    default_model: str,
    run_id: str,
) -> tuple[bool, str, str, str, str]:
    last_error = ""
    last_output = ""
    last_route_used = "primary"
    last_model_used = _canonical_model_name(default_model)
    total_attempts = retries + 1

    for attempt in range(1, retries + 2):
        route_used, routed_model = _resolve_route_for_attempt(
            routing=routing,
            stage_route_key=stage_route_key,
            default_model=default_model,
            attempt=attempt,
        )
        last_route_used = route_used
        last_model_used = routed_model
        print(
            f"[{stage_name}] Attempt {attempt}/{total_attempts} "
            f"route={route_used} model={routed_model} timeout={timeout_seconds}s"
        )

        env = os.environ.copy()
        env["RUN_ID"] = run_id
        env["PIPELINE_RUN_ID"] = run_id
        env["MODEL_ROUTE"] = route_used
        env["MODEL_NAME"] = routed_model
        env["MODEL_ROUTING_STAGE"] = stage_route_key

        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            last_error = _build_error_context(
                stage_name=stage_name,
                command=command,
                attempt=attempt,
                total_attempts=total_attempts,
                route_used=route_used,
                model_used=routed_model,
                timeout_seconds=timeout_seconds,
                returncode=None,
                stdout=_coerce_text(exc.stdout),
                stderr=_coerce_text(exc.stderr),
                exception=exc,
            )
            if attempt <= retries:
                time.sleep(2**attempt)
            continue

        combined_output = "\n".join(
            part.strip() for part in (proc.stdout or "", proc.stderr or "") if part and part.strip()
        )
        last_output = combined_output
        if proc.returncode == 0:
            detected_model = _extract_model_from_output(combined_output, routed_model)
            return True, combined_output, "", route_used, detected_model
        last_error = _build_error_context(
            stage_name=stage_name,
            command=command,
            attempt=attempt,
            total_attempts=total_attempts,
            route_used=route_used,
            model_used=routed_model,
            timeout_seconds=timeout_seconds,
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )
        if attempt <= retries:
            time.sleep(2**attempt)
    if not last_error:
        last_error = "unknown error"
    if not last_output:
        last_output = last_error
    return False, last_output, last_error, last_route_used, last_model_used


def main() -> int:
    load_env_file(Path(".env"))
    sqlite_path = Path(os.getenv("SQLITE_PATH", DEFAULT_SQLITE_PATH))
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_path)
    init_run_metrics(conn)
    init_run_config_tables(conn)

    run_id = run_id_now()
    retries = int(os.getenv("PIPELINE_RETRIES", "2"))
    stages = [
        ("ingest", ["python3", "ingest_rss.py"], "ranker", "deterministic-code"),
        ("score", ["python3", "score_rss.py"], "ranker", "deterministic-code"),
        ("extract_claims", ["python3", "extract_claims.py"], "extractor", "gemini-3-pro"),
        ("lift_topics", ["python3", "lift_topics.py"], "topic_lifter", "gemini-3-pro"),
        ("normalize_topics", ["python3", "normalize_topics.py"], "topic_curator", "ollama:qwen2.5"),
        ("enrich_topics", ["python3", "enrich_topics.py"], "enrichment", "codex-5.3"),
        ("generate_editorial", ["python3", "generate_editorial.py"], "editorial", "codex-5.3"),
    ]
    skip_stages = _read_stage_skip_set()
    if skip_stages:
        stages = [stage for stage in stages if stage[0] not in skip_stages]

    stage_timeouts = _load_stage_timeouts([name for name, *_ in stages])
    model_routing = _load_json_file(DEFAULT_MODEL_ROUTING_PATH)
    rules_engine = _load_json_file(
        Path(os.getenv("RULES_ENGINE_CONFIG", str(DEFAULT_RULES_ENGINE_PATH)))
    )
    prompts = _load_json_file(Path(os.getenv("PROMPTS_CONFIG", str(DEFAULT_PROMPTS_PATH))))
    current_snapshot = _effective_config_snapshot(
        run_id=run_id,
        model_routing=model_routing,
        rules_engine=rules_engine,
        prompts=prompts,
        stage_timeouts=stage_timeouts,
        retries=retries,
    )
    _persist_run_snapshot(conn, run_id, current_snapshot)

    for stage_name, cmd, route_key, default_model in stages:
        started = now_iso()
        t0 = time.time()
        ok, out, error_message, route_used, model_used = run_stage(
            stage_name=stage_name,
            command=cmd,
            retries=retries,
            timeout_seconds=stage_timeouts.get(stage_name, DEFAULT_STAGE_TIMEOUT_SECONDS),
            routing=model_routing,
            stage_route_key=route_key,
            default_model=default_model,
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
            _persist_run_delta(conn, run_id, current_snapshot)
            conn.close()
            return 1

    _persist_run_delta(conn, run_id, current_snapshot)
    conn.close()
    print(f"Pipeline run complete: {run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
