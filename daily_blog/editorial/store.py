import sqlite3


def init_editorial_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS editorial_candidates (
            topic_id TEXT PRIMARY KEY,
            title_options_json TEXT NOT NULL,
            outline_markdown TEXT NOT NULL,
            narrative_draft_markdown TEXT NOT NULL DEFAULT '',
            talking_points_json TEXT NOT NULL,
            verification_checklist_json TEXT NOT NULL,
            angle TEXT NOT NULL,
            audience TEXT NOT NULL,
            model_route_used TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(editorial_candidates)").fetchall()
        if len(row) > 1
    }
    if "angle" not in columns:
        conn.execute("ALTER TABLE editorial_candidates ADD COLUMN angle TEXT NOT NULL DEFAULT ''")
    if "audience" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN audience TEXT NOT NULL DEFAULT ''"
        )
    if "narrative_draft_markdown" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN "
            "narrative_draft_markdown TEXT NOT NULL DEFAULT ''"
        )
    if "evidence_status" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN "
            "evidence_status TEXT NOT NULL DEFAULT 'WARN'"
        )
    if "evidence_reasons_json" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN "
            "evidence_reasons_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "evidence_ui_state" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN evidence_ui_state TEXT NOT NULL DEFAULT ''"
        )
    conn.commit()
