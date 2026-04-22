---
status: planned
phase: 0
branch: feat/phase-0-settings-profiles
created: 2026-04-21
---

# Phase 0 — Инфраструктура настроек и профилей

## Обзор

Phase 0 закладывает фундамент, на котором строятся все последующие фазы: переключаемые профили
настроек приложения (camera_count, ring_buffer_size, shm_budget_mb, workers_per_processor и т.д.)
по аналогии с паттерном `RecipeManager` / YAML-слоты.

**Критерий готовности фазы:** профиль загружается из YAML → переключается → `RegistersManager`
отражает значения без рестарта приложения.

**Merge-стратегия (из плана):** squash → main.

**PR-чеклист:**
- `ruff check + ruff format` — зелёный
- `python Inspector_prototype/scripts/validate.py` — pass
- `python Inspector_prototype/scripts/run_framework_tests.py` — pass
- L1 unit-тесты для всего нового кода
- Минимум 1 L2 integration-тест на profile switch
- Обновлены `README.md` / `STATUS.md` в затронутых модулях

---

## Задачи

### Task 0.1 — AppSettingsSchema: схема настроек приложения (SchemaBase)

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Создать `AppSettingsSchema` — схему настроек приложения через `SchemaBase` + `FieldMeta`, включающую поля для масштабирования камер и SHM-бюджета (AD-1, AD-6).

**Контекст:**
Паттерн: `SchemaBase` + `@register_schema(...)` + `FieldMeta` — точно как в
`multiprocess_prototype_v3/schemas/camera.py` (`BaseCameraRegisters`).
Новая схема будет использоваться `SettingsProfileManager` (Task 0.2) как тип слота данных
и `RegistersManager` как один из регистров (Task 0.3).

**Файлы:**
- `Inspector_prototype/multiprocess_prototype_v3/schemas/app_settings.py` — **создать**
- `Inspector_prototype/multiprocess_prototype_v3/schemas/__init__.py` — добавить реэкспорт

**Шаги:**

1. Создать файл `schemas/app_settings.py`. Декорировать класс `@register_schema("AppSettingsSchema")`.
   Базовый класс — `SchemaBase` из `multiprocess_framework.modules.data_schema_module`.

2. Добавить поля с `FieldMeta` (метки, info, min/max, unit):
   - `camera_count: int` — число активных камер, default=1, min=1, max=16.
   - `ring_buffer_size: int` — размер ring-buffer на камеру (K слотов, AD-6), default=3, min=2, max=8.
   - `shm_budget_mb: int` — общий SHM-бюджет в МБ (AD-6), default=512, min=64, max=4096, unit="MB".
   - `workers_per_processor: int` — потоков на процесс-процессор (AD-3), default=2, min=1, max=8.
   - `display_count: int` — число отображаемых окон, default=2, min=0, max=16.
   - `camera_source_type: str` — тип источника по умолчанию для всех камер ("simulator", "webcam", "hikvision"), default="simulator".

3. Добавить `FieldRouting(channel="control_settings")` для всех полей (аналог `CAMERA_ROUTING`
   в `schemas/camera.py`).

4. Добавить в `schemas/__init__.py` строку импорта `AppSettingsSchema`:
   ```python
   from .app_settings import AppSettingsSchema
   ```
   и включить в `__all__` если есть.

5. Написать unit-тест `tests/unit/test_app_settings_schema.py`:
   - Создание экземпляра с дефолтами: поля имеют ожидаемые значения.
   - `model_dump()` → `model_validate(...)` round-trip без потерь.
   - Валидация: `camera_count=0` поднимает `ValidationError` (min=1).

**Критерии приёмки:**
- [ ] `AppSettingsSchema()` создаётся без ошибок, все дефолты правильные
- [ ] `model_dump() / model_validate()` round-trip — pytest pass
- [ ] `@register_schema` добавляет класс в `get_default_registry()`
- [ ] `ruff check schemas/app_settings.py` — без замечаний
- [ ] unit-тест запускается из `Inspector_prototype/` через `pytest multiprocess_prototype_v3/tests/unit/`

**Вне scope:** не создавать регистр / Register в RegistersManager (это Task 0.3), не создавать YAML-файлы.

