"""Create or update the curated Meridian Genie Space from source control."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from databricks.sdk import WorkspaceClient

from genie.build_tables import _warehouse_id
from genie.space_config import (
    SPACE_DESCRIPTION,
    SPACE_TITLE,
    build_serialized_space,
    table_names,
)

ROOT = Path(__file__).resolve().parents[1]


def create_or_update_space(
    client: WorkspaceClient,
    *,
    warehouse_id: str,
    catalog: str,
    schema: str,
):
    """Idempotently create or update the one project-owned Genie Space."""
    serialized_space = build_serialized_space(catalog, schema)
    listed = client.genie.list_spaces()
    existing = next(
        (space for space in listed.spaces or [] if space.title == SPACE_TITLE),
        None,
    )
    if existing:
        current = client.genie.get_space(
            existing.space_id,
            include_serialized_space=True,
        )
        space = client.genie.update_space(
            existing.space_id,
            title=SPACE_TITLE,
            description=SPACE_DESCRIPTION,
            warehouse_id=warehouse_id,
            serialized_space=serialized_space,
            etag=current.etag,
        )
        action = "updated"
    else:
        username = client.current_user.me().user_name
        space = client.genie.create_space(
            warehouse_id=warehouse_id,
            title=SPACE_TITLE,
            description=SPACE_DESCRIPTION,
            parent_path=f"/Workspace/Users/{username}",
            serialized_space=serialized_space,
        )
        action = "created"
    return action, space


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default=os.environ.get("DATABRICKS_PROFILE"))
    parser.add_argument("--catalog", default=os.environ.get("UC_CATALOG", "cs4603"))
    parser.add_argument("--schema", default=os.environ.get("UC_SCHEMA", "pa4"))
    parser.add_argument("--warehouse-id", default=os.environ.get("DATABRICKS_WAREHOUSE_ID"))
    args = parser.parse_args()

    client = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
    warehouse_id = _warehouse_id(client, args.warehouse_id)
    action, space = create_or_update_space(
        client,
        warehouse_id=warehouse_id,
        catalog=args.catalog,
        schema=args.schema,
    )
    evidence = {
        "action": action,
        "space_id": space.space_id,
        "title": SPACE_TITLE,
        "description": SPACE_DESCRIPTION,
        "warehouse_id": warehouse_id,
        "tables": list(table_names(args.catalog, args.schema)),
        "curation": {
            "general_instruction_count": 1,
            "trusted_query_count": 2,
            "sample_question_count": 3,
        },
    }
    evidence_path = ROOT / "genie" / "space_evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))
    print(f"Wrote {evidence_path}")


if __name__ == "__main__":
    main()
