# Phase 2 — Config-driven discovery + PluginManager

> **Master plan**: [plan.md](plan.md)
> **Branch**: `feat/discovery-config-paths`
> **Дней**: 2-3
> **Зависимости**: Phase 0
> **Refs trailer**: `Refs: plans/prototype-skeleton-2026-05/phase-2-discovery-config-paths.md, plans/prototype-skeleton-2026-05/plan.md`

## Цель

Убрать хардкод `PLUGINS_DIR = PROJECT_ROOT / "Plugins"` из `main.py`. Пути живут в `backend/config/system.yaml` (правильный путь!) и редактируются из GUI через перенесённый из backup `PluginManager`.

## Реюз готового

- `PluginRegistry.discover(*dirs)` — уже принимает varargs.
- `PluginManager` (Phase 0, из backup) — auto-discovery + hot-reload.
- `ConfigManager` + `config.subscribe()` для реактивности.

## Файлы

- `multiprocess_prototype/backend/config/system.yaml` — добавить:
  ```yaml
  discovery:
    plugin_paths: ["Plugins"]
    service_paths: ["Services"]
  ```
- `multiprocess_prototype/backend/config/user_overrides.yaml` (опц., gitignored) — для GUI-правок путей.
- `multiprocess_prototype/main.py` и `frontend/app.py` — заменить хардкод на `config.discovery.plugin_paths`.
- Подвкладка «Пути» в `frontend/widgets/tabs/plugins/`:
  - Список путей + кнопки «Добавить папку», «Удалить», «Рескан».
  - На «Рескан» → `PluginManager.rescan()` → событие `state.plugins.catalog_updated`.
- Каталог в PluginManagerTab подписан на это событие.

## Acceptance

- Добавление пути через GUI → плагины из новой папки видны в каталоге без рестарта.
- Настройки персистятся.
- 5-7 unit-тестов на PluginManager + integration на подвкладку.

---

## Задачи

### Порядок выполнения и параллелизм

```
Task 2.1 ──────────────────────┐
                               ├──► Task 2.3 ──► Task 2.4 ──► Task 2.5 ──► Task 2.7
Task 2.2 ──────────────────────┘                              (зависит 2.4)
                                                Task 2.6 ─────────────────► Task 2.7
                                                (зависит 2.4)
```

- **2.1 и 2.2** — независимы, можно запускать параллельно (один агент на каждую).
- **2.3** — ждёт 2.1 (нужна `DiscoverySection` в схеме) и 2.2 (нужен `load_system_config` с override).
- **2.4** — ждёт 2.3 (config-driven paths уже в `sys_config`, bootstrap читает их).
- **2.5 и 2.6** — ждут 2.4 (нужен `AppContext.plugin_manager()`); можно параллельно между собой.
- **2.7** — ждёт все предыдущие; запускается последней.

> **Напоминание** (из memory): максимум 2 агента параллельно без git-worktree, иначе merge-конфликты. Безопасная параллель: запустить 2.1 + 2.2 одновременно, остальное последовательно.

---

### Task 2.1 — DiscoverySection: Pydantic-схема для секции discovery

**Level:** Junior (Haiku, normal)
**Assignee:** developer
**Goal:** Добавить `DiscoverySection` в `schemas.py` и секцию `discovery` в `system.yaml`, чтобы пути к плагинам читались из конфига, а не были захардкожены.

**Context:** Сейчас `PLUGINS_DIR = PROJECT_ROOT / "Plugins"` — константа в `main.py`, и `_PLUGINS_DIR = Path(...) / "Plugins"` — в `app.py`. Обе ссылаются на одну папку, но не связаны с конфигом. После этой задачи `PluginRegistry.discover()` в обоих местах будет вызываться со значениями из `sys_config.discovery.plugin_paths`.

**Files:**
- `multiprocess_prototype/backend/config/schemas.py` — добавить `DiscoverySection`, добавить поле `discovery: DiscoverySection` в `SystemConfig`
- `multiprocess_prototype/backend/config/system.yaml` — добавить секцию `discovery`

**Steps:**

