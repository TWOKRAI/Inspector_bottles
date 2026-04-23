# План: Фаза 3 — Polish (Task 3.1 + Task 3.3)

**Дата:** 2026-04-23
**Статус:** DONE
**Источник:** METAPLAN_FIXES.md, раздел "Фаза 3"

## Обзор

Фаза 3 — качество жизни: watchdog-сигнализация при потере backend и защита от ошибок Qt thread-safety.
Task 3.1 даёт пользователю видимый сигнал о зависании/падении backend.
Task 3.3 добавляет декоратор-assertion для выявления cross-thread UI-вызовов в debug-режиме.

Зависимости: Task 1.4 (heartbeat/restart) **не реализован**, поэтому кнопка "Перезапустить"
в Task 3.1 отправляет `system.shutdown` (уже есть в каталоге) вместо `restart_all`.
`restart_all` добавляется в каталог как заглушка-forward на `system.shutdown` до готовности Task 1.4.

---

## Порядок выполнения

### Фаза A — Task 3.1 (независима)
- Task 3.1: GUI watchdog "Backend не отвечает" [DONE]

### Фаза B — Task 3.3 (независима, параллельно с 3.1)
- Task 3.3: Гарантия Qt thread safety [DONE]

---

## Детальные задачи

---

### Task 3.1 — P13: GUI watchdog "Backend не отвечает"

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** добавить в GuiProcess watchdog, который показывает жёлтый overlay после 5с без кадров и диалог перезапуска после 15с.

**Контекст архитектуры:**
- `GuiProcess._handle_new_frame(data)` вызывается при каждом `rendered_frame_ready` (строка 111 в `process.py`). Именно здесь нужно обновлять `last_frame_time = time.time()`.
- `_poll_messages()` вызывается QTimer каждые 16мс (строка 179 `launcher.py`). Здесь — проверять дельту.
- `self._window` — ссылка на `MainWindow` (строка 69 `process.py`, устанавливается в `launcher.py` строка 177).
- `MainWindow` содержит `_image_panel: ImagePanelWidget` (строки 337-351 `window.py`). Overlay нужен **поверх** image_panel.
- Кнопка перезапуска: `system.shutdown` уже зарегистрирован в `EXPLICIT_COMMAND_TARGETS` (`routing.py` строка 30) и реализован в `GuiCommandHandler.send_shutdown()`. До реализации Task 1.4 watchdog вызывает shutdown, не restart.
- `restart_all` в `GUI_COMMAND_CATALOG` и `EXPLICIT_COMMAND_TARGETS` **отсутствует** — добавляем как alias для `system.shutdown`.

**Файлы:**

| Файл (от корня `multiprocess_prototype_v3/`) | Действие |
|---|---|
| `backend/processes/gui/process.py` | добавить `_last_frame_time`, `_watchdog_state`, метод `_check_watchdog()`, вызов в `_poll_messages()` и `_handle_new_frame()` |
| `frontend/widgets/watchdog_overlay/widget.py` | **создать** — `WatchdogOverlay(QWidget)` |
| `frontend/widgets/watchdog_overlay/__init__.py` | **создать** — реэкспорт |
| `frontend/windows/main_window/window.py` | добавить методы `show_watchdog_warning()`, `show_watchdog_dialog()`, `hide_watchdog()` |
| `registers/commands/catalog.py` | добавить `restart_all: _args_empty` |
| `registers/commands/routing.py` | добавить `"restart_all": ["ProcessManager"]` в `EXPLICIT_COMMAND_TARGETS` |
| `frontend/commands/gui_command_handler.py` | добавить `send_restart_all() -> bool` |

**Шаги:**

