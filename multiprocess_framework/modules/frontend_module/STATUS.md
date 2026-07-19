# frontend_module — Статус

## Текущий этап: 6 / 8 (рефакторинг + ревизия); Ф1 фасад-флип — завершён

**Дата последней ревизии:** 2026-07-18 (frontend-constructor Ф1, T1.1–T1.2)

## Два поколения (frontend-constructor Ф1, T1.1)

Модуль исторически содержит два несовместимых поколения UI-конструктора.
**Gen-1** («application-центричное», `FrontendManager`/`WindowManager`/
`WidgetRegistry`) — не используется прототипом v3 (v1/v2-прототипы удалены,
e128b930). **Gen-2** («generic-механизмы», `tabs`/`state`/`components`/
`widgets.tabs`/`core.app_identity`) — живое, потребляется v3 deep-импортами
мимо фасада. До Ф1 фасад `__init__.py` экспортировал **только Gen-1** —
несоответствие исправлено T1.2 (см. ниже).

### Инвентарь Gen-1 (grep-доказательства 0 внешних потребителей)

Метод: `grep -rn "<символ>" --include="*.py" .` по всему репозиторию,
исключая сам `frontend_module/` и `__pycache__`. «Внешний потребитель» —
любой файл вне `multiprocess_framework/modules/frontend_module/`.

| # | Путь | LOC | Публичные символы | Внешние потребители | Внутренние тесты | Решение |
|---|------|----:|--------------------|----------------------|-------------------|---------|
| 1 | `application/` | 683 | `FrontendManager`, `WindowManager`, `ThreadManager`, `run_process_attached_frontend`, `FrontendLaunchHooks` | **0.** Единственный хит вне модуля — `multiprocess_framework/__init__.py` (ленивый PEP 562 `__getattr__` для `FrontendManager`, сам никем не вызывается; собственный docstring подтверждает «в v3-прототипе фасадный FrontendManager не используется»). Упоминания в `multiprocess_prototype/frontend/state/auth_state.py` — forward-compat комментарии (`pass  # WindowManager — forward-compat`), не импорт. Совпадения `WindowManager` в `widgets/tabs/displays/*` — другой класс (`PreviewWindowManager`, не связан) | `test_frontend_manager.py`, `test_window_manager_unit.py` | **LEGACY, frozen** |
| 2 | `core/widget_registry.py` | 78 | `WidgetRegistry` | 0 (только `core/default_factories.py`, внутри Gen-1) | нет | **LEGACY, frozen** |
| 3 | `core/window_registry.py` | 174 | `WindowRegistry` | 0 (только `application/window_manager.py`, внутри Gen-1) | `test_window_registry.py` | **LEGACY, frozen** |
| 4 | `core/default_factories.py` | 135 | `create_default_registry` | 0 | нет | **LEGACY, frozen** |
| 5 | `core/layout_composer.py` | 54 | `compose_layout` | 0 | нет | **LEGACY, frozen** |
| 6 | `schemas/widget_descriptor.py` | 96 | `WidgetDescriptor`, `widget_descriptor_from_dict` | 0 | `test_widget_descriptor.py` | **LEGACY, frozen** |
| 7 | `schemas/window_config.py` | 51 | `WindowConfig` | 0 (совпадение в `multiprocess_prototype/frontend/windows/config.py` — свой класс `WindowConfig(BaseModel)`, не связан) | `test_window_registry.py` | **LEGACY, frozen** |
| 8 | `configs/` | 75 | `FrontendManagerConfig`, `WindowManagerConfig`, `FrontendThreadManagerConfig` | **0 вообще** — даже `application/*.py` их не импортирует (проверено отдельно) | нет | **LEGACY, frozen** |
| 9 | `windows/` (`loading_window.py`) | 107 | `LoadingWindow` | 0 (комментарий-упоминание в `multiprocess_prototype/frontend/app.py`, не импорт) | `test_app_identity.py::TestLoadingWindowUsesIdentity` — тестирует интеграцию с живым `core.app_identity`, сам `LoadingWindow` не подключён ни одним composition root | **LEGACY, frozen** (тестовый класс тоже помечен `legacy_gen1`) |

