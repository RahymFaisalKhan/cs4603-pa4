"""Document Analyst graph backed by governed Unity Catalog function tools."""

from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from agent.graph import _run_async
from agent.planner import make_planner
from agent.prompts import UC_STEP_PROMPT, UC_SUPERVISOR_PROMPT
from agent.rag_agent import make_rag_agent
from agent.state import AnalystState
from agent.synthesizer import make_synthesizer
from uc_tools import function_names as configured_function_names

RAG = "rag_agent"
UC_TOOLS = "uc_tools"
SYNTH = "synthesizer"


def _is_compound_growth_step(step: str) -> bool:
    lowered = step.lower()
    return (
        "compound growth" in lowered
        or "cagr" in lowered
        or bool(re.search(r"\(\s*1\s*\+[^)]*\)\s*(?:\^|\*\*)", lowered))
    )


def _collapse_redundant_growth_steps(plan: list[str]) -> list[str]:
    """Keep only the first whole-period compound-growth calculation."""
    seen_growth = False
    normalized: list[str] = []
    for step in plan:
        lowered = step.lower()
        is_same_growth_formula = seen_growth and (
            "retrieved_net_revenue" in lowered
            or "retrieved net revenue" in lowered
        ) and any(
            marker in lowered
            for marker in ("perform the calculation", "compute", "*", "^", "**")
        )
        if is_same_growth_formula:
            continue
        if _is_compound_growth_step(step):
            if seen_growth:
                continue
            seen_growth = True
        normalized.append(step)
    return normalized


def make_uc_planner(llm):
    """Wrap the PA4 planner with deterministic compound-step normalization."""
    base_planner = make_planner(llm)

    def planner(state: AnalystState) -> dict:
        result = base_planner(state)
        result["plan"] = _collapse_redundant_growth_steps(result["plan"])
        return result

    return planner


def load_uc_tools(
    function_names: list[str] | None = None,
    client=None,
):
    """Load governed UC functions as LangChain tools."""
    from databricks_langchain import UCFunctionToolkit

    toolkit = UCFunctionToolkit(
        function_names=function_names or configured_function_names(),
        client=client,
    )
    return toolkit.tools


def make_uc_supervisor(llm):
    """Route retrieval steps to RAG and calculations to UC Functions."""

    def supervisor(state: AnalystState) -> dict:
        index = state.get("current_step_index", 0)
        plan = state.get("plan", [])
        if index >= len(plan):
            return {"next_agent": SYNTH}
        response = llm.invoke(
            [
                SystemMessage(content=UC_SUPERVISOR_PROMPT),
                HumanMessage(content=plan[index]),
            ]
        )
        decision = str(getattr(response, "content", response)).lower()
        return {"next_agent": UC_TOOLS if UC_TOOLS in decision else RAG}

    return supervisor


def make_uc_tools_node(tools, llm):
    """Execute one model-selected governed function for the current plan step."""
    by_name = {tool.name: tool for tool in tools}
    tool_llm = llm.bind_tools(tools)

    def uc_tools(state: AnalystState) -> dict:
        index = state.get("current_step_index", 0)
        step = state["plan"][index]
        prior = "\n".join(state.get("step_results", [])) or "None"
        response = tool_llm.invoke(
            [
                HumanMessage(
                    content=(f"{UC_STEP_PROMPT}\nCurrent step: {step}\nPrior results: {prior}")
                )
            ]
        )
        calls = getattr(response, "tool_calls", [])
        if not calls:
            result = f"calculation failed: model did not select a governed function for `{step}`"
        else:
            call = calls[0]
            tool = by_name.get(call["name"])
            if tool is None:
                result = f"calculation failed: unknown governed function {call['name']}"
            else:
                args = call.get("args", {})
                output = (
                    _run_async(tool.ainvoke(args))
                    if hasattr(tool, "ainvoke")
                    else tool.invoke(args)
                )
                result = _uc_result_text(output)
        return {
            "step_results": [*state.get("step_results", []), result],
            "current_step_index": index + 1,
        }

    return uc_tools


def _uc_result_text(output) -> str:
    """Extract the scalar value from a UC toolkit execution response."""
    value = getattr(output, "content", output)
    if isinstance(value, dict) and "value" in value:
        return str(value["value"])
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(decoded, dict) and "value" in decoded:
            return str(decoded["value"])
    return str(value)


def route_from_uc_supervisor(state: AnalystState) -> str:
    """Return the supervisor's selected node."""
    return state["next_agent"]


def build_graph_uc(
    llm=None,
    retriever=None,
    tools=None,
    function_names: list[str] | None = None,
    function_client=None,
):
    """Compile the PA4 graph with UC Functions replacing its MCP tool node."""
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

    builder = StateGraph(AnalystState)
    builder.add_node("planner", make_uc_planner(llm))
    builder.add_node("supervisor", make_uc_supervisor(llm))
    builder.add_node(RAG, make_rag_agent(retriever, llm))
    builder.add_node(UC_TOOLS, make_uc_tools_node(tools, llm))
    builder.add_node(SYNTH, make_synthesizer(llm))
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        route_from_uc_supervisor,
        {
            RAG: RAG,
            UC_TOOLS: UC_TOOLS,
            SYNTH: SYNTH,
        },
    )
    builder.add_edge(RAG, "supervisor")
    builder.add_edge(UC_TOOLS, "supervisor")
    builder.add_edge(SYNTH, END)
    return builder.compile()
