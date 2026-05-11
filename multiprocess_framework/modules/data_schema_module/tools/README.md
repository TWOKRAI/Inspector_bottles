# tools/ — Визуализация и документация схем

Рендер схемы в text/JSON/HTML/Mermaid + генерация пользовательской документации (markdown/rst/html).

`tools/` — **application layer**, зависит только от `core/` + `registry/`. **Опциональный для runtime** — используется в основном для генерации help-страниц, embedding'а в IDE, аудита схем.

## Публичный API

```python
from multiprocess_framework.modules.data_schema_module.tools import (
    # Визуализаторы
    SchemaVisualizer,

    # Generators
    SchemaDocumentationGenerator,

    # Контракты для расширения
    IVisualizationFormatter,
    IDocumentationFormatter,

    # Стандартные форматеры (готовые реализации)
    TextVisualizationFormatter,
    JsonVisualizationFormatter,
    HtmlVisualizationFormatter,
    MermaidVisualizationFormatter,
    MarkdownDocumentationFormatter,
    RstDocumentationFormatter,
    HtmlDocumentationFormatter,
)

# Также можно через extensions (тонкий re-export, ADR-DS-004)
from multiprocess_framework.modules.data_schema_module.extensions.tools import SchemaVisualizer
```

Корневой фасад `data_schema_module/__init__.py` НЕ реэкспортирует `tools/` — это **opt-in** компонент (по аналогии с `storage/`, `versioning/`).

## Паттерн использования

```python
from multiprocess_framework.modules.data_schema_module.tools import SchemaVisualizer

viz = SchemaVisualizer()
mermaid_diagram = viz.visualize_schema("processing", format="mermaid")
print(mermaid_diagram)

# Расширение: свой форматер
class XmlVisualizationFormatter(IVisualizationFormatter):
    @property
    def format_name(self) -> str: return "xml"
    def format(self, schema_name, schema_info) -> str:
        ...
viz.register_formatter(XmlVisualizationFormatter())
```

## Состав

| Файл | Содержимое |
|------|------------|
| `schema_visualizer.py` | `SchemaVisualizer` — точка входа визуализации |
| `schema_documentation_generator.py` | `SchemaDocumentationGenerator` |
| `formatters.py` | Готовые форматеры (Text/Json/Html/Mermaid + Markdown/Rst/Html) |
| `interfaces.py` | `IVisualizationFormatter`, `IDocumentationFormatter`, `ISchemaVisualizer`, `ISchemaDocumentationGenerator` (ADR-DS-005) |
| `examples/excel_formatter.py` | Пример своего форматера (Excel) |

## Применяемые паттерны

- **Strategy** — `IVisualizationFormatter`/`IDocumentationFormatter`. `SchemaVisualizer.register_formatter(...)` принимает любую реализацию.
- **Facade** — `SchemaVisualizer.visualize_schema(name, format=...)` — единая точка входа поверх стратегий.

См. [STATUS.md](STATUS.md), [interfaces.py](interfaces.py), [docs/TOOLS_GUIDE.md](../docs/TOOLS_GUIDE.md).