1. В `schemas.py` после класса `StorageDefaults` добавить класс `DiscoverySection(SchemaBase)` с полями:
   - `plugin_paths: list[str] = ["Plugins"]` — список относительных или абсолютных путей; аннотировать через `FieldMeta` с описанием «Директории для поиска плагинов»
   - `service_paths: list[str] = ["Services"]` — аналогично для сервисов (задел для Phase 3, но не подключать к логике сейчас)
   - `auto_discover: bool = True` — FieldMeta «Автообнаружение при старте»

2. В классе `SystemConfig` добавить поле `discovery: DiscoverySection = DiscoverySection()` (после `storage`).

3. В `system.yaml` добавить секцию:
   ```yaml
   # --- Автообнаружение плагинов и сервисов ---
   discovery:
     plugin_paths:
       - "Plugins"
     service_paths:
       - "Services"
     auto_discover: true
   ```

**Acceptance criteria:**
- [x] `load_system_config(CONFIG_PATH).discovery.plugin_paths == ["Plugins"]` — проверяется в тестах Task 2.7 (6eb7212)
- [x] `DiscoverySection()` (без аргументов) не бросает исключений (6eb7212)
- [x] `SystemConfig.model_validate({"discovery": {"plugin_paths": ["/abs/path", "rel/path"]}})` валидируется без ошибок (6eb7212)
- [x] `SystemConfig.model_validate({})` (пустой dict) даёт `discovery.plugin_paths == ["Plugins"]` (6eb7212)

**Out of scope:** Не подключать `service_paths` к логике discovery (это Phase 3). Не трогать `main.py` / `app.py` / AppContext — это Task 2.3 и 2.4.

**Edge cases:** Пустой список `plugin_paths: []` должен валидироваться без ошибок (пустой discovery — допустимое состояние).

**Dependencies:** нет

**Module contract:** public-api-change (добавляет поле в `SystemConfig`)

---

### Task 2.2 — user_overrides.yaml: deep-merge поверх system.yaml

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Расширить `load_system_config()` так, чтобы она автоматически подхватывала `user_overrides.yaml` рядом с `system.yaml` и deep-merge'ила его поверх базового конфига, сохраняя приоритет override-значений.

**Context:** Пути плагинов должны редактироваться через GUI (Task 2.5) и персистироваться. Писать изменения прямо в `system.yaml` (git-tracked) нежелательно — пользовательские пути попадут в коммиты. Решение: отдельный `user_overrides.yaml` рядом с `system.yaml`, который в `.gitignore`. `load_system_config` сама находит его и мержит — вызывающий код ничего не меняет.

**Files:**
- `multiprocess_prototype/backend/config/schemas.py` — расширить `load_system_config()`
- `multiprocess_prototype/backend/config/user_overrides.yaml` — создать пустой шаблон-заглушку с комментарием (не в .gitignore — добавит Task 2.7)
- `.gitignore` в корне проекта — добавить строку `multiprocess_prototype/backend/config/user_overrides.yaml`

**Steps:**

1. Написать функцию `_deep_merge(base: dict, override: dict) -> dict` в `schemas.py`:
   - Рекурсивно мержит `override` поверх `base`
   - Если оба значения — `dict`, мержить рекурсивно
   - Если тип не совпадает или override — не dict, брать значение из `override`
   - Функция чистая (не мутирует аргументы)

2. В `load_system_config(path)` после загрузки `system.yaml` добавить блок:
   ```
   override_path = path.parent / "user_overrides.yaml"
   if override_path.exists():
       raw = _deep_merge(raw, yaml.safe_load(override_path) or {})
   ```

3. Создать `user_overrides.yaml` с комментарием и пустым телом:
   ```yaml
   # Пользовательские переопределения — не коммитить (добавлен в .gitignore)
   # Пример:
   # discovery:
   #   plugin_paths:
   #     - "Plugins"
   #     - "/absolute/path/to/custom_plugins"
   ```

4. Добавить в корневой `.gitignore`:
   ```
   multiprocess_prototype/backend/config/user_overrides.yaml
   ```

**Acceptance criteria:**
- [x] `_deep_merge({"a": {"x": 1}}, {"a": {"y": 2}}) == {"a": {"x": 1, "y": 2}}` (0ac9a0f)
- [x] `_deep_merge({"a": 1}, {"a": 2}) == {"a": 2}` (override wins) (0ac9a0f)
- [x] При наличии `user_overrides.yaml` с `discovery.plugin_paths: ["/tmp/extra"]` — `load_system_config()` возвращает `discovery.plugin_paths == ["/tmp/extra"]` (0ac9a0f)
- [x] При отсутствии `user_overrides.yaml` — `load_system_config()` работает как прежде (0ac9a0f)
- [x] `user_overrides.yaml` в корне проекта `.gitignore` (проверить `git check-ignore`) (0ac9a0f)

