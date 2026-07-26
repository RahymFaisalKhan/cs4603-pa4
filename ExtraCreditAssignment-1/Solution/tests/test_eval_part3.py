"""Offline validation for Extra-Credit Assignment 1 Part 3."""

from __future__ import annotations

from pathlib import Path

from eval.compare_results import metric_deltas, worst_examples
from eval.run_eval import (
    REQUIRED_CATEGORIES,
    CachedPredictor,
    EndpointPredictor,
    _answer_from_response,
    _evidence_documents,
    _prediction_from_response,
    configure_databricks_auth,
    load_dataset,
    to_mlflow_dataset,
)

ROOT = Path(__file__).resolve().parents[1]


def test_eval_dataset_meets_assignment_coverage():
    examples = load_dataset(ROOT / "eval" / "eval_dataset.jsonl")
    assert len(examples) >= 10
    assert {example["category"] for example in examples} >= REQUIRED_CATEGORIES
    assert any(example["category"] == "not_in_document" for example in examples)


def test_mlflow_dataset_preserves_expectations():
    examples = load_dataset(ROOT / "eval" / "eval_dataset.jsonl")
    dataset = to_mlflow_dataset(examples)
    assert len(dataset) == len(examples)
    assert set(dataset[0]) == {"inputs", "expectations"}
    assert dataset[0]["inputs"]["request"] == examples[0]["request"]
    assert dataset[0]["expectations"] == {
        "expected_response": examples[0]["expected_response"]
    }


def test_endpoint_response_exposes_answer_and_evidence():
    response = {
        "messages": [{"role": "assistant", "content": "Automobile was first."}],
        "custom_outputs": {
            "route_history": ["genie"],
            "step_results": ["Structured result: Automobile | 12900000000000"],
        },
    }
    assert _answer_from_response(response) == "Automobile was first."
    documents = _evidence_documents(response)
    assert documents[0]["metadata"]["route"] == "genie"
    assert "Automobile" in documents[0]["page_content"]
    assert _prediction_from_response({"predictions": [response]}) == response
    assert _prediction_from_response({"predictions": response}) == response


def test_comparison_calculates_deltas_and_ranks_failures():
    assert metric_deltas({"correctness": 0.5}, {"correctness": 0.75}) == [
        {
            "metric": "correctness",
            "before": 0.5,
            "after": 0.75,
            "delta": 0.25,
        }
    ]
    frame = __import__("pandas").DataFrame(
        {
            "inputs/request": ["good", "bad"],
            "correctness/value": ["yes", "no"],
            "relevance_to_query/value": ["yes", "yes"],
        }
    )
    assert worst_examples(frame)[0]["request"] == "bad"


def test_cli_oauth_bridge_sets_only_process_environment(monkeypatch, tmp_path):
    config = tmp_path / ".databrickscfg"
    config.write_text(
        "[test-profile]\nhost = https://workspace.example\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    class Completed:
        stdout = '{"access_token":"short-lived-token"}'

    monkeypatch.setattr("eval.run_eval.subprocess.run", lambda *args, **kwargs: Completed())
    host, token = configure_databricks_auth("test-profile")
    assert host == "https://workspace.example"
    assert token == "short-lived-token"


def test_cached_predictor_requires_matching_request(tmp_path):
    cache = tmp_path / "predictions.json"
    cache.write_text(
        '[{"request":"question","response":"answer","evidence":[]}]',
        encoding="utf-8",
    )
    predictor = CachedPredictor(cache)
    assert predictor.by_request["question"]["response"] == "answer"


def test_endpoint_predictor_can_disable_tracing():
    predictor = EndpointPredictor.__new__(EndpointPredictor)
    predictor.trace_evidence = False
    assert predictor.trace_evidence is False
