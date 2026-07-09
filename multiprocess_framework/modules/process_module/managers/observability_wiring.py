# -*- coding: utf-8 -*-
"""
Wiring ObservabilityHub в composition root процесса (Ф5.16).

Композиция уровня 1 («рыба») поверх готовых примитивов уровня 0
(ObservabilityHub из channel_routing, ObservabilityDrainAdapter). Владелец
дренажа — ProcessModule (решение владельца 2026-07-09 §6.1, НЕ app_module).

Модель дренажа (§6.1, инвариант 3):
  - Один hub на процесс, тег = имя процесса.
  - Пилот — worker_module: его реестр слотов пуст (managers={}), поэтому
    подмена logger/stats на hub безопасна.
  - log/stats worker'а → hub (bounded-буфер) → drain по такту heartbeat в
    реальные LoggerManager/StatsManager через ObservabilityDrainAdapter.
  - error-слот worker'а остаётся РЕАЛЬНЫМ error_manager — write-through:
    error/critical пишутся синхронно, минуя буфер, потому что auto-restart
    (Ф3.7) убивает процесс SIGKILL'ом, обходя finally/atexit; буфер бы
    потерялся. Так же снимается конфликт «слот → ЛИБО sink, ЛИБО hub».

Хелпер намеренно тонкий и без импорта самого ProcessModule — тестируется в
изоляции (см. tests/test_observability_wiring.py).
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from ...channel_routing_module.observability import (
    KIND_LOG,
    KIND_STATS,
    ObservabilityDrainAdapter,
    ObservabilityHub,
    ObservabilityStore,
    StoreTapChannel,
)

# Имена store-tap'ов (хэндлы для remove_log_tap на teardown). Вешаем на ОБА
# менеджера: error_manager (track_error/write-through) и logger_manager
# (logger.error/ctx.log_error) — приложение логирует ошибки и туда, и туда.
STORE_ERROR_TAP = "observability_store::error"
STORE_LOGGER_TAP = "observability_store::logger_error"


def wire_process_observability(
    process_name: str,
    worker_manager: Optional[Any],
    logger: Optional[Any],
    stats: Optional[Any],
    error: Optional[Any],
) -> Tuple[Optional[ObservabilityHub], Optional[ObservabilityDrainAdapter]]:
    """Создать hub процесса и инъектировать его в слоты пилота (worker_module).

    Args:
        process_name:   Тег hub'а (== имя процесса).
        worker_manager: Пилотный ObservableMixin (слоты подменяются). None →
                        no-op (процесс без воркеров: нечего пилотировать).
        logger/stats/error: Реальные sink-менеджеры для drain-адаптера.

    Returns:
        (hub, adapter) или (None, None) если worker_manager отсутствует.

    Post:
        - worker.get_manager('logger') is hub;  worker.get_manager('stats') is hub;
        - worker.get_manager('error') is error  (write-through, НЕ hub);
        - adapter сконфигурирован на реальные logger/stats/error.
    """
    if worker_manager is None:
        return None, None

    hub = ObservabilityHub(process_name)
    adapter = ObservabilityDrainAdapter(logger=logger, stats=stats, error=error)

    # Буферизуемый путь: log + stats worker'а → hub (drain по heartbeat).
    worker_manager.register_manager("logger", hub)
    worker_manager.register_manager("stats", hub)
    # Write-through путь: error/critical → реальный error_manager напрямую.
    if error is not None:
        worker_manager.register_manager("error", error)

    return hub, adapter


def drain_process_observability(
    hub: Optional[ObservabilityHub],
    adapter: Optional[ObservabilityDrainAdapter],
    store: Optional[ObservabilityStore] = None,
) -> None:
    """Слить буфер hub'а (log/stats) в реальные менеджеры и (опц.) в стор.

    Зовётся по такту heartbeat и финально на graceful-teardown. `drain_all()`
    осушает каналы — вызываем ОДИН раз и разветвляем: adapter → sink-менеджеры,
    store → персистентная история (Ф5.20a). error-канал hub'а пуст (error идёт
    write-through мимо буфера) — в стор ошибки попадают отдельным store-tap'ом на
    error_manager, НЕ отсюда. Исключения глушим: дренаж телеметрии не должен
    ронять такт heartbeat (урок 2.1 — health self-publish не критичен).
    """
    if hub is None:
        return
    drained = hub.drain_all()
    if adapter is not None:
        adapter.apply_drained(drained)
    if store is not None:
        # log + stats из hub'а → стор (пачкой). error сюда НЕ идёт (write-through
        # ловит store-tap на error_manager) — иначе дублирование либо потеря.
        records = drained.get(KIND_LOG, []) + drained.get(KIND_STATS, [])
        if records:
            try:
                store.append_records(records)
            except Exception:  # nosec B110 — сбой стора не критичен для heartbeat
                pass


def wire_observability_store(
    error_manager: Optional[Any],
    logger_manager: Optional[Any] = None,
    db_path: Optional[str] = None,
) -> Tuple[ObservabilityStore, list]:
    """Создать персистентный стор и повесить store-tap на менеджеры ошибок (Ф5.20a).

    error/critical идут write-through в error_manager (Ф5.16) — tap ловит их у
    реального sink'а и кладёт в стор (так вкладка «Ошибки» получает историю).
    log/stats пишутся в стор из drain-петли (см. drain_process_observability).

    **Live-урок (2026-07-09):** ошибки приложения (напр. CapturePlugin через
    `ctx.log_error`) идут в logger_manager, НЕ в error_manager — tap только на
    error_manager видит ~0 ошибок. Поэтому store-tap вешаем НА ОБА менеджера на
    уровне ERROR: и error_manager (write-through track_error/log_exception), и
    logger_manager (`logger.error`/`ctx.log_error`). Оба пишут kind='error'; это
    разные менеджеры-инстансы, одна запись попадает ровно в один → без дублей.

    Args:
        error_manager: реальный ErrorManager (LoggerCore с add_log_tap).
        logger_manager: реальный LoggerManager (LoggerCore с add_log_tap).
        db_path: путь к SQLite-файлу стора. None → resolve_default_db_path().

    Returns:
        (store, taps) — taps: список (manager, tap_name) для unwire.
    """
    store = ObservabilityStore(db_path)
    taps: list[Tuple[Any, str]] = []
    for mgr, tap_name in ((error_manager, STORE_ERROR_TAP), (logger_manager, STORE_LOGGER_TAP)):
        if mgr is None or not hasattr(mgr, "add_log_tap"):
            continue
        # min_level=ERROR → ловим error + critical, ниже не пишем (вкладка «Ошибки»).
        mgr.add_log_tap(StoreTapChannel(store, name=tap_name), min_level="ERROR", name=tap_name)
        taps.append((mgr, tap_name))
    return store, taps


def unwire_observability_store(
    store: Optional[ObservabilityStore],
    taps: Optional[list],
) -> None:
    """Снять store-tap'ы с их менеджеров и закрыть стор (graceful teardown)."""
    for mgr, tap_name in taps or []:
        if mgr is not None and hasattr(mgr, "remove_log_tap"):
            try:
                mgr.remove_log_tap(tap_name)
            except Exception:  # nosec B110 — teardown best-effort
                pass
    if store is not None:
        try:
            store.close()
        except Exception:  # nosec B110
            pass