**Out of scope:** Не реализовывать запись в `user_overrides.yaml` — это делает Task 2.5 (GUI). Не трогать AppContext, main.py, app.py.

**Edge cases:**
- `user_overrides.yaml` существует, но пустой (`yaml.safe_load` вернёт `None`) → `_deep_merge(raw, {})` → без изменений
- `user_overrides.yaml` содержит невалидный YAML → `yaml.safe_load` бросает `yaml.YAMLError` → поймать, залогировать `print(f"[config] user_overrides.yaml: ошибка разбора: {e}")`, вернуть `SystemConfig.model_validate(raw)` без override

**Dependencies:** нет (Task 2.2 можно запускать параллельно с Task 2.1)

**Module contract:** impl-only (изменяет внутреннюю логику `load_system_config`, публичная сигнатура не меняется)

---

### Task 2.3 — Config-driven discovery в main.py и app.py

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Убрать хардкод `PLUGINS_DIR` / `_PLUGINS_DIR` из `main.py` и `app.py`, заменив на чтение из `sys_config.discovery.plugin_paths` с резолюцией относительно `PROJECT_ROOT`.

**Context:** После Task 2.1 в `SystemConfig` есть `discovery.plugin_paths: list[str]`. Нужно, чтобы оба места запуска (backend bootstrap и GUI startup) читали пути из конфига. Относительные пути резолвятся от `PROJECT_ROOT` (`HERE.parent` в main.py); абсолютные — как есть. `PluginRegistry.discover()` принимает varargs строк — передаём распакованный список.

**Files:**
- `multiprocess_prototype/main.py` — удалить строку `PLUGINS_DIR = PROJECT_ROOT / "Plugins"` (строка 33), изменить вызов `PluginRegistry.discover()`
- `multiprocess_prototype/frontend/app.py` — удалить `_PLUGINS_DIR = Path(...) / "Plugins"` (строка 22), передавать пути через config

**Steps:**

1. В `main.py`, функция `bootstrap()`:
   - Строку `PLUGINS_DIR = PROJECT_ROOT / "Plugins"` — **удалить** (это module-level константа, строка 33)
   - После `sys_config = load_system_config(CONFIG_PATH)` добавить:
     ```python
     _plugin_paths = [
         str(PROJECT_ROOT / p) if not Path(p).is_absolute() else p
         for p in (sys_config.discovery.plugin_paths if sys_config.discovery.auto_discover else [])
     ]
     ```
   - Заменить `PluginRegistry.discover(str(PLUGINS_DIR))` на `PluginRegistry.discover(*_plugin_paths)`

2. В `app.py`, функция `run_gui()`:
   - Строку `_PLUGINS_DIR = Path(__file__).resolve().parents[2] / "Plugins"` — **удалить** (строка 22, module-level)
   - В теле `run_gui()`, перед вызовом `PluginRegistry.discover(...)`, добавить загрузку конфига:
     ```python
     from multiprocess_prototype.backend.config.schemas import load_system_config
     from multiprocess_prototype.main import CONFIG_PATH, PROJECT_ROOT
     _app_sys_config = load_system_config(CONFIG_PATH)
     _app_plugin_paths = [
         str(PROJECT_ROOT / p) if not Path(p).is_absolute() else p
         for p in (_app_sys_config.discovery.plugin_paths if _app_sys_config.discovery.auto_discover else [])
     ]
     ```
   - Заменить `PluginRegistry.discover(str(_PLUGINS_DIR))` на `PluginRegistry.discover(*_app_plugin_paths)`

3. Убедиться, что если `_plugin_paths` пуст (пустой список из конфига или `auto_discover: false`), `PluginRegistry.discover()` вызывается без аргументов и не падает.

