"""Governed Unity Catalog tools used by Extra-Credit Assignment 1."""

from __future__ import annotations

import os

DEFAULT_FUNCTION_BASENAMES = (
    "growth_rate",
    "percentage_change",
    "compare_values",
    "to_billions",
)


def function_names(
    catalog: str | None = None,
    schema: str | None = None,
) -> list[str]:
    """Return the configured fully qualified Unity Catalog function names."""
    override = os.environ.get("UC_FUNCTION_NAMES", "")
    if override.strip():
        names = [name.strip() for name in override.split(",") if name.strip()]
    else:
        resolved_catalog = catalog or os.environ.get("UC_CATALOG", "main")
        resolved_schema = schema or os.environ.get("UC_SCHEMA", "default")
        names = [
            f"{resolved_catalog}.{resolved_schema}.{basename}"
            for basename in DEFAULT_FUNCTION_BASENAMES
        ]
    invalid = [name for name in names if len(name.split(".")) != 3]
    if invalid:
        raise ValueError(
            "UC function names must use catalog.schema.function: " + ", ".join(invalid)
        )
    return names


__all__ = ["DEFAULT_FUNCTION_BASENAMES", "function_names"]
