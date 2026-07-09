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

# Имя store-tap'а на error_manager (хэндл для remove_log_tap на teardown).
STORE_ERROR_TAP = "observability_store::error"


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
    db_path: Optional[str] = None,
) -> Tuple[Optional[ObservabilityStore], Optional[str]]:
    """Создать персистентный стор и повесить store-tap на error_manager (Ф5.20a).

    error/critical идут write-through в error_manager (Ф5.16) — tap ловит их у
    реального sink'а и кладёт в стор (так вкладка «Ошибки» получает историю).
    log/stats пишутся в стор из drain-петли (см. drain_process_observability).

    Args:
        error_manager: реальный ErrorManager (LoggerCore с add_log_tap). None или
            без add_log_tap → стор создаётся, но error-tap не вешается.
        db_path: путь к SQLite-файлу стора. None → resolve_default_db_path().

    Returns:
        (store, tap_name) или (store, None) если tap не повешен.
    """
    store = ObservabilityStore(db_path)
    if error_manager is None or not hasattr(error_manager, "add_log_tap"):
        return store, None
    channel = StoreTapChannel(store, name=STORE_ERROR_TAP)
    # min_level=ERROR → ловим error + critical, ниже не пишем (вкладка «Ошибки»).
    error_manager.add_log_tap(channel, min_level="ERROR", name=STORE_ERROR_TAP)
    return store, STORE_ERROR_TAP


def unwire_observability_store(
    error_manager: Optional[Any],
    store: Optional[ObservabilityStore],
    tap_name: Optional[str],
) -> None:
    """Снять store-tap с error_manager и закрыть стор (graceful teardown)."""
    if error_manager is not None and tap_name and hasattr(error_manager, "remove_log_tap"):
        try:
            error_manager.remove_log_tap(tap_name)
        except Exception:  # nosec B110 — teardown best-effort
            pass
    if store is not None:
        try:
            store.close()
        except Exception:  # nosec B110
            pass
