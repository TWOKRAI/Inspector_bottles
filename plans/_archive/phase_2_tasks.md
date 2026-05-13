---
status: planned
phase: 2
branch: feat/phase-2-settings-tab
base: master @ 2456789
created: 2026-04-22
---

# Phase 2 — Настройки: переключаемые профили

## Обзор

Phase 2 добавляет в вкладку «Настройки» (`SettingsTabWidget`) панель выбора и редактирования
профилей приложения (`SettingsProfilePanelWidget`). Пользователь видит: выпадающий список
профилей + кнопки Применить / Сохранить / По умолчанию + таблицу полей `AppSettingsRegisters`.
При переключении профиля `SettingsProfileManager.switch_profile` применяет snapshot в
`RegistersManager`, а `profile_changed` pyqtSignal уведомляет подписчиков (Phase 3+ слушают
этот сигнал для перестройки оркестрации).

Паттерн MVP из Phase 1 (`model / presenter / view / panel_widget`) переиспользуется полностью;
`RecipeSlotComboModel` используется для списка строковых profile_id; `RecipePanelBase` не
наследуется — у профилей нет int-слотов и `RecipesTabConfig`.

**Merge-стратегия:** squash → master.

**PR-чеклист:**
- `ruff check + ruff format` — зелёный
- `python scripts/validate.py` — pass
- `python scripts/run_framework_tests.py` — pass
- Все новые L1 unit-тесты проходят без PyQt5
- Минимум 1 L2 integration-тест (переключение профиля → RegistersManager отражает значения)
- Обновлён `README.md` в `settings_profile_widget/`

---

## Архитектурные решения Phase 2

### Почему не наследуемся от RecipePanelBase

`RecipePanelBase` жёстко привязан к:
- `parse_slot() -> int` + `parse_clamped_recipe_slot_text` (int-диапазон, min/max из `RecipesTabConfig`)
- `RecipeSlotComboModel.from_manager(recipe_manager, index_min, index_max)` — ждёт числовые границы
- `RecipesTabConfig` как обязательный `_ui` (поля `recipe_index_min`, `recipe_index_max`, `group_register_box`, etc.)
- `RecipeAutoSave` с `rm_snapshot_fn` специфичным для `RegistersManager`

Для профилей — string-based идентификаторы, своя схема конфига, другой менеджер. Создаём
независимый MVP-стек по тому же паттерну. `RecipeSlotComboModel` переиспользуется напрямую:
он уже работает со строками (поле `slots: list[str]`), и `from_manager` достаточно вызвать с
`list_profiles()` вместо `list_slots()`.

### Как реализовать profile_changed

`SettingsProfilePanelWidget` объявляет `profile_changed = pyqtSignal(str)` — аргумент `profile_id`.
`SettingsTabWidget` при создании панели подключает `panel.profile_changed.connect(callback)`.
Для Phase 3+ caller (фабрика вкладок / `FrontendLauncher`) подключает дополнительные handler'ы
через getter `settings_profile_panel` у `SettingsTabWidget`. `FrontendAppContext` не несёт сигналов
(dataclass), propagation через Python-callback'и при инициализации.

### Merge-логика: полная замена snapshot

`SettingsProfileManager.switch_profile(profile_id, registers_bridge)` уже реализован в Phase 0:
вызывает `AppSettingsRegisters.model_validate(snap)` → `validate_shm_budget(profile)` → 
`registers_bridge.model_validate_all({SETTINGS_REGISTER: profile.model_dump()})`.
Это полная замена snapshot с Pydantic-валидацией и SHM budget check.

Partial merge не нужен — Pydantic заполнит пустые поля defaults при `model_validate`.
При `ShmBudgetError` presenter показывает ошибку через view-callback, регистры не меняются.

### Схема конфига SettingsProfileTabConfig

Отдельная `SettingsProfileTabConfig(SchemaBase)` в
`frontend/widgets/settings_profile_widget/schemas.py`. Поля:
- строковые метки кнопок и подписей
- `touch_keyboard: Optional[dict]`

