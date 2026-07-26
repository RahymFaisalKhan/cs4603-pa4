"""Load the supervisor prompt through an MLflow Prompt Registry alias."""

from __future__ import annotations

import os

from agent.prompts import MULTI_SUPERVISOR_PROMPT


def load_supervisor_prompt_with_version() -> tuple[str, str | None]:
    """Return the aliased prompt and version, with an offline-safe fallback."""
    uri = os.environ.get("SUPERVISOR_PROMPT_URI", "").strip()
    if not uri:
        return MULTI_SUPERVISOR_PROMPT, None

    try:
        import mlflow

        mlflow.set_registry_uri("databricks-uc")
        prompt = mlflow.genai.load_prompt(
            uri,
            cache_ttl_seconds=0,
        )
        template = prompt.template
        if not isinstance(template, str):
            raise TypeError("The supervisor prompt must be a text template")
        return template, str(prompt.version)
    except Exception:
        if os.environ.get("PROMPT_REGISTRY_REQUIRED", "").lower() in {
            "1",
            "true",
            "yes",
        }:
            raise
        return MULTI_SUPERVISOR_PROMPT, None


def load_supervisor_prompt() -> str:
    """Return the production-aliased prompt text used by the agent."""
    return load_supervisor_prompt_with_version()[0]
