# CS4603 Extra-Credit Assignment 1

This submission completes Parts 1–3 and Part 4 Challenges E and F. Challenge D
includes its live trace and a working production-traffic SQL result through a
transparent client-side Unity Catalog payload-log fallback. The workspace
rejected the exact Databricks-managed inference-table feature, so that one
platform-managed step remains explicitly identified rather than misrepresented.

## Part 1 — Unity Catalog Functions

### Implementation and reproduction

The PA4 MCP graph is still there in `agent/graph.py`. I built the governed version separately in `agent/graph_uc.py` so you can run both and compare them side by side.

To install the environment, authenticate to Databricks, and register/verify the functions:

```bash
uv sync --extra dev --extra agents
databricks auth login \
  --host https://dbc-01190470-5ed4.cloud.databricks.com \
  --profile rahym-ec1
uv run python -m uc_tools.register_functions \
  --profile rahym-ec1 \
  --catalog cs4603 \
  --schema pa4
```

Running that registers (or replaces) these governed functions:

| Function | Definition | Purpose |
|---|---|---|
| `growth_rate` | Python | Apply compound annual growth |
| `percentage_change` | Python | Calculate percentage change |
| `compare_values` | Python | Identify the larger value and difference |
| `to_billions` | SQL | Convert raw yen to billions of yen |

After that, it runs all four functions directly, checks the results against known answers, grants `EXECUTE` to whichever principal you choose (the current user by default), and writes everything reproducible to `uc_tools/registration_evidence.json`.

You can try out the governed graph like this:

```python
from agent.graph_uc import build_graph_uc

graph = build_graph_uc()
result = graph.invoke({
    "messages": [{
        "role": "user",
        "content": (
            "What was Meridian's FY2023 net revenue, and what would it be "
            "after 3 years of 8% compound growth?"
        ),
    }]
})
print(result["final_answer"])
print(result["step_results"])
```

I ran this live and recorded it in `uc_tools/live_graph_evidence.json`. The graph built a two-step plan: first pull the FY2023 revenue, then run one three-year compound-growth calculation. It pulled `16,910 billion yen` from `annual_report.pdf` page 4, and the governed `cs4603.pa4.growth_rate` function returned `21.301729920000003` trillion yen — roughly `21,301.73 billion yen`.

Deployment is handled separately:

```bash
uv run python deployment/deploy_uc.py
```

This logs `deployment/agent_uc_chat_model.py` as a models-from-code `ChatAgent`, registers a separate `_uc` model, and deploys it along with the LLM endpoint, Vector Search index, and every UC Function declared as MLflow resources. Since I'm working in a quota-limited workspace, I set `UC_AGENT_ENDPOINT_NAME` so it updates the existing Agent Framework endpoint instead of spinning up a new one.

The logged model is `cs4603.pa4.pa4_document_analyst_uc`, version `1`, and its MLflow run is `39816c182b2b4c999f6c38cbe9c6d9fb` in experiment `/Shared/cs4603-extra-credit-1`. It's deployed on the existing `agents_cs4603-pa4-pa4_document_analyst` endpoint. When I queried the live endpoint, it returned `21,301.72992 billion yen`, kept the page-4 annual-report citation intact, and reported `tool_backend: unity_catalog_functions`.

### Task 1.2 — When SQL is preferable to Python

I'd reach for a SQL function when the calculation is naturally relational or set-based, when it makes sense to push the work down to the data engine, or when it only needs operations SQL already handles well. That way you skip spinning up a Python runtime and can run the calculation right next to the governed tables. Python makes more sense for procedural logic, algorithms that get awkward in SQL, or anything that needs a Python library. `to_billions` is SQL on purpose, since it's just a simple, deterministic numeric conversion. The other three, richer PA4 functions stayed in Python.

### Task 1.4 — MCP tools versus Unity Catalog Functions

