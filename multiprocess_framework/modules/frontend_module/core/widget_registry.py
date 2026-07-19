# -*- coding: utf-8 -*-
"""
LEGACY Gen-1 (frozen 2026-07-18) — WidgetRegistry — реестр типов виджетов и
фабрика для их создания. 0 внешних потребителей (см. frontend_module/STATUS.md).

Позволяет регистрировать фабрики по типу (slider, checkbox, ...) и создавать
виджеты по дескриптору или dict. Гибкая расширяемость: новый тип = register().
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Union

from multiprocess_framework.modules.frontend_module.interfaces import IRegistersManager, IWidgetFactory

WidgetFactoryFn = Callable[
    [str, Dict[str, Any], Optional[IRegistersManager], Optional[Any]],
    Optional[Any],
]


class WidgetRegistry(IWidgetFactory):
    """
    Реестр фабрик виджетов по типу.

    Пример:
        registry = WidgetRegistry()
        registry.register("slider", create_slider_widget)
        registry.register("checkbox", create_checkbox_widget)
        widget = registry.create("slider", {"register_name": "draw", "field_name": "dp"}, rm, parent)
    """

    def __init__(self) -> None:
        self._factories: Dict[str, WidgetFactoryFn] = {}

    def register(self, widget_type: str, factory: Union[WidgetFactoryFn, IWidgetFactory]) -> None:
        """Зарегистрировать фабрику для типа виджета."""
        if hasattr(factory, "create"):
            self._factories[widget_type] = factory.create  # type: ignore
        else:
            self._factories[widget_type] = factory  # type: ignore

    def get_factory(self, widget_type: str) -> Optional[WidgetFactoryFn]:
        """Получить фабрику по типу."""
        return self._factories.get(widget_type)

    def list_types(self) -> List[str]:
        """Список зарегистрированных типов."""
        return list(self._factories.keys())

    def create(
        self,
        widget_type: str,
        descriptor: Union[Dict[str, Any], Any],
        registers_manager: Optional[IRegistersManager] = None,
        parent: Optional[Any] = None,
    ) -> Optional[Any]:
        """
        Создать виджет по типу и дескриптору.

        Args:
            widget_type: Тип виджета (slider, checkbox, ...)
            descriptor: Параметры — dict или WidgetDescriptor
            registers_manager: Менеджер регистров
            parent: Родительский виджет

        Returns:
            Созданный виджет или None
        """
        factory = self._factories.get(widget_type)
        if not factory:
            return None
        if hasattr(descriptor, "to_factory_kwargs"):
            kwargs = descriptor.to_factory_kwargs()
        elif isinstance(descriptor, dict):
            kwargs = dict(descriptor)
        else:
            kwargs = {}
        return factory(widget_type, kwargs, registers_manager, parent)
