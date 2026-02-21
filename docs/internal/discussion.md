Yeah — your instinct is basically the “secret”: once you turn fuzzy goals into **structured artefacts with clear contracts**, orchestration suddenly stops being mystical and starts behaving like software.

What makes multi-agent systems *actually* work isn’t “more intelligence”, it’s:

* **tight I/O schemas** (inputs/outputs that are machine-checkable),
* **small context windows per role** (each agent sees only what it needs),
* **deterministic fallbacks** (when the model waffles, the system still progresses).

Tool-calling runtimes have matured enough that this is now practical even locally (Ollama + tool calling, llama.cpp templates/grammar, etc.). ([Ollama][1])

---

## Your pipeline is solid — here’s the real shape of it

What you described is a clean 5-stage funnel:

### 1) Harvest

**Reddit**: API is straightforward (OAuth + rate-limits), and predictable compared to X. (The “pricing controversy” era is real, and it’s still a factor, but for sane daily headline-level pulls it’s usually workable.) ([Zuplo][2])

**X/Twitter**: browser automation/scraping is the fragile bit. People do it, but you’re signing up for constant breakage (tokens, GraphQL IDs, rate limits, UI changes). ([Scrapfly][3])
If you go this route, the community tends to use libraries that emulate the internal web API with authenticated sessions (example: `twscrape`). ([GitHub][4])

### 2) Normalise into “claims”

Turn posts into a canonical object like:

* `headline`
* `who_cares` (audience)
* `problem/pressure`
* `proposed_solution`
* `evidence_type` (anecdote/data/link)
* `sources[]` (URLs, post IDs)

This is where “structured tasks” pays off: you’re not summarising, you’re **extracting primitives** that downstream steps can recombine.

### 3) Topic lifting (your “zoom out 1–2 layers”)

You want two levels:

* **Leaf**: the concrete thing being argued (“X library broke my build because …”)
* **Parent**: the durable topic (“dependency management failure modes in JS monorepos”)

This is a classification + clustering problem, but you can make it deterministic-ish by enforcing outputs:

* `parent_topic_slug`
* `parent_topic_label`
* `why_it_matters`
* `time_horizon` (flash / seasonal / evergreen)

### 4) Web expansion (related material)

This stage is where tool-calling agents shine: “given parent topic + 5–15 extracted claims, find reputable supporting sources, counterpoints, and canonical references”.

Key trick: make the agent return *only*:

* `query_terms[]`
* `candidate_sources[]` with `domain`, `url`, `stance`, `credibility_guess`
  Then your fetcher/validator tool does the real retrieval.

### 5) Editorial synthesis + scoring

You generate:

* title options
* outline skeletons
* talking points

Then score them with metrics that are *mostly not LLM judgement*.

---

## The scoring model that tends to behave (without becoming astrology)

A simple but effective composite:

### Value signals (evergreen + usefulness)

* **Evergreen score**: does it survive 6–12 months?
* **Problem intensity**: number of distinct “pain” claims across sources
* **Actionability**: can you give steps, code, templates, checklists?

### Uniqueness signals

* **Novelty delta**: “is this just the 500th take?”
* **Angle uniqueness**: you have a voice (systems architect + sales brain + writer). Use that as a differentiator.

### Reach signals (distribution reality)

* **Audience size proxy**: subreddit size + comment velocity + cross-posting
* **Cross-source corroboration**: same parent topic appears across multiple subs / platforms

### Production cost signals

* **Research cost**: number of primary sources needed
* **Media cost**: screenshots, diagrams, code samples, charts
* **Risk cost**: policy/defamation/legal sensitivity

When a candidate scores high on value + uniqueness + reach *and* low-ish on cost, it becomes an obvious pick.

---

## Where this usually fails (and how to make it not fail)

### 1) “Parent topic” becomes mushy

Fix: enforce **topic constraints**:

* must be describable as “How/Why/When X fails/works”
* must be explainable to a specific persona (e.g. “mid-level React dev shipping a PWA”)
* must have 3–5 subquestions (“causes”, “symptoms”, “fixes”, “trade-offs”, “tools”)

### 2) Agents hallucinate sources

Fix: LLMs propose candidates; **only tools fetch**. No tool result, no citation.

### 3) Twitter scraping eats your life

Fix: either accept maintenance as a cost (and isolate it behind one component), or downrank X as a signal source and treat it as “nice-to-have”. The ecosystem for scraping X changes constantly. ([Scrapfly][3])

### 4) Context bloat

Fix: each stage emits **small structured artefacts**. Subagents only receive:

* the artefact they need
* the minimum source snippets relevant to their step

This lines up with how local agent setups are evolving: smaller contexts, tighter tool interfaces. ([Ollama][1])

---

## A clean “agent roster” for this

You don’t need many, you need *separable responsibilities*:

1. **Collector**: pulls raw items (API/browser), dedupes, stores.
2. **Extractor**: turns each item into a “claim object”.
3. **Topic-lifter**: clusters claims into parent topics.
4. **Researcher**: proposes queries + candidate sources; tool fetch validates.
5. **Editor**: produces outlines + titles + angle options per parent topic.
6. **Ranker**: applies scoring function (mostly deterministic, with one LLM assist field at most).

Local OSS models are great for roles 2–5 if outputs are constrained; role 6 should lean deterministic.

[1]: https://docs.ollama.com/capabilities/tool-calling?utm_source=chatgpt.com "Tool calling"
[2]: https://zuplo.com/learning-center/reddit-api-guide?utm_source=chatgpt.com "Dive Into The Reddit API: Full Guide and Controversy"
[3]: https://scrapfly.io/blog/posts/how-to-scrape-twitter?utm_source=chatgpt.com "How to Scrape X.com (Twitter) in 2026"
[4]: https://github.com/vladkens/twscrape?utm_source=chatgpt.com "vladkens/twscrape"
