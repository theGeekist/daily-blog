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
            evidence_brief_json TEXT NOT NULL DEFAULT '{}',
            angle TEXT NOT NULL,
            audience TEXT NOT NULL,
            evidence_status TEXT NOT NULL DEFAULT 'WARN',
            evidence_reasons_json TEXT NOT NULL DEFAULT '[]',
            evidence_ui_state TEXT NOT NULL DEFAULT '',
            candidate_type TEXT NOT NULL DEFAULT '',
            post_intent TEXT NOT NULL DEFAULT '',
            artifact_types_present TEXT NOT NULL DEFAULT '[]',
            screenshot_required INTEGER NOT NULL DEFAULT 0,
            code_required INTEGER NOT NULL DEFAULT 0,
            transformability_score REAL NOT NULL DEFAULT 0.0,
            framework_agnostic_potential INTEGER NOT NULL DEFAULT 0,
            reader_pain_signal TEXT NOT NULL DEFAULT '',
            angle_fit_scores TEXT NOT NULL DEFAULT '[]',
            verification_cost TEXT NOT NULL DEFAULT 'unknown',
            draftability_now TEXT NOT NULL DEFAULT 'needs-evidence',
            reason_codes TEXT NOT NULL DEFAULT '[]',
            topic_confidence REAL NOT NULL DEFAULT 0.0,
            classifier_trace TEXT NOT NULL DEFAULT '{}',
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
    if "evidence_brief_json" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN "
            "evidence_brief_json TEXT NOT NULL DEFAULT '{}'"
        )
    if "candidate_type" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN candidate_type TEXT NOT NULL DEFAULT ''"
        )
    if "post_intent" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN post_intent TEXT NOT NULL DEFAULT ''"
        )
    if "artifact_types_present" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN "
            "artifact_types_present TEXT NOT NULL DEFAULT '[]'"
        )
    if "screenshot_required" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN "
            "screenshot_required INTEGER NOT NULL DEFAULT 0"
        )
    if "code_required" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN code_required INTEGER NOT NULL DEFAULT 0"
        )
    if "transformability_score" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN "
            "transformability_score REAL NOT NULL DEFAULT 0.0"
        )
    if "framework_agnostic_potential" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN "
            "framework_agnostic_potential INTEGER NOT NULL DEFAULT 0"
        )
    if "reader_pain_signal" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN "
            "reader_pain_signal TEXT NOT NULL DEFAULT ''"
        )
    if "angle_fit_scores" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN "
            "angle_fit_scores TEXT NOT NULL DEFAULT '[]'"
        )
    if "verification_cost" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN "
            "verification_cost TEXT NOT NULL DEFAULT 'unknown'"
        )
    if "draftability_now" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN "
            "draftability_now TEXT NOT NULL DEFAULT 'needs-evidence'"
        )
    if "reason_codes" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN reason_codes TEXT NOT NULL DEFAULT '[]'"
        )
    if "topic_confidence" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN topic_confidence REAL NOT NULL DEFAULT 0.0"
        )
    if "classifier_trace" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN "
            "classifier_trace TEXT NOT NULL DEFAULT '{}'"
        )
    conn.commit()


def init_candidate_dossiers_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_dossiers (
            run_id TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            schema_version TEXT NOT NULL DEFAULT '2.0.0',
            raw_capture_json TEXT NOT NULL DEFAULT '{}',
            normalized_candidate_json TEXT NOT NULL DEFAULT '{}',
            editorial_decision_json TEXT NOT NULL DEFAULT '{}',
            discovery_score_json TEXT NOT NULL DEFAULT '{}',
            publishability_score_json TEXT NOT NULL DEFAULT '{}',
            recommendation TEXT NOT NULL DEFAULT 'investigate',
            reason_codes_json TEXT NOT NULL DEFAULT '[]',
            topic_confidence REAL NOT NULL DEFAULT 0.0,
            classifier_trace_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            PRIMARY KEY (run_id, entry_id)
        )
        """
    )
    conn.commit()
