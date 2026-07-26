"""Demonstrate both fallback guardrails and export reproducible evidence."""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import HumanMessage

from agent.graph_multi import build_graph_multi
from bonus.guardrails import RollingWindowGuard, rejection_message

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "bonus" / "results" / "guardrail_evidence.json"


class _MustNotRun:
    def bind_tools(self, _tools):
        return self

    def invoke(self, _input):
        raise AssertionError("A blocked request reached an agent dependency")


def _blocked_graph_result(guard: RollingWindowGuard, user_id: str, prompt: str):
    dependency = _MustNotRun()
    graph = build_graph_multi(
        llm=dependency,
        retriever=dependency,
        tools=[],
        genie_agent=dependency,
        guard=guard.check,
    )
    result = graph.invoke(
        {
            "messages": [HumanMessage(content=prompt)],
            "user_id": user_id,
        }
    )
    return {
        "guardrail_reason": result["guardrail_reason"],
        "route_history": result["route_history"],
        "final_answer": result["final_answer"],
        "downstream_agent_called": False,
    }


def main() -> None:
    now = [1_000.0]
    guard = RollingWindowGuard(max_per_minute=2, clock=lambda: now[0])

    rate_results = []
    for prompt in ("first clean request", "second clean request", "third request"):
        reason = guard.check("rate-demo-user", prompt)
        rate_results.append(
            {
                "prompt": prompt,
                "decision": reason or "allowed",
                "response": rejection_message(reason) if reason else "passed to graph",
            }
        )

    pii_prompt = "Email the report to finance.user@example.com"
    pii_reason = guard.check("pii-demo-user", pii_prompt)

    rate_graph_guard = RollingWindowGuard(clock=lambda: now[0])
    rate_graph_guard.check("graph-rate-user", "one")
    rate_graph_guard.check("graph-rate-user", "two")
    rate_graph = _blocked_graph_result(
        rate_graph_guard,
        "graph-rate-user",
        "third request",
    )
    pii_graph = _blocked_graph_result(
        RollingWindowGuard(clock=lambda: now[0]),
        "graph-pii-user",
        pii_prompt,
    )
    evidence = {
        "implementation": "code_level_fallback",
        "reason": (
            "Databricks agent endpoints support inference tables but do not "
            "support AI Gateway rate-limit or AI Guardrail policies."
        ),
        "configuration": {
            "max_requests_per_user_per_rolling_minute": 2,
            "pii_types": ["Pakistani CNIC", "US SSN", "email address"],
        },
        "rate_limit_demo": rate_results,
        "pii_demo": {
            "prompt": pii_prompt,
            "decision": pii_reason,
            "response": rejection_message(pii_reason or ""),
        },
        "graph_short_circuit_demo": {
            "rate_limit": rate_graph,
            "pii": pii_graph,
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