1. **`WatchdogOverlay`** — создать `frontend/widgets/watchdog_overlay/widget.py`:
   - Класс `WatchdogOverlay(QWidget)` — полупрозрачный overlay поверх родительского виджета.
   - Конструктор `__init__(self, parent: QWidget)`: `super().__init__(parent)`, установить `Qt.WindowType: Qt.SubWindow` или просто позиционировать поверх parent через `resizeEvent`.
   - Метод `show_warning(text: str = "Ожидание backend...")` — жёлтый фон (`rgba(255, 200, 0, 180)`), крупный QLabel с текстом, `self.show()`.
   - Метод `hide_overlay()` — `self.hide()`.
   - Переопределить `resizeEvent` родителя не нужен — overlay сам подписывается через `parent.resizeEvent` или принимает обновление размера снаружи.
   - В `__init__.py`: `from .widget import WatchdogOverlay; __all__ = ["WatchdogOverlay"]`.

2. **`MainWindow`** — добавить в `frontend/windows/main_window/window.py`:
   - В `_build_ui()` (или в `__init__`) создать `self._watchdog_overlay = WatchdogOverlay(self._image_panel)` (родитель — `_image_panel`, не весь MainWindow).
   - `show_watchdog_warning(text: str)` — вызвать `self._watchdog_overlay.show_warning(text)` и обновить размер overlay до размера `_image_panel`.
   - `hide_watchdog()` — `self._watchdog_overlay.hide_overlay()`.
   - `show_watchdog_dialog()` — создать `QMessageBox` с текстом "Backend не отвечает. Перезапустить?", кнопками Yes/No. При Yes — вызвать callback `self._on_restart_requested` (передаётся снаружи). Если callback не задан — `pass`.
   - Добавить в `__init__` параметр `on_restart_requested: Callable[[], None] | None = None` и сохранить в `self._on_restart_requested`.

3. **`GuiProcess`** — добавить в `backend/processes/gui/process.py`:
   - В `_init_application_threads()`: `self._last_frame_time: float = 0.0`, `self._watchdog_state: str = "ok"` (значения: `"ok"`, `"warning"`, `"dialog_shown"`).
   - В конце `_handle_new_frame(data)`: `self._last_frame_time = time.time()` и `self._reset_watchdog()`.
   - Новый метод `_reset_watchdog()`: если `_watchdog_state != "ok"` → `self._watchdog_state = "ok"` и `self._window.hide_watchdog()` (с guard `if self._window`).
   - Новый метод `_check_watchdog()`:
     ```
     if self._last_frame_time == 0.0:
         return  # GUI ещё не получил ни одного кадра — не тревожить
     elapsed = time.time() - self._last_frame_time
     if elapsed > 15.0 and self._watchdog_state != "dialog_shown":
         self._watchdog_state = "dialog_shown"
         if self._window:
             self._window.show_watchdog_dialog()
     elif elapsed > 5.0 and self._watchdog_state == "ok":
         self._watchdog_state = "warning"
         if self._window:
             self._window.show_watchdog_warning("Ожидание backend...")
     ```
   - В `_poll_messages()` — добавить вызов `self._check_watchdog()` **после** обработки всех сообщений.

4. **Каталог команд** — добавить `restart_all`:
   - `registers/commands/catalog.py`: добавить `"restart_all": _args_empty` в `GUI_COMMAND_CATALOG`.
   - `registers/commands/routing.py`: добавить `"restart_all": ["ProcessManager"]` в `EXPLICIT_COMMAND_TARGETS`.
   - `frontend/commands/gui_command_handler.py`: добавить метод `send_restart_all() -> bool: return self.execute("restart_all")`.

5. **Подключение callback в launcher** — `frontend/launcher.py`:
   - В `create_main_window()`: передать `on_restart_requested=lambda: cmd.send_restart_all()` в конструктор `MainWindow`.
   - Убедиться что `MainWindow.__init__` принимает этот параметр (шаг 2).

**Критерии приёмки:**
- [ ] Запустить prototype, остановить backend-процессы вручную (или заблокировать renderer) — через 5с на image_panel появляется жёлтый overlay с текстом "Ожидание backend..."
- [ ] Через 15с появляется `QMessageBox` с кнопкой "Перезапустить?"
- [ ] При возобновлении кадров (если backend ожил раньше 15с) — overlay исчезает, `_watchdog_state` возвращается в `"ok"`
- [ ] При старте приложения (до первого кадра) — overlay НЕ появляется (`_last_frame_time == 0.0`)
- [ ] `restart_all` присутствует в `GUI_COMMAND_CATALOG` и `EXPLICIT_COMMAND_TARGETS`
- [ ] `GuiCommandHandler.send_restart_all()` существует и возвращает `bool`

