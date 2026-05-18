# Plan: Доводка ComboControl до эталонного паттерна

- **Slug:** `combo-finish`
- **Дата:** 2026-05-18
- **Статус:** DONE
- **Ветка:** `refactor/frontend-widgets-cleanup` (выполнено как часть общего фронт-рефакторинга, не отдельной веткой)

## Обзор

`ComboControl` функционально готов (presenter, view, facade, 2 test-файла), но не соответствует эталону `CheckboxControl` по структуре пакета: отсутствуют `defaults.py`, `registers.py`, `README.md`, пример `_examples/combo/`, реэкспорт из верхнего `components/__init__.py`, и упоминание combo в документации компонентов.

Цель — закрыть все пробелы без изменения бизнес-логики: после выполнения плана `combo/` является полноценным референс-компонентом наравне с `checkbox/`.

Слой: **framework** (`multiprocess_framework/modules/frontend_module/`).

---

## Сводная таблица задач

| # | Задача | Assignee | Зависимости |
|---|--------|----------|-------------|
| 1.1 | `combo/defaults.py` | developer | — |
| 1.2 | `combo/registers.py` | developer | — |
| 1.3 | `combo/__init__.py` обновить | developer | 1.1, 1.2 |
| 1.4 | `_examples/combo/` создать | developer | — |
| 1.5 | `_examples/__init__.py` реэкспорт | developer | 1.4 |
| 1.6 | `components/__init__.py` реэкспорт | developer | 1.1, 1.2, 1.3 |
| 1.7 | `combo/README.md` | developer | 1.1, 1.2 |
| 1.8 | `components/README.md` + `ARCHITECTURE.md` | developer | 1.7 |
| 1.9 | Тест `ComboRegister` | developer | 1.2 |

---

## Чек-лист acceptance criteria (верхний уровень)

- [x] Создан `combo/defaults.py` с минимум одним осмысленным дефолтом.
- [x] Создан `combo/registers.py` с `ComboRegister(RegisterDescriptor)`.
- [x] `combo/__init__.py` экспортирует `ComboRegister` и `combo_default`.
- [x] Создан подпакет `_examples/combo/` (`__init__.py`, `schemas.py`, `adapter.py`).
- [x] `_examples/__init__.py` реэкспортирует Combo-сущности.
- [x] `components/__init__.py` реэкспортирует `ComboControl, ComboControlResult, ComboPresenter, ComboView, ComboViewConfig`.
- [x] Создан `combo/README.md` с mermaid-диаграммами и разделами по образцу `checkbox/README.md`.
- [x] `components/README.md` обновлён: дерево папок, таблица, mermaid.
- [x] `components/ARCHITECTURE.md` — проверено, упоминаний combo как «будущего» нет, изменений не требовалось.
- [x] Существующие тесты `test_combo_v2.py` и `test_combo_form_ctx.py` не сломаны.
- [x] Добавлен тест на `ComboRegister` (instantiation + `widget` / `python_type` атрибуты).

---

## Порядок выполнения

### Phase 1: Дополнение пакета combo/

---

### Task 1.1 — `combo/defaults.py`: готовые экземпляры ComboViewConfig

**Level:** Junior (Haiku)
**Assignee:** docs-writer
**Goal:** Создать файл `combo/defaults.py` с двумя осмысленными готовыми конфигами на основе реальных use-cases в `factory.py`.
**Context:** В `factory.py` ComboControl вызывается с `ComboViewConfig(label=field_info.title)` (без `items`) — т.е. items берутся из Literal-типа поля. Самый частый сценарий — combo без placeholder (просто список items) и combo с placeholder (необязательный выбор). Именно эти два варианта нужны как дефолты. Аналог — `checkbox/defaults.py` с `checkbox_left` и `checkbox_right`.

**Files:**
- `multiprocess_framework/modules/frontend_module/components/combo/defaults.py` — создать

