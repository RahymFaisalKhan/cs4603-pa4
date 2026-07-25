"""Self-contained MLflow models-from-code definition (Task 2.1)."""

from __future__ import annotations

import os

import mlflow

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
    raise OSError(f"Model startup is missing environment variables: {', '.join(missing)}")

graph = build_graph(llm=get_chat_llm(), retriever=get_retriever(), tools=load_mcp_tools())
mlflow.models.set_model(graph)
