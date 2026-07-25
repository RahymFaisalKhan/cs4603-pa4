"""Agent Framework-compatible wrapper used by Bonus B.

The manual Part 2 endpoint intentionally exposes the graph's full typed state.
Current versions of ``databricks-agents`` require a standardized ChatAgent
request/response signature, so this thin models-from-code wrapper keeps the
same graph while exposing only the final assistant message.
"""

from __future__ import annotations

import os
from uuid import uuid4

import mlflow
from mlflow.pyfunc import ChatAgent
from mlflow.types.agent import ChatAgentMessage, ChatAgentResponse

from agent.graph import build_graph, load_mcp_tools
from config import get_chat_llm
from rag.store import get_retriever

REQUIRED = (
    "DATABRICKS_HOST",
    "DATABRICKS_TOKEN",
    "DATABRICKS_MODEL",
    "VECTOR_SEARCH_ENDPOINT",
    "VECTOR_SEARCH_INDEX",
)
missing = [name for name in REQUIRED if not os.environ.get(name)]
if missing:
    raise OSError(f"Agent startup is missing environment variables: {', '.join(missing)}")


class DocumentAnalystChatAgent(ChatAgent):
    def __init__(self) -> None:
        self.graph = build_graph(
            llm=get_chat_llm(),
            retriever=get_retriever(),
            tools=load_mcp_tools(),
        )

    @mlflow.trace(name="document_analyst_chat", span_type="AGENT")
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
        answer = result["final_answer"]
        return ChatAgentResponse(
            messages=[
                ChatAgentMessage(
                    role="assistant",
                    content=answer,
                    id=str(uuid4()),
                )
            ],
            finish_reason="stop",
            custom_outputs={
                "plan": result.get("plan", []),
                "step_results": result.get("step_results", []),
            },
        )


mlflow.models.set_model(DocumentAnalystChatAgent())
