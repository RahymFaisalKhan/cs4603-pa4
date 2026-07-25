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
4. Run the offline check with `uv run pytest -q`. Its six tests cover graph execution, both
   specialist paths, MCP stdio behavior, the owner-attributable net-income definition, client
   response parsing, and exponential-backoff recovery.

## Deployment

Create `SECRET_SCOPE` and store `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, and
`DATABRICKS_MODEL` in it. Then run:

```bash
uv run python deployment/deploy.py
databricks serving-endpoints get pa4-document-analyst
```

The script logs a models-from-code LangGraph model with all local packages in `code_paths`,
registers it in Unity Catalog, and creates or updates `SERVING_ENDPOINT_NAME`. Credentials are
secret references; Vector Search identifiers are ordinary environment variables. The deployed
manual endpoint `pa4-document-analyst` is `READY`, serves
`cs4603.pa4.pa4_document_analyst` version 19, and routes 100% of traffic to that version.

The executed `pa4.ipynb` contains an HTTP 200 response and the three required deployed queries.
It reports FY2023 owner-attributable net income of ¥1,107 billion, 15% of 2.4 billion as
360 million, and FY2023 revenue of ¥16,910 billion increasing to ¥18,601 billion after 10%.
It also records a verified scaled-to-zero cold start of 43.486 seconds versus a 4.301-second
warm request; the following warm SDK requests took 3.954, 9.230, and 6.364 seconds.

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

### Bonus A — GitHub Actions CI/CD

1. Deployment runs only from `main` because that branch is the reviewed source of truth; feature
   branches must not mutate the shared production endpoint. The workflow also supports manual
   dispatch for controlled ad-hoc deployments.
2. A production quality gate would evaluate a versioned held-out dataset and compare the
   candidate with the current endpoint on groundedness, numerical accuracy, latency, and safety.
   The deployment job should reject any candidate that falls below defined thresholds.

The verified workflow ran Ruff and all six tests before deploying. GitHub Actions run
`29352336749` completed successfully and promoted manual endpoint version 19.

### Bonus B — `databricks-agents`

1. `agents.deploy()` automatically provisions an Agent Framework endpoint and Review App and
   integrates tracing and feedback, while the manual `WorkspaceClient` route provides more
   direct control over served entities, traffic, environment variables, and secret wiring.
2. Human feedback should be joined with traces, categorized by retrieval, routing, or
   calculation failure, added to a versioned evaluation set, and used to improve prompts or
   retrieval. A later candidate should pass that evaluation set before deployment.

The raw LangGraph state is not a standardized Agent Framework response. To keep the same graph
while satisfying the current SDK, `deployment/agent_chat_model.py` wraps it in MLflow's
`ChatAgent` interface. The model accepts `list[ChatAgentMessage]` and returns a
`ChatAgentResponse` containing the final answer as an assistant message, plus the plan and step
results in `custom_outputs`. MLflow derives the compatible signature from this interface, and
Databricks recognizes the endpoint task as `agent/v2/chat`; the model does not reduce the graph
to an untyped plain-string `PythonModel`.

Verified Bonus B evidence:

- Agent Framework endpoint: `agents_cs4603-pa4-pa4_document_analyst`, state `READY`.
- Unity Catalog model: `cs4603.pa4.pa4_document_analyst`, version 12.
- Auto-generated Review App:
  `https://dbc-01190470-5ed4.cloud.databricks.com/ml/review-v2/4f6c042eb90f4136a0e16b6de0b00488/chat`.
- MLflow experiment:
  `https://dbc-01190470-5ed4.cloud.databricks.com/ml/experiments/1306660282575833`.
- Retrieval trace `tr-7c56786093e210b3b5ac365cd8773f5f`, calculation trace
  `tr-c7370aee42cb30cc592233be524402a0`, and combined trace
  `tr-a729247b35812c589b41254e1c5cfe49` all have `TraceStatus.OK` and a persisted
  human `user_rating` of 1.0.

### Bonus C — Standalone MCP service

1. Moving MCP out of the model container enables independent scaling, releases, access policy,
   reuse, and monitoring. It introduces network latency, OAuth failures, and a separate
   availability dependency.
2. The hosted service is protected by Databricks App authentication. Model Serving uses the
   least-privilege service principal `cs4603-pa4-mcp-client`, which has only `CAN_USE`; its OAuth
   credentials are stored in the `cs4603-deploy` secret scope. Private networking and explicit
   authorization should be added where available.
3. Bundling is preferable for a small stable toolset that should deploy atomically with one
   agent. A separate service is preferable when several agents share the tools or the tools
   require their own release cadence, security boundary, or scaling policy.

The Databricks App `cs4603-mcp-tools` is running with active compute and serves the protected
streamable-HTTP route at
`https://cs4603-mcp-tools-7474653007190101.aws.databricksapps.com/api/mcp`. Endpoint version 19
uses this URL with OAuth secret references. A calculation returned HTTP 200 and 360 million;
when the app was stopped, the same dependency failed with `503 Service Unavailable`, and it
recovered after the app restarted. This proves that deployed calculations use the standalone
HTTP service rather than the bundled stdio fallback.
