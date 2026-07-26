# -*- coding: utf-8 -*-
"""Детерминированная доставка state-дельт в тестах (Ф6.1/Ф6.3 truth-holes-closure).

Дельты уходят подписчику не в потоке-мутаторе, а тиком daemon-flusher'а (~120 мс) —
это единственный путь с Ф6.3 (флаг ``FW_STATE_COALESCE`` удалён вместе с OFF-веткой).
Тесты, которые проверяют ЧТО доставлено (формат конверта, revision-gap, resync, кэш
прокси), от расписания доставки не зависят — но ассерт сразу после мутации видел бы
пустой роутер.

Два плохих выхода и один хороший:

- ждать реальный тик (``sleep``) — flaky и медленно;
- пинить тесты в режим немедленной отправки — такого режима больше нет вовсе, а
  пока он был, пиннинг уводил сквозные тесты с ПРОДОВОГО пути: ровно та подмена,
  из-за которой дыры и заводятся;
- **flush сразу после dispatch** — тот же прод-путь (буфер, конверт с min/max
  revision, единственный отправитель), только тик заменён детерминированным
  вызовом. Так тест проверяет прод-режим и остаётся воспроизводимым.

Расписание доставки (тик, cap, порядок конвертов, финальный дренаж на shutdown) —
предмет ``test_delta_coalescing.py``; там ЭТОТ хелпер не применяется.
"""

from __future__ import annotations

from ..manager.delta_dispatcher import DeltaDispatcher


def apply_deterministic_delivery(monkeypatch) -> None:
    """Заменить тик flusher'а немедленным flush после каждого dispatch.

    Патчится КЛАСС (не инстанс): тесты создают ``StateStoreManager``/``DeltaDispatcher``
    в десятках мест, и перехват на уровне класса не требует трогать ни один вызов.
    """
    original_dispatch = DeltaDispatcher.dispatch
    original_dispatch_single = DeltaDispatcher.dispatch_single
    # Реплей подписчику (снимок дерева на subscribe) в ON-режиме тоже идёт через буфер —
    # без него три теста initial-replay видели бы пустой роутер.
    original_enqueue_replay = DeltaDispatcher.enqueue_replay

    def dispatch(self, deltas):
        stats = original_dispatch(self, deltas)
        self._flush_once()
        return stats

    def dispatch_single(self, delta):
        stats = original_dispatch_single(self, delta)
        self._flush_once()
        return stats

    def enqueue_replay(self, subscriber, deltas):
        result = original_enqueue_replay(self, subscriber, deltas)
        self._flush_once()
        return result

    monkeypatch.setattr(DeltaDispatcher, "dispatch", dispatch)
    monkeypatch.setattr(DeltaDispatcher, "dispatch_single", dispatch_single)
    monkeypatch.setattr(DeltaDispatcher, "enqueue_replay", enqueue_replay)


__all__ = ["apply_deterministic_delivery"]