**Зависимости:** нет (первая задача)

---

### Task 0.2 — SettingsYamlStore: YAML-хранилище профилей

**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Создать `SettingsYamlStore` — YAML-хранилище профилей настроек (зеркало `recipe_yaml_stores.py`).

**Контекст:**
Точный аналог `YamlSlotFileStore` / `RegisterRecipesYamlStore` из
`managers/recipe_yaml_stores.py`, но для профилей настроек.
Хранит: `version`, `current_profile`, `profiles: {id: {AppSettingsSchema fields}}`.
Файл по умолчанию: `multiprocess_prototype_v3/data/settings_profiles.yaml`.

**Файлы:**
- `Inspector_prototype/multiprocess_prototype_v3/managers/settings_yaml_store.py` — **создать**

**Шаги:**

1. Скопировать структуру из `recipe_yaml_stores.py`:
   - Константа `SETTINGS_FILE_VERSION = 1`.
   - Функция `default_settings_profiles_path() -> str` — возвращает путь к
     `multiprocess_prototype_v3/data/settings_profiles.yaml` (аналог `_default_data_path()` в `recipe_manager.py`).
   - Класс `SettingsYamlStore(YamlSlotFileStore)` — наследует базовый `YamlSlotFileStore`
     из `recipe_yaml_stores.py` (не дублировать read/write логику).

2. В `SettingsYamlStore` реализовать метод `save(*, version, current_profile, profiles)`:
   записывает dict вида `{"version": ..., "current_profile": ..., "profiles": {...}}`.

3. Добавить функцию `default_profile_snapshot() -> dict` — возвращает `AppSettingsSchema().model_dump()`
   (дефолтный снимок для слота "default").

4. Написать unit-тест `tests/unit/test_settings_yaml_store.py`:
   - Запись профиля → чтение → данные совпадают.
   - Несуществующий файл: `read_dict()` возвращает `None` без исключений.
   - Создаёт директорию если не существует (`os.makedirs` logic).

**Критерии приёмки:**
- [ ] `SettingsYamlStore.save(...)` создаёт валидный YAML-файл
- [ ] `SettingsYamlStore(path).read_dict()` возвращает записанные данные
- [ ] round-trip через tempfile — pytest pass
- [ ] `ruff check managers/settings_yaml_store.py` — без замечаний

**Вне scope:** не реализовывать логику переключения профилей (это `SettingsProfileManager` в Task 0.3).

**Зависимости:** Task 0.1 (нужен `AppSettingsSchema` для `default_profile_snapshot`)

---

### Task 0.3 — SettingsProfileManager: менеджер профилей

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Создать `SettingsProfileManager` — полный менеджер профилей настроек (зеркало `RecipeManager`): list/get/save/switch + SHM-budget validation (AD-6).

**Контекст:**
Архитектура точно по образцу `RecipeManager`:
- Двойные хранилища в `RecipeManager` (`_register_store` + `_app_store`) здесь заменяются
  одним `SettingsYamlStore` (профили настроек — единый файл).
- Слот `"default"` — заводской профиль (аналог `DEFAULT_RECIPE_SLOT_ID = "0"`).
- `switch_profile(profile_id)` — загружает профиль в `RegistersManager` через `model_validate_all`.
- **Budget-check (AD-6):** при `switch_profile` или `save_profile` вызывать
  `validate_shm_budget(profile)` — считает `camera_count * ring_buffer_size * max_frame_bytes`
  против `shm_budget_mb * 1024 * 1024`; при превышении поднимает `ShmBudgetError`.

**Файлы:**
- `Inspector_prototype/multiprocess_prototype_v3/managers/settings_profile_manager.py` — **создать**
- `Inspector_prototype/multiprocess_prototype_v3/managers/settings_profile_protocol.py` — **создать**
- `Inspector_prototype/multiprocess_prototype_v3/managers/__init__.py` — добавить реэкспорт

**Шаги:**

