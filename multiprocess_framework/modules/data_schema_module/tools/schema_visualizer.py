"""
Визуализатор схем данных.

Предоставляет методы для визуализации структуры Pydantic схем в различных форматах.
Использует паттерн Strategy для расширяемости форматов.
"""

from typing import Dict, Any, Optional, List, Type
from pathlib import Path
from pydantic import BaseModel

from ..registry.schema_registry import SchemaManager
from ..core.exceptions import SchemaNotFoundError
from .interfaces import ISchemaVisualizer, IVisualizationFormatter
from .formatters import (
    TextVisualizationFormatter,
    JsonVisualizationFormatter,
    HtmlVisualizationFormatter,
    MermaidVisualizationFormatter
)


class SchemaVisualizer(ISchemaVisualizer):
    """
    Визуализатор схем данных.
    
    Предоставляет методы для визуализации структуры Pydantic схем
    в различных форматах (текст, JSON, HTML, Mermaid диаграммы).
    
    Использует паттерн Strategy для расширяемости - можно легко добавить
    новые форматы через register_formatter().
    
    Example:
        visualizer = SchemaVisualizer()
        text = visualizer.visualize_schema("LoggerManager", format="text")
        
        # Добавление кастомного формата
        class ExcelFormatter(IVisualizationFormatter):
            format_name = "excel"
            def format(self, schema_name, schema_info):
                # Реализация экспорта в Excel
                pass
        
        visualizer.register_formatter(ExcelFormatter())
        excel_data = visualizer.visualize_schema("LoggerManager", format="excel")
    """
    
    def __init__(self, registry: Optional[SchemaManager] = None):
        """
        Инициализация визуализатора.
        
        Args:
            registry: SchemaManager (если None, используется глобальный экземпляр)
        """
        self.registry = registry or SchemaManager.get_instance()
        self._formatters: Dict[str, IVisualizationFormatter] = {}
        
        # Регистрируем стандартные форматеры
        self._register_default_formatters()
    
    def _register_default_formatters(self):
        """Зарегистрировать стандартные форматеры."""
        default_formatters = [
            TextVisualizationFormatter(),
            JsonVisualizationFormatter(),
            HtmlVisualizationFormatter(),
            MermaidVisualizationFormatter()
        ]
        for formatter in default_formatters:
            self.register_formatter(formatter)
    
    def register_formatter(self, formatter: IVisualizationFormatter):
        """
        Зарегистрировать новый форматер визуализации.
        
        Args:
            formatter: Экземпляр форматера, реализующего IVisualizationFormatter
            
        Example:
            class CustomFormatter(IVisualizationFormatter):
                @property
                def format_name(self) -> str:
                    return "custom"
                
                def format(self, schema_name: str, schema_info: Dict[str, Any]) -> str:
                    return f"Custom format for {schema_name}"
            
            visualizer.register_formatter(CustomFormatter())
        """
        if not isinstance(formatter, IVisualizationFormatter):
            raise TypeError(
                f"Форматер должен реализовывать IVisualizationFormatter, "
                f"получен {type(formatter)}"
            )
        self._formatters[formatter.format_name] = formatter
    
    def list_formats(self) -> List[str]:
        """
        Получить список доступных форматов визуализации.
        
        Returns:
            Список имен форматов
        """
        return list(self._formatters.keys())
    
    def visualize_schema(
        self,
        schema_name: str,
        format: str = "text",
        include_defaults: bool = True,
        include_types: bool = True,
        include_descriptions: bool = True
    ) -> str:
        """
        Визуализировать схему в указанном формате.
        
        Args:
            schema_name: Имя схемы
            format: Формат визуализации (должен быть зарегистрирован)
            include_defaults: Включить дефолтные значения
            include_types: Включить типы полей
            include_descriptions: Включить описания полей
            
        Returns:
            Строка с визуализацией схемы
            
        Raises:
            SchemaNotFoundError: Если схема не найдена
            ValueError: Если формат не поддерживается
            
        Example:
            visualizer = SchemaVisualizer()
            text = visualizer.visualize_schema("LoggerManager", format="text")
            html = visualizer.visualize_schema("LoggerManager", format="html")
        """
        schema = self.registry.get_schema(schema_name)
        if schema is None:
            available = self.registry.list_schemas()
            raise SchemaNotFoundError(schema_name, available)
        
        schema_info = self._extract_schema_info(
            schema,
            include_defaults,
            include_types,
            include_descriptions
        )
        
        if format not in self._formatters:
            available = ", ".join(self.list_formats())
            raise ValueError(
                f"Формат '{format}' не поддерживается. "
                f"Доступные форматы: {available}"
            )
        
        formatter = self._formatters[format]
        return formatter.format(schema_name, schema_info)
    
    def visualize_all_schemas(
        self,
        format: str = "text",
        include_defaults: bool = True
    ) -> str:
        """
        Визуализировать все зарегистрированные схемы.
        
        Args:
            format: Формат визуализации
            include_defaults: Включить дефолтные значения
            
        Returns:
            Строка с визуализацией всех схем
        """
        schemas = self.registry.list_schemas()
        results = []
        
        for schema_name in schemas:
            try:
                visualization = self.visualize_schema(
                    schema_name,
                    format=format,
                    include_defaults=include_defaults
                )
                results.append(visualization)
            except Exception as e:
                results.append(f"Ошибка визуализации схемы {schema_name}: {e}")
        
        if format == "text":
            return "\n\n" + "="*80 + "\n\n".join(results)
        elif format == "html":
            return self._format_all_as_html(results)
        else:
            return "\n\n".join(results)
    
    def save_visualization(
        self,
        schema_name: str,
        output_path: Path,
        format: str = "text",
        **kwargs
    ):
        """
        Сохранить визуализацию схемы в файл.
        
        Args:
            schema_name: Имя схемы
            output_path: Путь к файлу для сохранения
            format: Формат визуализации
            **kwargs: Дополнительные параметры для visualize_schema
        """
        visualization = self.visualize_schema(schema_name, format=format, **kwargs)
        output_path.write_text(visualization, encoding='utf-8')
    
    def _extract_schema_info(
        self,
        schema: Type[BaseModel],
        include_defaults: bool,
        include_types: bool,
        include_descriptions: bool
    ) -> Dict[str, Any]:
        """Извлечь информацию о схеме."""
        model_fields = schema.model_fields if hasattr(schema, 'model_fields') else {}
        fields_info = []
        
        for field_name, field_info in model_fields.items():
            field_data = {
                "name": field_name,
                "required": field_info.is_required() if hasattr(field_info, 'is_required') else True
            }
            
            if include_types:
                field_data["type"] = str(field_info.annotation) if hasattr(field_info, 'annotation') else "Any"
            
            if include_defaults and hasattr(field_info, 'default'):
                default = field_info.default
                if default is not None and default != ...:
                    field_data["default"] = str(default)
            
            if include_descriptions and hasattr(field_info, 'description'):
                description = field_info.description
                if description:
                    field_data["description"] = description
            
            fields_info.append(field_data)
        
        return {
            "name": schema.__name__,
            "fields": fields_info,
            "docstring": schema.__doc__ or ""
        }
    
    def _format_all_as_html(self, visualizations: List[str]) -> str:
        """Форматировать все схемы как HTML."""
        html = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            "<title>Все схемы</title>",
            "<style>",
            "body { font-family: Arial, sans-serif; margin: 20px; }",
            "h1 { color: #333; }",
            ".schema { margin-bottom: 40px; border: 1px solid #ddd; padding: 20px; }",
            "</style>",
            "</head>",
            "<body>",
            "<h1>Все зарегистрированные схемы</h1>"
        ]
        
        for viz in visualizations:
            html.append(f"<div class='schema'>{viz}</div>")
        
        html.extend(["</body>", "</html>"])
        return "\n".join(html)