**Steps:**
1. Импортировать `ComboViewConfig` из `combo.config`.
2. Создать `combo_default = ComboViewConfig()` — пустой конфиг, items приходят извне (наиболее частый случай в `factory.py`).
3. Создать `combo_with_placeholder = ComboViewConfig(placeholder="— выберите —")` — combo с строкой подсказки при пустом выборе.
4. Добавить docstring-модуль с описанием назначения файла (по образцу `checkbox/defaults.py`).

**Acceptance criteria:**
- [x] Файл создан, импортируется без ошибок: `from ...combo.defaults import combo_default, combo_with_placeholder`.
- [x] `combo_default.placeholder == ""`.
- [x] `combo_with_placeholder.placeholder == "— выберите —"`.

**Out of scope:** Не добавлять дефолты с явными `items` (они всегда контекстозависимы).
**Edge cases:** Нет.
**Dependencies:** —

---

### Task 1.2 — `combo/registers.py`: RegisterDescriptor для строковых полей

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Создать `combo/registers.py` с `ComboRegister(RegisterDescriptor)` по образцу `slider/registers.py`.
**Context:** `SliderRegister` — минималистичный дескриптор (`python_type = int`, `widget = "slider"`). Аналогичный `ComboRegister` нужен для строковых полей с `Literal[...]`-типом или просто `str`, где виджет = "combo". Дескриптор используется плагинами при объявлении схем регистров в Django-style через `DescriptorSchemaMeta`.

**Files:**
- `multiprocess_framework/modules/frontend_module/components/combo/registers.py` — создать

**Steps:**
1. Импортировать `RegisterDescriptor` из `multiprocess_framework.modules.data_schema_module`.
2. Объявить `class ComboRegister(RegisterDescriptor): python_type = str; widget = "combo"`.
3. Добавить docstring с примером использования (как в `slider/registers.py`): класс со схемой регистра и полем `mode = ComboRegister(name="Режим", default="auto")`.

**Acceptance criteria:**
- [x] `ComboRegister.python_type is str`.
- [x] `ComboRegister.widget == "combo"`.
- [x] Импортируется: `from ...combo.registers import ComboRegister`.

**Out of scope:** Не реализовывать сериализацию, валидацию Literal-аргументов или любую логику — только класс-дескриптор.
**Edge cases:** `RegisterDescriptor` может иметь обязательные параметры — проверить по `slider/registers.py`, не добавлять лишних атрибутов.
**Dependencies:** —

---

### Task 1.3 — `combo/__init__.py`: дополнить экспорт

**Level:** Junior (Haiku)
**Assignee:** docs-writer
**Goal:** Дополнить `combo/__init__.py` экспортом `ComboRegister`, `combo_default`, `combo_with_placeholder`.
**Context:** Текущий `__init__.py` экспортирует только `ComboViewConfig, ComboView, ComboPresenter, ComboControl, ComboControlResult`. После создания `defaults.py` и `registers.py` нужно добавить новые имена в импорты и `__all__`, а также обновить docstring по образцу `checkbox/__init__.py`.

**Files:**
- `multiprocess_framework/modules/frontend_module/components/combo/__init__.py` — изменить

**Steps:**
1. Прочитать текущий `combo/__init__.py`.
2. Добавить импорт `combo_default, combo_with_placeholder` из `combo.defaults`.
3. Добавить импорт `ComboRegister` из `combo.registers`.
4. Расширить `__all__` новыми именами: `"ComboRegister"`, `"combo_default"`, `"combo_with_placeholder"`.
5. Обновить docstring: упомянуть, что `ComboRegister` живёт в `registers.py`, документация в `README.md`.

**Acceptance criteria:**
- [x] `from ...combo import ComboRegister, combo_default, combo_with_placeholder` работает без ошибок.
- [x] `__all__` содержит все 8 публичных имён.

**Out of scope:** Не трогать логику view/presenter/facade.
**Edge cases:** —
**Dependencies:** Task 1.1, Task 1.2

---

### Phase 2: Пример _examples/combo/

