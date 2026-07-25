# -*- coding: utf-8 -*-
"""Тесты экспоненциального backoff + jitter супервизора (NEW-6a).

``ProcessMonitor._compute_backoff`` — чистый staticmethod: задержка перед рестартом
для попытки (1-based) по RestartPolicy. Проверяем fixed/exponential/cap/jitter +
обратную совместимость дефолтов.
"""

from __future__ import annotations

from ..core.restart_policy import RestartPolicy
from ..monitor.process_monitor import ProcessMonitor

_cb = ProcessMonitor._compute_backoff


class TestFixedMode:
    def test_default_is_fixed(self) -> None:
        p = RestartPolicy(backoff_sec=2.0)
        assert p.backoff_mode == "fixed"
        assert p.backoff_jitter == 0.0

    def test_fixed_constant_across_attempts(self) -> None:
        p = RestartPolicy(backoff_sec=2.5)
        assert _cb(p, 1) == 2.5
        assert _cb(p, 5) == 2.5
        assert _cb(p, 99) == 2.5


class TestExponentialMode:
    def test_doubles_from_base(self) -> None:
        p = RestartPolicy(backoff_sec=2.0, backoff_mode="exponential", backoff_max_sec=100.0)
        assert [_cb(p, a) for a in range(1, 6)] == [2.0, 4.0, 8.0, 16.0, 32.0]

    def test_first_attempt_equals_base(self) -> None:
        p = RestartPolicy(backoff_sec=3.0, backoff_mode="exponential")
        assert _cb(p, 1) == 3.0

    def test_capped_at_max(self) -> None:
        p = RestartPolicy(backoff_sec=2.0, backoff_mode="exponential", backoff_max_sec=20.0)
        assert _cb(p, 5) == 20.0  # 2*2^4=32 → cap 20
        assert _cb(p, 50) == 20.0


class TestJitter:
    def test_zero_jitter_deterministic(self) -> None:
        p = RestartPolicy(backoff_sec=10.0, backoff_jitter=0.0)
        assert _cb(p, 1, rand=0.0) == 10.0
        assert _cb(p, 1, rand=0.999) == 10.0

    def test_jitter_endpoints(self) -> None:
        p = RestartPolicy(backoff_sec=10.0, backoff_jitter=0.3)
        assert _cb(p, 1, rand=0.5) == 10.0  # середина — без изменения
        assert abs(_cb(p, 1, rand=0.0) - 7.0) < 1e-9  # 10*(1-0.3)
        assert _cb(p, 1, rand=1.0) == 13.0  # 10*(1+0.3)

    def test_jitter_within_bounds(self) -> None:
        p = RestartPolicy(backoff_sec=8.0, backoff_jitter=0.25)
        for r in (0.0, 0.1, 0.37, 0.5, 0.83, 0.999):
            v = _cb(p, 1, rand=r)
            assert 6.0 <= v <= 10.0  # [8*0.75, 8*1.25]

    def test_jitter_clamped_to_one(self) -> None:
        p = RestartPolicy(backoff_sec=5.0, backoff_jitter=2.0)  # >1 → 1.0
        assert _cb(p, 1, rand=0.0) == 0.0  # 5*(1-1)
        assert abs(_cb(p, 1, rand=1.0) - 10.0) < 1e-9  # 5*(1+1)

    def test_never_negative(self) -> None:
        p = RestartPolicy(backoff_sec=1.0, backoff_jitter=1.0)
        assert _cb(p, 1, rand=0.0) >= 0.0


class TestExponentialWithJitter:
    def test_exp_base_then_jitter(self) -> None:
        p = RestartPolicy(backoff_sec=2.0, backoff_mode="exponential", backoff_jitter=0.5)
        # attempt 3 → base 8; jitter r=0.5 → без изменения
        assert _cb(p, 3, rand=0.5) == 8.0
        # r=0 → 8*0.5=4
        assert _cb(p, 3, rand=0.0) == 4.0


class TestBackwardCompat:
    def test_policy_from_legacy_dict(self) -> None:
        # старый recipe-dict без новых полей → RestartPolicy с дефолтами (fixed)
        legacy = {"enabled": True, "max_retries": 3, "backoff_sec": 2.0, "window_sec": 60.0}
        p = RestartPolicy(**legacy)
        assert p.backoff_mode == "fixed"
        assert _cb(p, 1) == 2.0 and _cb(p, 4) == 2.0

    def test_policy_accepts_new_fields_from_dict(self) -> None:
        rp = {"enabled": True, "backoff_mode": "exponential", "backoff_max_sec": 30.0, "backoff_jitter": 0.2}
        p = RestartPolicy(**rp)
        assert p.backoff_mode == "exponential"
        assert p.backoff_max_sec == 30.0
        assert p.backoff_jitter == 0.2
