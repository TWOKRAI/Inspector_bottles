# tools/ — Статус

**Статус:** STABLE (visualization), STABLE (doc generation).

## Компоненты

| Компонент | Файл | Тесты | Статус |
|-----------|------|-------|--------|
| `SchemaVisualizer` | schema_visualizer.py | ✅ test_schema_visualizer.py (14 тестов) | Готов |
| `SchemaDocumentationGenerator` | schema_documentation_generator.py | ✅ test_schema_documentation_generator.py (16) | Готов |
| `TextVisualizationFormatter` | formatters.py | ✅ | Готов |
| `JsonVisualizationFormatter` | formatters.py | ✅ | Готов |
| `HtmlVisualizationFormatter` | formatters.py | ✅ | Готов |
| `MermaidVisualizationFormatter` | formatters.py | ✅ | Готов |
| `MarkdownDocumentationFormatter` | formatters.py | ✅ | Готов |
| `RstDocumentationFormatter` | formatters.py | ✅ | Готов |
| `HtmlDocumentationFormatter` | formatters.py | ✅ | Готов |
| `IVisualizationFormatter`/etc. | interfaces.py | ✅ | Готов (ADR-DS-005) |

## Внешние зависимости

| Зависимость | Тип | Назначение |
|-------------|-----|------------|
| `core/` | внутренний | базовые типы |
| `registry/` | внутренний | `SchemaManager` для list_schemas |
| `core/exceptions` | внутренний | `SchemaNotFoundError` |

## Потребители

- 3 импорта `SchemaVisualizer` (через `extensions/tools`)
- Используется в **`multiprocess_prototype`** для help-страниц и debug-view (см. потенциал carve-out, 2026-05-11_data_schema_polish.md Этап 7).

## Размер

- 5 файлов, **1216 LOC** — на границе кандидатуры на carve-out в `data_schema_tools_module`.

## Известные TODO

- [ ] Mermaid: поддержка диаграммы взаимодействия (не только структуры).
- [ ] HTML с CSS-стилями (сейчас базовый).
- [ ] OpenAPI/GraphQL экспорт.
