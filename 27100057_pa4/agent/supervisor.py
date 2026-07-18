"""Supervisor node and conditional routing edge (Task 1.3)."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from agent.prompts import SUPERVISOR_PROMPT
from agent.state import AnalystState

RAG = "rag_agent"
MCP = "mcp_tools"
SYNTH = "synthesizer"


def make_supervisor(llm):
    def supervisor(state: AnalystState) -> dict:
        index = state.get("current_step_index", 0)
        plan = state.get("plan", [])
        if index >= len(plan):
            return {"next_agent": SYNTH}
        response = llm.invoke(
            [SystemMessage(content=SUPERVISOR_PROMPT), HumanMessage(content=plan[index])]
        )
        decision = str(getattr(response, "content", response)).lower()
        return {"next_agent": MCP if MCP in decision else RAG}

    return supervisor


def route_from_supervisor(state: AnalystState) -> str:
    return state["next_agent"]