**Acceptance criteria:**
- [x] Строка `PLUGINS_DIR = PROJECT_ROOT / "Plugins"` отсутствует в `main.py` (e32c57d)
- [x] Строка `_PLUGINS_DIR = ...` отсутствует в `app.py` (e32c57d)
- [x] `bootstrap()` вызывает `PluginRegistry.discover("...абсолютный путь...")` с путями из `sys_config` (e32c57d)
- [x] При `discovery.plugin_paths: []` — `PluginRegistry.discover()` вызывается без аргументов, приложение стартует без ошибок (e32c57d)
- [x] При `auto_discover: false` — discovery не вызывается (e32c57d)

**Out of scope:** Не создавать `PluginManager` singleton здесь — это Task 2.4. Не трогать AppContext. Не менять логику вызова в bootstrap после строки discover.

**Edge cases:**
- `discovery.plugin_paths` содержит несуществующую директорию → `PluginRegistry.discover()` уже обрабатывает это gracefully (не падает, возвращает пустой результат). Дополнительная обработка не нужна.
- Путь абсолютный (`/opt/custom_plugins`) → не оборачивать в `PROJECT_ROOT /`, брать как есть.

**Dependencies:** Task 2.1 (нужна `DiscoverySection` в `SystemConfig`), Task 2.2 (нужен `load_system_config` с override)

**Module contract:** impl-only

---

### Task 2.4 — AppContext.plugin_manager(): singleton PluginManager

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Добавить в `AppContext` getter `plugin_manager()` возвращающий singleton `PluginManager`, инициализированный с путями из конфига и хранящийся в `extras["plugin_manager"]`; провести инициализацию в `run_gui()` до создания табов.

**Context:** `PluginManager` (framework, `process_module/plugins/manager.py`) уже существует и протестирован. Он принимает `registry`, `paths`, и опциональные logger/stats/error. GUI-компоненты (каталог, подвкладка «Пути») должны получать его через `ctx.plugin_manager()` — единый singleton. Создавать его нужно в `run_gui()` после того, как пути плагинов уже известны из конфига, и до создания табов.

**Files:**
- `multiprocess_prototype/frontend/app_context.py` — добавить метод `plugin_manager()`
- `multiprocess_prototype/frontend/app.py` — добавить создание `PluginManager` в `run_gui()` и сохранение в `ctx.extras`

**Steps:**

1. В `app_context.py`, в `TYPE_CHECKING` блок добавить:
   ```python
   from multiprocess_framework.modules.process_module.plugins.manager import PluginManager
   ```

2. В классе `AppContext` добавить метод:
   ```python
   def plugin_manager(self) -> "PluginManager | None":
       """Singleton PluginManager — автообнаружение и hot-reload плагинов.

       Инициализируется в run_gui() из путей sys_config.discovery.plugin_paths.
       None если GUI-процесс не инициализировал (например, в тестах).
       """
       return self.extras.get("plugin_manager")
   ```

3. В `app.py`, функция `run_gui()`, после блока `# 2. Сканировать плагины и построить RegistersManager` (после вызова `PluginRegistry.discover()`), добавить создание PluginManager:
   ```python
   from multiprocess_framework.modules.process_module.plugins.manager import PluginManager
   _plugin_manager = PluginManager(
       registry=PluginRegistry,
       paths=_app_plugin_paths,  # переменная из блока выше (Task 2.3)
   )
   _plugin_manager.initialize()
   ```
   Затем в `extras` контекста (после `ctx = build_app_context(...)`) добавить:
   ```python
   ctx.extras["plugin_manager"] = _plugin_manager
   ```

4. Убедиться, что `_app_plugin_paths` из Task 2.3 доступна в нужном месте (определяется до блока `# 2.`).

**Acceptance criteria:**
- [x] `ctx.plugin_manager()` возвращает объект `PluginManager`, не `None`, при нормальном запуске GUI (3212350)
- [x] `ctx.plugin_manager() is ctx.plugin_manager()` — один и тот же объект (singleton через extras) (3212350)
- [x] `ctx.plugin_manager().is_discovered` — `True` после `initialize()` (или после первого `discover()` если автодискавери вызван) (3212350)
- [x] В тестах `ctx = MagicMock()` → `ctx.plugin_manager.return_value = None` — не ломает виджеты, использующие getter (3212350)

**Out of scope:** Не вызывать `plugin_manager.discover()` повторно если `PluginRegistry.discover()` уже был вызван выше в `run_gui()`. PluginManager.initialize() не вызывает discover автоматически. Не реализовывать GUI подвкладку — это Task 2.5.

