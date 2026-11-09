# -*- coding: utf-8 -*-
"""Схема шагов ``pre_stop`` ProcessManager (Task 1.4 gui-graceful-close, ADR-PMM-044).

Purpose:
    Разбор ключа ``pre_stop`` конфига PM: список шагов ``{process, command, args, timeout_s}``,
    которые graceful-стоп исполняет ЗАПРОСОМ ребёнку до взвода событий стопа. Негодная запись
    пропускается с текстом ошибки; PM стартует всегда (принцип 5 владельца).

Public API:
    PreStopStep — неизменяемая запись шага (pydantic, ``extra="forbid"``).
    parse_pre_stop(raw) -> tuple[list[PreStopStep], list[str]] — принятые шаги и тексты ошибок.
    PRE_STOP_STEP_MAX_S — потолок ``timeout_s`` одного шага (60,0 с).
    PRE_STOP_TOTAL_MAX_S — потолок суммы ``timeout_s`` принятых шагов (120,0 с, граница включительно).
    PRE_STOP_SLICE_S — срез ожиданий шага (0,05 с).
    run_pre_stop_step(step, *, process_exists, ready_event, request_async, cancel_source, sender) — исполнить
        один шаг запросом с ожиданием ответа; итог ``(источник отмены | None, причина сбоя | None)``.

Stability:
    lite-контракт (контракт-тест ``tests/test_pre_stop_contract.py``). Формат текста ошибки
    ``pre_stop[<i>]: <поле> — <причина>`` — часть контракта: тексты не содержат входных значений.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ...message_module import build_command_message

__all__ = [
    "PRE_STOP_SLICE_S",
    "PRE_STOP_STEP_MAX_S",
    "PRE_STOP_TOTAL_MAX_S",
    "PreStopStep",
    "parse_pre_stop",
    "run_pre_stop_step",
]

PRE_STOP_STEP_MAX_S = 60.0
PRE_STOP_TOTAL_MAX_S = 120.0
#: Срез ожиданий шага: отмена (``force`` / внешнее событие) видна не позже него.
PRE_STOP_SLICE_S = 0.05
#: Допуск сравнения суммы с потолком: 0,1 + 0,2 не должно «превысить» 0,3 из-за двоичной дроби.
_TOTAL_EPS = 1e-9


class PreStopStep(BaseModel):
    """Один шаг ``pre_stop``: команда ``command`` процессу ``process`` с ожиданием ответа ≤ ``timeout_s``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    process: str = Field(strict=True, min_length=1)
    command: str = Field(strict=True, min_length=1)
    args: dict[str, Any] = Field(default_factory=dict, strict=True)
    # strict: ``int`` принимается как ``float``, ``bool`` и строки (``"5"``) — нет.
    timeout_s: float = Field(strict=True, gt=0, le=PRE_STOP_STEP_MAX_S, allow_inf_nan=False)

    @property
    def label(self) -> str:
        """``<process>.<command>`` — значение ``system_stop.pre_stop_step`` и имя шага в логе."""
        return f"{self.process}.{self.command}"


_FIELDS = frozenset(PreStopStep.model_fields)


def _error_text(index: int, exc: ValidationError) -> str:
    """Все ошибки записи — в одну строку. Поле — только известное имя: ``loc`` pydantic для
    лишнего ключа и для ключей ``args`` — входное значение, в текст оно не попадает."""
    parts: list[str] = []
    for err in exc.errors(include_input=False, include_url=False):
        loc = err.get("loc") or ()
        if err.get("type") == "extra_forbidden":
            parts.append("поле — неизвестный ключ")
            continue
        head = loc[0] if loc else None
        field = head if isinstance(head, str) and head in _FIELDS else "поле"
        parts.append(f"{field} — {err.get('msg', 'ошибка')}")
    return f"pre_stop[{index}]: " + "; ".join(parts)