---

### Task 1.4 — `_examples/combo/`: создать подпакет примера

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать `_examples/combo/` с тремя файлами (`schemas.py`, `adapter.py`, `__init__.py`) по точному образцу `_examples/checkbox/`.
**Context:** Каждый пример (`_examples/X/`) состоит из: `schemas.py` (регистр значения + UI-конфиг как `SchemaBase`, `BINDING_*` на классе, `EXAMPLE_X_ROUTING`), `adapter.py` (конвертеры схем → BindingConfig / ViewConfig, `coerce_ui`, `create_example_X`), `__init__.py` (реэкспорт всех публичных имён). Combo-специфика: поле регистра типа `Literal["auto", "manual", "off"]`, UI-конфиг содержит `combo_label`, `combo_tooltip`, `combo_placeholder`. Реальный use-case из `factory.py` — binding к Literal-полю, items из Literal-аргументов.

**Files:**
- `multiprocess_framework/modules/frontend_module/components/_examples/combo/__init__.py` — создать
- `multiprocess_framework/modules/frontend_module/components/_examples/combo/schemas.py` — создать
- `multiprocess_framework/modules/frontend_module/components/_examples/combo/adapter.py` — создать

**Steps:**

**schemas.py:**
1. Объявить `EXAMPLE_COMBO_ROUTING = FieldRouting(channel="control_example")`.
2. Объявить `ExampleComboValueRegister(SchemaBase)` с декоратором `@register_schema("ExampleComboValueRegister")`:
   - `BINDING_REGISTER: ClassVar[str] = "example_data_schema_combo"`.
   - `BINDING_FIELD: ClassVar[str] = "mode"`.
   - `register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(process_targets=("example",))`.
   - Поле `mode: Annotated[Literal["auto", "manual", "off"], FieldMeta("Режим работы", info="...", routing=EXAMPLE_COMBO_ROUTING)] = "auto"`.
3. Объявить `ExampleComboUiConfig(SchemaBase)` с декоратором `@register_schema("ExampleComboUiConfig")`:
   - `combo_label: Annotated[str, FieldMeta("Подпись")] = ""`.
   - `combo_tooltip: Annotated[str, FieldMeta("Подсказка")] = ""`.
   - `combo_placeholder: Annotated[str, FieldMeta("Placeholder")] = ""`.
   - `combo_widget_enabled: Annotated[bool, FieldMeta("Виджет доступен")] = True`.

**adapter.py:**
1. Функция `combo_binding(access_level=0) -> BindingConfig` — из `BINDING_*` на `ExampleComboValueRegister`.
2. Функция `combo_view_config_from_ui(ui: ExampleComboUiConfig) -> ComboViewConfig` — маппинг полей; пустые label/tooltip → `None`/`""` (берутся из `FieldMeta`).
3. Функция `coerce_ui(ui: None | dict | ExampleComboUiConfig) -> ExampleComboUiConfig` — три ветки: None / экземпляр / dict (через `model_validate`).
4. Функция `create_example_combo(registers_manager, ui=None, *, access_level=0) -> ComboControlResult` — вызывает `ComboControl.create` с `combo_binding(access_level)`, `combo_view_config_from_ui(coerce_ui(ui))`, `items=["auto", "manual", "off"]`, `current_access_level=access_level`. **Без `form_ctx`** — пример, не production.

**__init__.py:**
5. Реэкспортировать все публичные имена: `EXAMPLE_COMBO_ROUTING`, `ExampleComboValueRegister`, `ExampleComboUiConfig`, `combo_binding`, `combo_view_config_from_ui`, `coerce_ui`, `create_example_combo`.
6. `__all__` — явный список.

