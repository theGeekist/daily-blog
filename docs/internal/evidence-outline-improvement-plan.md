# Evidence → Outline Improvement Plan

## Context

Builds on `docs/internal/evidence-to-outline-discovery.md`. Existing intelligence and refactor plans are in `.sisyphus/plans/` — this plan covers only what those plans leave unspecified: the data flow from evidence to outline, model integration mechanics, and enrichment diversity. No duplication.

**Branch target:** `feat/evidence`

---

## Problem Recap (bedrock facts from discovery)

1. All 5 editorial candidates are static boilerplate — `EDITORIAL_STATIC_ONLY=1` is active and the LLM path for editorial was never exercised.
2. The LLM prompt path (`build_editorial_prompt`) receives only topic label + flat URL list. 286 claims with `problem_pressure`, `proposed_solution`, `evidence_type`, `stance` are ignored.
3. `discover_web_sources` scrapes DuckDuckGo HTML via `urllib` — fragile, produces only reddit.com results (47/47 sources from one domain).
4. `orchestrator_utils._run_model_cli` calls Ollama via `subprocess` (`ollama run model prompt`) — bypasses the native Python SDK, no structured output enforcement, no retry logic.
5. Model routing references `gemini-3-pro` and `codex-5.3` as fallbacks but `_resolve_cli` has no resolver for either — they will always fail silently.
6. No Gemini or Claude provider path exists in `orchestrator_utils`.

---

## OSS & Tool Candidates (researched)

### Model Invocation

