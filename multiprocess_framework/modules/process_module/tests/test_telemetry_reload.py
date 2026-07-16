# -*- coding: utf-8 -*-
"""Тесты единой точки применения telemetry-секции (PC 3.1).

``apply_telemetry_reconfigure`` — идемпотентный путь, общий для ``telemetry.reconfigure``,
``config.reload`` (data["telemetry"]) и файлового watcher'а (``make_telemetry_on_reload``).
Проверяем: применение по НАЛИЧИЮ ключа, обе плоскости независимы, «нет приёмника» видно
в результате, watcher применяет только throttle (граница Task 3.1/3.2).
"""

from __future__ import annotations

from multiprocess_framework.modules.config_module.core.config import Config
from multiprocess_framework.modules.process_module.managers.telemetry_reload import (
    THROTTLE_REMOVE,
    apply_telemetry_reconfigure,
    make_telemetry_on_reload,
)


class _FakeHeartbeat:
    def __init__(self) -> None:
        self.calls: list = []
        self.modes: list = []

    def reconfigure_telemetry(self, publish, *, mode: str = "replace") -> None:
        self.calls.append(publish)
        self.modes.append(mode)


class _FakeThrottle:
    """Стаб ThrottleMiddleware: держит правила + считает вызовы каждого мутатора.

    Поддерживает и replace-путь (``set_rules``), и merge-путь (``update_rule`` /
    ``remove_rule``) — так тесты проверяют И итоговое состояние правил, И ФАКТ, что
    merge зовёт именно per-правило API (оживший PC 0.1), а не полную замену.
    """

    def __init__(self) -> None:
        self.rules: dict = {}
        self.set_calls = 0
        self.update_calls: list = []
        self.remove_calls: list = []

    def set_rules(self, rules: dict) -> None:
        self.set_calls += 1
        self.rules = dict(rules)

    def update_rule(self, pattern: str, interval_sec: float) -> None:
        self.update_calls.append((pattern, interval_sec))
        self.rules[pattern] = interval_sec

    def remove_rule(self, pattern: str) -> bool:
        self.remove_calls.append(pattern)
        return self.rules.pop(pattern, None) is not None


class TestApplyTelemetryReconfigure:
    def test_publish_only_applies_to_heartbeat(self) -> None:
        hb, throttle = _FakeHeartbeat(), _FakeThrottle()
        section = {"publish": {"metrics": {"fps": {"enabled": False}}}}
        applied = apply_telemetry_reconfigure(section, heartbeat=hb, store_throttle=throttle)
        assert applied == {"publish": True}
        assert hb.calls == [{"metrics": {"fps": {"enabled": False}}}]
        assert throttle.set_calls == 0  # throttle НЕ трогается без ключа

    def test_throttle_only_applies_to_store(self) -> None:
        hb, throttle = _FakeHeartbeat(), _FakeThrottle()
        section = {"throttle": {"processes.**.state.fps": 2.0}}
        applied = apply_telemetry_reconfigure(section, heartbeat=hb, store_throttle=throttle)
        assert applied == {"throttle": True}
        assert throttle.rules == {"processes.**.state.fps": 2.0}
        assert hb.calls == []  # publish НЕ трогается без ключа

    def test_both_planes_applied(self) -> None:
        hb, throttle = _FakeHeartbeat(), _FakeThrottle()
        section = {"publish": {"default_interval_sec": 3.0}, "throttle": {"a.b": 1.0}}
        applied = apply_telemetry_reconfigure(section, heartbeat=hb, store_throttle=throttle)
        assert applied == {"publish": True, "throttle": True}
        assert hb.calls == [{"default_interval_sec": 3.0}]
        assert throttle.rules == {"a.b": 1.0}

    def test_publish_none_value_still_applied(self) -> None:
        """publish=None (ключ присутствует) → reconfigure_telemetry(None) — выключить gate."""
        hb = _FakeHeartbeat()
        applied = apply_telemetry_reconfigure({"publish": None}, heartbeat=hb)
        assert applied == {"publish": True}
        assert hb.calls == [None]

    def test_publish_without_receiver_reports_false(self) -> None:
        """publish запрошен, но heartbeat None → нет приёмника (False)."""
        applied = apply_telemetry_reconfigure({"publish": {}}, heartbeat=None)
        assert applied == {"publish": False}

    def test_throttle_without_receiver_reports_false(self) -> None:
        applied = apply_telemetry_reconfigure({"throttle": {"a": 1.0}}, store_throttle=None)
        assert applied == {"throttle": False}

    def test_empty_section_applies_nothing(self) -> None:
        hb, throttle = _FakeHeartbeat(), _FakeThrottle()
        assert apply_telemetry_reconfigure({}, heartbeat=hb, store_throttle=throttle) == {}
        assert apply_telemetry_reconfigure(None, heartbeat=hb, store_throttle=throttle) == {}
        assert hb.calls == [] and throttle.set_calls == 0

    def test_throttle_empty_dict_clears_rules(self) -> None:
        """throttle={} (ключ есть) → set_rules({}) снимает все правила."""
        throttle = _FakeThrottle()
        throttle.rules = {"old": 1.0}
        applied = apply_telemetry_reconfigure({"throttle": {}}, store_throttle=throttle)
        assert applied == {"throttle": True}
        assert throttle.rules == {}

    def test_default_mode_is_replace(self) -> None:
        """mode не передан → heartbeat получает mode='replace' (backward-compat)."""
        hb = _FakeHeartbeat()
        apply_telemetry_reconfigure({"publish": {"x": 1}}, heartbeat=hb)
        assert hb.modes == ["replace"]

    def test_mode_forwarded_to_heartbeat(self) -> None:
        """mode='merge' прокидывается в heartbeat.reconfigure_telemetry."""
        hb = _FakeHeartbeat()
        apply_telemetry_reconfigure({"publish": {"x": 1}}, mode="merge", heartbeat=hb)
        assert hb.modes == ["merge"]