**Итого Gen-1 во фронт-фасаде до Ф1:** ~1253 LOC (`application` 683 + core-подмножество 441 + `configs` 75 + `windows` 107 − пересечения) с 0 реальных внешних потребителей.

### Спорные/пограничные классификации

- **`schema_adapter.py` (37 LOC)** — в плане перечислен рядом с Gen-1, но это
  **не Gen-1**: 0 внешних потребителей (как и остальные), однако широко
  используется **внутри модуля обоими поколениями** — Gen-1 (`configs/`,
  `schemas/widget_descriptor.py`, `schemas/window_config.py`) **и** живым
  Gen-2 (`widgets/header/*`, `widgets/chrome/recording_indicator/schemas.py`,
  `components/_examples/*`, `core/schema_config.py`). **Не размечен LEGACY** —
  общая внутренняя зависимость, удалить/заморозить нельзя без поломки Gen-2.
- **`schemas/register_binding.py` (169 LOC)** — часть пакета `schemas/`
  (наряду с двумя Gen-1-файлами выше), но сам **живой**: `RegisterBinding`,
  `RegisterFieldMeta`, `ResolvedMeta` используются `components/base/interfaces.py`,
  `components/base/traits/schema_trait.py`,
  `components/base/infrastructure/{register_adapter,value_transformer}.py`,
  `core/base_configurable_widget.py`. Пакет `schemas/` в целом — **смешанный**
  (см. докстринг `schemas/__init__.py`), не заморожен целиком.
- **`core/routed_command.py` (`RoutedCommandSender`)** — не входил в список T1.1,
  но обнаружен при инвентаре: 0 внешних потребителей (только реэкспорт в
  `application/__init__.py`). Формально Gen-1-по-факту-неиспользования, но
  **не Gen-1 по конструкции** — Qt-независим, реализует протоколы
  `IRouterLike`/`SupportsCommandMessage` из `interfaces.py` (собственный
  докстринг: «расположение в core/, а не application/, чтобы импорт sender не
  подтягивал Qt через FrontendManager»). **Не размечен LEGACY** — оставлен как
  есть; решение по классификации вне scope Ф1.
- **`multiprocess_framework/__init__.py` (`__getattr__` для `FrontendManager`)** —
  единственная внешняя (за пределами `frontend_module/`) ссылка на Gen-1,
  вскрытая инвентарём. 0 реальных вызовов сегодня (по собственному докстрингу).
  Оставлена импортирующей через старый путь `frontend_module.FrontendManager`
  (сейчас недоступен → тихо возвращает `None`, как и раньше при отсутствии
  PySide6) — это сохраняет инвариант T1.2 «0 внешних ссылок на Gen-1-подпакет
  `application/` вне модуля» буквально, ценой того, что сам лениво-загружаемый
  alias теперь всегда резолвится в `None`. Он и до Ф1 не вызывался в проде.

## Фасад-флип (frontend-constructor Ф1, T1.2)

`__init__.py` теперь экспортирует **только живое поколение**:

- Протоколы контракта (`interfaces.py`): `SupportsCommandMessage`, `IRouterLike`,
  `IRegistersManager`, `IRegistersManagerGui`, `IConfigurableWidget`,
  `IWidgetFactory`, `IWidgetRegistry`, `ISignalProvider`, `IWindowRegistry`,
  `IFrontendManager`
- Механизм вкладок (NEW-D1): `TabSpec`, `TabRegistry`, `LazyTab`,
  `AccessContextSource`, `PlaceholderFactory`
- Read-model телеметрии (FE-005): `TelemetryViewModel`, `TelemetryHistorySource`,
  `DEFAULT_TRACKED_SUFFIXES`
- Идентичность приложения (NEW-2): `AppIdentity`, `get_app_identity`, `set_app_identity`
- Фасады подпакетов: `components`, `widgets` (включая `widgets.tabs`)