| Dimension | MCP server tools | Unity Catalog Function tools |
|---|---|---|
| Discovery | Discovered from a configured MCP server during a client session | Searchable through Catalog Explorer, `SHOW FUNCTIONS`, and a three-level UC name |
| Permissions | Controlled by the MCP service and its surrounding application/auth layer | Native `USE CATALOG`, `USE SCHEMA`, and `EXECUTE` privileges |
| Governance | Must build or connect auditing, ownership, and policy separately | UC supplies ownership, ACLs, auditability, metadata, and lineage |
| Reuse | Any MCP-compatible client can reuse the server, including clients outside Databricks | Any authorized Databricks notebook, SQL query, job, or agent can reuse the function |
| Versioning | Depends on the MCP service's source-control and deployment practice | `CREATE OR REPLACE FUNCTION` creates a centrally managed catalog revision |
| Transport | Standard MCP transport such as stdio or streamable HTTP | Toolkit invokes a named UC function on managed Databricks compute |
| Authentication | Transport-specific bearer token, OAuth, or local process trust | Unity Catalog identity and privileges; deployed agents can receive short-lived credentials |
| Portability | High because MCP is vendor-neutral | Databricks-specific |
| Latency | Local stdio can be fast; remote HTTP adds a network hop | Adds a managed function-execution hop |

That said, I'd still pick MCP when the tools need to be portable across platforms, when they're wrapping an existing non-Databricks service, when cross-language interoperability matters, when I need long-lived server state, or when there's streaming or custom protocol behavior that doesn't fit neatly into a scalar UC function. UC Functions win out for deterministic business logic where centralized access control, audit, lineage, and reuse inside Databricks actually matter.

### Task 1.5 — Why declared resources remove the token

`DatabricksFunction(...)` records the function dependency directly in the MLflow model. When you run `agents.deploy()`, Databricks grants the endpoint identity the access it needs and injects short-lived credentials at runtime. The function client just uses that ambient identity, so there's no PAT or function-specific secret sitting in the model or endpoint config. The same deployment also declares the LLM endpoint and Vector Search index, so their clients get to use the same automatic-authorization setup.

### Evidence

The following evidence lives in the cumulative `extra_credit.ipynb`:

1. Python and SQL function registration.
2. Direct execution results for all four functions.
3. Explicit `EXECUTE` grant output and UC metadata.
4. The canonical RAG-then-compound-growth query through `graph_uc.py`.
5. Catalog Explorer metadata/lineage screenshot.
6. The deployed endpoint's end-to-end governed-tool response.

I also kept the machine-readable registration, local graph, and deployed graph outputs in `uc_tools/registration_evidence.json`, `uc_tools/live_graph_evidence.json`, and `uc_tools/deployment_evidence.json`. Catalog Explorer metadata is captured in `uc_tools/catalog_explorer.png` and linked from the notebook.

## Part 2 — Genie Structured-Data Retrieval

### Tasks 2.1–2.3 — Tables, curation, and Conversation API

`genie/build_tables.py` idempotently creates two managed Delta tables in `cs4603.pa4` through the SQL Statement Execution API:

| Table | Grain | Rows | Source |
|---|---|---:|---|
| `meridian_segment_financials` | fiscal year × reportable segment | 8 | FY2023 is transcribed; FY2022 is synthesized |
| `meridian_income_statement` | fiscal year × line item | 26 | annual-report statement of operations |

Every table and column has a Unity Catalog comment. Monetary columns store raw Japanese yen as `BIGINT`, and expense values in the income statement are negative. The FY2023 segment rows sum to ¥16.91T revenue and ¥1.124T operating profit. Since the report doesn't disclose the FY2022 segment allocation, I synthesized plausible segment rows that sum exactly to the reported ¥14.55T revenue and ¥905B operating profit. `INSERT OVERWRITE` keeps repeated setup safe.

The exact derivation is documented in `genie/tables.sql`, and live totals/comments live in `genie/table_evidence.json`. A row-by-row mapping of reported versus synthetic values is in `genie/DATA_DERIVATION.md`.

Here's the setup and live verification:

