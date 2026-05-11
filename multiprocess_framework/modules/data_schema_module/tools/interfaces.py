# -*- coding: utf-8 -*-
"""
Контракты `tools/` — визуализация и документация схем.

- `IVisualizationFormatter` / `ISchemaVisualizer` — рендер схемы в text/html/mermaid.
- `IDocumentationFormatter` / `ISchemaDocumentationGenerator` — генерация
  пользовательской документации (markdown/rst/html) из схем.

Реализации: `tools/schema_visualizer.py`, `tools/schema_documentation_generator.py`.

Корневой [data_schema_module/interfaces.py](../interfaces.py) реэкспортирует
эти контракты для обратной совместимости (ADR-DS-005).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class IVisualizationFormatter(ABC):
    """Интерфейс стратегии визуализации схем."""

    @abstractmethod
    def format(self, schema_name: str, schema_info: Dict[str, Any]) -> str:
        """Форматировать информацию о схеме."""
        ...

    @property
    @abstractmethod
    def format_name(self) -> str:
        """Имя формата (например, 'text', 'html', 'mermaid')."""
        ...


class IDocumentationFormatter(ABC):
    """Интерфейс стратегии форматирования документации схем."""

    @abstractmethod
    def format_schema(
        self,
        schema_name: str,
        schema_info: Dict[str, Any],
        include_examples: bool = True,
    ) -> str:
        """Форматировать документацию для одной схемы."""
        ...

    @abstractmethod
    def format_api_reference(
        self,
        schemas: List[str],
        schema_infos: Dict[str, Dict[str, Any]],
    ) -> str:
        """Форматировать API Reference для всех схем."""
        ...

    @property
    @abstractmethod
    def format_name(self) -> str:
        """Имя формата (например, 'markdown', 'rst', 'html')."""
        ...


class ISchemaVisualizer(ABC):
    """Интерфейс для визуализатора схем."""

    @abstractmethod
    def visualize_schema(
        self,
        schema_name: str,
        format: str = "text",
        include_defaults: bool = True,
        include_types: bool = True,
        include_descriptions: bool = True,
    ) -> str:
        """Визуализировать схему в указанном формате."""
        ...

    @abstractmethod
    def register_formatter(self, formatter: IVisualizationFormatter) -> None:
        """Зарегистрировать новый форматер визуализации."""
        ...

    @abstractmethod
    def list_formats(self) -> List[str]:
        """Получить список доступных форматов."""
        ...


class ISchemaDocumentationGenerator(ABC):
    """Интерфейс для генератора документации схем."""

    @abstractmethod
    def generate_documentation(
        self,
        schema_name: Optional[str] = None,
        format: str = "markdown",
        include_examples: bool = True,
        include_defaults: bool = True,
    ) -> str:
        """Сгенерировать документацию для схемы или всех схем."""
        ...

    @abstractmethod
    def register_formatter(self, formatter: IDocumentationFormatter) -> None:
        """Зарегистрировать новый форматер документации."""
        ...

    @abstractmethod
    def list_formats(self) -> List[str]:
        """Получить список доступных форматов."""
        ...


__all__ = [
    "IVisualizationFormatter",
    "IDocumentationFormatter",
    "ISchemaVisualizer",
    "ISchemaDocumentationGenerator",
]
