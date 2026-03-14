# console_module

Менеджер терминальных окон процесса. Управляет терминальным I/O: показывает/скрывает окна, перехватывает stdout/stderr, читает ввод и передаёт его в CommandManager.

---

## Импорты

```python
from Inspector_prototype.multiprocess_framework.refactored.modules.console_module import (
    ConsoleManager,
    ConsoleConfig,
    ConsoleAdapter,
    ConsoleLogChannel,
    ConsoleProcessConfig,
)
from Inspector_prototype.multiprocess_framework.refactored.modules.console_module.interfaces import (
    IConsoleManager,
    IPlatformConsole,
)
```

## Точки входа

| Класс/функция | Метод | Описание |
|---------------|-------|----------|
| ConsoleManager | `initialize()` | Инициализация, создание платформенного терминала |
| ConsoleManager | `shutdown()` | Закрытие терминала, восстановление stdout/stderr |
| ConsoleManager | `show()` / `hide()` | Показать/скрыть основной терминал |
| ConsoleManager | `write(text, level, console_name)` | Вывести текст в терминал |
| ConsoleManager | `create_console(name, title)` | Создать дополнительное окно |
| ConsoleManager | `enable_input(callback)` | Запустить чтение stdin, callback(line) при вводе |
| ConsoleManager | `setup_redirect(enabled)` | Перехватить/восстановить stdout/stderr |
| ConsoleAdapter | `setup(managers, config)` | Интеграция с LoggerManager и CommandManager |

## Зависимости

- **Зависит от:** `base_manager`, `data_schema_module`, `logger_module` (ILogChannel)
- **Используется в:** `process_module`, `process_manager_module`

## Концепция

`ConsoleManager` управляет терминалами процесса:

1. **Основной терминал** — каждый процесс имеет свой терминал. ConsoleManager показывает/скрывает его, направляет вывод, читает ввод.
2. **Дополнительные терминалы** — можно создать ещё одно консольное окно через `create_console(name, title)`.
3. **God Mode** — отдельный процесс-консоль для управления всей системой.

ConsoleManager **НЕ** логирует (это `LoggerManager`), **НЕ** парсит команды (это `CommandManager`), **НЕ** маршрутизирует (это `RouterManager`). Он предоставляет «экран» — терминальное I/O.

## Три уровня использования

### Уровень 1 — Пассивный (конфиг)

```python
config = {
    "managers": {
        "console": {
            "enabled": True,          # показать терминал
            "redirect_stdout": True,  # перехватить stdout/stderr
        }
    }
}
```

### Уровень 2 — Активный (runtime)

```python
process.console_manager.show()
process.console_manager.hide()
process.console_manager.write("custom message\n", level="INFO")
process.console_manager.create_console("debug", title="Debug Window")
```

### Уровень 3 — God Mode

```python
from console_module import ConsoleProcessConfig
from process_manager_module import SystemLauncher

launcher = SystemLauncher()
launcher.add_process(*process(ConsoleProcessConfig()))  # интерактивная консоль
launcher.add_process(*process(MyWorkerConfig()))        # рабочий процесс
launcher.run()
```

God Mode — просто `ConsoleConfig(enabled=True, interactive=True)`. Ввод → `CommandManager` → `RouterManager` → любой процесс.

## Структура модуля

```
console_module/
  __init__.py                    # Публичный API
  interfaces.py                  # IConsoleManager, IPlatformConsole
  STATUS.md
  README.md
  core/
    console_manager.py           # ConsoleManager (BaseManager + ObservableMixin)
    console_config.py            # ConsoleConfig(SchemaBase)
  channels/
    console_log_channel.py       # ConsoleLogChannel(ILogChannel)
  redirectors/
    console_redirector.py        # ConsoleRedirector
  adapters/
    console_adapter.py           # ConsoleAdapter(BaseAdapter)
  configs/
    console_process_config.py    # ConsoleProcessConfig — God Mode
  platforms/
    __init__.py                  # create_platform_console() фабрика
    base.py                      # re-export IPlatformConsole
    windows.py                   # WindowsConsole
    unix.py                      # UnixConsole (Linux/macOS)
  tests/
    test_console_manager.py
    test_console_log_channel.py
    test_console_redirector.py
    test_console_adapter.py
    test_platforms.py
```

## Кроссплатформенность

| Платформа | Основной терминал | Дополнительные окна | show/hide |
|-----------|-------------------|---------------------|-----------|
| Windows   | ctypes WinAPI     | AllocConsole / subprocess | ShowWindow |
| Linux + GUI | print-based | xterm / gnome-terminal | флаг `_visible` |
| Linux headless | print-based | не поддерживается | флаг `_visible` |
| macOS     | print-based       | open -a Terminal | флаг `_visible` |

## Связь с другими модулями

```
console_module
    │
    ├── использует → base_manager (BaseManager)
    ├── использует → data_schema_module (SchemaBase)
    ├── использует → logger_module (ILogChannel)
    │
    └── используется в → process_module (ProcessManagers)
    └── используется в → process_manager_module (God Mode)
```

## Интеграция

### LoggerManager → ConsoleManager

`ConsoleLogChannel` добавляется в `LoggerManager` через `ConsoleAdapter.setup()` когда `console.enabled = True`.

### ConsoleManager → CommandManager

Input loop читает stdin → `command_manager.handle_command({"command": text, "source": "console"})`.

### ProcessModule

ConsoleManager создаётся автоматически в `ProcessManagers.initialize()`. По умолчанию — `enabled=False` (пассивный режим).

## Минимальный пример (standalone)

```python
from Inspector_prototype.multiprocess_framework.refactored.modules.console_module import (
    ConsoleManager,
    ConsoleConfig,
)

cfg = ConsoleConfig(enabled=True, redirect_stdout=False)
mgr = ConsoleManager(manager_name="demo", config=cfg)
mgr.initialize()
mgr.write("Hello from ConsoleManager\n", level="INFO")
mgr.shutdown()
```

## Запуск тестов

```bash
# Из корня Inspector_bottles (с активированным venv)
python Inspector_prototype/multiprocess_framework/refactored/run_all_tests.py --module console_module

# Или напрямую pytest
python -m pytest Inspector_prototype/multiprocess_framework/refactored/modules/console_module/tests/ -v
```

**Зависимости для тестов:** `pydantic`, `PyYAML`, `pytest` (см. `requirements.txt` в корне проекта).

## Примечания

- **Linux headless:** `supports_multiple_windows()` → False, `create_console()` вернёт False
- **enable_input()** блокирует поток: `read_input()` вызывает `input()`, на Windows не прерывается сигналами
- **Windows WinAPI:** базовая реализация через ctypes; дополнительные окна — через subprocess при необходимости
