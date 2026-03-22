# -*- coding: utf-8 -*-
"""
Семантика сигналов слайдер + поле ввода.

- Живое значение: движение слайдера обновляет только отображаемое число в QLineEdit;
  запись в регистр откладывается.
- Фиксация (committed): после паузы движения слайдера (`SLIDER_COMMIT_DELAY_MS`) или
  по `editingFinished` у поля — вызывается обработчик записи (реализуется в SliderControl).

Все Qt connect-ы для пары слайдер/поле собираются в SliderControl рядом с этими хелперами.
"""
from __future__ import annotations

from typing import Any, Callable

from frontend_module.core.qt_imports import QTimer

# Сохраняем прежний UX: дебаунс после отпускания/движения слайдера.
SLIDER_COMMIT_DELAY_MS = 100


def schedule_slider_value_commit(
    parent: Any,
    callback: Callable[[], None],
    delay_ms: int = SLIDER_COMMIT_DELAY_MS,
) -> None:
    """Отложенный вызов фиксации значения (аналог прежнего QTimer.singleShot на слайдере)."""
    QTimer.singleShot(delay_ms, callback)
