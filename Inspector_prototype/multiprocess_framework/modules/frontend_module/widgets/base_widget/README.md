# BaseWidget — базовый MVP-виджет

Общий каркас для виджетов по паттерну MVP (Model–View–Presenter) с опциональным слоем Model.

## Связь с MvpTabBase

**MvpTabBase** наследует **BaseWidget** и по умолчанию делает `_connect_signals` пустым (презентер подключается при создании или в `_on_presenter_ready`). Для полного flow с отдельным шагом привязки кнопок используйте **BaseWidget** и реализуйте `_connect_signals` (как HikvisionWidget).

## Жизненный цикл

```
__init__:
  1. _coerce_callbacks(callbacks)
  2. _coerce_ui(ui)
  3. _create_model()  → self._model (или None)
  4. _init_ui()       → построить Qt-дерево
  5. _create_presenter(model)
  6. _connect_signals()
  7. _on_presenter_ready(**kwargs)
```

## Generic и тип модели

```python
class MyWidget(BaseWidget[MyModel]):
    def _create_model(self) -> MyModel:
        return MyModel(...)

    def _create_presenter(self, model: Optional[MyModel]) -> MyPresenter:
        assert model is not None
        return MyPresenter(view=self, model=model, ui=self._ui)
```

## События для внешних подписчиков

- **`signal_bus`**: `WidgetSignalBus` — `event_emitted(str, object)` (event_id, payload).
- **`emit_widget_event(event_id, payload)`** — короткий вызов из подкласса.

Пример: `widget.signal_bus.event_emitted.connect(lambda e, p: logger.info("%s %s", e, p))`

## Шаблон для подкласса

```python
class MyWidget(BaseWidget[MyModel]):
    def _coerce_callbacks(self, callbacks):
        return callbacks or MyCallbacks()

    def _coerce_ui(self, ui):
        return coerce_schema_config(ui, MyUiConfig)

    def _create_model(self):
        return MyModel(rm=self._registers_manager, callbacks=self._callbacks, ui=self._ui)

    def _init_ui(self):
        # Только виджеты и layout, без connect
        layout = QVBoxLayout(self)
        self._button = QPushButton("...")
        layout.addWidget(self._button)

    def _create_presenter(self, model):
        return MyPresenter(view=self, model=model, ui=self._ui)

    def _connect_signals(self):
        self._button.clicked.connect(self._presenter.on_button_clicked)
```

## Пассивный View

View не должен вызываться презентером для «опроса» (например `get_selected_index()` при клике). Вместо этого:

- View эмитит сигналы с данными: `open_requested = pyqtSignal(int)`
- Слот View при клике: `self.open_requested.emit(self._list.currentRow())`
- Presenter подписан на `view.open_requested` и получает индекс

## Использование

- В TabWidget: BaseWidget наследует BaseTab → `add_tab(my_widget, "Title")` работает, хуки `on_tab_selected` доступны.
- В QStackedWidget, диалогах, боковых панелях — без ограничений.
