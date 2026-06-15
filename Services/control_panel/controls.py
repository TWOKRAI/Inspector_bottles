"""controls.py — ControlSpec: описание одного контрола пульта (core, без Qt/framework).

Контрол = элемент управления (кнопка/тумблер/слайдер/поле), привязанный к одному
выходному порту ноды ``control_panel``. При операции (нажатие/сдвиг/ввод) плагин
эмитит текущее значение контрола на его порт → в pipeline.

Dict-at-Boundary: на границе компонентов контролы — ``list[dict]``; ControlSpec —
Pydantic-модель внутри процесса (парсинг/валидация/коэрция значения по типу).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, field_validator

# Типы контролов v1.
ControlType = Literal["button", "toggle", "slider", "number", "text"]

_NUMERIC = {"slider", "number"}


class ControlSpec(BaseModel):
    """Спецификация одного контрола пульта.

    Attributes:
        id:    Уникальный идентификатор контрола (стабильный ключ).
        type:  Тип контрола (button|toggle|slider|number|text).
        label: Человекочитаемая подпись (для GUI).
        port:  Выходной порт ноды, на который эмитится значение (out_1..out_N).
        value: Текущее значение (хранится между эмитами; для button — не используется).
        min/max/step: Диапазон для slider/number.
        trigger_value: Что эмитит кнопка при нажатии (для type="button").
    """

    id: str
    type: ControlType = "button"
    label: str = ""
    port: str = "out_1"
    value: Any = None
    min: float = 0.0
    max: float = 100.0
    step: float = 1.0
    trigger_value: Any = True

    @field_validator("id")
    @classmethod
    def _id_not_empty(cls, v: str) -> str:
        if not str(v).strip():
            raise ValueError("ControlSpec.id не может быть пустым")
        return str(v).strip()

    def default_value(self) -> Any:
        """Значение по умолчанию для типа (стартовое состояние контрола)."""
        if self.type == "button":
            return self.trigger_value
        if self.type == "toggle":
            return False
        if self.type in _NUMERIC:
            return self.min
        return ""  # text

    def coerce(self, raw: Any) -> Any:
        """Привести произвольное значение к типу контрола (с clamp для чисел).

        button → trigger_value (нажатие — это импульс, payload фиксирован);
        toggle → bool; slider/number → float в [min, max]; text → str.
        """
        if self.type == "button":
            return self.trigger_value
        if self.type == "toggle":
            return bool(raw)
        if self.type in _NUMERIC:
            try:
                num = float(raw)
            except (TypeError, ValueError):
                num = self.min
            return _clamp(num, self.min, self.max)
        return "" if raw is None else str(raw)

    def to_dict(self) -> dict[str, Any]:
        """Сериализация на границу (Dict-at-Boundary)."""
        return self.model_dump()


def _clamp(value: float, low: float, high: float) -> float:
    """Ограничить число диапазоном [low, high] (с защитой от перевёрнутого диапазона)."""
    if high < low:
        low, high = high, low
    return max(low, min(high, value))


def parse_controls(raw: list[dict] | None) -> list[ControlSpec]:
    """Распарсить ``list[dict]`` контролов в ControlSpec (битые записи пропускаются).

    Дубли id отбрасываются (побеждает первый) — id должен быть уникальным.
    """
    specs: list[ControlSpec] = []
    seen: set[str] = set()
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        try:
            spec = ControlSpec(**item)
        except Exception:  # nosec B112 — битую запись контрола намеренно пропускаем
            continue
        if spec.id in seen:
            continue
        seen.add(spec.id)
        # value по умолчанию, если не задано
        if spec.value is None:
            spec.value = spec.default_value()
        specs.append(spec)
    return specs


def controls_to_dicts(specs: list[ControlSpec]) -> list[dict[str, Any]]:
    """Список ControlSpec → ``list[dict]`` (для state/команд)."""
    return [s.to_dict() for s in specs]


__all__ = ["ControlSpec", "ControlType", "parse_controls", "controls_to_dicts"]
