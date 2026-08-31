# -*- coding: utf-8 -*-
"""Приёмочные тесты задачи 5.1 (`plans/telemetry-stage6.md`, Ф5) — flight recorder:
дамп кольца записей процесса по явному жесту `ctx.flight_dump(reason)`.

Писаны НЕЗАВИСИМЫМ тестировщиком от пяти пунктов приёмки 5.1 (класс теста называет пункт),
БЕЗ чтения: `managers/observability_flight.py`, `managers/observability_wiring.py`,
`managers/observability_reload.py`, `managers/observability_ttl.py`,
`configs/observability_config.py`, `plugins/base.py`, `core/process_module.py`,
`Plugins/control/robot_control/plugin.py`, `tests/test_flight_recorder_hazards.py`,
`tests/test_flight_recorder_real_wiring.py`, `Plugins/control/robot_control/tests/
test_flight_dump_emitter.py`. Дифф веткиэ не читан вовсе.

**Приём «чёрный ящик из непрочитанного файла»** — тот же, каким уже пользуется этот
проект (`test_wide_event_acceptance.py`, докстринг критерия 8; тестер 2.1 —
`test_stats_delivery_acceptance.py`). Производственные символы `FlightRecorder`,
`flight_plane_report`, `apply_flight_recorder`, `FLIGHT_RECORDER_ATTR`,
`ObservabilityFlightConfig`, `PluginContext.flight_dump`, `SubPluginContext.flight_dump`
ИМПОРТИРУЮТСЯ и вызываются напрямую, хотя их файлы — в списке выше. Точные сигнатуры
(`FlightRecorder(enabled=, sink=, keep=, limit=)`, `.dump(svc, reason=, fields=, source=)`,
`.counters()`, `.knobs`, `.dumps/.records/.evicted_files/.last_path`,
`PluginContext.flight_dump(reason, /, **fields) -> bool`) получены `inspect.signature`/
`dir()` ВО ВРЕМЯ ВЫПОЛНЕНИЯ (метаданные, не тело метода). Поведение чёрного ящика
(тексты именованных отказов, форма шапки манифеста, ловушка `type`) установлено
ПРОГОНОМ реальных компонентов (`LoggerManager` с memory-каналом, `read_sink_tail`,
`SecretRedactor`) — эти файлы НЕ в списке запрещённых, читать и запускать их можно.
Ни одно ожидаемое ЗНАЧЕНИЕ в тестах ниже не взято из `observability_flight.py` —
каждое выведено из контракта: `plans/telemetry-stage6.md` (таблица решений Р5.1-1..14),
`multiprocess_framework/docs/observability/CONTROL_PANEL.md` (раздел Flight recorder),
`plugins/interfaces.py` (докстринг `IProcessServices.flight_recorder`, РАЗРЕШЁН к чтению),
`commands/builtin_commands.py` (РАЗРЕШЁН — шов `config.reload`/`introspect.observability`),
`configs/redaction.py` (РАЗРЕШЁН — `SECRET_FIELD_NAMES`, обе формы редакции).

Не покрыто здесь и почему — см. отчёт тестера оркестратору (не этот файл):
  - Live-арифметика «95 кадров брака → 1 срабатывание» на РЕАЛЬНОМ `RobotControlPlugin` —
    файл запрещён; пункт приёмки плана сам помечен «Live», не pytest;
  - цена в мс на 500 записей — число живого стенда, не unit-теста;
  - `WideEventSelector`/форма `write_event` — уже приёмка задачи 4.1
    (`test_wide_event_acceptance.py`), здесь используется как готовый механизм.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    SubPluginContext,
)


# ---------------------------------------------------------------------------
# Общие фейки и харнесы
# ---------------------------------------------------------------------------


class _Services:
    """Процесс в объёме, который читает `PluginContext` — симметрично `_Services` из
    `test_wide_event_acceptance.py`. `flight_recorder` не объявлен ВООБЩЕ, если
    `has_recorder_attr` не попросили явно — «плоскости нет» это ОТСУТСТВИЕ атрибута,
    а не `None` по умолчанию.
    """

    def __init__(
        self,
        name: str = "inspector",
        flight_recorder: Any = None,
        has_recorder_attr: bool | None = None,
        logger_manager: Any = None,
    ) -> None:
        self.name = name
        self.errors: List[str] = []
        self.logs: List[Dict[str, Any]] = []
        self._real_logger = logger_manager
        if logger_manager is not None:
            self.logger_manager = logger_manager
        if has_recorder_attr is None:
            has_recorder_attr = flight_recorder is not None
        if has_recorder_attr:
            self.flight_recorder = flight_recorder

    def _forward(self, mgr_method: str, message: str, **kwargs: Any) -> None:
        """Кроме учёта в `self.logs` (для проверки текста отказов), запись едет и в
        НАСТОЯЩИЙ `LoggerManager`, если он сшит — иначе `write_event`/`write_document`
        писали бы только в фейковый список и НИКОГДА не долетали бы до кольца, которое
        читает `FlightRecorder` (тот же жест, что `log_info` у production `services`,
        который есть тонкая обёртка над `logger_manager.info`)."""
        if self._real_logger is not None:
            kwargs.setdefault("module", "observability")
            getattr(self._real_logger, mgr_method)(message, **kwargs)

    def log_debug(self, message: str, **kwargs: Any) -> None:
        self.logs.append({"level": "DEBUG", "message": message, **kwargs})
        self._forward("debug", message, **kwargs)

    def log_info(self, message: str, **kwargs: Any) -> None:
        self.logs.append({"level": "INFO", "message": message, **kwargs})
        self._forward("info", message, **kwargs)

    def log_warning(self, message: str, **kwargs: Any) -> None:
        self.logs.append({"level": "WARNING", "message": message, **kwargs})
        self._forward("warning", message, **kwargs)

    def log_error(self, message: str, **kwargs: Any) -> None:
        self.errors.append(message)
        self.logs.append({"level": "ERROR", "message": message, **kwargs})
        self._forward("error", message, **kwargs)

    def log_critical(self, message: str, **kwargs: Any) -> None:
        self.errors.append(message)
        self.logs.append({"level": "CRITICAL", "message": message, **kwargs})
        self._forward("critical", message, **kwargs)


def _ctx(services: _Services, plugin_name: str | None = "robot_control") -> PluginContext:
    return PluginContext(services=services, plugin_name=plugin_name)


def _all_texts(services: _Services) -> str:
    return " ".join(entry["message"] for entry in services.logs)


TRACE_ID = "f1e2d3c4b5a697887766554433221100"


def _real_logger(
    tmp_path: Path,
    *,
    capacity: int = 500,
    channel: str = "flight_ring",
    declare_type: bool = True,
) -> LoggerManager:
    """Настоящий `LoggerManager` с memory-каналом — той же дорогой, что
    `test_observability_tail_delivery.py` (`_real_logger`), плюс канал `flight_ring`.

    `declare_type=False` воспроизводит ловушку Р5.1-7: без `type` цикл секции
    `channels` строит ФАЙЛОВЫЙ приёмник под тем же именем.
    """

    channel_cfg: Dict[str, Any] = {"capacity": capacity, "enabled": True}
    if declare_type:
        channel_cfg["type"] = "memory"
    config: Dict[str, Any] = {
        "app_name": "flight_acceptance",
        "log_directory": str(tmp_path),
        "enable_batching": False,
        "modules": {},
        "channels": {channel: channel_cfg},
        "scopes": {
            "SYSTEM": {"channels": [channel]},
            "BUSINESS": {"channels": [channel]},
            "DEBUG": {"channels": [channel]},
        },
    }
    mgr = LoggerManager(manager_name="FlightAcceptanceProbe", config=config)
    mgr.initialize()
    return mgr


def _flight_files(base: Path, process: str = "inspector") -> List[str]:
    return sorted(glob.glob(str(base / process / "flight" / "*.jsonl")))


# ---------------------------------------------------------------------------
# Р5.1-1 — дословная сигнатура фасада: `reason` позиционный, `**fields` — именованные;
# заглушка суб-контекста несёт ту же сигнатуру и отказывает, а не роняет TypeError.
# ---------------------------------------------------------------------------


class TestFacadeSignatureIsTheExactLiteral:
    def test_reason_is_positional_only_not_keyword(self) -> None:
        """Р5.1-1: `def flight_dump(self, reason="", /, **fields)` — `/` делает `reason`
        ТОЛЬКО позиционным, симметрично `write_document`/`write_event`."""
        import inspect

        sig = inspect.signature(PluginContext.flight_dump)
        reason_param = sig.parameters["reason"]
        assert reason_param.kind is inspect.Parameter.POSITIONAL_ONLY, (
            f"'reason' обязан быть positional-only, получено {reason_param.kind}"
        )
        assert reason_param.default == "", "дефолт 'reason' обязан быть пустой строкой"

    def test_payload_field_named_reason_does_not_raise_and_does_not_override_the_real_reason(self) -> None:
        """Довод `/` дословно (Р5.1-1): «прикладной ключ `reason` в нагрузке не имеет
        права увести конверт и не должен ронять линию `TypeError`'ом». Вызов
        `reason=` ИМЕНОВАННО обязан быть безопасно поглощён `**fields` (Python-семантика
        positional-only + `**kwargs`), а не поднять исключение — ровно то, чего третье
        написание жеста избегает."""
        services = _Services(has_recorder_attr=False)

        # Именованный 'reason=' НЕ роняет TypeError — поглощается **fields, реальный
        # позиционный reason остаётся дефолтным ("").
        result = _ctx(services).flight_dump(reason="ПОДМЕНА", trace_id=TRACE_ID)  # type: ignore[call-arg]

        assert result is False  # рекордера нет — но именно отказ, не исключение
        assert "'ПОДМЕНА'" not in _all_texts(services), (
            "прикладной 'reason=' не имеет права стать РЕАЛЬНЫМ reason конверта"
        )

    def test_subplugincontext_default_noop_refuses_instead_of_raising(self) -> None:
        assert SubPluginContext().flight_dump("reject", trace_id=TRACE_ID) is False

    def test_subplugincontext_signature_matches_the_parent_facade(self) -> None:
        import inspect

        parent_sig = inspect.signature(PluginContext.flight_dump)
        sub_sig = inspect.signature(SubPluginContext.flight_dump)
        parent_params = [p for name, p in parent_sig.parameters.items() if name != "self"]
        assert list(sub_sig.parameters.values()) == parent_params, (
            "заглушка суб-контекста обязана нести ТУ ЖЕ сигнатуру, что и фасад "
            "(регрессия 1.1: заглушка «по форме» роняла TypeError на именованном вызове)"
        )


# ---------------------------------------------------------------------------
# Критерий 2 (Р5.1-5, Р5.1-6, докстринг IProcessServices.flight_recorder) — минимум
# ДВА РАЗНЫХ названных отказа, ни один не тишина и не голый False; выключенное
# состояние — 0 файлов.
# ---------------------------------------------------------------------------


class TestNamedRefusalsNeverSilent:
    def test_missing_flight_recorder_attribute_refuses_named_not_silent(self) -> None:
        """Атрибута `flight_recorder` нет ВООБЩЕ — как `event_selector` в 4.1: это
        законное состояние, отказ должен быть НАЗВАН, а не тишина/голый False."""
        services = _Services(has_recorder_attr=False)
        assert not hasattr(services, "flight_recorder")

        result = _ctx(services).flight_dump("reject", trace_id=TRACE_ID)

        assert result is False
        assert services.logs, "отказ обязан оставить голос, а не тишину"
        assert "observability.flight.enabled" in _all_texts(services), (
            "отказ обязан НАЗВАТЬ адрес ручки (докстринг IProcessServices.flight_recorder)"
        )
        assert services.errors == [], "отсутствие плоскости — законное состояние, не ERROR"

    def test_flight_recorder_explicitly_none_behaves_identically_to_missing_attribute(self) -> None:
        """«Двух разных исполнений у «выключено» быть не должно» (Р5.1-5)."""
        missing = _Services(has_recorder_attr=False)
        none_attr = _Services(flight_recorder=None, has_recorder_attr=True)

        result_missing = _ctx(missing).flight_dump("reject", trace_id=TRACE_ID)
        result_none = _ctx(none_attr).flight_dump("reject", trace_id=TRACE_ID)

        assert result_missing is False and result_none is False
        assert "observability.flight.enabled" in _all_texts(missing)
        assert "observability.flight.enabled" in _all_texts(none_attr)

    def test_disabled_recorder_creates_zero_files_and_names_the_refusal(self, tmp_path: Path) -> None:
        """Критерий 2 дословно: выключенное состояние → 0 файлов, отказ назван."""
        from multiprocess_framework.modules.process_module.managers.observability_flight import (
            FlightRecorder,
        )

        logger = _real_logger(tmp_path)
        try:
            services = _Services(
                flight_recorder=FlightRecorder(enabled=False),
                logger_manager=logger,
            )
            for _ in range(3):
                assert _ctx(services).flight_dump("reject", trace_id=TRACE_ID) is False

            assert _flight_files(tmp_path) == [], "enabled=False обязан дать РОВНО 0 файлов"
            assert "observability.flight.enabled" in _all_texts(services)
        finally:
            logger.shutdown()

    def test_no_ring_refusal_is_a_different_named_reason_than_disabled(self, tmp_path: Path) -> None:
        """Р5.1-6: (а) выключен vs (б) приёмника нет/не memory — ДВА РАЗНЫХ диагноза,
        не один текст на оба (иначе оператор чинит не то)."""
        from multiprocess_framework.modules.process_module.managers.observability_flight import (
            FlightRecorder,
            flight_plane_report,
        )

        # Ловушка Р5.1-7: канал 'flight_ring' объявлен БЕЗ `type` → файловый приёмник
        # под тем же именем; `flight.sink` на него указывает, но tail() недоступен.
        logger = _real_logger(tmp_path, declare_type=False)
        try:
            services = _Services(
                flight_recorder=FlightRecorder(enabled=True, sink="flight_ring", keep=5),
                logger_manager=logger,
            )
            logger.info("предшествующая запись", module="observability")

            result = _ctx(services).flight_dump("reject", trace_id=TRACE_ID)

            assert result is False
            assert _flight_files(tmp_path) == [], "отказ 'нет кольца' тоже обязан дать 0 файлов"
            counters = flight_plane_report(services)["flight"]
            assert counters["refused_no_ring"] == 1
            assert counters["refused_disabled"] == 0, (
                "канал есть и enabled=True — отказ обязан считаться ПО ДРУГОМУ счётчику, не по 'disabled'"
            )
        finally:
            logger.shutdown()

    def test_write_failure_refuses_with_a_third_named_reason(self, tmp_path: Path) -> None:
        """Третий, ещё один отличный диагноз: кольцо читаемо, файл не пишется
        (диск/права/ФС) — `refused_failed`, а не `refused_disabled`/`refused_no_ring`."""
        from multiprocess_framework.modules.process_module.managers.observability_flight import (
            FlightRecorder,
            flight_plane_report,
        )

        # Блокер записи: log_directory указывает на ФАЙЛ там, где рекордеру нужно
        # создать подкаталог `<process>/flight/` — попытка mkdir падает.
        blocker = tmp_path / "blocked"
        blocker.write_text("занято", encoding="utf-8")
        logger = _real_logger(blocker)
        try:
            services = _Services(
                flight_recorder=FlightRecorder(enabled=True, sink="flight_ring", keep=5),
                logger_manager=logger,
            )
            logger.info("запись перед сбоем", module="observability")

            result = _ctx(services).flight_dump("reject", trace_id=TRACE_ID)

            assert result is False, "отказ дампа обязан вернуть False, а не поднять исключение"
            counters = flight_plane_report(services)["flight"]
            assert counters["refused_failed"] == 1
            assert counters["refused_disabled"] == 0
            assert counters["refused_no_ring"] == 0
        finally:
            logger.shutdown()


# ---------------------------------------------------------------------------
# Критерий 1 — серия записей → дамп несёт wide event и предшествующие записи;
# счёт записей согласован с ГЛУБИНОЙ кольца (не с числом записанного).
# ---------------------------------------------------------------------------


class TestDumpCarriesTheWideEventAndRespectsRingDepth:
    def test_dumped_record_count_is_bounded_by_ring_capacity_not_by_total_written(self, tmp_path: Path) -> None:
        """Ёмкость кольца — 6 (сознательно не 500-дефолт). Пишем 11 записей,
        дамп обязан нести РОВНО 6 записей (глубина кольца), не 11 (сколько написано)."""
        from multiprocess_framework.modules.process_module.managers.observability_flight import (
            FlightRecorder,
        )

        capacity = 6
        logger = _real_logger(tmp_path, capacity=capacity)
        try:
            services = _Services(
                flight_recorder=FlightRecorder(enabled=True, sink="flight_ring", keep=5),
                logger_manager=logger,
            )
            for i in range(11):
                logger.info(f"кадр {i}", module="observability")

            assert _ctx(services).flight_dump("reject", trace_id=TRACE_ID) is True

            files = _flight_files(tmp_path)
            assert len(files) == 1
            lines = Path(files[0]).read_text(encoding="utf-8").splitlines()
            body = lines[1:]
            assert len(body) == capacity, (
                f"дамп обязан нести РОВНО {capacity} записей (глубина кольца), получено {len(body)}"
            )
            import json

            header = json.loads(lines[0])
            assert header["ring"]["capacity"] == capacity
            assert header["ring"]["size"] == capacity
            # LoggerManager сам пишет одну строку 'initialized' на старте — 12 фактических.
            assert header["ring"]["written"] >= 11
            assert header["ring"]["evicted"] == header["ring"]["written"] - capacity
        finally:
            logger.shutdown()

    def test_dump_contains_the_units_wide_event_and_a_preceding_plain_record(self, tmp_path: Path) -> None:
        """«В дампе wide event бракованной единицы и предшествующие записи» — дословно.
        `write_event` — уже доказанный механизм 4.1, здесь используется как готовый."""
        logger = _real_logger(tmp_path, capacity=50)
        try:
            from multiprocess_framework.modules.process_module.managers.observability_flight import (
                FlightRecorder,
            )

            services = _Services(
                flight_recorder=FlightRecorder(enabled=True, sink="flight_ring", keep=5),
                logger_manager=logger,
            )
            ctx = _ctx(services)

            # Предшествующие записи — обычные кадры до фронта решения.
            logger.info("предшествующий_кадр_маркер_42", module="observability")
            # Фронт решения: широкая запись бракованной единицы (Ф4.1 механизм).
            ctx.write_event(
                "verdict",
                "брак",
                unit={"trace_id": TRACE_ID},
                decisive=True,
                action="reject",
            )

            assert ctx.flight_dump("reject", trace_id=TRACE_ID) is True

            files = _flight_files(tmp_path)
            assert len(files) == 1
            body_text = "\n".join(Path(files[0]).read_text(encoding="utf-8").splitlines()[1:])
            assert f"event verdict: брак trace={TRACE_ID}" in body_text, (
                "wide event бракованной единицы обязан лежать в дампе дословно (Р4.1-3 формат)"
            )
            assert "предшествующий_кадр_маркер_42" in body_text, "предшествующая запись обязана присутствовать в дампе"
        finally:
            logger.shutdown()

    def test_one_flight_dump_call_produces_exactly_one_file(self, tmp_path: Path) -> None:
        """Половина «не на кадр, а на фронт»: ОДИН вызов `flight_dump` — РОВНО один
        файл (не несколько, не ноль при успехе). Полная арифметика «95 кадров → 1
        срабатывание» — на реальном `RobotControlPlugin` (файл запрещён), Live."""
        from multiprocess_framework.modules.process_module.managers.observability_flight import (
            FlightRecorder,
        )

        logger = _real_logger(tmp_path)
        try:
            services = _Services(
                flight_recorder=FlightRecorder(enabled=True, sink="flight_ring", keep=5),
                logger_manager=logger,
            )
            logger.info("кадр", module="observability")

            assert _ctx(services).flight_dump("reject", trace_id=TRACE_ID) is True
            assert len(_flight_files(tmp_path)) == 1
        finally:
            logger.shutdown()

    def test_plain_log_records_never_trigger_a_dump_by_themselves(self, tmp_path: Path) -> None:
        """Половина критерия цены («вне горячего пути»): запись потоковых логов САМА
        ПО СЕБЕ не создаёт файлов — дамп рождается ТОЛЬКО явным `flight_dump`."""
        from multiprocess_framework.modules.process_module.managers.observability_flight import (
            FlightRecorder,
        )

        logger = _real_logger(tmp_path)
        try:
            services = _Services(
                flight_recorder=FlightRecorder(enabled=True, sink="flight_ring", keep=5),
                logger_manager=logger,
            )
            services.flight_recorder  # noqa: B018 — рекордер сшит, но не вызван
            for i in range(40):
                logger.info(f"поток {i}", module="observability")

            assert _flight_files(tmp_path) == [], (
                "поток логов не имеет права сам породить дамп — только явный ctx.flight_dump"
            )
        finally:
            logger.shutdown()


# ---------------------------------------------------------------------------
# Критерий 3 (Р5.1-10) — ретеншен по числу файлов, K+1-й вытесняет старейший,
# вытеснение с ГОЛОСОМ на каждое; keep=0 — без предела.
# ---------------------------------------------------------------------------


class TestRetentionEvictsOldestWithVoice:
    def test_kplus1th_dump_evicts_the_oldest_file_with_a_named_voice(self, tmp_path: Path) -> None:
        from multiprocess_framework.modules.process_module.managers.observability_flight import (
            FlightRecorder,
            flight_plane_report,
        )

        keep = 3  # сознательно не 5-дефолт
        logger = _real_logger(tmp_path)
        try:
            services = _Services(
                flight_recorder=FlightRecorder(enabled=True, sink="flight_ring", keep=keep),
                logger_manager=logger,
            )
            ctx = _ctx(services)
            first_path = None
            for i in range(keep + 1):
                logger.info(f"кадр {i}", module="observability")
                assert ctx.flight_dump(f"reject{i}", trace_id=TRACE_ID) is True
                if i == 0:
                    first_path = services.flight_recorder.last_path

            files = _flight_files(tmp_path)
            assert len(files) == keep, f"обязано остаться РОВНО keep={keep} файлов, получено {len(files)}"
            assert first_path not in files, "старейший (первый) дамп обязан быть вытеснен"

            counters = flight_plane_report(services)["flight"]
            assert counters["evicted_files"] == 1, "K+1-й дамп вытесняет РОВНО один старейший файл"

            first_name = os.path.basename(first_path)
            assert any(first_name in entry["message"] for entry in services.logs), (
                "вытеснение обязано иметь ГОЛОС — INFO с именем удалённого файла, не тишина"
            )
        finally:
            logger.shutdown()

    def test_keep_zero_means_unbounded_retention(self, tmp_path: Path) -> None:
        """`keep=0` — «без предела» (форма из `log_line_max_bytes`/`max_series`,
        CONTROL_PANEL.md)."""
        from multiprocess_framework.modules.process_module.managers.observability_flight import (
            FlightRecorder,
            flight_plane_report,
        )

        logger = _real_logger(tmp_path)
        try:
            services = _Services(
                flight_recorder=FlightRecorder(enabled=True, sink="flight_ring", keep=0),
                logger_manager=logger,
            )
            ctx = _ctx(services)
            for i in range(6):
                logger.info(f"кадр {i}", module="observability")
                assert ctx.flight_dump(f"reject{i}", trace_id=TRACE_ID) is True

            assert len(_flight_files(tmp_path)) == 6, "keep=0 не имеет права вытеснять НИЧЕГО"
            assert flight_plane_report(services)["flight"]["evicted_files"] == 0
        finally:
            logger.shutdown()


# ---------------------------------------------------------------------------
# Критерий 4 (Р5.1-14) — отказ дампа не роняет линию и не меняет уже вынесенный
# вердикт: `write_document` уже уехал своей дорогой, `flight_dump` падает молча (в
# смысле «без исключения»), а не молча (в смысле «без голоса» — см. критерий 2).
# ---------------------------------------------------------------------------


class TestFailedDumpDoesNotChangeTheVerdict:
    def test_failed_dump_does_not_raise_and_leaves_the_already_written_verdict_untouched(self, tmp_path: Path) -> None:
        from multiprocess_framework.modules.process_module.managers.observability_flight import (
            FlightRecorder,
        )

        class _DocumentSink:
            def __init__(self) -> None:
                self.documents: List[Dict[str, Any]] = []

            def append(self, document: Dict[str, Any]) -> bool:
                self.documents.append(document)
                return True

        blocker = tmp_path / "blocked"
        blocker.write_text("занято", encoding="utf-8")
        logger = _real_logger(blocker)
        try:
            services = _Services(
                flight_recorder=FlightRecorder(enabled=True, sink="flight_ring", keep=5),
                logger_manager=logger,
            )
            services.document_sink = _DocumentSink()  # type: ignore[attr-defined]
            ctx = _ctx(services)

            # Порядок дословно Р5.1-11: вердикт уже вынесен и записан ДО дампа.
            ctx.write_document("verdict", "брак", trace_id=TRACE_ID, action="reject")
            verdict_before = list(services.document_sink.documents)  # type: ignore[attr-defined]

            try:
                dump_result = ctx.flight_dump("reject", trace_id=TRACE_ID)
            except Exception as exc:  # pragma: no cover - сам факт исключения - находка
                pytest.fail(f"отказ дампа обязан вернуть False, а не поднять {type(exc)}: {exc}")

            assert dump_result is False
            assert services.document_sink.documents == verdict_before, (  # type: ignore[attr-defined]
                "уже записанный вердикт обязан остаться НЕТРОНУТЫМ отказом дампа"
            )
            assert len(services.document_sink.documents) == 1  # type: ignore[attr-defined]
        finally:
            logger.shutdown()


# ---------------------------------------------------------------------------
# Критерий 5 (Р5.1-12) — кольцо не открывает обходной дороги для секретов:
# `SecretRedactor` стоит ДО кольца, судится СОДЕРЖИМОЕ ФАЙЛА ДАМПА, не кольцо.
# ---------------------------------------------------------------------------


class TestSecretsNeverReachTheDumpFileInTheRaw:
    def test_dump_file_masks_a_secret_named_field_in_extra(self, tmp_path: Path) -> None:
        """Поверхность `extra` (redaction.py: `SECRET_FIELD_NAMES`, точное имя)."""
        from multiprocess_framework.modules.process_module.managers.observability_flight import (
            FlightRecorder,
        )

        raw_secret = "RAW_SECRET_VALUE_9f8e7d6c"
        logger = _real_logger(tmp_path)
        try:
            services = _Services(
                flight_recorder=FlightRecorder(enabled=True, sink="flight_ring", keep=5),
                logger_manager=logger,
            )
            logger.info("подключение к сервису", module="observability", password=raw_secret)

            assert _ctx(services).flight_dump("reject", trace_id=TRACE_ID) is True

            files = _flight_files(tmp_path)
            assert len(files) == 1
            dump_text = Path(files[0]).read_text(encoding="utf-8")
            assert raw_secret not in dump_text, (
                "сырой секрет из extra НЕ имеет права доехать до ФАЙЛА ДАМПА — "
                "кольцо кормится ПОСЛЕ SecretRedactor (Р5.1-12)"
            )
            assert "***" in dump_text, "маска редактора обязана присутствовать вместо секрета"
        finally:
            logger.shutdown()

    def test_dump_file_masks_a_secret_pattern_in_the_message_text(self, tmp_path: Path) -> None:
        """Вторая поверхность `redaction.py` — regex `ключ=значение` прямо в тексте
        сообщения (транзитный путь трейсбека), не полагаться на редакцию только `extra`."""
        from multiprocess_framework.modules.process_module.managers.observability_flight import (
            FlightRecorder,
        )

        raw_secret = "RAW_TOKEN_TEXT_1a2b3c4d"
        logger = _real_logger(tmp_path)
        try:
            services = _Services(
                flight_recorder=FlightRecorder(enabled=True, sink="flight_ring", keep=5),
                logger_manager=logger,
            )
            logger.info(f"попытка соединения token={raw_secret}", module="observability")

            assert _ctx(services).flight_dump("reject", trace_id=TRACE_ID) is True

            dump_text = Path(_flight_files(tmp_path)[0]).read_text(encoding="utf-8")
            assert raw_secret not in dump_text, "сырой секрет из ТЕКСТА сообщения НЕ имеет права доехать до файла дампа"
            assert "***" in dump_text
        finally:
            logger.shutdown()


# ---------------------------------------------------------------------------
# Р5.1-4 — дорога трёх точек: схема принимает ручки → `config.reload` доходит до
# ЖИВОГО рекордера (не только до слоя) → readback `introspect.observability -> flight`
# отдаёт действующие значения и счётчики. Идёт БОЕВЫМ командным путём (образец
# `test_wide_event_acceptance.py::TestConfigRoadReachesTheLiveSelectorAndReadsBack`).
# ---------------------------------------------------------------------------


class _FakeCommandManager:
    def __init__(self) -> None:
        self.handlers: Dict[str, Any] = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler

    def dispatch(self, command: str, data: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return self.handlers[command](data or {})


class _CommandFakeServices:
    def __init__(self, flight_recorder: Any) -> None:
        self.command_manager = _FakeCommandManager()
        self.logger_manager = None
        self.error_manager = None
        self.stats_manager = None
        self.router_manager = None
        self.flight_recorder = flight_recorder
        self.name = "acceptance_probe"
        self._config: Dict[str, Any] = {}

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def _log_info(self, *a: Any, **k: Any) -> None: ...

    def _log_debug(self, *a: Any, **k: Any) -> None: ...


def _wired_commands(flight_recorder: Any) -> _CommandFakeServices:
    from multiprocess_framework.modules.process_module.commands.builtin_commands import (
        BuiltinCommands,
    )

    services = _CommandFakeServices(flight_recorder)
    commands = BuiltinCommands(services)
    commands._register_observability_commands()
    commands._register_introspect_commands()
    return services


class TestConfigThreePointDoorReachesTheLiveRecorderAndReadsBack:
    def test_schema_accepts_the_four_knobs_with_named_defaults(self) -> None:
        """Р5.1-4: `observability.flight.{enabled, sink, keep, limit}`; дефолты по
        CONTROL_PANEL.md — `enabled=False`, `sink=""`, `keep=5`, `limit=0`."""
        from multiprocess_framework.modules.process_module.configs.observability_config import (
            ObservabilityFlightConfig,
        )

        defaults = ObservabilityFlightConfig()
        assert defaults.enabled is False
        assert defaults.sink == ""
        assert defaults.keep == 5
        assert defaults.limit == 0

        cfg = ObservabilityFlightConfig(enabled=True, sink="flight_ring", keep=9, limit=42)
        assert (cfg.enabled, cfg.sink, cfg.keep, cfg.limit) == (True, "flight_ring", 9, 42)

    def test_config_reload_changes_the_live_recorder_object_not_just_a_layer(self) -> None:
        from multiprocess_framework.modules.process_module.managers.observability_flight import (
            FlightRecorder,
        )

        recorder = FlightRecorder(enabled=False, sink="", keep=5, limit=0)
        services = _wired_commands(recorder)

        res = services.command_manager.dispatch(
            "config.reload",
            {"observability": {"flight": {"enabled": True, "sink": "flight_ring", "keep": 9, "limit": 4}}},
        )

        assert res.get("success") is True, f"config.reload отказал: {res}"
        # Главное доказательство: правка доехала до ЖИВОГО объекта, консультируемого
        # `flight_dump`, а не только до промежуточного слоя конфигурации.
        assert recorder.knobs == (True, "flight_ring", 9, 4), (
            f"живой рекордер не переехал на новые числа: {recorder.knobs}"
        )

    def test_introspect_observability_reports_flight_declared_values_and_counters(self) -> None:
        from multiprocess_framework.modules.process_module.managers.observability_flight import (
            FlightRecorder,
        )

        recorder = FlightRecorder(enabled=True, sink="flight_ring", keep=3, limit=0)
        services = _wired_commands(recorder)

        res = services.command_manager.dispatch("introspect.observability", {})

        assert "flight" in res, f"нет секции flight в ответе: {list(res.keys())}"
        flight = res["flight"]
        assert flight["declared"] is True
        assert flight["enabled"] is True
        assert flight["sink"] == "flight_ring"
        assert flight["keep"] == 3
        for key in (
            "dumps",
            "records",
            "evicted_files",
            "refused_disabled",
            "refused_no_ring",
            "refused_failed",
            "last_path",
        ):
            assert key in flight, f"readback обязан нести ключ {key!r} (CONTROL_PANEL.md, Ф5)"

    def test_introspect_without_any_recorder_wired_reports_declared_false(self) -> None:
        """Процесс без сшивки рекордера (одиночный запуск, тестовый стенд) — readback
        обязан честно сказать «плоскости нет», а не притвориться настроенным."""
        services = _CommandFakeServices(flight_recorder=None)
        services.flight_recorder = None
        from multiprocess_framework.modules.process_module.commands.builtin_commands import (
            BuiltinCommands,
        )

        commands = BuiltinCommands(services)
        commands._register_introspect_commands()
        res = services.command_manager.dispatch("introspect.observability", {})

        assert res["flight"]["declared"] is False


# ---------------------------------------------------------------------------
# Р5.1-8 — путь дампа резолвится через `log_paths` (базу `LoggerManager`), а НЕ от cwd.
# ---------------------------------------------------------------------------


class TestPathIsResolvedThroughLogPathsNotCwd:
    def test_dump_lands_under_the_configured_log_directory_not_under_cwd(self, tmp_path: Path) -> None:
        from multiprocess_framework.modules.process_module.managers.observability_flight import (
            FlightRecorder,
        )

        cwd_before = set(os.listdir(os.getcwd()))
        logger = _real_logger(tmp_path)
        try:
            services = _Services(
                flight_recorder=FlightRecorder(enabled=True, sink="flight_ring", keep=5),
                logger_manager=logger,
            )
            logger.info("кадр", module="observability")
            assert _ctx(services).flight_dump("reject", trace_id=TRACE_ID) is True

            last_path = Path(services.flight_recorder.last_path)
            assert str(tmp_path) in str(last_path), (
                f"дамп обязан лежать под сконфигурированной базой log_paths ({tmp_path}), получено {last_path}"
            )
            assert last_path.parent.name == "flight"
            assert last_path.parent.parent.name == "inspector"

            cwd_after = set(os.listdir(os.getcwd()))
            assert cwd_after == cwd_before, (
                "дамп не имеет права дописать НИ ОДНОГО файла в cwd (урок 3.3, «материализованный дефолт»)"
            )
        finally:
            logger.shutdown()
