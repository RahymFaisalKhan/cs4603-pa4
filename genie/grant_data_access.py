"""Grant least-privilege UC access to the deployed agent's service principal."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from databricks.sdk import WorkspaceClient

from genie.build_tables import _warehouse_id, execute_sql
from genie.space_config import table_names

ROOT = Path(__file__).resolve().parents[1]


def grant_statements(catalog: str, schema: str, principal: str) -> list[str]:
    """Return the minimum UC privileges Genie needs on its underlying data."""
    if any(character in principal for character in ("`", "'")):
        raise ValueError("principal cannot contain a quote or backtick")
    segment_table, income_table = table_names(catalog, schema)
    quoted = f"`{principal}`"
    return [
        f"GRANT USE CATALOG ON CATALOG {catalog} TO {quoted}",
        f"GRANT USE SCHEMA ON SCHEMA {catalog}.{schema} TO {quoted}",
        f"GRANT SELECT ON TABLE {segment_table} TO {quoted}",
        f"GRANT SELECT ON TABLE {income_table} TO {quoted}",
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default=os.environ.get("DATABRICKS_PROFILE"))
    parser.add_argument("--catalog", default=os.environ.get("UC_CATALOG", "cs4603"))
    parser.add_argument("--schema", default=os.environ.get("UC_SCHEMA", "pa4"))
    parser.add_argument("--warehouse-id", default=os.environ.get("DATABRICKS_WAREHOUSE_ID"))
    parser.add_argument("--principal", required=True)
    args = parser.parse_args()

    client = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
    warehouse_id = _warehouse_id(client, args.warehouse_id)
    for statement in grant_statements(args.catalog, args.schema, args.principal):
        execute_sql(client, warehouse_id, statement)
    verification_queries = [
        (
            "SELECT grantee, catalog_name, privilege_type "
            f"FROM {args.catalog}.information_schema.catalog_privileges "
            f"WHERE grantee = '{args.principal}'"
        ),
        (
            "SELECT grantee, catalog_name, schema_name, privilege_type "
            f"FROM {args.catalog}.information_schema.schema_privileges "
            f"WHERE grantee = '{args.principal}' AND schema_name = '{args.schema}'"
        ),
        (
            "SELECT grantee, table_catalog, table_schema, table_name, privilege_type "
            f"FROM {args.catalog}.information_schema.table_privileges "
            f"WHERE grantee = '{args.principal}' AND table_schema = '{args.schema}' "
            "AND table_name LIKE 'meridian_%' ORDER BY table_name"
        ),
    ]
    grants = [
        asdict(
            execute_sql(
                client,
                warehouse_id,
                query,
            )
        )
        for query in verification_queries
    ]
    evidence = {
        "principal": args.principal,
        "privileges": [
            "USE CATALOG on " + args.catalog,
            f"USE SCHEMA on {args.catalog}.{args.schema}",
            *[f"SELECT on {table}" for table in table_names(args.catalog, args.schema)],
        ],
        "grants": grants,
    }
    evidence_path = ROOT / "genie" / "grant_evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))
    print(f"Wrote {evidence_path}")


if __name__ == "__main__":
    main()
