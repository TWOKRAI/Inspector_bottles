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

Stability:
    lite-контракт (контракт-тест ``tests/test_pre_stop_contract.py``). Формат текста ошибки
    ``pre_stop[<i>]: <поле> — <причина>`` — часть контракта: тексты не содержат входных значений.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

__all__ = ["PRE_STOP_STEP_MAX_S", "PRE_STOP_TOTAL_MAX_S", "PreStopStep", "parse_pre_stop"]

PRE_STOP_STEP_MAX_S = 60.0
PRE_STOP_TOTAL_MAX_S = 120.0
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