**Edge cases:**
- `_app_plugin_paths` пуст → `PluginManager(registry, paths=[])` — корректное состояние, менеджер инициализирован, список путей пуст.

**Dependencies:** Task 2.3 (нужна переменная `_app_plugin_paths` в `run_gui()`)

**Module contract:** public-api-change (добавляет публичный getter в `AppContext`)

---

### Task 2.5 — Подвкладка «Пути» в PluginsTab (MVP)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать подвкладку «Пути» в `PluginsTab` с QListWidget путей, кнопками «Добавить папку» / «Удалить» / «Рескан» и персистенцией в `user_overrides.yaml`.

**Context:** Каталог плагинов должен поддерживать редактирование путей из GUI без рестарта. Подвкладка добавляется как отдельная секция-«мета» в дереве навигации PluginsTab (отдельная ветка «Пути», не под категорией плагинов). Изменения путей персистируются в `user_overrides.yaml` через функцию-helper (не перетирая остальные секции файла).

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/plugins/paths_subtab.py` — создать (новый файл)
- `multiprocess_prototype/frontend/widgets/tabs/plugins/_sections.py` — добавить `_PathsSection` и регистрацию в `build_plugin_sections()`
- `multiprocess_prototype/frontend/widgets/tabs/plugins/presenter.py` — добавить методы управления путями в `PluginsPresenter`

**Steps:**

1. В `presenter.py` добавить методы:

   - `get_plugin_paths() -> list[str]` — читает пути из `ctx.plugin_manager().plugin_paths` (если plugin_manager есть) или возвращает `[]`
   - `add_plugin_path(path: str) -> None` — добавляет путь в список через `_save_paths_to_overrides([...new_list])`
   - `remove_plugin_path(path: str) -> None` — удаляет путь (если есть) и сохраняет
   - `rescan() -> str` — вызывает `ctx.plugin_manager().rescan()`, возвращает строку-summary вида `"Загружено: 5, ошибок: 0, новых: 2"`
   - `_save_paths_to_overrides(paths: list[str]) -> None` — записывает `{"discovery": {"plugin_paths": paths}}` в `user_overrides.yaml` через `_deep_merge_and_save()`:
     - Читает текущий `user_overrides.yaml` (или `{}` если не существует)
     - Deep-merge: обновляет только ключ `discovery.plugin_paths`
     - Записывает обратно через `yaml.dump(..., allow_unicode=True, default_flow_style=False)`
     - Путь к файлу: `CONFIG_PATH.parent / "user_overrides.yaml"` (импортировать `CONFIG_PATH` из `multiprocess_prototype.main`)

2. Создать файл `paths_subtab.py` с классом `PathsSubtabWidget(QWidget)`:
   - Конструктор принимает `presenter: PluginsPresenter`
   - Верстка (QVBoxLayout):
     - QLabel «Директории плагинов» (заголовок)
     - `QListWidget` (self._list) — список путей, SelectionMode.SingleSelection
     - QHBoxLayout с кнопками:
       - QPushButton «Добавить папку...» → `_on_add()`
       - QPushButton «Удалить» → `_on_remove()`
       - QPushButton «Рескан» → `_on_rescan()`
     - QLabel (self._status) — однострочный статус (результат rescan или «Путь добавлен»)
   - `_populate()` — заполнить `self._list` из `presenter.get_plugin_paths()`
   - `_on_add()`:
     - Открыть `QFileDialog.getExistingDirectory(self, "Выберите папку с плагинами")`
     - Если директория выбрана → `presenter.add_plugin_path(path)` → `_populate()` → `self._status.setText("Путь добавлен")`
   - `_on_remove()`:
     - Взять текущий выбранный item из `self._list`
     - Если есть → `presenter.remove_plugin_path(item.text())` → `_populate()` → `self._status.setText("Путь удалён")`
   - `_on_rescan()`:
     - Вызвать `summary = presenter.rescan()`
     - `_populate()` (обновить список после rescan, пути могут не измениться)
     - `self._status.setText(summary)`
     - Emit сигнал `catalog_updated = Signal()` для подписки каталога (Task 2.6)

3. В `_sections.py` добавить `_PathsSection`:
   - `key = "__paths__"`, `title = "Пути"`, без `parent_key` (корневая секция)
   - `widget()` лениво создаёт `PathsSubtabWidget(PluginsPresenter(self._ctx))`
   - `action_buttons()` возвращает `[]`

4. В `build_plugin_sections()` добавить `_PathsSection` как **первый** элемент списка `sections` (перед категориями плагинов), обёрнутый в `SectionSpec`:
   ```python
   sections.append(SectionSpec(key="__paths__", title="Пути", factory=_make_paths_factory()))
   ```

**Acceptance criteria:**
- [x] Подвкладка «Пути» появляется в дереве навигации PluginsTab как корневой элемент (не под категорией) (Task 2.5)
- [x] «Добавить папку» открывает QFileDialog, добавленный путь появляется в списке (Task 2.5)
- [x] «Удалить» удаляет выбранный путь из списка (Task 2.5)
- [x] «Рескан» вызывает `PluginManager.rescan()` и обновляет статус-строку (Task 2.5)
- [x] После добавления/удаления пути `user_overrides.yaml` содержит актуальный список `discovery.plugin_paths` (Task 2.5)
- [x] При `plugin_manager() == None` (тесты без GUI) — `get_plugin_paths()` возвращает `[]`, кнопки работают без краша (Task 2.5)

**Out of scope:** Не реализовывать drag-drop переупорядочивания путей. Не добавлять валидацию «директория существует» при добавлении (пусть PluginManager.rescan разберётся). Не трогать каталог (Cards/Table) — обновление каталога после rescan — это Task 2.6.

**Edge cases:**
- `get_existing_directory` возвращает пустую строку (пользователь отменил) → ничего не делать
- `presenter.rescan()` при пустом `plugin_manager()` → вернуть строку `"PluginManager не инициализирован"`, не падать

**Dependencies:** Task 2.4 (нужен `AppContext.plugin_manager()`)

**Module contract:** new-lite (новый файл `paths_subtab.py`)

---

### Task 2.6 — Каталог подписывается на catalog_updated → перерисовка

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** После rescan каталог (Cards + Table) автоматически обновляет список плагинов без перезапуска, подписавшись на сигнал `catalog_updated` от `PathsSubtabWidget`.

**Context:** Когда `PluginManager.rescan()` завершается, в `PluginRegistry` могут появиться новые плагины. `PluginsTab` строит дерево навигации и таблицу один раз при инициализации. Нужно: при `catalog_updated` → переперестроить `_sections_specs` и обновить дерево и таблицу.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/plugins/tab.py` — добавить подписку и метод `refresh_catalog()`
- `multiprocess_prototype/frontend/widgets/tabs/plugins/_sections.py` — `_PathsSection.widget()` должен возвращать `PathsSubtabWidget` с доступом к сигналу

