---
Phase: 2
Название: Извлечение History
Статус: DONE
Коммит: 484f451
---

# Phase 2 — History секция с MVP ✅

## Цель

Извлечь ~130 LOC history-кода из tab.py в отдельную секцию `history/` с MVP.

## Задачи

- [x] **2.1** Создать `history/view.py` — HistoryView Protocol (5 методов: set_table_data, set_save/clear_enabled, scroll_to_bottom, get_save_path)
- [x] **2.2** Создать `history/presenter.py` — HistoryPresenter(TabPresenterBase): refresh, clear, save_to_csv
- [x] **2.3** Создать `history/section.py` — HistorySection(QWidget) implements SectionProtocol + HistoryView
- [x] **2.4** Зарегистрировать HistorySection через SettingsPresenter (add_history_page создаёт section)
- [x] **2.5** Тесты: 11 pure-Python тестов в `test_history_presenter.py` (100 passed total)

## Результат

| Файл | LOC | Что |
|------|-----|-----|
| `history/view.py` | ~30 | HistoryView Protocol, без Qt |
| `history/presenter.py` | ~120 | bus queries, CSV export, без Qt |
| `history/section.py` | ~120 | QWidget + SectionProtocol + HistoryView |
| `history/tests/test_history_presenter.py` | ~80 | 11 pure-Python тестов |

Из tab.py удалены: `_build_history_widget`, `_refresh_history`, `_on_history_clear`, `_on_history_save`, атрибуты `_history_table`, `_btn_save_history`, `_btn_clear_history`.
`_on_bus_undo_redo_sync` оставлен в tab.py (field sync для RegisterView, не history).
