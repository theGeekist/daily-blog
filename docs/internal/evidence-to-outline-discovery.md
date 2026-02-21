# Discovery: Evidence Gathering Does Not Inform Content Outlines

## Problem Statement

Evidence data (enrichment sources, claims, credibility scores) is gathered but **not used** to shape the content outline or narrative draft. The editorial stage either produces static templates or sends a prompt that mentions sources only as a flat list—never incorporating the actual evidence findings into the outline structure.

## Current Pipeline Flow (as-is)

```
mentions -> claims -> topic_clusters -> enrichment_sources -> editorial_candidates
```

### Where evidence is gathered

1. **Claims extraction** (`extract_claims.py`): Produces `headline`, `who_cares`, `problem_pressure`, `proposed_solution`, `evidence_type`, `sources_json` per mention. Currently 286 claims in DB.
2. **Enrichment** (`enrich_topics.py`): Discovers and verifies URLs per topic cluster. Produces `enrichment_sources` with `domain`, `stance`, `credibility_guess`, `fetched_ok`. Currently 47 rows, all from `reddit.com` with `medium` credibility.
3. **Evidence assessment** (`daily_blog/editorial/evidence.py:13`): `compute_evidence_assessment()` evaluates source count, fetched ratio, credibility avg, domain diversity. Returns PASS/WARN/BLOCK status.

### Where evidence is NOT used

4. **Editorial generation** (`generate_editorial.py:103-124`): Three paths:
   - `BLOCK` -> `blocked_editorial_package()` — static template with "insufficient evidence" messaging
   - `EDITORIAL_STATIC_ONLY=1` -> `static_editorial_package()` — **hardcoded template, zero evidence input**
   - LLM path -> `build_editorial_prompt()` — passes `validated_sources` as a flat URL list but **no claim details, no problem_pressure, no proposed_solution, no evidence_type**

### The disconnect in detail

`build_editorial_prompt()` at `daily_blog/editorial/model_io.py:65-121` receives:
- `topic_label`, `why_it_matters`, `time_horizon` (topic-level metadata only)
- `validated_sources` as `domain | credibility | url` lines

It does NOT receive:
- Individual claims (`headline`, `who_cares`, `problem_pressure`, `proposed_solution`)
- Evidence types per claim (data vs link vs anecdote)
- Stance information from enrichment (supports/contradicts/mixed)
- Corroboration patterns (which claims reinforce each other)
- The actual content/summaries from mentions

The static template path (`daily_blog/editorial/templates.py:1-74`) is even worse: `outline_for_topic()` and `narrative_draft_for_topic()` produce identical boilerplate for every topic, using only `label` and `why`.

## Observed Output Quality (from DB)

### All 5 editorial candidates are identical in structure

Every candidate uses `static-only:ollama:qwen2.5:14b` route, meaning the LLM was never called—the static template was used for all.

Evidence of template reuse (identical across all 5 topics):
- **Thesis**: "A useful system wins by balancing signal quality, novelty, and execution cost." (same for AI, Business, Engineering, Language, Misc)
- **Sections**: Always "1. What changed and why it matters, 2. Failure modes and trade-offs, 3. Implementation checklist"
- **Talking points**: Always "Signal extraction from noisy inputs / Trade-offs and implementation costs / Verification-first publishing workflow"
- **Angle**: Always "Pragmatic execution guide for teams making real publishing decisions."
- **Audience**: Always "Editors, analysts, and technical operators publishing evidence-backed explainers."

### Topic quality issues

- 214/286 claims (75%) clustered under "ai" — the topic lifter is over-grouping
- "misc" has 45 claims with empty keywords — a catch-all bucket
- All topics have `time_horizon: evergreen` and `model_route_used: heuristic-fallback` — the LLM topic lifter failed, falling back to keyword matching
- Enrichment sources are 100% reddit.com with uniform `medium` credibility and `neutral` stance — no diversity

### Claims quality issues

- Sample claims include non-actionable items: "Friday Tea Sipping Gossip Hour", "Interview Question", "What pays more than tech sales?"
- `model_route_used: None` on sampled claims — suggests heuristic fallback was used, not LLM extraction
- `evidence_type` is uniformly `link` — the detector is pattern-matching rather than analyzing content

## Root Causes

1. **`EDITORIAL_STATIC_ONLY=1` is set** — bypasses LLM entirely, producing template outlines that ignore all evidence
2. **Even the LLM prompt path doesn't pass claims** — `build_editorial_prompt()` only receives topic metadata + source URLs, not the rich claim data
3. **No evidence synthesis step** — there's no stage between enrichment and editorial that synthesizes "what the evidence actually says" into structured input
4. **Enrichment sources lack diversity** — `discover_web_sources()` in `daily_blog/enrichment/fetch.py` is producing only reddit URLs
5. **Model routing falls back to heuristics** — claims are extracted via simple string matching (keyword detection), not LLM analysis

