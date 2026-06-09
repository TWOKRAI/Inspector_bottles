# -*- coding: utf-8 -*-
"""
FieldMeta — дескриптор метаданных поля для Annotated[T, FieldMeta(...)].

Принцип работы:
    Значение поля хранится напрямую в модели (plain float/int/str/bool).
    Метаданные (описание, ограничения, права доступа, маршрутизация) —
    в аннотации через Annotated. Pydantic v2 сохраняет их в
    model_fields['имя_поля'].metadata и не изменяет схему типа.

Пример использования:

    from typing import Annotated
    from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase

    class DrawRegisters(SchemaBase):
        dp: Annotated[float, FieldMeta(
            "Обратное разрешение аккумулятора",
            info="Ratio of the accumulator resolution to image resolution",
            min=0.1, max=20.0, transfer_k=0.1, round_k=1,
            routing={"channel": "control_draw"},
        )] = 1.4

    r = DrawRegisters()
    r.dp            # → 1.4  (plain float)
    r.model_dump()  # → {"dp": 1.4, ...}
    DrawRegisters.get_field_meta("dp").to_dict()  # → {description, min, max, ...}
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Union

if TYPE_CHECKING:
    from pydantic import GetCoreSchemaHandler
    from pydantic_core import CoreSchema
    from .field_routing import FieldRouting

# Тип для параметра routing: принимаем FieldRouting, dict или None
_RoutingType = Union["FieldRouting", dict, None]

# Нормализация алиасов виджетов: combo→literal, spinbox→int, numeric→float.
# "slider" НЕ нормализуется — это отдельный UI hint (future Phase 2.4 SliderControl).
# "text"/"label" НЕ нормализуются — отдельные семантики (длинная строка / readonly).
_WIDGET_ALIASES: dict[str, str] = {
    "combo": "literal",
    "spinbox": "int",
    "numeric": "float",
}

# Допустимые виджеты UI. Пустая строка = автовыбор фабрикой по Python-типу.
# Алиасы (combo, spinbox, numeric) принимаются в __init__ и нормализуются
# в канонические значения — factory работает только с каноническими.
WidgetType = Literal[
    "",
    "checkbox",
    "slider",
    "spinbox",
    "int",
    "numeric",
    "float",
    "combo",
    "literal",
    "color3",
    "str",
    "text",
    "path",
    "label",
    # Кастомный динамический dropdown (значения вычисляются builder'ом в runtime —
    # напр. список моделей из data/models). Builder регистрируется через
    # CardsFieldFactory.register_type(...) на стороне фронтенда.
    "model_picker",
]


class FieldMeta:
    """
    Метаданные поля регистра / конфига.

    Используется как аннотация-дескриптор: Annotated[T, FieldMeta(...)].
    Pydantic v2 видит его прозрачно — не меняет схему типа поля.
    SchemaMixin читает метаданные через model_fields[name].metadata.

    Параметры:
        description     — краткое описание (для UI-лейбла)
        info            — подробное описание (для UI-подсказки)
        unit            — единица измерения ("px", "мс", "°", ...)
        min / max       — допустимый диапазон для числовых полей
        transfer_k      — шаг UI-слайдера = 1/transfer_k (по умолч. 1.0)
        round_k         — знаков после запятой при round_value()
        routing         — маршрутизация: channel для Router; опционально process_targets
                          для register_update (FieldRouting)
        access_level    — минимальный уровень доступа для изменения
        readonly        — запретить изменение через update_field()
        hidden          — скрыть в UI (can_modify() → False при hidden UI)
        description_i18n / info_i18n — локализованные тексты {"ru":..., "en":...}
        examples        — примеры значений для документации
    """

    __slots__ = (
        "description",
        "description_i18n",
        "info",
        "info_i18n",
        "unit",
        "examples",
        "routing",
        "access_level",
        "readonly",
        "hidden",
        "min",
        "max",
        "transfer_k",
        "round_k",
        "widget",
    )

    def __init__(
        self,
        description: str = "",
        *,
        info: str = "",
        unit: str = "",
        min: float | None = None,
        max: float | None = None,
        # Коэффициент масштабирования для UI-слайдеров (шаг = 1 / transfer_k)
        transfer_k: float = 1.0,
        # Кол-во знаков после запятой при round_value(); None — не округлять
        round_k: int | None = None,
        # Маршрутизация: dict {"channel": "..."} или FieldRouting(channel="...")
        routing: "_RoutingType" = None,
        access_level: int = 0,
        readonly: bool = False,
        hidden: bool = False,
        description_i18n: dict[str, str] | None = None,
        info_i18n: dict[str, str] | None = None,
        examples: list[Any] | None = None,
        # Какой UI-виджет рисовать фабрикой форм.
        # "" (default) — автовыбор по Python-типу.
        # Явные значения: см. WidgetType (Literal); IDE подсказывает варианты.
        widget: WidgetType = "",
    ) -> None:
        self.description = description
        self.info = info
        self.unit = unit
        self.min = min
        self.max = max
        self.transfer_k = transfer_k
        self.round_k = round_k
        # Нормализация routing: FieldRouting → dict, None → {}, dict → as-is
        if routing is None:
            self.routing: dict[str, Any] = {}
        elif hasattr(routing, "to_dict"):
            self.routing = routing.to_dict()
        else:
            self.routing = dict(routing)
        self.access_level = access_level
        self.readonly = readonly
        self.hidden = hidden
        self.description_i18n = description_i18n or {}
        self.info_i18n = info_i18n or {}
        self.examples = examples or []
        # Нормализация алиасов: combo→literal, spinbox→int, numeric→float.
        # Канонические значения и "" проходят без изменений.
        self.widget = _WIDGET_ALIASES.get(widget, widget)  # type: ignore[assignment]

    # =========================================================================
    # Интеграция с Pydantic v2
    # =========================================================================

    def __get_pydantic_core_schema__(
        self,
        source_type: Any,
        handler: "GetCoreSchemaHandler",
    ) -> "CoreSchema":
        """Прозрачный для Pydantic — делегирует схему базовому типу без изменений."""
        return handler(source_type)

    def __repr__(self) -> str:
        parts = [repr(self.description)]
        if self.min is not None:
            parts.append(f"min={self.min}")
        if self.max is not None:
            parts.append(f"max={self.max}")
        if self.unit:
            parts.append(f"unit={self.unit!r}")
        if self.routing:
            parts.append(f"routing={self.routing!r}")
        return f"FieldMeta({', '.join(parts)})"

    # =========================================================================
    # Локализация
    # =========================================================================

    def get_description(self, lang: str | None = None) -> str:
        """Описание поля на нужном языке (fallback → описание по умолчанию)."""
        if lang and self.description_i18n:
            return self.description_i18n.get(lang) or self.description
        return self.description

    def get_info(self, lang: str | None = None) -> str:
        """Подробное описание поля на нужном языке."""
        if lang and self.info_i18n:
            return self.info_i18n.get(lang) or self.info
        return self.info

    # =========================================================================
    # Управление доступом
    # =========================================================================

    def can_modify(self, access_level: int) -> bool:
        """True если поле разрешено к изменению с данным уровнем доступа."""
        return not self.readonly and self.access_level <= access_level

    def is_visible(self, access_level: int) -> bool:
        """True если поле должно быть показано при данном уровне доступа."""
        return not self.hidden and self.access_level <= access_level

    # =========================================================================
    # Валидация и числовые операции
    # =========================================================================

    def validate_value(
        self,
        value: Any,
        access_level: int = 0,
    ) -> tuple[bool, str | None]:
        """
        Проверить значение: права доступа + числовой диапазон [min, max].

        Возвращает (успех, сообщение_об_ошибке | None).
        """
        if not self.can_modify(access_level):
            return False, (f"Недостаточно прав доступа: требуется уровень {self.access_level}, передан {access_level}")
        if isinstance(value, (int, float)):
            if self.min is not None and value < self.min:
                return False, f"Значение {value} меньше минимального {self.min}"
            if self.max is not None and value > self.max:
                return False, f"Значение {value} больше максимального {self.max}"
        return True, None

    def clamp(self, value: float) -> float:
        """Ограничить числовое значение диапазоном [min, max]."""
        if self.min is not None:
            value = max(float(self.min), value)
        if self.max is not None:
            value = min(float(self.max), value)
        return value

    def round_value(self, value: float) -> float:
        """Округлить значение до round_k знаков (если задан)."""
        if self.round_k is not None:
            return round(value, self.round_k)
        return value

    def process_numeric(self, value: float) -> float:
        """Применить clamp и round_value последовательно."""
        return self.round_value(self.clamp(value))

    # =========================================================================
    # Сериализация
    # =========================================================================

    def to_dict(self, lang: str | None = None) -> dict[str, Any]:
        """
        Словарь метаданных для UI или конфигурации.

        При передаче lang — описания локализуются.
        Структура совместима со старым BaseField.to_metadata_dict().
        """
        return {
            "description": self.get_description(lang),
            "info": self.get_info(lang),
            "unit": self.unit,
            "min": self.min,
            "max": self.max,
            "transfer_k": self.transfer_k,
            "round_k": self.round_k,
            "routing": self.routing,
            "access_level": self.access_level,
            "readonly": self.readonly,
            "hidden": self.hidden,
            "examples": self.examples,
            "widget": self.widget,
        }
