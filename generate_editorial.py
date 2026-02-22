#!/usr/bin/env python3
import json
import os
import sqlite3
import sys
from pathlib import Path

from daily_blog.core.env import load_env_file
from daily_blog.core.time_utils import now_iso
from daily_blog.editorial.evidence import compute_evidence_assessment
from daily_blog.editorial.model_io import (
    EDITORIAL_RESPONSE_SCHEMA,
    EDITORIAL_STAGE,
    build_editorial_prompt,
    load_model_route,
    load_rules,
    validate_editorial_package,
)
from daily_blog.editorial.store import init_candidate_dossiers_table, init_editorial_table
from daily_blog.editorial.synthesis import synthesize_evidence_brief
from daily_blog.editorial.templates import blocked_editorial_package, static_editorial_package
from orchestrator_utils import ModelCallError, call_model

DEFAULT_SQLITE_PATH = "./data/daily-blog.db"
DEFAULT_TOP_OUTLINES_PATH = "./data/top_outlines.md"
DEFAULT_RESEARCH_PACK_PATH = "./data/research_pack.json"
DEFAULT_MODEL_ROUTING_PATH = "./config/model-routing.json"
DEFAULT_RULES_ENGINE_PATH = "./config/rules-engine.json"
DEFAULT_DOSSIER_DIR = "./data/candidates"


def _safe_slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value.lower())
    return "-".join(part for part in cleaned.split("-") if part) or "unknown"


def _recommendation_for(
    evidence_status: str,
    fetched_sources: int,
    topic_confidence: float,
    source_count: int,
) -> str:
    if topic_confidence < float(os.getenv("TOPIC_CONFIDENCE_THRESHOLD", "0.3")):
        return "hold"
    if evidence_status == "BLOCK":
        return "reject"
    if evidence_status == "WARN" and fetched_sources == 0:
        return "investigate"
    if evidence_status == "WARN":
        return "draft_with_caution"
    if source_count == 0:
        return "investigate"
    return "draft_with_caution"


def _build_dossier_markdown(dossier: dict) -> str:
    source = dossier.get("source", {})
    extraction = dossier.get("extraction", {})
    scoring = dossier.get("scoring", {})
    evidence = dossier.get("evidence", {})
    editorial = dossier.get("editorial", {})
    provenance = dossier.get("raw_capture", {})

    def _list(items: list[str], fallback: str) -> str:
        rows = [str(i).strip() for i in items if str(i).strip()]
        if not rows:
            return f"- {fallback}"
        return "\n".join(f"- {item}" for item in rows)

    classification = dossier.get("classification", {})
    vertical_fit = classification.get("vertical_fit", {})
    angles = [a.get("title", "") for a in editorial.get("angles", [])]

    return "\n".join(
        [
            f"# Candidate Dossier: {source.get('title', '(untitled)')}",
            "",
            "## Snapshot",
            f"- Recommendation: **{scoring.get('editorial_recommendation', 'investigate')}**",
            (
                f"- Confidence: topic="
                f"{classification.get('topic_confidence', 0.0):.2f}"
            ),
            f"- Evidence: {evidence.get('status', 'WARN')} ({evidence.get('ui_state', 'unknown')})",
            f"- Why interesting: {editorial.get('why_interesting', 'No summary available.')}",
            "",
            "## Candidate Understanding",
            f"- Candidate type: {extraction.get('candidate_type', 'unknown')}",
            f"- Post intent: {', '.join(extraction.get('post_intent', [])) or 'unknown'}",
            f"- Core problem: {extraction.get('core_problem', 'Not extracted')}",
            f"- Solution pattern: {extraction.get('solution_pattern', 'Not extracted')}",
            f"- Audience fit: {vertical_fit.get('primary', 'unknown')}",
            "",
            "## Editorial Potential",
            _list(angles, "No angles generated."),
            "",
            "## Verification and Risks",
            "### Verification plan",
            _list(editorial.get("verification_plan", []), "No verification plan."),
            "",
            "### Reason codes",
            _list(evidence.get("reason_codes", []), "none"),
            "",
            "## Draft Seed",
            f"- Hook: {editorial.get('outline_seed', {}).get('hook', '')}",
            f"- Thesis: {editorial.get('outline_seed', {}).get('thesis', '')}",
            "### Sections",
            _list(editorial.get("outline_seed", {}).get("sections", []), "No sections."),
            "",
            "## Provenance",
            f"- URL: {source.get('url', '')}",
            f"- Published at: {source.get('published_at', '')}",
            f"- Source platform: {source.get('platform', '')}",
            f"- Raw summary: {str(provenance.get('summary', ''))}",
            "",
        ]
    )


