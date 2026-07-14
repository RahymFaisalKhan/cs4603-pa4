"""Log, register, and serve the Document Analyst (Tasks 2.2 + 2.3)."""

from __future__ import annotations

import os
from pathlib import Path

import mlflow
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from databricks.sdk.service.serving import EndpointCoreConfigInput, ServedEntityInput
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT_SECRET_KEYS = (
    "DATABRICKS_HOST",
    "DATABRICKS_TOKEN",
    "DATABRICKS_MODEL",
)


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value or "<" in value:
        raise OSError(f"Set {name} in .env before deployment")
    return value


def ensure_deployment_secrets(client: WorkspaceClient, scope: str) -> None:
    """Create the deployment scope when needed and refresh required keys.

    Model Serving validates secret references while creating the endpoint, so
    all referenced keys must exist before the endpoint configuration is sent.
    """
    existing_scopes = {item.name for item in client.secrets.list_scopes()}
    if scope not in existing_scopes:
        client.secrets.create_scope(scope=scope)
        print(f"Created secret scope {scope!r}")

    for key in DEPLOYMENT_SECRET_KEYS:
        client.secrets.put_secret(
            scope=scope,
            key=key,
            string_value=_require(key),
        )

    existing_keys = {item.key for item in client.secrets.list_secrets(scope)}
    required_keys = set(DEPLOYMENT_SECRET_KEYS)
    if os.environ.get("MCP_SERVER_URL", "").strip():
        required_keys.update({"MCP_CLIENT_ID", "MCP_CLIENT_SECRET"})
    missing = required_keys - existing_keys
    if missing:
        raise RuntimeError(
            f"Secret scope {scope!r} is missing keys: {sorted(missing)}"
        )
    print(f"Deployment secrets are ready in scope {scope!r}")


def log_and_register():
    catalog = _require("UC_CATALOG")
    schema = _require("UC_SCHEMA")
    endpoint = _require("SERVING_ENDPOINT_NAME")
    model_name = os.environ.get("REGISTERED_MODEL_NAME", endpoint.replace("-", "_"))
    uc_name = f"{catalog}.{schema}.{model_name}"

    mlflow.set_tracking_uri("databricks")
    mlflow.set_registry_uri("databricks-uc")
    mlflow.set_experiment(os.environ.get("MLFLOW_EXPERIMENT", "/Shared/cs4603-pa4"))
    requirements = [
        "mlflow>=2.16.0",
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
    ]
    # Model packaging validates the graph in the CI process, where the serving
    # endpoint's M2M secrets are intentionally unavailable. Package using the
    # stdio fallback, then restore the remote URL for the endpoint configuration.
    mcp_server_url = os.environ.pop("MCP_SERVER_URL", None)
    try:
        with mlflow.start_run():
            info = mlflow.langchain.log_model(
                lc_model=str(ROOT / "deployment" / "agent_model.py"),
                name="agent",
                code_paths=[
                    str(ROOT / "agent"),
                    str(ROOT / "rag"),
                    str(ROOT / "tools"),
                    str(ROOT / "config.py"),
                ],
                pip_requirements=requirements,
                input_example={
                    "messages": [{"role": "user", "content": "What was revenue?"}]
                },
            )
    finally:
        if mcp_server_url is not None:
            os.environ["MCP_SERVER_URL"] = mcp_server_url
    registered = mlflow.register_model(info.model_uri, uc_name)
    print(f"Registered {uc_name} version {registered.version}")
    return uc_name, str(registered.version)


def create_or_update_endpoint(uc_name: str, version: str) -> str:
    endpoint_name = _require("SERVING_ENDPOINT_NAME")
    scope = _require("SECRET_SCOPE")
    host = _require("DATABRICKS_HOST").rstrip("/")
    client = WorkspaceClient()
    ensure_deployment_secrets(client, scope)

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
    # Bonus C: when configured, the graph connects to the independently
    # deployed Databricks App instead of starting the bundled stdio process.
    if mcp_server_url := os.environ.get("MCP_SERVER_URL", "").strip():
        environment_vars["MCP_SERVER_URL"] = mcp_server_url.rstrip("/")
        environment_vars["MCP_CLIENT_ID"] = (
            f"{{{{secrets/{scope}/MCP_CLIENT_ID}}}}"
        )
        environment_vars["MCP_CLIENT_SECRET"] = (
            f"{{{{secrets/{scope}/MCP_CLIENT_SECRET}}}}"
        )

    entity = ServedEntityInput(
        name=f"{endpoint_name}-{version}",
        entity_name=uc_name,
        entity_version=version,
        workload_size="Small",
        scale_to_zero_enabled=True,
        environment_vars=environment_vars,
    )
    try:
        client.serving_endpoints.get(endpoint_name)
    except NotFound:
        client.serving_endpoints.create_and_wait(
            name=endpoint_name,
            config=EndpointCoreConfigInput(name=endpoint_name, served_entities=[entity]),
        )
    else:
        client.serving_endpoints.update_config_and_wait(
            name=endpoint_name, served_entities=[entity]
        )
    url = f"{host}/serving-endpoints/{endpoint_name}/invocations"
    print(f"Endpoint READY: {url}")
    return url


if __name__ == "__main__":
    name, ver = log_and_register()
    create_or_update_endpoint(name, ver)
