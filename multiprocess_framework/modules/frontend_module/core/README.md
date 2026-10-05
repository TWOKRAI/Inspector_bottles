# core — базовые классы и утилиты frontend_module

Слой, не зависящий от Qt: маршрутизация команд, регистры-бридж, импорты Qt, интерфейсы. Размещается отдельно чтобы не подтягивать Qt в зависимости.

## Ключевые символы

- `RoutedCommandSender` — сборка COMMAND-сообщений и отправка первому получателю из маршрута.
- `FrontendRegistersBridge` — адаптер между GuiState и RegistersManager.
- `qt_imports` — централизованные импорты Qt (вежливая обработка missing PySide6).
- `qt_lifetime` — владение Qt-объектами через область (Task 0.4, Stability: lite; см. раздел ниже).

## Владение Qt-объектами (`qt_lifetime`)

Связь области владения base_manager (`IScope`) с `QObject`/`QThread`. Импорт — из
`frontend_module.interfaces`.

- `attach_qt(scope, obj, *, name=None) -> IHandle` — запись вида `"qobject"`, имя по умолчанию
  `<Тип>#n`. Закрытие области зовёт `obj.deleteLater()`: объект уходит во владение C++ и
  удаляется на своём потоке. Qt удалил объект первым — область закрывается синхронно.
  Закрытая область: объект освобождается, бросается `ScopeClosedError`.
- Проверка Qt-предка: Qt-родитель привязанного объекта обязан быть объектом этой области или
  её предка (не соседа, не потомка). Иначе `close` даёт пару `qt-tree mismatch` в `errors`.
  Объект без родителя — всегда совпадение. Проверка только на потоке объекта: закрывайте
  GUI-области на GUI-потоке.
- `flush_deferred_deletes()` — выполнить отложенные удаления без цикла событий (после
  `app.exec()`, в тестах). Только поток `QCoreApplication`. Доставляет только `DeferredDelete`.
- `QThreadHandle(thread, *, stop=None)` — `Stoppable` для `IScope.own`: `requestInterruption`,
  `quit`, `stop()` один раз; ожидание к сроку. `kill` нет: не остановившийся поток — выживший.
  Регистрируйте ручку потока ДО объектов этого потока (LIFO).

Пример:

```python
from multiprocess_framework.modules.frontend_module.interfaces import attach_qt, flush_deferred_deletes

timer = QTimer()
attach_qt(scope, timer, name="poll")
...
scope.close()               # timer.deleteLater()
flush_deferred_deletes()    # удаление без цикла событий
```

## Stability

contract

→ Корневой README: `../../README.md`
