"""Programmatic Genie Conversation API client with SQL/result extraction."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from databricks.sdk import WorkspaceClient

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTIONS = [
    "Rank Meridian's FY2023 segments by revenue.",
    "Which segment improved operating margin the most from FY2022 to FY2023?",
    "Compare FY2022 and FY2023 net revenue and operating profit.",
]


@dataclass
class GenieRoundTrip:
    question: str
    conversation_id: str
    message_id: str
    generated_sql: str
    columns: list[str]
    rows: list[list[str | None]]
    text: str


def _attachment_parts(message) -> tuple[str, str, str | None]:
    sql = ""
    text = ""
    query_attachment_id = None
    for attachment in message.attachments or []:
        if attachment.query:
            sql = attachment.query.query or ""
            query_attachment_id = attachment.attachment_id
        if attachment.text:
            text_value = getattr(attachment.text, "content", "")
            if isinstance(text_value, list):
                text += "\n".join(str(item) for item in text_value)
            else:
                text += str(text_value)
    return sql, text, query_attachment_id


def query_genie(
    client: WorkspaceClient,
    *,
    space_id: str,
    question: str,
) -> GenieRoundTrip:
    """Ask one question and return both generated SQL and normalized result rows."""
    message = client.genie.start_conversation_and_wait(
        space_id=space_id,
        content=question,
    )
    sql, text, attachment_id = _attachment_parts(message)
    columns: list[str] = []
    rows: list[list[str | None]] = []
    if attachment_id:
        query_result = client.genie.get_message_attachment_query_result(
            space_id=space_id,
            conversation_id=message.conversation_id,
            message_id=message.message_id,
            attachment_id=attachment_id,
        )
        statement = query_result.statement_response
        if statement and statement.manifest and statement.manifest.schema:
            columns = [
                column.name for column in statement.manifest.schema.columns or []
            ]
        if statement and statement.result and statement.result.data_array:
            rows = statement.result.data_array
    return GenieRoundTrip(
        question=question,
        conversation_id=message.conversation_id,
        message_id=message.message_id,
        generated_sql=sql,
        columns=columns,
        rows=rows,
        text=text,
    )


def _print_round_trip(result: GenieRoundTrip) -> None:
    print(f"Question: {result.question}")
    print("Generated SQL:")
    print(result.generated_sql or "<no SQL generated>")
    print("Result columns:")
    print(result.columns)
    print("Result rows:")
    for row in result.rows:
        print(row)
    if result.text:
        print("Genie text:")
        print(result.text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default=os.environ.get("DATABRICKS_PROFILE"))
    parser.add_argument("--space-id", default=os.environ.get("GENIE_SPACE_ID"))
    parser.add_argument("--question", action="append")
    args = parser.parse_args()
    if not args.space_id:
        raise OSError("Pass --space-id or set GENIE_SPACE_ID")

    client = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
    results = [
        query_genie(client, space_id=args.space_id, question=question)
        for question in (args.question or DEFAULT_QUESTIONS)
    ]
    for index, result in enumerate(results):
        if index:
            print()
        _print_round_trip(result)
    evidence_path = ROOT / "genie" / "conversation_evidence.json"
    evidence_path.write_text(
        json.dumps([asdict(result) for result in results], indent=2) + "\n"
    )
    print(f"\nWrote {evidence_path}")


if __name__ == "__main__":
    main()
