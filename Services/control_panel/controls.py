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

# Тип контрола — ВИД виджета (как выглядит/оперируется).
#   select — выпадающий список: options=[{label, value}], эмитит value выбранного
#            пункта (напр. выбор режима робота: cvt|draw|manual|toolchange).
ControlType = Literal["button", "toggle", "slider", "number", "text", "select"]

# Источник/назначение контрола — КУДА идёт действие (Phase 5 дашборд):
#   local   — эмит на свой выходной порт (pipeline-сигнал; дефолт, текущее поведение);
#   param   — правка register-поля ДРУГОЙ ноды (live field-write в target_process);
#   monitor — read-only показ значения поля другой ноды (без правки);
#   action  — триггер команды target_command на другой ноде (как «Рисовать»).
ControlSource = Literal["local", "param", "monitor", "action"]

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
    # select: список пунктов выпадающего списка [{label, value}]. label — подпись
    # для GUI, value — что эмитится при выборе. Пусто для остальных типов.
    options: list[dict[str, Any]] = []

    # Дашборд (Phase 5): контрол может управлять/наблюдать ДРУГУЮ ноду.
    source: ControlSource = "local"
    target_process: str = ""  # имя процесса-ноды (для param/monitor/action)
    target_plugin_index: int = 0  # индекс плагина в процессе (мульти-плагин)
    target_field: str = ""  # имя register-поля (param/monitor)
    target_command: str = ""  # имя команды (action)
    # action со значением: value_arg — имя аргумента команды, куда кладётся значение
    # контрола (пусто = чистый триггер, как кнопка «Рисовать»); command_args —
    # фиксированные аргументы команды (напр. {"device_id": "robot_main"}).
    value_arg: str = ""
    command_args: dict[str, Any] = {}

    @field_validator("id")
    @classmethod
    def _id_not_empty(cls, v: str) -> str:
        if not str(v).strip():
            raise ValueError("ControlSpec.id не может быть пустым")
        return str(v).strip()

    def option_values(self) -> list[Any]:
        """Список value всех пунктов select (для валидации/дефолта)."""
        return [o.get("value") for o in self.options if isinstance(o, dict) and "value" in o]

    def default_value(self) -> Any:
        """Значение по умолчанию для типа (стартовое состояние контрола)."""
        if self.type == "button":
            return self.trigger_value
        if self.type == "toggle":
            return False
        if self.type in _NUMERIC:
            return self.min
        if self.type == "select":
            vals = self.option_values()
            return vals[0] if vals else ""  # первый пункт списка
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
        if self.type == "select":
            vals = self.option_values()
            if raw in vals:
                return raw
            return vals[0] if vals else ""  # вне списка → первый пункт (или пусто)
        return "" if raw is None else str(raw)

    def is_operable(self) -> bool:
        """Можно ли оперировать контролом (monitor — только чтение, операция запрещена)."""
        return self.source != "monitor"

    def action_args(self, value: Any) -> dict[str, Any]:
        """Аргументы команды для action-источника: фикс. command_args + значение под value_arg.

        Пустой value_arg = чистый триггер (значение не передаётся, как кнопка «Рисовать»).
        """
        args: dict[str, Any] = dict(self.command_args or {})
        if self.value_arg:
            args[self.value_arg] = self.coerce(value)
        return args

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
