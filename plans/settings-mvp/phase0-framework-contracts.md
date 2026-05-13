---
Phase: 0
Название: Framework-контракты + подготовка
Статус: DONE
Коммиты: b9282c9, 4d7ce1b
---

# Phase 0 — Framework-контракты + подготовка ✅

## Цель

Создать framework-контракты (SectionProtocol, CurrentPageStack) и базовый класс для admin-панелей.

## Задачи

- [x] **0.1** Создать `frontend_module/widgets/tabs/section_protocol.py` — SectionProtocol (runtime_checkable Protocol для секций с tree-навигацией)
- [x] **0.2** Перенести `_CurrentPageStack` → `frontend_module/widgets/tabs/current_page_stack.py` (переименован в CurrentPageStack)
- [x] **0.3** Создать `administration/_base_panel.py` — BaseAdminPanel (в prototype)
- [x] **0.4** Прогнать все тесты — green baseline (272 passed)

## Результат

| Файл | Что |
|------|-----|
| `framework/.../section_protocol.py` | SectionProtocol — key, title, widget, action_buttons, on_activated/deactivated |
| `framework/.../current_page_stack.py` | CurrentPageStack — QStackedWidget с sizeHint только текущей страницы |
| `prototype/.../administration/_base_panel.py` | BaseAdminPanel — _create_header, _create_table, action_buttons |
| `prototype/.../settings/tab.py` | Заменён локальный _CurrentPageStack на import из framework |

## Ревью

Итерация 1: CHANGES REQUESTED → исправлены docstring, тип action_buttons, импорт через публичный __init__.
Итерация 2: APPROVED.
