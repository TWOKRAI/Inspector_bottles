# Styling (QSS)

Каскад токенов для Qt Style Sheets:

1. **Дефолты `style_id`** — `NamedStyleRegistry.register("slider", template, default_tokens)`.
2. **Глобальная палитра** — `StyleSession.set_global_tokens({...})` (все зарегистрированные виджеты).
3. **`widget_layer`** — оболочка: вкладка, панель, `MainWindow` (передаётся в `register` или `style_widget_tokens` в конфиге).
4. **`component_layer`** — конкретный контрол (`style_tokens` в `BaseControlConfig`).

Правее в списке — сильнее: переопределения компонента бьют палитру, палитра бьёт дефолты именованного стиля.

## Пример

```python
from frontend_module.styling import NamedStyleRegistry, StyleSession

reg = NamedStyleRegistry()
reg.register("demo", "QWidget {{ background: {bg}; color: {fg}; }}", {"bg": "#1e1e1e", "fg": "#ccc"})

session = StyleSession(registry=reg)
session.set_global_tokens({"fg": "#ffffff"})
session.set_global_qss("QToolTip { color: #000; }")  # опционально, на всё приложение

session.register(
    widget,
    style_id="demo",
    widget_layer={"bg": "#2d2d2d"},
    component_layer={"bg": "#333333"},
)
session.refresh("demo")  # после смены токенов в рантайме
```

Шаблоны — плейсхолдеры `{token}`; см. `render_qss`.

## Встроенные стили приложения

- Список и дефолтные токены: `default_bundles.py` (`StyleBundleSpec`, `register_default_bundles`).
- Файлы `.qss` лежат рядом с виджетами/компонентами, например `widgets/keyboard/styles/`, `widgets/tabs/styles/`, `components/common/qss/`.
- Готовая сессия с темой из dict: `create_app_style_session(ui_theme)` в `app_style_session.py` (прототип передаёт `config["ui_theme"]`).

## Конфиг контрола

В `BaseControlConfig`: `style_id`, при необходимости `style_qss_template` / `style_qss_path`, `style_widget_tokens`, `style_tokens`. Нужны `StyleSession` в аргументе конструктора или атрибут `style_session` у предка (например главного окна).

## Граница с приложением (прототип)

Pydantic-схемы (`SchemaBase`) и адаптеры «схема → dataclass» живут в **приложении**, не в `frontend_module`. Режимы merge/replace стилей и единая цепочка dict → schema → adapter → конфиг контрола зафиксированы в **ADR-089** (`multiprocess_framework/DECISIONS.md`).
