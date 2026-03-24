# -*- coding: utf-8 -*-
"""
Семантика сигналов слайдер + поле ввода.

- Живое значение: движение слайдера обновляет только отображаемое число;
  запись в регистр откладывается.
- Фиксация (committed): после паузы движения слайдера (SLIDER_COMMIT_DELAY_MS)
  или по editingFinished — вызывается обработчик записи.

control_v2 использует DebounceTrait в presenter; этот модуль — для потребителей,
которые не используют presenter (например, минимальные интеграции).
"""
from __future__ import annotations

from typing import Any, Callable

from frontend_module.core.qt_imports import QTimer

SLIDER_COMMIT_DELAY_MS = 100


def schedule_slider_value_commit(
    parent: Any,
    callback: Callable[[], None],
    delay_ms: int = SLIDER_COMMIT_DELAY_MS,
) -> None:
    """Отложенный вызов фиксации значения (аналог QTimer.singleShot)."""
    QTimer.singleShot(delay_ms, callback)