class TestThrottleMergeMode:
    """Task 1.1: throttle-плоскость в merge-режиме — per-правило update/remove."""

    def test_replace_mode_calls_set_rules(self) -> None:
        """mode='replace' (дефолт) → set_rules (полная замена), НЕ per-правило."""
        throttle = _FakeThrottle()
        throttle.rules = {"keep": 5.0}
        applied = apply_telemetry_reconfigure({"throttle": {"a.b": 2.0}}, mode="replace", store_throttle=throttle)
        assert applied == {"throttle": True}
        assert throttle.set_calls == 1
        assert throttle.update_calls == [] and throttle.remove_calls == []
        assert throttle.rules == {"a.b": 2.0}  # 'keep' снесён (replace)

    def test_merge_updates_single_rule_keeps_others(self) -> None:
        """mode='merge' меняет ТОЛЬКО одно правило, остальные не тронуты (через update_rule)."""
        throttle = _FakeThrottle()
        throttle.rules = {"keep": 5.0, "a.b": 1.0}
        applied = apply_telemetry_reconfigure({"throttle": {"a.b": 2.0}}, mode="merge", store_throttle=throttle)
        assert applied == {"throttle": True}
        assert throttle.set_calls == 0  # НЕ полная замена
        assert throttle.update_calls == [("a.b", 2.0)]
        assert throttle.rules == {"keep": 5.0, "a.b": 2.0}  # 'keep' сохранён

    def test_merge_none_marker_removes_rule(self) -> None:
        """mode='merge' + None-значение (THROTTLE_REMOVE) → remove_rule, правило исчезает."""
        throttle = _FakeThrottle()
        throttle.rules = {"keep": 5.0, "drop.me": 1.0}
        applied = apply_telemetry_reconfigure(
            {"throttle": {"drop.me": THROTTLE_REMOVE}}, mode="merge", store_throttle=throttle
        )
        assert applied == {"throttle": True}
        assert throttle.remove_calls == ["drop.me"]
        assert throttle.update_calls == []
        assert throttle.rules == {"keep": 5.0}  # только drop.me удалён

    def test_merge_zero_is_block_rule_not_removal(self) -> None:
        """0 — валидное правило «полная блокировка», НЕ маркер удаления (update_rule)."""
        throttle = _FakeThrottle()
        applied = apply_telemetry_reconfigure({"throttle": {"block.me": 0}}, mode="merge", store_throttle=throttle)
        assert applied == {"throttle": True}
        assert throttle.update_calls == [("block.me", 0)]
        assert throttle.remove_calls == []
        assert throttle.rules == {"block.me": 0}

    def test_merge_without_per_rule_api_reports_no_receiver(self) -> None:
        """merge требует update_rule/remove_rule — их нет → applied False (нет приёмника)."""

        class _OnlySetRules:
            def set_rules(self, rules: dict) -> None: ...

        applied = apply_telemetry_reconfigure({"throttle": {"a": 1.0}}, mode="merge", store_throttle=_OnlySetRules())
        assert applied == {"throttle": False}


class TestMakeTelemetryOnReload:
    def test_applies_throttle_from_config(self) -> None:
        """on_reload читает telemetry.throttle из Config и применяет к троттлу."""
        throttle = _FakeThrottle()
        on_reload = make_telemetry_on_reload(store_throttle=throttle)
        on_reload(Config(initial_data={"telemetry": {"throttle": {"processes.**.state.fps": 5.0}}}))
        assert throttle.rules == {"processes.**.state.fps": 5.0}

    def test_publish_in_file_does_not_touch_gate(self) -> None:
        """Граница 3.1/3.2: publish в файле НЕ применяется (heartbeat=None), throttle — да."""
        throttle = _FakeThrottle()
        on_reload = make_telemetry_on_reload(store_throttle=throttle)
        cfg = Config(
            initial_data={
                "telemetry": {
                    "publish": {"metrics": {"fps": {"enabled": False}}},
                    "throttle": {"x.y": 2.0},
                }
            }
        )
        on_reload(cfg)  # не должно падать; publish просто «нет приёмника»
        assert throttle.rules == {"x.y": 2.0}

    def test_no_telemetry_section_noop(self) -> None:
        throttle = _FakeThrottle()
        on_reload = make_telemetry_on_reload(store_throttle=throttle)
        on_reload(Config(initial_data={"observability": {"log_level": "DEBUG"}}))
        assert throttle.set_calls == 0