Gen-1 (`application`, `core.{widget_registry,window_registry,default_factories,
layout_composer}`, `schemas.{widget_descriptor,window_config}`, `configs`,
`windows`) убран из `__all__`, но **пакеты остаются импортируемыми** —
докстринг-маркер `LEGACY Gen-1 (frozen 2026-07-18)` в каждом. Gen-1-тесты
помечены pytest-маркером `legacy_gen1` (зарегистрирован в
`multiprocess_framework/modules/pytest.ini`).

`__version__` = `"0.5.0"`.

## Оценки (0-10)

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| Код (читаемость, стандарты) | 9 | Controls: primitives, typography/styles, `coerce_schema_config`, узкий конструктор |
| Тесты (покрытие) | 6–7 | `test_tabs_callbacks`, `test_touch_keyboard`, `test_controls_v2_base`, `test_schema_config`, `test_example_with_data_schema` |
| Документация (README, interfaces) | 9 | README с quick-start (Gen-2), TAB_STRUCTURE, MVP_TEMPLATE, ADR-серия, STATUS |
| Связанность (меньше = лучше) | 9 | Примитивы в `components/`, shell в `widgets/`, без shim |
| Правдивость фасада | 8 | Ф1: фасад = живое поколение (было 2/10 — экспортировал только мёртвый Gen-1) |
| Работоспособность | 9 | FrontendManager.run_app/shutdown_app (Legacy), GuiProcess интеграция; v3 — TabRegistry/TelemetryViewModel/components/widgets.tabs |

## Изменения

- **2026-07-18 (frontend-constructor Ф1, T1.1–T1.2):** инвентарь Gen-1 с
  grep-доказательствами 0 внешних потребителей; фасад-флип `__init__.py` —
  экспорт живого поколения (протоколы + tabs + state + app_identity +
  components/widgets); Gen-1 заморожен (докстринг-маркеры, не удалён);
  Gen-1-тесты помечены `legacy_gen1`. `__version__` 0.4.0 → 0.5.0.
- **2026-07-12 (NEW-D1):** добавлен generic-механизм вкладок `frontend_module.tabs`
  (`TabSpec`, `TabRegistry`, `LazyTab`, `AccessContextSource`) — перенос из
  прототипа (`tab_factory.py`). 0 обратных импортов; публичный API в
  `interfaces.py`. Тесты: `tests/test_tab_registry.py` (19). ADR-135.

## Чеклист рефакторинга

- [x] Этап 0: Фундамент — структура, interfaces.py, README, STATUS
- [x] Этап 1: Интеграция с RegistersManager и схемами приложения
- [x] Этап 2: BaseConfigurableWidget — портирование из App
- [x] Этап 3: WidgetRegistry, WidgetDescriptor
- [x] Этап 4: Базовые компоненты (SliderControl, CheckboxControl)
- [x] Этап 5: WindowRegistry, WindowConfig, LayoutComposer
- [x] Этап 5.5–5.8: Расширения (tables, tabs, header, keyboard, application layer)
- [x] Этап 6: FrontendManager (BaseManager), FrontendRegistersBridge, run_app/shutdown_app
- [ ] Этап 7: Unit-тесты (расширение покрытия)
- [ ] Этап 8: Финальная документация, ADR в DECISIONS.md

## Результаты ревизии (2026-04-17, историческая — до Ф1 фасад-флипа)

> Раздел ниже описывает состояние **до** frontend-constructor Ф1 (T1.2).
> `__init__.py`-таблица в подразделе «`__init__.py` экспорты» устарела —
> актуальный список см. «Фасад-флип» выше.

### interfaces.py (components/base/interfaces.py) — ВСЕ АКТИВНЫ

| Протокол | Используется | Статус |
|----------|-------------|--------|
| `IControlView[T]` | Checkbox, Numeric, Slider, SpinBox, Group, Label | **Активен** |
| `INumericView` | NumericPresenter (slider/spinbox) | **Активен** |
| `IFieldBinding` | Все presenter-ы через SyncTrait/SchemaTrait | **Активен** |
| `IRegisterPort` | Все presenter-ы через SyncTrait/SchemaTrait | **Активен** |
| `RegistersManagerLike` | Адаптеры, фасады, presenter-ы | **Активен** |

**Вердикт:** удалять нечего. Все протоколы используются.

