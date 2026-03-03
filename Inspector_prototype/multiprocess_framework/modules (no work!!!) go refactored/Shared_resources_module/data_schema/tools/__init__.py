"""
Инструменты для работы со схемами.

Содержит визуализацию схем и генерацию документации.
"""

from .schema_visualizer import SchemaVisualizer
from .schema_documentation_generator import SchemaDocumentationGenerator
from .formatters import (
    IVisualizationFormatter,
    IDocumentationFormatter,
    TextVisualizationFormatter,
    JsonVisualizationFormatter,
    HtmlVisualizationFormatter,
    MermaidVisualizationFormatter,
    MarkdownDocumentationFormatter,
    RstDocumentationFormatter,
    HtmlDocumentationFormatter
)

__all__ = [
    'SchemaVisualizer',
    'SchemaDocumentationGenerator',
    # Интерфейсы для расширения
    'IVisualizationFormatter',
    'IDocumentationFormatter',
    # Стандартные форматеры
    'TextVisualizationFormatter',
    'JsonVisualizationFormatter',
    'HtmlVisualizationFormatter',
    'MermaidVisualizationFormatter',
    'MarkdownDocumentationFormatter',
    'RstDocumentationFormatter',
    'HtmlDocumentationFormatter',
]

