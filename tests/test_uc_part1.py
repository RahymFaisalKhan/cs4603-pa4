"""Offline tests for Extra-Credit Assignment 1 Part 1."""

from __future__ import annotations

from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from agent.graph_uc import (
    UC_TOOLS,
    _collapse_redundant_growth_steps,
    _uc_result_text,
    build_graph_uc,
)
from agent.prompts import PLANNER_PROMPT
from uc_tools import function_names
from uc_tools.register_functions import (
    compare_values,
    growth_rate,
    percentage_change,
)


def test_governed_function_implementations():
    assert growth_rate(16.91, 0.08, 3) == 21.301729920000003
    assert percentage_change(100, 125) == 25
    assert compare_values(16.91, 15) == "16.91 (a) is larger by 1.91"


def test_uc_function_names_are_fully_qualified(monkeypatch):
    monkeypatch.delenv("UC_FUNCTION_NAMES", raising=False)
    assert function_names("cs4603", "pa4") == [
        "cs4603.pa4.growth_rate",
        "cs4603.pa4.percentage_change",
        "cs4603.pa4.compare_values",
        "cs4603.pa4.to_billions",
    ]


def test_planner_uses_one_compound_growth_step():
    prompt = " ".join(PLANNER_PROMPT.lower().split())
    assert "exactly one" in prompt
    assert "do not create one calculation per period" in prompt


def test_uc_scalar_result_is_normalized():
    assert _uc_result_text('{"format": "SCALAR", "value": "21.30172992"}') == ("21.30172992")


def test_redundant_compound_growth_steps_are_collapsed():
    plan = [
        "Retrieve FY2023 revenue",
        "Calculate 3 years of compound growth on the retrieved revenue",
        "Compute retrieved revenue * (1 + 0.08)^3",
        "Perform the calculation: retrieved_net_revenue * 1.259712 = result",
    ]
    assert _collapse_redundant_growth_steps(plan) == plan[:2]


class FakeRetriever:
    def invoke(self, query):
        assert "revenue" in query.lower()
        return [
            Document(
                page_content="FY2023 net revenue was ¥16.91 trillion.",
                metadata={"source": "annual_report.pdf", "page": 4},
            )
        ]


class FakeUCFunction:
    name = "cs4603__pa4__growth_rate"
    description = "Governed compound-growth function"

    def invoke(self, args):
        assert args == {"start_value": 16.91, "rate": 0.08, "years": 3}
        return growth_rate(**args)


class FakeLLM:
    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages):
        text = "\n".join(str(message.content) for message in messages)
        if "document-analysis planner" in text:
            return AIMessage(
                content=(
                    '["Find Meridian FY2023 net revenue", '
                    '"Project it for 3 years at 8% compound growth"]'
                )
            )
        if "Classify the current plan step" in text:
            return AIMessage(content=UC_TOOLS if "Project" in text else "rag_agent")
        if "Retrieved chunks" in text:
            return AIMessage(
                content=("FY2023 net revenue was ¥16.91 trillion [source: annual_report.pdf, p.4]")
            )
        if "governed Unity" in text:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "cs4603__pa4__growth_rate",
                        "args": {
                            "start_value": 16.91,
                            "rate": 0.08,
                            "years": 3,
                        },
                        "id": "uc-1",
                    }
                ],
            )
        if "Synthesize a direct" in text:
            return AIMessage(
                content=(
                    "Revenue was ¥16.91 trillion "
                    "[source: annual_report.pdf, p.4], projected to "
                    "¥21.30184704 trillion through a governed UC function."
                )
            )
        raise AssertionError(text)


def test_uc_graph_runs_rag_then_governed_function():
    graph = build_graph_uc(
        llm=FakeLLM(),
        retriever=FakeRetriever(),
        tools=[FakeUCFunction()],
    )
    result = graph.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "What was Meridian's FY2023 net revenue, and what would "
                        "it be after 3 years of 8% compound growth?"
                    ),
                }
            ]
        }
    )

    assert len(result["plan"]) == 2
    assert "annual_report.pdf" in result["step_results"][0]
    assert result["step_results"][1] == "21.301729920000003"
    assert "governed UC function" in result["final_answer"]