```bash
python -m genie.build_tables \
  --profile rahym-ec1 --catalog cs4603 --schema pa4 \
  --warehouse-id b4167325a6783244
python -m genie.build_space \
  --profile rahym-ec1 --catalog cs4603 --schema pa4 \
  --warehouse-id b4167325a6783244
python -m genie.genie_client \
  --profile rahym-ec1 --space-id 01f1886749c81c3eada5b6f36fcacb63
python -m genie.run_live_graph \
  --profile rahym-ec1 --space-id 01f1886749c81c3eada5b6f36fcacb63
```

`genie/build_space.py` created the **Meridian Financial Analytics** Genie Space:

- Space ID: `01f1886749c81c3eada5b6f36fcacb63`
- SQL warehouse: `b4167325a6783244`
- Tables: both governed Meridian tables above
- Curation: three sample questions, one detailed general instruction block, and two trusted question/SQL pairs (FY2023 segment ranking and segment YoY growth)

The instructions spell out yen scaling, what FY means, the operating-margin formula, and the important distinction between profit for the year and net income attributable to owners. The full version-2 Space payload is source-controlled in `genie/space_config.py`, and `genie/space_evidence.json` records the live Space.

`genie/genie_client.py` uses `WorkspaceClient.genie.start_conversation_and_wait`, pulls out the query attachment, and retrieves its inline result rows. All three live questions succeeded. For the canonical ranking question, Genie generated this:

```sql
SELECT segment, try_divide(revenue_yen,1000000000.0) AS revenue_billion_yen
FROM cs4603.pa4.meridian_segment_financials
WHERE fiscal_year = 2023
ORDER BY revenue_yen DESC
```

It returned Automobile ¥12,900B, Motorcycle ¥2,510B, Financial Services ¥1,100B, and Power Products & Other ¥400B. It also correctly picked out Financial Services as the biggest YoY operating-margin improver (+2.286 percentage points) and compared FY2022/FY2023 revenue and operating profit. Full SQL and row output is in `genie/conversation_evidence.json`.

The notebook also includes three visual evidence captures under
`genie/screenshots/`. They are rendered directly from the saved live
conversation IDs, generated SQL, rows, and answers, so each required question →
SQL → result round-trip is visible without relying on an external workspace
session during grading.

### Task 2.4 — Routed multi-agent graph

`agent/graph_multi.py` adds `GenieAgent` as a real graph node while keeping the Part 1 `UCFunctionToolkit` node and the PA4 Vector Search RAG node around:

```text
planner -> supervisor -> genie | rag_agent | uc_tools -> supervisor -> synthesizer
```

The planner keeps a full ranking request as one structured step. The supervisor follows explicit routing instructions: table lookups, rankings, aggregations, and YoY questions go to Genie; risks, strategy, and explanations go to RAG; deterministic numeric transforms go to UC Functions. The Genie node holds onto both the generated SQL and the Markdown rows in `step_results`, so the synthesizer can spell out the exact numbers. It also carries a Genie conversation ID for multi-step structured questions and logs `route_history` so everything stays auditable.

The two required live graph runs are captured in `genie/live_graph_evidence.json`:

1. "Rank Meridian's FY2023 segments by revenue." routed to **Genie**, kept the SQL and four result rows, and produced a clean ranked answer.
2. "What risks did Meridian cite for its Automobile segment?" routed to **RAG**, returned the five stated risk categories, and preserved the annual-report page citation.

The offline suite also verifies both routes plus the retained UC-tools route. That means a mixed request can pull a table value from Genie and then hand it off to a governed function for projection.

### Task 2.5 — Deployment and automatic authorization

`deployment/agent_multi_chat_model.py` exposes the routed graph as an MLflow `ChatAgent`. `deployment/deploy_multi.py` declares the LLM endpoint, Vector Search index, all four UC Functions, and:

```python
DatabricksGenieSpace(
    genie_space_id="01f1886749c81c3eada5b6f36fcacb63"
)
```

The registered model is `cs4603.pa4.pa4_document_analyst_multi`, version 1, from MLflow run `1cb4f4f26e2b40a1b63b8e73ff958cb9`. I pointed deployment at the existing `agents_cs4603-pa4-pa4_document_analyst` endpoint so I wouldn't burn another Free Edition endpoint slot. No PAT is stored anywhere in the model code or endpoint environment; resource credentials come through Agent Framework's automatic authorization instead.

