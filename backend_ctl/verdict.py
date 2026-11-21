# -*- coding: utf-8 -*-
"""verdict.py — форма вердикта I3 «причинность проверки» (Task 0.3).

«Проверено» = образ ДО + подтверждение хоста + образ ПОСЛЕ. Ответ «success»
без образа до и после — не доказательство: запись, которую хост отверг при уже
равном значении, выглядит как успех (B-3, ревизия наблюдаемости).

Чистый модуль: без ввода-вывода, без импортов ``multiprocess_*``. Два публичных
символа:

  * :func:`is_refusal` — «ack хоста — отказ?» (определение ниже);
  * :func:`judge` — единый суд над одной проверкой записи.

Отказ ack — dict, у которого (``success is False`` и ``error != "timeout"``)
ИЛИ ``status == "error"``. НЕ отказ: таймаут (``{"success": False, "error":
"timeout"}``), ``None``, не-dict (строка, число), dict без ``success`` и
``status``. Таймаут — не отказ: ``process.restart`` и запись штатно отвечают
таймаутом при доставленной команде; решает образ после.

Применяется только к ``set_register_verified`` и к полю ``register_restore``
(подключает Task 0.11). Остальные инструменты контракта читают свои ключи:
``config_reload_verified`` (BCTL-ADR-008: ``success`` — про применение, не
вердикт) и ``process_restart_verified`` (``restarted``, успех обратный).

Тела — заглушки стадии INTERFACE; реализация — стадия GREEN Task 0.3.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from typing import Any

__all__ = ["judge", "is_refusal"]


def is_refusal(ack: Any) -> bool:
    """Отказ ли ack хоста.

    Pre: любой объект.
    Post: ``bool``; не бросает. ``True`` только для dict, у которого
        (``success is False`` и ``error != "timeout"``) или ``status == "error"``.
    """
    raise NotImplementedError("Task 0.3 GREEN: is_refusal")


def judge(
    pre: Any,
    ack: Any,
    post: Any,
    target: Any,
    *,
    unreadable: tuple[str, ...] = (),
    eq: Callable[[Any, Any], bool] = operator.eq,
) -> dict:
    """Вердикт проверки записи по образу до, ack хоста и образу после.

    Pre: ``unreadable`` — кортеж имён из {``"pre"``, ``"post"``}; ``eq(a, b)`` —
        булево сравнение двух значений.
    Post: ответ — всегда dict с ключами ``verdict`` (``confirmed`` / ``vacuous`` /
        ``failed`` / ``unverifiable``), ``vacuous`` (bool), ``success`` (bool),
        ``pre``, ``post``, ``ack``, ``unverifiable`` (``list(unreadable)`` при
        любом вердикте); исключение наружу не выходит (исключение из ``eq`` —
        «не равно»).

    Правила — строго в этом порядке, первое сработавшее побеждает:
      1. :func:`is_refusal` (ack) -> ``failed``;
      2. ``unreadable`` не пуст -> ``unverifiable``;
      3. ``not eq(post, target)`` -> ``failed``;
      4. ``eq(pre, target)`` -> ``vacuous``;
      5. иначе -> ``confirmed``.

    ``vacuous = ("pre" not in unreadable) and eq(pre, target)`` — при ЛЮБОМ
    вердикте. ``success = verdict in {"confirmed", "vacuous"}`` — формула живёт
    только здесь.
    """
    raise NotImplementedError("Task 0.3 GREEN: judge")
