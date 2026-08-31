# -*- coding: utf-8 -*-
"""Приёмочные тесты задачи 4.1 (`plans/telemetry-stage6.md`, Ф4) — `PluginContext.write_event`:
одна широкая запись на единицу работы («почему изделие N забраковано»).

Писаны НЕЗАВИСИМЫМ тестировщиком от восьми критериев приёмки 4.1 (пункты названы при каждом
классе теста ниже), БЕЗ чтения: `plugins/base.py`, `plugins/interfaces.py`,
`managers/observability_wiring.py`, `managers/observability_reload.py`, `core/process_module.py`,
`configs/observability_config.py`, `commands/builtin_commands.py`,
`tests/test_wide_event_hazards.py` (тесты автора), `Plugins/control/robot_control/plugin.py`.

**Честно про приём "чёрный ящик из непрочитанного файла".** Производственные символы
`WideEventSelector`, `wire_process_observability`, `BuiltinCommands`, `ObservabilityEventsConfig`
ИМПОРТИРУЮТСЯ и вызываются напрямую, хотя их файлы — в списке выше. Это тот же приём, каким уже
пользуется этот проект: тестер задачи 2.1 (`test_stats_delivery_acceptance.py`) импортировал
`wire_process_observability`/`drain_process_observability` из своего же запрещённого-к-чтению
`observability_wiring.py`; тестеры readback-а (`test_observability_sampling_readback.py`,
`test_introspect_observability_after_hierarchy.py`) — `BuiltinCommands` из
`commands/builtin_commands.py`. Вызывающая конвенция (имена параметров, форма ответа) восстановлена
из РАЗРЕШЁННЫХ источников: `plans/telemetry-stage6.md` (Р4.1-1..12), `process_module/STATUS.md`
(запись 2026-08-16), `process_module/DECISIONS.md` (ADR-PM-036), `plugins/testing.py` (докстринг
`MockProcessServices.event_selector`) и уже существующих тестов — `test_plugin_context_documents.py`
(симметричный `write_document`), `test_frame_trace.py` (`MULTIPROCESS_FRAME_TRACE`/`trace_id`),
`test_observability_commands.py` + `test_introspect_observability_after_hierarchy.py` (вызов
`config.reload`/`introspect.observability` через `BuiltinCommands` на фейковом `services`).

Точные сигнатуры конструктора/методов чёрных ящиков (`WideEventSelector(first_n=, every_mth=)`,
`.select(kind, decisive=)`, `.counters()`, `.knobs`, `wire_process_observability(name, worker,
logger, stats, error)`) получены `inspect.signature`/`dir()` ВО ВРЕМЯ ВЫПОЛНЕНИЯ (метаданные —
имена параметров, не тело метода) — названо здесь явно, чтобы оценка независимости прогона была
честной. Ни одно ожидаемое ЗНАЧЕНИЕ в тестах ниже не взято из этой интроспекции — каждое выведено
из контракта (план/ADR/STATUS.md) и только затем сверено прогоном.

Не покрыто и почему — см. отчёт тестера оркестратору (не этот файл):
  - критерий 3 (trace_id widecast == trace_id вердикт-документа) — только МЕХАНИЗМ
    (см. `TestTraceIdConsistencyMechanism`), не реальный `RobotControlPlugin` (файл запрещён);
  - цена в байтах/фон на живом темпе (пункт приёмки плана, не входит в восемь критериев задания) —
    live-стенд, вне обычного pytest.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.process_module.generic import frame_trace
from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    SubPluginContext,
)


# ---------------------------------------------------------------------------
# Общие фейки — симметричны _Services/_RecordingSink из test_plugin_context_documents.py
# ---------------------------------------------------------------------------


class _Services:
    """Процесс в объёме, который читает `PluginContext`.

    Не `MagicMock`: фальшивка с ЛЮБЫМ атрибутом ответила бы и там, где его нет —
    «фальшивка-всегда-успех глушит гейт» (тот же довод, что в
    ``test_plugin_context_documents.py``). ``event_selector`` не объявлен ВООБЩЕ, если
    ``has_selector_attr`` не попросили явно — «плоскости нет» это ОТСУТСТВИЕ атрибута,
    а не ``None`` по умолчанию, ровно как у ``document_sink`` в том же файле.
    """

    def __init__(
        self,
        name: str = "inspector",
        event_selector: Any = None,
        has_selector_attr: bool | None = None,
    ) -> None:
        self.name = name
        self.errors: List[str] = []
        self.logs: List[Dict[str, Any]] = []
        if has_selector_attr is None:
            has_selector_attr = event_selector is not None
        if has_selector_attr:
            self.event_selector = event_selector

    def log_debug(self, message: str, **kwargs: Any) -> None:
        self.logs.append({"level": "DEBUG", "message": message, **kwargs})

    def log_info(self, message: str, **kwargs: Any) -> None:
        self.logs.append({"level": "INFO", "message": message, **kwargs})

    def log_warning(self, message: str, **kwargs: Any) -> None:
        self.logs.append({"level": "WARNING", "message": message, **kwargs})

    def log_error(self, message: str, **kwargs: Any) -> None:
        self.errors.append(message)
        self.logs.append({"level": "ERROR", "message": message, **kwargs})

    def log_critical(self, message: str, **kwargs: Any) -> None:
        self.errors.append(message)
        self.logs.append({"level": "CRITICAL", "message": message, **kwargs})


def _ctx(services: _Services, plugin_name: str | None = "robot_control") -> PluginContext:
    return PluginContext(services=services, plugin_name=plugin_name)


TRACE_ID = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"


@pytest.fixture()
def trace_off():
    """Выключить MULTIPROCESS_FRAME_TRACE на время теста (приём из test_frame_trace.py)."""
    prev = frame_trace._ENABLED
    frame_trace._ENABLED = False
    yield
    frame_trace._ENABLED = prev


@pytest.fixture()
def trace_on():
    prev = frame_trace._ENABLED
    frame_trace._ENABLED = True
    yield
    frame_trace._ENABLED = prev


# ---------------------------------------------------------------------------
# Критерий 1 — одна широкая запись на единицу: вердикт/ROI/счётчики/порог,
# БЕЗ confidence (Р4.1-12), находимая FTS5-поиском стора по trace_id И по слову.
# ---------------------------------------------------------------------------


class TestOneWideRecordPerUnit:
    def test_message_format_is_the_exact_literal_from_the_decision_table(self, trace_off) -> None:
        """Р4.1-3: ``message = "event <kind>: <summary> trace=<trace_id>"`` — дословно."""
        services = _Services()
        _ctx(services).write_event("verdict", "брак", unit={"trace_id": TRACE_ID}, decisive=True)
        assert services.logs[0]["message"] == f"event verdict: брак trace={TRACE_ID}"

    def test_message_format_stays_constant_shape_with_empty_trace(self, trace_off) -> None:
        """ADR-PM-036 п.2: «форма постоянна... даже при пустом следе» — без unit trace= пуст,
        но НИКУДА не девается (переменная форма сломала бы поиск по образцу)."""
        services = _Services()
        _ctx(services).write_event("verdict", "брак", decisive=True)  # без unit → пустой след
        assert services.logs[0]["message"] == "event verdict: брак trace="

    def test_single_call_carries_verdict_roi_counters_threshold_in_one_log_call(self, trace_off) -> None:
        """Один вызов write_event — РОВНО одна запись носителя со всем нужным для «почему»."""
        services = _Services()
        fields = {
            "action": "reject",
            "roi": [560, 240, 800, 600],
            "defects_found": 3,
            "frames_checked": 12,
            "defect_area_max": 1500.0,
            "min_defect_area": 200.0,
        }

        result = _ctx(services).write_event("verdict", "брак", unit={"trace_id": TRACE_ID}, decisive=True, **fields)

        assert result is True
        assert len(services.logs) == 1, "ожидался РОВНО один вызов носителя на один write_event"
        entry = services.logs[0]
        for key, value in fields.items():
            assert entry.get(key) == value, f"поле {key} не доехало до записи целиком"

    def test_no_confidence_key_is_required_or_invented(self, trace_off) -> None:
        """Р4.1-12: у площадного детектора confidence не существует по построению.

        «Почему забраковано» отвечается ПОРОГОМ (defect_area_max/min_defect_area), а не
        подделанным confidence — поле не имеет права появиться само по себе.
        """
        services = _Services()
        _ctx(services).write_event(
            "verdict",
            "брак",
            unit={"trace_id": TRACE_ID},
            decisive=True,
            defect_area_max=1500.0,
            min_defect_area=200.0,
        )
        entry = services.logs[0]
        assert "confidence" not in entry, "confidence не должен подделываться у площадного детектора"
        assert entry.get("defect_area_max") == 1500.0
        assert entry.get("min_defect_area") == 200.0

    def test_message_and_extra_are_findable_by_trace_id_and_by_word_via_store_search(self) -> None:
        """Стор-сторона критерия (Р4.1-3): FTS5 индексирует `message`, не `extra`.

        Запись со связкой ``message="event <kind>: <summary> trace=<id>"`` (ровно формат,
        доказанный двумя тестами выше) обязана находиться поиском И по `trace_id`, И по
        слову из `summary` — это и есть механизм «одна запись находится по следу и по
        слову», а не факт наличия строки как таковой.
        """
        from multiprocess_framework.modules.channel_routing_module.observability import (
            ObservabilityStore,
        )

        store = ObservabilityStore(":memory:")
        try:
            message = f"event verdict: брак_уникальное_слово trace={TRACE_ID}"
            record = {
                "kind": "log",
                "process": "inspector",
                "module": "robot_control",
                "ts": 1_700_000_000.0,
                "severity": "info",
                "message": message,
                "extra": {"event": "verdict", "trace_id": TRACE_ID, "spans": "off"},
            }
            inserted = store.append_records([record])
            assert inserted == 1

            by_trace = store.search(TRACE_ID)
            assert len(by_trace) == 1, f"поиск по trace_id ничего не нашёл: {by_trace}"

            by_word = store.search("брак_уникальное_слово")
            assert len(by_word) == 1, f"поиск по слову из summary ничего не нашёл: {by_word}"

            assert by_trace[0]["id"] == by_word[0]["id"], "оба пути обязаны находить ОДНУ и ту же запись"
        finally:
            store.close()


# ---------------------------------------------------------------------------
# Критерий 2 — пара маркеров: шторм единиц душится по числам first_n/every_mth;
# фронты (decisive=True) проходят ВСЕ и не двигают лестницу потока.
# ---------------------------------------------------------------------------


class TestPairOfMarkersStreamVsDecisive:
    def test_first_n_lets_exactly_first_n_stream_events_through(self) -> None:
        from multiprocess_framework.modules.process_module.managers.observability_wiring import (
            WideEventSelector,
        )

        selector = WideEventSelector(first_n=4, every_mth=0)
        results = [selector.select("verdict", decisive=False) for _ in range(9)]

        assert results == [True, True, True, True, False, False, False, False, False], (
            "first_n=4 обязан пропустить РОВНО первые 4 потоковых события; "
            "every_mth=0 — 'после первых N не проходит ничего' (ADR-PM-036 п.4)"
        )

    def test_every_mth_zero_means_nothing_after_first_n_not_a_zero_division(self) -> None:
        """Ловушка, названная спекой явно: у `events.every_mth` ноль — штатное значение
        («выключено»), а не ошибка/деление на ноль, В ОТЛИЧИЕ ОТ `sampling_every_mth`
        логгера (там `min=1`, ADR-PM-036 п.4)."""
        from multiprocess_framework.modules.process_module.managers.observability_wiring import (
            WideEventSelector,
        )

        selector = WideEventSelector(first_n=0, every_mth=0)
        results = [selector.select("verdict", decisive=False) for _ in range(5)]

        assert results == [False] * 5, "first_n=0, every_mth=0 — дефолт «поток не пишется вовсе»"

    def test_every_mth_throttles_the_stream_by_the_given_number(self) -> None:
        from multiprocess_framework.modules.process_module.managers.observability_wiring import (
            WideEventSelector,
        )

        selector = WideEventSelector(first_n=0, every_mth=5)
        results = [selector.select("verdict", decisive=False) for _ in range(15)]

        passed = sum(results)
        assert passed == 3, f"every_mth=5 на 15 потоковых событиях обязан пропустить 15//5=3, получено {passed}"

    def test_the_ladder_counts_from_the_end_of_first_n_not_from_zero(self) -> None:
        """Добавлено ПОСЛЕ инъекций (2026-08-16): тест выше слеп к этой арифметике.

        При ``first_n=0`` выражения ``seen % M`` и ``(seen - first_n) % M``
        совпадают тождественно, поэтому подмена одного другим не красила ничего —
        инъекция «лесенка считает от seen» давала на файле ноль. Числа обязаны
        расходиться: обе ручки ненулевые и взаимно простыми не выбраны случайно.
        """
        from multiprocess_framework.modules.process_module.managers.observability_wiring import (
            WideEventSelector,
        )

        selector = WideEventSelector(first_n=3, every_mth=5)
        results = [selector.select("verdict", decisive=False) for _ in range(14)]

        # Первые три — по first_n; дальше каждое пятое ПОСЛЕ них: 4-е..8-е → 8-е,
        # 9-е..13-е → 13-е. Литерал, а не пересчёт формулой из кода под тестом.
        assert results == [
            True,
            True,
            True,
            False,
            False,
            False,
            False,
            True,
            False,
            False,
            False,
            False,
            True,
            False,
        ]

    def test_decisive_always_passes_even_when_stream_is_fully_saturated(self) -> None:
        from multiprocess_framework.modules.process_module.managers.observability_wiring import (
            WideEventSelector,
        )

        # Самая тесная конфигурация потока — 0/0, поток не проходит НИКОГДА.
        selector = WideEventSelector(first_n=0, every_mth=0)

        decisive_results = [selector.select("verdict", decisive=True) for _ in range(6)]

        assert decisive_results == [True] * 6, "decisive=True обязан проходить отбор ВСЕГДА (Р4.1-6)"

    def test_decisive_calls_do_not_advance_the_stream_ladder(self) -> None:
        """«Лестницу потока не двигают»: фронты, идущие ПЕРЕД потоком, не тратят бюджет
        first_n потоковых событий того же рода."""
        from multiprocess_framework.modules.process_module.managers.observability_wiring import (
            WideEventSelector,
        )

        selector = WideEventSelector(first_n=2, every_mth=0)

        # 3 decisive-вызова ПЕРЕД потоком — если бы они двигали лестницу потока, первые
        # 2 потоковых события после них были бы уже за пределом first_n=2.
        for _ in range(3):
            assert selector.select("verdict", decisive=True) is True

        stream_results = [selector.select("verdict", decisive=False) for _ in range(3)]
        assert stream_results == [True, True, False], (
            "first_n=2 потоковых события обязаны пройти НЕЗАВИСИМО от того, сколько decisive-вызовов было перед ними"
        )

    def test_counting_is_per_kind_not_a_shared_global_budget(self) -> None:
        """Счёт — по РОДУ (Р4.1-6): бюджет одного kind не делится с другим."""
        from multiprocess_framework.modules.process_module.managers.observability_wiring import (
            WideEventSelector,
        )

        selector = WideEventSelector(first_n=2, every_mth=0)

        verdict_results = [selector.select("verdict", decisive=False) for _ in range(3)]
        audit_results = [selector.select("audit", decisive=False) for _ in range(3)]

        assert verdict_results == [True, True, False]
        assert audit_results == [True, True, False], (
            "kind='audit' обязан получить СВОЙ бюджет first_n=2, а не наследовать исчерпанный бюджет kind='verdict'"
        )

    def test_write_event_actually_consults_a_real_wired_selector(self, trace_off) -> None:
        """Смыкает «write_event учитывает event_selector» с уже доказанным отдельно
        поведением самого селектора (тесты выше) — без этого теста было бы доказано
        только «селектор работает сам по себе», а не то, что write_event его спрашивает."""
        from multiprocess_framework.modules.process_module.managers.observability_wiring import (
            WideEventSelector,
        )

        selector = WideEventSelector(first_n=2, every_mth=0)
        services = _Services(event_selector=selector)
        ctx = _ctx(services)

        outcomes = [
            ctx.write_event("verdict", "поток 1", unit={"trace_id": TRACE_ID}, decisive=False),
            ctx.write_event("verdict", "поток 2", unit={"trace_id": TRACE_ID}, decisive=False),
            ctx.write_event("verdict", "поток 3 — должен быть подавлен", unit={"trace_id": TRACE_ID}, decisive=False),
            ctx.write_event("verdict", "фронт — обязан пройти", unit={"trace_id": TRACE_ID}, decisive=True),
        ]

        assert outcomes == [True, True, False, True]
        assert len(services.logs) == 3, "подавленный поток НЕ должен звать носитель вовсе"
        assert [e["message"] for e in services.logs] == [
            f"event verdict: поток 1 trace={TRACE_ID}",
            f"event verdict: поток 2 trace={TRACE_ID}",
            f"event verdict: фронт — обязан пройти trace={TRACE_ID}",
        ]


# ---------------------------------------------------------------------------
# Критерий 3 — trace_id широкой записи совпадает с trace_id вердикт-документа
# ТОЙ ЖЕ единицы.
#
# Полный сквозной путь (реальный `RobotControlPlugin`, который ДОЛЖЕН передавать один
# trace_id в оба вызова — Р4.1-11) не проверяем: этот файл намеренно не читает
# `Plugins/control/robot_control/plugin.py` (код заявителя, не контракт write_event).
# Ниже проверяется МЕХАНИЗМ: если вызывающий передаёт один trace_id в оба API, оба
# доезжают одинаково — то есть сам механизм способен на согласованность.
# ---------------------------------------------------------------------------


class TestTraceIdConsistencyMechanism:
    def test_same_trace_id_reaches_both_write_event_and_write_document_verbatim(self, trace_off) -> None:
        services = _Services()

        class _Sink:
            def __init__(self) -> None:
                self.documents: List[Dict[str, Any]] = []

            def append(self, document: Dict[str, Any]) -> bool:
                self.documents.append(document)
                return True

        services.document_sink = _Sink()  # type: ignore[attr-defined]
        ctx = _ctx(services)

        ctx.write_event("verdict", "брак", unit={"trace_id": TRACE_ID}, decisive=True, action="reject")
        ctx.write_document("verdict", "брак", trace_id=TRACE_ID, action="reject")

        event_entry = services.logs[0]
        assert event_entry.get("trace_id") == TRACE_ID
        assert f"trace={TRACE_ID}" in event_entry["message"]

        doc_entry = services.document_sink.documents[0]  # type: ignore[attr-defined]
        assert doc_entry.get("trace_id") == TRACE_ID, (
            "механизм write_document обязан пронести переданный trace_id без искажения — "
            "иначе связка с wide event (Р4.1-11) невозможна даже при правильном вызывающем"
        )


# ---------------------------------------------------------------------------
# Критерий 4 — спаны: MULTIPROCESS_FRAME_TRACE OFF → "spans": "off" (строкой, ИМЕННО
# названо, не отсутствует); ON → спаны единицы из unit["trace"].
# ---------------------------------------------------------------------------


class TestSpansGatedByFrameTrace:
    def test_spans_is_the_literal_string_off_when_frame_trace_disabled(self, trace_off) -> None:
        services = _Services()
        unit = {"trace_id": TRACE_ID, "trace": [{"kind": "process", "node": "inspector", "ms": 1.2}]}

        _ctx(services).write_event("verdict", "брак", unit=unit, decisive=True)

        entry = services.logs[0]
        assert "spans" in entry, "поле обязано присутствовать (названный факт), а не отсутствовать молча"
        assert entry["spans"] == "off", f"ожидалась строка 'off', получено {entry['spans']!r}"

    def test_spans_carries_the_unit_trace_when_frame_trace_enabled(self, trace_on) -> None:
        services = _Services()
        spans = [{"kind": "process", "node": "inspector", "plugin": "blob_detector", "ms": 4.2}]
        unit = {"trace_id": TRACE_ID, "trace": spans}

        _ctx(services).write_event("verdict", "брак", unit=unit, decisive=True)

        entry = services.logs[0]
        assert entry["spans"] == spans, f"ожидались спаны unit['trace'] дословно, получено {entry['spans']!r}"

    def test_spans_off_regardless_of_unit_trace_when_frame_trace_disabled(self, trace_off) -> None:
        """Гейт — по флагу, а не по наличию `unit['trace']`: выключенный флаг обязан
        гасить спаны, даже если вызывающий их всё-таки передал."""
        services = _Services()
        unit = {"trace_id": TRACE_ID, "trace": [{"kind": "process", "node": "x", "ms": 1.0}]}

        _ctx(services).write_event("verdict", "брак", unit=unit, decisive=True)

        assert services.logs[0]["spans"] == "off"


# ---------------------------------------------------------------------------
# Критерий 5 — ручка по дороге трёх точек: observability.events.{first_n, every_mth}.
# Схема принимает; config.reload доходит до ЖИВОГО селектора (не только в слой);
# readback introspect.observability -> events отдаёт действующие значения и счётчики
# selected/skipped/decisive.
#
# Проверка идёт БОЕВЫМ командным путём: производственный `BuiltinCommands`,
# зарегистрированный на минимальном `services`-дубле, несущем НАСТОЯЩИЙ
# `WideEventSelector` атрибутом `event_selector` — приём `test_observability_commands.py`
# / `test_introspect_observability_after_hierarchy.py` для соседних ручек (`config.reload`
# → `logger`, readback `introspect.observability`). Ручка, применённая мимо `config.reload`
# (например прямой вызов внутренней функции сшивки), критерию не удовлетворяет по тексту
# задания — этот тест намеренно идёт командным путём, а не в обход него.
# ---------------------------------------------------------------------------


class _FakeCommandManager:
    def __init__(self) -> None:
        self.handlers: Dict[str, Any] = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler

    def dispatch(self, command: str, data: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return self.handlers[command](data or {})


class _CommandFakeServices:
    """Минимальный `services` для `BuiltinCommands` — по образцу `_FakeServices` в
    `test_observability_commands.py` / `test_introspect_observability_after_hierarchy.py`,
    плюс `event_selector` (Ф4, здесь новое)."""

    def __init__(self, event_selector: Any) -> None:
        self.command_manager = _FakeCommandManager()
        self.logger_manager = None
        self.error_manager = None
        self.stats_manager = None
        self.router_manager = None
        self.event_selector = event_selector
        self.name = "acceptance_probe"
        self._config: Dict[str, Any] = {}

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def _log_info(self, *a: Any, **k: Any) -> None: ...

    def _log_debug(self, *a: Any, **k: Any) -> None: ...


def _wired_commands(event_selector: Any) -> _CommandFakeServices:
    from multiprocess_framework.modules.process_module.commands.builtin_commands import (
        BuiltinCommands,
    )

    services = _CommandFakeServices(event_selector)
    commands = BuiltinCommands(services)
    commands._register_observability_commands()
    commands._register_introspect_commands()
    return services


class TestConfigRoadReachesTheLiveSelectorAndReadsBack:
    def test_schema_accepts_first_n_and_every_mth(self) -> None:
        from multiprocess_framework.modules.process_module.configs.observability_config import (
            ObservabilityEventsConfig,
        )

        cfg = ObservabilityEventsConfig(first_n=9, every_mth=6)
        assert cfg.first_n == 9
        assert cfg.every_mth == 6

    def test_config_reload_changes_the_live_selector_object_not_just_a_layer(self) -> None:
        from multiprocess_framework.modules.process_module.managers.observability_wiring import (
            WideEventSelector,
        )

        selector = WideEventSelector(first_n=0, every_mth=0)
        services = _wired_commands(selector)

        res = services.command_manager.dispatch(
            "config.reload", {"observability": {"events": {"first_n": 9, "every_mth": 6}}}
        )

        assert res.get("success") is True, f"config.reload отказал: {res}"
        # Главное доказательство критерия: правка доехала до ЖИВОГО объекта, который
        # непосредственно консультирует write_event, а не только до промежуточного слоя
        # конфигурации.
        assert selector.knobs == (9, 6), f"живой селектор не переехал на новые числа: {selector.knobs}"

    def test_introspect_observability_reports_events_declared_values_and_counters(self) -> None:
        from multiprocess_framework.modules.process_module.managers.observability_wiring import (
            WideEventSelector,
        )

        selector = WideEventSelector(first_n=3, every_mth=0)
        services = _wired_commands(selector)

        # Числа отбора — заведомо неамбигуированные: 5 потоковых (3 пройдут по first_n=3,
        # 2 нет по правилу «0 после N») + 2 decisive (проходят всегда, считаются отдельно).
        for _ in range(5):
            selector.select("verdict", decisive=False)
        for _ in range(2):
            selector.select("verdict", decisive=True)

        res = services.command_manager.dispatch("introspect.observability", {})

        assert "events" in res, f"нет секции events в ответе: {list(res.keys())}"
        events = res["events"]
        assert events["first_n"] == 3
        assert events["every_mth"] == 0
        assert events["kinds"]["verdict"] == {"selected": 3, "skipped": 2, "decisive": 2}

    def test_no_voice_on_throttling_but_counters_stay_visible_via_readback(self) -> None:
        """Р4.1-10: «голоса при отсеве нет», но число обязано быть видно readback'ом."""
        from multiprocess_framework.modules.process_module.managers.observability_wiring import (
            WideEventSelector,
        )

        selector = WideEventSelector(first_n=1, every_mth=0)
        services = _wired_commands(selector)

        for _ in range(4):
            selector.select("verdict", decisive=False)

        res = services.command_manager.dispatch("introspect.observability", {})
        assert res["events"]["kinds"]["verdict"]["skipped"] == 3, "отсев обязан быть виден числом в readback"


