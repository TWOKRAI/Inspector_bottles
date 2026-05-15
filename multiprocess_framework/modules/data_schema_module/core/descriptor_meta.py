# -*- coding: utf-8 -*-
"""
RegisterDescriptor + DescriptorSchemaMeta — Django-style declarative-API для регистров.

Позволяет вместо длинного

    enabled: Annotated[bool, FieldMeta("Enabled", info="...", widget="checkbox")] = True

писать декларативно:

    enabled = CheckboxRegister(name="Enabled", default=True, info="...")

где `CheckboxRegister` — подкласс `RegisterDescriptor` (живёт в
`components/checkbox/registers.py`). Под капотом `DescriptorSchemaMeta`
проходит по namespace класса и превращает дескрипторы в стандартные
Pydantic-аннотации `Annotated[python_type, FieldMeta(...)]`.

Использование (плагин)::

    from multiprocess_framework.modules.data_schema_module import (
        SchemaBase, DescriptorSchemaMeta, register_schema,
    )
    from multiprocess_framework.modules.frontend_module.components.registers import (
        CheckboxRegister,
    )

    @register_schema("MyRegistersV1")
    class MyRegisters(SchemaBase, metaclass=DescriptorSchemaMeta):
        enable_timer = CheckboxRegister(
            name="Включение таймера",
            default=True,
            info="Если включено — worker логирует tick",
        )

    r = MyRegisters()
    r.enable_timer    # → True (обычный bool, не дескриптор)
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic._internal._model_construction import ModelMetaclass

from .field_meta import FieldMeta


class RegisterDescriptor:
    """Базовый дескриптор поля регистра (Django-style).

    Подклассы переопределяют:
        python_type — Python-тип поля (bool, int, float, ...)
        widget      — какой UI-виджет рисовать ("checkbox", "spinbox", "slider", ...)

    И могут расширять `__init__` своими параметрами (например `min`/`max` у SliderRegister).
    """

    # Подклассы переопределяют:
    python_type: type = object
    widget: str = ""

    def __init__(
        self,
        name: str = "",
        *,
        default: Any = None,
        info: str = "",
        routing: dict | str | None = None,
        access_level: int = 0,
        readonly: bool = False,
        hidden: bool = False,
        unit: str = "",
        min: float | int | None = None,
        max: float | int | None = None,
        transfer_k: float = 1.0,
        round_k: int | None = None,
        examples: list | None = None,
    ) -> None:
        self.name = name
        self.default = default
        self.info = info
        self.routing = routing
        self.access_level = access_level
        self.readonly = readonly
        self.hidden = hidden
        self.unit = unit
        self.min = min
        self.max = max
        self.transfer_k = transfer_k
        self.round_k = round_k
        self.examples = examples or []

    def to_annotated(self) -> Any:
        """Превратить дескриптор в Annotated[python_type, FieldMeta(...)] для Pydantic.

        Вызывается из DescriptorSchemaMeta.__new__ при сборке класса.
        """
        return Annotated[
            self.python_type,
            FieldMeta(
                self.name,
                info=self.info,
                routing=self.routing
                if isinstance(self.routing, dict)
                else ({"channel": self.routing} if self.routing else None),
                access_level=self.access_level,
                readonly=self.readonly,
                hidden=self.hidden,
                unit=self.unit,
                min=self.min,
                max=self.max,
                transfer_k=self.transfer_k,
                round_k=self.round_k,
                examples=self.examples or None,
                widget=self.widget,
            ),
        ]


class DescriptorSchemaMeta(ModelMetaclass):
    """Metaclass для SchemaBase-наследников с Django-style declarative полями.

    Видит атрибуты-инстансы `RegisterDescriptor` в namespace класса и до
    Pydantic-валидации превращает их в:
        - `__annotations__[attr_name] = descriptor.to_annotated()`
        - `namespace[attr_name] = descriptor.default`

    Стандартные `Annotated[T, FieldMeta(...)]` поля сосуществуют с
    дескрипторами в одном классе — metaclass их не трогает.
    """

    def __new__(mcs, name: str, bases: tuple, namespace: dict, **kwargs):
        annotations = dict(namespace.get("__annotations__", {}))

        for attr_name, attr_value in list(namespace.items()):
            if isinstance(attr_value, RegisterDescriptor):
                # Преобразуем дескриптор в Pydantic-аннотацию + default value
                annotations[attr_name] = attr_value.to_annotated()
                namespace[attr_name] = attr_value.default

        namespace["__annotations__"] = annotations
        return super().__new__(mcs, name, bases, namespace, **kwargs)