## Relationship to Existing Plans

### `.sisyphus/plans/intelligence-layer.md`
Defines the full E2E pipeline with 7 stages. Stage 5 (Editor) specifies: "Input: enriched topics". The plan acknowledges editorial needs enriched data but doesn't specify HOW evidence should inform outline structure. **This discovery fills that gap.**

### `.sisyphus/plans/intelligence-execution.md`
Stage C says "Refactor `generate_editorial.py` to call LLM models via model routing" and "Add editorial quality gates". Neither specifies that claims/evidence should be injected into the prompt. **This is the missing requirement.**

### `.sisyphus/plans/backend-modular-refactor.md`
Focuses on code structure (modules, naming, SLOC). Not relevant to this data flow problem. Already partially executed (daily_blog/ package exists).

## What Needs to Change

### 1. Evidence synthesis step (new)

Before editorial generation, synthesize per-topic evidence into a structured brief:
- Top claims with their `problem_pressure` and `proposed_solution`
- Stance breakdown: how many sources support vs contradict vs are mixed
- Evidence strength: data-backed claims vs anecdotal
- Key tensions/contradictions across claims
- Corroboration clusters: which claims reinforce each other

### 2. Editorial prompt must include evidence brief

`build_editorial_prompt()` must receive and include:
- The synthesized evidence brief (not just URLs)
- Specific claims with their evidence types
- Stance/corroboration data to inform outline sections (e.g., "Counterpoints" section should cite actual contradictions)

### 3. Outline structure should be evidence-driven

Instead of a static 5-section template, the outline should adapt:
- If evidence shows strong consensus: focus on "how to implement"
- If evidence shows contradiction: focus on "analysis of competing approaches"
- If evidence is mostly anecdotal: focus on "what we know vs don't know"

### 4. Enrichment diversity must improve

All 47 enrichment sources are reddit.com. Need:
- Better web discovery (not just Reddit search)
- Domain diversity enforcement in source collection
- Credibility scoring based on actual domain reputation, not uniform "medium"

### 5. Model routing must actually work for content-quality stages

- Extractor and topic lifter are falling back to heuristics (all claims show `model_route_used: None`)
- Gemini is ideal for content synthesis and editorial drafting (per user preference)
- Ollama models (qwen2.5:7b/14b) are good for structured extraction
- Content generation (editorial, narrative) should route to Gemini via OAuth, not CLI

## Model Strategy: OSS + Subscription Balance

Per user requirements: lean on OSS (Ollama) for cost-sensitive batch work, leverage subscriptions (Gemini/Claude) for quality-sensitive content.

| Stage | Recommended Primary | Recommended Fallback | Rationale |
|-------|-------------------|---------------------|-----------|
| Extractor | `ollama:qwen2.5:14b` | `ollama:qwen2.5:7b` | Structured JSON extraction, high volume, cost-sensitive |
| Topic lifter | `ollama:qwen2.5:14b` | `ollama:llama3.1:8b` | Classification task, local is sufficient |
| Topic curator | `ollama:qwen2.5:7b` | `ollama:llama3.1:8b` | Simple normalization, smallest model works |
| Evidence synthesis (NEW) | `gemini` (via OAuth) | `ollama:qwen2.5:14b` | Content understanding, needs large context window |
| Enrichment | `gemini` (via OAuth) | `ollama:qwen2.5:14b` | Web research benefits from Gemini's grounding |
| Editorial/Outline | `gemini` (via OAuth) | `claude` (via OAuth) | Content quality is paramount, Gemini excels here |
| Ranker | deterministic code | deterministic code | No LLM needed |

OAuth integration for Gemini/Claude avoids API key management and leverages existing subscriptions.

## Next Steps

These are scoped to this specific problem (evidence-to-outline disconnect). They do NOT duplicate the existing intelligence-layer or backend-refactor plans.

1. **Add evidence synthesis module** — `daily_blog/editorial/synthesis.py` that aggregates claims + enrichment into a structured brief per topic
2. **Refactor `build_editorial_prompt()`** — accept and include the evidence brief, not just URLs
3. **Add evidence-adaptive outline templates** — outline structure varies based on evidence patterns
4. **Fix enrichment diversity** — improve `discover_web_sources()` to use multiple search strategies
5. **Enable Gemini OAuth routing** — add `gemini` provider to `orchestrator_utils._resolve_cli()` using `gemini` CLI (OAuth-based)
6. **Remove `EDITORIAL_STATIC_ONLY` default** — currently all editorial output is static templates
