"""Shared Databricks Vector Search retriever factory (Task 1.4)."""

from __future__ import annotations

from config import get_settings

CITATION_COLUMNS = ["chunk_id", "chunk_to_retrieve", "source", "page"]


def get_vector_store():
    from databricks_langchain import DatabricksVectorSearch

    settings = get_settings()
    if not settings["vs_endpoint"] or not settings["vs_index"]:
        raise OSError("VECTOR_SEARCH_ENDPOINT and VECTOR_SEARCH_INDEX must be configured")
    return DatabricksVectorSearch(
        index_name=settings["vs_index"],
        columns=CITATION_COLUMNS,
    )


def get_retriever(k: int = 4):
    if k < 1:
        raise ValueError("k must be at least 1")
    return get_vector_store().as_retriever(search_kwargs={"k": k})
