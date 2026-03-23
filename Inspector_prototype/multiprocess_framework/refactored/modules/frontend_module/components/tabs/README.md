# Tabs — TabWidget, BaseTab, MvpTabBase, RegisterBindingContext

Компоненты для вкладок главного окна.

## Экспорты

| Символ | Описание |
|--------|----------|
| `BaseTab` | Базовый класс виджета вкладки с хуками `on_tab_selected` / `on_tab_deselected` |
| `MvpTabBase` | Фасад для MVP-вкладок: _coerce_callbacks → _coerce_ui → _init_ui → _create_presenter → _on_presenter_ready |
| `TabWidget` | Внешний виджет с QTabWidget и кнопкой сворачивания |
| `RegisterBindingContext` | Контекст привязки к регистрам для секций (can_bind, rm) |
| `create_registers_placeholder` | Заглушка при отсутствии RegistersManager (единые текст и стили) |
| `callback_no_args` | Обёртка для Qt-сигналов: игнорирует аргумент, вызывает `fn()` |
| `tab_callbacks_from_dict` / `tab_callbacks_to_dict` | Утилиты для frozen dataclass колбэков |
| `TabViewProtocol` | Маркер для Protocol вью вкладки (см. `mvp_pattern.py`) |
| `TabPresenterBase` | Базовый презентер: `_view`, `_rm`, `_ui` |

## Шаблон структуры вкладки

См. **[TAB_STRUCTURE.md](TAB_STRUCTURE.md)** — рекомендации по организации вкладок.  
**[MVP_TEMPLATE.md](MVP_TEMPLATE.md)** — копировать для новой MVP-вкладки.  
Эталон — `multiprocess_prototype/frontend/widgets/camera_tab`.
