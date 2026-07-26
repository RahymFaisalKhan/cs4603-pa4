"""Enable inference logging, send production traffic, and export trace evidence."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import mlflow
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import AiGatewayInferenceTableConfig
from PIL import Image, ImageDraw, ImageFont

from eval.run_eval import _prediction_from_response, configure_databricks_auth
from genie.build_tables import _warehouse_id, execute_sql

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "bonus" / "results"
ENDPOINT = "agents_cs4603-pa4-pa4_document_analyst"
EXPERIMENT_ID = "1306660282575833"
TABLE = "cs4603.pa4.pa4_document_analyst_inference_payload"
TRACE_QUESTION = "Rank Meridian's FY2023 segments by revenue."
TRAFFIC = [
    TRACE_QUESTION,
    "What was Meridian's FY2023 net income?",
    "What strategic risk could affect Meridian's profitability?",
    "Which FY2023 segment had the highest operating margin?",
]


def _invoke(client: WorkspaceClient, endpoint: str, question: str) -> dict[str, Any]:
    request_id = f"part4-{uuid4()}"
    response = client.api_client.do(
        "POST",
        f"/serving-endpoints/{endpoint}/invocations",
        body={
            "client_request_id": request_id,
            "dataframe_records": [
                {"messages": [{"role": "user", "content": question}]}
            ],
        },
    )
    return {
        "client_request_id": request_id,
        "question": question,
        "response": _prediction_from_response(response),
    }


def _span_rows(trace) -> list[dict[str, Any]]:
    spans = sorted(trace.data.spans, key=lambda span: span.start_time_ns)
    children: dict[str | None, list] = {}
    for span in spans:
        children.setdefault(span.parent_id, []).append(span)
    roots = [span for span in spans if not span.parent_id]
    rows: list[dict[str, Any]] = []

    def visit(span, depth: int) -> None:
        duration_ms = max(0.0, (span.end_time_ns - span.start_time_ns) / 1_000_000)
        rows.append(
            {
                "depth": depth,
                "name": span.name,
                "span_type": str(span.span_type),
                "duration_ms": round(duration_ms, 2),
                "status": str(span.status.status_code),
                "span_id": span.span_id,
                "parent_id": span.parent_id,
            }
        )
        for child in children.get(span.span_id, []):
            visit(child, depth + 1)

    for root in roots:
        visit(root, 0)
    return rows


def _find_trace(question: str, attempts: int = 12):
    for _ in range(attempts):
        traces = mlflow.search_traces(
            experiment_ids=[EXPERIMENT_ID],
            max_results=30,
            return_type="list",
            include_spans=True,
        )
        for trace in traces:
            if question in json.dumps(trace.to_dict(), default=str):
                return trace
        time.sleep(5)
    raise RuntimeError("The endpoint trace did not reach the MLflow store in time")


def _render_trace(rows: list[dict[str, Any]], route: list[str], output: Path) -> None:
    width = 1500
    line_height = 34
    height = 160 + line_height * len(rows)
    image = Image.new("RGB", (width, height), "#f7f9fc")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=18)
    title_font = ImageFont.load_default(size=25)
    draw.text((32, 24), "Part 4 - MLflow production trace", fill="#13213c", font=title_font)
    draw.text(
        (32, 62),
        f"Question: {TRACE_QUESTION}",
        fill="#243b64",
        font=font,
    )
    draw.text(
        (32, 91),
        f"Winning route: {' → '.join(route) or 'unknown'}",
        fill="#087f5b",
        font=font,
    )
    draw.text((950, 91), "Span duration", fill="#52657f", font=font)
    y = 132
    max_duration = max((row["duration_ms"] for row in rows), default=1.0)
    for row in rows:
        x = 35 + row["depth"] * 30
        name = f"{row['name']}  [{row['span_type']}]"
        draw.text((x, y), name[:92], fill="#182b49", font=font)
        bar_width = max(3, int(420 * row["duration_ms"] / max_duration))
        color = "#6f42c1" if "GENIE" in name.upper() or "genie" in name else "#3b82f6"
        draw.rounded_rectangle((950, y, 950 + bar_width, y + 20), radius=5, fill=color)
        draw.text(
            (1380, y),
            f"{row['duration_ms']:.1f} ms",
            fill="#182b49",
            font=font,
        )
        y += line_height
    image.save(output)


def _aggregate_sql(client: WorkspaceClient, warehouse_id: str, table: str):
    description = execute_sql(client, warehouse_id, f"DESCRIBE TABLE {table}")
    columns = {row[0] for row in description.rows if row and row[0]}
    if "request_time" in columns:
        time_expression = "date_trunc('minute', request_time)"
    else:
        time_expression = "date_trunc('minute', to_timestamp(timestamp_ms / 1000))"
    duration = (
        "execution_duration_ms"
        if "execution_duration_ms" in columns
        else "execution_time_ms"
    )
    statement = f"""
