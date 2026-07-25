"""Fully offline graph smoke test."""

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from agent.graph import _run_async, build_graph, load_mcp_tools
from agent.prompts import RAG_EXTRACT_PROMPT
from client.sdk import DocumentAnalystClient


def test_run_async_inside_running_event_loop():
    async def outer():
        async def answer():
            return 42

        return _run_async(answer())

    assert asyncio.run(outer()) == 42


def test_net_income_definition_excludes_non_controlling_interests():
    prompt = RAG_EXTRACT_PROMPT.lower()
    assert "net income attributable to owners" in prompt
    assert "excluding non-controlling interests" in prompt
    assert "not `profit for the year`" in prompt


class FakeRetriever:
    def invoke(self, query):
        assert "revenue" in query.lower()
        return [Document(page_content="FY2023 net revenue was ¥16.91 trillion.", metadata={"source": "annual_report.pdf", "page": 4})]


class FakeTool:
    name = "growth_rate"
    description = "Calculate compound growth"

    def invoke(self, args):
        assert args["start_value"] == 16.91
        return "16.91 at 8% CAGR for 3 years = 21.3019"


class FakeLLM:
    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages):
        text = "\n".join(str(message.content) for message in messages)
        if "document-analysis planner" in text:
            return AIMessage(content='["Find FY2023 revenue", "Calculate revenue after 3 years at 8% CAGR"]')
        if "Classify the current plan step" in text:
            return AIMessage(content="mcp_tools" if "Calculate" in text else "rag_agent")
        if "Retrieved chunks" in text:
            return AIMessage(content="FY2023 net revenue was ¥16.91 trillion [source: annual_report.pdf, p.4]")
        if "Return a tool call only" in text:
            return AIMessage(content="", tool_calls=[{"name": "growth_rate", "args": {"start_value": 16.91, "rate": 0.08, "years": 3}, "id": "1"}])
        if "Synthesize a direct" in text:
            return AIMessage(content="Revenue was ¥16.91 trillion [source: annual_report.pdf, p.4], projected to ¥21.3019 trillion.")
        raise AssertionError(text)


def test_combined_query_runs_both_specialists():
    graph = build_graph(llm=FakeLLM(), retriever=FakeRetriever(), tools=[FakeTool()])
    result = graph.invoke({"messages": [{"role": "user", "content": "What was revenue and its value after 3 years at 8%?"}]})
    assert len(result["plan"]) == 2
    assert "annual_report.pdf" in result["step_results"][0]
    assert "21.3019" in result["step_results"][1]
    assert result["final_answer"] == result["messages"][-1].content


def test_mcp_stdio_works_when_imported_with_mlflow_stderr():
    class StreamToLogger:
        def write(self, _text):
            pass

        def flush(self):
            pass

    wrapped = StreamToLogger()
    original = sys.stderr
    try:
        # MCP captures this object in stdio_client's default argument at import
        # time, reproducing the Databricks MLflow serving environment.
        sys.stderr = wrapped
        tools = load_mcp_tools()
    finally:
        sys.stderr = original

    calculate = next(tool for tool in tools if tool.name == "calculate")
    result = _run_async(calculate.ainvoke({"expression": "1 + 2"}))
    assert "= 3" in str(result)


def test_client_parses_direct_mlflow_prediction_list():
    response = [
        {
            "messages": [
                {"type": "human", "content": "What was revenue?"},
                {"type": "ai", "content": "Revenue was 16,910 billion."},
            ],
            "final_answer": "Revenue was 16,910 billion.",
        }
    ]
    assert DocumentAnalystClient._answer(response) == "Revenue was 16,910 billion."


def test_client_retries_503_with_exponential_backoff(monkeypatch):
    attempts = []
    delays = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(
                503,
                json={"message": "endpoint is scaling"},
                headers={"x-request-id": "retry-1"},
            )
        return httpx.Response(
            200,
            json=[
                {
                    "messages": [{"type": "ai", "content": "Recovered answer."}],
                    "final_answer": "Recovered answer.",
                }
            ],
        )

    monkeypatch.setattr("client.sdk.time.sleep", delays.append)
    client = DocumentAnalystClient(
        "test-endpoint",
        host="https://example.test",
        token="test-token",
        max_retries=2,
    )
    client._client.close()
    client._client = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer test-token"},
    )
    try:
        assert client.ask("Will the retry recover?") == "Recovered answer."
    finally:
        client.close()

    assert len(attempts) == 2
    assert delays == [1]
