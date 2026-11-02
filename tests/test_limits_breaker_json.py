import json
import os
import tempfile
import threading
import unittest

from velox_guardrails import (
    Budget,
    BudgetExceeded,
    CircuitBreaker,
    CircuitOpenError,
    State,
    check_retry,
    parse_llm_json,
)

PRICES = {"small": (0.1, 0.5), "big": (1.0, 5.0)}


class RetryTests(unittest.TestCase):
    def test_attempt_boundary(self):
        self.assertTrue(check_retry(4).allowed)
        d = check_retry(5)
        self.assertFalse(d.allowed)
        self.assertIn("attempt", d.reason)

    def test_cost_boundary(self):
        self.assertTrue(check_retry(0, 9.99, max_cost=10).allowed)
        self.assertFalse(check_retry(0, 10, max_cost=10).allowed)

    def test_no_cost_limit_by_default(self):
        self.assertTrue(check_retry(0, 1e9).allowed)


class BudgetTests(unittest.TestCase):
    def test_cost_and_limit(self):
        b = Budget(PRICES, daily_limit=2.0, today=lambda: "2026-01-01")
        self.assertAlmostEqual(b.record("big", 1000, 100), 1.5)
        st = b.check()
        self.assertTrue(st.ok)
        self.assertFalse(st.warning)  # 1.5 / 2.0 = 75%, below the 80% default
        self.assertAlmostEqual(st.remaining, 0.5)

    def test_warning_and_exceeded(self):
        b = Budget(PRICES, daily_limit=2.0, today=lambda: "2026-01-01")
        b.record("big", 1000, 200)  # 2.0
        self.assertFalse(b.check().ok)
        with self.assertRaises(BudgetExceeded):
            b.ensure_available()

    def test_day_rollover(self):
        day = ["2026-01-01"]
        b = Budget(PRICES, daily_limit=1.0, today=lambda: day[0])
        b.record("big", 1000, 0)
        self.assertFalse(b.check().ok)
        day[0] = "2026-01-02"
        self.assertTrue(b.check().ok)
        self.assertAlmostEqual(b.month_total("2026-01"), 1.0)

    def test_unknown_model(self):
        b = Budget(PRICES, daily_limit=1.0)
        with self.assertRaises(KeyError):
            b.record("nope", 1, 1)
        b2 = Budget(PRICES, daily_limit=1.0, default_price=(1.0, 1.0))
        self.assertAlmostEqual(b2.record("nope", 1000, 0), 1.0)

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "spend.json")
            Budget(PRICES, 10, path=p, today=lambda: "2026-01-01").record("small", 1000, 0)
            b = Budget(PRICES, 10, path=p, today=lambda: "2026-01-01")
            self.assertAlmostEqual(b.used_today(), 0.1)
            with open(p, encoding="utf-8") as f:
                self.assertIn("2026-01-01", json.load(f))

    def test_threads(self):
        b = Budget(PRICES, 1e9, today=lambda: "2026-01-01")
        ts = [threading.Thread(target=lambda: [b.record("small", 1000, 0) for _ in range(50)]) for _ in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertAlmostEqual(b.used_today(), 40.0, places=4)


class BreakerTests(unittest.TestCase):
    def make(self, **kw):
        self.now = 0.0
        return CircuitBreaker("t", failure_threshold=2, recovery_timeout=10, clock=lambda: self.now, **kw)

    @staticmethod
    def boom():
        raise ValueError("x")

    def test_closed_open_half_open_close(self):
        cb = self.make()
        self.assertIs(cb.state, State.CLOSED)
        self.assertEqual(cb.call(self.boom, fallback="fb"), "fb")
        self.assertIs(cb.state, State.CLOSED)
        cb.call(self.boom, fallback="fb")
        self.assertIs(cb.state, State.OPEN)
        # open: function is not even called
        calls = []
        self.assertEqual(cb.call(lambda: calls.append(1), fallback="fb"), "fb")
        self.assertEqual(calls, [])
        self.now = 10
        self.assertIs(cb.state, State.HALF_OPEN)
        self.assertEqual(cb.call(lambda: "ok"), "ok")
        self.assertIs(cb.state, State.CLOSED)

    def test_half_open_failure_reopens(self):
        cb = self.make()
        cb.call(self.boom, fallback=0)
        cb.call(self.boom, fallback=0)
        self.now = 10
        self.assertIs(cb.state, State.HALF_OPEN)
        cb.call(self.boom, fallback=0)
        self.assertIs(cb.state, State.OPEN)
        self.now = 15  # recovery counted from the new failure
        self.assertIs(cb.state, State.OPEN)

    def test_open_without_fallback_raises(self):
        cb = self.make()
        for _ in range(2):
            with self.assertRaises(ValueError):
                cb.call(self.boom)
        with self.assertRaises(CircuitOpenError):
            cb.call(lambda: 1)

    def test_none_fallback_is_respected(self):
        cb = self.make()
        self.assertIsNone(cb.call(self.boom, fallback=None))

    def test_success_resets_failure_count(self):
        cb = self.make()
        cb.call(self.boom, fallback=0)
        cb.call(lambda: 1)
        cb.call(self.boom, fallback=0)
        self.assertIs(cb.state, State.CLOSED)
        self.assertEqual(cb.status()["total_failures"], 2)


class JsonTests(unittest.TestCase):
    def test_return_info(self):
        from velox_guardrails import parse_llm_json as p
        self.assertEqual(p('{"a": 1}', return_info=True), ({"a": 1}, False))
        self.assertEqual(p('{"a": [1, 2', return_info=True), ({"a": [1, 2]}, True))
        self.assertEqual(p('{"a": 1,}', return_info=True), ({"a": 1}, True))
        fenced = "```json" + chr(10) + '{"a": 1}' + chr(10) + "```"
        self.assertEqual(p(fenced, return_info=True), ({"a": 1}, True))
        self.assertEqual(p("nothing", return_info=True), (None, False))
        self.assertEqual(p('{"a": 1}'), {"a": 1})

    def test_plain(self):
        self.assertEqual(parse_llm_json('{"a": 1}'), {"a": 1})

    def test_code_fence_and_prose(self):
        t = 'Sure! Here you go:\n```json\n{"a": 1, "b": "x}y"}\n```\nHope that helps {really}.'
        self.assertEqual(parse_llm_json(t), {"a": 1, "b": "x}y"})

    def test_prose_around_without_fence(self):
        self.assertEqual(parse_llm_json('Result: {"a": {"b": 2}} done.'), {"a": {"b": 2}})

    def test_truncated(self):
        self.assertEqual(parse_llm_json('{"a": 1, "b": "hel'), {"a": 1, "b": "hel"})
        self.assertEqual(parse_llm_json('{"a": [1, 2, {"c": 3'), {"a": [1, 2, {"c": 3}]})
        self.assertEqual(parse_llm_json('{"a": 1, "b":'), {"a": 1, "b": None})
        self.assertEqual(parse_llm_json('{"a": 1, '), {"a": 1})
        self.assertEqual(parse_llm_json('{"a": 1, "b"'), {"a": 1, "b": None})

    def test_trailing_comma(self):
        self.assertEqual(parse_llm_json('{"a": [1, 2,], "b": 1,}'), {"a": [1, 2], "b": 1})

    def test_required_and_defaults(self):
        self.assertIsNone(parse_llm_json('{"a": 1}', required=["b"]))
        self.assertIsNone(parse_llm_json('{"a": null}', required=["a"]))
        self.assertEqual(parse_llm_json('{"a": 1}', required=["a"], defaults={"b": 2}), {"a": 1, "b": 2})

    def test_failures(self):
        for t in [None, "", "   ", "no json here", "[1, 2, 3]", "{broken: yes}"]:
            with self.subTest(t=t):
                self.assertIsNone(parse_llm_json(t))

    def test_japanese(self):
        self.assertEqual(parse_llm_json('```json\n{"要約": "こんにちは"}\n```'), {"要約": "こんにちは"})


if __name__ == "__main__":
    unittest.main()
