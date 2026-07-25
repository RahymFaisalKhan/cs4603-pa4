# Tutorial — Unity Catalog Functions as Tools

**CS 4603 · Extra-Credit Assignment 1 — background tutorial**

> You already know two ways to give an agent a tool: the **`@tool` decorator** (a Python function bound in-process) and an **MCP tool server** (tools exposed by a separate server over a protocol). This tutorial adds the third — **Unity Catalog Functions** — and focuses on what it uniquely brings: **governance**.

Native tools live in your process. MCP tools live in a server you run. A **Unity Catalog Function** lives in the **data platform's catalog** as a governed, permissioned, versioned asset — and *then* becomes a tool. This is the approach you implement in Part 1 of the assignment.

---

## 1. What a UC Function is

A **Unity Catalog (UC) Function** is a Python or SQL function registered in Unity Catalog under a three-level name: `catalog.schema.function` (e.g. `main.default.compound_growth`). Once registered it is:

- **Discoverable** — `SHOW FUNCTIONS`, Catalog Explorer, `DESCRIBE FUNCTION`.
- **Governed** — access is controlled by `GRANT EXECUTE`; it has an owner and ACLs.
- **Audited & traced** — calls and lineage are captured by the platform.
- **Versioned** — `CREATE OR REPLACE FUNCTION` manages revisions.
- **Callable everywhere** — from SQL, notebooks, jobs, **and agents**.

The tool body is the *same math* you wrote as a native/MCP tool. What UC adds is **governance around it.**

---

## 2. Registering a function

### Python (via the function client)

```python
from unitycatalog.ai.core.databricks import DatabricksFunctionClient

client = DatabricksFunctionClient()

def compound_growth(principal: float, rate: float, periods: int) -> float:
    """Return principal * (1 + rate) ** periods.

    Args:
        principal: starting value.
        rate: growth rate per period as a decimal (0.08 = 8%).
        periods: number of periods.
    """
    return principal * (1 + rate) ** periods

client.create_python_function(
    func=compound_growth, catalog="main", schema="default", replace=True,
)
```

As always, **type hints + docstring become the tool schema** — UC parses them into typed parameters and a description.

### SQL

```sql
CREATE OR REPLACE FUNCTION main.default.to_billions(amount_yen DOUBLE)
RETURNS DOUBLE
COMMENT 'Convert a raw JPY amount to billions of yen.'
RETURN amount_yen / 1e9;
```

Use SQL when the logic is set-based or benefits from pushdown; use Python for procedural logic.

Verify either kind directly:

```python
client.execute_function("main.default.compound_growth",
                        {"principal": 16.91, "rate": 0.08, "periods": 3})
# or in SQL:  SELECT main.default.compound_growth(16.91, 0.08, 3);
```

---

## 3. Turning UC Functions into agent tools

`UCFunctionToolkit` wraps one or more UC functions as LangChain tools — again dropping straight into the same `ToolNode` pattern you used with `@tool` and MCP tools:

```python
from databricks_langchain import UCFunctionToolkit

toolkit = UCFunctionToolkit(
    function_names=[
        "main.default.compound_growth",
        "main.default.percent_change",
        "main.default.to_billions",
    ]
)
tools = toolkit.tools               # LangChain tools
llm_with_tools = llm.bind_tools(tools)
# ...ToolNode(tools) exactly as before
```

Where does execution happen? **Not** in your agent process — the function runs on **Databricks compute** (serverless / SQL warehouse). Your agent just requests the call and receives the result.

---

## 4. Governance: the whole point

```sql
-- Grant execute to a user or group
GRANT EXECUTE ON FUNCTION main.default.compound_growth TO `data-scientists`;

-- Inspect
DESCRIBE FUNCTION EXTENDED main.default.compound_growth;
SHOW FUNCTIONS IN main.default;
```

Now the tool has: an **owner**, an **ACL** (who may call it), **lineage** (what used it), and **audit** entries — none of which native or MCP tools give you out of the box. A second team reuses the tool by being granted `EXECUTE`, not by copying code.

---

## 5. Automatic authorization at deploy time

When you deploy an agent that calls UC Functions, the serving endpoint needs permission to run them. Instead of embedding a token, you **declare the functions as resources** and the platform provisions **short-lived credentials automatically** (the same mechanism `databricks_deployment_v2/` uses for serving endpoints):

```python
from mlflow.models.resources import DatabricksFunction, DatabricksServingEndpoint

resources = [
    DatabricksServingEndpoint(endpoint_name="databricks-meta-llama-3-3-70b-instruct"),
    DatabricksFunction(function_name="main.default.compound_growth"),
    DatabricksFunction(function_name="main.default.percent_change"),
    DatabricksFunction(function_name="main.default.to_billions"),
]

# mlflow.pyfunc.log_model(..., resources=resources)
#   -> register in Unity Catalog
#   -> agents.deploy(...)      # endpoint calls the functions with auto-provisioned creds
```

**No tokens in code, no secret scope for the tools** — authorization is derived from the declared resources.

---

## 6. Strengths and limits

**Strengths**
- **Governance built in** — permissions, ownership, lineage, audit, versioning.
- **Reuse at scale** — any UC-aware agent/user/job can call the same function.
- **SQL or Python**, executed on managed compute, with **automatic auth** on deploy.

**Limits**
- **Databricks-specific** — not portable off the platform (contrast MCP's interoperability).
- **Execution hop** — running on Databricks compute adds latency vs. an in-process call.
- **Platform ceremony** — catalogs, schemas, grants: more setup than a one-line `@tool`.

---

## 7. How it compares to the tools you already know

| If you care most about… | Choose |
|-------------------------|--------|
| Speed of development, lowest latency | **Native `@tool`** (in-process) |
| Interoperability & cross-language reuse | **MCP** tool server |
| Governance, audit, permissioned reuse | **Unity Catalog Functions** (this tutorial) |

The LLM's view of the tool is identical in all three cases — the same name, description, and typed arguments. What changes is **where the tool runs and who governs it**. In Part 1 you take the *exact* PA4 tools and move them from an MCP server to governed UC Functions, then explain, as an engineer, what materially changed even though the model's view did not.

---

### Analyze
Why does declaring `DatabricksFunction(...)` as a resource remove the need for a token in your deployment code?