1. Создать `SettingsProfileManagerProtocol` (Protocol, `@runtime_checkable`) в
   `settings_profile_protocol.py`:
   ```python
   class SettingsProfileManagerProtocol(Protocol):
       def get_current_profile_id(self) -> str: ...
       def set_current_profile_id(self, profile_id: str) -> None: ...
       def list_profiles(self) -> list[str]: ...
       def get_profile_snapshot(self, profile_id: str) -> Optional[dict]: ...
       def save_profile_snapshot(self, profile_id: str, snapshot: dict) -> bool: ...
       def switch_profile(self, profile_id: str, registers_bridge: Any) -> bool: ...
       def ensure_default_profile(self, registers_bridge: Any) -> None: ...
   ```

2. Создать `SettingsProfileManager` в `settings_profile_manager.py`:
   - Конструктор: `__init__(self, data_path=None)` — принимает путь к YAML.
   - Поле `_store: SettingsYamlStore` + внутренний `_data: dict`.
   - Методы `load()` / `save()` — по аналогии с `RecipeManager.load/save`.
   - `list_profiles() -> list[str]` — ключи из `_data["profiles"]`.
   - `get_profile_snapshot(profile_id) -> Optional[dict]` — deepcopy слота.
   - `save_profile_snapshot(profile_id, snapshot) -> bool` — записать снимок в слот + `save()`.
   - `switch_profile(profile_id, registers_bridge) -> bool`:
     1. Найти слот, десериализовать через `AppSettingsSchema.model_validate(snapshot)`.
     2. Вызвать `validate_shm_budget(profile)` — при ошибке поднять `ShmBudgetError`.
     3. Вызвать `registers_bridge.model_validate_all({"settings": snapshot})` (или аналог
        прямой записи в регистр settings).
     4. Вернуть `True` при успехе, `False` если слот не найден.
   - `ensure_default_profile(registers_bridge)` — если слота "default" нет, создать из
     `default_profile_snapshot()` (аналог `ensure_slot_from_registers`).

3. Реализовать `validate_shm_budget(profile: AppSettingsSchema) -> None`:
   Формула из AD-6: `total = camera_count * ring_buffer_size * (resolution_width * resolution_height * 3)`
   где `resolution_width=1920`, `resolution_height=1080` (worst-case 1080p BGR).
   Если `total > shm_budget_mb * 1024 * 1024` — поднять `ShmBudgetError(camera_count, ring_buffer_size, total_mb, budget_mb)`.
   `ShmBudgetError` — кастомное исключение (определить в том же файле).

4. В `managers/__init__.py` добавить:
   ```python
   from .settings_profile_manager import SettingsProfileManager, ShmBudgetError
   from .settings_profile_protocol import SettingsProfileManagerProtocol
   ```

5. Написать unit-тесты `tests/unit/test_settings_profile_manager.py`:
   - `switch_profile` с существующим слотом → `True`, регистры обновились.
   - `switch_profile` с несуществующим слотом → `False`.
   - `validate_shm_budget`: 8 камер × K=3 × 1080p = ~144 MB при budget=512 — OK;
     8 камер × K=3 × 4K (~288 MB на K=3) при budget=100 → `ShmBudgetError`.
   - `save_profile_snapshot` + `get_profile_snapshot` round-trip.
   - `ensure_default_profile`: файл пустой → создаёт слот "default".

**Критерии приёмки:**
- [ ] `SettingsProfileManager` реализует `SettingsProfileManagerProtocol` (isinstance проходит)
- [ ] `switch_profile("default", bridge)` → `True` + значения в регистрах изменились
- [ ] `ShmBudgetError` поднимается при превышении бюджета (тест на 4K + 8 камер)
- [ ] round-trip YAML через tempfile — pytest pass
- [ ] `ruff check` — без замечаний

**Вне scope:** не интегрировать в `FrontendLauncher` (это Task 0.4), не создавать UI-виджет.

**Зависимости:** Task 0.1, Task 0.2

---

### Task 0.4 — AppSettingsRegister: регистр настроек в RegistersManager

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Зарегистрировать `AppSettingsSchema` как полноценный регистр в `RegistersManager` через существующий механизм `create_registers()`, чтобы `RegistersManager` отражал значения профиля.