**Acceptance criteria:**
- [x] `from ...components._examples.combo import create_example_combo, ExampleComboValueRegister` импортируется без ошибок.
- [x] `coerce_ui(None)` возвращает `ExampleComboUiConfig()` без ошибки.
- [x] `combo_binding()` возвращает `BindingConfig(register_name="example_data_schema_combo", field_name="mode")`.
- [x] `combo_view_config_from_ui(ExampleComboUiConfig(combo_label="Тест"))` возвращает `ComboViewConfig` с `label="Тест"`.

**Out of scope:** Не интегрировать в реальный RegistersManager, не писать Qt-тесты.
**Edge cases:** `coerce_ui({"combo_label": "X"})` должен работать через `model_validate`. Пустой `combo_label` (после strip) → `None` (не переопределяет `FieldMeta.label`).
**Dependencies:** —

---

### Task 1.5 — `_examples/__init__.py`: добавить Combo-реэкспорт

**Level:** Junior (Haiku)
**Assignee:** docs-writer
**Goal:** Добавить импорт и реэкспорт Combo-сущностей из `_examples/__init__.py` по образцу checkbox-блока.
**Context:** Текущий `_examples/__init__.py` реэкспортирует checkbox, compound_mixed, compound_numeric, group, label, numeric, slider, spinbox — 8 подпакетов. Combo нужно добавить девятым блоком.

**Files:**
- `multiprocess_framework/modules/frontend_module/components/_examples/__init__.py` — изменить

**Steps:**
1. Прочитать текущий `_examples/__init__.py`.
2. Добавить импорт-блок (после spinbox): `from ...combo import (EXAMPLE_COMBO_ROUTING, ExampleComboValueRegister, ExampleComboUiConfig, coerce_ui as combo_coerce_ui, combo_binding, combo_view_config_from_ui, create_example_combo)`.
3. Расширить `__all__` новыми именами: `"EXAMPLE_COMBO_ROUTING"`, `"ExampleComboValueRegister"`, `"ExampleComboUiConfig"`, `"combo_binding"`, `"combo_coerce_ui"`, `"combo_view_config_from_ui"`, `"create_example_combo"`.

**Acceptance criteria:**
- [x] `from ...components._examples import create_example_combo` работает.
- [x] Все существующие имена в `__all__` сохранены.

**Out of scope:** Не менять порядок существующих блоков.
**Dependencies:** Task 1.4

---

### Phase 3: Реэкспорт из верхнего components/

---

### Task 1.6 — `components/__init__.py`: добавить Combo в верхний реэкспорт

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Добавить `ComboControl, ComboControlResult, ComboPresenter, ComboView, ComboViewConfig, ComboRegister, combo_default, combo_with_placeholder` в `components/__init__.py`.
**Context:** Сейчас `factory.py` использует `from ...combo import ComboControl, ComboViewConfig` — полный путь. После этой задачи canonical импорт станет `from frontend_module.components import ComboControl, ComboViewConfig`. Существующий код в `factory.py` менять не нужно — это отдельная задача за пределами плана; главное — экспорт появится.

**Files:**
- `multiprocess_framework/modules/frontend_module/components/__init__.py` — изменить

**Steps:**
1. Прочитать текущий `components/__init__.py`.
2. Добавить import-блок после `checkbox`:
   ```
   from multiprocess_framework.modules.frontend_module.components.combo import (
       ComboControl,
       ComboControlResult,
       ComboPresenter,
       ComboView,
       ComboViewConfig,
       ComboRegister,
       combo_default,
       combo_with_placeholder,
   )
   ```
3. Добавить все 8 имён в `__all__`.

**Acceptance criteria:**
- [x] `from frontend_module.components import ComboControl` работает.
- [x] `from frontend_module.components import ComboRegister` работает.
- [x] `from frontend_module.components import combo_default` работает.
- [x] Все существующие публичные имена в `__all__` сохранены (регрессия недопустима).

**Out of scope:** Не менять `factory.py` — это отдельная задача.
**Edge cases:** Проверить, что новые импорты не создают циклических зависимостей (combo не импортирует из components/).
**Dependencies:** Task 1.3

---

### Phase 4: Документация

---

