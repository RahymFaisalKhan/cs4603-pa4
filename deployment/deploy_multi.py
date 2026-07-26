"""Log, register, and deploy the Part 2 RAG/Genie/UC multi-agent."""

from __future__ import annotations

import os
from pathlib import Path

import mlflow
from dotenv import load_dotenv
from mlflow.models.resources import (
    DatabricksFunction,
    DatabricksGenieSpace,
    DatabricksServingEndpoint,
    DatabricksVectorSearchIndex,
)

from uc_tools import function_names

load_dotenv()
ROOT = Path(__file__).resolve().parents[1]


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value or "<" in value:
        raise OSError(f"Set {name} before deploying the Part 2 agent")
    return value


def multi_resources() -> list:
    """Declare all dependencies for automatic authorization."""
    resources = [
        DatabricksServingEndpoint(endpoint_name=_require("DATABRICKS_MODEL")),
        DatabricksVectorSearchIndex(index_name=_require("VECTOR_SEARCH_INDEX")),
        DatabricksGenieSpace(genie_space_id=_require("GENIE_SPACE_ID")),
    ]
    resources.extend(
        DatabricksFunction(function_name=name) for name in function_names()
    )
    return resources


def log_and_register_multi_agent() -> tuple[str, str]:
    catalog = _require("UC_CATALOG")
    schema = _require("UC_SCHEMA")
    endpoint = _require("SERVING_ENDPOINT_NAME")
    base_name = os.environ.get("REGISTERED_MODEL_NAME", endpoint.replace("-", "_"))
    model_name = os.environ.get("MULTI_REGISTERED_MODEL_NAME", f"{base_name}_multi")
    uc_name = f"{catalog}.{schema}.{model_name}"

    mlflow.set_tracking_uri("databricks")
    mlflow.set_registry_uri("databricks-uc")
    mlflow.set_experiment(
        os.environ.get("MLFLOW_EXPERIMENT", "/Shared/cs4603-extra-credit-1")
    )
    with mlflow.start_run(run_name="part-2-genie-multi-agent"):
        info = mlflow.pyfunc.log_model(
            python_model=str(ROOT / "deployment" / "agent_multi_chat_model.py"),
            name="multi_source_chat_agent",
            code_paths=[
                str(ROOT / "agent"),
                str(ROOT / "rag"),
                str(ROOT / "uc_tools"),
                str(ROOT / "genie"),
            ],
            pip_requirements=[
                "mlflow>=3.0.0",
                "langgraph>=0.2.0",
                "langchain>=0.3.0",
                "langchain-core>=0.3.0",
                "databricks-sdk>=0.23.0",
                "databricks-langchain>=0.1.0",
                "databricks-vectorsearch>=0.40",
                "databricks-connect>=15.1.0",
                "unitycatalog-ai>=0.3.2",
                "unitycatalog-langchain>=0.3.0",
            ],
            resources=multi_resources(),
        )
    registered = mlflow.register_model(info.model_uri, uc_name)
    print(f"Registered Part 2 agent {uc_name} version {registered.version}")
    return uc_name, str(registered.version)


def deploy_multi_agent(model_name: str, model_version: str):
    """Deploy with short-lived credentials for Genie and the Part 1 resources."""
    mlflow.set_tracking_uri("databricks")
    mlflow.set_registry_uri("databricks-uc")
    try:
        from databricks import agents
    except ImportError as exc:
        raise RuntimeError("Install the deployment extra with `uv sync --extra agents`") from exc

    environment_vars = {
        "DATABRICKS_MODEL": _require("DATABRICKS_MODEL"),
        "VECTOR_SEARCH_INDEX": _require("VECTOR_SEARCH_INDEX"),
        "UC_CATALOG": _require("UC_CATALOG"),
        "UC_SCHEMA": _require("UC_SCHEMA"),
        "UC_FUNCTION_NAMES": ",".join(function_names()),
        "GENIE_SPACE_ID": _require("GENIE_SPACE_ID"),
    }
    endpoint_name = os.environ.get("MULTI_AGENT_ENDPOINT_NAME", "").strip() or None
    deployed = agents.deploy(
        model_name=model_name,
        model_version=int(model_version),
        scale_to_zero=True,
        environment_vars=environment_vars,
        endpoint_name=endpoint_name,
    )
    print(f"Endpoint: {deployed.endpoint_name}")
    print(f"Review app: {deployed.review_app_url}")
    return deployed


def main() -> None:
    name, version = log_and_register_multi_agent()
    deploy_multi_agent(name, version)


if __name__ == "__main__":
    main()
