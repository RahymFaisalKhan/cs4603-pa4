"""Compiled Document Analyst graph and MCP integration (Tasks 1.5 + 1.7)."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from agent.planner import make_planner
from agent.prompts import MCP_STEP_PROMPT
from agent.rag_agent import make_rag_agent
from agent.state import AnalystState
from agent.supervisor import MCP, RAG, SYNTH, make_supervisor, route_from_supervisor
from agent.synthesizer import make_synthesizer


def _run_async(coro):
    """Run a coroutine from normal Python or from a notebook with a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    result = []
    error = []

    def runner():
        try:
            # Some serving runtimes propagate the caller's running-loop
            # marker into worker threads. This thread must own a fresh loop.
            asyncio.events._set_running_loop(None)
            result.append(asyncio.run(coro))
        except BaseException as exc:  # Re-raised in the caller's thread.
            error.append(exc)

    thread = threading.Thread(target=runner)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


def _configure_mcp_stdio_stderr():
    """Make every MCP stdio session pass an OS-backed error stream explicitly.

    ``mcp.client.stdio.stdio_client`` captures ``sys.stderr`` as a function
    default when that module is imported.  MLflow can import it only after
    replacing stderr with ``StreamToLogger``, so changing ``sys.stderr`` around
    a later call is insufficient.  Patch the adapter's call-site binding once;
    this also covers the new sessions opened when an already-discovered tool is
    invoked.
    """
    import langchain_mcp_adapters.sessions as mcp_sessions

    original = mcp_sessions.stdio_client
    if getattr(original, "_uses_os_stderr", False):
        return

    @asynccontextmanager
    async def stdio_client_with_os_stderr(server):
        process_stderr = os.fdopen(os.dup(2), "w", buffering=1)
        try:
            async with original(server, errlog=process_stderr) as streams:
                yield streams
        finally:
            process_stderr.close()

    stdio_client_with_os_stderr._uses_os_stderr = True
    mcp_sessions.stdio_client = stdio_client_with_os_stderr


def load_mcp_tools(server_path: str | None = None):
    # Databricks Model Serving replaces sys.stderr with MLflow's
    # StreamToLogger, which has no fileno(). Configure the MCP stdio transport
    # before either discovery or invocation can launch its subprocess.
    root = Path(__file__).resolve().parents[1]
    path = Path(server_path) if server_path else root / "tools" / "mcp_server.py"
    url = os.environ.get("MCP_SERVER_URL")
    if url:
        config = {
            "analyst": {
                "url": f"{url.rstrip('/')}/mcp",
                "transport": "streamable_http",
                "headers": {"Authorization": f"Bearer {os.environ.get('DATABRICKS_TOKEN', '')}"},
            }
        }
    else:
        _configure_mcp_stdio_stderr()
        config = {
            "analyst": {
                "command": sys.executable,
                "args": [str(path)],
                "transport": "stdio",
            }
        }

    from langchain_mcp_adapters.client import MultiServerMCPClient

    return _run_async(MultiServerMCPClient(config).get_tools())


def make_mcp_node(tools, llm):
    by_name = {tool.name: tool for tool in tools}
    tool_llm = llm.bind_tools(tools)

    def mcp_tools(state: AnalystState) -> dict:
        index = state.get("current_step_index", 0)
        step = state["plan"][index]
        prior = "\n".join(state.get("step_results", [])) or "None"
        response = tool_llm.invoke(
            [
                HumanMessage(
                    content=f"{MCP_STEP_PROMPT}\nCurrent step: {step}\nPrior results: {prior}"
                )
            ]
        )
        calls = getattr(response, "tool_calls", [])
        if not calls:
            result = f"calculation failed: model did not select a tool for `{step}`"
        else:
            call = calls[0]
            tool = by_name.get(call["name"])
            if tool is None:
                result = f"calculation failed: unknown tool {call['name']}"
            else:
                args = call.get("args", {})
                output = _run_async(tool.ainvoke(args)) if hasattr(tool, "ainvoke") else tool.invoke(args)
                result = str(getattr(output, "content", output))
        return {
            "step_results": [*state.get("step_results", []), result],
            "current_step_index": index + 1,
        }

    return mcp_tools


def build_graph(llm=None, retriever=None, tools=None):
    if llm is None:
        from config import get_chat_llm

        llm = get_chat_llm()
    if retriever is None:
        from rag.store import get_retriever

        retriever = get_retriever()
    if tools is None:
        tools = load_mcp_tools()

    builder = StateGraph(AnalystState)
    builder.add_node("planner", make_planner(llm))
    builder.add_node("supervisor", make_supervisor(llm))
    builder.add_node(RAG, make_rag_agent(retriever, llm))
    builder.add_node(MCP, make_mcp_node(tools, llm))
    builder.add_node(SYNTH, make_synthesizer(llm))
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "supervisor")
    builder.add_conditional_edges("supervisor", route_from_supervisor, {RAG: RAG, MCP: MCP, SYNTH: SYNTH})
    builder.add_edge(RAG, "supervisor")
    builder.add_edge(MCP, "supervisor")
    builder.add_edge(SYNTH, END)
    return builder.compile()
