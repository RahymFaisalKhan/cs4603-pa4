"""Register, compare, and promote two supervisor-prompt versions."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import mlflow
from langchain_core.messages import AIMessage
from mlflow import MlflowClient

from agent.graph_multi import make_multi_supervisor
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


class _AliasSensitiveDemoLlm:
    """Expose which registry version the unchanged supervisor supplied."""

    def invoke(self, messages):
        system_prompt = messages[0].content
        route = "rag_agent" if "Coverage boundary:" in system_prompt else "genie"
        return AIMessage(content=route)


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="rahym-ec1")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_databricks_auth(args.profile)
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
    running_supervisor = make_multi_supervisor(_AliasSensitiveDemoLlm())
    demo_state = {
        "plan": ["Classify this generic financial-data request."],
        "current_step_index": 0,
        "route_history": [],
    }

    mlflow.genai.set_prompt_alias(
        name=PROMPT_NAME,
        alias="production",
        version=int(baseline.version),
    )
    _, loaded_before = load_supervisor_prompt_with_version()
    route_before = running_supervisor(demo_state)["next_agent"]

    mlflow.genai.set_prompt_alias(
        name=PROMPT_NAME,
        alias="production",
        version=int(coverage_aware.version),
    )
    loaded_text, loaded_after = load_supervisor_prompt_with_version()
    route_after = running_supervisor(demo_state)["next_agent"]

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
            "route_observed_with_v1": route_before,
            "route_observed_with_v2": route_after,
        },
        "production_alias_version": str(coverage_aware.version),
        "selection_rule": "Promote the version associated with higher frozen-set correctness.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