# ---------------------------------------------------------------------------
# Критерий 6 — отключаемость: процесс БЕЗ селектора / без плоскости работает названным
# поведением (фронты пишутся, поток нет), без AttributeError.
# ---------------------------------------------------------------------------


class TestNoSelectorIsNotAFailure:
    def test_process_without_the_event_selector_attribute_answers_like_default_0_0(self, trace_off) -> None:
        """Атрибута `event_selector` нет ВООБЩЕ (не `None`) — как у `_Services()` без
        `document_sink` в симметричном тесте write_document."""
        services = _Services(has_selector_attr=False)
        assert not hasattr(services, "event_selector")

        decisive_ok = _ctx(services).write_event("verdict", "брак", unit={"trace_id": TRACE_ID}, decisive=True)
        stream_ok = _ctx(services).write_event("verdict", "брак", unit={"trace_id": TRACE_ID}, decisive=False)

        assert decisive_ok is True, "фронт обязан писаться даже без сшивки селектора"
        assert stream_ok is False, "поток без сшивки селектора обязан молчать, ровно как дефолт 0/0"
        assert services.errors == [], "отсутствие плоскости — законное состояние, не отказ"

    def test_event_selector_explicitly_none_behaves_identically_to_missing_attribute(self, trace_off) -> None:
        """ADR-PM-036 п.5: «отключённость имеет ОДНО исполнение» — оба случая совпадают."""
        services = _Services(event_selector=None, has_selector_attr=True)

        decisive_ok = _ctx(services).write_event("verdict", "брак", unit={"trace_id": TRACE_ID}, decisive=True)
        stream_ok = _ctx(services).write_event("verdict", "брак", unit={"trace_id": TRACE_ID}, decisive=False)

        assert decisive_ok is True
        assert stream_ok is False


