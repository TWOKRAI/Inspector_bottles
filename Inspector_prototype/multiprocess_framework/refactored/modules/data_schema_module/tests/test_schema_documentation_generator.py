"""
Unit-тесты для SchemaDocumentationGenerator (tools/schema_documentation_generator.py).

Сценарии: генерация документации в markdown, rst, html; с примерами и без; для одной схемы и для всех;
generate_api_reference; несуществующая схема / неподдерживаемый формат → исключения.
"""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from ..registry.schema_registry import SchemaManager
from ..tools.schema_documentation_generator import SchemaDocumentationGenerator
from ..tools.formatters import IDocumentationFormatter
from ..models.base import BaseManagerModel
from ..models.types import ComponentType
from ..core.exceptions import SchemaNotFoundError


# Тестовая модель
class _TestDocModel(BaseManagerModel):
    """Тестовая модель для генератора документации."""
    
    field1: str = "default_value"
    field2: int = 42
    optional_field: str | None = None


@pytest.fixture(autouse=True)
def reset_registry():
    """Сбрасываем реестр перед каждым тестом."""
    registry = SchemaManager.get_instance()
    registry.clear()
    registry.register("TestDocModel", _TestDocModel)
    yield
    registry.clear()


def test_generate_documentation_markdown():
    """Тест генерации документации в Markdown формате."""
    generator = SchemaDocumentationGenerator()
    result = generator.generate_documentation("TestDocModel", format="markdown")
    
    assert "# TestDocModel" in result
    assert "## Поля" in result
    assert "field1" in result
    assert "field2" in result
    assert "| Поле |" in result


def test_generate_documentation_rst():
    """Тест генерации документации в RST формате."""
    generator = SchemaDocumentationGenerator()
    result = generator.generate_documentation("TestDocModel", format="rst")
    
    assert "TestDocModel" in result
    assert "field1" in result
    assert "field2" in result


def test_generate_documentation_html():
    """Тест генерации документации в HTML формате."""
    generator = SchemaDocumentationGenerator()
    result = generator.generate_documentation("TestDocModel", format="html")
    
    assert "<!DOCTYPE html>" in result
    assert "<html>" in result
    assert "TestDocModel" in result
    assert "<table>" in result


def test_generate_documentation_with_examples():
    """Тест генерации документации с примерами."""
    generator = SchemaDocumentationGenerator()
    result = generator.generate_documentation(
        "TestDocModel",
        format="markdown",
        include_examples=True
    )
    
    assert "## Пример использования" in result
    assert "```python" in result


def test_generate_documentation_without_examples():
    """Тест генерации документации без примеров."""
    generator = SchemaDocumentationGenerator()
    result = generator.generate_documentation(
        "TestDocModel",
        format="markdown",
        include_examples=False
    )
    
    assert "## Пример использования" not in result


def test_generate_documentation_all_schemas():
    """Тест генерации документации для всех схем."""
    generator = SchemaDocumentationGenerator()
    result = generator.generate_documentation(format="markdown")
    
    assert "TestDocModel" in result


def test_generate_documentation_missing_schema():
    """Тест генерации документации для несуществующей схемы."""
    generator = SchemaDocumentationGenerator()
    
    with pytest.raises(SchemaNotFoundError):
        generator.generate_documentation("NonExistentSchema", format="markdown")


def test_generate_documentation_invalid_format():
    """Тест генерации документации с неподдерживаемым форматом."""
    generator = SchemaDocumentationGenerator()
    
    with pytest.raises(ValueError) as exc_info:
        generator.generate_documentation("TestDocModel", format="invalid_format")
    
    assert "не поддерживается" in str(exc_info.value)


def test_generate_api_reference():
    """Тест генерации API Reference."""
    generator = SchemaDocumentationGenerator()
    result = generator.generate_api_reference(format="markdown")
    
    assert "# API Reference" in result
    assert "TestDocModel" in result
    assert "## Содержание" in result


def test_generate_api_reference_html():
    """Тест генерации API Reference в HTML формате."""
    generator = SchemaDocumentationGenerator()
    result = generator.generate_api_reference(format="html")
    
    assert "<!DOCTYPE html>" in result
    assert "<html>" in result
    assert "API Reference" in result


def test_save_documentation():
    """Тест сохранения документации в файл."""
    generator = SchemaDocumentationGenerator()
    
    with TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "docs.md"
        result = generator.generate_documentation(
            "TestDocModel",
            format="markdown",
            output_path=output_path
        )
        
        assert output_path.exists()
        content = output_path.read_text(encoding='utf-8')
        assert "TestDocModel" in content
        assert result == content


def test_register_formatter():
    """Тест регистрации кастомного форматера."""
    generator = SchemaDocumentationGenerator()
    
    class CustomFormatter(IDocumentationFormatter):
        @property
        def format_name(self) -> str:
            return "custom"
        
        def format_schema(self, schema_name, schema_info, include_examples):
            return f"Custom docs for {schema_name}"
        
        def format_api_reference(self, schemas, schema_infos):
            return "Custom API ref"
    
    generator.register_formatter(CustomFormatter())
    
    assert "custom" in generator.list_formats()
    result = generator.generate_documentation("TestDocModel", format="custom")
    assert result == "Custom docs for TestDocModel"


def test_register_formatter_invalid():
    """Тест регистрации невалидного форматера."""
    generator = SchemaDocumentationGenerator()
    
    class InvalidFormatter:
        pass
    
    with pytest.raises(TypeError):
        generator.register_formatter(InvalidFormatter())


def test_list_formats():
    """Тест получения списка форматов."""
    generator = SchemaDocumentationGenerator()
    formats = generator.list_formats()
    
    assert "markdown" in formats
    assert "rst" in formats
    assert "html" in formats
    assert len(formats) >= 3


def test_extract_schema_info():
    """Тест извлечения информации о схеме."""
    generator = SchemaDocumentationGenerator()
    schema = SchemaManager.get_instance().get_schema("TestDocModel")
    
    schema_info = generator._extract_schema_info(schema, include_defaults=True)
    
    assert schema_info["name"] == "_TestDocModel"  # Имя класса
    assert len(schema_info["fields"]) > 0
    assert any(f["name"] == "field1" for f in schema_info["fields"])


def test_generate_api_reference_invalid_format():
    """Тест генерации API Reference с неподдерживаемым форматом."""
    generator = SchemaDocumentationGenerator()
    
    with pytest.raises(ValueError) as exc_info:
        generator.generate_api_reference(format="invalid_format")
    
    assert "не поддерживается" in str(exc_info.value)

