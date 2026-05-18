# Baseline UI после Phase 2 — Settings tab

**Дата:** 2026-05-18
**Коммит:** `2868dc1` (refactor(framework): TreeNavTabPresenter — Phase 2)
**Снято через:** `mcp__qt-mcp__qt_snapshot` (probe в `multiprocess_prototype/frontend/app.py`)

Используется как эталон при `BaseTreeNavTab`-миграции (Phase 4) и pilot Recipes (Phase 6):
**после миграции структура виджет-дерева Settings должна совпадать с этой** (порядок секций,
имена `objectName`, наличие undo/redo, диф-скролл-мастера).

## Главное окно

```
- MainWindow [1260x797]
  - QWidget
    - AppHeaderWidget "AppHeader" [1260x65]
      - QLabel "BrandLabel" "INNOTECH"
      - QLabel "StatusLabel" "FPS: 0.0 | Latency: 0.0 ms"
      - LoginButton "LoginButton" "Войти"
    - ErrorBannerWidget "ErrorBanner" [hidden]
    - QTabWidget [1260x469] [tabs: *Settings | Recipes | Processes | Services | Plugins | Pipeline | Displays]
      - QStackedWidget "qt_tabwidget_stackedwidget"
      - QTabBar "qt_tabwidget_tabbar"
    - ImagePanelWidget "ImagePanel" [1260x240]
      - DisplaySlot "ImageSlot"
  - QStatusBar [1260x23]
    - QSizeGrip
    - QLabel "DirtyLabel" [hidden]
    - QLabel "FPS: 0.0"
    - QLabel "Latency: 0.0 ms"
    - QLabel "Frames: —"
```

## SettingsTab → DiffScrollTabLayout

Колоночная раскладка с диф-скроллом (см. ADR-126):

```
- SettingsTab [1258x426]
  - DiffScrollTabLayout [1242x410]
    - QScrollArea "DiffScrollActions" [160x352]       ← action-колонка (кнопки секций)
      - QWidget viewport
    - QWidget [160x48]                                 ← статичная зона (undo/redo)
      - QPushButton "DiffScrollUndo" "◀" [disabled]
      - QPushButton "DiffScrollRedo" "▶" [disabled]
    - QGroupBox "DiffScrollNavGroup" [230x400]         ← навигация ("Настройки")
      - QScrollArea "DiffScrollNav" [194x346]
    - QScrollArea "DiffScrollContent" [766x400]        ← content stack
      - QWidget viewport
        - CurrentPageStack [766x792]                  ← фикс sizeHint, см. baseline 0775d01
    - QScrollBar "DiffScrollMaster" [50x400]           ← мастер-скролл (диф)
```

## Nav-tree (содержимое DiffScrollNav)

Дерево навигации Settings таба содержит **5 узлов** (порядок зафиксирован в
`SettingsPresenter._TOP_SECTIONS` + `_ADMIN_CHILDREN`):

1. **Администрация** (раскрываемая ветка, ленивые admin-панели)
   - users / roles / sessions / audit_log
2. **Настройки системы** *(активная по умолчанию — выделена синим)*
3. **Настройка интерфейса**
4. **Оформление**
5. **История**

## Content при старте (system_settings)

`SystemSection` отображает `RegisterView` в cards-режиме с группами:

* **Система** — Таймаут остановки (5.000000 с), Бюджет SHM (512 МБ), Директория логов (logs/prototype_2)
* **Камера** — Тип источника (simulator), Частота кадров (25 fps), Ширина (640 px), Высота (480 px)
* **Обработка**, **Дисплей**, **Хранение** — ниже по диф-скроллу

Action-колонка содержит: **Сбросить** (disabled), **Сохранить** (disabled) — кнопки активируются при dirty.

Встроенный `_toggle` в `RegisterView` **скрыт** (хак `_toggle.hide()` в `SystemSection.__init__:87`).
В Phase 3 будет заменён параметром `RegisterView(show_toggle=False)`.

## objectName-ы (контракт для Phase 6 миграции layout)

При переносе `DiffScrollTabLayout` в `framework/.../tab_layouts/` (Phase 6.1) эти
`objectName` **должны быть сохранены** — на них завязан QSS:

| ObjectName | Назначение |
|------------|-----------|
| `AppHeader`, `BrandLabel`, `StatusLabel`, `LoginButton` | Header bar |
| `ErrorBanner`, `ImagePanel`, `ImageSlot`, `DirtyLabel` | Main shell |
| `DiffScrollActions`, `DiffScrollNav`, `DiffScrollNavGroup`, `DiffScrollContent` | DiffScrollTabLayout колонки |
| `DiffScrollUndo`, `DiffScrollRedo`, `DiffScrollMaster` | Static-зона DiffScrollTabLayout |
| `SettingsTreeNav` | Nav-дерево Settings (закладка на `QTreeWidget`) |

## Snapshot probe

Полный re-snapshot снимается через qt-mcp probe (см. `.claude/mcp/qt-mcp/README.md`):

```powershell
$env:QT_MCP_PROBE = "1"
python multiprocess_prototype/run.py
# в Claude Code:
# mcp__qt-mcp__qt_snapshot(max_depth=4)
# mcp__qt-mcp__qt_find_widget(class_name="SettingsTab")
```

Для сравнения с baseline — снять snapshot после Phase 4 и убедиться, что
структура `SettingsTab → DiffScrollTabLayout → ...` совпадает с разделом
«SettingsTab → DiffScrollTabLayout» выше (с точностью до перенумерации `[ref=wN]`).