### LegacySyncTrait — СОХРАНЁН

- **Определён в:** `components/base/traits/legacy_sync_trait.py`
- **Используется внутри:** `NumericPresenter` (опционально, через `legacy_context`)
- **Используется в прототипах:** пока нет (ни old, ни v2, ни v3 не передают `legacy_context`)
- **Тесты:** отсутствуют
- **Вердикт:** сохранён для будущего использования. Механизм синхронизации с v1 ui_elements/controls может понадобиться при миграции или интеграции.

### components/examples/ — ОСТАВЛЕНЫ НА МЕСТЕ

- 8 пакетов (checkbox, slider, spinbox, numeric, group, label, compound_numeric, compound_mixed)
- **Импортируются из:** `tests/test_example_with_data_schema.py` (единственный внешний потребитель)
- **Прототипы:** НЕ импортируют
- **Вердикт:** оставлены в `components/examples/` — являются тестовыми фикстурами. Перенос в `docs/examples/` сломает тесты без выгоды. Имеют свой README.

### __init__.py экспорты (историческое состояние 2026-04-17, ДО Ф1) — ОЧИЩЕНЫ

Из 19 экспортов реально импортировались извне только 3 (тогда фасад ещё был Gen-1):

| Символ | Использовался | Решение (2026-04-17) |
|--------|-------------|---------|
| `FrontendLaunchHooks` | old, v2, v3 | Оставлен (Ф1: перестал быть в фасаде, LEGACY) |
| `run_process_attached_frontend` | old, v2, v3 | Оставлен (Ф1: перестал быть в фасаде, LEGACY) |
| `FrontendManager` | old (тесты) | Оставлен (Ф1: перестал быть в фасаде, LEGACY) |
| `RoutedCommandSender` | Импортируется из `core.routed_command` напрямую | Оставлен (Ф1: перестал быть в фасаде, LEGACY по неиспользованию) |
| `WindowManager` | Используется через FrontendManager | Оставлен (Ф1: перестал быть в фасаде, LEGACY) |
| Остальные 14 символов | Не импортировались извне | Удалены из `__all__` и импортов |

Все эти символы по-прежнему доступны через подпакеты (`frontend_module.application`,
`frontend_module.core`, `frontend_module.schemas`, `frontend_module.configs`) —
просто больше не реэкспортируются через top-level `__init__.py`.

## Что работает

- `run_process_attached_frontend` + `FrontendLaunchHooks` — полный каркас запуска (LEGACY Gen-1)
- `FrontendManager` — initialize, run_app, shutdown_app, config hot-reload (LEGACY Gen-1)
- `FrontendRegistersBridge` — connection_map, send_callback, subscribe (LEGACY Gen-1)
- `TabRegistry`/`TabSpec` — generic-механизм вкладок (Gen-2, живое, в фасаде)
- `TelemetryViewModel`/`TelemetryHistorySource` — read-model телеметрии (Gen-2, живое, в фасаде)
- `AppIdentity`/`get_app_identity`/`set_app_identity` — идентичность приложения (Gen-2, живое, в фасаде)
- Controls: SliderControl, CheckboxControl, SpinBoxControl, NumericControl, CompoundControl (Gen-2, живое)
- Widgets: BaseWidget[TModel], HeaderWidget, TabWidget, ImagePanelWidget (Gen-2, живое); LoadingWindow (LEGACY Gen-1)
- TelemetryChart, SeriesSpec — конструкторный многосерийный live-график (PyQtGraph) (Gen-2, живое)
- Tables: StructuredTableWidget, StructuredTwoLevelTreeWidget, TreeWithToolbar (Gen-2, живое)
- Touch-клавиатура, WidgetSignalBus (Gen-2, живое)

## TODO

- [ ] Этап 7: Расширить unit-тесты (presenter-ы, WindowManager, ThreadManager)
- [ ] Этап 8: ADR-индекс в DECISIONS.md, финальная документация
- [ ] Рассмотреть вынос `components/examples/` в `tests/fixtures/` для чистоты
- [ ] frontend-constructor Ф3: промоушен универсального из прототипа (`plans/frontend-constructor/plan.md`)
