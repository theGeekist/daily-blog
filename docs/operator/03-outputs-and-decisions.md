# Outputs and Decisions

This file explains what to do with generated outputs.

## `data/daily_board.md`

What it is:
- ranked shortlist from scoring
- includes component scores (novelty, recency, corroboration, etc.)

How to use it:
- pick top 3-5 items for editorial drafting
- reject low-novelty or repetitive items
- compare score distribution day to day

Decision checklist:
- Is this topic new enough?
- Does it have evidence breadth?
- Is it actionable for your audience?

## `data/top_outlines.md`

What it is:
- topic-level title options and structured outline

How to use it:
- select one outline per chosen topic
- refine hook/thesis before publishing
- convert directly into a draft in your writing workflow

## `data/research_pack.json`

What it is:
- machine-readable evidence bundle per topic
- source URLs and credibility tags

How to use it:
- verify factual claims before publishing
- build citation footnotes
- inspect weak evidence clusters and deprioritize them

## Quick visualization ideas

1. Build a small notebook/dashboard from SQLite:
- top topics by score
- source diversity by topic
- daily novelty trend

2. Add a weekly roll-up view:
- which topics repeat
- which sources dominate
- which models/routes are failing more often

## Why outputs feel disconnected without context

The outputs are intentionally stage-specific. The connection is:

- `daily_board.md` -> selection input
- `top_outlines.md` -> drafting input
- `research_pack.json` -> verification input

Use all three together before deciding what to publish.
