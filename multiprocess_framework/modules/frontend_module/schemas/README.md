# schemas — схемы виджетов и окон

Структуры данных (Pydantic v2) для описания UI: виджеты, окна, привязка реестров.

## Ключевые символы

- `WidgetDescriptor` — описание виджета (тип, позиция, стиль, вложенность).
- `widget_descriptor_from_dict()` — парсинг WidgetDescriptor из словаря.
- `WindowConfig` — конфигурация главного окна (размер, позиция, вкладки).
- `RegisterBinding` — привязка реестра к UI-элементу (какой регистр, какое поле, триггер обновления).
- `RegisterFieldMeta`, `ResolvedMeta` — метаданные полей реестра для привязки UI.

## Stability

partial

→ Корневой README: `../../README.md`
