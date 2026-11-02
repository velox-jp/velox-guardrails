"""Retry-loop guard: stop on attempt count or accumulated cost."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetryDecision:
    allowed: bool
    reason: str = ""


def check_retry(
    attempt: int,
    cumulative_cost: float = 0.0,
    max_attempts: int = 5,
    max_cost: float | None = None,
) -> RetryDecision:
    """Call before each retry. `attempt` is the number of attempts already made.

    Returns allowed=False once attempt >= max_attempts or cumulative_cost >= max_cost.
    Cost is in whatever unit you use; the library does not assume a currency.
    """
    if attempt >= max_attempts:
        return RetryDecision(False, f"attempt limit reached ({max_attempts})")
    if max_cost is not None and cumulative_cost >= max_cost:
        return RetryDecision(False, f"cost limit reached ({max_cost})")
    return RetryDecision(True)
