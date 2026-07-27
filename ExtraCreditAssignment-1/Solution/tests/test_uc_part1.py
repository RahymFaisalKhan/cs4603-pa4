"""Offline validation for Extra-Credit Assignment 1 Part 1."""

from __future__ import annotations

import math

from deployment.deploy_uc import uc_resources
from uc_tools.register_functions import (
    compare_values,
    growth_rate,
    percentage_change,
)


def test_python_uc_function_implementations_match_known_results():
    assert math.isclose(growth_rate(16.91, 0.08, 3), 21.30172992)
    assert percentage_change(100, 125) == 25
    assert compare_values(16.91, 15) == "16.91 (a) is larger by 1.91"


def test_uc_deployment_declares_llm_vector_index_and_all_functions(monkeypatch):
    monkeypatch.setenv("DATABRICKS_MODEL", "llm-endpoint")
    monkeypatch.setenv("VECTOR_SEARCH_INDEX", "cs4603.pa4.index")
    monkeypatch.setenv("UC_CATALOG", "cs4603")
    monkeypatch.setenv("UC_SCHEMA", "pa4")
    monkeypatch.delenv("UC_FUNCTION_NAMES", raising=False)

    resources = uc_resources()
    assert [type(resource).__name__ for resource in resources] == [
        "DatabricksServingEndpoint",
        "DatabricksVectorSearchIndex",
        "DatabricksFunction",
        "DatabricksFunction",
        "DatabricksFunction",
        "DatabricksFunction",
    ]
    assert [resource.name for resource in resources[2:]] == [
        "cs4603.pa4.growth_rate",
        "cs4603.pa4.percentage_change",
        "cs4603.pa4.compare_values",
        "cs4603.pa4.to_billions",
    ]
