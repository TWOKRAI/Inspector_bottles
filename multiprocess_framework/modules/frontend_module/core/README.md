# core — базовые классы и утилиты frontend_module

Слой, не зависящий от Qt: маршрутизация команд, регистры-бридж, импорты Qt, интерфейсы. Размещается отдельно чтобы не подтягивать Qt в зависимости.

## Ключевые символы

- `RoutedCommandSender` — сборка COMMAND-сообщений и отправка первому получателю из маршрута.
- `FrontendRegistersBridge` — адаптер между GuiState и RegistersManager.
- `qt_imports` — централизованные импорты Qt (вежливая обработка missing PySide6).
- `qt_lifetime` — владение Qt-объектами через область (Task 0.4, Stability: lite; см. раздел ниже).
- `qt_gc_policy` — политика памяти GUI-процесса: сборкой `gc` владеет главный поток Qt (T1, ADR-PM-053, Stability: lite; см. раздел ниже).

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

## Политика памяти GUI (`qt_gc_policy`)

Автосборка `gc` в GUI-процессе выключена; сборку зовёт `QTimer(parent=app)` на потоке
`QCoreApplication` и явные границы. Финализаторы Qt-обёрток не исполняются на рабочих потоках.
Ядро — `process_module/lifecycle/gc_discipline.py` (`collect_on`, слот процесса); этот модуль —
тонкий адаптер, прямых вызовов `gc.*` в нём нет.

- `install_gui_memory_policy(app=None, *, interval_s=1.0, freeze=None, freeze_after_s=5.0, observe=False, log=None)` —
  только с потока `QCoreApplication` (иначе `RuntimeError`, и при повторе). Повтор — тот же объект,
  `rearm_freeze()`, таймер подключается, если приложение уже есть.
- `gui_memory_policy()` — установленная политика или `None`.
- `GuiMemoryPolicy.collect_now()` — `enforce()`, полная сборка; вне цикла событий
  (`loopLevel() == 0`) — ещё `flush_deferred_deletes()`. Внутри цикла — без flush, без ошибки.
- `stats()` — 13 счётчиков ядра + `timer_attached`; `uninstall()` — повтор no-op.

Точки включения: `multiprocess_prototype/frontend/app.py::run_gui` (выкл. — `INSPECTOR_GUI_GC_POLICY=0`,
наблюдаемость — `INSPECTOR_GC_OBSERVE=1`); фикстуры `_gui_memory_policy` / `_gui_memory_boundary` в
`multiprocess_framework/modules/conftest.py` и корневом `conftest.py`. В тестах вместо `gc.collect()` —
`gui_memory_policy().collect_now()`, вместо `gc.disable()/gc.enable()` — `paused_gc()` (страж
`tests/test_gc_policy_guard.py`).
