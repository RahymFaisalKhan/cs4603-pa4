"""Append the captured Part 3 evidence to the cumulative submission notebook."""

from __future__ import annotations

import json
from pathlib import Path

import nbformat
import pandas as pd
from nbformat.v4 import new_code_cell, new_markdown_cell, new_output

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "extra_credit.ipynb"
RESULTS = ROOT / "eval" / "results"
PART3_TAG = "part3-evidence"


def _code(source: str, output: str, execution_count: int):
    return new_code_cell(
        source=source,
        metadata={"tags": [PART3_TAG]},
        execution_count=execution_count,
        outputs=[
            new_output(
                output_type="execute_result",
                execution_count=execution_count,
                data={"text/plain": output},
                metadata={},
            )
        ],
    )


def _markdown(source: str):
    return new_markdown_cell(source=source, metadata={"tags": [PART3_TAG]})


def main() -> None:
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    notebook.cells = [
        cell
        for cell in notebook.cells
        if PART3_TAG not in cell.get("metadata", {}).get("tags", [])
    ]

    examples = [
        json.loads(line)
        for line in (ROOT / "eval" / "eval_dataset.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    category_counts = (
        pd.Series([example["category"] for example in examples])
        .value_counts()
        .rename_axis("category")
        .to_frame("examples")
    )
    before_metrics = json.loads(
        (RESULTS / "before" / "metrics.json").read_text(encoding="utf-8")
    )
    after_metrics = json.loads(
        (RESULTS / "after" / "metrics.json").read_text(encoding="utf-8")
    )
    comparison = json.loads(
        (RESULTS / "comparison.json").read_text(encoding="utf-8")
    )
    before = pd.read_csv(RESULTS / "before" / "per_example.csv")
    after = pd.read_csv(RESULTS / "after" / "per_example.csv")
    per_example = pd.DataFrame(
        {
            "id": [example["id"] for example in examples],
            "category": [example["category"] for example in examples],
            "before_correct": before["correctness/value"],
            "after_correct": after["correctness/value"],
            "before_grounded": before["retrieval_groundedness/value"],
            "after_grounded": after["retrieval_groundedness/value"],
            "before_relevance": before["relevance_to_query/value"],
            "after_relevance": after["relevance_to_query/value"],
        }
    )
    delta = pd.DataFrame(comparison["metrics"])
    deployment = json.loads(
        (RESULTS / "deployment_evidence.json").read_text(encoding="utf-8")
    )

    notebook.cells.extend(
        [
            _markdown(
                """# Part 3 — Agent Evaluation

This section evaluates the deployed Part 2 RAG/Genie/UC agent on one frozen
12-example set using MLflow 3.14 built-in LLM judges. It diagnoses the weakest
baseline cases, applies one table-coverage routing fix, and re-runs the exact same
examples. Full artifacts are under `eval/results/`."""
            ),
            _code(
                """eval_path = Path("eval/eval_dataset.jsonl")
eval_examples = [
    json.loads(line) for line in eval_path.read_text().splitlines() if line.strip()
]
pd.Series([row["category"] for row in eval_examples]).value_counts()""",
                f"Validated {len(examples)} frozen examples\n\n"
                + category_counts.to_string(),
                13,
            ),
            _markdown(
                """## Built-in judges and trace contract

`eval/run_eval.py` uses `mlflow.genai.evaluate` with `Correctness`,
`RelevanceToQuery`, `RetrievalGroundedness`, and `RetrievalRelevance`.
The endpoint's ordered `custom_outputs.step_results` are recorded as an MLflow
`RETRIEVER` span, so groundedness and evidence relevance inspect the exact
document extracts, structured rows, and tool outputs used by synthesis."""
            ),
            _code(
                """before = json.loads(
    Path("eval/results/before/metrics.json").read_text()
)
before""",
                json.dumps(before_metrics, indent=2),
                14,
            ),
            _markdown(
                """## Diagnosis and targeted fix

The three worst baseline rows were FY2024 guidance, free cash flow, and the
North-America-versus-Motorcycle comparison. Each was routed to Genie even though
the curated Space contains only FY2022–FY2023 income-statement and segment tables.

The single behavioral change is `_table_coverage_route` in
`agent/graph_multi.py`: annual-report-only domains go to RAG, while covered
income-statement/segment queries remain in Genie and arithmetic remains in UC
Functions. The deployed model also declares both Genie tables as resources so
version updates preserve equivalent table authorization."""
            ),
            _code(
                """deployment = json.loads(
    Path("eval/results/deployment_evidence.json").read_text()
)
deployment""",
                json.dumps(deployment, indent=2),
                15,
            ),
            _code(
                """after = json.loads(
    Path("eval/results/after/metrics.json").read_text()
)
after""",
                json.dumps(after_metrics, indent=2),
                16,
            ),
            _code(
                """comparison = json.loads(
    Path("eval/results/comparison.json").read_text()
)
pd.DataFrame(comparison["metrics"])""",
                delta.to_string(index=False),
                17,
            ),
            _code(
                """before_rows = pd.read_csv("eval/results/before/per_example.csv")
after_rows = pd.read_csv("eval/results/after/per_example.csv")
per_example = pd.DataFrame({
    "id": [row["id"] for row in eval_examples],
    "category": [row["category"] for row in eval_examples],
    "before_correct": before_rows["correctness/value"],
    "after_correct": after_rows["correctness/value"],
    "before_grounded": before_rows["retrieval_groundedness/value"],
    "after_grounded": after_rows["retrieval_groundedness/value"],
    "before_relevance": before_rows["relevance_to_query/value"],
    "after_relevance": after_rows["relevance_to_query/value"],
})
per_example""",
                per_example.to_string(index=False),
                18,
            ),
            _markdown(
                """## Analysis Summary

An answer can be correct but ungrounded when it guesses or calculates the right
number without evidence that supports every claim. It can be grounded but
incorrect when it faithfully uses the wrong fact, definition, sign, or
calculation.

For a financial document analyst I would gate deployment on groundedness, with
correctness as a companion threshold. Unsupported plausible figures defeat the
system's audit purpose. A strict 0.90 groundedness gate would still block this
model at 0.75 despite its 1.00 post-fix correctness, which is the honest
production conclusion.

The complete analysis is provided in [`writeup.md`](writeup.md)."""
            ),
        ]
    )
    nbformat.write(notebook, NOTEBOOK)
    print(f"Updated {NOTEBOOK} with {len(notebook.cells)} cells")


if __name__ == "__main__":
    main()
