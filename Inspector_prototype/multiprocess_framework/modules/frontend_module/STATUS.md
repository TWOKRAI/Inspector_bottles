# frontend_module — Статус рефакторинга

## Текущий этап: 6 / 8

## Оценки (0-10)

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| Код (читаемость, стандарты) | 9 | Controls: primitives, typography/styles, `coerce_schema_config`, узкий конструктор |
| Тесты (покрытие) | 6–7 | `test_tabs_callbacks.py` (tabs: Qt-обёртка + dataclass dict); `test_controls_v2_base.py`; `test_schema_config.py`; window_registry |
| Документация (README, interfaces) | 8 | `tabs/TAB_STRUCTURE.md`, `widgets/base_widget`, `components/*`, STATUS, ADR |
| Связанность (меньше = лучше) | 9 | Примитивы в `components/` (flatten бывш. control_v2); shell в `widgets/`; без shim `controls/` |
| Работоспособность | 9 | FrontendManager.run_app/shutdown_app, GuiProcess интеграция |

## Чеклист рефакторинга

- [x] Этап 0: Фундамент — структура, interfaces.py, README, STATUS
- [x] Этап 1: интеграция с RegistersManager и схемами приложения (прототип: registers/schemas)
- [x] Этап 2: BaseConfigurableWidget — портирование из App
- [x] Этап 3: WidgetRegistry, WidgetDescriptor
- [x] Этап 4: Базовые компоненты (SliderControl, CheckboxControl)
- [x] Этап 5: WindowRegistry, WindowConfig, LayoutComposer
- [x] Этап 5.5: WindowRegistry расширен (needs_*, filter_names, apply, close_all)
- [x] Этап 5.6: RegistersManager connection (connection_map, send_callback)
- [x] Этап 5.7: Компоненты (structured_table, table_with_toolbar, tab_widget, keyboard, keyboard_mini, header, performance_monitor)
- [x] Этап 5.8: Application (WindowManager, ThreadManager), windows/, widgets/; Coordinator удалён, логика в FrontendManager
- [x] Этап 6: FrontendManager (BaseManager), FrontendRegistersBridge, run_app/shutdown_app, GuiProcess интеграция, config hot-reload
- [ ] Этап 7: Unit-тесты
- [ ] Этап 8: Документация, ADR в DECISIONS.md

## Известные проблемы

- PyQt5 — зависимость от конкретного UI-фреймворка (пока приемлемо)

## История изменений

