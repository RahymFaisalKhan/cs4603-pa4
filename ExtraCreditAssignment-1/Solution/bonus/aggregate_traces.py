"""Aggregate the four production MLflow traces when inference tables are unavailable."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import mlflow

from bonus.trace_and_monitor import EXPERIMENT_ID, TRAFFIC
from eval.run_eval import configure_databricks_auth

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "bonus" / "results" / "trace_aggregate_evidence.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="rahym-ec1")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_databricks_auth(args.profile)
    mlflow.set_tracking_uri("databricks")
    traces = mlflow.search_traces(
        experiment_ids=[EXPERIMENT_ID],
        max_results=100,
        return_type="list",
        include_spans=True,
    )

    selected = {}
    for trace in traces:
        serialized = json.dumps(trace.to_dict(), default=str)
        question = next((item for item in TRAFFIC if item in serialized), None)
        if question is None or question in selected:
            continue
        root = next(
            (span for span in trace.data.spans if not span.parent_id),
            None,
        )
        if root is None:
            continue
        duration_ms = (root.end_time_ns - root.start_time_ns) / 1_000_000
        selected[question] = {
            "trace_id": trace.info.trace_id,
            "duration_ms": round(duration_ms, 2),
            "status": str(root.status.status_code),
        }

    rows = [
        {"question": question, **selected[question]}
        for question in TRAFFIC
        if question in selected
    ]
    durations = [row["duration_ms"] for row in rows]
    aggregate = {
        "source": "MLflow production traces",
        "reason": "Workspace rejected inference tables for this agent endpoint type.",
        "experiment_id": EXPERIMENT_ID,
        "n_requests": len(rows),
        "avg_latency_ms": (
            round(sum(durations) / len(durations), 2) if durations else None
        ),
        "max_latency_ms": max(durations) if durations else None,
        "error_count": sum("OK" not in row["status"] for row in rows),
        "requests": rows,
    }
    OUTPUT.write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(aggregate, indent=2))


if __name__ == "__main__":
    main()
