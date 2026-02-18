#!/usr/bin/env python3
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator_utils import ModelCallError, call_model

DEFAULT_SQLITE_PATH = "./data/daily-blog.db"
DEFAULT_TOP_OUTLINES_PATH = "./data/top_outlines.md"
DEFAULT_RESEARCH_PACK_PATH = "./data/research_pack.json"
DEFAULT_MODEL_ROUTING_PATH = "./config/model-routing.json"
DEFAULT_RULES_ENGINE_PATH = "./config/rules-engine.json"
EDITORIAL_STAGE = "editorial"

EDITORIAL_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "title_options",
        "outline_markdown",
        "narrative_draft_markdown",
        "talking_points",
        "verification_checklist",
        "angle",
        "audience",
    ],
    "properties": {
        "title_options": {
            "type": "array",
            "items": {"type": "string"},
        },
        "outline_markdown": {"type": "string"},
        "narrative_draft_markdown": {"type": "string"},
        "talking_points": {
            "type": "array",
            "items": {"type": "string"},
        },
        "verification_checklist": {
            "type": "array",
            "items": {"type": "string"},
        },
        "angle": {"type": "string"},
        "audience": {"type": "string"},
    },
}


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
            "ALTER TABLE editorial_candidates ADD COLUMN narrative_draft_markdown TEXT NOT NULL DEFAULT ''"
        )
    if "evidence_status" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN evidence_status TEXT NOT NULL DEFAULT 'WARN'"
        )
    if "evidence_reasons_json" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN evidence_reasons_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "evidence_ui_state" not in columns:
        conn.execute(
            "ALTER TABLE editorial_candidates ADD COLUMN evidence_ui_state TEXT NOT NULL DEFAULT ''"
        )
    conn.commit()


def load_model_route(path: Path) -> str:
    if not path.exists():
        return "codex-5.3"
    obj = json.loads(path.read_text(encoding="utf-8"))
    return str(obj.get(EDITORIAL_STAGE, {}).get("primary", "codex-5.3"))


