# Extra-Credit 1 · PART 4

## Bonus Challenges — Observability & Governance in Production

> Part of **CS 4603 Extra-Credit Assignment 1**.
> ← Prev: [Part 3 — Agent Evaluation](part-3-agent-evaluation.md) · [Overview](../README.md)

---

### Why this part exists

Parts 1–3 get your agent **built, routed, and measured offline**. Part 4 is about what happens **after it is serving real traffic**: can you *see* what it did, and can you *stop* it from doing something harmful? These are the two pillars the industry calls **observability** and **governance** — and they are exactly the topics the Databricks GenAI Engineer exam groups under *"Evaluation & Monitoring"* and *"Governance."*

Everything here is **optional** and additive — each challenge stands alone, builds on the endpoint you already deployed, and is meant to deepen understanding rather than add busywork. Pick the ones that interest you.

| Challenge | Pillar | Core Databricks feature |
|-----------|--------|-------------------------|
| **D — Tracing & Monitoring** | Observability | MLflow Tracing · inference tables · Agent Monitoring |
| **E — Guardrails via AI Gateway** | Governance / Safety | Mosaic AI Gateway (rate limits, safety, PII) |
| **F — Prompt Lifecycle** *(stretch)* | LLMOps / CI-CD | MLflow Prompt Registry + aliases |

---

## Background tutorial: observability vs. governance

Before the challenges, a short primer on the two ideas and where each Databricks feature fits. You already know MLflow *experiments/runs* from PA1–PA4; these are the runtime cousins.

### 1. Observability — "what did my agent actually do?"

When an agent answers a question, a lot happens that a single output string hides: which node ran (RAG? Genie? a tool?), what the retriever returned, how many tokens each LLM call burned, and how long each step took. **Observability** is making all of that visible.

- **MLflow Tracing** captures a **trace** = an ordered tree of **spans** (one span per step: retriever call, tool call, LLM call). With LangChain, one line — `mlflow.langchain.autolog()` — auto-instruments your graph so every invocation produces a trace you can open in the MLflow UI and expand step by step. This is the *dev-time* microscope.

- **Inference tables** are the *production* version: when enabled on a Model Serving endpoint, Databricks **logs every request and response to a Delta table** automatically. Because it is just a Delta table in Unity Catalog, you query it with plain SQL — latency percentiles, token usage, error rates, traffic over time.

- **Agent / production monitoring** layers scheduled **quality** checks on top of that logged traffic (e.g. run the Part 3 judges on a sample of live requests), so quality is tracked continuously, not just once at eval time.

> Mental model: **Tracing** = a debugger for one request. **Inference tables** = a flight recorder for all requests. **Monitoring** = alarms wired to the flight recorder.

### 2. Governance — "what should my agent be allowed to do?"

An agent on the open internet will eventually receive abusive prompts, prompt-injection attempts, or requests that would make it leak PII or run up a huge bill. **Governance** is the guardrails that constrain behaviour *regardless of what the agent code does*.

- **Mosaic AI Gateway** sits **in front of** a serving endpoint as a policy layer. Without changing agent code you can attach:
  - **Rate limits** (requests per user/endpoint per minute) — cost and abuse control.
  - **Safety guardrails** — block unsafe/toxic content.
  - **PII detection/masking** — block or redact personal data in prompts/responses.
  - **Usage tracking** — a system table of who called what, how much.

- **Why a gateway instead of `if` statements in your agent?** A gateway policy is **centralized, auditable, and uniform** across every consumer of the endpoint; it can't be bypassed by a bug in one code path, and it's owned by the platform/governance team rather than buried in application logic. That separation of concerns is the whole point.

> Mental model: agent code decides *how to answer*; the gateway decides *what is allowed through the door* — in both directions.

---

## Challenge D: Tracing & Monitoring

**Goal:** make one live query fully observable, then query production traffic in aggregate.

**Steps**
1. **Trace a single query.** Enable tracing and invoke your multi-agent graph on one question that exercises routing:
   ```python
   # Expected pattern:
   import mlflow
   mlflow.langchain.autolog()          # auto-instrument the LangChain/LangGraph app

   with mlflow.start_run(run_name="trace-demo"):
       result = app.invoke({"messages": [("user", "Rank Meridian's FY2023 segments by revenue.")]})
   # open the run in the MLflow UI and expand the trace
   ```
   In your notebook, show the **trace tree** and point out **which node handled the query** (RAG vs Genie vs UC tools) and the span timings.

2. **Log production traffic.** Enable the **inference table** on your served endpoint (Serving UI → endpoint → *Inference tables*, or set it when deploying). Send a handful of requests so rows accumulate.

3. **Query the table.** Write **one** SQL query over the inference table, e.g.:
   ```sql
   -- Expected pattern (name is <catalog>.<schema>.<endpoint>_payload):
   SELECT date_trunc('minute', request_time) AS minute,
          count(*)                            AS n_requests,
          avg(execution_time_ms)              AS avg_latency_ms
   FROM main.default.doc_analyst_payload
   GROUP BY 1 ORDER BY 1;
   ```

**Deliverables:** the trace screenshot (with the winning node identified), the SQL + its result, and a short note: *what one metric would you alert on in production, at what threshold, and why?*

---

## Challenge E: Guardrails via AI Gateway

**Goal:** enforce a safety/cost boundary on your endpoint **without touching agent code**, and observe it firing.

> **Heads-up on Databricks Free Edition.** AI Gateway on the free tier is limited: only *basic* guardrails and rate limits are exposed, some safety/PII policies and higher limits are reserved for paid tiers, and availability varies by region/workspace and changes over time. You also need a **deployed serving endpoint** to attach a policy to, which can itself be quota-limited on Free Edition. If you can configure and trip a real gateway policy — great, do the steps below. **If the gateway is unavailable to you, use the code-level fallback instead** (see "If AI Gateway isn't available"); the learning goal — *understanding where a guardrail belongs* — is the same either way. Either path is a complete answer to this challenge; just state which one you took and why.

