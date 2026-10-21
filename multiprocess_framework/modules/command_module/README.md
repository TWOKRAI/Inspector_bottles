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
from multiprocess_framework.modules.command_module import CommandManager

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
| `handle_command(message, *, reply=None)` | Найти и вызвать обработчик. Вернуть результат или `{"status": "error", ...}`. `reply` — только для команды с исполнителем (ниже). |

**Обработка ошибок:** исключения внутри обработчика перехватываются `Dispatcher` → возвращается `{"status": "error", "reason": "..."}`.

### Команды с исполнителем (Task 1.9a, ADR-CMD-006)

`register_command(..., executor=None, key_from=None, targets=None)` — новые необязательные аргументы; умолчания
прежние, команда без них синхронна, как всегда.

- `executor` — `OrderedExecutor` (`worker_module`, например `KeyedExecutor`); с ним задаётся ровно одно из
  `key_from="<поле data>"` (ключ `frozenset({data[поле]})`) или `targets="all"` (ключ `None` — «все ключи»).
- Регистрация отклоняется (`False` + WARNING): `executor` не ровно с одним из `key_from`/`targets`; `targets` вне
  `{None, "all"}`; `key_from`/`targets` без `executor`; `executor` при `metadata.manages_own_reply`.
- Объект исполнителя хранится вне `metadata`; в `metadata` — только строки `executor` (имя), `key_from`, `targets`.
- `handle_command(msg, reply=r)` для такой команды → `DEFERRED` (экспорт `command_module`), результат придёт в `r`
  ровно один раз с потока исполнителя (или отказ `system_stopping` / `executor_busy`).
- Без `reply` (консоль, тесты, вложенные вызовы) → исполнение на месте + один WARNING на имя «исполнено вне очереди
  ключа». `DEFERRED` без `reply` не возвращается никогда.
- Поля ключа нет / не непустая `str` → возврат `{"success": False, "error": "key_missing", "command": <имя>}` +
  WARNING без значения поля; обработчик и `reply` не вызываются.
- Роутер передаёт `reply` только командам с `metadata.executor` (ADR-RTR-015). `overwrite_command` снимает исполнителя.

### Исполнитель по имени (Task 1.9m, ADR-CMD-007)

`executor=` принимает объект `OrderedExecutor` или **имя** исполнителя из реестра процесса (`ExecutorManager`,
`worker_module`): `register_command("camera.start", h, executor="io", key_from="camera")`. Сигнатуры
`register_command` / `handle_command` не менялись, только расширен тип `executor`; объектная форма работает как раньше.

- Реестр — kwarg конструктора `CommandManager(..., executors=<IExecutorRegistry>)` (умолчание `None`). Через `managers=`
  не передаётся: тот словарь уходит наблюдателям миксина. `ProcessManagers` подставляет `ExecutorManager` процесса сам.
- Имя разрешается **при регистрации** (fail fast), до прочих проверок исполнителя. Отказ (`False` + WARNING с именем,
  метрика `registration.failed`): пустое имя; реестра нет (`executors=None`); имя не найдено. Команда, зарегистрированная
  раньше, чем создан исполнитель, отклоняется — порядок «создать исполнитель, затем команды» лежит на вызывающем.
- Объект фиксируется при регистрации (подмены под тем же именем в реестре нет); в `metadata["executor"]` кладётся строка,
  переданная вызывающим (имя в реестре), а не `obj.name`.
- Зависимость однонаправленная: `command_module` знает только протокол `worker_module.interfaces.IExecutorRegistry`
  (под `TYPE_CHECKING`).

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
from multiprocess_framework.modules.dispatch_module import DispatchStrategy

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
from multiprocess_framework.modules.command_module import CommandAdapter

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
from multiprocess_framework.modules.command_module import BaseCommandManager

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
python -m pytest multiprocess_framework/modules/command_module/tests/ -v
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
