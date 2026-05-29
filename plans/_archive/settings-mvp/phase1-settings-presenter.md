---
Phase: 1
Название: Top-level SettingsPresenter
Статус: DONE
Коммиты: df3c0e7, e999b60
---

# Phase 1 — SettingsPresenter + View Protocol ✅

## Цель

Создать MVP-каркас для Settings таба: presenter координирует навигацию, view — рендерит Qt.

## Задачи

- [x] **1.1** Создать `settings/view.py` — SettingsView Protocol (7 методов + 7 фабричных)
- [x] **1.2** Создать `settings/presenter.py` — навигация, реестр SectionProtocol, undo/redo, populate()
- [x] **1.3** Извлечь tree helpers → `settings/_nav_tree.py` (build_nav_tree, find_tree_item, select_tree_key + re-export CurrentPageStack)
- [x] **1.4** Рефакторинг `tab.py` → оболочка с Protocol-реализацией, делегация presenter'у
- [x] **1.5** Green-bar: все 22 теста проходят

## Результат

| Файл | LOC | Что |
|------|-----|-----|
| `view.py` | 100 | SettingsView Protocol — 14 методов (навигация + фабрики секций) |
| `presenter.py` | 255 | SettingsPresenter — populate(), навигация, lazy admin, undo/redo |
| `_nav_tree.py` | 99 | build_nav_tree, find_tree_item, select_tree_key |
| `tab.py` | 661 | Оболочка (~200 LOC stays + ~200 LOC Phase 2-3 + ~130 Protocol) |

## Ревью

Итерация 1: CHANGES REQUESTED — tab.py слишком толстый (690 LOC), presenter — хранилище индексов.
Итерация 2: Перенесена координация навигации в presenter (populate, ensure_admin_panel, конфигурация секций).
