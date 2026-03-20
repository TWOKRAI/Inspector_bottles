# frontend_module — Статус рефакторинга

## Текущий этап: 6 / 8

## Оценки (0-10)

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| Код (читаемость, стандарты) | 8 | FrontendManager, FrontendRegistersBridge; Coordinator удалён |
| Тесты (покрытие) | 2 | Ручная проверка, unit-тесты планируются |
| Документация (README, interfaces) | 7 | README, interfaces, STATUS, ADR |
| Связанность (меньше = лучше) | 8 | data_schema, registers_module; схемы регистров — в приложении |
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