SELECT {time_expression} AS minute,
       count(*) AS n_requests,
       round(avg({duration}), 2) AS avg_latency_ms,
       sum(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS errors
FROM {table}
GROUP BY 1
ORDER BY 1
""".strip()
    return execute_sql(client, warehouse_id, statement)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="rahym-ec1")
    parser.add_argument("--endpoint", default=ENDPOINT)
    parser.add_argument("--warehouse-id", default="b4167325a6783244")
    parser.add_argument("--skip-enable", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    host, token = configure_databricks_auth(args.profile)
    client = WorkspaceClient(host=host, token=token)
    RESULTS.mkdir(parents=True, exist_ok=True)

    gateway_response = None
    gateway_error = None
    if not args.skip_enable:
        try:
            gateway_response = client.serving_endpoints.put_ai_gateway(
                name=args.endpoint,
                inference_table_config=AiGatewayInferenceTableConfig(
                    enabled=True,
                    catalog_name="cs4603",
                    schema_name="pa4",
                    table_name_prefix="pa4_document_analyst_inference",
                ),
            ).as_dict()
        except Exception as exc:
            gateway_error = f"{type(exc).__name__}: {exc}"

    traffic = []
    for question in TRAFFIC:
        traffic.append(_invoke(client, args.endpoint, question))

    mlflow.set_tracking_uri("databricks")
    trace = _find_trace(TRACE_QUESTION)
    rows = _span_rows(trace)
    route = (
        traffic[0]
        .get("response", {})
        .get("custom_outputs", {})
        .get("route_history", [])
    )
    trace_evidence = {
        "trace_id": trace.info.trace_id,
        "experiment_id": EXPERIMENT_ID,
        "endpoint": args.endpoint,
        "question": TRACE_QUESTION,
        "winning_route": route,
        "spans": rows,
    }
    (RESULTS / "trace_evidence.json").write_text(
        json.dumps(trace_evidence, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    _render_trace(rows, route, RESULTS / "trace_tree.png")

    inference_result = None
    inference_error = None
    if not gateway_error:
        warehouse_id = _warehouse_id(client, args.warehouse_id)
        for _ in range(6):
            try:
                inference_result = _aggregate_sql(client, warehouse_id, TABLE)
                if inference_result.rows:
                    break
            except Exception as exc:
                inference_error = str(exc)
            time.sleep(10)

    intended_query = f"""
SELECT date_trunc('minute', request_time) AS minute,
       count(*) AS n_requests,
       round(avg(execution_duration_ms), 2) AS avg_latency_ms,
       sum(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS errors
FROM {TABLE}
GROUP BY 1
ORDER BY 1
""".strip()
    evidence = {
        "endpoint": args.endpoint,
        "inference_table": TABLE,
        "configuration": gateway_response,
        "configuration_error": gateway_error,
        "traffic": [
            {
                "client_request_id": item["client_request_id"],
                "question": item["question"],
                "route_history": (
                    item.get("response", {})
                    .get("custom_outputs", {})
                    .get("route_history", [])
                ),
            }
            for item in traffic
        ],
        "aggregate_query": (
            inference_result.statement if inference_result else intended_query
        ),
        "aggregate_columns": inference_result.columns if inference_result else [],
        "aggregate_rows": inference_result.rows if inference_result else [],
        "query_note": (
            None
            if inference_result and inference_result.rows
            else (
                "The workspace rejected inference tables for this agent endpoint "
                "type, so the documented SQL could not produce rows."
                if gateway_error
                else "Inference delivery is asynchronous; re-run with --skip-enable."
            )
        ),
        "last_error": inference_error,
    }
    (RESULTS / "inference_table_evidence.json").write_text(
        json.dumps(evidence, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"trace": trace_evidence, "inference": evidence}, indent=2))


if __name__ == "__main__":
    main()
