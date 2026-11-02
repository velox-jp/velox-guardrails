"""Daily spend tracker with a limit. You supply the price table and the currency."""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import date
from typing import Callable, Mapping


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class BudgetStatus:
    ok: bool
    used: float
    limit: float
    remaining: float
    warning: bool


class Budget:
    """Track spend per day.

    prices: {model: (input_per_1k_tokens, output_per_1k_tokens)} in your currency.
    daily_limit: ok becomes False when used >= daily_limit.
    path: optional JSON file; when set, totals survive restarts.
    today: optional function returning a "YYYY-MM-DD" string (useful in tests).
    """

    def __init__(
        self,
        prices: Mapping[str, tuple[float, float]],
        daily_limit: float,
        warn_ratio: float = 0.8,
        path: str | os.PathLike | None = None,
        default_price: tuple[float, float] | None = None,
        today: Callable[[], str] | None = None,
    ) -> None:
        self.prices = dict(prices)
        self.daily_limit = daily_limit
        self.warn_ratio = warn_ratio
        self.path = os.fspath(path) if path else None
        self.default_price = default_price
        self._today = today or (lambda: date.today().isoformat())
        self._lock = threading.Lock()
        self._log: dict = self._load()

    def estimate(self, model: str, input_tokens: int, output_tokens: int) -> float:
        price = self.prices.get(model, self.default_price)
        if price is None:
            raise KeyError(f"no price for model {model!r}; add it to prices or set default_price")
        return input_tokens / 1000 * price[0] + output_tokens / 1000 * price[1]

    def record(self, model: str, input_tokens: int, output_tokens: int, operation: str = "") -> float:
        cost = self.estimate(model, input_tokens, output_tokens)
        with self._lock:
            day = self._log.setdefault(self._today(), {"total": 0.0, "operations": []})
            day["total"] = round(day["total"] + cost, 6)
            day["operations"].append(
                {"op": operation, "model": model, "in": input_tokens, "out": output_tokens, "cost": round(cost, 6)}
            )
            del day["operations"][:-500]
            self._save()
        return cost

    def used_today(self) -> float:
        with self._lock:
            return self._log.get(self._today(), {}).get("total", 0.0)

    def check(self) -> BudgetStatus:
        used = self.used_today()
        limit = self.daily_limit
        return BudgetStatus(
            ok=used < limit,
            used=round(used, 6),
            limit=limit,
            remaining=round(limit - used, 6),
            warning=limit > 0 and used / limit >= self.warn_ratio,
        )

    def ensure_available(self) -> None:
        st = self.check()
        if not st.ok:
            raise BudgetExceeded(f"daily budget reached: {st.used} / {st.limit}")

    def month_total(self, month: str | None = None) -> float:
        """Sum for a "YYYY-MM" prefix (default: current month)."""
        month = month or self._today()[:7]
        with self._lock:
            return round(sum(d["total"] for k, d in self._log.items() if k.startswith(month)), 6)

    def _load(self) -> dict:
        if self.path and os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except (OSError, ValueError):
                pass
        return {}

    def _save(self) -> None:
        if not self.path:
            return
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._log, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
