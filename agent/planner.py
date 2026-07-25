"""Robust JSON planner node (Task 1.2)."""

from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from agent.prompts import PLANNER_PROMPT
from agent.state import AnalystState


def _text(message) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content)
    return str(content)


def _parse_plan(raw: str, fallback: str) -> list[str]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            value = value.get("steps") or value.get("plan")
        if isinstance(value, list):
            steps = [str(item).strip() for item in value if str(item).strip()]
            if steps:
                return steps[:5]
    except (json.JSONDecodeError, TypeError):
        pass
    return [fallback]


def make_planner(llm):
    def planner(state: AnalystState) -> dict:
        messages = state.get("messages", [])
        question = _text(messages[-1]) if messages else ""
        response = llm.invoke([SystemMessage(content=PLANNER_PROMPT), HumanMessage(content=question)])
        return {
            "plan": _parse_plan(_text(response), question),
            "current_step_index": 0,
            "step_results": [],
        }

    return planner
