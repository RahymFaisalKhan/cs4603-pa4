"""Bonus B deployment through the databricks-agents SDK."""

from __future__ import annotations

import os
from pathlib import Path

import mlflow
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value or "<" in value:
        raise OSError(f"Set {name} in .env before deployment")
    return value


def log_and_register_chat_agent() -> tuple[str, str]:
    """Log the same graph behind MLflow's standardized ChatAgent signature."""
    catalog = _require("UC_CATALOG")
    schema = _require("UC_SCHEMA")
    endpoint = _require("SERVING_ENDPOINT_NAME")
    model_name = os.environ.get("REGISTERED_MODEL_NAME", endpoint.replace("-", "_"))
    uc_name = f"{catalog}.{schema}.{model_name}"

    mlflow.set_tracking_uri("databricks")
    mlflow.set_registry_uri("databricks-uc")
    mlflow.set_experiment(os.environ.get("MLFLOW_EXPERIMENT", "/Shared/cs4603-pa4"))
    mcp_server_url = os.environ.pop("MCP_SERVER_URL", None)
    try:
        with mlflow.start_run():
            info = mlflow.pyfunc.log_model(
                python_model=str(ROOT / "deployment" / "agent_chat_model.py"),
                name="chat_agent",
                code_paths=[
                    str(ROOT / "agent"),
                    str(ROOT / "rag"),
                    str(ROOT / "tools"),
                    str(ROOT / "config.py"),
                ],
                pip_requirements=[
                    "mlflow>=3.0.0",
                    "langgraph>=0.2.0",
                    "langchain>=0.3.0",
                    "langchain-core>=0.3.0",
                    "langchain-openai>=0.2.0",
                    "databricks-langchain>=0.1.0",
                    "databricks-vectorsearch>=0.40",
                    "mcp>=1.0.0",
                    "langchain-mcp-adapters>=0.0.5",
                    "httpx>=0.27.0",
                    "python-dotenv>=1.0.0",
                ],
            )
    finally:
        if mcp_server_url is not None:
            os.environ["MCP_SERVER_URL"] = mcp_server_url
    registered = mlflow.register_model(info.model_uri, uc_name)
    print(f"Registered Agent Framework model {uc_name} version {registered.version}")
    return uc_name, str(registered.version)


def main() -> None:
    from databricks import agents

    name, version = log_and_register_chat_agent()
    scope = _require("SECRET_SCOPE")
    environment_vars = {
        "DATABRICKS_HOST": f"{{{{secrets/{scope}/DATABRICKS_HOST}}}}",
        "DATABRICKS_TOKEN": f"{{{{secrets/{scope}/DATABRICKS_TOKEN}}}}",
        "DATABRICKS_MODEL": f"{{{{secrets/{scope}/DATABRICKS_MODEL}}}}",
        "VECTOR_SEARCH_ENDPOINT": _require("VECTOR_SEARCH_ENDPOINT"),
        "VECTOR_SEARCH_INDEX": _require("VECTOR_SEARCH_INDEX"),
        "EMBEDDINGS_ENDPOINT": os.environ.get(
            "EMBEDDINGS_ENDPOINT", "databricks-gte-large-en"
        ),
    }
    if mcp_server_url := os.environ.get("MCP_SERVER_URL", "").strip():
        environment_vars["MCP_SERVER_URL"] = mcp_server_url.rstrip("/")
        environment_vars["MCP_CLIENT_ID"] = (
            f"{{{{secrets/{scope}/MCP_CLIENT_ID}}}}"
        )
        environment_vars["MCP_CLIENT_SECRET"] = (
            f"{{{{secrets/{scope}/MCP_CLIENT_SECRET}}}}"
        )
    deployed = agents.deploy(
        model_name=name,
        model_version=version,
        scale_to_zero=True,
        environment_vars=environment_vars,
    )
    print(f"Endpoint: {deployed.endpoint_name}")
    print(f"Review app: {deployed.review_app_url}")


if __name__ == "__main__":
    main()
