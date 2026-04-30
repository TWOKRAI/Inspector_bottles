# `frontend_module` — Архитектурные решения

PySide6-фреймворк виджетов с привязкой к `data_schema_module` (`SchemaBase` + `FieldMeta` + `FieldRouting`). Каждое решение зафиксировано как **ADR** в глобальном `multiprocess_framework/DECISIONS.md`.

> **Этот файл — индекс**, а не дубль. Каждая запись ниже ссылается на полный текст в глобальном `DECISIONS.md`.

---

## Реестр

| ADR | Тема | Глобальный текст |
|-----|------|------------------|
| ADR-033 | `frontend_module` и `shared_registers` — фундамент UI-фреймворка | `../../DECISIONS.md#adr-033` |
| ADR-034 | `FrontendManager` — единая точка входа (`BaseManager`) | `../../DECISIONS.md#adr-034` |
| ADR-035 | `FrontendRegistersBridge` — связь frontend с backend через регистры | `../../DECISIONS.md#adr-035` |
| ADR-036 | Конфигурация frontend — hot-reload без перезапуска | `../../DECISIONS.md#adr-036` |
| ADR-037 | Рефакторинг `frontend_module` и прототипа (2026-03-18) | `../../DECISIONS.md#adr-037` |
| ADR-042 | `ProcessModule` как `IRouterLike` для `FrontendManager` | `../../DECISIONS.md#adr-042` |
| ADR-043 | Унифицированные конфиги frontend на `SchemaBase` + `FieldMeta` | `../../DECISIONS.md#adr-043` |
| ADR-044 | Реорганизация `components/` и паттерн «конфиг рядом с виджетом» | `../../DECISIONS.md#adr-044` |
| ADR-053 | Прототип — один `GuiProcess`, импорты регистров, `FrontendManager` runtime | `../../DECISIONS.md#adr-053` |
| ADR-084 | `FrontendAppContext` — явный контекст вкладок без слияния слоёв | `../../DECISIONS.md#adr-084` |
| ADR-090 | `frontend/coordinators`, границы виджет / Presenter / `managers` | `../../DECISIONS.md#adr-090` |
| ADR-095 | `StructuredTwoLevelTreeWidget` — группа → строки | `../../DECISIONS.md#adr-095` |
| ADR-097 | Touch-клавиатура — проброс из `FrontendConfig`, делегат по колонкам | `../../DECISIONS.md#adr-097` |

---

## Краткая суть (без дублирования полного текста)

**1. Конфиг рядом с виджетом (ADR-044).** Каждый виджет в `components/<name>/` имеет свой `config.py` с `SchemaBase`-наследником. Конфиг не лежит отдельно в `configs/` — это нарушает принцип «модуль = одна папка».

**2. Виджет ↔ регистр (ADR-035).** Виджет связывается с полем регистра через `FieldRouting.channel` + `FieldMeta`. `FrontendRegistersBridge` подписывается на изменения регистра и обновляет UI; обратно — через `set_field_value()` в `RegistersManager`.

**3. `FrontendManager` — `BaseManager` (ADR-034).** Точка входа в подсистему фронтенда из процесса. Управляет окнами, виджетами, привязкой к регистрам.

**4. Координаторы (ADR-090).** `frontend/coordinators/` — слой между виджетом, Presenter и managers. Виджет не знает про Router/IPC — координатор делегирует действия в backend.

**5. Hot-reload конфигов (ADR-036).** Изменение `FrontendConfig` через `ConfigManager.subscribe()` пересобирает виджеты без перезапуска процесса.

---

## Где искать детали

- Архитектура виджетов — `README.md` модуля.
- Cookbook — `WIDGET_COOKBOOK.md` модуля (примеры компонентов).
- Полный текст ADR — глобальный `multiprocess_framework/DECISIONS.md`.
- Дорожная карта — `multiprocess_framework/docs/FRONTEND_COMMAND_LAUNCHER_ROADMAP.md`.
