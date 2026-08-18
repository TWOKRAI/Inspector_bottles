# -*- coding: utf-8 -*-
"""Приёмочные тесты ``TelemetryPublishConfig.default_enabled`` (RED — поля ещё нет).

Поле ``default_enabled: bool = True`` отвечает на вопрос «что делать с метрикой,
для которой в ``metrics`` нет правила». Сегодня неперечисленная метрика ВСЕГДА
включена (конфиг сужает, а не работает белым списком) — ``default_enabled=False``
переворачивает это в «выключена, пока явно не включена».

Источник критериев — постановка задачи (акцептанс 1-6), не диффа реализации: поля
в схеме нет, тесты пишутся от ЖЕЛАЕМОГО поведения и обязаны быть КРАСНЫМИ до
реализации. Каждый тест СНАЧАЛА обращается к атрибуту ``cfg.default_enabled`` —
поле не объявлено, обращение падает ``AttributeError`` раньше, чем тест дойдёт до
``resolve()``/``due_metrics()``. После реализации та же строка перестаёт падать, и
тест начинает проверять реальное поведение (значение атрибута + резолв).

Критерий 5 — главный: свойство обязано держаться на ЖИВОМ гейте (``TelemetryGate``,
собранном ``ProcessHeartbeat._build_telemetry_gate()`` из секции
``telemetry.publish``), а не только на голом ``TelemetryPublishConfig.resolve()``, и
обязано гасить метрику, объявленную ПЛАГИНОМ через ``declare_metric``, наравне с
фреймворковыми именами — иначе регрессия «выключение работает для фреймворка и не
работает для плагина (или наоборот)» осталась бы невидимой. Рядом — обязательный
контроль (правило «неподключённый драйвер = ровный ноль»): та же связка БЕЗ
``default_enabled`` обязана пропустить хотя бы одну метрику, иначе красный тест
критерия 5 мог бы стать зелёным по причине, не имеющей отношения к самому полю.

Каталог метрик (``gated_metrics()``) наполняется ИМПОРТОМ производителей — импорт
обоих модулей ниже обязателен явно, иначе состав каталога зависит от того, что уже
успел импортировать сосед по сессии pytest (исторически воспроизведено — см.
комментарий в ``test_telemetry_publish_config.py``: семь телеметрийных тестов
краснели ТОЛЬКО в полном прогоне).
"""

from __future__ import annotations

import multiprocess_framework.modules.process_module.heartbeat.process_heartbeat  # noqa: F401,E402
import multiprocess_framework.modules.process_module.heartbeat.telemetry  # noqa: F401,E402
from multiprocess_framework.modules.observability_declarations import (
    KIND_METRIC,
    declare_metric,
    forget_declarations,
)
from multiprocess_framework.modules.process_module.configs import (
    MetricRule,
    TelemetryPublishConfig,
)
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.heartbeat.telemetry import gated_metrics


