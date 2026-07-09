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
    ObservabilityDrainAdapter,
    ObservabilityHub,
)


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
) -> None:
    """Слить буфер hub'а (log/stats) в реальные менеджеры.

    Зовётся по такту heartbeat и финально на graceful-teardown. error-канал
    hub'а пуст (error идёт write-through мимо буфера) — apply_drained по нему
    вырождается в no-op. Исключения глушим: дренаж телеметрии не должен ронять
    такт heartbeat (урок 2.1 — health self-publish не критичен).
    """
    if hub is None or adapter is None:
        return
    adapter.apply_drained(hub.drain_all())