The Genie Space resource gives the endpoint identity `CAN RUN` access to the Space, but UC still requires separate data privileges, and the first served query made that boundary obvious. So `genie/grant_data_access.py` granted the endpoint's system service principal (`53f956da-ff9f-4f38-a9f9-cf8f494a04b0`) only `USE CATALOG`, `USE SCHEMA`, and `SELECT` on the two Meridian tables. `genie/grant_evidence.json` confirms those privileges through `information_schema`.

```bash
python -m genie.grant_data_access \
  --profile rahym-ec1 --catalog cs4603 --schema pa4 \
  --warehouse-id b4167325a6783244 \
  --principal 53f956da-ff9f-4f38-a9f9-cf8f494a04b0
```

The endpoint came up in `READY` state, and the served ranking question worked end to end: `route_history` was `["genie"]`, the response kept the generated SQL and four table rows, and the final answer correctly ranked Automobile, Motorcycle, Financial Services, and Power Products & Other with the right amounts. Full endpoint/resource/response evidence is in `genie/deployment_evidence.json`.

### Analysis — RAG versus Genie

Two questions that RAG handles best:

1. "What risks did Meridian cite for its Automobile segment?" This is an enumerated narrative scattered through risk-factor prose, not a relational aggregate.
2. "Which R&D priorities did management describe for FY2024?" This is asking for qualitative themes and management context where the exact wording and citations matter.

Two questions that Genie handles best:

1. "Rank FY2023 segments by revenue." Just a filter plus an ordered projection over one governed table.
2. "Which segment improved operating margin the most from FY2022 to FY2023?" This needs a self-join, two ratios, a difference, and a max — SQL does this precisely and reproducibly.

The supervisor leans on intent and vocabulary to decide. Words like fiscal-year, rank, highest/lowest, aggregation, margin, comparison, and YoY point to structured retrieval. Words like risk, reason, strategy, priority, and outlook explanation point to narrative retrieval. And when a request asks for a deterministic projection or conversion after retrieval, that signals the UC-tools node.

### Analysis — Text-to-SQL failure modes

First, Genie can pick the wrong semantic measure. For example, "net income" could get mapped to `Profit for the year` (which includes NCI) instead of `Net income attributable to owners`, or a segment question could accidentally hit the consolidated income statement instead. To guard against this, the general instructions spell out both distinctions, table descriptions state their grain, column comments define each value, and the trusted SQL examples show the correct patterns.

Second, Genie can return something that looks numerically plausible but is actually scaled or joined wrong. Raw yen could get labeled as billions, operating margin could get calculated across inconsistent years, or a self-join could drop one fiscal-year predicate and multiply rows it shouldn't. Column comments and instructions state the raw-yen storage and formulas, and the trusted ranking and YoY queries demonstrate the correct scaling, aliases, join keys, year filters, and ordering. Curation cuts down these risks but doesn't eliminate them entirely, which is why the generated SQL and rows stay visible in the evidence and traces.

### Analysis — Governance and lineage

Both tables are owned by `27100057@lums.edu.pk`. Direct querying is available to the owner, metastore administrators, and principals with `USE CATALOG`, `USE SCHEMA`, and `SELECT`. The deployed system service principal has exactly those data privileges on these two tables — sharing a Genie Space doesn't quietly bypass Unity Catalog privileges. For the served agent, `DatabricksGenieSpace` lets Agent Framework provision short-lived runtime credentials for the declared Space instead of embedding a PAT, and the scoped table grants determine what that runtime identity can actually read.

If SQL were embedded directly in the agent code, UC could still audit the table statement, but the business intent, the choice of generated query, and any reusable semantic guidance would all live outside the governed analytics asset. Routing through Genie puts a governed Space between user intent and SQL instead: Space access, Conversation API activity, generated SQL, warehouse query history, and table lineage can all be connected. The source tables and their comments stay centrally permissioned, while the supervisor route and stored generated SQL explain why the query ran in the first place.

