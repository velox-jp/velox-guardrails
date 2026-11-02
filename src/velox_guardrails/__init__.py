"""velox_guardrails: small, dependency-free guardrails for LLM applications."""

from .breaker import CircuitBreaker, CircuitOpenError, State
from .budget import Budget, BudgetExceeded, BudgetStatus
from .injection import (
    DEFAULT_PATTERNS,
    InjectionResult,
    sanitize_injection,
    scan_injection,
)
from .jsonfix import parse_llm_json
from .pii import find_pii, mask_pii
from .retry import RetryDecision, check_retry

__version__ = "0.1.0"

__all__ = [
    "Budget",
    "BudgetExceeded",
    "BudgetStatus",
    "CircuitBreaker",
    "CircuitOpenError",
    "DEFAULT_PATTERNS",
    "InjectionResult",
    "RetryDecision",
    "State",
    "check_retry",
    "find_pii",
    "mask_pii",
    "parse_llm_json",
    "sanitize_injection",
    "scan_injection",
]
