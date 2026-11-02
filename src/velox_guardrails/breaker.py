"""Circuit breaker: CLOSED -> OPEN after repeated failures -> HALF_OPEN after a wait -> CLOSED."""
from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)
_NO_FALLBACK = object()


class State(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    pass


class CircuitBreaker:
    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 3,
        recovery_timeout: float = 60.0,
        success_threshold: int = 1,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self._clock = clock
        self._lock = threading.RLock()
        self._state = State.CLOSED
        self._failures = 0
        self._successes = 0
        self._opened_at = 0.0
        self.total_calls = 0
        self.total_failures = 0

    @property
    def state(self) -> State:
        with self._lock:
            if self._state is State.OPEN and self._clock() - self._opened_at >= self.recovery_timeout:
                self._state = State.HALF_OPEN
                self._successes = 0
                logger.info("breaker %s: half-open", self.name)
            return self._state

    def call(self, fn: Callable[..., Any], *args: Any, fallback: Any = _NO_FALLBACK, **kwargs: Any) -> Any:
        """Run fn.

        While open: return `fallback` if one was given (None counts), else raise CircuitOpenError.
        When fn raises: count a failure, then return `fallback` if given, else re-raise.
        """
        if self.state is State.OPEN:
            if fallback is _NO_FALLBACK:
                raise CircuitOpenError(f"circuit {self.name!r} is open")
            return fallback
        with self._lock:
            self.total_calls += 1
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self._on_failure()
            if fallback is _NO_FALLBACK:
                raise
            return fallback
        self._on_success()
        return result

    def _on_success(self) -> None:
        with self._lock:
            self._failures = 0
            if self._state is State.HALF_OPEN:
                self._successes += 1
                if self._successes >= self.success_threshold:
                    self._state = State.CLOSED
                    self._successes = 0
                    logger.info("breaker %s: closed", self.name)

    def _on_failure(self) -> None:
        with self._lock:
            self._failures += 1
            self.total_failures += 1
            if self._state is State.HALF_OPEN or self._failures >= self.failure_threshold:
                self._state = State.OPEN
                self._opened_at = self._clock()
                logger.warning("breaker %s: open", self.name)

    def reset(self) -> None:
        with self._lock:
            self._state = State.CLOSED
            self._failures = 0
            self._successes = 0

    def status(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "state": self.state.value,
                "failure_count": self._failures,
                "total_calls": self.total_calls,
                "total_failures": self.total_failures,
            }
