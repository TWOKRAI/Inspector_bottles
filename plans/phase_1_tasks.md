---
status: planned
phase: 1
branch: feat/phase-1-recipes-table
base: master @ 17f66e9
created: 2026-04-21
---

# Phase 1 — Рецепты: улучшение таба

## Обзор

Phase 1 улучшает вкладку «Рецепты» в прототипе `multiprocess_prototype_v3`: заменяет поле ввода
слота на `QComboBox` с динамическим списком, добавляет auto-save с debounce и версионирование YAML,
а также добавляет полноценное покрытие тестами MVP-слоёв (model + presenter) без PyQt5.

Входная точка — уже работающая вкладка (`RecipesTabWidget` → `RegisterRecipePanelWidget`) с
паттерном MVP (`_recipe_panel_base.py`, `recipes_widget/{model,presenter,view}.py`).
Выходной критерий: редактирование ячейки → `rm.set_field_value` → IPC propagation; смена слота
через ComboBox загружает рецепт; auto-save срабатывает через debounce без потери данных.

**Merge-стратегия:** squash → `master`.

**PR-чеклист:**
- `ruff check + ruff format` — зелёный
- `python Inspector_prototype/scripts/validate.py` — pass
- `python Inspector_prototype/scripts/run_framework_tests.py` — pass
- Все новые L1 unit-тесты проходят без PyQt5
- Минимум 1 L2 integration-тест (ячейка → регистр → IPC)
- Обновлены `README.md` в затронутых виджетах

---

### Task 1.1 — SlotComboBoxModel: модель списка слотов

**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Создать чистую Python-модель `RecipeSlotComboModel`, которая хранит список доступных
слотов и текущий выбранный индекс, без каких-либо зависимостей от PyQt5.

**Контекст:**
Сейчас номер слота вводится вручную в `QLineEdit` (`_recipe_panel_base.py`, поле `_slot`).
Переход на `QComboBox` требует модели, которая: знает список слотов (берёт их из
`recipe_manager.list_slots()` или генерирует диапазон `[index_min..index_max]`), умеет
конвертировать combo-индекс в идентификатор слота (строку), а строку слота обратно в combo-индекс.
Модель должна быть тестируема без PyQt5.

**Файлы:**
- `Inspector_prototype/multiprocess_prototype_v3/frontend/widgets/recipes_widget/slot_combo_model.py` — создать
- `Inspector_prototype/multiprocess_prototype_v3/frontend/widgets/recipes_widget/__init__.py` — добавить экспорт

**Шаги:**
1. Создать dataclass `RecipeSlotComboModel` с полями:
   `slots: List[str]` (список идентификаторов), `current_index: int` (0-based combo-индекс).
2. Добавить classmethod `from_manager(recipe_manager, index_min, index_max) -> RecipeSlotComboModel`:
   если `recipe_manager` имеет `list_slots()` и список непустой — использовать его;
   иначе сгенерировать `[str(i) for i in range(index_min, index_max + 1)]`.
3. Добавить метод `slot_id_for_index(combo_idx: int) -> str` — возвращает `slots[combo_idx]`
   с защитой от выхода за границы (fallback → `slots[0]`).
4. Добавить метод `index_for_slot_id(slot_id: str) -> int` — ищет слот по строке,
   fallback → 0 при отсутствии.
5. Добавить метод `current_slot_id() -> str` — `slot_id_for_index(self.current_index)`.
6. Добавить `labels: List[str]` — читаемые метки для ComboBox (`f"Слот {s}"` по умолчанию,
   кастомизируемые через `label_fn: Optional[Callable[[str], str]]`).

**Критерии приёмки:**
- [ ] `from_manager(None, 0, 5)` возвращает slots `["0","1","2","3","4","5"]`
- [ ] `from_manager(mock_mgr_with_slots(["A","B","C"]), 0, 5)` возвращает slots `["A","B","C"]`
- [ ] `index_for_slot_id("B")` → `1` для списка `["A","B","C"]`
- [ ] `slot_id_for_index(999)` не бросает исключение
- [ ] Файл импортируется без PyQt5 в окружении
- [ ] `ruff check` на новом файле чистый

**Вне scope:** никакого Qt-кода, никакой привязки к `RecipesTabConfig`, никакой логики
сохранения/загрузки YAML.

