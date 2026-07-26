"""Run the Part 3 judged evaluation against the deployed multi-source agent.

MLflow 3 uses ``mlflow.genai.evaluate`` for the same Agent Evaluation workflow
that older course examples invoke through ``mlflow.evaluate`` with
``model_type="databricks-agent"``.  This harness uses the current API and its
built-in correctness, groundedness, answer-relevance, and chunk-relevance
judges.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import mlflow
import pandas as pd
from databricks.sdk import WorkspaceClient
from mlflow.entities import SpanType
from mlflow.genai.scorers import (
    Correctness,
    RelevanceToQuery,
    RetrievalGroundedness,
    RetrievalRelevance,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "eval" / "eval_dataset.jsonl"
DEFAULT_ENDPOINT = "agents_cs4603-pa4-pa4_document_analyst"
REQUIRED_CATEGORIES = {
    "retrieval",
    "calculation",
    "structured",
    "multi_hop",
    "not_in_document",
}


def configure_databricks_auth(profile: str) -> tuple[str, str]:
    """Bridge the CLI's keychain OAuth profile into SDK/MLflow process memory."""
    config = configparser.ConfigParser()
    config_path = Path.home() / ".databrickscfg"
    if not config.read(config_path) or profile not in config:
        raise OSError(f"Databricks profile {profile!r} is not defined in {config_path}")
    host = config[profile].get("host", "").rstrip("/")
    if not host:
        raise OSError(f"Databricks profile {profile!r} has no host")
    token_process = subprocess.run(
        ["databricks", "auth", "token", "--profile", profile, "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    token = json.loads(token_process.stdout).get("access_token", "")
    if not token:
        raise OSError(f"Databricks profile {profile!r} returned no access token")

    # The OAuth token stays only in this process. Explicit PAT-style SDK auth
    # avoids a keychain subprocess from every MLflow evaluation worker.
    os.environ["DATABRICKS_HOST"] = host
    os.environ["DATABRICKS_TOKEN"] = token
    os.environ["DATABRICKS_AUTH_TYPE"] = "pat"
    os.environ.pop("DATABRICKS_CONFIG_PROFILE", None)
    return host, token


def load_dataset(path: Path) -> list[dict[str, Any]]:
    """Read and validate the source-controlled JSONL evaluation set."""
    examples: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                example = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
            missing = {
                "id",
                "category",
                "request",
                "expected_response",
                "expected_facts",
            } - example.keys()
            if missing:
                raise ValueError(f"{path}:{line_number}: missing {sorted(missing)}")
            if not isinstance(example["expected_facts"], list):
                raise ValueError(f"{path}:{line_number}: expected_facts must be a list")
            examples.append(example)

    if len(examples) < 10:
        raise ValueError("Part 3 requires at least 10 evaluation examples")
    ids = [example["id"] for example in examples]
    if len(ids) != len(set(ids)):
        raise ValueError("Evaluation example ids must be unique")
    categories = {example["category"] for example in examples}
    if missing_categories := REQUIRED_CATEGORIES - categories:
        raise ValueError(f"Missing required categories: {sorted(missing_categories)}")
    return examples


def to_mlflow_dataset(examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert JSONL rows to MLflow GenAI's inputs/expectations schema."""
    return [
        {
            "inputs": {"request": example["request"]},
            "expectations": {
                "expected_response": example["expected_response"],
            },
        }
        for example in examples
    ]


def _answer_from_response(response: dict[str, Any]) -> str:
    messages = response.get("messages") or []
    if messages:
        content = messages[-1].get("content")
        if content:
            return str(content)
    choices = response.get("choices") or []
    if choices:
        content = (choices[-1].get("message") or {}).get("content")
        if content:
            return str(content)
    raise RuntimeError(f"Endpoint response has no assistant message: {response}")


def _prediction_from_response(response: dict[str, Any]) -> dict[str, Any]:
    """Unwrap the pyfunc scoring envelope used by deployed ChatAgents."""
    predictions = response.get("predictions")
    if isinstance(predictions, dict):
        return predictions
    if isinstance(predictions, list) and predictions:
        prediction = predictions[0]
        if isinstance(prediction, dict):
            return prediction
    return response


def _evidence_documents(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose the agent's retrieved/structured evidence to MLflow's RAG judges."""
    custom_outputs = response.get("custom_outputs") or {}
    step_results = custom_outputs.get("step_results") or []
    routes = custom_outputs.get("route_history") or []
    documents = []
    for index, content in enumerate(step_results):
        route = routes[index] if index < len(routes) else "unknown"
        documents.append(
            {
                "page_content": str(content),
                "metadata": {
                    "doc_uri": f"meridian://agent-evidence/{route}/{index + 1}",
                    "route": route,
                },
            }
        )
    if not documents:
        documents.append(
            {
                "page_content": "No supporting evidence was returned by the agent.",
                "metadata": {"doc_uri": "meridian://agent-evidence/missing"},
            }
        )
    return documents


@dataclass
class EndpointPredictor:
    """Callable endpoint adapter that also creates judge-compatible retrieval spans."""

    endpoint_name: str
    profile: str
    trace_evidence: bool = True
    records: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        host = os.environ.get("DATABRICKS_HOST")
        token = os.environ.get("DATABRICKS_TOKEN")
        if not host or not token:
            host, token = configure_databricks_auth(self.profile)
        self.client = WorkspaceClient(host=host, token=token)

    def __call__(self, request: str) -> str:
        invocation_error = ""
        try:
            response = self.client.api_client.do(
                "POST",
                f"/serving-endpoints/{self.endpoint_name}/invocations",
                body={
                    "dataframe_records": [
                        {"messages": [{"role": "user", "content": request}]}
                    ]
                },
            )
            if not isinstance(response, dict):
                raise TypeError(
                    f"Expected a JSON object from endpoint, got {type(response)}"
                )
            prediction = _prediction_from_response(response)
            answer = _answer_from_response(prediction)
        except Exception as exc:
            # A failed served prediction is itself an evaluation result. Keep
            # it in the table rather than allowing MLflow 3.14's harness to
            # abort when it encounters a prediction without a trace.
            invocation_error = f"{type(exc).__name__}: {str(exc)[:500]}"
            answer = (
                "The agent invocation failed and produced no answer. "
                f"Error type: {type(exc).__name__}."
            )
            prediction = {
                "custom_outputs": {
                    "route_history": ["invocation_error"],
                    "step_results": [
                        "No supporting evidence was returned because the invocation failed."
                    ],
                    "invocation_error": invocation_error,
                }
            }
        evidence = _evidence_documents(prediction)

        # mlflow.genai.evaluate creates the root prediction trace. This child
        # RETRIEVER span lets the built-in groundedness and chunk-relevance
        # judges inspect the exact evidence used by the final synthesizer.
        if self.trace_evidence:
            with mlflow.start_span(
                name="agent_evidence",
                span_type=SpanType.RETRIEVER,
            ) as span:
                span.set_inputs({"request": request})
                span.set_outputs(evidence)

        with self._lock:
            self.records.append(
                {
                    "request": request,
                    "response": answer,
                    "custom_outputs": prediction.get("custom_outputs") or {},
                    "evidence": evidence,
                    "invocation_error": invocation_error or None,
                }
            )
        return answer


@dataclass
class CachedPredictor:
    """Replay captured endpoint outputs while creating fresh evaluation traces."""

    cache_path: Path
    records: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.by_request = {record["request"]: record for record in cached}

    def __call__(self, request: str) -> str:
        if request not in self.by_request:
            raise KeyError(f"No cached prediction for {request!r}")
        record = self.by_request[request]
        evidence = record["evidence"]
        with mlflow.start_span(
            name="agent_evidence",
            span_type=SpanType.RETRIEVER,
        ) as span:
            span.set_inputs({"request": request})
            span.set_outputs(evidence)
        self.records.append(record)
        return record["response"]


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if pd.isna(value):
        return None
    return str(value)


def export_results(
    *,
    result,
    predictor: EndpointPredictor,
    output_dir: Path,
    label: str,
    endpoint: str,
    dataset: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_requests = [
        example["request"]
        for example in load_dataset(dataset)
    ]
    records_by_request = {
        record["request"]: record
        for record in predictor.records
    }
    ordered_records = [
        records_by_request[request]
        for request in dataset_requests
        if request in records_by_request
    ]
    metrics = {
        "label": label,
        "endpoint": endpoint,
        "dataset": str(dataset),
        "mlflow_run_id": result.run_id,
        "metrics": result.metrics,
    }
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    (output_dir / "predictions.json").write_text(
        json.dumps(ordered_records, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    if result.result_df is not None:
        result.result_df.to_csv(output_dir / "per_example.csv", index=False)
        (output_dir / "per_example.json").write_text(
            result.result_df.to_json(orient="records", indent=2) + "\n",
            encoding="utf-8",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--profile", default="rahym-ec1")
    parser.add_argument("--label", choices=("before", "after"), required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Defaults to eval/results/<label>.",
    )
    parser.add_argument(
        "--experiment",
        default="/Shared/cs4603-extra-credit-1",
    )
    parser.add_argument(
        "--predictions-cache",
        type=Path,
        help="Replay an existing predictions.json while re-running judges.",
    )
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Checkpoint served predictions without running MLflow judges.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and summarize the dataset without calling Databricks.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    examples = load_dataset(args.dataset)
    category_counts = pd.Series(
        [example["category"] for example in examples]
    ).value_counts()
    print(f"Validated {len(examples)} examples")
    print(category_counts.to_string())
    if args.dry_run:
        return

    configure_databricks_auth(args.profile)
    output_dir = args.output_dir or ROOT / "eval" / "results" / args.label
    if args.collect_only:
        output_dir.mkdir(parents=True, exist_ok=True)
        predictor = EndpointPredictor(
            args.endpoint,
            args.profile,
            trace_evidence=False,
        )
        for index, example in enumerate(examples, start=1):
            predictor(example["request"])
            (output_dir / "predictions.json").write_text(
                json.dumps(
                    predictor.records,
                    indent=2,
                    default=_json_default,
                )
                + "\n",
                encoding="utf-8",
            )
            print(f"Collected {index}/{len(examples)}: {example['id']}")
        print(f"Checkpointed: {output_dir / 'predictions.json'}")
        return

    os.environ.setdefault("MLFLOW_GENAI_EVAL_SKIP_TRACE_VALIDATION", "true")
    os.environ.setdefault("MLFLOW_GENAI_EVAL_MAX_WORKERS", "1")
    os.environ.setdefault("MLFLOW_GENAI_EVAL_PREDICT_RATE_LIMIT", "1")
    os.environ.setdefault("MLFLOW_GENAI_EVAL_SCORER_RATE_LIMIT", "1")
    mlflow.set_tracking_uri("databricks")
    mlflow.set_experiment(args.experiment)
    predictor = (
        CachedPredictor(args.predictions_cache)
        if args.predictions_cache
        else EndpointPredictor(args.endpoint, args.profile)
    )
    scorers = [
        Correctness(aggregations=["mean"]),
        RelevanceToQuery(aggregations=["mean"]),
        RetrievalGroundedness(aggregations=["mean"]),
        RetrievalRelevance(aggregations=["mean"]),
    ]
    with mlflow.start_run(run_name=f"part-3-agent-eval-{args.label}"):
        result = mlflow.genai.evaluate(
            data=to_mlflow_dataset(examples),
            predict_fn=predictor,
            scorers=scorers,
        )

    export_results(
        result=result,
        predictor=predictor,
        output_dir=output_dir,
        label=args.label,
        endpoint=args.endpoint,
        dataset=args.dataset,
    )
    print(json.dumps(result.metrics, indent=2, default=_json_default))
    print(f"Run: {result.run_id}")
    print(f"Exported: {output_dir}")


if __name__ == "__main__":
    main()
