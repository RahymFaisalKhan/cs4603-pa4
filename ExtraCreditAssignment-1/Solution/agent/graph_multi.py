"""Part 2 graph routing structured, narrative, and calculation steps."""

from __future__ import annotations

import os
from collections.abc import Callable

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from agent.graph_uc import (
    RAG,
    SYNTH,
    UC_TOOLS,
    _collapse_redundant_growth_steps,
    load_uc_tools,
    make_uc_tools_node,
)
from agent.planner import _parse_plan, _text
from agent.prompt_registry import load_supervisor_prompt
from agent.prompts import (
    GENIE_STEP_PROMPT,
    MULTI_PLANNER_PROMPT,
)
from agent.rag_agent import make_rag_agent
from agent.state import AnalystState
from agent.synthesizer import make_synthesizer

GENIE = "genie"
GUARDRAIL = "guardrail"

# Part 2's Genie Space contains only FY2022–FY2023 consolidated income
# statement rows and segment financials. These subjects exist only in the
# annual report, so sending them to Genie guarantees empty/null SQL results.
RAG_ONLY_TABLE_MARKERS = (
    "fy2024",
    "forecast",
    "guidance",
    "cash flow",
    "capital expenditure",
    "free cash flow",
    "balance sheet",
    "total assets",
    "total equity",
    "debt",
    "north america",
    "europe",
    "asia",
    "regional",
    "region ",
    "geographic",
    "ceo",
    "executive compensation",
)


def _table_coverage_route(step: str) -> str | None:
    """Route annual-report-only structured facts away from the limited Space."""
    lowered = step.lower()
    if any(marker in lowered for marker in RAG_ONLY_TABLE_MARKERS):
        return RAG
    return None


def _normalize_multi_plan(question: str, plan: list[str]) -> list[str]:
    """Keep a pure ranking request as one SQL-capable structured step."""
    lowered = question.lower()
    is_ranking = any(marker in lowered for marker in ("rank ", "ranking", "highest", "lowest"))
    needs_followup_calculation = any(
        marker in lowered
        for marker in ("project", "compound", " cagr", "after ", "convert")
    )
    if is_ranking and not needs_followup_calculation:
        return [question]
    return _collapse_redundant_growth_steps(plan)


def make_multi_planner(llm):
    """Plan structured lookups, narrative retrieval, and governed calculations."""

    def planner(state: AnalystState) -> dict:
        messages = state.get("messages", [])
        question = _text(messages[-1]) if messages else ""
        response = llm.invoke(
            [
                SystemMessage(content=MULTI_PLANNER_PROMPT),
                HumanMessage(content=question),
            ]
        )
        plan = _normalize_multi_plan(
            question,
            _parse_plan(_text(response), question),
        )
        return {
            "plan": plan,
            "current_step_index": 0,
            "step_results": [],
            "route_history": [],
            "genie_conversation_id": "",
        }

    return planner


def make_multi_supervisor(llm, *, coverage_guard: bool = True):
    """Route each planned step to Genie, RAG, or governed UC functions.

    ``coverage_guard=False`` is reserved for the Part 4 prompt-version
    experiment, where the two registry prompts must be compared without the
    deterministic Part 3 safeguard masking their routing behavior.
    """

    def supervisor(state: AnalystState) -> dict:
        index = state.get("current_step_index", 0)
        plan = state.get("plan", [])
        if index >= len(plan):
            return {"next_agent": SYNTH}
        if coverage_guard and (coverage_route := _table_coverage_route(plan[index])):
            return {
                "next_agent": coverage_route,
                "route_history": [
                    *state.get("route_history", []),
                    coverage_route,
                ],
            }
        response = llm.invoke(
            [
                SystemMessage(content=load_supervisor_prompt()),
                HumanMessage(content=plan[index]),
            ]
        )
        decision = _text(response).strip().lower()
        if GENIE in decision:
            next_agent = GENIE
        elif UC_TOOLS in decision:
            next_agent = UC_TOOLS
        else:
            next_agent = RAG
        return {
            "next_agent": next_agent,
            "route_history": [*state.get("route_history", []), next_agent],
        }

    return supervisor


def make_guardrail_node(
    guard: Callable[[str, str], str | None] | None,
):
    """Short-circuit blocked requests before planner, retrieval, or tool calls."""

    def guardrail(state: AnalystState) -> dict:
        if guard is None:
            return {"guardrail_reason": ""}
        messages = state.get("messages", [])
        prompt = _text(messages[-1]) if messages else ""
        user_id = state.get("user_id", "anonymous")
        reason = guard(user_id, prompt)
        if not reason:
            return {"guardrail_reason": ""}

        from bonus.guardrails import rejection_message

        return {
            "guardrail_reason": reason,
            "final_answer": rejection_message(reason),
            "route_history": [GUARDRAIL],
        }

    return guardrail


