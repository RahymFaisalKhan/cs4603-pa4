"""Code-level fallback guardrails for agent endpoints without Gateway policies."""

from __future__ import annotations

import re
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

PII_PATTERN = re.compile(
    r"(?ix)"
    r"(?:\b\d{5}-?\d{7}-?\d\b)"  # Pakistani CNIC
    r"|(?:\b\d{3}-\d{2}-\d{4}\b)"  # US SSN
    r"|(?:\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b)"  # email
)

REJECTION_MESSAGES = {
    "pii_blocked": (
        "Request blocked: remove personal identifiers such as CNICs, SSNs, "
        "or email addresses and try again."
    ),
    "rate_limited": (
        "Request blocked: this user exceeded the configured two requests per "
        "rolling minute. Try again later."
    ),
}


@dataclass
class RollingWindowGuard:
    """Apply PII blocking and a per-user rolling-window request limit."""

    max_per_minute: int = 2
    clock: Callable[[], float] = time.time
    calls: dict[str, list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def check(self, user_id: str, prompt: str) -> str | None:
        """Return a rejection reason, or ``None`` when the request may proceed."""
        now = self.clock()
        with self._lock:
            recent = [
                timestamp
                for timestamp in self.calls[user_id]
                if now - timestamp < 60
            ]
            self.calls[user_id] = recent
            if len(recent) >= self.max_per_minute:
                return "rate_limited"
            if PII_PATTERN.search(prompt):
                return "pii_blocked"
            recent.append(now)
            return None


def rejection_message(reason: str) -> str:
    """Return a stable, non-sensitive response for a blocked request."""
    return REJECTION_MESSAGES.get(reason, "Request blocked by policy.")
