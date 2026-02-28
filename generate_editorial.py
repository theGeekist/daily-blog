#!/usr/bin/env python3
import json
import os
import sqlite3
import sys
from pathlib import Path

from daily_blog.config import load_app_config
from daily_blog.core.env import load_env_file
from daily_blog.core.time_utils import now_iso
from daily_blog.editorial.evidence import compute_evidence_assessment
from daily_blog.editorial.prompt import (
    EDITORIAL_RESPONSE_SCHEMA,
    EDITORIAL_STAGE,
    build_editorial_prompt,
    load_model_route,
    load_rules,
    validate_editorial_package,
)
from daily_blog.editorial.store import init_editorial_table
from daily_blog.editorial.templates import blocked_editorial_package, static_editorial_package
from orchestrator_utils import ModelCallError, call_model

DEFAULT_SQLITE_PATH = "./data/daily-blog.db"
DEFAULT_TOP_OUTLINES_PATH = "./data/top_outlines.md"
DEFAULT_RESEARCH_PACK_PATH = "./data/research_pack.json"
DEFAULT_MODEL_ROUTING_PATH = "./config/model-routing.json"
DEFAULT_RULES_ENGINE_PATH = "./config/rules-engine.json"


def _load_discussion_signals(conn: sqlite3.Connection, topic_id: str) -> dict[str, list[str]]:
    try:
        rows = conn.execute(
            """
            SELECT problem_statements_json, solution_statements_json
            FROM discussion_receipts
            WHERE topic_id = ?
            """,
            (topic_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return {"problem_statements": [], "solution_statements": []}

    def _collect(index: int) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for row in rows:
            raw = row[index] if len(row) > index else "[]"
            try:
                loaded = json.loads(raw or "[]")
            except Exception:
                loaded = []
            if not isinstance(loaded, list):
                continue
            for item in loaded:
                if not isinstance(item, str):
                    continue
                cleaned = " ".join(item.strip().split())
                if not cleaned:
                    continue
                lowered = cleaned.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                out.append(cleaned)
                if len(out) >= 12:
                    return out
        return out

    return {
        "problem_statements": _collect(0),
        "solution_statements": _collect(1),
    }


def main() -> int:
    load_env_file(Path(".env"))
    project_root = Path(__file__).resolve().parent
    app_cfg = load_app_config(project_root=project_root, environ=os.environ)
    sqlite_path = app_cfg.paths.sqlite_path
    outlines_path = app_cfg.paths.top_outlines_path
    research_path = app_cfg.paths.research_pack_path
    routing_path = app_cfg.paths.model_routing_config
    rules_path = app_cfg.paths.rules_engine_config

    if not sqlite_path.exists():
        print(f"SQLite DB not found: {sqlite_path}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(sqlite_path)
    init_editorial_table(conn)
    model_route = load_model_route(routing_path)
    rules_obj = load_rules(rules_path)
    topics = conn.execute(
        """
        SELECT topic_id, parent_topic_label, why_it_matters, time_horizon
        FROM topic_clusters
        ORDER BY claim_count DESC
        """
    ).fetchall()
    if not topics:
        print("No topics found. Run lift_topics.py first.", file=sys.stderr)
        conn.close()
        return 2

    now = now_iso()
    md_lines = ["# Top Outlines", ""]
    research_pack: list[dict] = []

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

    for topic_id, label, why, time_horizon in topics:
        sources = conn.execute(
            """
            SELECT domain, url, fetched_ok, credibility_guess
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
            {"domain": d, "url": u, "credibility_guess": c}
            for d, u, fetched_ok, c in sources
            if int(fetched_ok) == 1
        ]

        static_only = app_cfg.editorial.static_only
        discussion_signals = _load_discussion_signals(conn, str(topic_id))
        if bool(assessment.get("output_suppressed")):
            package = blocked_editorial_package(label, why, evidence_reasons)
            model_route_used = "evidence-gate:block"
        elif static_only:
            package = static_editorial_package(label, why)
            model_route_used = f"static-only:{model_route}"
        else:
            prompt = build_editorial_prompt(
                topic_label=label,
                why_it_matters=why,
                time_horizon=time_horizon,
                validated_sources=valid_sources,
                problem_statements=discussion_signals["problem_statements"],
                solution_statements=discussion_signals["solution_statements"],
            )
            try:
                response = call_model(EDITORIAL_STAGE, prompt, schema=EDITORIAL_RESPONSE_SCHEMA)
                package = response["content"]
                validate_editorial_package(package)
                model_route_used = str(response["model_used"])
            except ModelCallError:
                package = static_editorial_package(label, why)
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
                angle, audience, evidence_status, evidence_reasons_json,
                evidence_ui_state, model_route_used, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                topic_id,
                json.dumps(title_options, ensure_ascii=True),
                outline,
                narrative_draft,
                json.dumps(talking_points, ensure_ascii=True),
                json.dumps(checklist, ensure_ascii=True),
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
                "discussion_signals": discussion_signals,
            }
        )

    conn.commit()
    conn.close()

    outlines_path.parent.mkdir(parents=True, exist_ok=True)
    research_path.parent.mkdir(parents=True, exist_ok=True)
    outlines_path.write_text("\n".join(md_lines), encoding="utf-8")
    research_path.write_text(
        json.dumps(research_pack, ensure_ascii=True, indent=2), encoding="utf-8"
    )

    print(f"Editorial candidates generated: {len(topics)}")
    print(f"Outlines path: {outlines_path}")
    print(f"Research pack path: {research_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