| Дата | Что сделано | Этап |
|------|-------------|------|
| 2026-03-24 | **ADR-089**: цепочка конфига UI — `SchemaBase` в прототипе, dataclass во фреймворке, адаптер на границе; merge/replace стилей; см. `multiprocess_framework/DECISIONS.md` | 6 |
| 2026-03-24 | **`styling/`**: встроенные QSS рядом с виджетами (`default_bundles`, `create_app_style_session`); прототип без дублирующих `qss/`/`token_bundles/`; ADR-088 | 6 |
| 2026-03-24 | **`styling/`**: QSS-слой (`StyleSession`, `NamedStyleRegistry`, каскад токенов), поля в `BaseControlConfig`, хук в `BaseConfigurableWidget`; пример `frontend/styles/`; ADR-086 | 6 |
| 2026-03-24 | **`TAB_STRUCTURE.md`** / **`mvp_pattern.py`**: ссылки на актуальные ADR и `multiprocess_prototype/docs/FRONTEND_MAP.md` (удалён устаревший план из `docs/` прототипа) | 6 |
| 2026-03-24 | **`StructuredTableWidget`**: при наличии **`_value_editable`** в строке данных — переопределение `editable` для текстовой ячейки (таблица рецептов в прототипе, ADR-080) | 6 |
| 2026-03-24 | **ADR-079**: `WidgetSignalBus` → `widgets/widget_signal_bus.py`; `TabWidget` + клавиатуры — шина событий; граница widgets vs components (tabs/tables не в components) | 6 |
| 2026-03-24 | **ADR-078**: `button_style` → `widgets/header/`; удалён пакет `widgets/base` (коллизия с `base_widget`) | 6 |
| 2026-03-24 | **ADR-077**: `components` = только контролы (flatten); `widgets` = tabs, base_widget, header, …; `MvpTabBase(BaseWidget)`; SimWebcamWidget + Model | 6 |
| 2026-03-24 | **BaseWidget** (`widgets/base_widget/`): MVP с опциональным Model; HikvisionWidget рефакторинг (ADR-076) | 6 |
| 2026-03-23 | Эталон вкладки в доках: `multiprocess_prototype/frontend/widgets/tabs_setting/camera_tab` (перенос из `widgets/camera_tab`) | 6 |
| 2026-03-23 | **ADR-073**: `TabPresenterBase` / `TabViewProtocol` (`tabs/mvp_pattern.py`); `CameraTabPresenter` на базовом классе; `processing_tab` — `IRegistersManagerGui` + `RegisterBindingContext`; реэкспорт tabs (с ADR-077 — из `widgets`); `test_tabs_callbacks.py` | 6 |
| 2026-03-23 | **tabs**: `callback_utils` влит в `callbacks_base.py`; `tab_callbacks_*` без ручного списка полей для `@dataclass`; `TabWidget` — тип `Dict[int, BaseTab]`; тесты переименованы в `test_tabs_callbacks.py` | 6 |
| 2026-03-23 | **ADR-072**: `callback_no_args`, `TAB_STRUCTURE.md`, `tabs/README.md`; camera_tab на `coerce_schema_config` | 6 |
| 2026-03-23 | **ADR-070**: primitives и common в v2-слое (исторически `control_v2/`); v1 удалён; затем flatten в `components/` (**ADR-077**) | 6 |
| 2026-03-23 | Примеры v2: убран `adapter_common`; примеры **numeric**, **group** (путь см. **ADR-077**: `components/examples/`) | 6 |
| 2026-03-23 | Пакет v2 вынесен из legacy `controls/`; примеры в `examples/`; ADR-069; документация ARCHITECTURE | 6 |
| 2026-03-23 | Controls v2: `group/labeled_numeric_factory.py` (ADR-068); фасады slider/spinbox — импорт фабрики без lazy | 6 |
| 2026-03-23 | Controls v2: `on_access_denied` / `ControlAccessDeniedEvent`; докстринги `hooks` у фасадов; ADR-067 доп. про фабрику групп | 6 |
| 2026-03-23 | Controls v2: `ControlHooks` + события записи; `SliderPresenter`/`SpinBoxPresenter`; фасады без прокси `NumericControl`; `test_controls_v2_hooks`; ADR-067; slider/base README | 6 |
| 2026-03-23 | `example_with_data_schema`: spinbox, compound_numeric (BGR), compound_mixed, label; v2 `SpinBoxControl` + lazy import в `spinbox/facade` | 6 |
| 2026-03-23 | Controls v2: `SchemaTrait.refresh()` / `_refresh_meta`, `AccessTrait.set_required_level`, `refresh_metadata` в Checkbox/Numeric presenter; тесты | 6 |
| 2026-03-23 | `example_with_data_schema`: `adapter_common`, исправлен циклический импорт slider, README | 6 |
| 2026-03-23 | `example_with_data_schema`: `BINDING_*` на `ExampleCheckboxValueRegister`; адаптер без модульных ключей | 6 |
| 2026-03-23 | Controls v2 `checkbox`: `IControlView[bool]` + порты в presenter, `RegistersManagerLike` в фасаде, README+Mermaid, экспорт View/Presenter, `test_checkbox_v2.py` | 6 |
| 2026-03-23 | Controls v2 `base`: порты `IFieldBinding` / `IRegisterPort` / `RegistersManagerLike`, README+Mermaid, ADR-064; `RegisterAdapter` ключ подписки с `index`; `test_controls_v2_base.py` | 6 |
| 2026-03-21 | Controls refactor: `common/field_sync.py` (единая publish_control_value_to_observers), `common/sizes.py` (VALUE_INPUT_*), `slider/legacy_sync.py` (publish_legacy_ui_refs); BaseConfigurableWidget без exclude; primitives→common; баг Tuple в layout_builder | 6 |
| 2026-03-21 | Controls: пакеты `slider/schema`, `checkbox/schema`; `value_mapping`, `field_sync`, `layout_builder`; README по компонентам; докстринги методов | 6 |
| 2026-03-21 | Controls: `coerce_schema_config`, primitives (label, numeric line edit, styled slider), `value_bridge`, typography/styles; конструктор только config+rm+parent; ADR-060 | 6 |
| 2026-03-21 | Рефакторинг SliderControl, CheckboxControl: RegisterBinding, ResolvedMeta, SliderConfig, CheckboxConfig; папка-на-компонент; BaseConfigurableWidget: config, _resolve_meta; ADR-059 | 6 |
| 2026-03-20 | `RoutedCommandSender` (`core/routed_command.py`), `SupportsCommandMessage` (interfaces), `run_process_attached_frontend` + `FrontendLaunchHooks`; ADR-058 | 6 |
| 2026-03-20 | README: примеры — `multiprocess_prototype.registers.schemas.processing_tab` | 6 |
| 2026-03-20 | FrontendManager: `queue_manager`, `stop_event` в `__init__` (без присвоения `_…` из приложения) | 6 |
| 2026-03-20 | FrontendRegistersBridge: в сообщение register_update добавлено `type: data` (согласованность с Message / Router) | 6 |
| 2026-03-20 | Документация registers_bridge: connection_map как fallback к register_dispatch (ADR-048) | 6 |
| 2026-03-20 | action_binding.connect_action_handlers, HeaderWidget.action_triggered, get_signal_map, AdminButtonConfig.action_id, HeaderButtonItem.action_id | 6 |
| 2026-03-19 | LoadingWindow, ImagePanelWidget, HeaderWidget (windows из конфига), ISignalProvider | 6 |
| 2026-03-19 | WindowManager: IConfig поддержка, _config_get для dot-notation | 6 |
| 2026-03-18 | Создание фундамента: структура, interfaces, README, STATUS | 0 |
| 2026-03-18 | BaseConfigurableWidget, WidgetDescriptor, WidgetRegistry, SliderControl, CheckboxControl | 4 |
| 2026-03-18 | WindowRegistry, WindowConfig, LayoutComposer (compose_layout) | 5 |
| 2026-03-18 | SliderControl: ui_elements, controls, callback, touch_keyboard_factory; QMessageBox; _show_touch_keyboard fix | 5 |
| 2026-03-18 | WindowRegistry: needs_*, filter_names, apply, close_all; RegistersManager: connection_map, subscribe_all, set_field_value | 5 |
| 2026-03-18 | Components: structured_table, table_with_toolbar, tab_widget, keyboard, keyboard_mini, header, performance_monitor | 5 |
| 2026-03-18 | Application: WindowManager, ThreadManager, Coordinator; windows/, widgets/ | 5 |
| 2026-03-18 | FrontendManager (BaseManager), FrontendRegistersBridge, config hot-reload, GuiProcess | 6 |
| 2026-03-18 | Рефакторинг: удалён Coordinator, qt_imports, _model_to_register_name; run_app/shutdown_app в FrontendManager | 6 |

*История: записи до 2026-03-24 с `control_v2` / `controls` как путём импорта отражают состояние до **ADR-077**; актуально — `frontend_module.components` (контролы) и `frontend_module.widgets` (вкладки, BaseWidget, шапка и т.д.).*