## Part 3 — Agent Evaluation

### Task 3.1 — Frozen evaluation dataset

`eval/eval_dataset.jsonl` has 12 examples and stays unchanged across both measured runs. It includes four retrieval cases, three structured cases, two calculations, two multi-hop cases, and one not-in-document refusal. Every row has a stable ID, category, request, expected response, and expected facts. I deliberately made the set cross both Part 2 retrieval paths plus the Part 1 governed calculation path.

The source JSONL keeps both `expected_response` and `expected_facts`, as the assignment asked for. Since MLflow 3.14's current `Correctness` scorer rejects rows that pass both fields at once, `eval/run_eval.py` sends the canonical `expected_response` to that scorer while keeping the fact list in the source dataset for human review.

### Task 3.2 — Judged MLflow evaluation

The harness runs on `mlflow.genai.evaluate`, which is MLflow 3's successor to the course's `mlflow.evaluate(..., model_type="databricks-agent")` pattern. It calls the deployed `ChatAgent` through the pyfunc scoring envelope and runs four built-in judges:

- `Correctness`
- `RelevanceToQuery` (answer relevance)
- `RetrievalGroundedness`
- `RetrievalRelevance` (per-evidence relevance and span-level precision)

The endpoint returns the ordered evidence actually passed to its synthesizer in `custom_outputs.step_results`, and the harness records those results as a typed MLflow `RETRIEVER` span. That lets the built-in RAG judges compare the answer against the exact structured rows, document extracts, and governed-function outputs the agent actually used.

To work around Free Edition endpoint quotas and trace-store retries, collection and judging can run separately:

```bash
python -m eval.run_eval --label after --profile rahym-ec1 --collect-only
python -m eval.run_eval --label after --profile rahym-ec1 \
  --predictions-cache eval/results/after/predictions.json
```

Each endpoint answer gets checkpointed right away. Replaying the cache doesn't change an answer or its evidence — it just creates fresh MLflow traces for the judges.

The clean baseline run is `c40d62927c5a43fc9e646b92540809d1`, and the definitive after run is `6051768be35348cb9dbd6bb629f979b3`. Both live in `/Shared/cs4603-extra-credit-1`. Aggregate metrics, raw served predictions, and full per-example MLflow tables are exported under `eval/results/before/` and `eval/results/after/`.

| ID | Category | Before correctness | After correctness | Before grounded | After grounded | Before answer relevance | After answer relevance | Before evidence precision | After evidence precision |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `retrieval_net_income` | retrieval | yes | yes | yes | yes | yes | yes | 1.00 | 1.00 |
| `retrieval_fy2024_guidance` | retrieval | no | yes | no | yes | yes | yes | 0.00 | 0.00 |
| `retrieval_rnd_priorities` | retrieval | no | yes | yes | yes | yes | yes | 1.00 | 1.00 |
| `structured_segment_rank` | structured | yes | yes | yes | yes | yes | yes | 1.00 | 1.00 |
| `structured_margin_leader` | structured | yes | yes | yes | yes | yes | yes | 1.00 | 1.00 |
| `structured_income_growth` | structured | yes | yes | no | yes | yes | yes | 0.67 | 0.67 |
| `calculation_revenue_projection` | calculation | yes | yes | no | no | yes | yes | 0.50 | 0.50 |
| `calculation_free_cash_flow` | calculation | no | yes | no | no | yes | yes | 0.00 | 0.00 |
| `multihop_profit_vs_rnd` | multi-hop | no | yes | yes | yes | yes | yes | 0.25 | 0.25 |
| `multihop_regions_vs_segment` | multi-hop | no | yes | no | yes | yes | yes | 0.00 | 0.25 |
| `retrieval_risk_effect` | retrieval | yes | yes | yes | yes | yes | yes | 1.00 | 1.00 |
| `not_in_document_ceo_pay` | not in document | yes | yes | no | no | yes | yes | 0.50 | 0.00 |

