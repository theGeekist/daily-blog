CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    entry_id TEXT NOT NULL,
    headline TEXT NOT NULL,
    who_cares TEXT NOT NULL,
    problem_pressure TEXT NOT NULL,
    proposed_solution TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    model_route_used TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_clusters (
    topic_id TEXT PRIMARY KEY,
    parent_topic_slug TEXT NOT NULL,
    parent_topic_label TEXT NOT NULL,
    why_it_matters TEXT NOT NULL,
    time_horizon TEXT NOT NULL,
    claim_count INTEGER NOT NULL,
    keywords_json TEXT NOT NULL,
    model_route_used TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claim_topic_map (
    claim_id TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    model_route_used TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (claim_id, topic_id)
);

CREATE TABLE IF NOT EXISTS enrichment_sources (
    topic_id TEXT NOT NULL,
    query_terms_json TEXT NOT NULL,
    domain TEXT NOT NULL,
    url TEXT NOT NULL,
    stance TEXT NOT NULL,
    credibility_guess TEXT NOT NULL,
    fetched_ok INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (topic_id, url)
);

CREATE TABLE IF NOT EXISTS editorial_candidates (
    topic_id TEXT PRIMARY KEY,
    title_options_json TEXT NOT NULL,
    outline_markdown TEXT NOT NULL,
    narrative_draft_markdown TEXT NOT NULL DEFAULT '',
    talking_points_json TEXT NOT NULL,
    verification_checklist_json TEXT NOT NULL,
    evidence_brief_json TEXT NOT NULL DEFAULT '{}',
    angle TEXT NOT NULL DEFAULT '',
    audience TEXT NOT NULL DEFAULT '',
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
);

CREATE TABLE IF NOT EXISTS run_metrics (
    run_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    row_count INTEGER NOT NULL,
    model_route_used TEXT NOT NULL,
    error_message TEXT NOT NULL,
    PRIMARY KEY (run_id, stage_name)
);

-- model_route_used already exists in the CREATE TABLE statements above.

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
);
