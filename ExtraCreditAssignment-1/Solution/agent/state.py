"""Typed state schema for the Document Analyst graph (Task 1.1)."""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AnalystState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    plan: list[str]
    current_step_index: int
    step_results: list[str]
    next_agent: str
    route_history: list[str]
    genie_conversation_id: str
    user_id: str
    guardrail_reason: str
    final_answer: str
