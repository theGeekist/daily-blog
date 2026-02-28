from typing import Any

from daily_blog.enrichment.helpers import credibility_rank


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
        sum(
            credibility_rank(str(row[3] or "").strip().lower())
            for row in fetched_rows
        )
        / fetched_count
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