**Steps (AI Gateway path)**
1. **Attach a Gateway policy** to your serving endpoint (Serving UI → endpoint → *AI Gateway*, or via the SDK). Configure **both**:
   - a **rate limit** (e.g. a low per-user requests-per-minute so you can trip it), **and**
   - one **safety or PII guardrail** (block unsafe content, or detect/mask PII).
   ```python
   # Expected pattern (SDK sketch — consult current AI Gateway docs for exact fields):
   from databricks.sdk import WorkspaceClient
   w = WorkspaceClient()
   w.serving_endpoints.put_ai_gateway(
       name="doc-analyst-endpoint",
       rate_limits=[{"calls": 2, "renewal_period": "minute", "key": "user"}],
       guardrails={"input": {"pii": {"behavior": "BLOCK"}, "safety": True}},
   )
   ```
2. **Trip each guardrail.** Send enough requests to hit the rate limit (capture the throttled/`429` response), and send one request containing obvious PII or unsafe content and capture the **blocked** response.
3. **Check usage tracking.** If enabled, query the **usage table** to show the calls were recorded.

**If AI Gateway isn't available (code-level fallback)**

Implement the *same two guardrails inside your agent* and demonstrate them firing locally — then compare the two approaches in your write-up.

```python
# Expected pattern — guardrails as a pre-processing step in the graph:
import re, time
from collections import defaultdict

_PII = re.compile(r"\b(\d{13}|\d{3}-\d{2}-\d{4}|[\w.+-]+@[\w-]+\.[\w.]+)\b")  # CNIC/SSN/email
_calls = defaultdict(list)  # user_id -> recent request timestamps

def guard(user_id: str, prompt: str, max_per_min: int = 2) -> str | None:
    """Return a rejection reason, or None if the request may proceed."""
    now = time.time()
    _calls[user_id] = [t for t in _calls[user_id] if now - t < 60]
    if len(_calls[user_id]) >= max_per_min:
        return "rate_limited"
    if _PII.search(prompt):
        return "pii_blocked"
    _calls[user_id].append(now)
    return None
# call guard(...) at the top of the graph; short-circuit to a safe message if it returns a reason.
```

Demonstrate **both** a rate-limited request and a PII-blocked request being stopped.

**Deliverables:** evidence of each guardrail firing (gateway responses **or** the fallback short-circuiting), and a short analysis: *why is the gateway the better home for these controls in production — and what can a gateway guardrail protect against that in-agent code cannot (and vice-versa)?*

---

## Challenge F: Prompt Lifecycle *(stretch)*

**Goal:** stop treating prompts as hard-coded strings and start **versioning** them like model artifacts — the governance twin of Part 1's UC Functions.

**Background.** Your agent's prompts (`PLANNER_PROMPT`, `SUPERVISOR_PROMPT`, `SYNTHESIZER_PROMPT`, and the rest) already live in one place — `agent/prompts.py` — which is better than scattering them across nodes, but they are still **plain Python constants baked into your code**. That means a prompt can't be versioned, reviewed, or rolled back independently: changing one requires editing source and **redeploying** the whole agent, and there is no record of which prompt version produced which result. The **MLflow Prompt Registry** stores each prompt as a **named, versioned asset**; **aliases** (`dev`, `staging`, `production`) are movable pointers to a specific version. Your app loads a prompt **by alias**, so promoting a new prompt to production — or rolling back — is just *moving an alias*, with **no redeploy and no code change**. This is the same "promote across environments via a pointer" pattern used for models, and it is explicitly on the exam.

**Steps**
1. **Register** your synthesizer (or supervisor) prompt and set an alias:
   ```python
   # Expected pattern:
   import mlflow
   p1 = mlflow.genai.register_prompt(
       name="doc_analyst_synthesizer",
       template="Answer using ONLY the provided context...\n\nContext:\n{{context}}\n\nQuestion: {{question}}",
       commit_message="v1 baseline",
   )
   mlflow.genai.set_prompt_alias("doc_analyst_synthesizer", alias="production", version=p1.version)
   ```
2. **Load by alias** in your agent instead of the constant in `agent/prompts.py`:
   ```python
   prompt = mlflow.genai.load_prompt("prompts:/doc_analyst_synthesizer@production")
   ```
3. **Iterate & promote.** Register a **v2** (e.g. the fix you found in Part 3), evaluate both with your Part 3 harness, then **move the `production` alias** to whichever version scored better. Show that the running app picks up the change **without redeploying**.

**Deliverables:** the two registered versions, a before/after eval comparison (reuse Part 3), and a short note: *how does alias-based promotion make a rollback safe and instant?*

---

## What to submit for Part 4

For each challenge you attempt, include in `extra_credit.ipynb` (outputs visible) and answer its analysis question in `writeup.md`. State clearly which challenges you attempted — any subset is fine.

---

## Reference Map (Part 4)

| Topic | Docs |
|-------|------|
| MLflow Tracing | *MLflow Tracing*, `mlflow.langchain.autolog()` |
| Inference tables | *Inference tables for Model Serving* |
| Production/agent monitoring | *Agent / production monitoring* |
| AI Gateway guardrails | *Mosaic AI Gateway* (rate limits, safety, PII, usage tracking) |
| Prompt Registry & aliases | *MLflow Prompt Registry*, `mlflow.genai.register_prompt` / `set_prompt_alias` / `load_prompt` |

---

← Prev: [Part 3 — Agent Evaluation](part-3-agent-evaluation.md) · [Overview](../README.md)