**Контекст:**
Нужно изучить `multiprocess_prototype_v3/registers/` — там функция `create_registers()`,
которую вызывает `FrontendLauncher.build_registers()`. Новый регистр `"settings"` должен
создаваться там же и быть доступен через `registers_manager.get_register("settings")`.
Паттерн: смотреть как регистрируются `"camera"`, `"processor"` и т.д.

**Файлы:**
- `Inspector_prototype/multiprocess_prototype_v3/registers/` — найти `create_registers.py`
  или аналог; добавить регистр `"settings"` с типом `AppSettingsSchema`
- `Inspector_prototype/multiprocess_prototype_v3/registers/schemas/` — если схемы регистров
  хранятся отдельно: добавить `settings_register.py` по паттерну соседних файлов

**Шаги:**

1. Изучить `multiprocess_prototype_v3/registers/__init__.py` и соседние файлы — найти
   `create_registers()` и понять как регистрируется новый регистр.

2. Добавить регистр `"settings"` в `create_registers()`:
   ```python
   ("settings", AppSettingsSchema),
   ```
   (точный синтаксис — по образцу существующих регистров в файле).

3. Убедиться что импорт `AppSettingsSchema` добавлен в файл `create_registers` или
   соответствующий `__init__.py`.

4. Проверить что `registers_manager.get_register("settings")` не ломает существующие тесты:
   запустить `python Inspector_prototype/scripts/validate.py` — pass.

5. Написать unit-тест `tests/unit/test_settings_register.py`:
   - `create_registers()` возвращает менеджер, в котором есть ключ `"settings"`.
   - `registers_manager.get_register("settings")` возвращает экземпляр `AppSettingsSchema`.
   - `model_dump_all()` включает секцию `"settings"` с полями из `AppSettingsSchema`.

**Критерии приёмки:**
- [ ] `create_registers()` не бросает исключений
- [ ] `registers_manager.get_register("settings")` возвращает `AppSettingsSchema`
- [ ] `model_dump_all()["settings"]` присутствует и содержит ожидаемые ключи
- [ ] `python Inspector_prototype/scripts/validate.py` — pass после изменений
- [ ] Существующие тесты `test_registers_bridge.py`, `test_registers_registry.py` — не сломаны

**Вне scope:** не менять `switch_profile` в SettingsProfileManager под конкретную структуру
RegistersManager — это делается здесь, уточняя правильный ключ.

**Зависимости:** Task 0.1, Task 0.3

---

### Task 0.5 — Интеграция SettingsProfileManager в FrontendLauncher и FrontendAppContext

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Подключить `SettingsProfileManager` в `FrontendLauncher.register_windows()` и `FrontendAppContext` по аналогии с `RecipeManager`, чтобы `app_ctx.settings_profile_manager` был доступен для будущих вкладок.

**Контекст:**
`FrontendLauncher.register_windows()` (строки 83-103 в `frontend/launcher.py`) создаёт
`RecipeManager` и передаёт его в `FrontendAppContext`. По той же схеме нужно создать
`SettingsProfileManager` и добавить его в `FrontendAppContext`.

`FrontendAppContext` (`frontend/app_context.py`) — dataclass с полями зависимостей.
Новое поле: `settings_profile_manager: Optional[SettingsProfileManagerProtocol] = None`.

Конфиг-путь: `config.get("settings_profiles_path")` — добавить в `FrontendConfig` (Task 0.5
включает минимальные изменения в `frontend_config.py`).

**Файлы:**
- `Inspector_prototype/multiprocess_prototype_v3/frontend/launcher.py` — изменить
- `Inspector_prototype/multiprocess_prototype_v3/frontend/app_context.py` — изменить
- `Inspector_prototype/multiprocess_prototype_v3/frontend/configs/frontend_config.py` — добавить поле `settings_profiles_path`

**Шаги:**

1. В `frontend/configs/frontend_config.py` добавить поле `settings_profiles_path: Optional[str] = None`
   в класс `FrontendConfig` (рядом с полем `recipes_path`).

2. В `frontend/app_context.py` добавить поле в `FrontendAppContext`:
   ```python
   settings_profile_manager: Optional[SettingsProfileManagerProtocol] = None
   ```
   Добавить импорт `SettingsProfileManagerProtocol`.
   Добавить accessor-метод:
   ```python
   def get_settings_profiles_path(self) -> Any:
       return self.config.get("settings_profiles_path")
   ```

