# -*- coding: utf-8 -*-
"""Ф4.2 — опасности единой точки эмиссии (авторские тесты на механизм).

Характеризацию поведения ErrorManager держит
``error_module/tests/test_emission_characterization.py``. Здесь — то, что видно
только автору слияния: контракт хука ``_route`` и дыры, которые слияние
вскрыло или могло создать.

Три опасности, каждая проверяется отдельно:
  1. **Контракт возврата тройной**, и путать его нельзя: ``None`` = запись
     отклонена гейтом (``messages_skipped``), ``[]`` = приёмников нет
     (``records_without_channels``), непустой список = адресаты. Разница между
     первыми двумя — «мы решили не писать» против «мы хотели, но некуда».
  2. **Пустой список раньше проваливался в ветку буфера**: ничего не клал и всё
     равно инкрементировал ``messages_batched``. Потеря была не просто тихой —
     счётчик активно уверял, что запись ушла.
  3. **Общая часть обязана быть общей.** Контекст, tap'ы и учёт потерь теперь
     физически одни — тесты проверяют это на наследнике с ЧУЖИМ резолвом, а не
     на самом логгере, где всё и так в одном месте.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from multiprocess_framework.modules.channel_routing_module.interfaces import IChannel
from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LogLevel,
    LoggerScopeSchema,
    LogScope,
)
from multiprocess_framework.modules.logger_module.configs import LoggerRuleSchema
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.core.name_hierarchy import NameHierarchy


class _SpyChannel(IChannel):
    def __init__(self, name: str) -> None:
        self._name = name
        self.written: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "spy"

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self.written.append(data)
        return {"status": "success", "channel": self._name}

    def close(self) -> None:
        pass


def _logger(tmp_path: Path, *, batching: bool = False) -> LoggerManager:
    mgr = LoggerManager(
        manager_name="EmissionPoint",
        config=LoggerManagerConfig(
            app_name="emission",
            log_directory=str(tmp_path),
            enable_batching=batching,
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
    )
    mgr.initialize()
    return mgr


class _CustomRouting(LoggerManager):
    """Наследник с ЧУЖИМ резолвом — модель того, чем стал ErrorManager.

    Смысл теста на нём, а не на ErrorManager: доказывается свойство хука, а не
    поведение конкретного менеджера ошибок. Если общая часть снова расползётся
    по копиям, сломается здесь — у наследника, который её не писал.
    """

    forced: Optional[List[str]] = None

    def _route(self, scope: LogScope, level: LogLevel, module: str) -> Optional[List[str]]:
        if self.forced is not None:
            return list(self.forced)
        return super()._route(scope, level, module)


def _custom(tmp_path: Path, forced: Optional[List[str]], *, batching: bool = False) -> _CustomRouting:
    mgr = _CustomRouting(
        manager_name="CustomRouting",
        config=LoggerManagerConfig(
            app_name="custom",
            log_directory=str(tmp_path),
            enable_batching=batching,
            modules={},
            channels={
                "a": LoggerChannelSchema(
                    name="a", type="file", enabled=True, file_path="a.log", format="%(message)s", rotate=False
                ),
            },
            # Скоуп БЕЗ списка каналов: резолв родителя возьмёт весь реестр.
            scopes={"SYSTEM": LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=[])},
        ),
    )
    mgr.initialize()
    mgr.forced = forced
    return mgr


# ---------------------------------------------------------------------------
# Контракт возврата _route
# ---------------------------------------------------------------------------


def test_none_means_gated_not_lost(tmp_path: Path) -> None:
    """``None`` учитывается как отклонение гейтом, а не как потеря."""
    mgr = _custom(tmp_path, forced=None)
    try:
        mgr.config.scopes["SYSTEM"].enabled = False
        mgr.invalidate_decision_cache()

        mgr.log(LogScope.SYSTEM, LogLevel.INFO, "заглушённое", module="m")

        assert mgr.stats["messages_skipped"] == 1
        assert mgr.stats["records_without_channels"] == 0, "отклонение гейтом посчитали потерей"
    finally:
        mgr.shutdown()


def test_empty_list_is_counted_as_loss(tmp_path: Path) -> None:
    """``[]`` — потеря, и она видна: ни один приёмник не назван.

    Достижимо без наследника: скоуп без списка каналов + пустой реестр (все
    приёмники сняты ``logger.sink.disable``).
    """
    mgr = _custom(tmp_path, forced=[])
    try:
        mgr.log(LogScope.SYSTEM, LogLevel.INFO, "некуда", module="m")

        assert mgr.stats["records_without_channels"] == 1
        assert mgr.stats["messages_skipped"] == 0, "потерю посчитали отклонением гейтом"
    finally:
        mgr.shutdown()


def test_empty_list_does_not_count_as_batched(tmp_path: Path) -> None:
    """Счётчик не имеет права утверждать, что запись ушла в буфер.

    Именно этим старая ветка и была опасна: ``messages_batched`` рос, в буфер не
    попадало ничего, и по числам всё выглядело здоровым.
    """
    mgr = _custom(tmp_path, forced=[], batching=True)
    try:
        # Дельта, а не абсолют: менеджер логирует собственное ``initialized``
        # через себя же, и к моменту проверки счётчик уже ненулевой. Абсолютный
        # ноль здесь был бы тестом на то, что менеджер молчит о своём старте.
        before = mgr.stats["messages_batched"]

        mgr.log(LogScope.SYSTEM, LogLevel.INFO, "некуда", module="m")

        assert mgr.stats["messages_batched"] == before, "пустая адресация посчитана как батченая"
        assert mgr.stats["records_without_channels"] == 1
    finally:
        mgr.shutdown()


def test_empty_list_for_error_goes_to_floor(tmp_path: Path) -> None:
    """У ошибки без приёмников есть пол — потери не происходит вовсе."""
    mgr = _custom(tmp_path, forced=[])
    try:
        mgr.log(LogScope.SYSTEM, LogLevel.ERROR, "ошибка без приёмников", module="m")

        assert mgr.stats["errors_to_floor"] == 1
        assert mgr.stats["records_without_channels"] == 0, "ошибка спасена полом — это не потеря"
    finally:
        mgr.shutdown()


def test_loss_warning_is_emitted_once(tmp_path: Path) -> None:
    """Предупреждение о потере не должно само стать штормом.

    Приёмников нет — значит предупреждать некуда, кроме stdlib-fallback'а;
    без ограничения он получил бы строку на каждую запись ровно тогда, когда
    система и так в плохом состоянии.
    """
    mgr = _custom(tmp_path, forced=[])
    try:
        emitted: List[str] = []
        mgr._fallback_log = lambda level, msg: emitted.append(f"{level}:{msg}")  # type: ignore[method-assign]

        for _ in range(5):
            mgr.log(LogScope.SYSTEM, LogLevel.INFO, "некуда", module="m")

        assert mgr.stats["records_without_channels"] == 5, "считать надо каждую, а не только первую"
        assert len(emitted) == 1, f"предупреждений {len(emitted)}, ожидалось одно"
    finally:
        mgr.shutdown()


# ---------------------------------------------------------------------------
# Общая часть действительно общая
# ---------------------------------------------------------------------------


def test_custom_routing_gets_shared_context(tmp_path: Path) -> None:
    """Наследник с чужим резолвом получает сборку контекста даром.

    Ровно то, что развилка теряла: ``proc_name`` из базы процесса не доезжал до
    severity-пути, потому что тот собирал ``extra`` своей копией.
    """
    mgr = _custom(tmp_path, forced=["a"])
    try:
        spy = _SpyChannel("a")
        mgr._channel_registry.unregister("a")
        mgr._channel_registry.register(spy)
        mgr.set_base_context(proc_name="camera_0")

        mgr.log(LogScope.SYSTEM, LogLevel.INFO, "запись", module="m")

        assert spy.written[0]["extra"]["proc_name"] == "camera_0"
    finally:
        mgr.shutdown()


def test_custom_routing_feeds_taps(tmp_path: Path) -> None:
    """И tap'ы — тоже даром, без своей копии рассылки."""
    mgr = _custom(tmp_path, forced=["a"])
    try:
        tap = _SpyChannel("tap")
        mgr.add_tap(tap, min_level="DEBUG", name="tap")

        mgr.log(LogScope.SYSTEM, LogLevel.INFO, "запись", module="m")

        assert [r["message"] for r in tap.written] == ["запись"]
    finally:
        mgr.shutdown()


