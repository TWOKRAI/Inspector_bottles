# -*- coding: utf-8 -*-
"""Регресс-стражи по находкам РЕВЬЮ ФАЗЫ Ф0 (2026-07-27, три независимые линзы).

Каждая находка воспроизведена ревьюером запуском, а не вычитана из диффа.
Общее у всех трёх — они бьют по пути, который фаза объявила защищённым:

  1. [blocker] **Тихая потеря на прямом (небатченом) пути.** Инвариант плана
     «невидимый дроп невозможен» держался ТОЛЬКО при включённом батчинге.
     `enable_batching` — операбельное поле секции ``observability``, то есть
     оператор мог выключить батчинг hot-reload'ом и молча включить потери
     WARNING/INFO/DEBUG. ERROR спасал floor, остальные исчезали без следа.
     Две дыры: у ``ErrorManager`` своя копия цикла записи (не считала НИЧЕГО),
     и у ``LoggerCore`` не считался отказ канала статусом ``{"status":"error"}``.
  2. [blocker] **Контекст не доезжал до severity-пути.** Двухслойный контекст
     Ф0.5 (`set_base_context` + форточка `log_context`) был заинлайнен в
     ``LoggerCore.log``; ``ErrorManager.log`` — полный override — собирал свой
     ``extra`` руками и брал только потоковый слой. Итог: на ГЛАВНОМ
     производственном пути ошибок терялся ``proc_name``.
  3. [major] **Счётчики консоли стирались снятием приёмника.** История потерь
     обнулялась ровно той командой, которую дают при разборе инцидента.

Класс у всех один: развилка «две реализации одной операции», где второй
экземпляр отстаёт от первого. 0.4 зеркалили в двух местах, 0.9 в двух, tap'ы
в двух — а 0.5 забыли. Пока развилку не убрала Ф4.2, эти стражи держат её
синхронной.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.error_module import ErrorManager, ErrorManagerConfig
from multiprocess_framework.modules.logger_module.channels.log_channel import LogChannel
from multiprocess_framework.modules.logger_module.core.error_floor import reset_error_floors
from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_core import log_context
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


@pytest.fixture(autouse=True)
def _clean_floors():
    reset_error_floors()
    yield
    reset_error_floors()


class _FakeProcess:
    def __init__(self, name: str) -> None:
        self.name = name


class _RefusingChannel(LogChannel):
    """Живой канал, который отвечает отказом и НЕ бросает исключение.

    Так ведёт себя закрытый ``FileChannel`` и отброшенная по пределу ожидания
    консоль (R2). Отличить от рабочего можно только по статусу.
    """

    def __init__(self, name: str) -> None:
        super().__init__(LoggerChannelSchema(name=name, type="file", enabled=True))
        self.attempts = 0

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self.attempts += 1
        return {"status": "error", "error": "канал закрыт", "channel": self.name}

    def close(self) -> None:
        return None


def _unbatched_logger(tmp_path: Path) -> LoggerManager:
    """Логгер с ВЫКЛЮЧЕННЫМ батчингом — операторская, а не экзотическая раскладка."""
    mgr = LoggerManager(
        manager_name="DirectPathProbe",
        config=LoggerManagerConfig(
            app_name="phase_findings",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels={
                "system_file": LoggerChannelSchema(
                    name="system_file",
                    type="file",
                    enabled=True,
                    file_path="system.log",
                    format="%(message)s",
                    rotate=False,
                ),
            },
            scopes={"SYSTEM": LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=["system_file"])},
        ),
        process=_FakeProcess("direct_probe"),
    )
    mgr.initialize()
    return mgr


# =============================================================================
# 1. Прямой путь: отказ канала статусом обязан считаться
# =============================================================================


def test_refused_warning_is_counted_on_the_direct_path(tmp_path: Path) -> None:
    """Батчинг выключен, канал жив, но отвечает отказом → WARNING не исчезает молча.

    ERROR на том же канале спасает floor — дыра была именно для уровней ниже
    ERROR, и именно они составляют основную массу записей. Счётчик обязан
    отличаться от «канала нет»: там опечатка в scopes или снятый sink, здесь
    сток жив и отказывает — лечится это разным.
    """
    mgr = _unbatched_logger(tmp_path)
    try:
        refusing = _RefusingChannel("system_file")
        mgr._channel_registry.unregister("system_file")
        mgr._channel_registry.register(refusing)

        before = mgr.get_stats()
        mgr.warning("предупреждение в отказывающий канал", module="findings")
        after = mgr.get_stats()

        assert refusing.attempts == 1, "канал даже не попробовали — тест проверяет не то"
        assert after["channel_refused_records"] == before["channel_refused_records"] + 1, (
            "отказ живого канала не посчитан: запись исчезла без следа"
        )
        assert after["channel_refused_by_channel"].get("system_file") == 1
        assert after["unresolved_channel_records"] == before["unresolved_channel_records"], (
            "отказ спутан с «канала нет» — это разные болезни"
        )
        assert after["channel_write_errors"] == before["channel_write_errors"], (
            "отказ спутан с исключением — это тоже разные болезни"
        )
    finally:
        mgr.shutdown()


def test_missing_channel_is_counted_on_the_direct_path(tmp_path: Path) -> None:
    """Парная половина: приёмника нет — учитывается своим счётчиком, не общим.

    **Переклассифицировано в 2.8.** Прежняя редакция снимала приёмник командой
    и ждала `unresolved_channel_records`. С 2.8 снятый ОПЕРАТОРОМ приёмник
    исключается из маршрута, поэтому запись, которой не осталось ни одного
    приёмника, попадает в `records_without_channels` — другой класс той же
    потери. Свойство, ради которого тест писался, сохранено дословно: запись,
    не легшая никуда, **видна счётчиком, и счётчик именно свой**, а не общий
    `channel_refused_records`.

    Ветка «имя не резолвится, хотя никто его не снимал» (опечатка в конфиге)
    по-прежнему даёт `unresolved_channel_records` — она проверяется
    в `test_unknown_channel_accounting.py`.
    """
    mgr = _unbatched_logger(tmp_path)
    try:
        mgr.set_sink_enabled("system_file", False)

        before = mgr.get_stats()
        mgr.warning("предупреждение в снятый канал", module="findings")
        after = mgr.get_stats()

        assert after["records_without_channels"] == before["records_without_channels"] + 1
        assert after["unresolved_channel_records"] == before["unresolved_channel_records"]
        assert after["channel_refused_records"] == before["channel_refused_records"]
    finally:
        mgr.shutdown()


# =============================================================================
# 2. ErrorManager: своя копия цикла записи не считала НИЧЕГО
# =============================================================================


def _unbatched_error_manager(tmp_path: Path) -> ErrorManager:
    mgr = ErrorManager(
        manager_name="ErrorDirectProbe",
        config=ErrorManagerConfig(
            app_name="phase_findings",
            enable_batching=False,
            default_level="WARNING",
            critical_file_path=str(tmp_path / "critical.log"),
            error_file_path=str(tmp_path / "errors.log"),
            warnings_file_path=str(tmp_path / "warnings.log"),
        ),
        process=_FakeProcess("error_direct_probe"),
    )
    mgr.initialize()
    return mgr


def test_warning_falls_back_to_live_channel_when_its_own_is_removed(tmp_path: Path) -> None:
    """Снятие ``warnings_file`` переводит WARNING на живой ``errors_file`` (P2).

    Прежняя редакция этого теста ожидала здесь РОСТ ``unresolved_channel_records``:
    маршруты уровней считались один раз на ``initialize()``, и после
    ``sink.disable`` ``_level_to_channel`` продолжал указывать на снятый канал.
    Резидуал P2 это починил — fallback-цепочка пересчитывается на каждое
    изменение состава, и запись теперь не теряется вовсе.

    Инвариант «невидимый дроп невозможен» переехал в тест ниже — на вход, где
    приёмника действительно не остаётся.
    """
    mgr = _unbatched_error_manager(tmp_path)
    try:
        assert mgr.set_sink_enabled("warnings_file", False), "предусловие: канал был и снят"
        assert mgr.get_stats()["level_routes"]["WARNING"] == "errors_file", (
            "маршрут WARNING не пересобрался после снятия его канала"
        )

        before = mgr.get_stats()
        mgr.warning("предупреждение с fallback'ом", module="findings")
        after = mgr.get_stats()

        assert after["unresolved_channel_records"] == before["unresolved_channel_records"]
        assert "предупреждение с fallback'ом" in (tmp_path / "errors.log").read_text(encoding="utf-8")
    finally:
        mgr.shutdown()


def test_error_manager_counts_warning_without_any_receiver(tmp_path: Path) -> None:
    """WARNING без единого приёмника при выключенном батчинге не исчезает молча.

    Тот же инвариант, что проверял ревьюер, но на входе, который после P2
    действительно означает «приёмника нет»: сняты ВСЕ severity-каналы. Пол
    сюда не подстилается осознанно — он для ERROR/CRITICAL; WARNING обязан
    оставить счётчик.
    """
    mgr = _unbatched_error_manager(tmp_path)
    try:
        for name in list(mgr._channel_registry.names()):
            mgr.set_sink_enabled(name, False)
        assert mgr.get_stats()["level_routes"] == {}, "предусловие: severity-маршрутов не осталось"

        before = mgr.get_stats()
        mgr.warning("предупреждение в никуда", module="findings")
        after = mgr.get_stats()

        assert after["records_without_channels"] > before["records_without_channels"], (
            "WARNING без приёмников исчезло без счётчика — инвариант «невидимый дроп невозможен» нарушен"
        )
    finally:
        mgr.shutdown()


def test_error_manager_counts_refusal_on_warning(tmp_path: Path) -> None:
    """WARNING в живой, но отказывающий канал — тоже учитывается."""
    mgr = _unbatched_error_manager(tmp_path)
    try:
        target = "warnings_file"
        refusing = _RefusingChannel(target)
        mgr._channel_registry.unregister(target)
        mgr._channel_registry.register(refusing)

        before = mgr.get_stats()
        mgr.warning("предупреждение в отказывающий канал", module="findings")
        after = mgr.get_stats()

        assert refusing.attempts == 1, "канал не пробовали"
        assert after["channel_refused_records"] == before["channel_refused_records"] + 1
    finally:
        mgr.shutdown()


# =============================================================================
# 3. Контекст обязан доезжать до severity-пути ErrorManager
# =============================================================================


def test_severity_path_carries_base_context_and_window(tmp_path: Path) -> None:
    """``proc_name`` из базы процесса и форточка ``log_context`` доезжают до ошибки.

    Ревьюер получил ``extra={}`` на severity-пути при заполненной базе — то
    есть механизм, который Ф0.5 заводила ИМЕННО чтобы `proc_name` не терялся у
    потоков, на главном пути ошибок не работал. Проверяется по полу: он несёт
    запись целиком и не зависит от формата канала.
    """
    mgr = ErrorManager(
        manager_name="CtxProbe",
        config=ErrorManagerConfig(
            app_name="phase_findings",
            enable_batching=False,
            critical_file_path=str(tmp_path / "critical.log"),
            error_file_path=str(tmp_path / "errors.log"),
            warnings_file_path=None,
        ),
        process=_FakeProcess("ctx_probe"),
    )
    mgr.initialize()
    token = log_context.set({"window_field": "из форточки"})
    try:
        mgr.set_base_context(proc_name="camera_0")
        # Все приёмники сняты — запись гарантированно уйдёт в пол целиком.
        for name in list(mgr._channel_registry.names()):
            mgr.set_sink_enabled(name, False)

        mgr.error("ошибка с контекстом", module="findings")

        floor_path = Path(mgr.get_stats()["error_floor"]["path"])
        payload = floor_path.read_text(encoding="utf-8")
        assert "camera_0" in payload, (
            "proc_name из базы процесса не доехал до severity-пути — ровно то, "
            "ради чего Ф0.5 вводила второй слой контекста"
        )
        assert "из форточки" in payload, "log_context не доехал до severity-пути"
    finally:
        log_context.reset(token)
        mgr.shutdown()


def test_severity_path_thread_context_still_wins(tmp_path: Path) -> None:
    """Приоритет слоёв на severity-пути тот же, что у логгера: поток перекрывает базу.

    Без этой проверки предыдущий тест зеленел бы и в реализации, которая
    просто приклеила базу поверх всего, сломав порядок приоритетов.
    """
    mgr = ErrorManager(
        manager_name="CtxOrderProbe",
        config=ErrorManagerConfig(
            app_name="phase_findings",
            enable_batching=False,
            critical_file_path=str(tmp_path / "critical.log"),
            error_file_path=str(tmp_path / "errors.log"),
            warnings_file_path=None,
        ),
        process=_FakeProcess("ctx_order_probe"),
    )
    mgr.initialize()
    try:
        mgr.set_base_context(who="база")
        mgr.push_context(who="поток")
        for name in list(mgr._channel_registry.names()):
            mgr.set_sink_enabled(name, False)

        mgr.error("кто победит", module="findings", who="явный_extra")

        payload = Path(mgr.get_stats()["error_floor"]["path"]).read_text(encoding="utf-8")
        assert "явный_extra" in payload, "явный extra вызова обязан перекрывать все слои"
        assert "поток" not in payload and "база" not in payload
    finally:
        mgr.pop_context()
        mgr.shutdown()


# =============================================================================
# 4. История потерь консоли переживает reconfigure
# =============================================================================


def test_console_history_survives_reconfigure(tmp_path: Path) -> None:
    """Полная пересборка каналов не стирает счётчики потерь консоли.

    ``set_sink_enabled`` покрыт отдельным тестом в
    ``test_console_backpressure_hazards.py``; здесь — второй путь ухода канала,
    через ``reconfigure`` (hot-reload секции observability).
    """
    mgr = LoggerManager(
        manager_name="ConsoleHistoryProbe",
        config=LoggerManagerConfig(
            app_name="phase_findings",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels={"console": LoggerChannelSchema(name="console", type="console", format="%(message)s")},
            scopes={"SYSTEM": LoggerScopeSchema(enabled=True, min_level="WARNING", channels=["console"])},
        ),
        process=_FakeProcess("console_history"),
    )
    mgr.initialize()
    try:
        console = mgr.get_channel("console")
        assert console is not None
        console.sink_writes_dropped = 5
        assert mgr.get_stats()["sink_writes_dropped"] == 5

        applied = mgr.reconfigure(mgr.config.model_dump())
        assert applied is True, "предусловие: валидный reconfigure применился"

        assert mgr.get_stats()["sink_writes_dropped"] == 5, (
            "hot-reload стёр историю потерь консоли — а reload делают как раз при разборе"
        )
    finally:
        mgr.shutdown()


def test_absorbed_history_lists_every_backpressure_key(tmp_path: Path) -> None:
    """Накопитель обязан забирать ВСЕ ключи давления, а не только первый.

    Страж против частичного переноса: добавили третий счётчик на канал,
    в ``_on_channel_removed`` его забыли — и он теряется при снятии приёмника,
    а остальные нет. Расхождение такого рода читается как «этот счётчик всегда
    нулевой», а не как дефект.
    """
    from multiprocess_framework.modules.logger_module.core.logger_core import _CHANNEL_BACKPRESSURE_KEYS

    mgr = LoggerManager(
        manager_name="AbsorbAllProbe",
        config=LoggerManagerConfig(
            app_name="phase_findings",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels={"console": LoggerChannelSchema(name="console", type="console", format="%(message)s")},
            scopes={"SYSTEM": LoggerScopeSchema(enabled=True, min_level="WARNING", channels=["console"])},
        ),
        process=_FakeProcess("absorb_all"),
    )
    mgr.initialize()
    try:
        console = mgr.get_channel("console")
        assert console is not None
        for offset, key in enumerate(_CHANNEL_BACKPRESSURE_KEYS, start=1):
            setattr(console, key, offset)

        mgr.set_sink_enabled("console", False)

        stats = mgr.get_stats()
        missing: List[str] = [
            key for offset, key in enumerate(_CHANNEL_BACKPRESSURE_KEYS, start=1) if stats[key] != offset
        ]
        assert not missing, f"эти счётчики потерялись при снятии канала: {missing}"
    finally:
        mgr.shutdown()
