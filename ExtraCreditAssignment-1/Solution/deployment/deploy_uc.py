"""Log, register, and deploy the Part 1 UC-function agent."""

from __future__ import annotations

import os
from pathlib import Path

import mlflow
from dotenv import load_dotenv
from mlflow.models.resources import (
    DatabricksFunction,
    DatabricksServingEndpoint,
    DatabricksVectorSearchIndex,
)

from eval.run_eval import configure_databricks_auth
from uc_tools import function_names

load_dotenv()
ROOT = Path(__file__).resolve().parents[1]


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value or "<" in value:
        raise OSError(f"Set {name} before deploying the UC-function agent")
    return value


def uc_resources() -> list:
    """Declare every dependency needed for automatic authorization."""
    resources = [
        DatabricksServingEndpoint(endpoint_name=_require("DATABRICKS_MODEL")),
        DatabricksVectorSearchIndex(index_name=_require("VECTOR_SEARCH_INDEX")),
    ]
    resources.extend(
        DatabricksFunction(function_name=name) for name in function_names()
    )
    return resources


def log_and_register_uc_agent() -> tuple[str, str]:
    """Log models-from-code and register it in Unity Catalog."""
    catalog = _require("UC_CATALOG")
    schema = _require("UC_SCHEMA")
    endpoint = _require("SERVING_ENDPOINT_NAME")
    base_name = os.environ.get("REGISTERED_MODEL_NAME", endpoint.replace("-", "_"))
    model_name = os.environ.get("UC_REGISTERED_MODEL_NAME", f"{base_name}_uc")
    uc_name = f"{catalog}.{schema}.{model_name}"

    mlflow.set_tracking_uri("databricks")
    mlflow.set_registry_uri("databricks-uc")
    mlflow.set_experiment(
        os.environ.get("MLFLOW_EXPERIMENT", "/Shared/cs4603-extra-credit-1")
    )
    with mlflow.start_run(run_name="part-1-uc-function-agent"):
        info = mlflow.pyfunc.log_model(
            python_model=str(ROOT / "deployment" / "agent_uc_chat_model.py"),
            name="uc_function_chat_agent",
            code_paths=[
                str(ROOT / "agent"),
                str(ROOT / "rag"),
                str(ROOT / "uc_tools"),
            ],
            pip_requirements=[
                "mlflow>=3.0.0",
                "langgraph>=0.2.0",
                "langchain>=0.3.0",
                "langchain-core>=0.3.0",
                "databricks-sdk>=0.23.0",
                "databricks-langchain>=0.1.0",
                "databricks-vectorsearch>=0.40",
                "unitycatalog-ai>=0.3.2",
                "unitycatalog-langchain>=0.3.0",
            ],
            resources=uc_resources(),
        )
    registered = mlflow.register_model(info.model_uri, uc_name)
    print(f"Registered Part 1 agent {uc_name} version {registered.version}")
    return uc_name, str(registered.version)


def deploy_uc_agent(model_name: str, model_version: str):
    """Deploy with short-lived credentials for all declared dependencies."""
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
    }
    endpoint_name = os.environ.get("UC_AGENT_ENDPOINT_NAME", "").strip() or None
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
    if profile := os.environ.get("DATABRICKS_PROFILE"):
        configure_databricks_auth(profile)
    name, version = log_and_register_uc_agent()
    deploy_uc_agent(name, version)


if __name__ == "__main__":
    main()
