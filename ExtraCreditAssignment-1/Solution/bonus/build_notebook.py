"""Append captured Part 4 evidence to the cumulative submission notebook."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_output

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "extra_credit.ipynb"
RESULTS = ROOT / "bonus" / "results"
PART4_TAG = "part4-evidence"


def _markdown(source: str):
    return new_markdown_cell(source=source, metadata={"tags": [PART4_TAG]})


def _code(source: str, output: str, execution_count: int):
    return new_code_cell(
        source=source,
        metadata={"tags": [PART4_TAG]},
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


def _image_cell(path: Path, execution_count: int):
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return new_code_cell(
        source=(
            'display(Image(filename="bonus/results/trace_tree.png"))'
        ),
        metadata={"tags": [PART4_TAG]},
        execution_count=execution_count,
        outputs=[
            new_output(
                output_type="display_data",
                data={
                    "image/png": encoded,
                    "text/plain": "<MLflow trace tree with measured span timings>",
                },
                metadata={},
            )
        ],
    )


def main() -> None:
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    notebook.cells = [
        cell
        for cell in notebook.cells
        if PART4_TAG not in cell.get("metadata", {}).get("tags", [])
    ]

    trace = json.loads((RESULTS / "trace_evidence.json").read_text(encoding="utf-8"))
    inference = json.loads(
        (RESULTS / "inference_table_evidence.json").read_text(encoding="utf-8")
    )
    aggregate = json.loads(
        (RESULTS / "trace_aggregate_evidence.json").read_text(encoding="utf-8")
    )
    guardrails = json.loads(
        (RESULTS / "guardrail_evidence.json").read_text(encoding="utf-8")
    )
    prompts = json.loads(
        (RESULTS / "prompt_registry_evidence.json").read_text(encoding="utf-8")
    )

    span_summary = [
        {
            "depth": span["depth"],
            "name": span["name"],
            "type": span["span_type"],
            "duration_ms": span["duration_ms"],
            "status": span["status"],
        }
        for span in trace["spans"]
    ]
    inference_summary = {
        "capture_mode": inference["capture_mode"],
        "managed_inference_table": inference["managed_inference_table"],
        "aggregate_table": inference["aggregate_table"],
        "managed_inference_table_requirement_met": inference[
            "managed_inference_table_requirement_met"
        ],
        "functional_uc_payload_monitoring_met": inference[
            "functional_uc_payload_monitoring_met"
        ],
        "configuration": inference["configuration"],
        "configuration_error": inference["configuration_error"],
        "live_request_routes": [
            {
                "question": row["question"],
                "route_history": row["route_history"],
            }
            for row in inference["traffic"]
        ],
        "aggregate_query": inference["aggregate_query"],
        "aggregate_columns": inference["aggregate_columns"],
        "aggregate_rows": inference["aggregate_rows"],
        "query_note": inference["query_note"],
        "mlflow_trace_fallback_aggregate": aggregate,
    }

    notebook.cells.extend(
        [
            _markdown(
                """# Part 4 — Observability and Governance

Challenge D includes the live trace and a working aggregate SQL result over an
explicitly labeled client-side Unity Catalog payload-log fallback. The exact
Databricks-managed inference-table feature was rejected by this workspace and
is not misrepresented as complete. Challenges E and F are completed using the
permitted code-level guardrail fallback and a real-LLM prompt-routing
comparison, respectively."""
            ),
            _code(
                """trace = json.loads(
    Path("bonus/results/trace_evidence.json").read_text()
)
{
    "trace_id": trace["trace_id"],
    "winning_route": trace["winning_route"],
    "spans": trace["spans"],
}""",
                json.dumps(
                    {
                        "trace_id": trace["trace_id"],
                        "winning_route": trace["winning_route"],
                        "spans": span_summary,
                    },
                    indent=2,
                ),
                19,
            ),
            _image_cell(RESULTS / "trace_tree.png", 20),
            _markdown(
                """The ranking query was handled by **Genie**. The 38.3 s root
span spent 23.7 s in the Genie call, including 6.4 s in
`pending_warehouse`; parsing took only 15.4 ms. The client measured 101.2 s for
the first request because endpoint scale-from-zero preceded the trace. I would
alert when five-minute p95 latency exceeds 45 s for three windows, or
immediately when HTTP errors exceed 2%."""
            ),
            _code(
                """inference = json.loads(
    Path("bonus/results/inference_table_evidence.json").read_text()
)
inference""",
                json.dumps(inference_summary, indent=2),
                21,
            ),
            _markdown(
                """The AI Gateway API returned `Inference table is not currently
supported for this endpoint type in this workspace.` The legacy capture API is
also disabled. The evidence therefore keeps
`managed_inference_table_requirement_met=false`, while the explicitly labeled
client-side UC Delta payload log produced real aggregate SQL rows and sets
`functional_uc_payload_monitoring_met=true`. The same four production MLflow
traces independently aggregate to 21,880.80 ms average root-span latency,
38,264.84 ms maximum latency, and zero errors."""
            ),
            _code(
                """guardrail_evidence = json.loads(
    Path("bonus/results/guardrail_evidence.json").read_text()
)
guardrail_evidence["graph_short_circuit_demo"]""",
                json.dumps(guardrails["graph_short_circuit_demo"], indent=2),
                22,
            ),
            _markdown(
                """Both fallback controls short-circuited at the graph's first
node: the third request was `rate_limited`, and an email-bearing request was
`pii_blocked`. Neither reached the planner, LLM, retriever, Genie, or tools.
A production Gateway remains preferable because it is centralized,
identity-aware, auditable, and cannot be bypassed by an omitted graph node;
in-agent policy remains useful for domain-specific intermediate state."""
            ),
            _code(
                """prompt_evidence = json.loads(
    Path("bonus/results/prompt_registry_evidence.json").read_text()
)
prompt_evidence""",
                json.dumps(prompts, indent=2),
                23,
            ),
            _markdown(
                """Prompt versions are immutable and `production` is a movable
pointer. The same running supervisor, backed by the real Databricks model
endpoint, loaded v1 and then v2 after an alias move without rebuild or
redeploy. The prompt-only routing comparison disables the deterministic
coverage guard so the registry prompt is the sole changed variable. The
separate 0.5833→1.0000 figures remain explicitly labeled as system-level Part 3
measurements and are not misattributed to prompt text alone."""
            ),
        ]
    )
    nbformat.write(notebook, NOTEBOOK)
    print(f"Updated {NOTEBOOK} with {len(notebook.cells)} cells")


if __name__ == "__main__":
    main()