**Зависимости:** нет (Task 1.1 первая в цепочке).

---

### Task 1.2 — SlotComboBox: замена QLineEdit → QComboBox в RecipePanelBase

**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Заменить `QLineEdit` слота на `QComboBox` в `RecipePanelBase._init_ui()`, подключив
`RecipeSlotComboModel` как источник данных и синхронизируя текущий индекс с презентером.

**Контекст:**
`_recipe_panel_base.py` содержит `_init_ui()`, где создаётся `QLineEdit self._slot` и метод
`parse_slot()` использует `parse_clamped_recipe_slot_text`. При переходе на ComboBox нужно:
сохранить публичный API `parse_slot() -> int`, заменить внутреннее поле `_slot: QLineEdit` на
`_slot_combo: QComboBox`, заполнить его из `RecipeSlotComboModel`, обновить инициализацию
начального слота. При этом логика presenter'а (`on_load_clicked`, `on_save_clicked`) должна
остаться неизменной — она вызывает `view.parse_slot()`.

**Файлы:**
- `Inspector_prototype/multiprocess_prototype_v3/frontend/widgets/_recipe_panel_base.py` — изменить
- `Inspector_prototype/multiprocess_prototype_v3/frontend/widgets/recipes_widget/slot_combo_model.py` — использовать (Task 1.1)

**Шаги:**
1. В `RecipePanelBase` добавить поле `_slot_combo_model: Optional[RecipeSlotComboModel] = None`.
2. В `_init_ui()` заменить блок с `QLineEdit` на `QComboBox`:
   - построить `RecipeSlotComboModel.from_manager(recipe_manager, index_min, index_max)` и
     сохранить в `self._slot_combo_model`;
   - создать `self._slot_combo = QComboBox()` и наполнить его `addItems(model.labels)`;
   - установить текущий индекс: `model.index_for_slot_id(str(initial_slot))`.
3. Переписать `parse_slot() -> int`:
   - взять `combo_idx = self._slot_combo.currentIndex()`;
   - вернуть `int(self._slot_combo_model.slot_id_for_index(combo_idx))` с fallback на `index_min`
     при `ValueError`.
4. Удалить вызов `bind_touch_keyboard_line_edit` для слота (или сохранить только для touch_keyboard_tree).
5. Подключить `self._slot_combo.currentIndexChanged` к методу `_on_slot_index_changed(index: int)`
   который обновляет `self._slot_combo_model.current_index = index`.
6. Проверить обратную совместимость: `RegisterRecipePanelWidget` и `AppRecipePanelWidget` не
   должны требовать изменений — они наследуют базу.

**Критерии приёмки:**
- [ ] `RecipesTabWidget` создаётся без ошибок с `registers_manager=None` (placeholder-ветка)
- [ ] `RecipePanelBase` не импортирует PyQt5 напрямую (только через `frontend_module.core.qt_imports`)
- [ ] `parse_slot()` возвращает корректный `int` для любого состояния комбо
- [ ] `ruff check` чистый на изменённом файле

**Вне scope:** auto-save, debounce, версионирование YAML — это Task 1.3. Не менять логику
presenter'ов (`RegisterRecipePresenter`, `AppRecipePresenter`).

**Зависимости:** Task 1.1.

---

### Task 1.3 — AutoSaveDebounce: debounce-сохранение + версионирование YAML

**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Реализовать `RecipeAutoSave` — компонент debounce-записи рецепта в YAML с
автоматическим ротационным версионированием файлов слотов, не зависящий от PyQt5.

**Контекст:**
Сейчас сохранение рецепта происходит только при явном нажатии «Сохранить». Необходимо добавить
auto-save: при каждом изменении ячейки через некоторый интервал (по умолчанию 1.5 с) автоматически
записывать текущее состояние регистров в YAML-слот. Версионирование: перед перезаписью сохранять
предыдущую версию как `<slot_id>.v<N>.yaml` в подпапке `versions/` (держать не более `max_versions`
файлов, удалять старые).

Компонент должен быть тестируемым без PyQt5: debounce-таймер реализуется через `threading.Timer`
или через инжектируемую `clock`-функцию (не `QTimer`). Привязка `QTimer` к виджету — в отдельном
thin-адаптере (Task 1.4).

