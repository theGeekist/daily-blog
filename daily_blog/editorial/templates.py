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


def static_editorial_package(label: str, why: str) -> dict:
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


def blocked_editorial_package(label: str, why: str, reasons: list[str]) -> dict:
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