Не расширяет `SettingsTabConfig` (та Legacy-схема с `controls: List[ControlBinding]`).

---

### Task 2.1 — SettingsProfileTabConfig: схема конфига и строки UI

**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Создать `SettingsProfileTabConfig(SchemaBase)` — конфигурационную схему панели
профилей настроек с текстами кнопок, подписей и опциональным touch_keyboard.

**Контекст:**
По аналогии с `RecipesTabConfig` в Phase 1, для `SettingsProfilePanelWidget` нужна своя схема
конфига. Она хранит строковые метки UI (кнопки, заголовки, подписи) и передаётся через
`coerce_schema_config`. Схема регистрируется через `@register_schema` для serialization
compatibility.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/settings_profile_widget/schemas.py` — создать
- `multiprocess_prototype/frontend/widgets/settings_profile_widget/__init__.py` — создать

**Шаги:**
1. Создать `SettingsProfileTabConfig(SchemaBase)` с аннотацией `@register_schema("SettingsProfileTabConfig")`.
2. Поля с `FieldMeta` и русскими дефолтными значениями:
   - `group_box_title: str = "Профиль настроек"`
   - `label_profile: str = "Профиль:"`
   - `btn_apply: str = "Применить"`
   - `btn_save: str = "Сохранить"`
   - `btn_default: str = "По умолчанию"`
   - `table_title: str = "Параметры приложения"`
   - `col_param: str = "Параметр"`
   - `col_value: str = "Значение"`
   - `col_info: str = "Информация"`
   - `touch_keyboard: Optional[Dict[str, Any]] = None` (через `Field(default=None)`)
3. В `__init__.py` экспортировать `SettingsProfileTabConfig`.
4. Добавить `default_tab_item()` функцию возвращающую `TabItemConfig(id="settings_profile", title="Настройки профиля", widget="settings_profile")` — для будущей интеграции в `TabsConfig`.

**Критерии приёмки:**
- [ ] `SettingsProfileTabConfig()` создаётся с дефолтами без ошибок
- [ ] `SettingsProfileTabConfig.model_dump()` / `model_validate(data)` round-trip корректен
- [ ] `coerce_schema_config(None, SettingsProfileTabConfig)` возвращает объект с дефолтами
- [ ] `coerce_schema_config({"btn_apply": "Применить!"}, SettingsProfileTabConfig)` переопределяет поле
- [ ] `ruff check` на новых файлах чистый
- [ ] Файл импортируется без PyQt5

**Вне scope:** не изменять `SettingsTabConfig`, не добавлять логику UI, не регистрировать
в `_default_tabs()` — это Task 2.6.

**Зависимости:** нет (первая задача в цепочке).

---

### Task 2.2 — SettingsProfileComboModel: модель списка профилей (str-based)

**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Создать `SettingsProfileComboModel` — тонкую обёртку над `RecipeSlotComboModel`
для строковых profile_id с фабричным методом `from_profile_manager`.

**Контекст:**
`RecipeSlotComboModel` уже работает с `slots: list[str]` и не зависит от int-диапазонов.
Нужно создать factory `from_profile_manager(manager)` который вызывает `manager.list_profiles()`
и передаёт в `RecipeSlotComboModel` с кастомной `label_fn` (имя профиля без "Слот" префикса).
`SettingsProfileComboModel` — это type alias или thin subclass с одним classmethod, без дублирования
логики `RecipeSlotComboModel`.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/settings_profile_widget/profile_combo_model.py` — создать
- `multiprocess_prototype/frontend/widgets/settings_profile_widget/__init__.py` — добавить экспорт

**Шаги:**
1. Импортировать `RecipeSlotComboModel` из `..recipes_widget.slot_combo_model`.
2. Создать `SettingsProfileComboModel` как dataclass-обёртку или simple module-level factory:
   - `from_profile_manager(manager: Any) -> RecipeSlotComboModel`: вызывает `manager.list_profiles()`,
     если список пустой — использует `["default"]` как fallback;
     передаёт `label_fn=lambda pid: pid` (профиль отображается своим именем, без "Слот" префикса);
     возвращает `RecipeSlotComboModel(slots=profiles, current_index=0, label_fn=...)`.