def route_from_guardrail(state: AnalystState) -> str:
    """Continue allowed requests and terminate blocked requests."""
    return "blocked" if state.get("guardrail_reason") else "allowed"


def load_genie_agent(
    genie_space_id: str | None = None,
    client=None,
):
    """Create the Databricks GenieAgent wrapper for the governed Space."""
    from databricks_langchain.genie import GenieAgent

    space_id = genie_space_id or os.environ.get("GENIE_SPACE_ID")
    if not space_id:
        raise OSError("Set GENIE_SPACE_ID or pass genie_space_id")
    return GenieAgent(
        genie_space_id=space_id,
        genie_agent_name="meridian_financials",
        description=(
            "Answers tabular questions about Meridian segment and consolidated "
            "financials from governed Delta tables."
        ),
        include_context=True,
        message_processor=lambda messages: _text(messages[-1]) if messages else "",
        client=client,
    )


def _named_message_content(messages, name: str) -> str:
    for message in messages:
        if getattr(message, "name", None) == name:
            return _text(message).strip()
    return ""


def make_genie_node(genie_agent):
    """Run one structured step and retain SQL plus rows for synthesis."""

    def genie(state: AnalystState) -> dict:
        index = state.get("current_step_index", 0)
        step = state["plan"][index]
        prior = "\n".join(state.get("step_results", [])) or "None"
        request = {
            "messages": [
                HumanMessage(
                    content=(
                        f"{GENIE_STEP_PROMPT}\nCurrent step: {step}\n"
                        f"Prior results: {prior}"
                    )
                )
            ]
        }
        conversation_id = state.get("genie_conversation_id")
        if conversation_id:
            request["conversation_id"] = conversation_id
        response = genie_agent.invoke(request)
        messages = response.get("messages", [])
        sql = _named_message_content(messages, "query_sql")
        result_rows = _named_message_content(messages, "query_result")
        reasoning = _named_message_content(messages, "query_reasoning")
        pieces = []
        if sql:
            pieces.append(f"Generated SQL:\n{sql}")
        if result_rows:
            pieces.append(f"Structured result:\n{result_rows}")
        elif reasoning:
            pieces.append(f"Genie response:\n{reasoning}")
        result = "\n\n".join(pieces) or "Genie returned no structured result"
        return {
            "step_results": [*state.get("step_results", []), result],
            "current_step_index": index + 1,
            "genie_conversation_id": response.get("conversation_id", ""),
        }

    return genie


def route_from_multi_supervisor(state: AnalystState) -> str:
    return state["next_agent"]


def build_graph_multi(
    llm=None,
    retriever=None,
    tools=None,
    genie_agent=None,
    *,
    function_names: list[str] | None = None,
    function_client=None,
    genie_space_id: str | None = None,
    genie_client=None,
    guard: Callable[[str, str], str | None] | None = None,
):
    """Compile the Part 2 multi-agent graph."""
    if llm is None:
        from config import get_chat_llm

        llm = get_chat_llm()
    if retriever is None:
        from rag.store import get_retriever

        retriever = get_retriever()
    if tools is None:
        tools = load_uc_tools(
            function_names=function_names,
            client=function_client,
        )
    if genie_agent is None:
        genie_agent = load_genie_agent(
            genie_space_id=genie_space_id,
            client=genie_client,
        )

    builder = StateGraph(AnalystState)
    builder.add_node(GUARDRAIL, make_guardrail_node(guard))
    builder.add_node("planner", make_multi_planner(llm))
    builder.add_node("supervisor", make_multi_supervisor(llm))
    builder.add_node(RAG, make_rag_agent(retriever, llm))
    builder.add_node(GENIE, make_genie_node(genie_agent))
    builder.add_node(UC_TOOLS, make_uc_tools_node(tools, llm))
    builder.add_node(SYNTH, make_synthesizer(llm))
    builder.add_edge(START, GUARDRAIL)
    builder.add_conditional_edges(
        GUARDRAIL,
        route_from_guardrail,
        {
            "allowed": "planner",
            "blocked": END,
        },
    )
    builder.add_edge("planner", "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        route_from_multi_supervisor,
        {
            RAG: RAG,
            GENIE: GENIE,
            UC_TOOLS: UC_TOOLS,
            SYNTH: SYNTH,
        },
    )
    builder.add_edge(RAG, "supervisor")
    builder.add_edge(GENIE, "supervisor")
    builder.add_edge(UC_TOOLS, "supervisor")
    builder.add_edge(SYNTH, END)
    return builder.compile()
