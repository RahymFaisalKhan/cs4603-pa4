"""Canonical, source-controlled configuration for the Meridian Genie Space."""

from __future__ import annotations

import json

SEGMENT_TABLE_BASENAME = "meridian_segment_financials"
INCOME_TABLE_BASENAME = "meridian_income_statement"
SPACE_TITLE = "Meridian Financial Analytics"
SPACE_DESCRIPTION = (
    "Governed structured analysis of Meridian Motor Corporation segment and "
    "income-statement results for FY2022 and FY2023."
)


def table_names(catalog: str, schema: str) -> tuple[str, str]:
    """Return the fully qualified segment and income-statement table names."""
    return (
        f"{catalog}.{schema}.{SEGMENT_TABLE_BASENAME}",
        f"{catalog}.{schema}.{INCOME_TABLE_BASENAME}",
    )


def build_space_payload(catalog: str, schema: str) -> dict:
    """Build the version-2 serialized Genie Space payload."""
    segment_table, income_table = table_names(catalog, schema)
    return {
        "version": 2,
        "config": {
            "sample_questions": [
                {
                    "id": "8b1536654f024f51a27d483822ade101",
                    "question": ["Rank Meridian's FY2023 segments by revenue."],
                },
                {
                    "id": "94a31a00de6e4c9fbe26a976510ad202",
                    "question": ["Which segment improved operating margin the most year over year?"],
                },
                {
                    "id": "e6fe3cdfce244d28988ca4b0ab18d303",
                    "question": ["Compare FY2022 and FY2023 net revenue and operating profit."],
                },
            ]
        },
        "data_sources": {
            "tables": [
                {
                    "identifier": income_table,
                    "description": [
                        "Condensed consolidated statement of operations, one row per "
                        "fiscal year and line item. Expense rows are stored as negative "
                        "raw-yen amounts."
                    ],
                    "column_configs": [
                        {
                            "column_name": "fiscal_year",
                            "enable_format_assistance": True,
                        },
                        {
                            "column_name": "line_item",
                            "enable_entity_matching": True,
                        },
                    ],
                },
                {
                    "identifier": segment_table,
                    "description": [
                        "One row per fiscal year and reportable segment. Revenue and "
                        "operating income are raw Japanese yen; units_sold is nullable "
                        "for segments without a meaningful unit count."
                    ],
                    "column_configs": [
                        {
                            "column_name": "fiscal_year",
                            "enable_format_assistance": True,
                        },
                        {
                            "column_name": "segment",
                            "enable_entity_matching": True,
                        },
                    ],
                },
            ]
        },
        "instructions": {
            "text_instructions": [
                {
                    "id": "fb321a1081934cb9904ee3a63901e401",
                    "content": [
                        "All monetary columns are raw Japanese yen. Divide by "
                        "1,000,000,000 for billions and by 1,000,000,000,000 for "
                        "trillions, and label the scale. 'FY2023' means "
                        "fiscal_year = 2023. Prefer revenue_yen for segment revenue. "
                        "Compute operating margin as operating_income_yen / revenue_yen. "
                        "An unqualified 'net income' means the 'Net income attributable "
                        "to owners' line item, not 'Profit for the year'. Never mix "
                        "segment totals with consolidated income-statement line items."
                    ],
                }
            ],
            "example_question_sqls": [
                {
                    "id": "a967017398b444bc947aa1e2798fe602",
                    "question": ["Show year-over-year revenue growth by segment for FY2023."],
                    "sql": [
                        "SELECT current.segment,\n",
                        "       prior.revenue_yen / 1000000000.0 AS fy2022_revenue_billion_yen,\n",
                        "       current.revenue_yen / 1000000000.0 AS fy2023_revenue_billion_yen,\n",
                        "       (current.revenue_yen - prior.revenue_yen) * 100.0\n",
                        "         / prior.revenue_yen AS yoy_growth_pct\n",
                        f"FROM {segment_table} current\n",
                        f"JOIN {segment_table} prior ON current.segment = prior.segment\n",
                        "WHERE current.fiscal_year = 2023 AND prior.fiscal_year = 2022\n",
                        "ORDER BY yoy_growth_pct DESC",
                    ],
                },
                {
                    "id": "f333deea926a4d4084194762123ce501",
                    "question": ["Rank Meridian's FY2023 segments by revenue."],
                    "sql": [
                        "SELECT segment, revenue_yen / 1000000000.0 AS revenue_billion_yen\n",
                        f"FROM {segment_table}\n",
                        "WHERE fiscal_year = 2023\n",
                        "ORDER BY revenue_yen DESC",
                    ],
                },
            ],
        },
    }


def build_serialized_space(catalog: str, schema: str) -> str:
    """Return the compact JSON string required by the Genie Spaces API."""
    return json.dumps(build_space_payload(catalog, schema), separators=(",", ":"))