def parse_pre_stop(raw: Any) -> tuple[list[PreStopStep], list[str]]:
    """Разобрать ``pre_stop``: принятые шаги в порядке списка и тексты ошибок (по одной на запись).

    ``None`` или ``[]`` — пусто без ошибок; не список — одна ошибка, шагов нет. Негодная запись
    пропускается, остальные принимаются. Сумма ``timeout_s`` — по принятым записям: запись, с которой
    сумма превысила бы ``PRE_STOP_TOTAL_MAX_S``, пропускается и в сумму не входит.
    """
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], ["pre_stop: ожидается список"]
    steps: list[PreStopStep] = []
    errors: list[str] = []
    total = 0.0
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            errors.append(f"pre_stop[{index}]: запись — ожидается объект")
            continue
        try:
            step = PreStopStep.model_validate(entry)
        except ValidationError as exc:
            errors.append(_error_text(index, exc))
            continue
        if total + step.timeout_s > PRE_STOP_TOTAL_MAX_S + _TOTAL_EPS:
            errors.append(f"pre_stop[{index}]: timeout_s — сумма шагов больше {PRE_STOP_TOTAL_MAX_S:g} с")
            continue
        total += step.timeout_s
        steps.append(step)
    return steps, errors


def run_pre_stop_step(
    step: PreStopStep,
    *,
    process_exists: Callable[[str], bool],
    ready_event: Callable[[str], Any],
    request_async: Callable[..., Any],
    cancel_source: Callable[[], str | None],
    sender: str,
) -> tuple[str | None, str | None]:
    """Исполнить шаг: ``(источник отмены, None)`` | ``(None, причина сбоя)`` | ``(None, None)`` — выполнен.

    Порядок (ADR-PMM-044): реестр (``process_exists``) → готовность (``ready_event`` → ``Event | None``; ``None`` —
    сигнала нет, действовать сразу) → ``request_async(message, on_response, timeout=...)`` → ожидание ответа. Все
    ожидания — срезами ≤ ``PRE_STOP_SLICE_S`` с проверкой ``cancel_source()``; часы шага — ``time.monotonic()``.
    Зовётся с потока шагов, не с потока приёма: колбэк ``request_async`` приходит на поток приёма и только кладёт
    ответ. Колбэк закрытого шага (опоздавший ответ, конверт подметания) — no-op. Исключения пробрасываются.
    """
    deadline = time.monotonic() + step.timeout_s
    if not process_exists(step.process):
        return None, "процесс не найден"
    ready = ready_event(step.process)
    if ready is not None:
        while not ready.is_set():
            source = cancel_source()
            if source is not None:
                return source, None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, "ребёнок не готов"
            ready.wait(min(PRE_STOP_SLICE_S, remaining))
    source = cancel_source()
    if source is not None:
        return source, None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None, "timeout"

    answered = threading.Event()
    closed = threading.Event()
    box: dict[str, Any] = {}

    def on_response(response: dict) -> None:
        # Поток приёма PM: только положить ответ и взвести событие. Шаг закрыт — no-op (h2).
        if closed.is_set():
            return
        box["response"] = response
        box["thread"] = threading.get_ident()
        answered.set()

    message = build_command_message(step.process, step.command, dict(step.args), sender=sender)
    caller = threading.get_ident()
    try:
        request_async(message, on_response, timeout=remaining)
        while not answered.is_set():
            source = cancel_source()
            if source is not None:
                return source, None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, "timeout"
            answered.wait(min(PRE_STOP_SLICE_S, remaining))
    finally:
        closed.set()
    response = box.get("response")
    if box.get("thread") == caller:
        return None, "ошибка отправки"  # синхронный отказ request_async — колбэк на потоке шага
    if isinstance(response, dict) and response.get("success") is True:
        return None, None
    if isinstance(response, dict) and "type" not in response and response.get("error") == "timeout":
        return None, "timeout"  # конверт подметания слота
    return None, "ошибка ответа"
