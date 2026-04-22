# processing_tab — вкладка «Обработка»

Тонкая оболочка: **`ProcessingTabWidget`** встраивает **`ProcessingPanelWidget`** или placeholder.

## Схема

```mermaid
flowchart LR
    PT[ProcessingTabWidget] -->|rm| PP[ProcessingPanelWidget]
    PT -->|нет rm| PH[placeholder Обработка]
```

## Файлы

| Файл | Содержимое |
|------|------------|
| `widget.py` | `ProcessingTabWidget` |
| `schemas.py` | реэкспорт `ProcessingTabUiConfig` из `processing_panel_widget` |

См. [`../../processing_panel_widget/README.md`](../../processing_panel_widget/README.md).