### Task 3.3 — Diagnosis, one targeted fix, and re-measurement

The three lowest baseline examples, each with a mean per-row judge score of 0.20, were:

1. FY2024 net-revenue and operating-profit guidance.
2. FY2023 free cash flow from operating cash flow and capital expenditure.
3. North American revenue versus Motorcycle segment revenue.

All three traced back to the same root cause. The Part 2 supervisor treated any table-shaped financial request as a Genie request, but the curated Genie Space only has two tables: FY2022–FY2023 income-statement rows and FY2022–FY2023 segment financials. FY2024 guidance, cash-flow data, and regional revenue only exist in the annual report. So Genie kept returning empty or null rows even though Vector Search actually had the facts. This was a routing/table-coverage bug, not a chunking problem.

I made one targeted behavioral change: `_table_coverage_route` in `agent/graph_multi.py`. It's an explicit coverage guard that sends FY2024 guidance, cash-flow, balance-sheet, regional/geographic, and executive-compensation steps to RAG instead. Income-statement and segment questions still go to Genie, and arithmetic still goes to UC Functions. `MULTI_SUPERVISOR_PROMPT` documents the same boundary so the learned and deterministic routing policies agree with each other.

The fixed graph is registered as `cs4603.pa4.pa4_document_analyst_multi`, version 3, from MLflow run `8a8674395ac940ea883966533cd0aeb5`, and it's active on `agents_cs4603-pa4-pa4_document_analyst`. Version 3 also declares both Genie tables as `DatabricksTable` resources. That authorization declaration doesn't change any answers — it just makes sure each new serving identity gets the same minimum `SELECT` access, so deployment identity drift can't confound the comparison.

| Judge metric | Before | After | Delta |
|---|---:|---:|---:|
| Correctness | 0.5833 | 1.0000 | **+0.4167** |
| Retrieval groundedness | 0.5000 | 0.7500 | **+0.2500** |
| Answer relevance | 1.0000 | 1.0000 | +0.0000 |
| Retrieval relevance | 0.4444 | 0.4444 | +0.0000 |
| Retrieved-evidence precision | 0.5764 | 0.5556 | **−0.0208** |

The fix moved the main quality metrics substantially. Five of twelve baseline answers were judged incorrect, and now all twelve after answers are correct. The three coverage cases now return the expected FY2024 guidance, ¥1,170B free cash flow, and ¥4,910B North-America-versus-Motorcycle difference. Groundedness climbed by 25 points.

The small precision regression is worth being upfront about. SQL usually returns one narrow, highly relevant result table, while RAG tends to pull back several chunks around the target fact. The CEO-compensation refusal is still correct, but it retrieves unrelated nearby report chunks before concluding the value just isn't there, so its evidence precision dropped from 0.50 to 0.00. That's a good next thing to optimize, but changing retrieval or the refusal policy would be a second behavioral fix, and it's outside the scope of this one-change experiment.

### Analysis — Correctness, groundedness, and a production gate

An answer can be correct but not grounded when the model already knows, guesses, or calculates the right value, but the retrieved evidence doesn't actually back it up. The revenue projection is a good example of this: the final number can be mathematically correct while the last evidence span is missing one of the labeled intermediate assumptions the groundedness judge expects. On the flip side, an answer can be grounded but incorrect if it faithfully repeats an irrelevant chunk, uses the wrong financial definition, or computes incorrectly from correctly retrieved values. The baseline operating-profit-versus-R&D answer was grounded in real rows but got the expense sign wrong.

For this document analyst, I'd gate a production deploy on **groundedness**, with correctness as a required companion threshold. An answer that's ungrounded but sounds plausible is hard for a user to catch, and it undermines the whole point of the system's citation/audit trail. So groundedness is the safety gate, and correctness confirms the supported evidence was actually interpreted properly. A practical policy would require both to clear a documented threshold and would block on either one regressing. Under a strict 0.90 groundedness gate, the measured 0.75 after score would correctly block this agent from being called production-ready, even though correctness hit 1.00.

## Part 4 — Observability and Governance

