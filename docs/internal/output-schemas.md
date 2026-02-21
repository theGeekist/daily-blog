## Output Schemas

### claims
- `claim_id` TEXT PRIMARY KEY
- `entry_id` TEXT
- `headline` TEXT
- `who_cares` TEXT
- `problem_pressure` TEXT
- `proposed_solution` TEXT
- `evidence_type` TEXT
- `sources_json` TEXT (JSON array)
- `created_at` TEXT

### topic_clusters
- `topic_id` TEXT PRIMARY KEY
- `parent_topic_slug` TEXT
- `parent_topic_label` TEXT
- `why_it_matters` TEXT
- `time_horizon` TEXT (`flash|seasonal|evergreen`)
- `claim_count` INTEGER
- `keywords_json` TEXT (JSON array)
- `created_at` TEXT

### enrichment_sources
- `topic_id` TEXT
- `query_terms_json` TEXT (JSON array)
- `domain` TEXT
- `url` TEXT
- `stance` TEXT
- `credibility_guess` TEXT
- `fetched_ok` INTEGER (`0|1`)
- `created_at` TEXT

### editorial_candidates
- `topic_id` TEXT PRIMARY KEY
- `title_options_json` TEXT (JSON array)
- `outline_markdown` TEXT
- `talking_points_json` TEXT (JSON array)
- `verification_checklist_json` TEXT (JSON array)
- `model_route_used` TEXT
- `created_at` TEXT

### report files
- `data/daily_board.md` ranked candidates and score components
- `data/top_outlines.md` title options and outline per topic
- `data/research_pack.json` topic -> validated sources mapping
