"""Offline validation for the Part 4 bonus challenges."""

from __future__ import annotations

from bonus.guardrails import RollingWindowGuard, rejection_message


def test_guard_blocks_email_without_counting_it_as_an_allowed_call():
    guard = RollingWindowGuard(clock=lambda: 100.0)
    assert guard.check("user", "Email me at analyst@example.com") == "pii_blocked"
    assert guard.calls["user"] == []
    assert "personal identifiers" in rejection_message("pii_blocked")


def test_guard_rate_limits_third_request_in_rolling_minute():
    now = [100.0]
    guard = RollingWindowGuard(max_per_minute=2, clock=lambda: now[0])
    assert guard.check("user", "one") is None
    assert guard.check("user", "two") is None
    assert guard.check("user", "three") == "rate_limited"
    now[0] = 161.0
    assert guard.check("user", "allowed after window") is None


def test_guard_detects_cnic_and_ssn():
    guard = RollingWindowGuard(clock=lambda: 100.0)
    assert guard.check("cnic", "CNIC 35202-1234567-1") == "pii_blocked"
    assert guard.check("ssn", "SSN 123-45-6789") == "pii_blocked"


def test_prompt_loader_uses_constant_when_registry_uri_is_unset(monkeypatch):
    monkeypatch.delenv("SUPERVISOR_PROMPT_URI", raising=False)
    from agent.prompt_registry import load_supervisor_prompt_with_version
    from agent.prompts import MULTI_SUPERVISOR_PROMPT

    assert load_supervisor_prompt_with_version() == (
        MULTI_SUPERVISOR_PROMPT,
        None,
    )