| Tool | License | Why it fits |
|------|---------|-------------|
| [`ollama` Python SDK](https://github.com/ollama/ollama-python) | MIT | Native `chat()` API with `format=Model.model_json_schema()`. Eliminates subprocess overhead, gives deterministic JSON schema enforcement at the grammar level (v0.5+). No more `ollama run` subprocess. |
| [`instructor`](https://github.com/567-labs/instructor) | MIT | Wraps any LLM provider with Pydantic validation + automatic retry on schema violations. `instructor.from_provider("ollama/qwen2.5:14b")` just works. Handles the most common failure mode (model outputs partial JSON). |
| [`google-generativeai`](https://pypi.org/project/google-generativeai/) | Apache-2.0 | Official Gemini Python SDK. Supports `response_mime_type="application/json"` + `response_schema` for structured output. Uses `GOOGLE_API_KEY` or ADC (`gcloud auth application-default login`). |
| [Gemini CLI headless](https://google-gemini.github.io/gemini-cli/docs/cli/headless.html) | Apache-2.0 | `gemini -p "prompt" --output-format json`. **Known issue**: OAuth cached credentials fail when launched as a Python subprocess ([issue #12042](https://github.com/google-gemini/gemini-cli/issues/12042)). Use `GOOGLE_API_KEY` for subprocess calls, or Vertex AI ADC via `GOOGLE_GENAI_USE_VERTEXAI=true`. |
| [opencode + antigravity-auth](https://github.com/NoeFabris/opencode-antigravity-auth) | MIT | Enables OpenCode to authenticate against Google's Antigravity IDE via OAuth, giving access to Gemini 3 Pro and Claude Opus 4.6 via existing Google subscription. Already integrated in `orchestrator_utils` as `opencode` CLI. |

**Decision:** Replace all `ollama run` subprocess calls with the `ollama` Python SDK. For Gemini, use `google-generativeai` SDK with `GOOGLE_API_KEY` (API key from Google AI Studio — free quota, no billing required, distinct from subscription). For stages where quality matters most (editorial, evidence synthesis), route to Gemini via SDK. Keep opencode/openclaw for Claude fallback since that path already works.

### Enrichment Search

| Tool | License | Why it fits |
|------|---------|-------------|
| [`duckduckgo-search` (DDGS)](https://pypi.org/project/duckduckgo-search/) | MIT | Official Python library for DuckDuckGo. `DDGS().text(query, max_results=10)` returns structured dicts with `href`, `title`, `body`. Replaces the fragile `urllib` HTML scrape in `fetch.py`. No API key. |
| [SearXNG Docker](https://github.com/searxng/searxng-docker) + [`mcp-searxng`](https://github.com/ihor-sokoliuk/mcp-searxng) | AGPL-3.0 | Self-hosted meta-search over 89+ engines (Google, Bing, DDG, Brave, etc.). `docker run -d -p 8888:8080 searxng/searxng` gives a local JSON search API. Resolves domain diversity problem — different engines surface different domains. Free, no rate limits. |
| [Firecrawl](https://github.com/firecrawl/firecrawl) | AGPL-3.0 | Turns any URL into LLM-ready markdown. Self-hostable. Use for URL content extraction (replacing `verify_source_fetch` HEAD requests with actual content fetch for credibility assessment). |

**Decision for MVP:** Add `duckduckgo-search` library as immediate drop-in for `discover_web_sources`. Add SearXNG as optional backend behind an env var (`ENRICH_SEARCH_BACKEND=searxng|ddgs`). Firecrawl deferred — it adds operational complexity; use it only for the evidence synthesis content extraction step.

### Evidence Synthesis

No dedicated OSS library exists for general-domain evidence synthesis. TrialMind and similar tools are biomedical-specific. The right approach for this codebase is:

- **`instructor` + Ollama/Gemini** for structured synthesis (Pydantic model defines the output shape, instructor handles retries)
- **`spaCy`** (MIT) as optional future enhancement for entity extraction across claims, but not required for MVP

---

## Implementation Plan

### Phase 1: Fix model invocation layer (`orchestrator_utils.py`)

**Goal:** Replace `subprocess` CLI calls with native SDK calls. Add Gemini provider. Fix broken fallback routing.

**Changes to `orchestrator_utils.py`:**

Replace `_resolve_cli` + `_run_model_cli` with a provider dispatch table:

```python
# Provider registry: maps prefix → callable
def _dispatch_ollama(model_id: str, prompt: str, schema: dict | None) -> str:
    from ollama import chat
    kwargs: dict = {"model": model_id, "messages": [{"role": "user", "content": prompt}]}
    if schema:
        kwargs["format"] = schema  # native grammar-constrained JSON
    resp = chat(**kwargs)
    return resp.message.content

def _dispatch_gemini(model_id: str, prompt: str, schema: dict | None) -> str:
    import google.generativeai as genai
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_id)
    config = {}
    if schema:
        config = {"response_mime_type": "application/json", "response_schema": schema}
    resp = model.generate_content(prompt, generation_config=config)
    return resp.text

def _dispatch_opencode(model_id: str, prompt: str, schema: dict | None) -> str:
    # existing subprocess path — kept as fallback for Claude
    ...
```

Routing key format in `model-routing.json`:
- `ollama:qwen2.5:14b` → `_dispatch_ollama("qwen2.5:14b", ...)`
- `gemini:gemini-2.0-flash` → `_dispatch_gemini("gemini-2.0-flash", ...)`
- `gemini:gemini-2.5-pro` → `_dispatch_gemini("gemini-2.5-pro", ...)`
- `opencode:claude-opus-4-6` → `_dispatch_opencode(...)` (existing path)

Add `instructor` wrapping at the `call_model` level for retry on schema validation failure (max 2 retries):

```python
import instructor
# wrap ollama client: instructor.from_provider("ollama/qwen2.5:14b")
# wrap genai client: instructor.from_provider("google/gemini-2.0-flash")
```

**New `config/model-routing.json`:**

```json
{
  "extractor": {
    "primary": "ollama:qwen2.5:14b",
    "fallback": "ollama:qwen2.5:7b"
  },
  "topic_lifter": {
    "primary": "ollama:qwen2.5:14b",
    "fallback": "ollama:llama3.1:8b"
  },
  "topic_curator": {
    "primary": "ollama:qwen2.5:7b",
    "fallback": "ollama:llama3.1:8b"
  },
  "evidence_synthesis": {
    "primary": "gemini:gemini-2.0-flash",
    "fallback": "ollama:qwen2.5:14b"
  },
  "enrichment": {
    "primary": "ollama:qwen2.5:14b",
    "fallback": "ollama:llama3.1:8b"
  },
  "editorial": {
    "primary": "gemini:gemini-2.0-flash",
    "fallback": "opencode:claude-opus-4-6"
  },
  "ranker": {
    "primary": "deterministic-code",
    "fallback": "deterministic-code"
  }
}
```

Rationale: Ollama handles all batch extraction (high volume, cost-zero locally). Gemini handles evidence synthesis and editorial (quality-sensitive, generous free quota via `GOOGLE_API_KEY` from AI Studio). Claude via opencode as paid fallback only.

**Dependencies to add:**
```
ollama>=0.4.0
google-generativeai>=0.8.0
instructor>=1.7.0
```

**Files changed:** `orchestrator_utils.py`, `config/model-routing.json`, `requirements.txt` (or `pyproject.toml`)

---

### Phase 2: Fix enrichment diversity (`enrich_topics.py` + `daily_blog/enrichment/fetch.py`)

**Goal:** Replace fragile DDG HTML scrape with DDGS library. Add SearXNG optional backend. Enforce domain diversity.

**`daily_blog/enrichment/fetch.py` changes:**

Replace `discover_web_sources` with library-backed implementation:

```python
def discover_web_sources(topic_label: str, query_terms: list[str], limit: int = 12) -> list[str]:
    backend = os.getenv("ENRICH_SEARCH_BACKEND", "ddgs")  # "ddgs" | "searxng"
    query = " ".join([topic_label] + query_terms[:6]).strip()
    if not query:
        return []
    if backend == "searxng":
        return _discover_searxng(query, limit)
    return _discover_ddgs(query, limit)

def _discover_ddgs(query: str, limit: int) -> list[str]:
    from duckduckgo_search import DDGS
    results = DDGS().text(query, max_results=limit)
    return [r["href"] for r in results if r.get("href")]

def _discover_searxng(query: str, limit: int) -> list[str]:
    base = os.getenv("SEARXNG_BASE_URL", "http://localhost:8888")
    params = urllib.parse.urlencode({"q": query, "format": "json", "engines": "google,bing,ddg,brave"})
    url = f"{base}/search?{params}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())
    return [r["url"] for r in data.get("results", [])[:limit] if r.get("url")]
```

Add domain diversity enforcement in `filter_sources_for_quality` in `daily_blog/enrichment/helpers.py`:
- Require at least `min_domain_diversity` (default 3) distinct domains after filtering
- If a single domain has >50% of sources, cap it at `max_per_domain` (default 3)

**Dependencies to add:** `duckduckgo-search>=6.0`

**Optional SearXNG setup** (documented in `ops/runbook.md`, not required for MVP):
```bash
docker run -d --name searxng -p 8888:8080 \
  -v "$HOME/.config/searxng:/etc/searxng" \
  --restart unless-stopped searxng/searxng:latest
```

**Files changed:** `daily_blog/enrichment/fetch.py`, `daily_blog/enrichment/helpers.py`, `enrich_topics.py`

---

### Phase 3: Add evidence synthesis stage (new)

**Goal:** Before editorial generation, synthesize per-topic claims + enrichment into a structured brief that informs outline structure.

**New file: `daily_blog/editorial/synthesis.py`**

```python
from pydantic import BaseModel

class EvidenceBrief(BaseModel):
    topic_id: str
    claim_count: int
    top_claims: list[str]           # top 5 claims by evidence_type priority (data > link > anecdote)
    problem_pressures: list[str]    # distinct problem_pressure values
    proposed_solutions: list[str]   # distinct proposed_solution values
    evidence_type_counts: dict[str, int]   # {"data": 3, "link": 12, "anecdote": 5}
    stance_breakdown: dict[str, int]       # {"supports": 8, "contradicts": 2, "neutral": 7}
    dominant_pattern: str           # "consensus" | "contested" | "anecdotal" | "data-backed"
    outline_strategy: str           # "implementation-guide" | "analysis" | "explainer" | "caution"

def synthesize_evidence(topic_id: str, claims: list[dict], sources: list[dict]) -> EvidenceBrief:
    ...
```

`dominant_pattern` and `outline_strategy` are derived deterministically from the data (no LLM needed for this step):
- data_count > 50% of claims → `data-backed` → `outline_strategy = "implementation-guide"`
- contradicts_count > 20% of sources → `contested` → `outline_strategy = "analysis"`
- anecdote_count > 70% of claims → `anecdotal` → `outline_strategy = "caution"`
- else → `consensus` → `outline_strategy = "explainer"`

**Update `daily_blog/editorial/model_io.py` — `build_editorial_prompt`:**

Include the evidence brief in the prompt:

```python
def build_editorial_prompt(
    topic_label: str,
    why_it_matters: str,
    time_horizon: str,
    validated_sources: list[dict],
    evidence_brief: EvidenceBrief,        # NEW
) -> str:
    ...
    # Inject: dominant_pattern, outline_strategy, top_claims,
    # problem_pressures, proposed_solutions, stance_breakdown
    # The LLM adapts the outline structure to match the evidence pattern.
```

The prompt instructs the model:
- If `outline_strategy == "analysis"`: include a "Competing Views" section citing specific contradicting sources
- If `outline_strategy == "implementation-guide"`: include a "Step-by-Step" section with claims as evidence anchors
- If `outline_strategy == "caution"`: lead with caveats and evidence gaps

**Update `generate_editorial.py`:**
- Call `synthesize_evidence()` per topic before the editorial LLM call
- Pass `evidence_brief` to `build_editorial_prompt`
- Remove `EDITORIAL_STATIC_ONLY` default — set it to `0` once phases 1 and 2 are stable

**New DB column:** `editorial_candidates.evidence_brief_json TEXT` (stores the serialized brief for debugging and UI)

**Files changed:** `daily_blog/editorial/synthesis.py` (new), `daily_blog/editorial/model_io.py`, `generate_editorial.py`, `daily_blog/editorial/store.py`

---

### Phase 4: Adaptive outline templates

**Goal:** Replace the single static template with evidence-strategy-driven templates.

**Update `daily_blog/editorial/templates.py`:**

```python
STRATEGY_TEMPLATES: dict[str, Callable[[str, str], str]] = {
    "implementation-guide": _outline_implementation_guide,
    "analysis": _outline_analysis,
    "explainer": _outline_explainer,
    "caution": _outline_caution,
}

def static_editorial_package(label: str, why: str, strategy: str = "explainer") -> dict:
    outline_fn = STRATEGY_TEMPLATES.get(strategy, _outline_explainer)
    ...
```

Each template has a distinct structure. The `analysis` template adds a "Competing Evidence" section. The `implementation-guide` template leads with a "What Changed" section and ends with an "Action Checklist". The `caution` template leads with "What We Don't Know Yet".

**Files changed:** `daily_blog/editorial/templates.py`, `generate_editorial.py`

---

## Dependency Summary

```
# New additions (add to requirements.txt / pyproject.toml)
ollama>=0.4.0                  # Phase 1: Ollama native SDK
google-generativeai>=0.8.0     # Phase 1: Gemini SDK (GOOGLE_API_KEY from AI Studio)
instructor>=1.7.0              # Phase 1: Pydantic retry/validation wrapper
duckduckgo-search>=6.0         # Phase 2: DDGS library for enrichment
pydantic>=2.0                  # Phase 3: Already likely present, ensure v2
```

No new infra required for MVP. SearXNG Docker is optional and documented as an ops enhancement.

---

## Environment Variables

```bash
# Phase 1 — Gemini
GOOGLE_API_KEY=...             # From https://aistudio.google.com/app/apikey (free quota)
                               # Alternatively: gcloud auth application-default login
                               #   + GOOGLE_GENAI_USE_VERTEXAI=true (uses your GCP subscription)

# Phase 2 — Enrichment
ENRICH_SEARCH_BACKEND=ddgs     # "ddgs" (default) or "searxng"
SEARXNG_BASE_URL=http://localhost:8888   # if using searxng backend

# Phase 3 — Evidence synthesis
EDITORIAL_STATIC_ONLY=0        # Set to 0 once phases 1+2 verified stable
```

---

## Known Constraints & Risks

| Constraint | Detail | Mitigation |
|-----------|--------|-----------|
| Gemini CLI subprocess OAuth | When `gemini` CLI is launched as Python subprocess, cached OAuth credentials are not picked up ([issue #12042](https://github.com/google-gemini/gemini-cli/issues/12042)). | Use `google-generativeai` SDK directly instead of CLI subprocess. `GOOGLE_API_KEY` avoids this entirely. |
| Ollama SDK vs CLI | Native SDK requires `ollama` server running locally on port 11434. The current subprocess path can fall back to any path-resolvable binary. | Check `ollama serve` health at startup; gracefully fall back to subprocess if SDK import fails. |
| Gemini free quota | AI Studio free tier: 1500 requests/day for Flash, 50/day for Pro. Pipeline processes 5 topics currently. Well within limits. | Monitor via `run_metrics`. Add rate-limit error handling in `_dispatch_gemini`. |
| instructor retry cost | Each retry adds latency. Caps at 2 retries. | Set `max_retries=2` in instructor client. Log retry events to `run_metrics`. |
| SearXNG diversity | More engines = more diverse results but slower. | Default to DDGs (fast, free). SearXNG is opt-in via env var. |

---

## Acceptance Criteria

- [ ] `orchestrator_utils._run_model_cli` replaced with provider dispatch; no `subprocess` call for `ollama:` routes
- [ ] `gemini:` routes resolve via `google-generativeai` SDK
- [ ] `discover_web_sources` uses `DDGS` library; domain diversity in enrichment ≥ 3 distinct domains for AI topic
- [ ] `synthesize_evidence()` produces `EvidenceBrief` for all 5 current topics
- [ ] `build_editorial_prompt` includes evidence brief fields (top claims, pattern, strategy)
- [ ] At least one editorial candidate uses LLM-generated outline (not static template)
- [ ] `outline_markdown` for `ai` topic is different in structure from `business` topic
- [ ] All existing tests still pass: `python3 -m unittest discover -s tests`

---

## Phasing & Dependencies

```
Phase 1 (model layer)
  └── unblocks Phase 2 (enrichment can now use Gemini for source suggestions)
        └── unblocks Phase 3 (synthesis needs diverse sources to be meaningful)
              └── unblocks Phase 4 (adaptive templates need synthesis output)
```

Phase 1 is the critical path. Phases 2–4 can proceed in parallel after Phase 1 is stable.

---

## Relation to Existing Plans

| Existing Plan | Overlap | How this plan differs |
|---|---|---|
| `.sisyphus/plans/intelligence-layer.md` | Defines stage 5 (Editor) needs "enriched topics" as input | Does not specify what data from enrichment enters the prompt, or how to adapt outline structure. This plan specifies exactly that. |
| `.sisyphus/plans/intelligence-execution.md` | Stage C: "Refactor generate_editorial.py to call LLM models via model routing" | Does not specify which SDK to use, how to pass claims data, or that a synthesis step is needed. This plan specifies all three. |
| `.sisyphus/plans/backend-modular-refactor.md` | Package structure, naming conventions, SLOC limits | Fully orthogonal. New modules in this plan follow the same naming conventions (`synthesis.py`, `_service.py` suffix for orchestration). |
