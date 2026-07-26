# -*- coding: utf-8 -*-
"""Ф0.4 — учёт записей, адресованных несуществующему каналу.

План: plans/observability-unified-routing.md, задача 0.4.

Дефект (поведенчески, без ссылки на реализацию): запись лога может быть
адресована имени канала, которого не существует — опечатка в scopes
конфига, канал снят через ``logger.sink.disable``, канал никогда не
создавался. Сегодня такая запись теряется МОЛЧА: ни счётчика, ни следа.
Это отдельный класс потери от уже закрытых (переполнение буфера — Ф0.3,
пол ошибок — Ф0.9): там канал существует и либо не успевает, либо все
каналы отсутствуют одновременно (только для ERROR/CRITICAL). Здесь канал,
названный в конфиге, не резолвится в объект вовсе — для ЛЮБОГО уровня.

НЕЗАВИСИМЫЙ тестировщик: этот файл писался БЕЗ чтения
``logger_module/core/logger_core.py`` и без чтения незакоммиченного диффа.
Источник контракта — задание оркестратора (Ф0.4) поверх публичного API,
уже подтверждённого соседними тестами (``test_counters_visible_path.py``,
``test_error_floor.py``, ``test_sink_control.py``).

Публичный контракт, который проверяется:
    ``LoggerManager.get_stats()`` (и ``LoggerCore.get_stats()``) ВСЕГДА
    содержит:
      - ``unresolved_channel_records: int``
      - ``unresolved_channels: dict[str, int]``
      - ``channel_write_errors: int``
      - ``channel_write_errors_by_channel: dict[str, int]``

Ожидаемый результат прогона: ВСЕ тесты в этом файле КРАСНЫЕ — фикс ещё не
написан. Это половина пары «болезнь воспроизведена → исчезла».
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from multiprocess_framework.modules.logger_module.channels.log_channel import LogChannel
from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    observability_counters,
)


# =============================================================================
# Инфраструктура
# =============================================================================


def _config(
    tmp_path: Path,
    *,
    enable_batching: bool,
    scope_channels: List[str],
    extra_channels: Optional[Dict[str, LoggerChannelSchema]] = None,
    batch_size: int = 10_000,
    batch_interval: float = 600.0,
) -> LoggerManagerConfig:
    """Логгер с единственным реальным скоупом BUSINESS (куда роутит ``.info()``).

    ``batch_size``/``batch_interval`` намеренно огромны по умолчанию — сброс
    пачки происходит только явным ``manager.flush()``, а не по таймеру или
    по заполнению (если явно не попросили иное через параметры).
    """
    channels: Dict[str, LoggerChannelSchema] = {
        "system_file": LoggerChannelSchema(
            name="system_file", type="file", enabled=True, file_path="system.log", rotate=False
        ),
    }
    if extra_channels:
        channels.update(extra_channels)
    return LoggerManagerConfig(
        app_name="unknown_channel_unit",
        log_directory=str(tmp_path),
        enable_batching=enable_batching,
        batch_size=batch_size,
        batch_interval=batch_interval,
        modules={},
        channels=channels,
        scopes={
            "BUSINESS": LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=scope_channels),
        },
    )


@contextmanager
def _logger(
    tmp_path: Path,
    *,
    enable_batching: bool,
    scope_channels: List[str],
    extra_channels: Optional[Dict[str, LoggerChannelSchema]] = None,
    batch_size: int = 10_000,
) -> Iterator[LoggerManager]:
    manager = LoggerManager(
        manager_name="UnknownChannelLogger",
        config=_config(
            tmp_path,
            enable_batching=enable_batching,
            scope_channels=scope_channels,
            extra_channels=extra_channels,
            batch_size=batch_size,
        ),
    )
    try:
        yield manager
    finally:
        manager.shutdown()


class _ErrorStatusChannel(LogChannel):
    """Канал, который ОТКАЗЫВАЕТ (``status: error``), но не бросает исключение.

    Эта потеря — НЕ write-ошибка в смысле нового счётчика: она уже учтена
    как ``flush_failed`` (см. ``test_counters_visible_path.py``). Счётчик
    исключений (``channel_write_errors``) обязан остаться на нуле.
    """

    def __init__(self, name: str) -> None:
        super().__init__(LoggerChannelSchema(name=name, type="console", enabled=True))

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "error", "channel": self.name, "error": "отклонено намеренно"}


class _RaisingChannel(LogChannel):
    """Канал, который падает с исключением внутри ``write()`` — настоящая write-ошибка."""

    def __init__(self, name: str) -> None:
        super().__init__(LoggerChannelSchema(name=name, type="console", enabled=True))

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        raise RuntimeError("симулированный сбой канала")


# =============================================================================
# 1. Оба пути доставки считают (п.1 контракта)
# =============================================================================


def test_unresolved_channel_counted_on_buffered_path(tmp_path: Path) -> None:
    """Батчинг включён: неизвестное имя канала в scope-конфиге, 5 записей, явный flush."""
    with _logger(tmp_path, enable_batching=True, scope_channels=["ghost_channel"]) as manager:
        for i in range(5):
            manager.info(f"buffered {i}", module="unit")
        manager.flush()

        stats = manager.get_stats()
        assert stats["unresolved_channel_records"] == 5
        assert stats["unresolved_channels"] == {"ghost_channel": 5}
        assert stats["channel_write_errors"] == 0
        assert stats["channel_write_errors_by_channel"] == {}


def test_unresolved_channel_counted_on_direct_path(tmp_path: Path) -> None:
    """Батчинг выключен: та же ситуация обязана считаться и без буфера вовсе."""
    with _logger(tmp_path, enable_batching=False, scope_channels=["ghost_channel"]) as manager:
        for i in range(5):
            manager.info(f"direct {i}", module="unit")

        stats = manager.get_stats()
        assert stats["unresolved_channel_records"] == 5
        assert stats["unresolved_channels"] == {"ghost_channel": 5}


def test_unresolved_after_sink_disabled(tmp_path: Path) -> None:
    """Вариант из списка дефекта: канал БЫЛ, снят через ``logger.sink.disable`` в рантайме.

    ``set_sink_enabled(name, False)`` реально убирает канал из ``_channel_registry``
    (см. ``test_sink_control.py``), поэтому сценарий тождественен «канал не резолвится».
    """
    with _logger(tmp_path, enable_batching=True, scope_channels=["system_file"]) as manager:
        assert manager.set_sink_enabled("system_file", False) is True

        for i in range(4):
            manager.info(f"запись после disable {i}", module="unit")
        manager.flush()

        stats = manager.get_stats()
        assert stats["unresolved_channel_records"] == 4
        assert stats["unresolved_channels"] == {"system_file": 4}


# =============================================================================
# 2. Считается ПО ЗАПИСИ, а не по пачке (п.2 контракта)
# =============================================================================


def test_unresolved_channel_count_accumulates_across_batches(tmp_path: Path) -> None:
    """7 записей, пачка по 2 → несколько авто-сбросов + финальный flush.

    Страж от реализации, которая ПЕРЕЗАПИСЫВАЕТ счётчик на каждом flush вместо
    накопления: неверная версия дала бы 1 (размер последней недо-пачки) или 2
    (размер последнего полного flush), а не 7.
    """
    with _logger(tmp_path, enable_batching=True, scope_channels=["ghost_channel"], batch_size=2) as manager:
        for i in range(7):
            manager.info(f"batch item {i}", module="unit")
        manager.flush()

        stats = manager.get_stats()
        assert stats["unresolved_channel_records"] == 7
        assert stats["unresolved_channels"] == {"ghost_channel": 7}


# =============================================================================
# 3. Ровно одно WARNING на неизвестное имя, НАВСЕГДА (п.3 контракта)
# =============================================================================


def test_exactly_one_warning_per_unknown_channel_name(tmp_path: Path, caplog) -> None:
    """Первая запись на новое имя — одно WARNING; повтор того же имени — тишина;
    другое неизвестное имя — своё персональное WARNING.

    Предупреждение проверяется через ``caplog`` на fallback-логгер модуля (stdlib
    ``logging``), а не через собственную маршрутизацию каналов логгера — как и
    требует контракт. Логгер адресуется по имени пакета (``multiprocess_framework``),
    а не по точному модулю: точное имя логгера внутри ``logger_core.py`` — деталь
    реализации, которую независимый тест не обязан знать.
    """
    with _logger(tmp_path, enable_batching=True, scope_channels=["ghost_a"]) as manager:
        with caplog.at_level(logging.WARNING, logger="multiprocess_framework"):
            for i in range(3):
                manager.info(f"запись {i} на ghost_a", module="unit")
            manager.flush()

            assert len(caplog.records) == 1, "первая запись на новое имя обязана дать ровно одно WARNING"
            assert "ghost_a" in caplog.records[0].getMessage()

            # Ещё записи на ТО ЖЕ имя — второго предупреждения быть не должно.
            for i in range(2):
                manager.info(f"снова ghost_a {i}", module="unit")
            manager.flush()
            assert len(caplog.records) == 1, "повтор уже известного имени не должен плодить WARNING"

            # Другое неизвестное имя — своё персональное предупреждение.
            manager.config.scopes["BUSINESS"].channels = ["ghost_b"]
            manager.invalidate_decision_cache()
            manager.info("запись на ghost_b", module="unit")
            manager.flush()

            assert len(caplog.records) == 2, "новое неизвестное имя обязано получить своё предупреждение"
            assert "ghost_b" in caplog.records[1].getMessage()


# =============================================================================
# 4. Счётчики не зависят от того, заглушено ли предупреждение (п.4 контракта)
# =============================================================================


def test_counting_continues_when_warning_is_silenced(tmp_path: Path, caplog) -> None:
    """Порог CRITICAL глушит WARNING полностью — но учёт обязан продолжаться."""
    with _logger(tmp_path, enable_batching=True, scope_channels=["ghost_silent"]) as manager:
        with caplog.at_level(logging.CRITICAL, logger="multiprocess_framework"):
            for i in range(5):
                manager.info(f"тихая запись {i}", module="unit")
            manager.flush()

        assert len(caplog.records) == 0, "порог CRITICAL обязан подавить WARNING целиком"

        stats = manager.get_stats()
        assert stats["unresolved_channel_records"] == 5, "заглушённое предупреждение не должно глушить счётчик"
        assert stats["unresolved_channels"] == {"ghost_silent": 5}


# =============================================================================
# 5. Здоровая установка — ноль везде (п.5 контракта)
# =============================================================================


def test_healthy_setup_reports_zero(tmp_path: Path) -> None:
    """Все каналы резолвятся → все четыре счётчика молчат нулём.

    Страж от над-учёта: рядом лежит НЕИСПОЛЬЗУЕМЫЙ отключённый канал
    (``enabled=False``, не упомянут ни в одном scope) — неверная реализация,
    перебирающая ВСЕ объявленные каналы вместо реально адресованных записей,
    засветилась бы здесь.
    """
    extra = {
        "unused_disabled": LoggerChannelSchema(name="unused_disabled", type="console", enabled=False),
    }
    with _logger(tmp_path, enable_batching=True, scope_channels=["system_file"], extra_channels=extra) as manager:
        for i in range(10):
            manager.info(f"здоровая запись {i}", module="unit")
        manager.flush()

        stats = manager.get_stats()
        assert stats["unresolved_channel_records"] == 0
        assert stats["unresolved_channels"] == {}
        assert stats["channel_write_errors"] == 0
        assert stats["channel_write_errors_by_channel"] == {}


# =============================================================================
# 6. channel_write_errors — про ИСКЛЮЧЕНИЕ, а не про отказ статусом (п.6 контракта)
# =============================================================================


def test_channel_error_status_is_not_counted_as_write_error(tmp_path: Path) -> None:
    """Канал вернул ``{"status": "error"}`` — это НЕ write-ошибка для нового счётчика."""
    with _logger(tmp_path, enable_batching=False, scope_channels=["system_file"]) as manager:
        manager._channel_registry.unregister("system_file")
        manager._channel_registry.register(_ErrorStatusChannel("system_file"))

        manager.info("запись, которую канал отклонит статусом", module="unit")

        stats = manager.get_stats()
        assert stats["channel_write_errors"] == 0
        assert stats["channel_write_errors_by_channel"] == {}


def test_channel_exception_is_counted_as_write_error(tmp_path: Path) -> None:
    """Канал бросает исключение из ``write()`` — вот это настоящая write-ошибка."""
    with _logger(tmp_path, enable_batching=False, scope_channels=["system_file"]) as manager:
        manager._channel_registry.unregister("system_file")
        manager._channel_registry.register(_RaisingChannel("system_file"))

        manager.info("первая запись", module="unit")
        manager.info("вторая запись", module="unit")

        stats = manager.get_stats()
        assert stats["channel_write_errors"] == 2
        assert stats["channel_write_errors_by_channel"] == {"system_file": 2}


# =============================================================================
# 7. Видимый путь — ключи обязаны доехать до observability_counters() (п.7 контракта)
# =============================================================================


REQUIRED_UNRESOLVED_KEYS: List[str] = [
    "unresolved_channel_records",
    "unresolved_channels",
    "channel_write_errors",
    "channel_write_errors_by_channel",
]


def test_unresolved_channel_keys_reach_observability_counters(tmp_path: Path) -> None:
    """Ключи из контракта обязаны доехать до ``observability_counters()``, не только до ``get_stats()``.

    Класс отказа этого проекта уже стрелял дважды на соседнем счётчике
    (Ф0.3): счётчик существовал в ``get_stats()``, но наружу его пересылал
    ``_plane_counters()`` (``observability_reload.py``) через ЖЁСТКО
    перечисленный список ключей — новый счётчик в этот список автоматически
    не попадает. Страж ловит оба варианта потери: «счётчика нет в
    get_stats()» и «есть в get_stats(), но потерян на пересылке».
    """
    with _logger(tmp_path, enable_batching=True, scope_channels=["ghost_visible"]) as manager:
        manager.info("невидимый маршрут", module="unit")
        manager.flush()

        counters = observability_counters(logger=manager)["logger"]
        missing = [k for k in REQUIRED_UNRESOLVED_KEYS if k not in counters]
        assert not missing, f"ключи не доехали до observability_counters: {missing}"
