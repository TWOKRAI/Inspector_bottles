# command_module

Тонкая обёртка над `dispatch_module`. `CommandManager` регистрирует обработчики под именами команд и вызывает `handle_command()` на каждом входящем сообщении. Полная мощь `Dispatcher` (4 стратегии, сценарии) доступна через `register_command(strategy=...)`.

---

## Структура модуля

```
command_module/
├── interfaces.py              ← ЕДИНСТВЕННЫЙ публичный контракт (ICommandManager)
├── __init__.py                ← Публичный API (CommandManager, CommandAdapter, ...)
│
├── core/
│   ├── command_manager.py     ← Фасад (BaseManager + ObservableMixin) — основной класс
│   └── base_command_manager.py← Лёгкий конкретный менеджер без ObservableMixin
│
├── adapters/
│   └── command_adapter.py     ← CommandAdapter — интеграция с ProcessModule
│
└── tests/
    ├── test_command_manager.py
    ├── test_base_command_manager.py
    └── test_command_adapter.py
```

---

## Как работает

```
handle_command(message)
    └─ dispatcher.dispatch(message, key_field="command", data_field="data")
            └─ EXACT / FALLBACK / PATTERN / CHAIN — те же стратегии что в dispatch_module
```

`CommandManager` — это `Dispatcher` с именованным API для команд. Разница только в терминологии: `register_command` вместо `register_handler`, `handle_command` вместо `dispatch`.

---

## Быстрый старт

```python
from multiprocess_framework.refactored.modules.command_module import CommandManager

manager = CommandManager("my_process")
manager.initialize()

manager.register_command("set_fps", lambda data: set_fps(data["fps"]))
manager.register_command("ping",    lambda data: {"pong": True})

result = manager.handle_command({"command": "set_fps", "data": {"fps": 30}})

manager.shutdown()
```

---

## API CommandManager

### Жизненный цикл

| Метод | Описание |
|-------|----------|
| `initialize()` | Инициализирует внутренний `Dispatcher`. Вернуть `True` при успехе. |
| `shutdown()` | Завершает `Dispatcher`, освобождает ресурсы. |

### Регистрация команд

| Метод | Описание |
|-------|----------|
| `register_command(name, handler, ...)` | Зарегистрировать команду. По умолчанию `EXACT_MATCH`. |
| `overwrite_command(name, handler, ...)` | Принудительная перезапись во всех стратегиях. |

**Параметры `register_command`:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `command_name` | `str` | Имя команды (ключ в `msg["command"]`) |
| `handler` | `Callable` | `fn(data) -> Any` или `fn(message) -> Any` |
| `expects_full_message` | `bool` | Если `True` — handler получает всё сообщение |
| `efficiency` | `int` | Приоритет для `FALLBACK_MATCH` |
| `tags` | `List[str]` | Теги для группировки |
| `strategy` | `DispatchStrategy` | Стратегия (`None` → `EXACT_MATCH`) |

### Выполнение команд

| Метод | Описание |
|-------|----------|
| `handle_command(message)` | Найти и вызвать обработчик. Вернуть результат или `{"status": "error", ...}`. |

**Обработка ошибок:** исключения внутри обработчика перехватываются `Dispatcher` → возвращается `{"status": "error", "reason": "..."}`.

### Запросы

| Метод | Описание |
|-------|----------|
| `get_commands()` | Список всех зарегистрированных команд из всех стратегий. |
| `get_command_info(name)` | Информация о конкретной команде или `None`. |
| `get_commands_by_tag(tag)` | Команды по тегу. |
| `get_stats()` | Статистика: `total_commands`, `commands`, `process_name`. |

### Обновление

| Метод | Описание |
|-------|----------|
| `update_command_metadata(name, metadata)` | Заменить метаданные. |
| `update_command_tags(name, tags)` | Заменить теги. |

---

## Использование стратегий

```python
from multiprocess_framework.refactored.modules.dispatch_module import DispatchStrategy

# FALLBACK: несколько обработчиков — побеждает с высшим efficiency
manager.register_command("process", fast_handler, strategy=DispatchStrategy.FALLBACK_MATCH, efficiency=10)
manager.register_command("process", slow_handler, strategy=DispatchStrategy.FALLBACK_MATCH, efficiency=1)

result = manager.handle_command({"command": "process", "strategy": "fallback", "data": {}})
# → fast_handler

# PATTERN: regex в имени команды
manager.register_command(r"cam_\d+", cam_handler, strategy=DispatchStrategy.PATTERN_MATCH)
result = manager.handle_command({"command": "cam_3", "data": {}})
```

---

## CommandAdapter (для ProcessModule)

`CommandAdapter` — тонкая обёртка над `CommandManager` для интеграции с процессом. Добавляет `execute_via_message` — отправить команду другому процессу через роутер.

```python
from multiprocess_framework.refactored.modules.command_module import CommandAdapter

adapter = CommandAdapter(manager, process=self)
adapter.setup()

# Отправить команду другому процессу (через router + message_manager)
adapter.execute_via_message(
    command_name="set_fps",
    args={"fps": 30},
    targets=["process_2"],
    need_ack=False
)
```

`execute_via_message` требует `process.message_manager` и `process.router`.

---

## BaseCommandManager — lightweight вариант

Конкретный (не абстрактный) класс для тестов и простых случаев. Только `EXACT_MATCH`, без `ObservableMixin`.

```python
from multiprocess_framework.refactored.modules.command_module import BaseCommandManager

m = BaseCommandManager("simple")
m.register_command("ping", lambda data: {"pong": True})
result = m.handle_command({"command": "ping", "data": {}})
```

Исключения в обработчике возвращаются как `{"status": "error", "reason": "..."}` — не пробрасываются.

---

## Интеграция с LoggerManager

```python
manager = CommandManager(
    "my_process",
    managers={"logger": logger_manager, "error": error_manager},
    config={"logger": True, "error": True}
)
```

---

## Тесты

```bash
python -m pytest Inspector_prototype/multiprocess_framework/refactored/modules/command_module/tests/ -v
```

Покрытие (34 теста):
- Жизненный цикл: `initialize` / `shutdown`
- Регистрация: дубликаты, `overwrite_command`
- Выполнение: точное совпадение, fallback, full_message, не найдено, exception → error
- Теги и метаданные
- `CommandAdapter`: setup, `execute_via_message` (с mock процессом и без)
- `BaseCommandManager`: все основные операции

---

## Roadmap / Что не хватает

| Задача | Приоритет | Этап |
|--------|-----------|------|
| Интеграция с `ProcessModule` в worker | Высокий | 3 |
| `correlation_id` для request-response | Средний | 5 |
| Dead code: `raise` в `handle_command.except` — Dispatcher уже ловит всё | Низкий | 6 |
