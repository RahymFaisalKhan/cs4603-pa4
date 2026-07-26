"""Offline validation for Extra-Credit Assignment 1 Part 2."""

from __future__ import annotations

import json

from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from agent.graph_multi import (
    GENIE,
    RAG,
    _normalize_multi_plan,
    _table_coverage_route,
    build_graph_multi,
    make_multi_supervisor,
)
from agent.graph_uc import UC_TOOLS
from deployment.deploy_multi import multi_resources
from genie.build_tables import build_statements
from genie.grant_data_access import grant_statements
from genie.space_config import build_space_payload


def test_table_rows_reconcile_to_reported_totals():
    sql = "\n".join(build_statements("cs4603", "pa4"))
    assert "16910000000000" in sql
    assert "14550000000000" in sql
    assert sum([12_900_000_000_000, 2_510_000_000_000, 1_100_000_000_000, 400_000_000_000]) == 16_910_000_000_000
    assert sum([560_000_000_000, 360_000_000_000, 180_000_000_000, 24_000_000_000]) == 1_124_000_000_000
    assert sum([11_030_000_000_000, 2_120_000_000_000, 1_030_000_000_000, 370_000_000_000]) == 14_550_000_000_000
    assert sum([430_000_000_000, 310_000_000_000, 145_000_000_000, 20_000_000_000]) == 905_000_000_000


def test_every_table_and_column_has_a_comment():
    statements = build_statements("cs4603", "pa4")
    ddl = "\n".join(statement for statement in statements if statement.startswith("CREATE"))
    assert ddl.count("CREATE OR REPLACE TABLE") == 2
    assert ddl.count(" COMMENT '") == 9


def test_curated_space_has_tables_instructions_and_trusted_queries():
    payload = build_space_payload("cs4603", "pa4")
    assert payload["version"] == 2
    assert len(payload["data_sources"]["tables"]) == 2
    assert len(payload["instructions"]["text_instructions"]) == 1
    assert len(payload["instructions"]["example_question_sqls"]) == 2
    assert len(payload["config"]["sample_questions"]) == 3
    for section in (
        payload["config"]["sample_questions"]
        + payload["instructions"]["text_instructions"]
        + payload["instructions"]["example_question_sqls"]
    ):
        assert len(section["id"]) == 32
        int(section["id"], 16)
    json.dumps(payload)


class RoutingLLM:
    def __init__(self, answer: str):
        self.answer = answer

    def invoke(self, messages):
        return AIMessage(content=self.answer)


def test_supervisor_routes_contrasting_questions():
    cases = [
        ("Rank Meridian's FY2023 segments by revenue.", GENIE),
        ("What risks did Meridian cite for its Automobile segment?", RAG),
        ("Project the retrieved revenue for 3 years at 8% growth.", UC_TOOLS),
    ]
    for question, expected in cases:
        result = make_multi_supervisor(RoutingLLM(expected))(
            {"plan": [question], "current_step_index": 0}
        )
        assert result["next_agent"] == expected


def test_part3_table_coverage_guard_routes_unsupported_domains_to_rag():
    rag_only_steps = [
        "Retrieve Meridian's FY2024 forecast revenue.",
        "Look up FY2023 operating cash flow and capital expenditure.",
        "Find North America FY2023 revenue.",
        "Find the CEO's executive compensation.",
    ]
    for step in rag_only_steps:
        assert _table_coverage_route(step) == RAG
    assert _table_coverage_route("Rank FY2023 segments by revenue.") is None
    assert _table_coverage_route("Query FY2023 operating profit.") is None


def test_ranking_request_stays_one_structured_step():
    question = "Rank Meridian's FY2023 segments by revenue."
    plan = ["Query all segment revenue", "Rank the returned rows"]
    assert _normalize_multi_plan(question, plan) == [question]


def test_deployed_principal_gets_only_required_table_privileges():
    statements = grant_statements("cs4603", "pa4", "agent-application-id")
    assert statements == [
        "GRANT USE CATALOG ON CATALOG cs4603 TO `agent-application-id`",
        "GRANT USE SCHEMA ON SCHEMA cs4603.pa4 TO `agent-application-id`",
        (
            "GRANT SELECT ON TABLE cs4603.pa4.meridian_segment_financials "
            "TO `agent-application-id`"
        ),
        (
            "GRANT SELECT ON TABLE cs4603.pa4.meridian_income_statement "
            "TO `agent-application-id`"
        ),
    ]


def test_part3_deployment_declares_underlying_genie_tables(monkeypatch):
    values = {
        "DATABRICKS_MODEL": "llm-endpoint",
        "VECTOR_SEARCH_INDEX": "cs4603.pa4.index",
        "GENIE_SPACE_ID": "space-id",
        "UC_CATALOG": "cs4603",
        "UC_SCHEMA": "pa4",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    resources = multi_resources()
    table_resources = [
        resource.name
        for resource in resources
        if type(resource).__name__ == "DatabricksTable"
    ]
    assert table_resources == [
        "cs4603.pa4.meridian_segment_financials",
        "cs4603.pa4.meridian_income_statement",
    ]


class FakeRetriever:
    def invoke(self, query):
        assert "risk" in query.lower()
        return [
            Document(
                page_content=(
                    "Automobile risks include cyclical demand, supply constraints, "
                    "foreign exchange, regulation, and technology shifts."
                ),
                metadata={"source": "annual_report.pdf", "page": 12},
            )
        ]


class FakeGenieAgent:
    def invoke(self, request):
        assert "structured-data step" in request["messages"][0].content
        return {
            "messages": [
                AIMessage(
                    name="query_sql",
                    content=(
                        "SELECT segment, revenue_yen FROM financials "
                        "WHERE fiscal_year=2023 ORDER BY revenue_yen DESC"
                    ),
                ),
                AIMessage(
                    name="query_result",
                    content=(
                        "| segment | revenue_yen |\n|---|---:|\n"
                        "| Automobile | 12900000000000 |"
                    ),
                ),
            ],
            "conversation_id": "conversation-1",
        }


class GraphLLM:
    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        text = "\n".join(str(message.content) for message in messages)
        if "financial-analysis planner" in text:
            question = messages[-1].content
            return AIMessage(content=json.dumps([question]))
        if "Classify the current plan step" in text:
            step = messages[-1].content.lower()
            return AIMessage(content=RAG if "risks" in step else GENIE)
        if "Retrieved chunks" in text:
            return AIMessage(
                content=(
                    "Meridian cited cyclical demand, supply-chain, FX, regulatory, "
                    "and technology risks [source: annual_report.pdf, p.12]."
                )
            )
        if "Synthesize a direct" in text:
            return AIMessage(content=text.split("Results:\n", 1)[-1])
        raise AssertionError(text)


def _graph():
    return build_graph_multi(
        llm=GraphLLM(),
        retriever=FakeRetriever(),
        tools=[],
        genie_agent=FakeGenieAgent(),
    )


def test_structured_question_routes_to_genie_and_preserves_sql_and_rows():
    result = _graph().invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Rank Meridian's FY2023 segments by revenue.",
                }
            ]
        }
    )
    assert "Generated SQL" in result["step_results"][0]
    assert "Automobile" in result["step_results"][0]
    assert result["genie_conversation_id"] == "conversation-1"


def test_narrative_question_routes_to_rag_and_preserves_citation():
    result = _graph().invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "What risks did Meridian cite for its Automobile segment?",
                }
            ]
        }
    )
    assert "annual_report.pdf" in result["step_results"][0]
    assert "technology risks" in result["final_answer"]
