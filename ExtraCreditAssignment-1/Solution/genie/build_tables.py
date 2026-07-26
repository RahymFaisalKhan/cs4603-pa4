"""Create and verify the governed Delta tables used by the Meridian Genie Space."""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import Disposition, StatementState

from genie.space_config import table_names

ROOT = Path(__file__).resolve().parents[1]
TERMINAL_STATES = {
    StatementState.CANCELED,
    StatementState.CLOSED,
    StatementState.FAILED,
    StatementState.SUCCEEDED,
}


@dataclass
class QueryResult:
    statement: str
    columns: list[str]
    rows: list[list[str | None]]


def _warehouse_id(client: WorkspaceClient, explicit: str | None) -> str:
    if explicit:
        return explicit
    warehouses = list(client.warehouses.list())
    if not warehouses:
        raise RuntimeError("No Databricks SQL warehouse is available")
    running = next((item for item in warehouses if str(item.state) == "RUNNING"), None)
    return str((running or warehouses[0]).id)


def execute_sql(client: WorkspaceClient, warehouse_id: str, statement: str) -> QueryResult:
    """Execute one statement, wait for completion, and normalize inline rows."""
    response = client.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=warehouse_id,
        disposition=Disposition.INLINE,
        wait_timeout="50s",
    )
    while response.status and response.status.state not in TERMINAL_STATES:
        time.sleep(1)
        response = client.statement_execution.get_statement(response.statement_id)
    state = response.status.state if response.status else None
    if state != StatementState.SUCCEEDED:
        error = response.status.error.message if response.status and response.status.error else state
        raise RuntimeError(f"SQL statement failed: {error}\n{statement}")
    columns = []
    if response.manifest and response.manifest.schema:
        columns = [column.name for column in response.manifest.schema.columns or []]
    rows = response.result.data_array if response.result and response.result.data_array else []
    return QueryResult(statement=statement, columns=columns, rows=rows)


def build_statements(catalog: str, schema: str) -> list[str]:
    """Return idempotent table DDL, source rows, and ownership-only grants."""
    segment_table, income_table = table_names(catalog, schema)
    return [
        f"""
CREATE OR REPLACE TABLE {segment_table} (
  fiscal_year INT NOT NULL COMMENT 'Fiscal year ending March 31, expressed as a four-digit year.',
  segment STRING NOT NULL COMMENT 'Meridian reportable business segment.',
  revenue_yen BIGINT NOT NULL COMMENT 'External net revenue in raw Japanese yen.',
  operating_income_yen BIGINT NOT NULL COMMENT 'Segment operating profit in raw Japanese yen.',
  units_sold BIGINT COMMENT 'Units sold in the fiscal year; NULL for non-unit-based segments.'
)
USING DELTA
COMMENT 'Meridian reportable-segment financials for FY2022-FY2023, derived from the FY2023 annual report; FY2022 segment allocation is explicitly synthesized and reconciles to consolidated totals.'
""".strip(),
        f"""
INSERT OVERWRITE {segment_table} VALUES
  (2022, 'Automobile',             11030000000000, 430000000000,  3680000),
  (2022, 'Motorcycle',              2120000000000, 310000000000, 17000000),
  (2022, 'Financial Services',       1030000000000, 145000000000,     NULL),
  (2022, 'Power Products & Other',    370000000000,  20000000000,     NULL),
  (2023, 'Automobile',             12900000000000, 560000000000,  4070000),
  (2023, 'Motorcycle',              2510000000000, 360000000000, 18500000),
  (2023, 'Financial Services',       1100000000000, 180000000000,     NULL),
  (2023, 'Power Products & Other',    400000000000,  24000000000,     NULL)
""".strip(),
        f"""
CREATE OR REPLACE TABLE {income_table} (
  fiscal_year INT NOT NULL COMMENT 'Fiscal year ending March 31, expressed as a four-digit year.',
  display_order INT NOT NULL COMMENT 'Presentation order in the condensed statement of operations.',
  line_item STRING NOT NULL COMMENT 'Consolidated income-statement line item.',
  amount_yen BIGINT NOT NULL COMMENT 'Amount in raw Japanese yen; costs and expenses are negative.'
)
USING DELTA
COMMENT 'Meridian condensed consolidated statement of operations for FY2022-FY2023, transcribed from the FY2023 annual report.'
""".strip(),
        f"""
INSERT OVERWRITE {income_table} VALUES
  (2022,  1, 'Net revenue',                         14550000000000),
  (2022,  2, 'Cost of sales',                      -11780000000000),
  (2022,  3, 'Gross profit',                         2770000000000),
  (2022,  4, 'SG&A expenses',                       -1050000000000),
  (2022,  5, 'R&D expense',                          -815000000000),
  (2022,  6, 'Operating profit',                      905000000000),
  (2022,  7, 'Finance income, net',                    62000000000),
  (2022,  8, 'Share of profit of associates',         140000000000),
  (2022,  9, 'Profit before tax',                    1107000000000),
  (2022, 10, 'Income tax expense',                   -360000000000),
  (2022, 11, 'Profit for the year',                    747000000000),
  (2022, 12, 'Net income attributable to owners',      707000000000),
  (2022, 13, 'Net income attributable to NCI',          40000000000),
  (2023,  1, 'Net revenue',                         16910000000000),
  (2023,  2, 'Cost of sales',                      -13560000000000),
  (2023,  3, 'Gross profit',                         3350000000000),
  (2023,  4, 'SG&A expenses',                       -1346000000000),
  (2023,  5, 'R&D expense',                          -880000000000),
  (2023,  6, 'Operating profit',                     1124000000000),
  (2023,  7, 'Finance income, net',                    78000000000),
  (2023,  8, 'Share of profit of associates',         168000000000),
  (2023,  9, 'Profit before tax',                    1370000000000),
  (2023, 10, 'Income tax expense',                   -233000000000),
  (2023, 11, 'Profit for the year',                   1137000000000),
  (2023, 12, 'Net income attributable to owners',     1107000000000),
  (2023, 13, 'Net income attributable to NCI',          30000000000)
""".strip(),
    ]