### Task 1.7 — `combo/README.md`: создать по образцу `checkbox/README.md`

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Создать `combo/README.md` с теми же разделами, что у `checkbox/README.md`, адаптированными для ComboControl.
**Context:** Структура `checkbox/README.md`: заголовок, раздел «Слои» (flowchart), «Поток значения» (sequenceDiagram), «Binding-aware mode (form_ctx)» (sequenceDiagram), «Отличия», «Пример», «Тесты». Для combo — те же разделы, с поправкой на str-значения и `set_items`.

**Files:**
- `multiprocess_framework/modules/frontend_module/components/combo/README.md` — создать

**Steps:**
1. Раздел **заголовок и краткое описание**: `ComboControl v2` — выпадающий список с привязкой к регистру. Те же порты, что у checkbox. `set_items` — дополнительный метод `ComboView` для передачи вариантов.
2. Раздел **«Слои»** — `flowchart LR` с узлами `ComboControl.create`, `ComboView`, `ComboPresenter`, `SchemaTrait + SyncTrait + AccessTrait`, `RegisterAdapter`.
3. Раздел **«Поток значения»** — `sequenceDiagram` аналогично checkbox: User → ComboView (смена выбора) → ComboPresenter (`_on_changed`) → SyncTrait (`write`) → RegisterAdapter → subscribe callback → `set_value_silent`.
4. Раздел **«Binding-aware mode (form_ctx)»** — `sequenceDiagram` аналогично checkbox, но путь через `ComboPresenter._on_changed` → `FormContext.write` → `ActionBus` → `FieldSetHandler` → `RegistersManager` → subscribe callback → `set_value_silent`. Тот же текст про undo.
5. Раздел **«Отличия от числового контрола»**: нет DebounceTrait; `on_finished` — no-op; items передаются через `ComboControl.create(..., items=[...])` или `ComboViewConfig.items`; str-кастование при `_on_external_change`.
6. Раздел **«Пример»** — code block с `ComboControl.create(rm, BindingConfig(...), ComboViewConfig(), items=["auto", "manual", "off"])`.
7. Раздел **«Тесты»** — ссылки на `test_combo_v2.py`, `test_combo_form_ctx.py`, упоминание `test_form_context_integration.py` если в нём есть combo-тест (проверить содержимое файла перед написанием).

**Acceptance criteria:**
- [x] Файл создан, содержит все 7 разделов.
- [x] Оба mermaid-блока (`flowchart` и два `sequenceDiagram`) синтаксически корректны (проверить отсутствие незакрытых `subgraph`/`end`).
- [x] Ссылки на тестовые файлы актуальны (файлы существуют).

**Out of scope:** Не описывать внутреннюю реализацию traits (она документирована в `base/README.md`).
**Dependencies:** Task 1.1, Task 1.2

---

### Task 1.8 — `components/README.md` и `ARCHITECTURE.md`: добавить combo

**Level:** Junior (Haiku)
**Assignee:** docs-writer
**Goal:** Обновить `components/README.md` (дерево, mermaid, таблица) и `ARCHITECTURE.md` (упоминание combo как стандартного контрола).
**Context:** `components/README.md` содержит: дерево папок (секция «Структура папок»), mermaid flowchart «карта зависимостей», ASCII-диаграмму «карта компонентов», таблицу компонентов и список примеров использования. В каждом месте combo не упомянут. `ARCHITECTURE.md` в секции «Как добавить компонент» приводит combo как пример будущего компонента — эту строку теперь нужно обновить, указав, что combo уже реализован.

**Files:**
- `multiprocess_framework/modules/frontend_module/components/README.md` — изменить
- `multiprocess_framework/modules/frontend_module/components/ARCHITECTURE.md` — изменить