**Файлы:**
- `Inspector_prototype/multiprocess_prototype_v3/frontend/widgets/recipes_widget/auto_save.py` — создать
- `Inspector_prototype/multiprocess_prototype_v3/frontend/widgets/recipes_widget/__init__.py` — добавить экспорт

**Шаги:**
1. Создать dataclass `AutoSaveConfig` с полями:
   `debounce_sec: float = 1.5`, `max_versions: int = 5`, `versions_subdir: str = "versions"`.
2. Создать класс `RecipeAutoSave`:
   - конструктор `__init__(self, recipe_manager, slot_getter: Callable[[], str], rm_snapshot_fn: Callable[[], Dict[str, Any]], config: AutoSaveConfig = ...)`;
   - `slot_getter` — функция возвращающая текущий slot_id (из модели комбо);
   - `rm_snapshot_fn` — функция возвращающая снимок `{register_name: model_dump()}` для записи.
3. Реализовать метод `schedule()`: отменить предыдущий отложенный вызов (если есть), создать новый
   `threading.Timer(debounce_sec, self._do_save)`.
4. Реализовать `_do_save()`:
   - получить `slot_id = slot_getter()`;
   - получить `snapshot = rm_snapshot_fn()`;
   - вызвать `_rotate_versions(slot_id)` — скопировать текущий YAML в `versions/<slot>.v<N>.yaml`,
     удалить лишние (старше `max_versions`);
   - вызвать `recipe_manager.save_slot(slot_id, snapshot)`.
5. Реализовать `_rotate_versions(slot_id: str)`: через `pathlib`, работать с директорией рядом с
   файлом рецепта (получить путь через `getattr(recipe_manager, "_data_path", None)`).
6. Реализовать `cancel()`: отменяет pending timer если он активен.

**Критерии приёмки:**
- [ ] `schedule()` + `_do_save()` вызываются без PyQt5 в unit-тесте с mock `recipe_manager`
- [ ] Повторный `schedule()` в течение debounce_sec отменяет предыдущий (только одна запись)
- [ ] После `_do_save()` в `versions/` появляется файл `<slot>.v1.yaml` (тест с `tmp_path`)
- [ ] При `max_versions=2` старые версии удаляются, в папке не более 2 файлов
- [ ] `cancel()` предотвращает запись после вызова
- [ ] `ruff check` на новом файле чистый

**Вне scope:** `QTimer`, любой Qt-код. Не интегрировать в виджет — это Task 1.4.

**Зависимости:** нет прямых (независимый компонент). Логически после Task 1.2.

---

### Task 1.4 — Интеграция ComboBox + AutoSave в RecipePanelBase

**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Подключить `RecipeAutoSave` к `RecipePanelBase` через тонкий Qt-адаптер (`QTimer`),
а смену слота в ComboBox — к загрузке рецепта через presenter.

**Контекст:**
После Tasks 1.1–1.3 ComboBox и AutoSave существуют как отдельные компоненты. Нужно:
(а) При смене индекса ComboBox вызывать `presenter.on_load_clicked()` (загружать рецепт слота).
(б) При изменении любой ячейки (`leaf_cell_changed`) вызывать `auto_save.schedule()`.
(в) Debounce-таймер в Qt-контексте реализовать через `QTimer.singleShot` — тонкий адаптер
    `QtDebounceAdapter` в `_recipe_panel_base.py`, который при вызове `schedule()` вызывает
    `QTimer.singleShot(delay_ms, callback)` и отменяет предыдущий через `QTimer` + флаг.

**Файлы:**
- `Inspector_prototype/multiprocess_prototype_v3/frontend/widgets/_recipe_panel_base.py` — изменить
- `Inspector_prototype/multiprocess_prototype_v3/frontend/widgets/recipes_widget/auto_save.py` — добавить `QtDebounceAdapter`

**Шаги:**
1. В `auto_save.py` создать `QtDebounceAdapter` — класс с методом `schedule(delay_ms, callback)`:
   отменяет предыдущий `QTimer` (через флаг `_cancelled`), создаёт новый `QTimer.singleShot`.
   Этот класс импортирует `QTimer` через `frontend_module.core.qt_imports`.