def main() -> int:
    load_env_file(Path(".env"))
    sqlite_path = Path(os.getenv("SQLITE_PATH", DEFAULT_SQLITE_PATH))
    outlines_path = Path(os.getenv("TOP_OUTLINES_PATH", DEFAULT_TOP_OUTLINES_PATH))
    research_path = Path(os.getenv("RESEARCH_PACK_PATH", DEFAULT_RESEARCH_PACK_PATH))
    routing_path = Path(os.getenv("MODEL_ROUTING_CONFIG", DEFAULT_MODEL_ROUTING_PATH))
    rules_path = Path(os.getenv("RULES_ENGINE_CONFIG", DEFAULT_RULES_ENGINE_PATH))

    if not sqlite_path.exists():
        print(f"SQLite DB not found: {sqlite_path}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(sqlite_path)
    init_editorial_table(conn)
    init_candidate_dossiers_table(conn)
    model_route = load_model_route(routing_path)
    rules_obj = load_rules(rules_path)
    topic_columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(topic_clusters)").fetchall()
        if len(row) > 1
    }
    has_topic_confidence = "topic_confidence" in topic_columns
    topic_query = (
        """
        SELECT topic_id, parent_topic_label, why_it_matters, time_horizon,
               parent_topic_slug, topic_confidence
        FROM topic_clusters
        ORDER BY claim_count DESC
        """
        if has_topic_confidence
        else """
        SELECT topic_id, parent_topic_label, why_it_matters, time_horizon, parent_topic_slug
        FROM topic_clusters
        ORDER BY claim_count DESC
        """
    )
    topics = conn.execute(topic_query).fetchall()
    if not topics:
        print("No topics found. Run lift_topics.py first.", file=sys.stderr)
        conn.close()
        return 2

    now = now_iso()
    run_id = os.getenv("PIPELINE_RUN_ID", "").strip()
    if not run_id:
        try:
            row = conn.execute("SELECT MAX(run_id) FROM candidate_scores").fetchone()
            run_id = str((row[0] if row else "") or "manual-run")
        except sqlite3.OperationalError:
            run_id = "manual-run"
    md_lines = ["# Top Outlines", ""]
    research_pack: list[dict] = []
    dossier_dir = Path(os.getenv("DOSSIER_OUTPUT_DIR", DEFAULT_DOSSIER_DIR)) / _safe_slug(run_id)
    dossier_dir.mkdir(parents=True, exist_ok=True)

    try:
        topic_evidence_type_rows = conn.execute(
            """
            SELECT ctm.topic_id, c.evidence_type
            FROM claim_topic_map ctm
            JOIN claims c ON c.claim_id = ctm.claim_id
            """
        ).fetchall()
    except sqlite3.OperationalError:
        topic_evidence_type_rows = []
    topic_evidence_types: dict[str, set[str]] = {}
    for tid, evidence_type in topic_evidence_type_rows:
        key = str(tid or "")
        if not key:
            continue
        topic_evidence_types.setdefault(key, set()).add(str(evidence_type or "").strip().lower())

    skip_misc = os.getenv("EDITORIAL_INCLUDE_MISC", "0") != "1"
    generated_count = 0
    for topic_row in topics:
        topic_id = topic_row[0]
        label = topic_row[1]
        why = topic_row[2]
        time_horizon = topic_row[3]
        slug = topic_row[4]
        stored_topic_confidence = (
            topic_row[5] if has_topic_confidence and len(topic_row) > 5 else None
        )
        if skip_misc and str(slug) == "misc":
            continue
        generated_count += 1
        try:
            candidate_row = conn.execute(
                """
                SELECT c.entry_id, c.final_score, c.novelty_status, c.novelty_score,
                       c.recency_score,
                       c.corroboration_score, c.source_diversity_score, c.actionability_score,
                       m.title, m.url, m.source, m.summary, m.published
                FROM candidate_scores c
                LEFT JOIN mentions m ON m.entry_id = c.entry_id
                WHERE c.run_id = ? AND c.topic = ?
                ORDER BY c.rank_index ASC
                LIMIT 1
                """,
                (run_id, str(slug)),
            ).fetchone()
        except sqlite3.OperationalError:
            candidate_row = None
        entry_id = str(candidate_row[0]) if candidate_row else ""

        try:
            claim_rows = conn.execute(
                """
                SELECT c.claim_id, c.headline, c.problem_pressure, c.proposed_solution,
                       c.evidence_type
                FROM claims c
                JOIN claim_topic_map ctm ON ctm.claim_id = c.claim_id
                WHERE ctm.topic_id = ?
                """,
                (topic_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            claim_rows = []
        claims = [
            {
                "claim_id": str(claim_id or ""),
                "headline": str(headline or ""),
                "problem_pressure": str(problem_pressure or ""),
                "proposed_solution": str(proposed_solution or ""),
                "evidence_type": str(evidence_type or ""),
            }
            for claim_id, headline, problem_pressure, proposed_solution, evidence_type in claim_rows
        ]
        if entry_id:
            entry_claim_rows = conn.execute(
                """
                SELECT c.claim_id, c.headline, c.problem_pressure, c.proposed_solution,
                       c.evidence_type
                FROM claims c
                JOIN claim_topic_map ctm ON ctm.claim_id = c.claim_id
                WHERE c.entry_id = ? AND ctm.topic_id = ?
                """,
                (entry_id, topic_id),
            ).fetchall()
            scoped_claims = [
                {
                    "claim_id": str(claim_id or ""),
                    "headline": str(h or ""),
                    "problem_pressure": str(p or ""),
                    "proposed_solution": str(s or ""),
                    "evidence_type": str(e or ""),
                }
                for claim_id, h, p, s, e in entry_claim_rows
            ]
            if scoped_claims:
                claims = scoped_claims
        sources = conn.execute(
            """
            SELECT domain, url, fetched_ok, credibility_guess, stance
            FROM enrichment_sources
            WHERE topic_id = ?
            ORDER BY credibility_guess DESC
            """,
            (topic_id,),
        ).fetchall()
        assessment = compute_evidence_assessment(
            source_rows=sources,
            topic_evidence_types=topic_evidence_types.get(str(topic_id), set()),
            rules_obj=rules_obj,
        )
        evidence_status = str(assessment["status"])
        evidence_ui_state = str(assessment["ui_state"])
        evidence_reasons = [str(r) for r in assessment.get("reasons", [])]
        valid_sources = [
            {"domain": d, "url": u, "credibility_guess": c, "stance": s}
            for d, u, fetched_ok, c, s in sources
            if int(fetched_ok) == 1
        ]
        evidence_brief, evidence_synthesis_route = synthesize_evidence_brief(
            topic_id=str(topic_id),
            topic_label=str(label),
            claims=claims,
            validated_sources=valid_sources,
        )
        topic_confidence = (
            float(stored_topic_confidence)
            if stored_topic_confidence is not None
            else (0.35 if str(slug) == "misc" else 0.8)
        )

        static_only = os.getenv("EDITORIAL_STATIC_ONLY", "0") == "1"
        outline_strategy = str(evidence_brief.get("outline_strategy", "explainer"))
        if bool(assessment.get("output_suppressed")):
            package = blocked_editorial_package(label, why, evidence_reasons)
            model_route_used = "evidence-gate:block"
        elif static_only:
            package = static_editorial_package(label, why, strategy=outline_strategy)
            model_route_used = f"static-only:{model_route}"
        else:
            prompt = build_editorial_prompt(
                topic_label=label,
                why_it_matters=why,
                time_horizon=time_horizon,
                validated_sources=valid_sources,
                evidence_brief=evidence_brief,
                claims=claims,
            )
            try:
                response = call_model(EDITORIAL_STAGE, prompt, schema=EDITORIAL_RESPONSE_SCHEMA)
                package = response["content"]
                validate_editorial_package(package)
                model_route_used = str(response["model_used"])
            except ModelCallError:
                package = static_editorial_package(label, why, strategy=outline_strategy)
                model_route_used = f"static-template:{model_route}"

        title_options = package["title_options"]
        talking_points = package["talking_points"]
        checklist = package["verification_checklist"]
        outline = package["outline_markdown"]
        narrative_draft = package["narrative_draft_markdown"]
        angle = package["angle"]
        audience = package["audience"]

        conn.execute(
            """
            INSERT OR REPLACE INTO editorial_candidates (
                topic_id, title_options_json, outline_markdown, narrative_draft_markdown,
                talking_points_json, verification_checklist_json,
                evidence_brief_json, angle, audience, evidence_status, evidence_reasons_json,
                evidence_ui_state, model_route_used, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                topic_id,
                json.dumps(title_options, ensure_ascii=True),
                outline,
                narrative_draft,
                json.dumps(talking_points, ensure_ascii=True),
                json.dumps(checklist, ensure_ascii=True),
                json.dumps(evidence_brief, ensure_ascii=True),
                angle,
                audience,
                evidence_status,
                json.dumps(evidence_reasons, ensure_ascii=True),
                evidence_ui_state,
                model_route_used,
                now,
            ),
        )

        prefix = (
            "[BLOCKED]"
            if evidence_status == "BLOCK"
            else "[WARN]"
            if evidence_status == "WARN"
            else "[READY]"
        )
        md_lines.append(f"## {label}")
        md_lines.append(f"- topic_id: {topic_id}")
        md_lines.append(f"- recommendation_gate: {prefix}")
        md_lines.append(f"- evidence_status: {evidence_status} ({evidence_ui_state})")
        md_lines.append(f"- evidence_reasons: {'; '.join(evidence_reasons)}")
        md_lines.append(f"- model_route_used: {model_route_used}")
        md_lines.append(f"- evidence_synthesis_route: {evidence_synthesis_route}")
        md_lines.append(f"- angle: {angle}")
        md_lines.append(f"- audience: {audience}")
        md_lines.append("- title options:")
        for t in title_options:
            md_lines.append(f"  - {t}")
        md_lines.append("- outline:")
        md_lines.append("```markdown")
        md_lines.append(outline)
        md_lines.append("```")
        md_lines.append("- narrative_draft:")
        md_lines.append("```markdown")
        md_lines.append(narrative_draft)
        md_lines.append("```")
        md_lines.append("")

        research_pack.append(
            {
                "topic_id": topic_id,
                "topic_label": label,
                "time_horizon": time_horizon,
                "angle": angle,
                "audience": audience,
                "sources": valid_sources,
                "checklist": checklist,
                "narrative_draft_markdown": narrative_draft,
                "evidence_status": evidence_status,
                "evidence_ui_state": evidence_ui_state,
                "evidence_reasons": evidence_reasons,
                "evidence_metrics": assessment.get("metrics", {}),
                "evidence_brief": evidence_brief,
                "evidence_synthesis_route": evidence_synthesis_route,
            }
        )

        dossier_scope = "entry" if entry_id else "topic"
        if not entry_id:
            entry_id = f"topic-{_safe_slug(str(topic_id))}"
        discovery_total = round(float(candidate_row[1] or 0.0), 4) if candidate_row else 0.0
        fetched_count = int(assessment.get("metrics", {}).get("fetched_count", 0) or 0)
        source_count = int(assessment.get("metrics", {}).get("source_count", 0) or 0)
        recommendation = _recommendation_for(
            evidence_status=evidence_status,
            fetched_sources=fetched_count,
            topic_confidence=topic_confidence,
            source_count=source_count,
        )
        threshold = float(os.getenv("TOPIC_CONFIDENCE_THRESHOLD", "0.3"))
        reason_codes: list[str] = []
        if evidence_status == "BLOCK":
            reason_codes.append("EVIDENCE_BLOCK")
        elif evidence_status == "WARN":
            reason_codes.append("EVIDENCE_WARN")
        if topic_confidence < threshold:
            reason_codes.append("TOPIC_UNCERTAIN")
        if fetched_count == 0:
            reason_codes.append("NO_FETCHED_SOURCES")
        if not reason_codes:
            reason_codes.append("NONE")

        evidence_coverage = assessment.get("metrics", {}).get("fetched_ratio")
        source_quality = assessment.get("metrics", {}).get("avg_credibility")
        corroboration = (
            None if fetched_count == 0 or not candidate_row else float(candidate_row[5] or 0.0)
        )
        source_diversity = (
            None if fetched_count == 0 or not candidate_row else float(candidate_row[6] or 0.0)
        )
        publishability_total = (
            None
            if fetched_count == 0 or not candidate_row
            else round((float(candidate_row[5] or 0) + float(candidate_row[6] or 0)) / 2, 4)
        )
        publishability_values = (
            evidence_coverage,
            source_quality,
            corroboration,
            source_diversity,
        )
        if all(value is not None for value in publishability_values):
            publishability_state = "evaluated"
        elif any(value is not None for value in publishability_values):
            publishability_state = "partial"
        else:
            publishability_state = "not_evaluated"

        top_claims = [
            str(item).strip()
            for item in evidence_brief.get("top_claims", [])
            if str(item).strip()
        ]
        if not top_claims:
            top_claims = [str(c.get("headline", "")).strip() for c in claims if c.get("headline")]
        outline_sections = top_claims[:5]
        if not outline_sections:
            outline_sections = [
                line.strip("# ").strip() for line in outline.splitlines() if line.startswith("## ")
            ][:5]

        dossier = {
            "meta": {
                "run_id": run_id,
                "entry_id": entry_id,
                "dossier_scope": dossier_scope,
                "generated_at": now,
                "schema_version": "2.0.0",
            },
            "source": {
                "platform": (
                    "reddit"
                    if dossier_scope == "entry" and entry_id.startswith("t3_")
                    else ("rss" if dossier_scope == "entry" else "")
                ),
                "url": (
                    str(candidate_row[9] or "")
                    if dossier_scope == "entry" and candidate_row
                    else ""
                ),
                "title": (
                    str(candidate_row[8] or "")
                    if dossier_scope == "entry" and candidate_row
                    else str(label or "")
                ),
                "published_at": (
                    str(candidate_row[12] or "")
                    if dossier_scope == "entry" and candidate_row
                    else ""
                ),
                "engagement": {},
            },
            "extraction": {
                "candidate_type": "practitioner_help_request"
                if "help" in str(candidate_row[11] if candidate_row else "").lower()
                else "news_event",
                "post_intent": ["showcase", "request_feedback"]
                if "feedback" in str(candidate_row[11] if candidate_row else "").lower()
                else ["discuss"],
                "domains": [str(slug or "misc")],
                "stack_detected": [],
                "core_problem": (claims[0].get("problem_pressure", "") if claims else ""),
                "solution_pattern": (claims[0].get("proposed_solution", "") if claims else ""),
                "author_ask": [],
                "artifacts_present": [],
            },
            "classification": {
                "topic_primary": str(slug or "misc"),
                "topic_secondary": [],
                "topic_confidence": topic_confidence,
                "vertical_fit": {
                    "primary": "Tame the Tech",
                    "cluster": "Where the User Begins",
                },
                "reader_level": "intermediate",
            },
            "scoring": {
                "discovery": {
                    "total": discovery_total,
                    "novelty": float(candidate_row[3] or 0.0) if candidate_row else 0.0,
                    "recency": float(candidate_row[4] or 0.0) if candidate_row else 0.0,
                    "actionability": float(candidate_row[7] or 0.0) if candidate_row else 0.0,
                },
                "publishability": {
                    "state": publishability_state,
                    "evidence_coverage": evidence_coverage,
                    "source_quality": source_quality,
                    "corroboration": corroboration,
                    "source_diversity": source_diversity,
                    "total": publishability_total,
                },
                "editorial_recommendation": recommendation,
            },
            "evidence": {
                "status": evidence_status.lower(),
                "ui_state": evidence_ui_state,
                "reason_codes": list(dict.fromkeys(reason_codes)),
                "verified_sources": valid_sources,
            },
            "editorial": {
                "why_interesting": str(why or "").strip(),
                "angles": [
                    {"title": t, "type": "candidate-specific", "fit_score": 0.75}
                    for t in title_options[:3]
                ],
                "verification_plan": checklist,
                "outline_seed": {
                    "hook": (
                        top_claims[0]
                        if top_claims
                        else (claims[0].get("headline", "") if claims else "")
                    ),
                    "thesis": (
                        "Dominant evidence pattern: "
                        f"{evidence_brief.get('dominant_pattern', 'unknown')}. "
                        f"Strategy: {evidence_brief.get('outline_strategy', 'explainer')}."
                    ),
                    "sections": outline_sections,
                },
            },
            "raw_capture": {
                "summary": str(candidate_row[11] or "") if candidate_row else "",
                "comments_snapshot": [],
                "media_links": [],
            },
        }
        conn.execute(
            """
            INSERT OR REPLACE INTO candidate_dossiers (
                run_id, entry_id, schema_version, raw_capture_json, normalized_candidate_json,
                editorial_decision_json, discovery_score_json, publishability_score_json,
                recommendation, reason_codes_json, topic_confidence,
                classifier_trace_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                entry_id,
                "2.0.0",
                json.dumps(dossier.get("raw_capture", {}), ensure_ascii=True),
                json.dumps(
                    {
                        "extraction": dossier.get("extraction", {}),
                        "classification": dossier.get("classification", {}),
                    },
                    ensure_ascii=True,
                ),
                json.dumps(dossier.get("editorial", {}), ensure_ascii=True),
                json.dumps(dossier.get("scoring", {}).get("discovery", {}), ensure_ascii=True),
                json.dumps(
                    dossier.get("scoring", {}).get("publishability", {}),
                    ensure_ascii=True,
                ),
                recommendation,
                json.dumps(
                    dossier.get("evidence", {}).get("reason_codes", []),
                    ensure_ascii=True,
                ),
                float(topic_confidence),
                json.dumps({"topic_slug": str(slug or "misc")}, ensure_ascii=True),
                now,
            ),
        )
        dossier_path = dossier_dir / f"{_safe_slug(entry_id)}.candidate.json"
        dossier_path.write_text(
            json.dumps(dossier, ensure_ascii=True, indent=2), encoding="utf-8"
        )
        md_path = dossier_dir / f"{_safe_slug(entry_id)}.candidate.md"
        md_path.write_text(_build_dossier_markdown(dossier), encoding="utf-8")

    conn.commit()
    conn.close()

    outlines_path.parent.mkdir(parents=True, exist_ok=True)
    research_path.parent.mkdir(parents=True, exist_ok=True)
    outlines_path.write_text("\n".join(md_lines), encoding="utf-8")
    research_path.write_text(
        json.dumps(research_pack, ensure_ascii=True, indent=2), encoding="utf-8"
    )

    print(f"Editorial candidates generated: {generated_count}")
    print(f"Outlines path: {outlines_path}")
    print(f"Research pack path: {research_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