def test_custom_routing_counts_unresolved(tmp_path: Path) -> None:
    """И учёт потерь — тоже. Резолв назвал канал, которого нет."""
    mgr = _custom(tmp_path, forced=["его_нет"])
    try:
        before = mgr.stats["unresolved_channel_records"]

        mgr.log(LogScope.SYSTEM, LogLevel.INFO, "запись", module="m")

        assert mgr.stats["unresolved_channel_records"] - before == 1
    finally:
        mgr.shutdown()


def test_extra_channel_dedup_survives(tmp_path: Path) -> None:
    """Дедупликация приёмников живёт в ``_route`` и обязана работать там.

    Инвариант Ф0.9 «одна запись — одна копия». **Переклассифицирован в Ф2.6:**
    раньше вторую копию давал per-module канал — при скоупе без явного списка
    fallback брал весь реестр, где module-канал уже лежал, и его дописывали
    вторым. Механизм снят, сложение осталось (``channels_extra``), и ловушка
    воспроизводится дословно: добавка называет приёмник, который уже пришёл из
    fallback'а.
    """
    mgr = _logger(tmp_path)
    try:
        mgr.config.scopes["SYSTEM"].channels = []
        spy = _SpyChannel("проба_файл")
        mgr._channel_registry.register(spy)
        mgr._name_hierarchy = NameHierarchy({"proba": LoggerRuleSchema(channels_extra=["проба_файл"])})
        mgr.invalidate_decision_cache()

        mgr.log(LogScope.SYSTEM, LogLevel.INFO, "одна запись", module="proba")

        assert len(spy.written) == 1, f"запись легла в приёмник {len(spy.written)} раз(а)"
    finally:
        mgr.shutdown()


# Ф2.6: тест «module-канал вне реестра всё равно принимает» снят вместе с
# механизмом. Он сторожил хук ``_resolve_channel``, существовавший ровно потому,
# что у логгера было ДВА хранилища каналов: generic-выключение приёмника снимало
# канал из реестра, а второй словарь его сохранял. Хранилище теперь одно, и
# расходиться нечему — свойство исчезло вместе с причиной, а не осталось
# непроверенным. Само выключение приёмника и его учёт покрыты
# ``test_sink_control.py`` и ``test_unknown_channel_accounting.py``.