2. В `RecipePanelBase._init_ui()` создать `RecipeAutoSave` + `QtDebounceAdapter` если
   `recipe_manager is not None`:
   - `slot_getter` = лямбда `lambda: self._slot_combo_model.current_slot_id()`;
   - `rm_snapshot_fn` = лямбда из модели presenter'а;
   - сохранить как `self._auto_save: Optional[RecipeAutoSave]`.
3. В `_on_slot_index_changed(index)` вызвать `presenter.on_load_clicked()` после обновления
   `current_index` модели (только если `recipe_manager is not None`).
4. В `_on_leaf_value_changed_slot()` после вызова `self._presenter.on_leaf_value_changed(...)`
   вызвать `self._auto_save.schedule()` если `self._auto_save is not None`.
5. В деструкторе (`closeEvent` или `__del__`) вызвать `self._auto_save.cancel()` если задан.
6. Убедиться что при `recipe_manager=None` auto-save не создаётся и смена слота только обновляет
   `_slot_combo_model.current_index` без вызова presenter.

**Критерии приёмки:**
- [ ] При смене combo-индекса с реальным `recipe_manager` вызывается `presenter.on_load_clicked`
- [ ] Правка ячейки планирует auto-save через debounce (проверяется mock auto_save)
- [ ] При `recipe_manager=None` смена комбо не бросает исключений
- [ ] `ruff check` чистый на изменённых файлах

**Вне scope:** не менять `RegisterRecipePanelWidget` и `AppRecipePanelWidget` напрямую. Не
добавлять версионирование в `RecipeManager` (он уже есть — `save_slot`). Не трогать IPC-слой.

**Зависимости:** Task 1.2, Task 1.3.

---

### Task 1.5 — Тесты L1: presenter + модель без PyQt5

**Уровень:** Middle (Sonnet)
**Исполнитель:** tester
**Цель:** Покрыть unit-тестами `RegisterRecipePresenter`, `RecipeSlotComboModel` и
`RecipeAutoSave` — все тесты должны проходить без PyQt5.

**Контекст:**
В venv PyQt5 отсутствует (установлен PyQt6), поэтому тесты виджетов пропускаются через
`pytest.importorskip("PyQt5")`. Логика presenter'а и моделей — уже отделена от Qt (паттерн MVP).
Нужно добавить тесты без `importorskip`, покрыв ключевые пути.

Эталон для структуры тестов — `tests/unit/test_frontend_integration_settings.py` (Phase 0):
чистые pytest-классы, без PyQt5, с mock-объектами.

**Файлы:**
- `Inspector_prototype/multiprocess_prototype_v3/tests/unit/test_recipes_slot_combo_model.py` — создать
- `Inspector_prototype/multiprocess_prototype_v3/tests/unit/test_recipes_auto_save.py` — создать
- `Inspector_prototype/multiprocess_prototype_v3/tests/unit/test_recipes_register_presenter.py` — создать

**Шаги:**
1. `test_recipes_slot_combo_model.py`:
   - `TestFromManager`: `from_manager(None, 0, 3)` → slots `["0","1","2","3"]`; с mock_manager
     возвращающим `["A","B"]` → slots `["A","B"]`.
   - `TestIndexConversion`: `index_for_slot_id` на существующий и отсутствующий слот; `slot_id_for_index`
     с выходом за границы.
2. `test_recipes_auto_save.py`:
   - Создать `FakeRecipeManager(tmp_path)` с `save_slot`, `_data_path`, `list_slots`.
   - `TestScheduleAndSave`: `schedule()` + `time.sleep(2.0)` → файл записан; двойной `schedule()`
     в интервале debounce → только 1 запись.
   - `TestVersioning`: после 3 вызовов `_do_save()` (прямо, без таймера) с `max_versions=2`
     папка `versions/` содержит не более 2 файлов.
   - `TestCancel`: `schedule()` + немедленный `cancel()` → файл не записан.
3. `test_recipes_register_presenter.py`:
   - Создать `FakeRM` с `set_field_value`, `get_register`, `register_names`, `get_field_metadata`.
   - `TestOnLeafValueChanged`: строка → `rm.set_field_value` вызван с правильным типом.
   - `TestOnLoadClicked`: мок `recipe_manager.load_recipe_to_registers` вызван и `refresh_table_rows` вызван.
   - `TestOnSaveClicked`: `save_registers_to_recipe` вызван с текущим slot_id.
   - `TestInitialSlot`: `compute_initial_slot` возвращает значение из `recipe_manager` если есть.