**Steps:**

1. В `tab.py`, метод `__init__`, после `self.populate()`:
   - Найти секцию «Пути» в `self._sections_specs` (по ключу `"__paths__"`)
   - Получить виджет (`_PathsSection.widget()` → `PathsSubtabWidget`)
   - Подключить: `paths_widget.catalog_updated.connect(self.refresh_catalog)`

2. Добавить метод `refresh_catalog(self) -> None` в `PluginsTab`:
   - Пересобрать секции через `build_plugin_sections(self._ctx)` (вызвать заново)
   - Обновить `self._sections_specs` (поле базы) — новый список
   - Перестроить дерево: очистить `self._tree_nav`, вызвать `build_nav_tree_from_specs(self._tree_nav, self._sections_specs)`, `self._tree_nav.expandAll()`
   - Если текущий режим `TABLE` → вызвать `self._refresh_table()`
   - Установить `self._status.setText("Каталог обновлён")` если есть статус-лейбл (опционально, не обязательно)

3. Убедиться, что `_PathsSection` создаёт `PathsSubtabWidget` в `widget()` и возвращает его повторно (lazy: создать один раз). Это важно, чтобы подписка не терялась при повторных вызовах `widget()`.

**Acceptance criteria:**
- [x] После вызова `_on_rescan()` в `PathsSubtabWidget` → `catalog_updated` emit → `refresh_catalog()` вызван (Task 2.6)
- [x] Если до rescan было N плагинов, а после N+1 → дерево показывает N+1 плагин (без рестарта) (Task 2.6)
- [x] Режим TABLE: после rescan таблица тоже обновляется (строк стало больше) (Task 2.6)
- [x] Повторный `refresh_catalog()` не дублирует плагины в дереве (Task 2.6)