**Вне scope:**
- НЕ реализовывать реальный механизм перезапуска процессов (это Task 1.4)
- НЕ добавлять overlay в `DisplayWindow` — только в `MainWindow._image_panel`
- НЕ трогать polling QTimer (интервал остаётся 16мс)
- НЕ добавлять тесты (отдельная задача Tester если потребуется)

**Граничные случаи:**
- `self._window` может быть `None` (до инициализации MainWindow) — все вызовы через guard `if self._window`
- `elapsed` вычисляется только если `_last_frame_time > 0` — защищает от ложной тревоги при старте
- `dialog_shown` — повторный вызов `show_watchdog_dialog()` при каждом тике НЕ происходит (guard `!= "dialog_shown"`)
- Если пользователь нажал "Нет" в диалоге — `_watchdog_state` остаётся `"dialog_shown"`, диалог не всплывает повторно до ожива backend

**Зависимости:** нет (Task 1.4 не требуется — используем `system.shutdown` как fallback)

---

### Task 3.3 — P12: Гарантия Qt thread safety

**Уровень:** Middle (Sonnet, normal thinking)
**Исполнитель:** developer
**Цель:** создать декоратор `@ensure_main_thread` и применить к критичным методам обновления виджетов для выявления cross-thread UI-вызовов в debug-режиме.

**Контекст архитектуры:**
- Все обновления виджетов (`update_frame`, `update_latency`, `update_camera_status`, etc.) вызываются из `GuiProcess._poll_messages()`, который триггерится QTimer в main thread (строка 179 `launcher.py`). Формально безопасно.
- `DisplayWindow.update_frame()` вызывается через `display_router` → `add_frame_callback` (`window_manager.py` строка 112) — callback привязывается к виджету из main thread, вызывается тоже из main thread через QTimer.
- Потенциальная опасность: если в будущем кто-то вызовет `window.update_frame()` из фонового QThread или воркера — PyQt5 упадёт или зависнет без диагностики.
- Декоратор нужен только для **debug-режима** (не нагружать prod). Активация: переменная окружения `INSPECTOR_DEBUG_QT=1` или аргумент командной строки.
- `FrontendAppContext` (`frontend/app_context.py`) — удобное место для хранения `debug_qt: bool` флага, но декоратор должен быть **независимым утилитным модулем**, не завязанным на контекст.

**Файлы:**

| Файл (от корня `multiprocess_prototype_v3/`) | Действие |
|---|---|
| `frontend/utils/qt_thread_guard.py` | **создать** — декоратор `ensure_main_thread` |
| `frontend/utils/__init__.py` | **создать или обновить** — реэкспорт |
| `frontend/windows/main_window/window.py` | применить `@ensure_main_thread` к методам обновления |
| `frontend/widgets/display_window/widget.py` | применить `@ensure_main_thread` к `update_frame` |

**Шаги:**

1. **`frontend/utils/qt_thread_guard.py`** — создать модуль:
   - Импорты: `import os`, `import functools`, `from PyQt5.QtCore import QThread`, `from PyQt5.QtWidgets import QApplication`.
   - Константа `_DEBUG_QT: bool = os.environ.get("INSPECTOR_DEBUG_QT", "0") == "1"`.
   - Функция `ensure_main_thread(func)`:
     ```python
     def ensure_main_thread(func):
         @functools.wraps(func)
         def wrapper(*args, **kwargs):
             if _DEBUG_QT:
                 app = QApplication.instance()
                 if app is not None:
                     assert QThread.currentThread() == app.thread(), (
                         f"{func.__qualname__} вызван не из main thread! "
                         f"Текущий поток: {QThread.currentThread()}"
                     )
             return func(*args, **kwargs)
         return wrapper
     ```
   - Экспортировать: `__all__ = ["ensure_main_thread"]`.

