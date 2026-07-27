"""Register, compare, and promote two supervisor-prompt versions."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import mlflow
from databricks.sdk import WorkspaceClient
from databricks_langchain import ChatDatabricks
from mlflow import MlflowClient

from agent.graph_multi import GENIE, RAG, make_multi_supervisor
from agent.prompt_registry import load_supervisor_prompt_with_version
from agent.prompts import MULTI_SUPERVISOR_PROMPT
from eval.run_eval import configure_databricks_auth

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "bonus" / "results" / "prompt_registry_evidence.json"
PROMPT_NAME = "cs4603.pa4.meridian_multi_supervisor"

BASELINE_PROMPT = """Classify the current plan step and return exactly one node name.
Return `genie` for structured/table questions: lookups of financial line items, fiscal-year
comparisons, rankings, aggregation, highest/lowest, operating margins, and year-over-year
analysis. Return `rag_agent` for narrative or qualitative annual-report questions such as
risks, strategy, explanations, priorities, or management commentary. Return `uc_tools` only
for a deterministic numeric transform or calculation that should use a governed function.
Do not route arithmetic embedded inside a structured SQL aggregation away from Genie."""

ROUTING_CASES = [
    {
        "id": "retrieval_fy2024_guidance",
        "step": "Retrieve Meridian's FY2024 forecast revenue and operating profit.",
        "expected_route": RAG,
    },
    {
        "id": "retrieval_rnd_priorities",
        "step": "Find the three R&D priorities described by management.",
        "expected_route": RAG,
    },
    {
        "id": "structured_segment_rank",
        "step": "Rank Meridian's FY2023 segments by revenue.",
        "expected_route": GENIE,
    },
    {
        "id": "structured_margin_leader",
        "step": "Query which segment had the highest FY2023 operating margin.",
        "expected_route": GENIE,
    },
    {
        "id": "structured_income_growth",
        "step": "Calculate FY2022-to-FY2023 net-income growth from the income statement.",
        "expected_route": GENIE,
    },
    {
        "id": "retrieval_risk_effect",
        "step": "Explain how a stronger yen affects Meridian according to the risk factors.",
        "expected_route": RAG,
    },
    {
        "id": "not_in_document_ceo_pay",
        "step": "Find the CEO's FY2023 executive compensation in the annual report.",
        "expected_route": RAG,
    },
]


def _ensure_version(name: str, template: str, message: str):
    client = MlflowClient()
    try:
        versions = list(client.search_prompt_versions(name=name, max_results=100))
    except Exception as exc:
        if "does not exist" not in str(exc):
            raise
        versions = []
    existing = next(
        (version for version in versions if version.template == template),
        None,
    )
    return existing or mlflow.genai.register_prompt(
        name=name,
        template=template,
        commit_message=message,
        tags={"assignment": "extra-credit-1", "part": "4"},
    )


def _correctness(metrics_path: Path) -> float:
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    return float(payload["metrics"]["correctness/mean"])


def _evaluate_routes(supervisor) -> dict:
    rows = []
    for case in ROUTING_CASES:
        state = {
            "plan": [case["step"]],
            "current_step_index": 0,
            "route_history": [],
        }
        observed = supervisor(state)["next_agent"]
        rows.append(
            {
                **case,
                "observed_route": observed,
                "correct": observed == case["expected_route"],
            }
        )
    correct = sum(row["correct"] for row in rows)
    return {
        "correct": correct,
        "total": len(rows),
        "accuracy": correct / len(rows),
        "rows": rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="rahym-ec1")
    parser.add_argument(
        "--model-endpoint",
        default=os.environ.get(
            "DATABRICKS_MODEL",
            "databricks-meta-llama-3-3-70b-instruct",
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    host, token = configure_databricks_auth(args.profile)
    mlflow.set_tracking_uri("databricks")
    mlflow.set_registry_uri("databricks-uc")

    baseline = _ensure_version(
        PROMPT_NAME,
        BASELINE_PROMPT,
        "v1: broad table-shaped routing used by the Part 3 baseline",
    )
    coverage_aware = _ensure_version(
        PROMPT_NAME,
        MULTI_SUPERVISOR_PROMPT,
        "v2: encode the curated Genie table-coverage boundary",
    )

    uri = f"prompts:/{PROMPT_NAME}@production"
    os.environ["SUPERVISOR_PROMPT_URI"] = uri
    os.environ["PROMPT_REGISTRY_REQUIRED"] = "true"
    workspace = WorkspaceClient(host=host, token=token)
    routing_llm = ChatDatabricks(
        endpoint=args.model_endpoint,
        temperature=0.0,
        workspace_client=workspace,
    )
    # Disable the deterministic coverage guard only for this controlled
    # experiment so the registry prompt is the sole changing variable.
    running_supervisor = make_multi_supervisor(
        routing_llm,
        coverage_guard=False,
    )

    mlflow.genai.set_prompt_alias(
        name=PROMPT_NAME,
        alias="production",
        version=int(baseline.version),
    )
    _, loaded_before = load_supervisor_prompt_with_version()
    baseline_routing = _evaluate_routes(running_supervisor)

    mlflow.genai.set_prompt_alias(
        name=PROMPT_NAME,
        alias="production",
        version=int(coverage_aware.version),
    )
    loaded_text, loaded_after = load_supervisor_prompt_with_version()
    coverage_routing = _evaluate_routes(running_supervisor)

    if coverage_routing["accuracy"] >= baseline_routing["accuracy"]:
        selected = coverage_aware
        selected_role = "coverage-aware"
    else:
        selected = baseline
        selected_role = "baseline"
    mlflow.genai.set_prompt_alias(
        name=PROMPT_NAME,
        alias="production",
        version=int(selected.version),
    )

    before_score = _correctness(ROOT / "eval" / "results" / "before" / "metrics.json")
    after_score = _correctness(ROOT / "eval" / "results" / "after" / "metrics.json")
    evidence = {
        "prompt_name": PROMPT_NAME,
        "production_uri": uri,
        "versions": [
            {
                "version": str(baseline.version),
                "role": "baseline",
                "part3_system_correctness": before_score,
            },
            {
                "version": str(coverage_aware.version),
                "role": "coverage-aware",
                "part3_system_correctness": after_score,
            },
        ],
        "alias_demo_without_redeploy": {
            "loaded_before_promotion": loaded_before,
            "loaded_after_promotion": loaded_after,
            "coverage_boundary_present": "Coverage boundary:" in loaded_text,
            "same_supervisor_instance": True,
            "real_llm_endpoint": args.model_endpoint,
            "deterministic_coverage_guard_enabled": False,
            "baseline_prompt_routing_eval": baseline_routing,
            "coverage_prompt_routing_eval": coverage_routing,
        },
        "production_alias_version": str(selected.version),
        "production_alias_role": selected_role,
        "selection_rule": (
            "Promote the prompt with higher routing accuracy on route-labeled "
            "cases drawn from the frozen Part 3 dataset; ties favor the "
            "coverage-aware version."
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
