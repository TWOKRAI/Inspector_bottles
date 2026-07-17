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
    THROTTLE_CLEAR_MARKER,
    THROTTLE_REMOVE,
    apply_telemetry_reconfigure,
    detect_throttle_caps,
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

    def test_throttle_empty_dict_without_defaults_clears_rules(self) -> None:
        """throttle={} БЕЗ default_throttle_rules → set_rules({}) (backward-compat).

        Адресная операторская команда без источника дефолтов сохраняет прежнее
        поведение: пустая секция снимает все правила. Возврат к дефолтам — только когда
        дефолты переданы (декларативный файловый путь), см. Task 2.1.
        """
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


class TestThrottleBootReloadCoherence:
    """Task 2.1 (находка B): единая семантика пустоты throttle — boot ≡ reload.

    Пустая throttle-секция (``{}``/``None``) в replace-режиме → boot-дефолты (когда
    они переданы). Полная очистка — только явным :data:`THROTTLE_CLEAR_MARKER`.
    """

    _DEFAULTS = {"processes.**.state.fps": 0.05, "processes.**.state.latency_ms": 0.05}

    def test_empty_throttle_with_defaults_restores_boot_rules(self) -> None:
        """throttle={} + default_throttle_rules → set_rules(defaults), НЕ пусто."""
        throttle = _FakeThrottle()
        throttle.rules = {"custom": 3.0}
        applied = apply_telemetry_reconfigure(
            {"throttle": {}}, store_throttle=throttle, default_throttle_rules=self._DEFAULTS
        )
        assert applied == {"throttle": True}
        assert throttle.rules == self._DEFAULTS  # вернулись boot-дефолты, не {}

    def test_none_throttle_value_with_defaults_restores_boot_rules(self) -> None:
        """throttle=None (ключ есть) + defaults → тоже boot-дефолты (симметрично {})."""
        throttle = _FakeThrottle()
        throttle.rules = {"custom": 3.0}
        apply_telemetry_reconfigure({"throttle": None}, store_throttle=throttle, default_throttle_rules=self._DEFAULTS)
        assert throttle.rules == self._DEFAULTS

    def test_clear_marker_wipes_rules_even_with_defaults(self) -> None:
        """Явный {"__clear__": true} → set_rules({}) даже когда дефолты переданы."""
        throttle = _FakeThrottle()
        throttle.rules = {"custom": 3.0}
        applied = apply_telemetry_reconfigure(
            {"throttle": {THROTTLE_CLEAR_MARKER: True}},
            store_throttle=throttle,
            default_throttle_rules=self._DEFAULTS,
        )
        assert applied == {"throttle": True}
        assert throttle.rules == {}  # намеренная полная очистка

    def test_clear_marker_wipes_in_merge_mode(self) -> None:
        """Clear-маркер снимает всё и в merge-режиме (перекрывает per-правило дельту)."""
        throttle = _FakeThrottle()
        throttle.rules = {"keep": 5.0, "a.b": 1.0}
        apply_telemetry_reconfigure({"throttle": {THROTTLE_CLEAR_MARKER: True}}, mode="merge", store_throttle=throttle)
        assert throttle.set_calls == 1  # полная очистка через set_rules({})
        assert throttle.rules == {}

    def test_nonempty_throttle_ignores_defaults(self) -> None:
        """Непустая секция применяется как есть — дефолты не подмешиваются."""
        throttle = _FakeThrottle()
        applied = apply_telemetry_reconfigure(
            {"throttle": {"x.y": 2.0}}, store_throttle=throttle, default_throttle_rules=self._DEFAULTS
        )
        assert applied == {"throttle": True}
        assert throttle.rules == {"x.y": 2.0}  # ровно заданное, без дефолтов

    def test_clear_marker_strict_true_only(self) -> None:
        """Маркер срабатывает только на ``is True``: truthy-значение ≠ full-clear.

        Гипотетическое правило с именем ключа ``__clear__`` и числовым значением НЕ должно
        случайно снести весь набор — применяется как обычное правило (replace).
        """
        throttle = _FakeThrottle()
        throttle.rules = {"old": 1.0}
        apply_telemetry_reconfigure({"throttle": {THROTTLE_CLEAR_MARKER: 0.5}}, store_throttle=throttle)
        assert throttle.rules == {THROTTLE_CLEAR_MARKER: 0.5}  # НЕ пусто — не сработал clear


