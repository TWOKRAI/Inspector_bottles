---
Phase: 3
Название: Извлечение System Settings
Статус: DONE
Зависит от: Phase 2 (✅)
Коммит: 706f5f1
---

# Phase 3 — System Settings секция с MVP

## Цель

Извлечь из `tab.py` всю логику system settings (RegisterView, save/reload, field sync, validation) в отдельную секцию `system/` с MVP. Это **главное сокращение** tab.py (~130 LOC → отдельная секция).

## Задачи

### Task 3.1 — `system/view.py` (~30 LOC)
**Level:** Middle
**Goal:** SystemSettingsView Protocol для presenter

```python
class SystemSettingsView(TabViewProtocol, Protocol):
    def set_editor_value(self, key: str, value: object) -> None: ...
    def get_editor_values(self) -> dict[str, object]: ...
    def set_dirty(self, dirty: bool) -> None: ...
    def show_validation_error(self, key: str, message: str) -> None: ...
    def clear_validation_errors(self) -> None: ...
```

**Files:** `multiprocess_prototype/frontend/widgets/tabs/settings/system/view.py`

### Task 3.2 — `system/presenter.py` (~180 LOC)
**Level:** Middle+
**Goal:** Presenter с load/save/validate/dirty/field sync

Извлечь из tab.py:
- `save()` → `presenter.save()`
- `reload()` → `presenter.reload()`
- `_init_editor_values()`, `_sync_editors_to_cfg()`
- `_on_field_changed()`, `_on_field_changed_action_bus()`
- `_set_dirty()`, `_show_validation_errors()`, `_clear_validation_errors()`
- `_on_bus_undo_redo_sync()` — тоже сюда (field sync для RegisterView)

Presenter наследует `TabPresenterBase[SystemSettingsView, None]`, НЕ импортирует Qt.

**Files:** `multiprocess_prototype/frontend/widgets/tabs/settings/system/presenter.py`

### Task 3.3 — `system/section.py` (~150 LOC)
**Level:** Middle+
**Goal:** QWidget-обёртка RegisterView, implements SectionProtocol + SystemSettingsView

Section:
- Создаёт RegisterView (field_infos, category_titles)
- Реализует SystemSettingsView Protocol
- Реализует SectionProtocol (key="system_settings", title="Настройки системы")
- Владеет кнопками: ViewModeToggle, Сбросить, Сохранить
- `action_buttons()` возвращает [toggle, reset, save]

**Files:** `multiprocess_prototype/frontend/widgets/tabs/settings/system/section.py`

### Task 3.4 — Обновить tab.py и presenter
**Level:** Middle
**Goal:** Удалить вынесенный код, делегировать SystemSection

Из tab.py удалить:
- `save()`, `reload()` — делегировать system section
- `_init_editor_values()`, `_sync_editors_to_cfg()`
- `_on_field_changed()`, `_on_field_changed_action_bus()`
- `_set_dirty()`, `_show_validation_errors()`, `_clear_validation_errors()`
- `_on_bus_undo_redo_sync()`
- `self._register_view`, `self._view` (RegisterView) — перенести в SystemSection
- `self._cfg`, `self._prefs` — перенести в SystemSection
- `self._dirty` — перенести в SystemSection

**ВАЖНО**: Сигналы `settings_saved` и `dirty_changed` остаются на SettingsTab (публичный API). SystemSection эмитит их через callback/signal.

tab.py после Phase 3: ~350-400 LOC → ~200-250 LOC.

**Files:** `tab.py`, `presenter.py`

### Task 3.5 — Тесты
**Level:** Middle
**Goal:** pure-Python тесты для SystemPresenter + green-bar

- `test_save_validates_and_persists` — mock view, проверить save flow
- `test_reload_resets_editors` — проверить reload flow
- `test_field_change_marks_dirty` — проверить dirty flag
- `test_validation_error_shows_on_view` — проверить error flow
- Green-bar: все существующие тесты (settings + admin + history)

**Files:** `multiprocess_prototype/frontend/widgets/tabs/settings/system/tests/test_system_presenter.py`

## Acceptance Criteria

- [x] `system/view.py` — Protocol, без Qt
- [x] `system/presenter.py` — save/reload/validate/dirty, без Qt, наследует TabPresenterBase
- [x] `system/section.py` — QWidget, implements SectionProtocol + SystemSettingsView
- [x] tab.py ≤ 400 LOC (412 строк — приемлемо, 261 реального кода)
- [x] Сигналы settings_saved/dirty_changed работают через SystemSection → SettingsTab
- [x] `_on_bus_undo_redo_sync` перенесён в system/presenter
- [x] Все тесты green (settings + admin + history + system)

## Out of Scope

- НЕ трогать appearance (Phase 4)
- НЕ трогать admin панели (Phase 5)
- НЕ менять yaml_io.py