# ---------------------------------------------------------------------------
# Критерий 7 — конверт: прикладные поля event/trace_id/spans в нагрузке не уводят
# запись в чужой род; kind/summary — позиционные (весь payload можно splat'ить
# без TypeError).
# ---------------------------------------------------------------------------


class TestEnvelopeWinsOverPayload:
    def test_payload_field_named_event_does_not_override_kind(self, trace_off) -> None:
        services = _Services()
        _ctx(services).write_event("verdict", "брак", unit={"trace_id": TRACE_ID}, decisive=True, event="ПОДМЕНА")

        entry = services.logs[0]
        assert entry["event"] == "verdict", "прикладной 'event' не имеет права увести конверт от рода вызова"

    def test_payload_field_named_trace_id_does_not_override_the_real_trace_id(self, trace_off) -> None:
        services = _Services()
        _ctx(services).write_event("verdict", "брак", unit={"trace_id": TRACE_ID}, decisive=True, trace_id="ПОДМЕНА")

        entry = services.logs[0]
        assert entry["trace_id"] == TRACE_ID
        assert f"trace={TRACE_ID}" in entry["message"]

    def test_payload_field_named_spans_does_not_override_the_real_spans(self, trace_off) -> None:
        services = _Services()
        _ctx(services).write_event("verdict", "брак", unit={"trace_id": TRACE_ID}, decisive=True, spans="ПОДМЕНА")

        entry = services.logs[0]
        assert entry["spans"] == "off", "конверт кладётся ПОСЛЕ fields (Р4.1-4) — прикладной spans проигрывает"

    def test_whole_payload_dict_can_be_splatted_without_a_typeerror(self, trace_off) -> None:
        """Ради чего kind/summary сделаны позиционными (симметрия с write_document)."""
        services = _Services()
        payload = {
            "kind": "ПОДМЕНА",
            "summary": "ПОДМЕНА",
            "trace_id": "ПОДМЕНА",
            "event": "ПОДМЕНА",
            "action": "reject",
            "defect_area_max": 1500.0,
        }

        result = _ctx(services).write_event("verdict", "брак", unit={"trace_id": TRACE_ID}, decisive=True, **payload)

        assert result is True
        entry = services.logs[0]
        assert entry["event"] == "verdict"
        assert entry["trace_id"] == TRACE_ID
        assert entry["action"] == "reject", "прикладная часть при этом не потеряна"