class TestUnknownModeRejected:
    """Task 1.2 (замечание ревьюера Task 1.1): неизвестный mode → явная ошибка, не replace."""

    def test_unknown_mode_rejected(self) -> None:
        """Опечатка mode='mrege' → error-dict, НИ ОДНА плоскость не применена (не wipe)."""
        hb, throttle = _FakeHeartbeat(), _FakeThrottle()
        throttle.rules = {"keep": 5.0}
        result = apply_telemetry_reconfigure(
            {"publish": {"metrics": {"fps": {"enabled": False}}}, "throttle": {"a.b": 2.0}},
            mode="mrege",  # опечатка «merge»
            heartbeat=hb,
            store_throttle=throttle,
        )
        # Наблюдаемая ошибка вместо молчаливого деструктивного replace.
        assert "error" in result
        assert result["mode"] == "mrege"
        assert "publish" not in result and "throttle" not in result
        # НИЧЕГО не тронуто: gate не пересобран, правила троттла целы.
        assert hb.calls == [] and hb.modes == []
        assert throttle.set_calls == 0 and throttle.update_calls == [] and throttle.remove_calls == []
        assert throttle.rules == {"keep": 5.0}  # соседнее правило НЕ стёрто

    def test_valid_modes_still_apply(self) -> None:
        """Контроль: replace/merge остаются рабочими (валидация не ломает валидные режимы)."""
        for mode in ("replace", "merge"):
            hb = _FakeHeartbeat()
            result = apply_telemetry_reconfigure({"publish": {"x": 1}}, mode=mode, heartbeat=hb)
            assert result == {"publish": True}
            assert hb.modes == [mode]


class _RulesThrottle:
    """Стаб троттла: отдаёт снимок правил через ``rules`` (как ThrottleMiddleware)."""

    def __init__(self, rules: dict) -> None:
        self.rules = dict(rules)


