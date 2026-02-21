#!/usr/bin/env python3
"""
Data Cleanup Utility

Archives old data artifacts and cleans old run_metrics rows.

This script follows a safety-first approach:
1. Archives data before deletion
2. Dry-run mode to preview changes
3. Configurable retention policies
4. Comprehensive logging of all actions

Usage:
    python3 scripts/cleanup_data.py [--dry-run] [--retention-days 30]
"""

import argparse
import json
import os
import sqlite3
import sys
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from daily_blog.core.env import load_env_file

DEFAULT_SQLITE_PATH = "./data/daily-blog.db"
DEFAULT_DATA_DIR = "./data"
DEFAULT_ARCHIVE_DIR = "./data/archive"
DEFAULT_RETENTION_DAYS = 30
DEFAULT_METRICS_RETENTION_DAYS = 90

ARCHIVEABLE_PATTERNS = [
    "*.jsonl",
    "*.json",
    "*.md",
    "*.txt",
    "*.log",
    "*.log.*",
]

ARCHIVE_EXCLUDE_PATTERNS = [
    "daily-blog.db",
    "archive",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def should_archive_file(file_path: Path) -> bool:
    """Check if a file should be archived based on patterns."""
    if not file_path.is_file():
        return False

    file_name = file_path.name

    for exclude in ARCHIVE_EXCLUDE_PATTERNS:
        if file_name == exclude or file_name.startswith(exclude):
            return False

    for pattern in ARCHIVEABLE_PATTERNS:
        if file_path.match(pattern):
            return True

    return False


def is_older_than(file_path: Path, days: int) -> bool:
    """Check if a file is older than specified days."""
    if not file_path.exists():
        return False

    file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
    cutoff_time = utc_now() - timedelta(days=days)

    return file_mtime < cutoff_time


def create_archive(
    files_to_archive: list[Path],
    archive_dir: Path,
    dry_run: bool = False,
) -> tuple[str, int]:
    """Create a tar.gz archive of specified files."""
    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    archive_name = f"cleanup_archive_{timestamp}.tar.gz"
    archive_path = archive_dir / archive_name

    if dry_run:
        return str(archive_path), len(files_to_archive)

    archive_dir.mkdir(parents=True, exist_ok=True)

    archived_count = 0
    with tarfile.open(archive_path, "w:gz") as tar:
        for file_path in files_to_archive:
            try:
                tar.add(file_path, arcname=file_path.name)
                archived_count += 1
            except Exception as e:
                print(f"Warning: Failed to archive {file_path}: {e}", file=sys.stderr)

    return str(archive_path), archived_count


def get_metrics_to_clean(conn: sqlite3.Connection, retention_days: int) -> list[tuple[str, str]]:
    """Get run_metrics rows older than retention period."""
    cutoff_date = (utc_now() - timedelta(days=retention_days)).strftime("%Y-%m-%d")

    rows = conn.execute(
        """
        SELECT run_id, started_at
        FROM run_metrics
        WHERE date(started_at) < ?
        ORDER BY started_at ASC
        """,
        (cutoff_date,),
    ).fetchall()

    return rows


def archive_old_metrics(
    conn: sqlite3.Connection, archive_dir: Path, dry_run: bool = False
) -> tuple[int, str | None]:
    """Archive old run_metrics to JSON before deletion."""
    rows = get_metrics_to_clean(conn, DEFAULT_METRICS_RETENTION_DAYS)

    if not rows:
        return 0, None

    if dry_run:
        return len(rows), None

    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    metrics_archive_name = f"run_metrics_archive_{timestamp}.json"
    metrics_archive_path = archive_dir / metrics_archive_name

    archive_data: list[dict[str, Any]] = []
    for run_id, _ in rows:
        stage_rows = conn.execute(
            """
            SELECT run_id, stage_name, status, started_at, finished_at,
                   duration_ms, row_count, model_route_used, actual_model_used, error_message
            FROM run_metrics WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()

        for row in stage_rows:
            archive_data.append(
                {
                    "run_id": row[0],
                    "stage_name": row[1],
                    "status": row[2],
                    "started_at": row[3],
                    "finished_at": row[4],
                    "duration_ms": row[5],
                    "row_count": row[6],
                    "model_route_used": row[7],
                    "actual_model_used": row[8],
                    "error_message": row[9],
                    "archived_at": utc_now().isoformat(),
                }
            )

    archive_dir.mkdir(parents=True, exist_ok=True)
    metrics_archive_path.write_text(json.dumps(archive_data, indent=2))

    return len(rows), str(metrics_archive_path)


def delete_old_metrics(conn: sqlite3.Connection, retention_days: int, dry_run: bool = False) -> int:
    """Delete old run_metrics rows."""
    cutoff_date = (utc_now() - timedelta(days=retention_days)).strftime("%Y-%m-%d")

    if dry_run:
        rows = conn.execute(
            """
            SELECT COUNT(*) FROM run_metrics WHERE date(started_at) < ?
            """,
            (cutoff_date,),
        ).fetchone()
        return rows[0] if rows else 0

    cursor = conn.execute(
        """
        DELETE FROM run_metrics WHERE date(started_at) < ?
        """,
        (cutoff_date,),
    )
    conn.commit()

    return cursor.rowcount


def vacuum_database(conn: sqlite3.Connection) -> None:
    """Run VACUUM to reclaim space after deletions."""
    conn.execute("VACUUM")
    conn.commit()


def scan_old_files(data_dir: Path, retention_days: int) -> list[Path]:
    """Scan for files older than retention period that can be archived."""
    old_files: list[Path] = []

    for item in data_dir.iterdir():
        if should_archive_file(item) and is_older_than(item, retention_days):
            old_files.append(item)

    return old_files


def main() -> int:
    parser = argparse.ArgumentParser(description="Data Cleanup Utility")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without executing",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help=f"Retention period for data files (default: {DEFAULT_RETENTION_DAYS})",
    )
    parser.add_argument(
        "--metrics-retention-days",
        type=int,
        default=DEFAULT_METRICS_RETENTION_DAYS,
        help=f"Retention period for run_metrics (default: {DEFAULT_METRICS_RETENTION_DAYS})",
    )
    parser.add_argument(
        "--data-dir",
        default=DEFAULT_DATA_DIR,
        help=f"Data directory (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--archive-dir",
        default=DEFAULT_ARCHIVE_DIR,
        help=f"Archive directory (default: {DEFAULT_ARCHIVE_DIR})",
    )

    args = parser.parse_args()

    load_env_file(Path(".env"))

    data_dir = Path(args.data_dir)
    archive_dir = Path(args.archive_dir)
    sqlite_path = Path(os.getenv("SQLITE_PATH", DEFAULT_SQLITE_PATH))

    print("=== Data Cleanup Utility ===")
    if args.dry_run:
        print("DRY RUN MODE - No changes will be made")
    print(f"Data directory: {data_dir}")
    print(f"Archive directory: {archive_dir}")
    print(f"File retention: {args.retention_days} days")
    print(f"Metrics retention: {args.metrics_retention_days} days")
    print()

    actions: list[str] = []

    if not data_dir.exists():
        print(f"Error: Data directory not found: {data_dir}")
        return 1

    old_files = scan_old_files(data_dir, args.retention_days)

    if old_files:
        print(f"=== Old Files to Archive ({len(old_files)}) ===")
        for f in sorted(old_files):
            size_mb = f.stat().st_size / (1024 * 1024)
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            print(f"  {f.name} ({size_mb:.2f} MB, modified: {mtime})")

        if not args.dry_run:
            archive_path, archived_count = create_archive(old_files, archive_dir)
            print(f"\nCreated archive: {archive_path}")
            print(f"Archived files: {archived_count}/{len(old_files)}")
            actions.append(f"Archived {archived_count} files to {archive_path}")

            for f in old_files:
                try:
                    f.unlink()
                    actions.append(f"Deleted {f}")
                except Exception as e:
                    print(f"Warning: Failed to delete {f}: {e}", file=sys.stderr)
        else:
            print(f"\nWould archive {len(old_files)} files")
    else:
        print("=== Old Files ===")
        print("No files to archive")

    print()

    if sqlite_path.exists():
        print("=== Database Metrics Cleanup ===")
        conn = sqlite3.connect(sqlite_path)

        try:
            metrics_to_archive_count, metrics_archive_path = archive_old_metrics(
                conn, archive_dir, args.dry_run
            )

            if metrics_to_archive_count > 0:
                print(f"Metrics to archive: {metrics_to_archive_count}")
                if not args.dry_run and metrics_archive_path:
                    actions.append(
                        f"Archived {metrics_to_archive_count} metrics to {metrics_archive_path}"
                    )

            deleted_count = delete_old_metrics(conn, args.metrics_retention_days, args.dry_run)

            if deleted_count > 0:
                print(f"Metrics to delete: {deleted_count}")
                if not args.dry_run:
                    actions.append(f"Deleted {deleted_count} old metrics rows")
                    vacuum_database(conn)
                    print("Database vacuumed")
            else:
                print("No old metrics to delete")

        finally:
            conn.close()
    else:
        print("=== Database Metrics ===")
        print(f"Database not found: {sqlite_path}")

    print()

    if args.dry_run:
        print("=== Summary ===")
        print("No changes made (dry run mode)")
    else:
        print("=== Actions Taken ===")
        if actions:
            for action in actions:
                print(f"  - {action}")
        else:
            print("  No actions performed")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
