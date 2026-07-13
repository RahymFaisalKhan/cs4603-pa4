"""Final cited-answer synthesizer (Task 1.6)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.prompts import SYNTHESIZER_PROMPT
from agent.state import AnalystState


def make_synthesizer(llm):
    def synthesizer(state: AnalystState) -> dict:
        question = getattr(state.get("messages", [""])[0], "content", "")
        results = "\n".join(
            f"Step {i + 1}: {result}" for i, result in enumerate(state.get("step_results", []))
        )
        response = llm.invoke(
            [
                SystemMessage(content=SYNTHESIZER_PROMPT),
                HumanMessage(content=f"Original question: {question}\n\nResults:\n{results}"),
            ]
        )
        answer = str(getattr(response, "content", response)).strip()
        return {"final_answer": answer, "messages": [AIMessage(content=answer)]}

    return synthesizer
