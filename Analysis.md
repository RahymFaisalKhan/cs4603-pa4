# CS4603 PA4 — Document Analyst

## Setup

```bash
uv sync --extra dev
cp .env.example .env
```

Set the Databricks host/token, serving LLM, Unity Catalog names, Vector Search endpoint/index,
source table, serving endpoint, and secret scope in `.env`. Never commit `.env`.

## Running locally

1. Upload `data/annual_report.pdf` to a Unity Catalog volume, for example
   `/Volumes/main/default/pa4/annual_report.pdf`.
2. In a Databricks notebook attached to a runtime that supports `ai_parse_document` and
   `ai_prep_search`, run:

   ```python
   from rag.ingest import ingest
   ingest(spark, "/Volumes/main/default/pa4/annual_report.pdf")
   ```

   This writes `SOURCE_TABLE`, enables Change Data Feed, creates or synchronizes the
   configured triggered Delta Sync index, and waits for it to become ready.
3. Run `pa4.ipynb` from the project root for retrieval-only, calculation-only, and combined
   examples. The graph uses the same managed index locally and after deployment.
4. Run the offline check with `uv run pytest -q`. It injects fake LLM, retriever, and tool
   dependencies, invokes a combined query, and verifies both specialist paths.

## Deployment

Create `SECRET_SCOPE` and store `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, and
`DATABRICKS_MODEL` in it. Then run:

```bash
uv run python deployment/deploy.py
databricks serving-endpoints get pa4-document-analyst
```

The script logs a models-from-code LangGraph model with all local packages in `code_paths`,
registers it in Unity Catalog, and creates or updates `SERVING_ENDPOINT_NAME`. Credentials are
secret references; Vector Search identifiers are ordinary environment variables. The final
workspace-specific model version, URL, responses, and latency measurements should be captured
by executing `pa4.ipynb` before submission.

## Design decisions

The graph plans before execution and routes each atomic step through a supervisor. Retrieval
and deterministic computation are isolated so prompts, failures, and evaluation can be tuned
independently. Both specialists return to the supervisor, which routes to synthesis only after
all steps finish. Dependencies can be injected, making graph behavior testable without cloud
services. Production construction instead uses the configured Databricks LLM, managed Vector
Search retriever, and MCP tools.

## Analysis Questions

### Task 1.2 — Planner

1. Dependent steps are ordered in `plan`. Each specialist appends its output to
   `step_results`; the MCP node receives all earlier results in its prompt, so a later growth
   calculation can use a revenue retrieved earlier. A weakness is that dependencies are text,
   not typed references, so ambiguous units or several similar values can still cause errors.
2. Replanning can recover when retrieval returns “not found” or an unexpected unit, but it adds
   LLM calls, latency, cost, and the possibility of plan drift. For this short, fixed report,
   executing a 2–5 step plan is usually preferable. Replanning would help if “find operating
   margin” failed and the system needed separate operating-income and revenue retrieval steps.

### Task 1.3 — Supervisor

1. Misrouting a lookup to MCP produces a missing or invented tool input; misrouting arithmetic
   to RAG usually produces “not found.” Detect it through route traces, tool-call validation,
   empty retrieval, and result-type checks. Recovery could retry once with the other specialist
   or ask an LLM validator to reclassify the failed step.
2. A ReAct agent is simpler for open-ended tasks with few tools. The supervisor is worthwhile
   when workflows repeatedly mix retrieval and calculations: routing is observable, prompts are
   narrower, deterministic math is enforced, and each specialist can be evaluated separately.

### Task 1.4 — RAG Agent

1. Retrieving for an atomic step removes unrelated clauses and often improves embedding
   similarity—for example, revenue retrieval is not diluted by CAGR wording. It can lose useful
   context, such as company, year, or units, if the planner makes the step too terse.
2. Rewrite the step with entities and constraints from the original question and earlier
   results: “Meridian Motor Corporation FY2023 consolidated net revenue, Japanese yen.” Query
   expansion, metadata filters, and hybrid/reranked retrieval are additional improvements.

### Task 2.1 — Model Definition

1. Models-from-code reconstructs the model in a clean serving container. Laptop-only modules,
   files, processes, or databases are absent there, producing import or connection failures.
   The definition and `code_paths` therefore contain all code, while external dependencies use
   stable service endpoints and environment configuration.
2. An external index stays fresh and keeps the artifact and cold start small, but adds network
   latency, authentication, quotas, and another availability dependency. A baked corpus is
   fast and self-contained but increases artifact size/cold start and requires a new model
   version whenever documents change.

### Task 2.3 — Serving Endpoint

1. Authentication for calling the endpoint is distinct from credentials used by code inside
   its container. The running graph must make outbound calls to the serving LLM and Vector
   Search, so it needs explicit credentials or a supported service identity.
2. Databricks provisions the new served entity and transitions traffic after it becomes ready;
   existing requests continue on the old replica while new requests move according to the
   endpoint configuration. Readiness waiting prevents routing traffic to an uninitialized
   version, although clients should still retry transient 503 responses.

### Task 3.2 — Client

1. Exponential backoff reduces synchronized retry storms and gives a scaling or rate-limited
   endpoint progressively more recovery time. Fixed retries can repeatedly hit the same busy
   interval.
2. Excessive retries multiply traffic, cost, queueing, and user-visible latency during an
   outage. Across many users they can prevent recovery. Production clients should cap attempts
   and total elapsed time, and normally add jitter/circuit breaking.
3. Streaming is useful when perceived latency matters, such as showing the first sentences of
   a long financial explanation in a chat UI. `ask()` is simpler for scripts that need one
   complete value before continuing. This endpoint may legitimately return one full chunk.

### Bonus A / B / C

Bonus A runs lint and the offline test before deployment, deploys only from `main`, and supports
manual dispatch. Feature branches should not mutate production. A production gate would compare
candidate answers on a versioned evaluation set against the current endpoint and reject a model
whose groundedness, numerical accuracy, latency, or safety falls below thresholds.

Bonus B replaces manual endpoint provisioning with `agents.deploy()`, gaining automatic endpoint
and Review App setup but giving up some low-level endpoint configuration control. Human ratings
should be joined with traces, categorized by retrieval/routing/calculation failure, added to an
evaluation set, used to improve prompts or retrieval, and required to pass an offline gate.

Bonus C decouples tool scaling, release cadence, access policy, and monitoring, but introduces
network latency, authentication, and service-availability failures. Protect it with Databricks
app authentication, least-privilege service identities, private networking where available, and
authorization checks. Bundling is preferable for a small stable toolset and atomic deployment;
a remote service is worthwhile when many agents share tools or tools need independent scaling.