3. Добавить `sync_current(model: RecipeSlotComboModel, manager: Any) -> None` — устанавливает
   `model.current_index = model.index_for_slot_id(manager.get_current_profile_id())`.
4. Функция `profile_id_from_model(model: RecipeSlotComboModel) -> str` — возвращает
   `model.current_slot_id()` (str, не int). Это замена `parse_slot() -> int` для профилей.

**Критерии приёмки:**
- [ ] `from_profile_manager(mock_manager_with(["default","fast"]))` → `model.slots == ["default","fast"]`
- [ ] `from_profile_manager(mock_manager_with([]))` → `model.slots == ["default"]` (fallback)
- [ ] `label_fn("fast")` → `"fast"` (не "Слот fast")
- [ ] `sync_current` устанавливает правильный index при наличии профиля в списке
- [ ] Файл импортируется без PyQt5
- [ ] `ruff check` чистый

**Вне scope:** не дублировать логику `RecipeSlotComboModel` (index conversion, labels property,
slot_id_for_index). Не добавлять логику сохранения/загрузки YAML.

**Зависимости:** Task 2.1 (пакет создан).

---

### Task 2.3 — SettingsProfileModel + SettingsProfilePresenter: MVP-слои без Qt

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Создать `SettingsProfileModel` (dataclass) и `SettingsProfilePresenter` — полные
MVP-слои логики панели профилей без зависимостей на PyQt5.

**Контекст:**
По аналогии с `RegisterRecipeModel` + `RegisterRecipePresenter` из Phase 1. Отличия:
- `SettingsProfileModel` держит ссылки на `SettingsProfileManagerProtocol`, `RegistersManager`
  (или `Any` — duck typing), `RecipeSlotComboModel` (список профилей), `SettingsProfileTabConfig`.
- `SettingsProfilePresenter` реализует `on_apply_clicked()` (switch_profile), `on_save_clicked()`
  (save_profile_snapshot из текущих регистров), `on_default_clicked()` (switch к "default"),
  `on_leaf_value_changed(group_id, field_id, column_key, text)` (set_field_value в rm).
