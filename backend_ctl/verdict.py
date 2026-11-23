# -*- coding: utf-8 -*-
"""verdict.py — форма вердикта I3 «причинность проверки» (Task 0.3).

«Проверено» = образ ДО + подтверждение хоста + образ ПОСЛЕ. Ответ «success»
без образа до и после — не доказательство: запись, которую хост отверг при уже
равном значении, выглядит как успех (B-3, ревизия наблюдаемости).

Чистый модуль: без ввода-вывода, без импортов пакетов фреймворка. Два публичных
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

Формула успеха живёт только в :func:`judge`: инструмент её не пересчитывает.

Purpose: единая форма вердикта проверки записи (I3) для ``backend_ctl``.
Stability: lite
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
    if not isinstance(ack, dict):
        return False
    if ack.get("status") == "error":
        return True
    return ack.get("success") is False and ack.get("error") != "timeout"


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

    Pre: ``unreadable`` — кортеж/список/frozenset имён из {``"pre"``, ``"post"``},
        не строка и не итератор; ``eq(a, b)`` — булево сравнение двух значений.
    Post: ответ — всегда dict с ключами ``verdict`` (``confirmed`` / ``vacuous`` /
        ``failed`` / ``unverifiable``), ``vacuous`` (bool), ``success`` (bool),
        ``pre``, ``post``, ``ack``, ``unverifiable`` (``list(unreadable)`` при
        любом вердикте); ни одно ``Exception`` из ``eq`` наружу не выходит (оно —
        «не равно»); ``BaseException`` (KeyboardInterrupt, SystemExit) выходит.

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
    vacuous = "pre" not in unreadable and _equal(eq, pre, target)
    if is_refusal(ack):
        verdict = "failed"
    elif unreadable:
        verdict = "unverifiable"
    elif not _equal(eq, post, target):
        verdict = "failed"
    elif vacuous:
        verdict = "vacuous"
    else:
        verdict = "confirmed"
    return {
        "verdict": verdict,
        "vacuous": vacuous,
        "success": verdict in ("confirmed", "vacuous"),
        "pre": pre,
        "post": post,
        "ack": ack,
        "unverifiable": list(unreadable),
    }


def _equal(eq: Callable[[Any, Any], bool], a: Any, b: Any) -> bool:
    """``eq(a, b)`` как bool; исключение из ``eq`` — «не равно» (``judge`` не бросает)."""
    try:
        return bool(eq(a, b))
    except Exception:  # noqa: BLE001 — исключение из eq = «не равно» (DESIGN 0.3)
        return False