class TestSchemaDefaultEnabled:
    """Критерии 1-4, 6 — на голой схеме ``TelemetryPublishConfig.resolve()``/``unknown_metrics()``."""

    def test_criterion1_default_true_matches_todays_behavior(self) -> None:
        """Критерий 1: конфиг без ``default_enabled`` (как собирается сегодня) не
        меняет поведения для неперечисленной метрики — ``(True, default_interval_sec)``
        дословно как сейчас.

        Красный сейчас: поля ``default_enabled`` нет в схеме — обращение к атрибуту
        падает ``AttributeError`` раньше, чем тест дойдёт до ``resolve()``.
        """
        cfg = TelemetryPublishConfig(default_interval_sec=7.0)
        assert cfg.default_enabled is True
        enabled, interval = cfg.resolve("совершенно_неизвестная_метрика")
        assert enabled is True
        assert interval == 7.0

    def test_criterion2_default_false_disables_every_catalog_metric(self) -> None:
        """Критерий 2: ``default_enabled=False`` и пустой ``metrics`` → ЛЮБОЕ имя
        из каталога резолвится как ``enabled=False``.

        Красный сейчас: ``default_enabled=False`` в конструкторе молча отбрасывается
        (``SchemaBase`` extra=ignore — см. ``test_unknown_keys_ignored`` в
        ``test_telemetry_publish_config.py``) — ``resolve()`` по-прежнему отдаёт
        ``True`` для любой неперечисленной метрики. Падает ``AssertionError`` на
        первом же имени каталога (текущее значение ``True`` вместо ожидаемого ``False``).
        """
        catalog = gated_metrics()
        assert catalog, "каталог метрик пуст — производители не импортированы, тест выродится"
        cfg = TelemetryPublishConfig(default_enabled=False)
        assert cfg.default_enabled is False
        assert cfg.metrics == {}
        for name in catalog:
            enabled, _ = cfg.resolve(name)
            assert enabled is False, f"метрика {name!r} каталога осталась включена при default_enabled=False"

    def test_criterion3a_explicit_opt_in_keeps_its_own_interval(self) -> None:
        """Критерий 3 (свой интервал): ``default_enabled=False`` + явное правило
        ``{enabled: true, interval_sec: 0.25}`` — метрика включена СО СВОИМ
        интервалом, не с ``default_interval_sec``.

        Красный сейчас: атрибут ``default_enabled`` падает ``AttributeError``
        раньше, чем тест дойдёт до ``resolve()``.
        """
        cfg = TelemetryPublishConfig(
            default_enabled=False,
            default_interval_sec=9.0,
            metrics={"opt_in_own_interval": MetricRule(enabled=True, interval_sec=0.25)},
        )
        assert cfg.default_enabled is False
        enabled, interval = cfg.resolve("opt_in_own_interval")
        assert enabled is True
        assert interval == 0.25

    def test_criterion3b_explicit_opt_in_without_interval_inherits_default(self) -> None:
        """Критерий 3 (наследование интервала): ``default_enabled=False`` + явное
        правило ``{enabled: true}`` БЕЗ своего ``interval_sec`` — интервал наследует
        ``default_interval_sec``, как и до появления ``default_enabled``.

        Красный сейчас: атрибут ``default_enabled`` падает ``AttributeError``
        раньше, чем тест дойдёт до ``resolve()``.
        """
        cfg = TelemetryPublishConfig(
            default_enabled=False,
            default_interval_sec=4.5,
            metrics={"opt_in_inherits": MetricRule(enabled=True)},
        )
        assert cfg.default_enabled is False
        enabled, interval = cfg.resolve("opt_in_inherits")
        assert enabled is True
        assert interval == 4.5

    def test_criterion4_explicit_disabled_rule_still_wins_over_true_default(self) -> None:
        """Критерий 4 (старая дорога не сломана): ``default_enabled=True`` + явное
        правило ``{enabled: false}`` — метрика всё равно выключена.

        Красный сейчас: атрибут ``default_enabled`` падает ``AttributeError``
        раньше, чем тест дойдёт до ``resolve()``.
        """
        cfg = TelemetryPublishConfig(
            default_enabled=True,
            metrics={"legacy_disabled": MetricRule(enabled=False)},
        )
        assert cfg.default_enabled is True
        enabled, _ = cfg.resolve("legacy_disabled")
        assert enabled is False

    def test_criterion6_unknown_metrics_no_false_positive_when_default_disabled(self) -> None:
        """Критерий 6: пустой ``metrics`` при ``default_enabled=False`` не даёт
        ложных срабатываний ``unknown_metrics()``.

        Красный сейчас: атрибут ``default_enabled`` падает ``AttributeError``
        раньше, чем тест дойдёт до ``unknown_metrics()``.
        """
        cfg = TelemetryPublishConfig(default_enabled=False)
        assert cfg.default_enabled is False
        assert cfg.metrics == {}
        assert cfg.unknown_metrics() == set()


class _MinimalServices:
    """Минимальный дубль ``IProcessServices`` — только то, что реально читает
    ``ProcessHeartbeat._build_telemetry_gate()`` (``get_config``). Логирующие методы
    сознательно не добавлены: ``_warn_capped_metrics``/``_warn_unknown_metrics``
    дергают ``log_warning`` только когда есть что сказать (``tick_sec`` задан /
    ``unknown_metrics()`` непуст) — при пустом ``metrics`` и без ``tick_sec`` (наш
    случай) обе ветки выходят раньше, до обращения к логгеру.
    """

    def __init__(self, config: dict) -> None:
        self._config = config

    def get_config(self, key: str, default: object = None) -> object:
        return self._config.get(key, default)


