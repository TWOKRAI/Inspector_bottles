---
paths:
  - "multiprocess_framework/modules/frontend_module/**"
  - "multiprocess_prototype/registers/**"
---

# Правила GUI (PySide6)

## Виджеты
- v3 сгруппированы по доменам: `chrome/`, `sources/`, `recipes/`, `processing/`, `settings/`, `pipeline/`, `tabs_setting/`, `base/`
- Реорганизация: `docs/refactors/2026-04_widgets_reorg.md`

## Qt-паттерны (КРИТИЧНО)
- **blockSignals** перед программной правкой виджетов — иначе рекурсия сигналов
- **setFlags** с осторожностью — может вызвать рекурсию (ItemChanged → setFlags → ItemChanged)
- **EditTriggers** — отключать на деревьях/списках если не нужно inline-редактирование
- Новые табы — **полный MVP** (presenter + view Protocol)

## Dict at Boundary для GUI
- Виджеты работают **только с dict**, никогда с live SchemaBase
- Данные: dict → виджет → dict (round-trip)

## Register routing
- FieldRouting **без IPC-канала** = зависание GUI
- Всегда проверять что канал зарегистрирован перед send_message

## Tab order
- Settings первым → Recipes → функциональные табы (не Settings последним)

## Тестирование GUI — pytest-qt + qt-mcp (НЕ «GUI не тестируем»)

Старое правило «GUI widgets — не тестируем» **устарело**. На проекте стоят оба инструмента — они дополняют друг друга, не конкурируют.

### pytest-qt — для unit/integration (CI, gate, green-bar)

- Установлен: `pytest-qt>=4.4`, `qt_api = "pyside6"` (`pyproject.toml`)
- Фикстура `qtbot` — создаёт изолированный `QApplication` в каждом тесте
- Используется для:
  - Поведенческие тесты виджетов (клик → ожидаемое изменение состояния)
  - Сигналы (`qtbot.waitSignal(widget.signal, timeout=2000)`)
  - dirty-флаги, save/reload, валидация
  - Файлы YAML/конфиги — через monkeypatch путей
- Где живут: рядом с виджетом — `widgets/tabs/<name>/tests/test_<name>.py`
- Эталон: `multiprocess_prototype/frontend/widgets/tabs/settings/tests/test_settings_tab.py`
- Запуск: `python -m pytest <path> -v`

### qt-mcp — для агентского smoke / baseline / диагностики

- MCP-сервер ([README](../.claude/mcp/qt-mcp/README.md), [SETUP](../.claude/mcp/qt-mcp/SETUP_GUIDE.md))
- Probe врезан в `multiprocess_prototype/frontend/app.py:run_gui()` под `QT_MCP_PROBE=1`
- Подключается к **живому** прототипу через `localhost:9142` — видит реальные QObject, IPC, multiprocess state
- Используется для:
  - **Baseline UI** перед рефакторингом → `qt_snapshot(max_depth=4)` → сохранить как `plans/<slug>/baseline-*.md`
  - **Diff после миграции** — `qt_snapshot` против baseline, структура должна совпасть с точностью до `[ref=wN]`
  - **Smoke живой системы** — `qt_screenshot(full_window=True)` показывает агенту/пользователю текущее UI
  - **Диагностика «не виден / не работает»** — `qt_find_widget` + `qt_widget_details`
- Запуск (POSIX bash, не PowerShell в Claude Code):
  ```
  QT_MCP_PROBE=1 python multiprocess_prototype/run.py
  ```
  Подождать ≥12 сек после запуска, потом дёргать `qt_list_windows`.

### Что чем тестировать — таблица

| Сценарий | Инструмент |
|----------|-----------|
| «Клик кнопки меняет состояние» | `pytest-qt` (qtbot) |
| «Сигнал `settings_saved` эмитится при save()» | `pytest-qt` (`qtbot.waitSignal`) |
| «Виджет dirty при изменении» | `pytest-qt` |
| «После рефакторинга widget tree идентичен» | **qt-mcp** (`qt_snapshot` diff против baseline) |
| «objectName-ы для QSS сохранены» | **qt-mcp** (`qt_find_widget` по `object_name`) |
| «Почему виджет не виден / disabled?» | **qt-mcp** (`qt_widget_details`) |
| «Покажи как сейчас выглядит UI» | **qt-mcp** (`qt_screenshot`) |
| Multiprocess IPC + GUI вместе | **qt-mcp** (живой `gui` процесс) |
| Изолированный unit-тест бизнес-логики | `pytest-qt` |

### КРИТИЧНО: НЕ ставить `QT_MCP_PROBE=1` при запуске pytest

Probe и pytest-qt конфликтуют по порту 9142 — на втором `qtbot` фикстуре probe упадёт. Env-флаг только для ручного/agent smoke, не для CI/gate.

### Green-bar контракт (для каждого PR с GUI-изменениями)

1. `pytest-qt` тесты затронутой вкладки/виджета — **зелёные** (обязательно).
2. При рефакторинге UI-структуры — `qt-mcp` baseline до миграции **сохранён** в `plans/<slug>/baseline-*.md`. После миграции — `qt_snapshot` совпадает.
3. Хаки доступа к приватным полям (`_toggle.hide()`, `_content_scroll.setWidgetResizable()` снаружи) — устранены через публичный API.

## Семантический поиск и архитектурные метрики

GUI-код плотно завязан на регистры, presenter'ы, виджеты — слепой Grep легко
теряет callers. Используй два MCP-инструмента (ортогональные):

| Вопрос | Tool |
|--------|------|
| «Где используется `RegisterView`?» / «Кто вызывает `populate()`?» | `mcp__qex__search_code` (qex-first для рефакторинга) |
| «Какие виджеты импортируют `tabs/`?» | `mcp__qex__search_code` (тематически) |
| «`frontend_module` не импортирует `multiprocess_prototype`?» | `mcp__sentrux__check_rules` через `/sentrux-rules` |
| «После переноса DiffScrollTabLayout во framework — циклов нет?» | `mcp__sentrux__dsm` через `/sentrux-dsm` |
| «Phase 2 не ухудшил health?» | `session_start` в начале фазы → `session_end` в конце |
| «Какие виджеты без тестов?» | `mcp__sentrux__test_gaps` через `/sentrux-gaps` |

qex — «*где*», sentrux — «*насколько здорово*». Не дублируют. На GUI-задачах
оба критичны: qex для безопасного переименования / расширения API,
sentrux для контроля слоёв (`framework ← Services ← Plugins ← prototype`).
