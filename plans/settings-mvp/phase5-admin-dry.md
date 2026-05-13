---
Phase: 5
Название: Перенос interface + DRY admin-панелей
Статус: PENDING
Зависит от: Phase 4
---

# Phase 5 — Interface перенос + DRY admin-панелей через BaseAdminPanel

## Цель

1. Перенести `interface_section.py` → `interface/section.py` (без MVP — слишком прост)
2. Рефакторинг admin-панелей на наследование `BaseAdminPanel` (создана в Phase 0)

## Задачи

### Task 5.1 — `interface/section.py`
Перенести, обернуть SectionProtocol. Без MVP (81 LOC, одна кнопка).

### Task 5.2 — `users_panel.py` → BaseAdminPanel
Вынести общий код (header, table setup) в base, оставить CRUD-логику.

### Task 5.3 — `sessions_panel.py` → BaseAdminPanel
Read-only панель. Только `_create_header` + `_create_table`.

### Task 5.4 — `audit_log_panel.py` → BaseAdminPanel
Сложнее: фильтры + пагинация. Table через base, фильтры — свои.

### Task 5.5 — Green-bar admin тестов

## Acceptance Criteria

- [ ] interface/ с SectionProtocol
- [ ] 3 admin панели наследуют BaseAdminPanel
- [ ] Дублирование admin < 5%
- [ ] hasattr → isinstance(panel, SectionProtocol) в tab.py
- [ ] Все тесты green