3. В `frontend/launcher.py` в методе `register_windows()` после создания `recipe_manager`
   добавить создание `settings_profile_manager`:
   ```python
   from multiprocess_prototype.managers import SettingsProfileManager
   settings_profile_manager = SettingsProfileManager(
       data_path=config.get("settings_profiles_path"),
   )
   if regs is not None:
       settings_profile_manager.ensure_default_profile(regs)
   ```
   Передать `settings_profile_manager` в `FrontendAppContext(...)`.

4. Убедиться, что `FrontendAppContext` корректно сериализуется в тесте
   `tests/test_frontend_app_context.py` — поле `settings_profile_manager=None` не ломает
   существующий код.

5. Проверить: `python Inspector_prototype/scripts/validate.py` и
   `python Inspector_prototype/scripts/run_framework_tests.py` — оба pass.

**Критерии приёмки:**
- [ ] `FrontendAppContext` имеет поле `settings_profile_manager`
- [ ] `FrontendLauncher` создаёт `SettingsProfileManager` и передаёт его в контекст
- [ ] Существующие тесты `test_frontend_app_context.py` — не сломаны
- [ ] `validate.py` + `run_framework_tests.py` — pass
- [ ] `ruff check frontend/launcher.py frontend/app_context.py` — без замечаний

**Вне scope:** не создавать UI-виджет для переключения профилей (Phase 2), не реализовывать
событие `profile_changed` (Phase 2).

**Зависимости:** Task 0.3, Task 0.4

---

### Task 0.6 — Smoke-test: переключение профиля end-to-end

**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Написать L1 unit-тест и L2 integration-тест, которые верифицируют полный цикл: YAML-профиль → `switch_profile` → `RegistersManager` отражает значения.

**Контекст:**
Критерий приёмки фазы: "Профиль из YAML → переключается → `RegistersManager` отражает значения."
L1 — чистые объекты, без GUI. L2 — через `create_registers()` как делают существующие
тесты `test_recipe_manager.py` / `test_registers_bridge.py`.
Тесты располагаются в:
- L1: `Inspector_prototype/multiprocess_prototype_v3/tests/unit/` (новая директория если не существует)
- L2: `Inspector_prototype/multiprocess_prototype_v3/tests/test_settings_profile_switch.py`

**Файлы:**
- `Inspector_prototype/multiprocess_prototype_v3/tests/unit/__init__.py` — создать если нет
- `Inspector_prototype/multiprocess_prototype_v3/tests/unit/test_app_settings_schema.py` — уже создан в Task 0.1
- `Inspector_prototype/multiprocess_prototype_v3/tests/unit/test_settings_yaml_store.py` — уже создан в Task 0.2
- `Inspector_prototype/multiprocess_prototype_v3/tests/unit/test_settings_profile_manager.py` — уже создан в Task 0.3
- `Inspector_prototype/multiprocess_prototype_v3/tests/unit/test_settings_register.py` — уже создан в Task 0.4
- `Inspector_prototype/multiprocess_prototype_v3/tests/test_settings_profile_switch.py` — **создать** (L2)

**Шаги:**

1. Создать `tests/unit/__init__.py` (пустой) если директория `unit/` ещё не существует.

2. Написать L2-тест `test_settings_profile_switch.py`:

   **Сценарий A — базовый switch:**
   ```
   1. create_registers() → registers, _
   2. tempfile + SettingsProfileManager(data_path=tmp)
   3. ensure_default_profile(registers)
   4. Сохранить профиль "fast" с camera_count=4, ring_buffer_size=2
   5. switch_profile("fast", registers) → True
   6. assert registers.get_register("settings").camera_count == 4
   7. assert registers.get_register("settings").ring_buffer_size == 2
   ```

   **Сценарий B — несуществующий профиль:**
   ```
   switch_profile("nonexistent", registers) → False
   assert registers.get_register("settings").camera_count == 1  # не изменился
   ```

   **Сценарий C — SHM-budget exceeded:**
   ```
   Профиль с camera_count=8, ring_buffer_size=3, shm_budget_mb=50
   switch_profile("overbudget", registers) → поднимает ShmBudgetError
   ```

   **Сценарий D — round-trip YAML:**
   ```
   save_profile_snapshot("prod", {...}) → load (новый SettingsProfileManager) → get_profile_snapshot("prod") == saved
   ```

