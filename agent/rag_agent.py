"""Cited RAG agent backed by Databricks Vector Search (Task 1.4)."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from agent.prompts import RAG_EXTRACT_PROMPT
from agent.state import AnalystState


def format_docs(docs) -> str:
    formatted = []
    for doc in docs:
        metadata = getattr(doc, "metadata", {}) or {}
        source = metadata.get("source", "unknown")
        page = metadata.get("page", "?")
        # ai_prep_search deliberately separates embedding text from the richer
        # text intended for generation. Prefer that retrieval text when the
        # Vector Search adapter returns it as metadata.
        content = metadata.get(
            "chunk_to_retrieve", getattr(doc, "page_content", str(doc))
        )
        formatted.append(f"{content}\n[source: {source}, p.{page}]")
    return "\n\n".join(formatted)


def make_rag_agent(retriever, llm):
    def rag_agent(state: AnalystState) -> dict:
        index = state.get("current_step_index", 0)
        step = state["plan"][index]
        docs = retriever.invoke(step)
        if not docs:
            result = "not found in documents"
        else:
            context = format_docs(docs)
            response = llm.invoke(
                [
                    SystemMessage(content=RAG_EXTRACT_PROMPT),
                    HumanMessage(content=f"Step: {step}\n\nRetrieved chunks:\n{context}"),
                ]
            )
            result = str(getattr(response, "content", response)).strip()
        return {
            "step_results": [*state.get("step_results", []), result],
            "current_step_index": index + 1,
        }

    return rag_agent