**Out of scope:** Не анимировать переход. Не сохранять «выбранный плагин» при обновлении дерева (сброс выделения допустим). Не реализовывать diff-алгоритм (полная перестройка достаточна для MVP).

**Edge cases:**
- `_tree_nav is None` (крайне маловероятно, но защититься `if self._tree_nav is None: return`)
- rescan не нашёл новых плагинов → `refresh_catalog()` всё равно вызван, дерево перестраивается (нейтральная операция)

**Dependencies:** Task 2.4 (plugin_manager), Task 2.5 (PathsSubtabWidget с сигналом catalog_updated)

**Module contract:** impl-only

---

### Task 2.7 — Тесты Phase 2

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Написать 7 unit/integration тестов, покрывающих все новые компоненты Phase 2: схему, deep-merge, bootstrap-логику, singleton, подвкладку «Пути» и обновление каталога.

**Context:** Тесты живут рядом с тестируемым кодом. Config-тесты — в новой директории `multiprocess_prototype/backend/config/tests/`. GUI-тесты для подвкладки — рядом с существующими `plugins/tests/test_plugins_tab.py`. Все тесты должны проходить через `python scripts/run_framework_tests.py` или `pytest` из корня.

**Files:**
- `multiprocess_prototype/backend/config/tests/__init__.py` — создать пустой
- `multiprocess_prototype/backend/config/tests/test_discovery_schema.py` — создать (3 теста)
- `multiprocess_prototype/frontend/widgets/tabs/plugins/tests/test_paths_subtab.py` — создать (4 теста)

**Steps:**

1. `test_discovery_schema.py` — тесты на схему и loader:

   **test_discovery_section_defaults** — проверить, что `DiscoverySection()` даёт `plugin_paths=["Plugins"]`, `service_paths=["Services"]`, `auto_discover=True`

   **test_load_system_config_with_overrides** (tmp_path fixture):
   - Создать `system.yaml` с `discovery.plugin_paths: ["Plugins"]`
   - Создать `user_overrides.yaml` с `discovery.plugin_paths: ["/custom"]`
   - Вызвать `load_system_config(system_yaml_path)`
   - Assert: `result.discovery.plugin_paths == ["/custom"]`

   **test_load_system_config_override_partial_merge** (tmp_path fixture):
   - `system.yaml`: `discovery: {plugin_paths: ["Plugins"], auto_discover: true}`
   - `user_overrides.yaml`: `discovery: {plugin_paths: ["/extra"]}` (без auto_discover)
   - Assert: `result.discovery.plugin_paths == ["/extra"]` и `result.discovery.auto_discover == True` (не перетёрто)

2. `test_paths_subtab.py` — тесты GUI (используют `qtbot`):

   **test_paths_subtab_creates_without_plugin_manager** (qtbot):
   - `ctx = _make_mock_ctx()` (из существующего test_plugins_tab.py)
   - `ctx.plugin_manager.return_value = None`
   - Создать `PathsSubtabWidget(PluginsPresenter(ctx))`
   - `qtbot.addWidget(widget)`
   - Assert: виджет создан без исключений, `widget._list.count() == 0`

   **test_paths_subtab_shows_paths_from_manager** (qtbot):
   - Mock `ctx.plugin_manager()` → Mock PluginManager с `plugin_paths = [Path("/test/Plugins")]`
   - Создать `PathsSubtabWidget(PluginsPresenter(ctx))`
   - `qtbot.addWidget(widget)`
   - Assert: `widget._list.count() == 1`, `widget._list.item(0).text() == "/test/Plugins"`

   **test_rescan_updates_status** (qtbot):
   - Mock `plugin_manager` с `rescan()` возвращающим объект с `loaded=["p1"]`, `failed=[]`, `new_plugins=["p1"]`
   - Нажать кнопку «Рескан» программно → `widget._on_rescan()`
   - Assert: `widget._status.text()` содержит «Загружено: 1» (или «1» + «0» + «1»)

   **test_catalog_updated_emitted_on_rescan** (qtbot):
   - Mock plugin_manager с `rescan()` → любой результат
   - Подписаться на `widget.catalog_updated` через `qtbot.waitSignal`
   - Вызвать `widget._on_rescan()`
   - Assert: сигнал был emit'нут