class TestDetectThrottleCaps:
    """Task 1.3: «no silent caps» — publisher-поднятие ниже central-правила → явный отчёт.

    detect_throttle_caps НЕ трогает троттл (auto-relax отвергнут ADR-PM-017) — только
    сообщает инициатору о потолке, чтобы тот осознанно ослабил central-правило.
    """

    def test_publisher_below_central_rule_is_reported(self) -> None:
        """publisher fps=0.2с ниже central 1.0с → метрика в отчёте (троттл срезал бы)."""
        throttle = _RulesThrottle({"processes.**.state.fps": 1.0})
        caps = detect_throttle_caps({"metrics": {"fps": {"interval_sec": 0.2}}}, throttle)
        assert caps == {"fps": {"publisher_interval_sec": 0.2, "throttle_interval_sec": 1.0}}

    def test_publisher_above_central_rule_not_reported(self) -> None:
        """publisher fps=2.0с выше central 1.0с → троттл не режет → отчёт пуст."""
        throttle = _RulesThrottle({"processes.**.state.fps": 1.0})
        assert detect_throttle_caps({"metrics": {"fps": {"interval_sec": 2.0}}}, throttle) == {}

    def test_soft_default_does_not_cap(self) -> None:
        """Мягкий дефолт-троттл (0.05с) ниже поднятого publisher (0.1с) → caps пуст."""
        throttle = _RulesThrottle({"processes.**.state.fps": 0.05})
        assert detect_throttle_caps({"metrics": {"fps": {"interval_sec": 0.1}}}, throttle) == {}

    def test_full_block_rule_is_reported(self) -> None:
        """central-правило 0 (полная блокировка) строже любого publisher → в отчёте."""
        throttle = _RulesThrottle({"processes.**.state.fps": 0})
        caps = detect_throttle_caps({"metrics": {"fps": {"interval_sec": 0.5}}}, throttle)
        assert caps == {"fps": {"publisher_interval_sec": 0.5, "throttle_interval_sec": 0.0}}

    def test_metric_without_explicit_interval_skipped(self) -> None:
        """interval_sec не задан (наследование default) → не флагуем (неоднозначно)."""
        throttle = _RulesThrottle({"processes.**.state.fps": 1.0})
        assert detect_throttle_caps({"metrics": {"fps": {"enabled": False}}}, throttle) == {}

    def test_metric_without_central_rule_skipped(self) -> None:
        """Нет central-правила под метрику → нечему резать → пусто."""
        throttle = _RulesThrottle({"processes.**.state.latency_ms": 1.0})
        assert detect_throttle_caps({"metrics": {"fps": {"interval_sec": 0.1}}}, throttle) == {}

    def test_suffix_match_is_generic(self) -> None:
        """Сопоставление по суффиксу паттерна: worker-метрика effective_hz тоже ловится."""
        throttle = _RulesThrottle({"processes.**.workers.*.effective_hz": 1.0})
        caps = detect_throttle_caps({"metrics": {"effective_hz": {"interval_sec": 0.1}}}, throttle)
        assert caps == {"effective_hz": {"publisher_interval_sec": 0.1, "throttle_interval_sec": 1.0}}

    def test_no_throttle_or_no_metrics_is_empty(self) -> None:
        assert detect_throttle_caps({"metrics": {"fps": {"interval_sec": 0.1}}}, None) == {}
        assert detect_throttle_caps({}, _RulesThrottle({"processes.**.state.fps": 1.0})) == {}
        assert detect_throttle_caps(None, _RulesThrottle({"x": 1.0})) == {}

    def test_strictest_rule_wins_on_multiple_candidates(self) -> None:
        """Несколько правил под метрику → берём строжайшее (макс. интервал)."""
        throttle = _RulesThrottle({"a.fps": 0.5, "processes.**.state.fps": 2.0})
        caps = detect_throttle_caps({"metrics": {"fps": {"interval_sec": 0.1}}}, throttle)
        assert caps["fps"]["throttle_interval_sec"] == 2.0


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
        """Телеметрия в файле не объявлена → троттл не трогаем (observability-only reload)."""
        throttle = _FakeThrottle()
        throttle.rules = {"keep": 5.0}
        on_reload = make_telemetry_on_reload(store_throttle=throttle)
        on_reload(Config(initial_data={"observability": {"log_level": "DEBUG"}}))
        assert throttle.set_calls == 0
        assert throttle.rules == {"keep": 5.0}  # правила целы

    def test_throttle_removed_from_file_resets_to_defaults(self) -> None:
        """Task 2.1: throttle РЕАЛЬНО удалён из файла (был → нет) → boot-дефолты (не stale)."""
        defaults = {"processes.**.state.fps": 0.05}
        throttle = _FakeThrottle()
        on_reload = make_telemetry_on_reload(store_throttle=throttle, default_throttle_rules=defaults)
        # 1-й reload: throttle задан в файле → применён.
        on_reload(Config(initial_data={"telemetry": {"throttle": {"custom.rule": 9.0}}}))
        assert throttle.rules == {"custom.rule": 9.0}
        # 2-й reload: throttle УДАЛЁН из файла (осталась только publish) → возврат к дефолтам.
        on_reload(Config(initial_data={"telemetry": {"publish": {"default_interval_sec": 2.0}}}))
        assert throttle.rules == defaults

    def test_unrelated_reload_preserves_runtime_throttle(self) -> None:
        """HIGH-регресс (ревью 2026-07-17): несвязанная правка файла НЕ откатывает runtime-дельту.

        throttle никогда не было в файле; оператор задал правило рантайм-командой; правка
        observability.log_level (тот же файл) НЕ должна молча снести операторское правило.
        """
        defaults = {"processes.**.state.fps": 0.05}
        throttle = _FakeThrottle()
        on_reload = make_telemetry_on_reload(store_throttle=throttle, default_throttle_rules=defaults)
        # 1-й reload: в файле только publish, throttle отсутствует → троттл не тронут.
        on_reload(Config(initial_data={"telemetry": {"publish": {"default_interval_sec": 2.0}}}))
        # Оператор задал правило рантайм-командой (эмуляция telemetry.broadcast).
        throttle.rules = {"operator.rule": 0.5}
        # 2-й reload: правка НЕсвязанной секции; throttle в файле как не было, так и нет.
        on_reload(
            Config(
                initial_data={
                    "observability": {"log_level": "DEBUG"},
                    "telemetry": {"publish": {"default_interval_sec": 3.0}},
                }
            )
        )
        assert throttle.rules == {"operator.rule": 0.5}  # runtime-дельта цела, не откатана

    def test_reload_empty_throttle_restores_defaults(self) -> None:
        """Task 2.1: throttle={} в файле → boot-дефолты (boot ≡ reload)."""
        defaults = {"processes.**.state.fps": 0.05}
        throttle = _FakeThrottle()
        throttle.rules = {"custom.rule": 9.0}
        on_reload = make_telemetry_on_reload(store_throttle=throttle, default_throttle_rules=defaults)
        on_reload(Config(initial_data={"telemetry": {"throttle": {}}}))
        assert throttle.rules == defaults

    def test_reload_custom_throttle_overrides_defaults(self) -> None:
        """Непустой throttle в файле применяется как есть, дефолты не подмешиваются."""
        defaults = {"processes.**.state.fps": 0.05}
        throttle = _FakeThrottle()
        on_reload = make_telemetry_on_reload(store_throttle=throttle, default_throttle_rules=defaults)
        on_reload(Config(initial_data={"telemetry": {"throttle": {"a.b": 4.0}}}))
        assert throttle.rules == {"a.b": 4.0}