### Challenge D — Tracing and monitoring *(functional UC fallback; managed feature unavailable)*

I sent four fresh live requests to the deployed endpoint `agents_cs4603-pa4-pa4_document_analyst`. The routing question "Rank Meridian's FY2023 segments by revenue" produced MLflow trace `tr-d0bc64e74f5946f02d444404138e4afe` in experiment `1306660282575833`. `custom_outputs.route_history` shows **Genie** as the winning node. The exported trace tree is `bonus/results/trace_tree.png`, and its measured spans include:

| Span | Type | Duration |
|---|---|---:|
| `multi_source_document_analyst` | AGENT | 38,264.84 ms |
| `_query_genie_as_agent` | internal | 23,745.73 ms |
| `genie_timeline` | CHAIN | 23,549.73 ms |
| `pending_warehouse` | CHAIN | 6,409.01 ms |
| `executing_query` | CHAIN | 4,847.35 ms |
| `_parse_query_result` | PARSER | 15.39 ms |

This makes the bottleneck clear: most measured application latency sits inside the Genie round-trip, including 6.4 seconds waiting for the SQL warehouse and 4.8 seconds executing the query, rather than in the 15.4 ms result parser. The client observed 101,176.24 ms for this first request because it also included the endpoint's scale-from-zero startup before the trace began.

I tried enabling the UC inference table through `PUT /api/2.0/serving-endpoints/{name}/ai-gateway`, supplying catalog `cs4603`, schema `pa4`, and prefix `pa4_document_analyst_inference`. I verified `CAN_MANAGE`, schema ownership, the active endpoint type, and the 100%-to-v3 route first. The same API was also tested on the existing custom-model endpoint. Both returned:

```text
NotFound: Inference table is not currently supported for this endpoint type in this workspace.
```

The legacy `auto_capture_config` path is also disabled by the service, which now only accepts `enabled=false` and directs users back to AI Gateway. Creating another agent endpoint would not change the workspace feature gate and would exceed this Free Edition workspace's serving-concurrency quota. I therefore left both existing endpoint models and routes unchanged.

To make the remaining learning objective executable, `bonus/trace_and_monitor.py` now implements a clearly labeled client-side fallback. It writes the same four live requests and responses, endpoint name, route history, timestamps, measured client latency, HTTP status, and request IDs to the managed Delta table `cs4603.pa4.pa4_document_analyst_client_payload`. The table comment and each row's `capture_source` identify it as `client_side_fallback`; it is not claimed as a Databricks-managed inference table.

`bonus/monitoring.sql` queries that fallback table:

```sql
SELECT date_trunc('minute', request_time) AS minute,
       count(*) AS n_requests,
       round(avg(execution_duration_ms), 2) AS avg_latency_ms,
       sum(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS errors
FROM cs4603.pa4.pa4_document_analyst_client_payload
GROUP BY 1
ORDER BY 1;
```

The live result is:

| Minute (UTC) | Requests | Average client latency | Errors |
|---|---:|---:|---:|
| 2026-07-27 12:08 | 1 | 101,176.24 ms | 0 |
| 2026-07-27 12:10 | 3 | 16,756.22 ms | 0 |

The SQL result, all four request IDs, and `managed_inference_table_requirement_met=false` / `functional_uc_payload_monitoring_met=true` are preserved in `bonus/results/inference_table_evidence.json`. An independent aggregation of the four matching production traces records 21,880.80 ms average root-span latency, 38,264.84 ms maximum latency, and zero failed roots in `bonus/results/trace_aggregate_evidence.json`.

**Production alert.** I'd alert when five-minute p95 end-to-end latency exceeds 45 seconds for three consecutive windows, plus an immediate alert if the HTTP error rate exceeds 2%. The sustained threshold sits above the 38.3-second successful root trace but will catch repeated warehouse cold starts, Genie polling delays, or serving saturation. A separate cold-start dashboard should retain client-observed latency because the 101.2-second first request shows that trace duration alone can understate what a user experienced.

### Challenge E — Guardrail fallback