def load_rules(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    obj = json.loads(path.read_text(encoding="utf-8"))
    return obj if isinstance(obj, dict) else {}


def outline_for_topic(label: str, why: str) -> str:
    return "\n".join(
        [
            f"# {label}: practical breakdown",
            "",
            "## Hook",
            f"Why now: {why}",
            "",
            "## Thesis",
            "A useful system wins by balancing signal quality, novelty, and execution cost.",
            "",
            "## Sections",
            "1. What changed and why it matters",
            "2. Failure modes and trade-offs",
            "3. Implementation checklist",
            "",
            "## Counterpoints",
            "- What could invalidate this angle?",
            "- Which assumptions need fresh evidence?",
            "",
            "## Conclusion",
            "Summarize decision criteria and next action for readers.",
        ]
    )


def narrative_draft_for_topic(label: str, why: str) -> str:
    return "\n".join(
        [
            f"## Intro hook: why {label} matters now",
            f"- Immediate context: {why}",
            "- Reader tension: what decision is unclear right now?",
            "",
            "## Storyline",
            "- Setup: what changed recently",
            "- Conflict: what teams are getting wrong",
            "- Resolution: a practical approach validated by evidence",
            "",
            "## Sections",
            "1. Signal map: the strongest evidence and what it proves",
            "2. Decision framework: options, trade-offs, and constraints",
            "3. Execution plan: actions teams can do this week",
            "",
            "## Outro",
            "- Re-state the core decision rubric",
            "- Give a concrete next action and verification checkpoint",
        ]
    )


def static_editorial_package(label: str, why: str) -> dict[str, Any]:
    return {
        "title_options": [
            f"{label}: what changed, what to do next",
            f"A practical guide to {label.lower()}",
            f"{label}: decision framework for teams",
        ],
        "outline_markdown": outline_for_topic(label, why),
        "narrative_draft_markdown": narrative_draft_for_topic(label, why),
        "talking_points": [
            "Signal extraction from noisy inputs",
            "Trade-offs and implementation costs",
            "Verification-first publishing workflow",
        ],
        "verification_checklist": [
            "Every key claim has at least one fetched citation",
            "Title is non-duplicative against recent runs",
            "Outline includes hook, thesis, sections, counterpoints, conclusion",
        ],
        "angle": "Pragmatic execution guide for teams making real publishing decisions.",
        "audience": (
            "Editors, analysts, and technical operators publishing evidence-backed explainers."
        ),
    }


def blocked_editorial_package(label: str, why: str, reasons: list[str]) -> dict[str, Any]:
    evidence_reasons = "; ".join(reasons) if reasons else "insufficient evidence quality"
    return {
        "title_options": [f"Blocked: {label} (insufficient evidence)"],
        "outline_markdown": "\n".join(
            [
                f"## Evidence gate blocked: {label}",
                "",
                f"Why now: {why}",
                "",
                "## Blocking reasons",
                f"- {evidence_reasons}",
                "",
                "## Next actions",
                "1. Enrich this topic until fetched source threshold is met.",
                "2. Re-run pipeline and review evidence status before editorial drafting.",
            ]
        ),
        "talking_points": [
            "Recommendation blocked until evidence quality thresholds are met.",
            "Prioritize additional fetched and credible sources before publishing.",
        ],
        "verification_checklist": [
            "At least 3 sources linked to the topic",
            "At least 50% of sources fetched successfully",
            "Average credibility at least medium",
            "At least 2 distinct source domains",
        ],
        "angle": "Evidence gate blocked this recommendation.",
        "audience": "Operators validating evidence quality before editorial output.",
        "narrative_draft_markdown": "\n".join(
            [
                f"## Intro hook: {label} is currently blocked",
                "- This topic cannot proceed to publication because evidence thresholds failed.",
                "",
                "## Storyline",
                "- Setup: candidate identified as potentially relevant",
                "- Conflict: fetched/credible evidence was insufficient",
                "- Resolution: enrich and verify before drafting",
                "",
                "## Sections",
                "1. Evidence gaps and missing validation",
                "2. Data collection plan to close gaps",
                "3. Re-validation checklist for readiness",
                "",
                "## Outro",
                "- Do not publish until evidence status is PASS.",
            ]
        ),
    }


def credibility_score(credibility_guess: str) -> int:
    guess = str(credibility_guess or "").strip().lower()
    if guess == "high":
        return 3
    if guess == "medium":
        return 2
    return 1


def compute_evidence_assessment(
    source_rows: list[tuple[Any, Any, Any, Any]],
    topic_evidence_types: set[str],
    rules_obj: dict[str, Any],
) -> dict[str, Any]:
    thresholds = rules_obj.get("evidence_thresholds", {})
    fail_states = rules_obj.get("evidence_fail_states", {})
    min_sources = int(thresholds.get("min_sources", 3))
    min_fetched_ratio = float(thresholds.get("min_fetched_ratio", 0.5))
    min_avg_cred = float(thresholds.get("min_avg_credibility_score", 2.0))
    warn_min_fetched_ratio = float(thresholds.get("warn_min_fetched_ratio", 0.7))
    warn_min_avg_cred = float(thresholds.get("warn_min_avg_credibility_score", 3.0))
    min_domain_diversity = int(thresholds.get("min_domain_diversity", 2))
    block_anecdote = bool(thresholds.get("block_anecdote_without_min_sources", True))

    total_sources = len(source_rows)
    fetched_rows = [row for row in source_rows if int(row[2] or 0) == 1]
    fetched_count = len(fetched_rows)
    fetched_ratio = (fetched_count / total_sources) if total_sources else 0.0
    avg_cred = (
        sum(credibility_score(str(row[3] or "")) for row in fetched_rows) / fetched_count
        if fetched_count
        else 0.0
    )
    domain_diversity = len({str(row[0] or "").strip().lower() for row in fetched_rows if row[0]})
    evidence_types = {str(v).strip().lower() for v in topic_evidence_types if v}

    reasons: list[str] = []
    status = "PASS"

    if total_sources < min_sources:
        status = "BLOCK"
        reasons.append(f"source_count={total_sources} below minimum {min_sources}")
    if fetched_ratio < min_fetched_ratio:
        status = "BLOCK"
        reasons.append(f"fetched_ratio={fetched_ratio:.2f} below minimum {min_fetched_ratio:.2f}")
    if avg_cred < min_avg_cred:
        status = "BLOCK"
        reasons.append(f"avg_credibility={avg_cred:.2f} below minimum {min_avg_cred:.2f}")
    if block_anecdote and evidence_types == {"anecdote"} and total_sources < min_sources:
        status = "BLOCK"
        reasons.append("only anecdotal claims with insufficient source count")

    if status != "BLOCK":
        if fetched_ratio < warn_min_fetched_ratio:
            status = "WARN"
            reasons.append(
                f"fetched_ratio={fetched_ratio:.2f} below recommended {warn_min_fetched_ratio:.2f}"
            )
        if avg_cred < warn_min_avg_cred:
            status = "WARN"
            reasons.append(
                f"avg_credibility={avg_cred:.2f} below recommended {warn_min_avg_cred:.2f}"
            )
        if domain_diversity < min_domain_diversity:
            status = "WARN"
            reasons.append(
                f"domain_diversity={domain_diversity} below minimum {min_domain_diversity}"
            )

    if not reasons and status == "PASS":
        reasons.append("all evidence thresholds satisfied")

    state_cfg = fail_states.get(status, {}) if isinstance(fail_states, dict) else {}
    ui_state = str(state_cfg.get("ui_state", status)).strip() or status
    output_suppressed = bool(state_cfg.get("output_suppressed", status == "BLOCK"))
    return {
        "status": status,
        "reasons": reasons,
        "ui_state": ui_state,
        "output_suppressed": output_suppressed,
        "metrics": {
            "source_count": total_sources,
            "fetched_count": fetched_count,
            "fetched_ratio": round(fetched_ratio, 4),
            "avg_credibility": round(avg_cred, 4),
            "domain_diversity": domain_diversity,
            "evidence_types": sorted(evidence_types),
        },
    }


def has_min_outline_sections(outline_markdown: str, minimum: int = 3) -> bool:
    headings: set[str] = set()
    for line in outline_markdown.splitlines():
        match = re.match(r"^###?\s+(.+?)\s*$", line.strip())
        if match:
            headings.add(match.group(1).lower())
    return len(headings) >= minimum


def build_editorial_prompt(
    topic_label: str,
    why_it_matters: str,
    time_horizon: str,
    validated_sources: list[dict[str, Any]],
) -> str:
    source_lines = [
        f"- {src['domain']} | {src['credibility_guess']} | {src['url']}"
        for src in validated_sources
    ]
    if not source_lines:
        source_lines = ["- no validated sources available"]

    return "\n".join(
        [
            (
                "Generate a high-quality editorial package including title options, "
                "a detailed outline, key talking points, and a verification checklist."
            ),
            "",
            "Return JSON only. No prose outside JSON.",
            "",
            "Topic context:",
            f"- label: {topic_label}",
            f"- why_it_matters: {why_it_matters}",
            f"- time_horizon: {time_horizon}",
            "- validated_sources:",
            *source_lines,
            "",
            "Required JSON shape:",
            "{",
            '  "title_options": ["...", "...", "..."],',
            '  "outline_markdown": "...",',
            '  "narrative_draft_markdown": "...",',
            '  "talking_points": ["..."],',
            '  "verification_checklist": ["..."],',
            '  "angle": "...",',
            '  "audience": "..."',
            "}",
            "",
            "Quality requirements:",
            "- At least 3 non-redundant title options.",
            (
                "- outline_markdown must include at least 3 distinct markdown "
                "sections using H2 or H3 headings."
            ),
            (
                "- narrative_draft_markdown must include H2 sections for Intro hook, "
                "Storyline, Sections, and Outro."
            ),
            "- talking_points should be specific and execution oriented.",
            (
                "- verification_checklist should focus on factual correctness and "
                "source-backed claims."
            ),
        ]
    )


def validate_editorial_package(package: dict[str, Any]) -> None:
    for key in ("title_options", "talking_points", "verification_checklist"):
        values = package.get(key)
        if not isinstance(values, list) or not values:
            raise ModelCallError(f"editorial package missing non-empty list for '{key}'")
        if not all(isinstance(item, str) and item.strip() for item in values):
            raise ModelCallError(f"editorial package has invalid entries for '{key}'")

    outline = package.get("outline_markdown", "")
    if not isinstance(outline, str) or not outline.strip():
        raise ModelCallError("editorial package missing non-empty outline_markdown")
    if not has_min_outline_sections(outline, minimum=3):
        raise ModelCallError(
            "editorial package failed quality gate: outline needs >= 3 distinct H2/H3 sections"
        )

    narrative = package.get("narrative_draft_markdown", "")
    if not isinstance(narrative, str) or not narrative.strip():
        raise ModelCallError("editorial package missing non-empty narrative_draft_markdown")
    lower = narrative.lower()
    required_markers = ["## intro", "## storyline", "## sections", "## outro"]
    missing_markers = [m for m in required_markers if m not in lower]
    if missing_markers:
        raise ModelCallError(
            "editorial package failed narrative gate: missing sections "
            + ", ".join(missing_markers)
        )

    for key in ("angle", "audience"):
        value = package.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ModelCallError(f"editorial package missing non-empty '{key}'")


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

        static_only = os.getenv("EDITORIAL_STATIC_ONLY", "0") == "1"
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