- При `ShmBudgetError` в `on_apply_clicked()` — вызвать `view.show_error(str(e))`, не падать.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/settings_profile_widget/model.py` — создать
- `multiprocess_prototype/frontend/widgets/settings_profile_widget/presenter.py` — создать
- `multiprocess_prototype/frontend/widgets/settings_profile_widget/view.py` — создать

**Шаги:**

**model.py:**
1. Создать `@dataclass SettingsProfileModel`:
   - `ui: SettingsProfileTabConfig`
   - `profile_manager: Any` (SettingsProfileManagerProtocol duck-typed)
   - `rm: Any` (RegistersManager duck-typed, может быть None)
   - `combo_model: RecipeSlotComboModel`
2. Метод `compute_initial_profile_id() -> str`:
   возвращает `profile_manager.get_current_profile_id()` если manager есть, иначе `"default"`.
3. Метод `build_tree_rows() -> list[dict]`: читает `rm.get_register(SETTINGS_REGISTER)`,
   вызывает `rm.get_field_metadata(SETTINGS_REGISTER)` для получения `FieldMeta`;
   строит rows `[{group_id: SETTINGS_REGISTER, field_id: fname, param: label, value: current_val, info: meta.info}]`.
   Если `rm is None` — возвращает `[]`.

**view.py:**
4. Создать `@runtime_checkable class SettingsProfilePanelViewProtocol(Protocol)`:
   - `current_profile_id() -> str` — текущий profile_id из комбо (str, не int)
   - `refresh_table_rows() -> None`
   - `set_leaf_value_text(group_id: str, field_id: str, text: str) -> None`
   - `show_error(message: str) -> None` — показать сообщение об ошибке (ShmBudgetError)

**presenter.py:**
5. Создать `SettingsProfilePresenter`:
   - `__init__(self, *, view: SettingsProfilePanelViewProtocol, model: SettingsProfileModel)`
6. `on_apply_clicked() -> None`:
   - `profile_id = view.current_profile_id()`
   - вызвать `model.profile_manager.switch_profile(profile_id, model.rm)`
   - при `ShmBudgetError` → `view.show_error(str(e))`
   - при успехе → `view.refresh_table_rows()` + обновить `combo_model.current_index`
7. `on_save_clicked() -> None`:
   - `profile_id = view.current_profile_id()`
   - `snapshot = model.rm.model_dump_all()` если rm не None
   - вызвать `model.profile_manager.save_profile_snapshot(profile_id, snapshot)`
8. `on_default_clicked() -> None`:
   - вызвать `model.profile_manager.switch_profile("default", model.rm)`
   - при ошибке → `view.show_error(str(e))`
   - `view.refresh_table_rows()`
9. `on_leaf_value_changed(group_id: str, field_id: str, column_key: str, text: str) -> None`:
   - если `column_key != "value"` или `rm is None` → return
   - получить текущее значение через `rm.get_register(group_id)` + `model_dump()`
   - `coerce_string_to_value(text, prev)` (импорт из `..recipes_widget.recipe_rows`)
   - вызвать `rm.set_field_value(group_id, field_id, new_val)` — field_id = field_name
   - при неуспехе откатить `view.set_leaf_value_text(group_id, field_id, format_value_for_cell(prev))`
10. `build_tree_groups() -> list`: возвращает `[{"group_id": SETTINGS_REGISTER, "title": "...", "rows": model.build_tree_rows()}]`.
11. `refresh_from_registers() -> None`: вызывает `view.refresh_table_rows()`.

**Критерии приёмки:**
- [ ] `SettingsProfileModel` + `SettingsProfilePresenter` импортируются без PyQt5
- [ ] `on_apply_clicked()` при mock-manager вызывает `switch_profile` с правильным profile_id
- [ ] `on_apply_clicked()` при `ShmBudgetError` вызывает `view.show_error(...)` без проброса исключения
- [ ] `on_save_clicked()` вызывает `save_profile_snapshot` с данными из `rm.model_dump_all()`
- [ ] `on_leaf_value_changed` с невалидным значением откатывает ячейку
- [ ] `SettingsProfilePanelViewProtocol` проходит `isinstance` check на mock-объекте с нужными методами
- [ ] `ruff check` на всех трёх файлах чистый

**Вне scope:** не добавлять Qt-код. Не реализовывать `profile_changed` сигнал — это в Task 2.4.
Не добавлять auto-save (Phase 2 не предполагает debounce для профилей).

**Зависимости:** Task 2.1, Task 2.2.

---

### Task 2.4 — SettingsProfilePanelWidget: Qt-виджет + profile_changed сигнал

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Реализовать `SettingsProfilePanelWidget(BaseWidget[SettingsProfileModel])` — Qt-виджет
панели профилей с `QComboBox`, кнопками, `StructuredTwoLevelTreeWidget` и сигналом `profile_changed`.

**Контекст:**
По структуре аналогичен `AppRecipePanelWidget` из Phase 1 (`panel_widget.py`), но наследует
`BaseWidget[SettingsProfileModel]` напрямую (не через `RecipePanelBase`). Строит UI вручную
с теми же Qt-компонентами. `StructuredTwoLevelTreeWidget` переиспользуется как есть — он не
знает о типе данных.

Сигнал `profile_changed = pyqtSignal(str)` эмитируется после успешного `switch_profile`:
в `_on_apply_with_signal`. Внешние подписчики (Phase 3+) подключаются через геттер виджета.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/settings_profile_widget/panel_widget.py` — создать

**Шаги:**
1. Объявить `class SettingsProfilePanelWidget(BaseWidget[SettingsProfileModel])`:
   - `profile_changed = pyqtSignal(str)` — аргумент: profile_id строка
2. Конструктор:
   ```
   __init__(self, *, profile_manager, registers_manager, ui, touch_keyboard=None, parent=None)
   ```
   Сохранить аргументы, вызвать `super().__init__(registers_manager=registers_manager, ui=ui, parent=parent)`.
