# Extra-Credit 1 · PART 3

## Agent Evaluation

> Part of **CS 4603 Extra-Credit Assignment 1**.
> ← Prev: [Part 2 — Genie](part-2-genie-structured-data.md) · Next: [Part 4 — Bonus Challenges](part-4-bonus-challenges.md) · [Overview](../README.md)

---

PA4 proved your endpoint *responds*. Here you measure whether it is *right* and *grounded* — across **both** retrieval paths (RAG and, if you did Part 2, Genie).

### Task 3.1: Build an evaluation dataset

Create **at least 10** evaluation examples over the Meridian corpus in `eval/eval_dataset.jsonl`. Cover a mix of:
- pure **retrieval** ("What was net income in FY2023?"),
- **calculation** ("...projected 3 years at 8%?"),
- **structured/tabular** ("Rank the FY2023 segments by revenue." — exercises the Genie path if you built it),
- **multi-hop** (retrieve two facts, then compare),
- and **at least one "not in the document"** case (the agent must decline, not hallucinate).

```jsonl
{"request": "What was Meridian's net revenue in FY2023?", "expected_response": "¥16.91 trillion", "expected_facts": ["16.91 trillion", "page 4"]}
{"request": "What is Meridian's projected net revenue after 3 years of 8% CAGR?", "expected_response": "≈ ¥21.30 trillion"}
```

### Task 3.2: Run judged evaluation

Evaluate your agent with **Databricks Agent Evaluation / MLflow LLM judges**.

```python
# Expected pattern:
import mlflow, pandas as pd

eval_df = pd.read_json("eval/eval_dataset.jsonl", lines=True)

with mlflow.start_run(run_name="doc-analyst-eval"):
    results = mlflow.evaluate(
        model=my_agent_predict_fn,     # or a served-endpoint wrapper
        data=eval_df,
        model_type="databricks-agent", # enables built-in LLM judges
    )
print(results.metrics)
```

Report, at minimum, the built-in judges for **correctness**, **groundedness** (a.k.a. faithfulness), and **relevance** (answer + retrieved-chunk relevance). Include the per-example table.

### Task 3.3: Diagnose, fix, and re-measure

- Identify the **worst-scoring** example(s) and state the **root cause** (bad chunking? weak prompt? tool misfire? retrieval miss? wrong route to RAG vs Genie?).
- Make **one** targeted change (e.g. adjust a prompt, chunk size, `k`, a tool, or a routing rule).
- **Re-run the same eval** and present a **before/after delta table**. Improvement is nice, but what matters is a *correct diagnosis backed by honest numbers* — a regression you can explain is fine.

**Analysis (write-up):** Why can an answer be **correct but not grounded** (or vice-versa)? Which judge would you gate a production deploy on, and why?

---

← Prev: [Part 2 — Genie](part-2-genie-structured-data.md) · Next: [Part 4 — Bonus Challenges](part-4-bonus-challenges.md) · [Overview](../README.md)
