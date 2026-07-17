# frontend_module — Статус

## Текущий этап: 6 / 8 (рефакторинг + ревизия)

**Дата последней ревизии:** 2026-04-17

## Оценки (0-10)

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| Код (читаемость, стандарты) | 9 | Controls: primitives, typography/styles, `coerce_schema_config`, узкий конструктор |
| Тесты (покрытие) | 6–7 | `test_tabs_callbacks`, `test_touch_keyboard`, `test_controls_v2_base`, `test_schema_config`, `test_example_with_data_schema` |
| Документация (README, interfaces) | 9 | README с quick-start, TAB_STRUCTURE, MVP_TEMPLATE, ADR-серия, STATUS |
| Связанность (меньше = лучше) | 9 | Примитивы в `components/`, shell в `widgets/`, без shim |
| Работоспособность | 9 | FrontendManager.run_app/shutdown_app, GuiProcess интеграция |

## Изменения

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

## Результаты ревизии (2026-04-17)

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

### __init__.py экспорты — ОЧИЩЕНЫ

Из 19 экспортов реально импортируются извне только 3:

| Символ | Используется | Решение |
|--------|-------------|---------|
| `FrontendLaunchHooks` | old, v2, v3 | **Оставлен** |
| `run_process_attached_frontend` | old, v2, v3 | **Оставлен** |
| `FrontendManager` | old (тесты) | **Оставлен** |
| `RoutedCommandSender` | Импортируется из `core.routed_command` напрямую | **Оставлен** (удобство) |
| `WindowManager` | Используется через FrontendManager | **Оставлен** (удобство) |
| Остальные 14 символов | Не импортируются извне | **Удалены из `__all__` и импортов** |

Удалённые из top-level: `BaseConfigurableWidget`, `WidgetRegistry`, `WindowRegistry`, `WindowEntry`, `FrontendRegistersBridge`, `WidgetDescriptor`, `widget_descriptor_from_dict`, `create_default_registry`, `WindowConfig`, `compose_layout`, `FrontendManagerConfig`, `FrontendThreadManagerConfig`, `WindowManagerConfig`, `ThreadManager`.

Все эти символы по-прежнему доступны через подпакеты (`frontend_module.core`, `frontend_module.schemas`, `frontend_module.configs`).

## Что работает

- `run_process_attached_frontend` + `FrontendLaunchHooks` — полный каркас запуска
- `FrontendManager` — initialize, run_app, shutdown_app, config hot-reload
- `FrontendRegistersBridge` — connection_map, send_callback, subscribe
- Controls: SliderControl, CheckboxControl, SpinBoxControl, NumericControl, CompoundControl
- Widgets: BaseWidget[TModel], HeaderWidget, TabWidget, ImagePanelWidget, LoadingWindow
- TelemetryChart, SeriesSpec — конструкторный многосерийный live-график (PyQtGraph)
- Tables: StructuredTableWidget, StructuredTwoLevelTreeWidget, TreeWithToolbar
- Touch-клавиатура, WidgetSignalBus

## TODO

- [ ] Этап 7: Расширить unit-тесты (presenter-ы, WindowManager, ThreadManager)
- [ ] Этап 8: ADR-индекс в DECISIONS.md, финальная документация
- [ ] Рассмотреть вынос `components/examples/` в `tests/fixtures/` для чистоты