3. `_coerce_ui(ui)` → `coerce_schema_config(ui, SettingsProfileTabConfig)`.
4. `_create_model()`:
   - Построить `combo_model = from_profile_manager(self._profile_manager)`
   - `sync_current(combo_model, self._profile_manager)`
   - Вернуть `SettingsProfileModel(ui=self._ui, profile_manager=self._profile_manager, rm=self._registers_manager, combo_model=combo_model)`
5. `_create_presenter(model)` → `SettingsProfilePresenter(view=self, model=model)`.
6. `_init_ui()`:
   - `QGroupBox(self._ui.group_box_title)` + `QHBoxLayout`: `QLabel(label_profile)` + `QComboBox(self._profile_combo)` + кнопки Применить / Сохранить / По умолчанию
   - Заполнить `_profile_combo` из `self._model.combo_model.labels`
   - `QLabel(table_title)` + `StructuredTwoLevelTreeWidget` с колонками `[param, value, info]`
   - `self._block_table = False`
7. `_connect_signals()`:
   - `_btn_apply.clicked → _on_apply_with_signal`
   - `_btn_save.clicked → presenter.on_save_clicked`
   - `_btn_default.clicked → _on_default_with_signal`
   - `_tree.leaf_cell_changed → _on_leaf_value_changed_slot`
   - `_profile_combo.currentIndexChanged → _on_profile_index_changed`
8. `_on_apply_with_signal()`:
   - вызвать `self._presenter.on_apply_clicked()`
   - при успехе (нет исключения) — `self.profile_changed.emit(self.current_profile_id())`
9. `_on_default_with_signal()`:
   - вызвать `self._presenter.on_default_clicked()`
   - `self.profile_changed.emit("default")`
10. `current_profile_id() -> str` (реализует view protocol):
    - `combo_idx = self._profile_combo.currentIndex()`
    - `return self._model.combo_model.slot_id_for_index(combo_idx)`
11. `_on_profile_index_changed(index: int)`:
    - обновить `self._model.combo_model.current_index = index`
    - **не** вызывать apply автоматически (применение только через кнопку "Применить")
12. `show_error(message: str)` (реализует view protocol):
    - вывести `QMessageBox.warning(self, "Ошибка профиля", message)` или просто `print`/logger
13. `refresh_table_rows()`, `set_leaf_value_text(group_id, field_id, text)` — по аналогии с `RecipePanelBase`.
14. `_build_tree_data() -> list`: возвращает `self._presenter.build_tree_groups()`.
15. `_on_presenter_ready()`: вызвать `self.refresh_table_rows()`.

**Критерии приёмки:**
- [ ] `SettingsProfilePanelWidget` создаётся с `profile_manager=None` без ошибок (placeholder)
- [ ] `profile_changed` — сигнал PyQt (не обычный метод), проверяется `hasattr(panel, "profile_changed")`
- [ ] `current_profile_id()` возвращает строку из combo (не int)
- [ ] `show_error("test")` не бросает исключения
- [ ] `ruff check` на новом файле чистый

**Вне scope:** не добавлять auto-save с debounce. Не изменять `RecipePanelBase`. Не трогать
`SettingsTabWidget` — это Task 2.5.

**Зависимости:** Task 2.3.

---

### Task 2.5 — Интеграция в SettingsTabWidget + FrontendAppContext

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Добавить `SettingsProfilePanelWidget` в `SettingsTabWidget` рядом с
`AppRecipePanelWidget`, пробросить `settings_profile_manager` из `FrontendAppContext` и
обеспечить getter `profile_panel` для внешних подписчиков `profile_changed`.

**Контекст:**
`SettingsTabWidget` сейчас содержит только `AppRecipePanelWidget`. Нужно добавить
`SettingsProfilePanelWidget` выше или ниже него (выше — логичнее, сначала "какой профиль",
потом "UI-рецепт"). При этом `SettingsProfilePanelWidget` требует `profile_manager` и
`registers_manager`. Оба доступны в `FrontendAppContext`.

