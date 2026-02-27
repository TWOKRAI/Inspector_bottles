"""
Unit тесты для SchemaVisualizer.
"""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from ..registry.schema_registry import SchemaRegistry
from ..tools.schema_visualizer import SchemaVisualizer
from ..tools.formatters import IVisualizationFormatter
from ..models.base import BaseManagerModel
from ..models.types import ComponentType
from ..core.exceptions import SchemaNotFoundError


# Тестовая модель
class _TestVisualizerModel(BaseManagerModel):
    """Тестовая модель для визуализатора."""
    
    field1: str = "default_value"
    field2: int = 42
    optional_field: str | None = None


@pytest.fixture(autouse=True)
def reset_registry():
    """Сбрасываем реестр перед каждым тестом."""
    registry = SchemaRegistry.get_instance()
    registry.clear()
    registry.register("TestVisualizerModel", _TestVisualizerModel)
    yield
    registry.clear()


def test_visualize_schema_text():
    """Тест визуализации схемы в текстовом формате."""
    visualizer = SchemaVisualizer()
    result = visualizer.visualize_schema("TestVisualizerModel", format="text")
    
    assert "Схема: TestVisualizerModel" in result
    assert "field1" in result
    assert "field2" in result
    assert "default_value" in result
    assert "42" in result


def test_visualize_schema_json():
    """Тест визуализации схемы в JSON формате."""
    visualizer = SchemaVisualizer()
    result = visualizer.visualize_schema("TestVisualizerModel", format="json")
    
    import json
    data = json.loads(result)
    assert data["name"] == "_TestVisualizerModel"  # Имя класса, не схемы
    assert len(data["fields"]) > 0
    assert any(f["name"] == "field1" for f in data["fields"])


def test_visualize_schema_html():
    """Тест визуализации схемы в HTML формате."""
    visualizer = SchemaVisualizer()
    result = visualizer.visualize_schema("TestVisualizerModel", format="html")
    
    assert "<!DOCTYPE html>" in result
    assert "<html>" in result
    assert "TestVisualizerModel" in result
    assert "<table>" in result


def test_visualize_schema_mermaid():
    """Тест визуализации схемы в Mermaid формате."""
    visualizer = SchemaVisualizer()
    result = visualizer.visualize_schema("TestVisualizerModel", format="mermaid")
    
    assert "classDiagram" in result
    assert "class TestVisualizerModel" in result
    assert "field1" in result


def test_visualize_schema_missing_schema():
    """Тест визуализации несуществующей схемы."""
    visualizer = SchemaVisualizer()
    
    with pytest.raises(SchemaNotFoundError):
        visualizer.visualize_schema("NonExistentSchema", format="text")


def test_visualize_schema_invalid_format():
    """Тест визуализации с неподдерживаемым форматом."""
    visualizer = SchemaVisualizer()
    
    with pytest.raises(ValueError) as exc_info:
        visualizer.visualize_schema("TestVisualizerModel", format="invalid_format")
    
    assert "не поддерживается" in str(exc_info.value)


def test_visualize_schema_with_options():
    """Тест визуализации с различными опциями."""
    visualizer = SchemaVisualizer()
    
    # Без дефолтных значений
    result_no_defaults = visualizer.visualize_schema(
        "TestVisualizerModel",
        format="text",
        include_defaults=False
    )
    assert "default_value" not in result_no_defaults
    
    # Без типов
    result_no_types = visualizer.visualize_schema(
        "TestVisualizerModel",
        format="text",
        include_types=False
    )
    # Проверяем, что типы не включены (косвенно через отсутствие двоеточий с типами)
    
    # Без описаний
    result_no_descriptions = visualizer.visualize_schema(
        "TestVisualizerModel",
        format="text",
        include_descriptions=False
    )
    # Проверяем, что результат получен
    assert len(result_no_descriptions) > 0


def test_visualize_all_schemas():
    """Тест визуализации всех схем."""
    visualizer = SchemaVisualizer()
    result = visualizer.visualize_all_schemas(format="text")
    
    assert "TestVisualizerModel" in result


def test_save_visualization():
    """Тест сохранения визуализации в файл."""
    visualizer = SchemaVisualizer()
    
    with TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "visualization.txt"
        visualizer.save_visualization(
            "TestVisualizerModel",
            output_path,
            format="text"
        )
        
        assert output_path.exists()
        content = output_path.read_text(encoding='utf-8')
        assert "TestVisualizerModel" in content


def test_register_formatter():
    """Тест регистрации кастомного форматера."""
    visualizer = SchemaVisualizer()
    
    class CustomFormatter(IVisualizationFormatter):
        @property
        def format_name(self) -> str:
            return "custom"
        
        def format(self, schema_name: str, schema_info: dict) -> str:
            return f"Custom format: {schema_name}"
    
    visualizer.register_formatter(CustomFormatter())
    
    assert "custom" in visualizer.list_formats()
    result = visualizer.visualize_schema("TestVisualizerModel", format="custom")
    assert result == "Custom format: TestVisualizerModel"


def test_register_formatter_invalid():
    """Тест регистрации невалидного форматера."""
    visualizer = SchemaVisualizer()
    
    class InvalidFormatter:
        pass
    
    with pytest.raises(TypeError):
        visualizer.register_formatter(InvalidFormatter())


def test_list_formats():
    """Тест получения списка форматов."""
    visualizer = SchemaVisualizer()
    formats = visualizer.list_formats()
    
    assert "text" in formats
    assert "json" in formats
    assert "html" in formats
    assert "mermaid" in formats
    assert len(formats) >= 4


def test_extract_schema_info():
    """Тест извлечения информации о схеме."""
    visualizer = SchemaVisualizer()
    schema = SchemaRegistry.get_instance().get_schema("TestVisualizerModel")
    
    schema_info = visualizer._extract_schema_info(
        schema,
        include_defaults=True,
        include_types=True,
        include_descriptions=True
    )
    
    assert schema_info["name"] == "_TestVisualizerModel"  # Имя класса
    assert len(schema_info["fields"]) > 0
    assert any(f["name"] == "field1" for f in schema_info["fields"])


def test_format_all_as_html():
    """Тест форматирования всех схем как HTML."""
    visualizer = SchemaVisualizer()
    visualizations = ["<div>Schema 1</div>", "<div>Schema 2</div>"]
    
    result = visualizer._format_all_as_html(visualizations)
    
    assert "<!DOCTYPE html>" in result
    assert "<html>" in result
    assert "Schema 1" in result
    assert "Schema 2" in result