**Steps (README.md):**
1. В разделе «Структура папок» добавить строку `├── combo/` после `checkbox/`, с подпунктами аналогично checkbox-блоку: `config.py`, `view.py`, `presenter.py`, `facade.py`, `defaults.py`, `registers.py`.
2. В mermaid `flowchart TB` добавить узел `Combo[combo/ ComboView]` в subgraph «Примитивы» и узел `ComboControl[combo/]` в subgraph «Фасады»; добавить ребро `Combo --> ComboControl`.
3. В ASCII-диаграмму «карта компонентов» добавить блок для `combo/` после `checkbox/` (по аналогии с форматом checkbox-блока).
4. В таблице компонентов добавить строку: `| **combo/** | Выпадающий список | ComboViewConfig | ComboView | ComboControl |`.
5. Добавить пример использования ComboControl (раздел «Примеры использования»): `ComboControl.create(rm, BindingConfig(...), ComboViewConfig(), items=["a", "b"])`.

**Steps (ARCHITECTURE.md):**
6. Найти строку «например, ComboBox» (в разделе «Рекомендации» `README.md`) — обновить, указав что combo уже реализован. В `ARCHITECTURE.md` найти любое упоминание combo как «будущего» компонента и заменить на «реализованный».

**Acceptance criteria:**
- [x] В дереве папок `README.md` появился блок `combo/` с подфайлами.
- [x] В таблице компонентов есть строка `combo/`.
- [x] В `ARCHITECTURE.md` нет формулировок «например, ComboBox» как нереализованного примера.

**Out of scope:** Не переписывать ASCII-диаграммы полностью — только добавить combo-блок.
**Dependencies:** Task 1.7

---

### Phase 5: Тесты

---

### Task 1.9 — Тест на `ComboRegister`

**Level:** Junior (Haiku)
**Assignee:** docs-writer
**Goal:** Добавить тесты на `ComboRegister` в существующий файл `test_combo_v2.py`.
**Context:** Аналогично `SliderRegister` — нужно убедиться, что `python_type = str` и `widget = "combo"` не изменятся при рефакторинге. Тесты простые (атрибуты класса), без Qt. Файл `test_combo_v2.py` уже содержит `TestComboPresenter` и `TestComboControlFacade` — добавить новый класс `TestComboRegister` в конец файла.

**Files:**
- `multiprocess_framework/modules/frontend_module/tests/test_combo_v2.py` — изменить

**Steps:**
1. Прочитать конец `test_combo_v2.py`.
2. Добавить в конец файла новый класс `TestComboRegister` с двумя тестами:
   - `test_python_type_is_str` — `assert ComboRegister.python_type is str`.
   - `test_widget_is_combo` — `assert ComboRegister.widget == "combo"`.
3. Добавить импорт `ComboRegister` из `...combo.registers` в секцию импортов файла.

**Acceptance criteria:**
- [x] `pytest multiprocess_framework/modules/frontend_module/tests/test_combo_v2.py -v` проходит все тесты, включая новые `TestComboRegister`.
- [x] Существующие тесты `TestComboPresenter` и `TestComboControlFacade` не сломаны.

**Out of scope:** Не тестировать интеграцию `ComboRegister` с `DescriptorSchemaMeta` — это отдельный слой.
**Dependencies:** Task 1.2

---

## Риски и ограничения

1. **Циклические импорты:** `combo/` не должен импортировать из `components/__init__.py`. Проверить после Task 1.6.
2. **`_examples/__init__.py` alias:** `coerce_ui` из combo экспортируется как `combo_coerce_ui` (как `checkbox_coerce_ui` и т.д.) — важно не нарушить соглашение об именовании.
3. **`ARCHITECTURE.md` стр. «ComboBox»:** в `README.md` раздел «Рекомендации» содержит строку `- **Добавить новый value-контрол** (например, ComboBox)` — она говорит про добавление в `numeric/facade`, а не про `combo/` как standalone. Не трогать её смысл — только при необходимости уточнить, что standalone combo уже есть.
4. **`test_form_context_integration.py`:** перед написанием Task 1.7 (README) — проверить содержимое файла на наличие combo-теста (упомянуть в README только если он есть).
