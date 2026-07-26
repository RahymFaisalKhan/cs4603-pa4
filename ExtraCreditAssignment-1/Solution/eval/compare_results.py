"""Create a compact before/after delta report from exported MLflow results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = ROOT / "eval" / "results"


def _load_metrics(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        key: float(value)
        for key, value in payload["metrics"].items()
        if isinstance(value, (int, float))
    }


def metric_deltas(before: dict[str, float], after: dict[str, float]) -> list[dict[str, Any]]:
    return [
        {
            "metric": metric,
            "before": before[metric],
            "after": after[metric],
            "delta": after[metric] - before[metric],
        }
        for metric in sorted(before.keys() & after.keys())
    ]


def _as_score(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and not pd.isna(value):
        return float(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"yes", "true", "pass", "passed"}:
            return 1.0
        if normalized in {"no", "false", "fail", "failed"}:
            return 0.0
    return None


def worst_examples(frame: pd.DataFrame) -> list[dict[str, Any]]:
    value_columns = [
        column
        for column in frame.columns
        if column.endswith("/value")
        and any(
            name in column
            for name in (
                "correctness",
                "relevance_to_query",
                "retrieval_groundedness",
                "retrieval_relevance",
            )
        )
    ]
    request_column = next(
        (
            column
            for column in ("inputs/request", "request", "inputs")
            if column in frame.columns
        ),
        None,
    )
    ranked = []
    for index, row in frame.iterrows():
        scores = [
            score
            for column in value_columns
            if (score := _as_score(row[column])) is not None
        ]
        if not scores:
            continue
        ranked.append(
            {
                "row": int(index),
                "request": str(row[request_column]) if request_column else "",
                "mean_judge_score": sum(scores) / len(scores),
                "scores": {
                    column: _as_score(row[column])
                    for column in value_columns
                    if _as_score(row[column]) is not None
                },
            }
        )
    return sorted(ranked, key=lambda item: item["mean_judge_score"])[:3]


def _markdown(deltas: list[dict[str, Any]], worst: list[dict[str, Any]]) -> str:
    lines = [
        "# Part 3 before/after comparison",
        "",
        "| Metric | Before | After | Delta |",
        "|---|---:|---:|---:|",
    ]
    lines.extend(
        f"| `{row['metric']}` | {row['before']:.4f} | {row['after']:.4f} | "
        f"{row['delta']:+.4f} |"
        for row in deltas
    )
    lines.extend(["", "## Lowest-scoring baseline examples", ""])
    for row in worst:
        label = row["request"] or f"row {row['row']}"
        lines.append(f"- {row['mean_judge_score']:.3f} — {label}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    before = _load_metrics(args.results_dir / "before" / "metrics.json")
    after = _load_metrics(args.results_dir / "after" / "metrics.json")
    baseline = pd.read_csv(args.results_dir / "before" / "per_example.csv")
    deltas = metric_deltas(before, after)
    worst = worst_examples(baseline)
    payload = {"metrics": deltas, "worst_baseline_examples": worst}
    (args.results_dir / "comparison.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.results_dir / "comparison.md").write_text(
        _markdown(deltas, worst),
        encoding="utf-8",
    )
    print(_markdown(deltas, worst))


if __name__ == "__main__":
    main()