Databricks' current serving API says agent endpoints don't accept Gateway rate-limit or AI Guardrail policies in this workspace. So I used the assignment's code-level fallback instead. `bonus/guardrails.py` implements:

- a maximum of two accepted requests per user per rolling minute; and
- blocking for Pakistani CNICs, US SSNs, and email addresses.

The guardrail is an actual first node in `agent/graph_multi.py`, sitting before the planner, Vector Search, Genie, UC Functions, or any LLM call. A rejected request goes straight to `END` with a safe response and `route_history=["guardrail"]`.

The deterministic demonstration in `bonus/results/guardrail_evidence.json` shows:

| Test | Decision | Downstream agent called |
|---|---|---:|
| Third request inside one rolling minute | `rate_limited` | false |
| `finance.user@example.com` in the prompt | `pii_blocked` | false |

The production model wrapper accepts `custom_inputs.user_id`, and deployment can turn on the fallback with `ENABLE_CODE_GUARDRAILS=true`. It's off by default in the shared endpoint configuration so the assignment's aggressive two-request demo limit doesn't accidentally deny ordinary evaluation traffic.

**Analysis.** A Gateway is the better home for this in production, since its policy is centralized, auditable, independently administered, and applied before traffic even reaches any potentially buggy application path. It can also enforce identity-aware limits across every client and block unsafe input even if the agent fails to initialize. In-agent controls, on the other hand, can inspect domain-specific state and intermediate tool plans that the Gateway simply can't see, and they can return application-specific explanations. But they eat into application capacity, can be bypassed by alternate deployments, and fail open if a developer forgets to add the guard node. The strongest design for a paid tier would use both layers together: platform-wide controls at the Gateway, and domain-specific policy inside the graph.

### Challenge F — Prompt lifecycle

I registered the routed supervisor in the Unity Catalog Prompt Registry as `cs4603.pa4.meridian_multi_supervisor`:

| Version | Purpose | Associated frozen-system correctness |
|---|---|---:|
| 1 | Original broad table-shaped routing prompt | 0.5833 |
| 2 | Coverage-aware prompt documenting the Genie table boundary | 1.0000 |

The isolated real-LLM routing comparison used seven route-labeled cases drawn
from the frozen Part 3 set:

| Prompt version | Correct routes | Routing accuracy |
|---|---:|---:|
| v1 baseline | 5 / 7 | 0.7143 |
| v2 coverage-aware | 6 / 7 | 0.8571 |

Because v2 scored higher, `production` remains on v2. Full per-case expected
and observed routes are preserved in the prompt evidence JSON.

The agent no longer feeds `MULTI_SUPERVISOR_PROMPT` directly to the supervisor LLM. `agent/prompt_registry.py` loads `prompts:/cs4603.pa4.meridian_multi_supervisor@production` with a zero-second alias-cache TTL. There's a local fallback to keep offline tests working, and setting `PROMPT_REGISTRY_REQUIRED=true` switches this to fail closed instead.

For the no-redeploy demonstration, `bonus/prompt_lifecycle.py` creates one
supervisor backed by the real Databricks model endpoint, points `production` at
v1, evaluates route-labeled cases drawn from the frozen Part 3 dataset, moves
the alias to v2, and evaluates the **same supervisor instance** again. The
controlled comparison disables the deterministic table-coverage guard so the
registry prompt is the only changed variable. The alias is then left on the
version with higher routing accuracy (ties favor the coverage-aware v2).

The 0.5833-to-1.0000 numbers remain the honest Part 3 **system-level**
evaluation and are not presented as a prompt-only delta. The separate
route-labeled experiment is the isolated v1-versus-v2 prompt comparison; its
results and per-case routes are stored in
`bonus/results/prompt_registry_evidence.json`.

**Rollback analysis.** Versions are immutable, but an alias is just a movable pointer. So rollback simply means atomically moving `production` back to v1. The next supervisor call reloads that alias with no source changes, model registration, or endpoint deployment needed. This cuts recovery time way down while keeping an auditable record of both prompt versions and every promotion decision.
