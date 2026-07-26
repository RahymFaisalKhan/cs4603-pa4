"""Run the two required contrasting questions through the live Part 2 graph."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import mlflow
from databricks.sdk import WorkspaceClient
from databricks_langchain import ChatDatabricks, DatabricksVectorSearch
from unitycatalog.ai.core.databricks import DatabricksFunctionClient

from agent.graph_multi import build_graph_multi, load_genie_agent
from agent.graph_uc import load_uc_tools
from rag.store import CITATION_COLUMNS
from uc_tools import function_names

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = [
    "Rank Meridian's FY2023 segments by revenue.",
    "What risks did Meridian cite for its Automobile segment?",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default=os.environ.get("DATABRICKS_PROFILE"))
    parser.add_argument("--space-id", default=os.environ.get("GENIE_SPACE_ID"))
    parser.add_argument(
        "--model",
        default=os.environ.get(
            "DATABRICKS_MODEL",
            "databricks-meta-llama-3-3-70b-instruct",
        ),
    )
    parser.add_argument(
        "--vector-index",
        default=os.environ.get(
            "VECTOR_SEARCH_INDEX",
            "cs4603.pa4.pa4_analyst_index",
        ),
    )
    parser.add_argument("--catalog", default=os.environ.get("UC_CATALOG", "cs4603"))
    parser.add_argument("--schema", default=os.environ.get("UC_SCHEMA", "pa4"))
    args = parser.parse_args()
    if not args.space_id:
        raise OSError("Pass --space-id or set GENIE_SPACE_ID")

    if args.profile:
        os.environ["DATABRICKS_CONFIG_PROFILE"] = args.profile
        mlflow.set_tracking_uri(f"databricks://{args.profile}")
    client = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
    llm = ChatDatabricks(
        endpoint=args.model,
        temperature=0.0,
        workspace_client=client,
    )
    authorization = client.config.authenticate().get("Authorization", "")
    access_token = authorization.removeprefix("Bearer ").strip()
    if not access_token:
        raise RuntimeError("The selected Databricks profile did not yield an access token")
    vector_store = DatabricksVectorSearch(
        index_name=args.vector_index,
        columns=CITATION_COLUMNS,
        client_args={
            "workspace_url": client.config.host,
            "personal_access_token": access_token,
        },
    )
    function_client = DatabricksFunctionClient(client=client)
    tools = load_uc_tools(
        function_names=function_names(args.catalog, args.schema),
        client=function_client,
    )
    graph = build_graph_multi(
        llm=llm,
        retriever=vector_store.as_retriever(search_kwargs={"k": 4}),
        tools=tools,
        genie_agent=load_genie_agent(args.space_id, client=client),
    )

    evidence = []
    for question in QUESTIONS:
        print(f"Running: {question}", flush=True)
        result = graph.invoke({"messages": [{"role": "user", "content": question}]})
        record = {
            "question": question,
            "plan": result.get("plan", []),
            "route_history": result.get("route_history", []),
            "step_results": result.get("step_results", []),
            "final_answer": result.get("final_answer", ""),
        }
        evidence.append(record)
        print(json.dumps(record, indent=2), flush=True)

    evidence_path = ROOT / "genie" / "live_graph_evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"Wrote {evidence_path}")


if __name__ == "__main__":
    main()
