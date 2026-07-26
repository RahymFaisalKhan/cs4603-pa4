"""Agent Framework model for the Part 2 routed RAG/Genie/UC graph."""

from __future__ import annotations

import os
from uuid import uuid4

import mlflow
from databricks.sdk import WorkspaceClient
from databricks_langchain import ChatDatabricks, DatabricksVectorSearch
from mlflow.pyfunc import ChatAgent
from mlflow.types.agent import ChatAgentMessage, ChatAgentResponse
from unitycatalog.ai.core.databricks import DatabricksFunctionClient

from agent.graph_multi import build_graph_multi, load_genie_agent
from agent.graph_uc import load_uc_tools
from uc_tools import function_names

CITATION_COLUMNS = ["chunk_id", "chunk_to_retrieve", "source", "page"]
REQUIRED = (
    "DATABRICKS_MODEL",
    "VECTOR_SEARCH_INDEX",
    "UC_CATALOG",
    "UC_SCHEMA",
    "GENIE_SPACE_ID",
)
missing = [name for name in REQUIRED if not os.environ.get(name)]
if missing:
    raise OSError("Part 2 agent startup is missing: " + ", ".join(missing))


def _build_automatically_authorized_graph():
    """Build every client from credentials injected for declared resources."""
    workspace_client = WorkspaceClient()
    llm = ChatDatabricks(
        endpoint=os.environ["DATABRICKS_MODEL"],
        temperature=0.0,
        workspace_client=workspace_client,
    )
    vector_kwargs = {"workspace_client": workspace_client}
    if workspace_client.config.auth_type not in {
        "model_serving_user_credentials",
        "pat",
        "oauth-m2m",
    }:
        authorization = workspace_client.config.authenticate().get("Authorization", "")
        access_token = authorization.removeprefix("Bearer ").strip()
        vector_kwargs["client_args"] = {
            "workspace_url": workspace_client.config.host,
            "personal_access_token": access_token,
        }
    vector_store = DatabricksVectorSearch(
        index_name=os.environ["VECTOR_SEARCH_INDEX"],
        columns=CITATION_COLUMNS,
        **vector_kwargs,
    )
    function_client = DatabricksFunctionClient(client=workspace_client)
    tools = load_uc_tools(
        function_names=function_names(),
        client=function_client,
    )
    genie_agent = load_genie_agent(
        genie_space_id=os.environ["GENIE_SPACE_ID"],
        client=workspace_client,
    )
    return build_graph_multi(
        llm=llm,
        retriever=vector_store.as_retriever(search_kwargs={"k": 4}),
        tools=tools,
        genie_agent=genie_agent,
    )


class MultiSourceDocumentAnalyst(ChatAgent):
    """Expose the routed Part 2 graph through the standard ChatAgent contract."""

    def __init__(self) -> None:
        self.graph = _build_automatically_authorized_graph()

    @mlflow.trace(name="multi_source_document_analyst", span_type="AGENT")
    def predict(
        self,
        messages: list[ChatAgentMessage],
        context=None,
        custom_inputs=None,
    ) -> ChatAgentResponse:
        graph_messages = [
            {"role": message.role, "content": message.content or ""}
            for message in messages
            if message.role in {"system", "user", "assistant"}
        ]
        result = self.graph.invoke({"messages": graph_messages})
        return ChatAgentResponse(
            messages=[
                ChatAgentMessage(
                    role="assistant",
                    content=result["final_answer"],
                    id=str(uuid4()),
                )
            ],
            finish_reason="stop",
            custom_outputs={
                "plan": result.get("plan", []),
                "step_results": result.get("step_results", []),
                "route_history": result.get("route_history", []),
                "data_backends": [
                    "vector_search",
                    "genie",
                    "unity_catalog_functions",
                ],
            },
        )


mlflow.models.set_model(MultiSourceDocumentAnalyst())
