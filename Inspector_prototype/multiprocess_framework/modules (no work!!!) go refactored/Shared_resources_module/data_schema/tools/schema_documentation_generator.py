"""
Генератор документации из схем.

Автоматически генерирует документацию из зарегистрированных Pydantic схем.
Использует паттерн Strategy для расширяемости форматов.
"""

from typing import Dict, Any, Optional, List
from pathlib import Path
from pydantic import BaseModel

from ..registry.schema_registry import SchemaRegistry
from ..core.exceptions import SchemaNotFoundError
from ..core.interfaces import ISchemaDocumentationGenerator, IDocumentationFormatter
from .formatters import (
    MarkdownDocumentationFormatter,
    RstDocumentationFormatter,
    HtmlDocumentationFormatter
)


class SchemaDocumentationGenerator(ISchemaDocumentationGenerator):
    """
    Генератор документации из схем.
    
    Автоматически генерирует документацию в различных форматах
    из зарегистрированных Pydantic схем.
    
    Использует паттерн Strategy для расширяемости - можно легко добавить
    новые форматы через register_formatter().
    
    Example:
        generator = SchemaDocumentationGenerator()
        docs = generator.generate_documentation("LoggerManager", format="markdown")
        
        # Добавление кастомного формата
        class CustomDocFormatter(IDocumentationFormatter):
            format_name = "custom"
            def format_schema(self, schema_name, schema_info, include_examples):
                return f"Custom docs for {schema_name}"
            def format_api_reference(self, schemas, schema_infos):
                return "Custom API ref"
        
        generator.register_formatter(CustomDocFormatter())
        custom_docs = generator.generate_documentation("LoggerManager", format="custom")
    """
    
    def __init__(self, registry: Optional[SchemaRegistry] = None):
        """
        Инициализация генератора документации.
        
        Args:
            registry: SchemaRegistry (если None, используется глобальный экземпляр)
        """
        self.registry = registry or SchemaRegistry.get_instance()
        self._formatters: Dict[str, IDocumentationFormatter] = {}
        
        # Регистрируем стандартные форматеры
        self._register_default_formatters()
    
    def _register_default_formatters(self):
        """Зарегистрировать стандартные форматеры."""
        default_formatters = [
            MarkdownDocumentationFormatter(),
            RstDocumentationFormatter(),
            HtmlDocumentationFormatter()
        ]
        for formatter in default_formatters:
            self.register_formatter(formatter)
    
    def register_formatter(self, formatter: IDocumentationFormatter):
        """
        Зарегистрировать новый форматер документации.
        
        Args:
            formatter: Экземпляр форматера, реализующего IDocumentationFormatter
            
        Example:
            class CustomFormatter(IDocumentationFormatter):
                @property
                def format_name(self) -> str:
                    return "custom"
                
                def format_schema(self, schema_name, schema_info, include_examples):
                    return f"Custom format for {schema_name}"
                
                def format_api_reference(self, schemas, schema_infos):
                    return "Custom API ref"
            
            generator.register_formatter(CustomFormatter())
        """
        if not isinstance(formatter, IDocumentationFormatter):
            raise TypeError(
                f"Форматер должен реализовывать IDocumentationFormatter, "
                f"получен {type(formatter)}"
            )
        self._formatters[formatter.format_name] = formatter
    
    def list_formats(self) -> List[str]:
        """
        Получить список доступных форматов документации.
        
        Returns:
            Список имен форматов
        """
        return list(self._formatters.keys())
    
    def generate_documentation(
        self,
        schema_name: Optional[str] = None,
        format: str = "markdown",
        output_path: Optional[Path] = None,
        include_examples: bool = True,
        include_defaults: bool = True
    ) -> str:
        """
        Сгенерировать документацию для схемы или всех схем.
        
        Args:
            schema_name: Имя схемы (если None, генерируется для всех схем)
            format: Формат документации (должен быть зарегистрирован)
            output_path: Путь для сохранения (если None, возвращается строка)
            include_examples: Включить примеры использования
            include_defaults: Включить дефолтные значения
            
        Returns:
            Строка с документацией
            
        Raises:
            SchemaNotFoundError: Если схема не найдена
            ValueError: Если формат не поддерживается
            
        Example:
            generator = SchemaDocumentationGenerator()
            docs = generator.generate_documentation("LoggerManager", format="markdown")
        """
        if format not in self._formatters:
            available = ", ".join(self.list_formats())
            raise ValueError(
                f"Формат '{format}' не поддерживается. "
                f"Доступные форматы: {available}"
            )
        
        if schema_name:
            docs = self._generate_single_schema_docs(
                schema_name,
                format,
                include_examples,
                include_defaults
            )
        else:
            docs = self._generate_all_schemas_docs(
                format,
                include_examples,
                include_defaults
            )
        
        if output_path:
            output_path.write_text(docs, encoding='utf-8')
        
        return docs
    
    def generate_api_reference(
        self,
        output_path: Optional[Path] = None,
        format: str = "markdown"
    ) -> str:
        """
        Сгенерировать API Reference документацию для всех схем.
        
        Args:
            output_path: Путь для сохранения
            format: Формат документации
            
        Returns:
            Строка с API Reference документацией
            
        Raises:
            ValueError: Если формат не поддерживается
        """
        if format not in self._formatters:
            available = ", ".join(self.list_formats())
            raise ValueError(
                f"Формат '{format}' не поддерживается. "
                f"Доступные форматы: {available}"
            )
        
        schemas = self.registry.list_schemas()
        schema_infos = {}
        
        for schema_name in schemas:
            try:
                schema = self.registry.get_schema(schema_name)
                if schema:
                    schema_infos[schema_name] = self._extract_schema_info(schema, include_defaults=True)
            except Exception:
                pass
        
        formatter = self._formatters[format]
        docs = formatter.format_api_reference(schemas, schema_infos)
        
        if output_path:
            output_path.write_text(docs, encoding='utf-8')
        
        return docs
    
    def _generate_single_schema_docs(
        self,
        schema_name: str,
        format: str,
        include_examples: bool,
        include_defaults: bool
    ) -> str:
        """Сгенерировать документацию для одной схемы."""
        schema = self.registry.get_schema(schema_name)
        if schema is None:
            available = self.registry.list_schemas()
            raise SchemaNotFoundError(schema_name, available)
        
        schema_info = self._extract_schema_info(schema, include_defaults)
        formatter = self._formatters[format]
        
        return formatter.format_schema(schema_name, schema_info, include_examples)
    
    def _generate_all_schemas_docs(
        self,
        format: str,
        include_examples: bool,
        include_defaults: bool
    ) -> str:
        """Сгенерировать документацию для всех схем."""
        schemas = self.registry.list_schemas()
        schema_infos = {}
        
        for schema_name in schemas:
            try:
                schema = self.registry.get_schema(schema_name)
                if schema:
                    schema_infos[schema_name] = self._extract_schema_info(schema, include_defaults)
            except Exception:
                pass
        
        formatter = self._formatters[format]
        
        # Для некоторых форматов используем специальный метод API Reference
        if hasattr(formatter, 'format_api_reference'):
            return formatter.format_api_reference(schemas, schema_infos)
        else:
            # Иначе генерируем для каждой схемы отдельно
            docs_parts = []
            for schema_name in schemas:
                if schema_name in schema_infos:
                    doc = formatter.format_schema(
                        schema_name,
                        schema_infos[schema_name],
                        include_examples
                    )
                    docs_parts.append(doc)
            
            return "\n\n---\n\n".join(docs_parts)
    
    def _extract_schema_info(
        self,
        schema: type[BaseModel],
        include_defaults: bool
    ) -> Dict[str, Any]:
        """Извлечь информацию о схеме."""
        model_fields = schema.model_fields if hasattr(schema, 'model_fields') else {}
        fields_info = []
        
        for field_name, field_info in model_fields.items():
            field_data = {
                "name": field_name,
                "type": str(field_info.annotation) if hasattr(field_info, 'annotation') else "Any",
                "required": field_info.is_required() if hasattr(field_info, 'is_required') else True
            }
            
            if include_defaults and hasattr(field_info, 'default'):
                default = field_info.default
                if default is not None and default != ...:
                    field_data["default"] = str(default)
            
            if hasattr(field_info, 'description'):
                description = field_info.description
                if description:
                    field_data["description"] = description
            
            fields_info.append(field_data)
        
        return {
            "name": schema.__name__,
            "fields": fields_info,
            "docstring": schema.__doc__ or ""
        }