3. Убедиться что все unit-тесты (из Tasks 0.1-0.4) запускаются из одной команды:
   ```
   cd Inspector_prototype && pytest multiprocess_prototype_v3/tests/unit/ -v
   ```

4. Убедиться что L2-тест запускается:
   ```
   cd Inspector_prototype && pytest multiprocess_prototype_v3/tests/test_settings_profile_switch.py -v
   ```

5. Обновить `README.md` в `managers/` — добавить строку про `SettingsProfileManager` в таблицу модулей.

**Критерии приёмки:**
- [ ] Сценарий A: `switch_profile` → `True`, `registers.get_register("settings").camera_count == 4`
- [ ] Сценарий B: несуществующий профиль → `False`, регистры не изменились
- [ ] Сценарий C: превышение budget → `ShmBudgetError`
- [ ] Сценарий D: YAML round-trip через tempfile — данные идентичны
- [ ] `cd Inspector_prototype && pytest multiprocess_prototype_v3/tests/unit/ -v` — all pass
- [ ] `cd Inspector_prototype && pytest multiprocess_prototype_v3/tests/test_settings_profile_switch.py -v` — all pass
- [ ] `managers/README.md` обновлён — упоминает `SettingsProfileManager`

**Вне scope:** не тестировать GUI/виджеты (это Phase 2), не тестировать IPC-пропагацию
между процессами (это Phase 3+).

**Зависимости:** Task 0.1, Task 0.2, Task 0.3, Task 0.4, Task 0.5

---

## Порядок реализации

```
Task 0.1 (схема)
    ↓
Task 0.2 (YAML-store)  ←── зависит от 0.1
    ↓
Task 0.3 (менеджер)    ←── зависит от 0.1, 0.2
    ↓
Task 0.4 (регистр)     ←── зависит от 0.1, 0.3 (уточняет метод switch_profile)
    ↓
Task 0.5 (интеграция в лаунчер/контекст)  ←── зависит от 0.3, 0.4
    ↓
Task 0.6 (smoke-test end-to-end)  ←── зависит от всех предыдущих
```

Каждая задача закрывается отдельным коммитом на ветке `feat/phase-0-settings-profiles`.

## Файлы Phase 0 (итог)

**Новые:**
- `multiprocess_prototype_v3/schemas/app_settings.py`
- `multiprocess_prototype_v3/managers/settings_yaml_store.py`
- `multiprocess_prototype_v3/managers/settings_profile_manager.py`
- `multiprocess_prototype_v3/managers/settings_profile_protocol.py`
- `multiprocess_prototype_v3/tests/unit/__init__.py`
- `multiprocess_prototype_v3/tests/unit/test_app_settings_schema.py`
- `multiprocess_prototype_v3/tests/unit/test_settings_yaml_store.py`
- `multiprocess_prototype_v3/tests/unit/test_settings_profile_manager.py`
- `multiprocess_prototype_v3/tests/unit/test_settings_register.py`
- `multiprocess_prototype_v3/tests/test_settings_profile_switch.py`

**Изменяемые:**
- `multiprocess_prototype_v3/schemas/__init__.py` — реэкспорт `AppSettingsSchema`
- `multiprocess_prototype_v3/managers/__init__.py` — реэкспорт менеджера и протокола
- `multiprocess_prototype_v3/registers/` — добавить регистр "settings" (конкретный файл уточняет Task 0.4)
- `multiprocess_prototype_v3/frontend/app_context.py` — поле `settings_profile_manager`
- `multiprocess_prototype_v3/frontend/launcher.py` — создание менеджера
- `multiprocess_prototype_v3/frontend/configs/frontend_config.py` — поле `settings_profiles_path`
- `multiprocess_prototype_v3/managers/README.md` — обновить таблицу
