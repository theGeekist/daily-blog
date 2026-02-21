import sqlite3


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