**Критерии приёмки:**
- [ ] Все тесты в трёх файлах проходят без `PyQt5` в venv
- [ ] `pytest Inspector_prototype/multiprocess_prototype_v3/tests/unit/test_recipes_*.py -v` — все green
- [ ] Нет `importorskip("PyQt5")` ни в одном из этих трёх файлов
- [ ] Coverage presenter ≥ 80% ветвей (оценочно по структуре тестов)

**Вне scope:** не тестировать виджеты (`RecipePanelBase`, `RegisterRecipePanelWidget`) — они
требуют PyQt5. Не тестировать IPC-слой (это L2, Task 1.6).

**Зависимости:** Task 1.1, Task 1.3. Можно делать параллельно с Task 1.4.

---

### Task 1.6 — Integration-тест L2: ячейка → регистр → IPC propagation

**Уровень:** Senior (teamlead, Opus)
**Исполнитель:** teamlead
**Цель:** Написать один integration-тест, который проверяет полную цепочку: редактирование
ячейки через presenter → `rm.set_field_value` → значение отражается в RegistersManager и уходит
в IPC (mock-шина или `RouterManager` stub), а также что переключение слота через ComboBox
загружает корректные значения регистров.

**Контекст:**
Это обязательный L2-тест из PR-чеклиста мета-плана (`prototype_v3_expansion.md`, Phase 1).
Тест не использует PyQt5. Для имитации RegistersManager использовать реальный
`RegistersManager` из `registers_module` с тестовыми регистрами (или lightweight stub).
IPC propagation проверяется через мок `RouterManager.send` или перехват `set_field_value`-callback.

Паттерн для структуры теста — аналог `test_frontend_integration_settings.py`, но глубже:
работает с реальным `RegisterRecipePresenter` + реальным `RecipeAutoSave` + FakeRM.

**Файлы:**
- `Inspector_prototype/multiprocess_prototype_v3/tests/integration/test_recipe_cell_to_register.py` — создать
- `Inspector_prototype/multiprocess_prototype_v3/tests/integration/__init__.py` — создать если не существует

**Шаги:**
1. Создать минимальный `FakeRegisterSchema(SchemaBase)` с 2-3 полями через `FieldMeta`
   (int + float + str) — чтобы не зависеть от производственных регистров.
2. Создать `FakeRM` — реализует `IRegistersManagerGui`: `set_field_value`, `get_register`,
   `register_names`, `get_field_metadata`; при `set_field_value` записывает в словарь и
   добавляет вызов в `calls: list`.
3. Создать `FakeRecipeManager(tmp_path)` — реализует `RecipeManagerProtocol` с реальными YAML.
4. `TestCellToRegister`:
   - Сценарий "редактирование int-поля": создать `RegisterRecipePresenter(view=fake_view, model=model)`,
     вызвать `on_leaf_value_changed(group_id, field_id, "value", "42")`, проверить что
     `FakeRM.calls` содержит `set_field_value(register_name, field_name, 42)` (тип int, не строка).
   - Сценарий "откат при невалидном значении": передать строку вместо int → `set_field_value`
     не вызван с новым значением, `view.set_leaf_value_text` вызван со старым значением.
5. `TestSlotSwitchLoadsRecipe`:
   - Записать слот "1" через `FakeRecipeManager.save_slot("1", {...})` с конкретными значениями.
   - Вызвать `presenter._apply_load_slot(1)`.
   - Проверить что `FakeRM.last_set_calls` содержат ожидаемые значения из слота.
6. Проверить отдельным assert: `presenter.initial_slot()` возвращает текущий слот из
   `recipe_manager.get_current_register_recipe_number()`.

**Критерии приёмки:**
- [ ] Тест запускается без PyQt5: `pytest tests/integration/test_recipe_cell_to_register.py -v`
- [ ] Все 3 сценария (int-редактирование, откат, slot-switch) проходят
- [ ] Тест не зависит от файловой системы проекта (использует `tmp_path`)
- [ ] `ruff check` на тестовом файле чистый

**Вне scope:** не тестировать виджеты, не поднимать реальные процессы, не тестировать YAML
debounce (покрыто Task 1.5).

**Зависимости:** Task 1.5 (структуры FakeRM и FakeRecipeManager можно переиспользовать).