#: Имя метрики, СИМУЛИРУЮЩЕЕ объявление стороннего плагина (как
#: ``Plugins/sources/capture/plugin.py`` зовёт ``ctx.declare_metric(...)`` на
#: импорте) — не фреймворковое имя, владелец не начинается с ``multiprocess_framework.``.
_PLUGIN_METRIC_NAME = "тестовая_метрика_плагина_default_enabled"
_PLUGIN_OWNER = "тестовый_плагин_default_enabled"


class TestLiveGateDefaultEnabled:
    """Критерий 5 (главный) — свойство держится на ЖИВОМ ``TelemetryGate``, не только на схеме."""

    def test_criterion5_live_gate_silences_whole_catalog_including_plugin_metric(self) -> None:
        """Процесс, поднятый с ``telemetry.publish.default_enabled: false``, не
        публикует НИ ОДНОЙ метрики каталога через живой гейт
        (``ProcessHeartbeat._build_telemetry_gate().due_metrics()``) — включая имя,
        объявленное ПЛАГИНОМ через ``declare_metric``, а не только фреймворковые
        имена из ``heartbeat/telemetry.py`` и ``process_heartbeat.py``.

        Красный сейчас: ``TelemetryPublishConfig.from_dict`` молча роняет ключ
        ``default_enabled`` — ``due_metrics()`` на первом тике по-прежнему выдаёт ВЕСЬ
        каталог (все метрики включены по умолчанию). Падает ``AssertionError``: ``due``
        — большое непустое множество вместо пустого.

        Ловит РЕГРЕССИЮ «выключение работает для фреймворковых имён и не работает для
        плагинных (или наоборот)»: если реализация погасит только имена из какого-то
        захардкоженного списка вместо равного прохода по ``gated_metrics()``,
        ``_PLUGIN_METRIC_NAME`` останется в ``due`` и множество не совпадёт с пустым.
        """
        declare_metric(_PLUGIN_METRIC_NAME, owner=_PLUGIN_OWNER)
        try:
            catalog = gated_metrics()
            framework_names = {"fps", "latency_ms", "effective_hz", "cycle_duration_ms", "shm"}
            assert framework_names <= set(catalog), sorted(catalog)  # тест не вырожден — фреймворк в каталоге
            assert _PLUGIN_METRIC_NAME in catalog  # и плагинное имя тоже туда попало

            hb = ProcessHeartbeat(_MinimalServices({"telemetry": {"publish": {"default_enabled": False}}}))
            gate = hb._build_telemetry_gate()
            assert gate is not None

            due = gate.due_metrics(now=0.0)
            assert due == set(), f"гейт пропустил метрики при default_enabled=False: {sorted(due)!r}"
        finally:
            forget_declarations(KIND_METRIC, names={_PLUGIN_METRIC_NAME})

    def test_control_same_harness_without_default_enabled_still_publishes(self) -> None:
        """Контроль к критерию 5, а не отдельный акцептанс-тест (обязателен по правилу
        «неподключённый драйвер = ровный ноль» — подтверждающий ноль засчитывается
        только в паре с контролем, дающим ненулевое).

        ТА ЖЕ связка (``_MinimalServices`` → ``_build_telemetry_gate`` →
        ``due_metrics``), но БЕЗ ``default_enabled`` в конфиге — обязана пропустить
        хотя бы одну метрику. Без этого контроля критерий 5 мог бы стать зелёным по
        причине, не имеющей отношения к ``default_enabled`` (например, если
        ``_build_telemetry_gate`` вообще перестал бы строить рабочий гейт) — тест не
        отличил бы «выключил конкретно default_enabled» от «гейт сломан и молчит всегда».

        Эта проверка ХАРАКТЕРИЗУЕТ сегодняшнее поведение и обязана быть зелёной уже
        сейчас — и остаться зелёной после реализации (конфиг без ``default_enabled``
        наследует его дефолт ``True``).
        """
        hb = ProcessHeartbeat(_MinimalServices({"telemetry": {"publish": {}}}))
        gate = hb._build_telemetry_gate()
        assert gate is not None
        due = gate.due_metrics(now=0.0)
        assert due, "гейт-харнес сам по себе пуст — контроль не доказывает ничего про default_enabled"