**Acceptance criteria:**
- [x] `pytest multiprocess_prototype/backend/config/tests/` — 3 теста PASSED (92cad02)
- [x] `pytest multiprocess_prototype/frontend/widgets/tabs/plugins/tests/test_paths_subtab.py` — 4 теста PASSED (92cad02)
- [x] Все тесты из Task 2.7 проходят вместе с существующими тестами в `test_plugins_tab.py` без конфликтов (92cad02)
- [x] Нет новых `import` ошибок при запуске всего suite (92cad02)

**Out of scope:** Не писать E2E тест с реальным запуском GUI-процесса. Не тестировать `_save_paths_to_overrides` через реальную файловую систему — используй `tmp_path` или мокировать.

**Edge cases:**
- `tmp_path` fixtures: `user_overrides.yaml` отсутствует, существует, пустой, невалидный YAML — покрыто тестами выше

**Dependencies:** Все Tasks 2.1–2.6 должны быть завершены

**Module contract:** n/a (только тесты)

---

## Закрытие фазы

**Статус: ✅ DONE** (2026-05-25)

**Сводка:** Discovery теперь полностью config-driven (`system.yaml` + опциональный `user_overrides.yaml` с deep-merge), хардкод `PLUGINS_DIR`/`_PLUGINS_DIR` удалён. `PluginManager` доступен как singleton через `AppContext.plugin_manager()`. В `PluginsTab` добавлена подвкладка «Пути» с CRUD путей и кнопкой «Рескан», каталог обновляется по сигналу `catalog_updated` без перезапуска.

**Коммиты фазы (11):**

| Хеш | Тип | Что |
|-----|-----|-----|
| d91d753 | docs | Декомпозиция Phase 2 на 7 Task X.Y |
| 6eb7212 | feat (Task 2.1) | `DiscoverySection` + секция в `system.yaml` |
| 0ac9a0f | feat (Task 2.2) | `_deep_merge` + автозагрузка `user_overrides.yaml` |
| e32c57d | feat (Task 2.3) | Убрать хардкод `PLUGINS_DIR` из `main.py`/`app.py` |
| 3212350 | feat (Task 2.4) | `AppContext.plugin_manager()` + singleton в `run_gui` |
| b02ab48 | docs | Tasks 2.1–2.4 [x] |
| 9de9f34 | feat (Task 2.5) | Подвкладка «Пути» (`PathsSubtabWidget`) |
| bcee165 | feat (Task 2.6) | `catalog_updated` → `refresh_catalog` |
| 92cad02 | test (Task 2.7) | 7 тестов (3 config + 4 GUI) |
| dbf2a28 | test | Регрессия в `test_plugins_tab.py` под новую секцию «Пути» |
| d405e1e | fix | Singleton `_PathsSection` через модульный кэш по `id(ctx)` |

**Тесты:** 22 PASSED (`pytest backend/config/tests + frontend/widgets/tabs/plugins/tests`).

**Ревью:** Reviewer (Opus) — 2 итерации, APPROVE на 2-й.

**Technical debt (follow-up, не блокирует merge):**

1. **Прямой доступ к `PluginManager._plugin_paths`** в `presenter.add_plugin_path/remove_plugin_path` (`presenter.py:155,174`). Допустимо для MVP. В следующей фазе — добавить публичный `PluginManager.set_paths(paths)` в framework.
2. **Дублирование list comprehension** для резолюции путей в `main.py` и `app.py`. Кандидат на утилитную функцию `resolve_plugin_paths(config, root)` в `schemas.py`.
3. **`refresh_catalog` не очищает `_content_stack`** — старые lazy-секции плагинов остаются в QStackedWidget после rescan. При частом rescan'е возможен рост виджетов. Для MVP допустимо.
4. **Type hint `qtbot: pytest.fixture`** — некорректная аннотация в существующем `test_plugins_tab.py` и новом `test_paths_subtab.py`. Исправить разом в follow-up рефакторинге.

**Acceptance Phase 2 в master plan:**
- [x] Добавление пути через GUI → плагины из новой папки видны в каталоге без рестарта (Task 2.5 + 2.6)
- [x] Настройки персистятся в `user_overrides.yaml` (Task 2.2 + 2.5)
- [x] 5-7 unit-тестов (фактически 7) + регрессия на caталог (Task 2.7 + dbf2a28)
