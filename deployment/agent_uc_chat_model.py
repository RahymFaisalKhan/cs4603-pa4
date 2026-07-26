"""Agent Framework model that uses governed UC Functions and automatic auth."""

from __future__ import annotations

import os
from uuid import uuid4

import mlflow
from databricks_langchain import ChatDatabricks, DatabricksVectorSearch
from mlflow.pyfunc import ChatAgent
from mlflow.types.agent import ChatAgentMessage, ChatAgentResponse
from unitycatalog.ai.core.databricks import DatabricksFunctionClient

from agent.graph_uc import build_graph_uc, load_uc_tools
from uc_tools import function_names

CITATION_COLUMNS = ["chunk_id", "chunk_to_retrieve", "source", "page"]

REQUIRED = (
    "DATABRICKS_MODEL",
    "VECTOR_SEARCH_INDEX",
    "UC_CATALOG",
    "UC_SCHEMA",
)
missing = [name for name in REQUIRED if not os.environ.get(name)]
if missing:
    raise OSError("UC agent startup is missing environment variables: " + ", ".join(missing))


def _build_automatically_authorized_graph():
    """Build clients that use credentials injected from declared MLflow resources."""
    llm = ChatDatabricks(
        endpoint=os.environ["DATABRICKS_MODEL"],
        temperature=0.0,
    )
    vector_store = DatabricksVectorSearch(
        index_name=os.environ["VECTOR_SEARCH_INDEX"],
        columns=CITATION_COLUMNS,
    )
    function_client = DatabricksFunctionClient()
    tools = load_uc_tools(
        function_names=function_names(),
        client=function_client,
    )
    return build_graph_uc(
        llm=llm,
        retriever=vector_store.as_retriever(search_kwargs={"k": 4}),
        tools=tools,
    )


class GovernedDocumentAnalyst(ChatAgent):
    """Expose the UC-backed graph through the standardized ChatAgent contract."""

    def __init__(self) -> None:
        self.graph = _build_automatically_authorized_graph()

    @mlflow.trace(name="governed_document_analyst", span_type="AGENT")
    def predict(
        self,
        messages: list[ChatAgentMessage],
        context=None,
        custom_inputs=None,
    ) -> ChatAgentResponse:
        graph_messages = [
            {
                "role": message.role,
                "content": message.content or "",
            }
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
                "tool_backend": "unity_catalog_functions",
            },
        )


mlflow.models.set_model(GovernedDocumentAnalyst())