2. **`frontend/utils/__init__.py`**:
   - Если файл не существует — создать: `from .qt_thread_guard import ensure_main_thread; __all__ = ["ensure_main_thread"]`.
   - Если существует — добавить строку реэкспорта.

3. **Применить к `MainWindow`** в `frontend/windows/main_window/window.py`:
   - Добавить импорт: `from multiprocess_prototype_v3.frontend.utils import ensure_main_thread`.
   - Декорировать следующие методы (все — публичные update-методы, вызываемые из GuiProcess):
     - `update_frame`
     - `update_latency`
     - `update_camera_status`
     - `update_camera_error`
     - `update_camera_fps`
     - `update_camera_devices`
     - `update_camera_parameters`
     - `update_camera_resolution`
     - `sync_camera_type`
   - Синтаксис: разместить `@ensure_main_thread` непосредственно перед `def`.

4. **Применить к `DisplayWindow`** в `frontend/widgets/display_window/widget.py`:
   - Добавить импорт: `from multiprocess_prototype_v3.frontend.utils import ensure_main_thread`.
   - Декорировать `update_frame(self, frame: np.ndarray)`.

5. **Документация**: в `frontend/utils/qt_thread_guard.py` добавить docstring модуля:
   ```
   Утилита Qt thread safety для debug-режима.
   Активация: установить переменную окружения INSPECTOR_DEBUG_QT=1.
   В prod (_DEBUG_QT=False) декоратор — zero-overhead wrapper.
   ```

**Критерии приёмки:**
- [ ] `frontend/utils/qt_thread_guard.py` существует, импортируется без ошибок
- [ ] `ensure_main_thread` — обычная функция-декоратор (не класс), `functools.wraps` сохраняет `__name__` и `__doc__`
- [ ] При `INSPECTOR_DEBUG_QT=0` (или переменная не задана) — декоратор не делает assertion, вызов функции происходит без overhead кроме одного `if`
- [ ] При `INSPECTOR_DEBUG_QT=1` вызов декорированного метода из main thread — работает нормально, без исключений
- [ ] `MainWindow.update_frame`, `update_latency` и ещё 7 методов декорированы
- [ ] `DisplayWindow.update_frame` декорирован
- [ ] Grep `@ensure_main_thread` в `window.py` показывает ≥ 9 вхождений
- [ ] Grep `@ensure_main_thread` в `display_window/widget.py` показывает 1 вхождение

**Вне scope:**
- НЕ добавлять `QMetaObject.invokeMethod` или `QApplication.postEvent` — только assertion, не автоматическое переключение потока
- НЕ декорировать приватные методы (`_build_ui`, `_refresh_resolution_status` и т.д.)
- НЕ трогать виджеты за пределами `MainWindow` и `DisplayWindow` (камерные виджеты, вкладки — отдельный аудит при необходимости)
- НЕ изменять `FrontendAppContext` — флаг debug хранится только в env переменной

**Граничные случаи:**
- `QApplication.instance()` может вернуть `None` в тестах без Qt event loop — guard `if app is not None` обязателен
- Если файл `frontend/utils/__init__.py` уже существует с другим содержимым — добавить строку, не перезаписывать
- `_DEBUG_QT` вычисляется один раз при импорте модуля — это корректно, env переменная должна быть задана до запуска

**Зависимости:** нет (независима от Task 3.1)

---

## Риски и ограничения

1. **Task 3.1**: `MainWindow.__init__` принимает именованные аргументы через `**kwargs` паттерн в нескольких местах — нужно аккуратно добавить `on_restart_requested` не сломав существующие вызовы в тестах.
2. **Task 3.1**: Overlay на `_image_panel` требует чтобы `_image_panel` существовал к моменту создания overlay. Убедиться что `WatchdogOverlay(self._image_panel)` создаётся **после** `_build_ui()`.
3. **Task 3.3**: `ensure_main_thread` должен быть импортирован как `from multiprocess_prototype_v3.frontend.utils import ensure_main_thread` — абсолютный импорт, не relative, иначе конфликт при запуске через `main.py`.