def validation_queries(catalog: str, schema: str) -> list[str]:
    segment_table, income_table = table_names(catalog, schema)
    return [
        f"""
SELECT fiscal_year,
       SUM(revenue_yen) AS segment_revenue_yen,
       SUM(operating_income_yen) AS segment_operating_income_yen
FROM {segment_table}
GROUP BY fiscal_year
ORDER BY fiscal_year
""".strip(),
        f"""
SELECT fiscal_year, line_item, amount_yen
FROM {income_table}
WHERE line_item IN ('Net revenue', 'Operating profit', 'Net income attributable to owners')
ORDER BY fiscal_year, display_order
""".strip(),
        f"DESCRIBE TABLE EXTENDED {segment_table}",
        f"DESCRIBE TABLE EXTENDED {income_table}",
        f"SHOW GRANTS ON TABLE {segment_table}",
        f"SHOW GRANTS ON TABLE {income_table}",
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default=os.environ.get("DATABRICKS_PROFILE"))
    parser.add_argument("--catalog", default=os.environ.get("UC_CATALOG", "cs4603"))
    parser.add_argument("--schema", default=os.environ.get("UC_SCHEMA", "pa4"))
    parser.add_argument("--warehouse-id", default=os.environ.get("DATABRICKS_WAREHOUSE_ID"))
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Leave existing tables untouched and only regenerate validation evidence.",
    )
    args = parser.parse_args()

    client = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
    warehouse_id = _warehouse_id(client, args.warehouse_id)
    if not args.validate_only:
        for statement in build_statements(args.catalog, args.schema):
            print(f"Executing: {statement.splitlines()[0]}", flush=True)
            execute_sql(client, warehouse_id, statement)
    validation = [
        asdict(execute_sql(client, warehouse_id, statement))
        for statement in validation_queries(args.catalog, args.schema)
    ]
    evidence = {
        "catalog": args.catalog,
        "schema": args.schema,
        "warehouse_id": warehouse_id,
        "source": "data/annual_report.md",
        "derivation_note": (
            "FY2023 segment and both income-statement years are transcribed from the "
            "report. FY2022 segment rows are plausible synthesized allocations that "
            "sum exactly to reported revenue of 14.55T yen and operating profit of "
            "905B yen."
        ),
        "validation": validation,
    }
    evidence_path = ROOT / "genie" / "table_evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))
    print(f"Wrote {evidence_path}")


if __name__ == "__main__":
    main()