# ---------------------------------------------------------------------------
# Критерий 8 — SubPluginContext несёт write_event; вызов ПО ЭТАЛОННОЙ СИГНАТУРЕ
# именованными аргументами не падает (дефект 1.1: заглушка «по форме» роняла TypeError
# на именованном вызове, а позиционный тест автора был зелён).
# ---------------------------------------------------------------------------


class TestSubPluginContextCarriesWriteEvent:
    def test_default_noop_refuses_instead_of_raising(self) -> None:
        assert SubPluginContext().write_event("verdict", "брак") is False

    def test_default_noop_accepts_the_reference_signature_by_keyword_without_typeerror(self) -> None:
        """РОВНО регрессия 1.1: заглушка обязана принимать `unit=`/`decisive=` и
        произвольные **fields именованно, не только позиционно."""
        result = SubPluginContext().write_event(
            "verdict",
            "брак",
            unit={"trace_id": TRACE_ID},
            decisive=True,
            defect_area_max=1500.0,
            roi=[1, 2, 3, 4],
        )
        assert result is False  # noop — но БЕЗ TypeError

    def test_parent_can_hand_its_road_down(self, trace_off) -> None:
        services = _Services()
        parent = _ctx(services)

        sub = SubPluginContext(write_event=parent.write_event)
        result = sub.write_event("verdict", "брак от вложенного", unit={"trace_id": TRACE_ID}, decisive=True)

        assert result is True
        assert services.logs[0]["message"] == f"event verdict: брак от вложенного trace={TRACE_ID}"