`FrontendAppContext.get_settings_profile_tab_ui()` — нужен новый метод-getter для секции
конфига `settings_profile_tab`. Добавить в `FrontendAppContext` и в `FrontendConfig.build_dict`
(или только в `app_context.py` с `config.get("settings_profile_tab")`).

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/recipes_settings_tab/widget.py` — изменить
- `multiprocess_prototype/frontend/app_context.py` — изменить

**Шаги:**
1. В `app_context.py` добавить метод `get_settings_profile_tab_ui(self) -> Any`:
   `return self.config.get("settings_profile_tab")`.
2. В `SettingsTabWidget.__init__` добавить параметр
   `settings_profile_manager: Optional[Any] = None` и сохранить.
3. В `SettingsTabWidget._init_ui()` после создания `AppRecipePanel` добавить блок:
   - если `settings_profile_manager is not None`:
     - создать `SettingsProfilePanelWidget(profile_manager=self._settings_profile_manager, registers_manager=self._registers_manager, ui=profile_tab_ui, ...)`
     - сохранить как `self._profile_panel: Optional[SettingsProfilePanelWidget]`
     - `layout.addWidget(self._profile_panel)` ПЕРЕД `app_recipe_panel`
   - иначе `self._profile_panel = None`
4. Добавить property `profile_panel` → `Optional[SettingsProfilePanelWidget]` — getter для
   подключения внешних обработчиков `profile_changed`.
5. В фабрике вкладок (или где `SettingsTabWidget` создаётся) добавить передачу
   `settings_profile_manager=ctx.settings_profile_manager` из `FrontendAppContext`.
   Найти точку создания через grep `SettingsTabWidget(` — это `frontend/launcher.py` или
   фабрика вкладок.

**Критерии приёмки:**
- [ ] `SettingsTabWidget` с `settings_profile_manager=None` создаётся без ошибок
- [ ] `SettingsTabWidget` с реальным `SettingsProfileManager` создаётся без ошибок
- [ ] `tab.profile_panel` возвращает `SettingsProfilePanelWidget` или `None`
- [ ] `profile_changed` сигнал доступен снаружи через `tab.profile_panel.profile_changed.connect(...)`
- [ ] `get_settings_profile_tab_ui()` возвращает `None` при отсутствии секции в config (не бросает)
- [ ] `ruff check` на изменённых файлах чистый

**Вне scope:** не менять фабрику вкладок внутри `tabs_config.py` (там id / title, не логика).
Не добавлять новую вкладку в `_default_tabs()` — профили живут внутри существующей вкладки
"Настройки". Не трогать Phase 1 widgets.

**Зависимости:** Task 2.4.

---

### Task 2.6 — Тесты L1: SettingsProfileModel + SettingsProfilePresenter без PyQt5

**Уровень:** Middle (Sonnet)
**Исполнитель:** tester
**Цель:** Покрыть unit-тестами `SettingsProfileModel`, `SettingsProfilePresenter` и
`SettingsProfileComboModel` — все тесты проходят без PyQt5.

**Контекст:**
Эталон — `tests/unit/test_recipes_register_presenter.py` и
`tests/unit/test_settings_profile_manager.py` из Phase 0/1. Структура: классы с pytest,
mock-объекты через `unittest.mock` или простые fake-классы. Нет `importorskip("PyQt5")`.

`FakeRM` (реализует duck-typed RegistersManager) и `FakeProfileManager` (реализует
`SettingsProfileManagerProtocol`) создаются внутри тестового файла.

**Файлы:**
- `multiprocess_prototype/tests/unit/test_settings_profile_combo_model.py` — создать
- `multiprocess_prototype/tests/unit/test_settings_profile_presenter.py` — создать

**Шаги:**

**test_settings_profile_combo_model.py:**
1. `TestFromProfileManager`:
   - `from_profile_manager(mock_with(["default","fast","prod"]))` → `model.slots == ["default","fast","prod"]`
   - `from_profile_manager(mock_with([]))` → `model.slots == ["default"]`
   - `label_fn("my_profile")` → `"my_profile"` (не "Слот my_profile")
2. `TestSyncCurrent`:
   - `sync_current(model, mock_manager_with_current("fast"))` → `model.current_index == index_of("fast")`
   - `sync_current(model, mock_manager_with_current("nonexistent"))` → fallback 0, нет исключения
3. `TestProfileIdFromModel`:
   - `profile_id_from_model(model)` → `str` (не int)

**test_settings_profile_presenter.py:**
4. Создать `FakeRM` с методами: `get_register(name)`, `model_dump_all()`, `set_field_value(reg, field, val)`,
   `get_field_metadata(reg)`. `set_field_value` возвращает `(True, None)`.
5. Создать `FakeProfileManager` реализующий `SettingsProfileManagerProtocol`:
   хранит `profiles: dict`, `current: str`, реальная логика switch (без SHM-проверок).
6. Создать `FakeView` реализующий `SettingsProfilePanelViewProtocol`.
7. `TestOnApplyClicked`:
   - успешное переключение → `fake_manager.switch_profile` вызван с правильным profile_id
   - после apply → `view.refresh_table_rows` вызван
8. `TestOnApplyWithShmBudgetError`:
   - `FakeProfileManager.switch_profile` поднимает `ShmBudgetError` → presenter вызывает
     `view.show_error(...)` и не пробрасывает исключение
9. `TestOnSaveClicked`:
   - `on_save_clicked()` → `fake_manager.save_profile_snapshot` вызван с данными из `FakeRM.model_dump_all()`
10. `TestOnDefaultClicked`:
    - `on_default_clicked()` → `switch_profile("default", ...)` вызван
11. `TestOnLeafValueChanged`:
    - валидное int-значение → `rm.set_field_value` вызван с правильным типом
    - невалидная строка → откат: `view.set_leaf_value_text` вызван со старым значением,
      `set_field_value` не вызван с новым значением

**Критерии приёмки:**
- [ ] Все тесты в двух файлах проходят без PyQt5 в venv
- [ ] `pytest tests/unit/test_settings_profile_*.py -v` — все green
- [ ] Нет `importorskip("PyQt5")` ни в одном файле
- [ ] `FakeRM`, `FakeProfileManager`, `FakeView` не требуют PyQt5
- [ ] `ruff check` чистый

**Вне scope:** не тестировать `SettingsProfilePanelWidget` (требует PyQt), не тестировать
YAML persistence (покрыто Phase 0 тестами).

**Зависимости:** Task 2.3.

---

### Task 2.7 — Integration-тест L2: переключение профиля обновляет RegistersManager

**Уровень:** Senior (teamlead, Opus)
**Исполнитель:** teamlead
**Цель:** Написать L2 integration-тест, который проверяет полную цепочку: переключение профиля
через presenter → `SettingsProfileManager.switch_profile` → `RegistersManager` отражает
значения из профиля; а также `profile_changed` сигнал не блокирует цепочку при ошибке.

**Контекст:**
Обязательный L2-тест из PR-чеклиста фазы (`prototype_v3_expansion.md`, Phase 2).
Используются реальные `SettingsProfileManager` + реальный `RegistersManager` из
`create_registers()`. Для presenter — реальный `SettingsProfilePresenter` с `FakeView`.
PyQt5 не нужен. Структура аналогична `test_settings_profile_switch.py` из Phase 0.

**Файлы:**
- `multiprocess_prototype/tests/integration/test_profile_switch_updates_registers.py` — создать
- `multiprocess_prototype/tests/integration/__init__.py` — создать если не существует

**Шаги:**
1. Создать `FakeView` реализующий `SettingsProfilePanelViewProtocol`:
   - `_current_id: str`; `current_profile_id()` → `self._current_id`
   - `errors: list[str]`; `show_error(msg)` → `self.errors.append(msg)`
   - `refresh_calls: int`; `refresh_table_rows()` → `self.refresh_calls += 1`
   - `leaf_texts: dict`; `set_leaf_value_text(g, f, t)` → `self.leaf_texts[(g, f)] = t`
2. `@pytest.fixture registers` — `create_registers()[0]` (реальный RegistersManager).
3. `@pytest.fixture yaml_path(tmp_path)` — путь для YAML.
4. `TestScenario_ProfileSwitch`:
   - Создать `SettingsProfileManager(yaml_path)`, `ensure_default_profile(registers)`
   - Сохранить профиль `"fast"` с `camera_count=4`
   - Собрать `SettingsProfileModel` + `SettingsProfilePresenter` + `FakeView(current_id="fast")`
   - Вызвать `presenter.on_apply_clicked()`
   - Assert: `registers.get_register(SETTINGS_REGISTER).camera_count == 4`
   - Assert: `fake_view.refresh_calls == 1`
5. `TestScenario_ShmBudgetErrorNoRegistersChange`:
   - Создать профиль с budget-превышением (camera_count=8, ring_buffer_size=3, shm_budget_mb=64)
   - Вызвать `presenter.on_apply_clicked()`
   - Assert: `fake_view.errors` непустой (сообщение об ошибке передано)
   - Assert: `registers.get_register(SETTINGS_REGISTER).camera_count` не изменился
6. `TestScenario_SaveCurrentRegistersToProfile`:
   - Применить "fast" через реальный `switch_profile`
   - Вызвать `presenter.on_save_clicked()` с view.current_profile_id = "fast"
   - Создать новый `SettingsProfileManager` с тем же yaml_path
   - Assert: `new_manager.get_profile_snapshot("fast")["camera_count"] == 4`
7. `TestScenario_DefaultRestoresRegisters`:
   - Переключить на "fast" (camera_count=4)
   - Вызвать `presenter.on_default_clicked()`
   - Assert: `registers.get_register(SETTINGS_REGISTER).camera_count == 1` (дефолт)

**Критерии приёмки:**
- [ ] `pytest tests/integration/test_profile_switch_updates_registers.py -v` — все 4 сценария green
- [ ] Тест запускается без PyQt5 в venv
- [ ] Использует `tmp_path` — нет зависимости от файловой системы проекта
- [ ] `ruff check` на тестовом файле чистый

**Вне scope:** не тестировать Qt-сигналы, не поднимать реальные процессы, не тестировать UI.

**Зависимости:** Task 2.3, Task 2.6.

---

## Порядок выполнения

```
Task 2.1 (схема конфига)
    └─→ Task 2.2 (combo model)
            └─→ Task 2.3 (model + presenter + view protocol)   ←── можно делать параллельно с 2.2
                    ├─→ Task 2.4 (Qt-виджет + сигнал)
                    │       └─→ Task 2.5 (интеграция в SettingsTabWidget)
                    ├─→ Task 2.6 (L1 unit-тесты)               ←── параллельно с 2.4
                    └─→ Task 2.7 (L2 integration-тест)         ←── после 2.6
```

## Риски и ограничения

- `BaseWidget` API (lifecycle `_create_model` / `_create_presenter` / `_init_ui` / `_connect_signals`
  / `_on_presenter_ready`) нужно изучить перед Task 2.4 — убедиться что flow тот же что в
  `AppRecipePanelWidget`. Файл: `frontend_module/widgets/base_widget.py`.
- `StructuredTwoLevelTreeWidget.set_data(groups)` — формат `groups` должен совпадать с тем
  что ожидает виджет. Проверить через `AppRecipePanelWidget.build_tree_groups()` возвращаемую
  структуру. Файл: `frontend_module/widgets/tables/structured_two_level_tree.py`.
- `SETTINGS_REGISTER` константа — импортируется из `multiprocess_prototype.registers.constants`.
  В `SettingsProfilePresenter.on_leaf_value_changed` group_id == `SETTINGS_REGISTER`.
- `model_dump_all()` у RegistersManager возвращает `{register_name: {field: value}}`.
  `save_profile_snapshot` ждёт `{field: value}` (плоский снимок одного регистра).
  Нужно извлечь `rm.model_dump_all().get(SETTINGS_REGISTER, {})` в `on_save_clicked`.
