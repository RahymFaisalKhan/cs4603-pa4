"""Register, verify, and grant access to the Part 1 Unity Catalog functions."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import PermissionsChange, Privilege, SecurableType
from dotenv import load_dotenv
from unitycatalog.ai.core.databricks import DatabricksFunctionClient

from uc_tools import function_names

ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = Path(__file__).with_name("functions.sql")


def growth_rate(start_value: float, rate: float, years: float) -> float:
    """Project a value using compound annual growth.

    Args:
        start_value: Starting value before growth is applied.
        rate: Annual growth rate as a decimal, such as 0.08 for eight percent.
        years: Number of years over which the value compounds.

    Returns:
        The value after applying compound annual growth.
    """
    if start_value < 0:
        raise ValueError("start_value must be non-negative")
    if rate <= -1:
        raise ValueError("rate must be greater than -1")
    if years < 0:
        raise ValueError("years must be non-negative")
    return start_value * (1 + rate) ** years


def percentage_change(old_value: float, new_value: float) -> float:
    """Calculate percentage change from an old value to a new value.

    Args:
        old_value: Baseline value used as the percentage denominator.
        new_value: New value to compare with the baseline.

    Returns:
        Percentage change, where positive values are increases and negative values are decreases.
    """
    if old_value == 0:
        raise ValueError("percentage change is undefined when old_value is zero")
    return (new_value - old_value) / abs(old_value) * 100


def compare_values(a: float, b: float) -> str:
    """Compare two numeric values and describe the absolute difference.

    Args:
        a: First value to compare.
        b: Second value to compare.

    Returns:
        A concise statement identifying the larger value and absolute difference.
    """
    if a == b:
        return f"{a:g} and {b:g} are equal"
    larger = a if a > b else b
    label = "a" if a > b else "b"
    return f"{larger:g} ({label}) is larger by {abs(a - b):g}"


PYTHON_FUNCTIONS = (growth_rate, percentage_change, compare_values)
VERIFICATION_CASES: dict[str, tuple[dict[str, float], Any]] = {
    "growth_rate": (
        {"start_value": 16.91, "rate": 0.08, "years": 3.0},
        21.30172992,
    ),
    "percentage_change": (
        {"old_value": 100.0, "new_value": 125.0},
        25.0,
    ),
    "compare_values": (
        {"a": 16.91, "b": 15.0},
        "16.91 (a) is larger by 1.91",
    ),
    "to_billions": (
        {"amount_yen": 16_910_000_000_000.0},
        16_910.0,
    ),
}


def _result_value(result: Any) -> Any:
    error = getattr(result, "error", None)
    if error:
        raise RuntimeError(str(error))
    return getattr(result, "value", result)


def _matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, float):
        return math.isclose(float(actual), expected, rel_tol=1e-9, abs_tol=1e-9)
    return str(actual) == expected


def register_functions(
    client: DatabricksFunctionClient,
    catalog: str,
    schema: str,
) -> list[str]:
    """Create or replace all governed Part 1 functions."""
    created: list[str] = []
    for function in PYTHON_FUNCTIONS:
        info = client.create_python_function(
            func=function,
            catalog=catalog,
            schema=schema,
            replace=True,
        )
        name = getattr(info, "full_name", f"{catalog}.{schema}.{function.__name__}")
        created.append(name)
        print(f"Registered Python function: {name}")

    sql = SQL_PATH.read_text().format(catalog=catalog, schema=schema)
    info = client.create_function(sql_function_body=sql)
    sql_name = getattr(info, "full_name", f"{catalog}.{schema}.to_billions")
    created.append(sql_name)
    print(f"Registered SQL function: {sql_name}")
    return created


def verify_functions(
    client: DatabricksFunctionClient,
    names: list[str],
) -> dict[str, Any]:
    """Execute every function directly and validate its known result."""
    evidence: dict[str, Any] = {}
    for name in names:
        basename = name.rsplit(".", 1)[-1]
        parameters, expected = VERIFICATION_CASES[basename]
        actual = _result_value(client.execute_function(name, parameters=parameters))
        if not _matches(actual, expected):
            raise AssertionError(f"{name} returned {actual!r}; expected {expected!r}")
        evidence[name] = {
            "parameters": parameters,
            "result": actual,
            "status": "passed",
        }
        print(f"Verified {name}: {actual}")
    return evidence


def grant_execute(
    workspace: WorkspaceClient,
    names: list[str],
    principals: list[str],
) -> dict[str, Any]:
    """Grant EXECUTE on every function and return the resulting ACL evidence."""
    grants: dict[str, Any] = {}
    for name in names:
        for principal in principals:
            workspace.grants.update(
                SecurableType.FUNCTION.value,
                name,
                changes=[
                    PermissionsChange(
                        add=[Privilege.EXECUTE],
                        principal=principal,
                    )
                ],
            )
        response = workspace.grants.get(
            SecurableType.FUNCTION.value,
            name,
        )
        assignments = [
            {
                "principal": assignment.principal,
                "privileges": [privilege.value for privilege in assignment.privileges or []],
            }
            for assignment in response.privilege_assignments or []
        ]
        grants[name] = assignments
        print(f"Permissions for {name}: {assignments}")
    return grants


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=os.environ.get("UC_CATALOG", "main"))
    parser.add_argument("--schema", default=os.environ.get("UC_SCHEMA", "default"))
    parser.add_argument(
        "--profile",
        default=os.environ.get("DATABRICKS_PROFILE") or None,
        help="Databricks CLI profile; unified authentication is used when omitted.",
    )
    parser.add_argument(
        "--grant-to",
        action="append",
        default=[],
        metavar="PRINCIPAL",
        help="User/group/service principal to grant EXECUTE; repeat as needed.",
    )
    parser.add_argument(
        "--skip-grants",
        action="store_true",
        help="Register and verify without changing function ACLs.",
    )
    parser.add_argument(
        "--evidence-file",
        type=Path,
        default=ROOT / "uc_tools" / "registration_evidence.json",
    )
    return parser


def main() -> None:
    load_dotenv()
    args = _parser().parse_args()
    workspace = WorkspaceClient(profile=args.profile)
    client = DatabricksFunctionClient(client=workspace)

    names = register_functions(client, args.catalog, args.schema)
    expected_names = function_names(args.catalog, args.schema)
    if names != expected_names:
        raise AssertionError(f"Registered names {names!r} do not match {expected_names!r}")
    verification = verify_functions(client, names)

    principals = args.grant_to
    if not principals and not args.skip_grants:
        current_user = workspace.current_user.me()
        principal = current_user.user_name or current_user.id
        if not principal:
            raise RuntimeError("Could not resolve the current Databricks principal")
        principals = [principal]
    grants = {} if args.skip_grants else grant_execute(workspace, names, principals)

    evidence = {
        "catalog": args.catalog,
        "schema": args.schema,
        "functions": names,
        "verification": verification,
        "grants": grants,
    }
    args.evidence_file.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_file.write_text(json.dumps(evidence, indent=2, default=str) + "\n")
    print(f"Wrote evidence: {args.evidence_file}")


if __name__ == "__main__":
    main()
