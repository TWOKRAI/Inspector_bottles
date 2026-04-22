# Refactoring plan: `console_module` (модуль #18)

> **Статус:** DRAFT
> **Дата:** 2026-04-12
> **Автор плана:** Manager (Opus 4.6)
> **Ссылки:** [00_overview.md](./00_overview.md) · [ARCHITECTURE.md](../../Inspector_prototype/multiprocess_framework/ARCHITECTURE.md) · [17_registers_module.md](./17_registers_module.md) · [ADR-010](../../Inspector_prototype/multiprocess_framework/DECISIONS.md)

---

## 0. Контекст

Console module -- модуль #18, последний перед milestone M2. Зависимости (#1 base_manager, #2 data_schema_module, #5 logger_module) отрефакторены. Модуль компактный: 17 файлов, 974 LOC, 5 тестовых файлов. Код уже проходил рефакторинг (STATUS.md: "8/8 завершен"), но:

1. **Legacy `console_redirect.py` в `process_manager_module`** -- использует старый API (`ConsoleRedirector(queue, process_name)`), несовместимый с текущим `ConsoleRedirector(console_manager)`. Мертвый код, который сломается при вызове.
2. **Нет DECISIONS.md** -- ни одного локального ADR, хотя решений достаточно (3 уровня использования, God Mode = конфигурация, ConsoleLogChannel в console_module а не в logger_module).
3. **ARCHITECTURE.md section 6.18** -- заглушка `TODO (после модуля #18, milestone M2)`.
4. **Нет интерактивного режима для регистров** -- текущий God Mode просто пробрасывает raw text в `command_manager.handle_command()`. Нет command-ов для работы с registers (list, get, set).
5. **Кроссплатформенные пробелы:**
   - `UnixConsole.read_input()` использует `input()` -- блокирующий, не прерываемый на Windows.
   - `WindowsConsole.close()` вызывает `FreeConsole()` безусловно -- может убить единственную консоль приложения.
   - Нет теста `WindowsConsole` на Linux/macOS (mock-based).
6. **`ConsoleConfig` принимается через `setattr` в process_managers.py** -- антипаттерн, нужно `ConsoleConfig(**dict)` или `model_validate`.
7. **Тесты:** 5 файлов, ~35 тестов -- покрытие неплохое, но нет теста для `ConsoleProcessConfig`, нет mock-теста для `WindowsConsole`, нет edge cases для `_input_loop` (exception в callback).

**Milestone M2 задача:** интерактивный console меняет поля регистров в runtime; изменения через Router летят между процессами. Console module должен предоставить инфраструктуру для этого.

**Сложность:** средняя -- 60% документация/cleanup, 30% register commands, 10% platform fixes.

---

## 1. Текущее состояние (baseline)

- **Файлов:** 17 `.py` (без tests/__pycache__)
- **LOC:** 974 (без тестов)
- **Тестов:** 5 файлов (~35 тестов)
- **Публичный API:** `ConsoleManager`, `ConsoleConfig`, `ConsoleAdapter`, `ConsoleLogChannel`, `ConsoleRedirector`, `ConsoleProcessConfig`, `IConsoleManager`, `IPlatformConsole`

### 1.1. Внешние потребители

| Модуль | Что использует | Затронут? |
|--------|---------------|-----------|
| process_module / managers_config.py | `ConsoleConfig` (импорт, секция `console` в `ManagersConfig`) | Нет (API не меняется) |
| process_module / process_managers.py | `ConsoleManager`, `ConsoleConfig`, `ConsoleAdapter` (создание, инициализация, attach) | Да (Task 1.2: setattr -> model_validate) |
| process_manager_module / console_redirect.py | `ConsoleRedirector` (OLD queue API) | Да (Task 1.3: удалить или обновить) |
| multiprocess_framework / __init__.py | `ConsoleManager` (lazy export) | Нет |

### 1.2. Файлы и LOC

| Файл | LOC | Статус |
|------|-----|--------|
| `core/console_manager.py` | 261 | Refactor minor |
| `interfaces.py` | 127 | Без изменений |
| `configs/console_config.py` | 35 | Без изменений |
| `configs/console_process_config.py` | 42 | Без изменений |
| `adapters/console_adapter.py` | 76 | Расширить (register commands) |
| `channels/console_log_channel.py` | 59 | Без изменений |
| `redirectors/console_redirector.py` | 75 | Minor fix |
| `platforms/unix.py` | 96 | Platform fix |
| `platforms/windows.py` | 106 | Platform fix + mock test |
| `platforms/__init__.py` | 24 | Без изменений |
| `platforms/base.py` | 8 | Без изменений |
| `__init__.py` | 39 | Без изменений |
| `README.md` | 189 | Обновить |
| `STATUS.md` | 50 | Обновить |

---

## 2. Атомарные задачи

### Этап 1: Cleanup и platform fixes

---

### Task 1.1 -- Удалить legacy console_redirect.py в process_manager_module

**Статус:** [PENDING]
**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Удалить мертвый `console_redirect.py` в `process_manager_module/runner/`, который использует несуществующий API `ConsoleRedirector(queue, process_name)`.

**Контекст:** После рефакторинга console_module `ConsoleRedirector` принимает `IConsoleManager`, а не queue. Файл `console_redirect.py` в process_manager_module вызывает `ConsoleRedirector(output_queues, process_name)` -- это упадет с TypeError при любом вызове. Redirect теперь настраивается через `ConsoleManager.setup_redirect()` в `process_managers.py`, а не через runner.

**Файлы:**
- `Inspector_prototype/multiprocess_framework/modules/process_manager_module/runner/console_redirect.py` -- **удалить**
- `Inspector_prototype/multiprocess_framework/modules/process_manager_module/runner/process_runner.py` -- убрать `from .console_redirect import _setup_console_redirect` и вызов `_setup_console_redirect(...)` (строка 139)

**Шаги:**
1. Удалить файл `console_redirect.py`
2. В `process_runner.py`: убрать импорт `from .console_redirect import _setup_console_redirect` (строка 16)
3. В `process_runner.py`: убрать вызов `redirector = _setup_console_redirect(process_name, process_data, log)` (строка 139) и все использования `redirector` ниже (если есть)
4. Проверить что никакие другие файлы не импортируют из `console_redirect`

**Критерии приемки:**
- [ ] `console_redirect.py` удален
- [ ] `process_runner.py` компилируется без ошибок (import check)
- [ ] `pytest process_manager_module/tests/ -v` -- все тесты проходят
- [ ] `grep -r "console_redirect" modules/process_manager_module/` -- 0 результатов (кроме __pycache__)

**Вне scope:** Менять логику ConsoleRedirector в console_module. Менять process_managers.py.

---

### Task 1.2 -- Исправить создание ConsoleConfig через setattr в process_managers.py

**Статус:** [PENDING]
**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Заменить ручной `setattr` loop при создании `ConsoleConfig` на `ConsoleConfig.model_validate(dict)` в `process_managers.py`.

**Контекст:** В `process_managers.py:168-177` конфиг создается через:
```python
console_config = ConsoleConfig()
if isinstance(console_cfg_dict, dict):
    for key, value in console_cfg_dict.items():
        if hasattr(console_config, key):
            setattr(console_config, key, value)
```
Это антипаттерн: пропускает валидацию Pydantic, молча игнорирует неизвестные ключи. Все остальные менеджеры (logger, error, stats) уже используют `Config(**dict)` или `model_validate()`.

**Файлы:**
- `Inspector_prototype/multiprocess_framework/modules/process_module/managers/process_managers.py` -- метод `_create_console_manager`

**Шаги:**
1. Заменить блок строк 172-177 на: `console_config = ConsoleConfig(**console_cfg_dict) if isinstance(console_cfg_dict, dict) and console_cfg_dict else ConsoleConfig()`
2. Убедиться что `ConsoleConfig` импортирован (уже импортирован на строке 170)

**Критерии приемки:**
- [ ] `setattr` loop удален из `_create_console_manager`
- [ ] `ConsoleConfig` создается через конструктор или `model_validate`
- [ ] `pytest process_module/tests/ -v` -- все тесты проходят
- [ ] Неизвестные ключи в dict вызывают ошибку валидации (а не молча игнорируются)

**Вне scope:** Менять другие методы `_create_*_manager`. Менять сам `ConsoleConfig`.
**Зависимости:** нет

---

### Task 1.3 -- Platform fixes: WindowsConsole.close() и UnixConsole

**Статус:** [PENDING]
**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Исправить потенциальные проблемы кроссплатформенности в WindowsConsole и UnixConsole.

**Контекст:** Windows + Linux -- основные платформы (macOS только dev). Текущие проблемы:
- `WindowsConsole.close()` безусловно вызывает `FreeConsole()` -- это убьет единственную консоль приложения, если дополнительная не создавалась через `AllocConsole`.
- `WindowsConsole` не отслеживает, был ли вызван `AllocConsole` (т.е. создали ли мы консоль или подключились к существующей).
- `ConsoleRedirector.write()` молча глушит ВСЕ ошибки через `self._closed = True` -- при любой ошибке redirect перестает работать навсегда.

**Файлы:**
- `Inspector_prototype/multiprocess_framework/modules/console_module/platforms/windows.py`
- `Inspector_prototype/multiprocess_framework/modules/console_module/redirectors/console_redirector.py`

**Шаги:**
1. В `WindowsConsole.__init__`: добавить `self._allocated_console: bool = False`
2. В `WindowsConsole.create()`: запомнить `self._allocated_console = True` только если был вызван `AllocConsole()` (т.е. `hwnd` был 0)
3. В `WindowsConsole.close()`: вызывать `FreeConsole()` только если `self._allocated_console is True`
4. В `ConsoleRedirector.write()`: заменить голый `except Exception: self._closed = True` на логирование через `self._original_stderr.write(...)` перед выставлением `_closed` (чтобы ошибка не пропала бесследно)

**Критерии приемки:**
- [ ] `WindowsConsole.close()` вызывает `FreeConsole()` только если `AllocConsole()` был вызван ранее
- [ ] `self._allocated_console` флаг добавлен и корректно выставляется
- [ ] `ConsoleRedirector.write()` при ошибке пишет сообщение в `_original_stderr` перед `_closed = True`
- [ ] `pytest console_module/tests/ -v` -- все тесты проходят

**Вне scope:** Реализация создания дополнительных окон через subprocess на Windows. Реализация множественных окон на Unix.
**Edge cases:**
- `WindowsConsole` в среде без реальной консоли (например, pythonw.exe) -- `GetConsoleWindow()` вернет 0, `AllocConsole()` создаст новую, `close()` должен ее освободить.
- `ConsoleRedirector.write()` с `_original_stderr` который тоже недоступен -- fallback на `pass`.

---

### Task 1.4 -- Mock-тест для WindowsConsole

**Статус:** [PENDING]
**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Добавить mock-based тесты для `WindowsConsole`, запускаемые на любой платформе.

**Контекст:** Текущий `test_platforms.py` тестирует только текущую платформу через фабрику. `WindowsConsole` на Linux/macOS не покрыт тестами. Нужны mock-тесты для ctypes.windll.

**Файлы:**
- `Inspector_prototype/multiprocess_framework/modules/console_module/tests/test_platforms.py` -- добавить класс `TestWindowsConsoleMocked`

**Шаги:**
1. Добавить класс `TestWindowsConsoleMocked` с `@pytest.mark.skipif(sys.platform == "win32", reason="mock-тест, на Windows запускается реальный")`
2. Мокнуть `ctypes.windll` через `unittest.mock.patch`
3. Тестировать: `create()`, `show()`, `hide()`, `close()` (с `_allocated_console=True` и `False`), `write()`, `read_input()`
4. Проверить что `close()` с `_allocated_console=False` НЕ вызывает `FreeConsole()`

**Критерии приемки:**
- [ ] Минимум 6 тестов для WindowsConsole на mock
- [ ] Тесты запускаются на Linux/macOS (проверить в CI)
- [ ] Тест для `close()` проверяет `_allocated_console` guard (из Task 1.3)
- [ ] `pytest console_module/tests/test_platforms.py -v` -- все тесты проходят

**Вне scope:** Интеграционное тестирование на реальном Windows.
**Зависимости:** Task 1.3 (platform fixes)

---

### Этап 2: Register-interactive commands (core M2)

---

### Task 2.1 -- RegisterCommandHandler: команды для работы с регистрами

**Статус:** [PENDING]
**Уровень:** Senior (Opus)
**Исполнитель:** teamlead
**Цель:** Создать обработчик консольных команд для работы с регистрами: `reg list`, `reg get <name>`, `reg set <name>.<field> <value>`, `reg info <name>`.

**Контекст:** Milestone M2 требует: "интерактивный console меняет поля регистров в runtime; изменения через Router летят между процессами". Текущий God Mode передает raw text в `command_manager.handle_command()`, но нет команд для регистров. `RegisterCommandHandler` должен быть частью `console_module`, но использовать `registers_module` API (`RegistersManager`) для доступа к данным. Команда `reg set` должна отправлять изменение через `RouterManager`, чтобы другие процессы получили обновление.

**Файлы:**
- `Inspector_prototype/multiprocess_framework/modules/console_module/commands/register_commands.py` -- **создать**
- `Inspector_prototype/multiprocess_framework/modules/console_module/commands/__init__.py` -- **создать**
- `Inspector_prototype/multiprocess_framework/modules/console_module/adapters/console_adapter.py` -- расширить setup() для регистрации команд

**Шаги:**
1. Создать `commands/register_commands.py` с классом `RegisterCommandHandler`:
   - `handle(args: list[str], process: Any) -> str` -- главный dispatch по `args[0]`
   - `_list(process) -> str` -- список зарегистрированных регистров (из `process.registers_manager` или `process.shared_resources`)
   - `_get(name: str, process) -> str` -- вывод всех полей регистра как таблица
   - `_set(name: str, field: str, value: str, process) -> str` -- изменение поля + отправка через router
   - `_info(name: str, process) -> str` -- метаинформация (FieldMeta, FieldRouting) регистра
2. Формат вывода: plain text с выравниванием (для терминала), без ANSI если `_platform.isatty()` == False
3. Команда `reg set` должна:
   - Вызвать `register_instance.update_field(field, value)`
   - Отправить сообщение через `router_manager.send_message()` с `type="register_update"` и `targets="*"` (broadcast)
4. В `ConsoleAdapter.setup()`: если `config.interactive` -- зарегистрировать `RegisterCommandHandler` в `command_manager` через `command_manager.register_handler("reg", handler.handle)`
5. Обработка ошибок: если `registers_manager` не найден в процессе -- вернуть "registers not available"

**Критерии приемки:**
- [ ] `reg list` -- выводит список регистров (или "no registers" если пусто)
- [ ] `reg get <name>` -- выводит поля регистра с текущими значениями
- [ ] `reg set <name>.<field> <value>` -- меняет поле и отправляет update
- [ ] `reg info <name>` -- выводит FieldMeta + FieldRouting для каждого поля
- [ ] Неизвестный subcommand -- вывод help
- [ ] Отсутствие registers_manager -- graceful fallback

**Вне scope:** GUI для регистров. Автокомплит. History. Цветной вывод (оставить на потом).
**Edge cases:**
- Регистр с вложенными SchemaBase -- `reg get` должен показать flatten или nested
- Значение с пробелами: `reg set camera.path "/dev/video 0"` -- парсинг кавычек
- Невалидное значение для поля -- Pydantic ValidationError -> вывести в консоль

**Зависимости:** Task 1.1, 1.2 (cleanup)

---

### Task 2.2 -- Системные консольные команды: help, status, processes

**Статус:** [PENDING]
**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Добавить базовые системные команды для God Mode: `help`, `status`, `ps` (list processes), `stats`.

**Контекст:** God Mode без базовых команд бесполезен. Нужен минимальный набор для диагностики. Эти команды не зависят от registers_module.

**Файлы:**
- `Inspector_prototype/multiprocess_framework/modules/console_module/commands/system_commands.py` -- **создать**
- `Inspector_prototype/multiprocess_framework/modules/console_module/commands/__init__.py` -- обновить экспорт
- `Inspector_prototype/multiprocess_framework/modules/console_module/adapters/console_adapter.py` -- зарегистрировать system commands

**Шаги:**
1. Создать `commands/system_commands.py` с классом `SystemCommandHandler`:
   - `help` -- вывести список доступных команд и их описание
   - `status` -- состояние текущего процесса (name, uptime, managers list, enabled/disabled)
   - `ps` -- список дочерних процессов (если доступен process_manager_process, иначе -- только свой процесс)
   - `stats` -- агрегированная статистика из StatsManager
2. В `ConsoleAdapter.setup()`: зарегистрировать system commands для всех четырех ключей
3. `help` должен быть динамическим -- показывать все зарегистрированные команды в command_manager

**Критерии приемки:**
- [ ] `help` выводит список команд с описаниями
- [ ] `status` выводит состояние текущего процесса
- [ ] `ps` выводит список процессов (или "not available" если нет process_manager)
- [ ] `stats` выводит метрики (или "no stats" если StatsManager не активен)
- [ ] Все команды работают без crash при отсутствии менеджеров

**Вне scope:** Команды для управления процессами (start/stop/restart -- это в command_module). Цветной вывод.
**Зависимости:** Task 1.1

---

### Task 2.3 -- Тесты для register и system commands

**Статус:** [PENDING]
**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Написать unit-тесты для RegisterCommandHandler и SystemCommandHandler.

**Файлы:**
- `Inspector_prototype/multiprocess_framework/modules/console_module/tests/test_register_commands.py` -- **создать**
- `Inspector_prototype/multiprocess_framework/modules/console_module/tests/test_system_commands.py` -- **создать**

**Шаги:**
1. `test_register_commands.py`:
   - Mock process с registers_manager, router_manager
   - Тест `reg list` с пустым и непустым списком регистров
   - Тест `reg get <name>` -- корректный вывод полей
   - Тест `reg set` -- вызов `update_field` + `send_message`
   - Тест `reg set` с невалидным значением -- graceful error
   - Тест `reg info` -- вывод FieldMeta
   - Тест без registers_manager -- graceful fallback
2. `test_system_commands.py`:
   - Тест `help` -- содержит хотя бы "help", "status"
   - Тест `status` -- содержит process name
   - Тест `stats` -- без StatsManager не падает
   - Тест `ps` -- без process_manager не падает

**Критерии приемки:**
- [ ] Минимум 10 тестов для register_commands
- [ ] Минимум 5 тестов для system_commands
- [ ] Все тесты используют mock (не требуют запущенного процесса)
- [ ] `pytest console_module/tests/ -v` -- все тесты проходят

**Вне scope:** Интеграционные тесты с реальными регистрами.
**Зависимости:** Task 2.1, 2.2

---

### Этап 3: Документация

---

### Task 3.1 -- Создать DECISIONS.md для console_module

**Статус:** [PENDING]
**Уровень:** Junior (Haiku)
**Исполнитель:** docs-writer
**Цель:** Формализовать архитектурные решения console_module в локальном DECISIONS.md.

**Файлы:**
- `Inspector_prototype/multiprocess_framework/modules/console_module/DECISIONS.md` -- **создать**

**Шаги:**
1. Создать `DECISIONS.md` с ADR по следующим решениям:
   - **ADR-CM-001: Три уровня использования** -- passive/active/God Mode через один ConsoleConfig
   - **ADR-CM-002: God Mode = конфигурация** -- не отдельный код, а `ConsoleConfig(enabled=True, interactive=True)`
   - **ADR-CM-003: ConsoleLogChannel живет в console_module** -- не в logger_module, потому что знает о ConsoleManager
   - **ADR-CM-004: IPlatformConsole изолирует платформенную логику** -- ConsoleManager не знает о WinAPI/xterm
   - **ADR-CM-005: ConsoleProcessConfig наследует ProcessLaunchConfig** -- God Mode как standalone процесс через стандартный build() (ADR-114)
   - **ADR-CM-006: RegisterCommandHandler в console_module** -- команды для регистров живут в console, не в registers_module
   - **ADR-CM-007: ConsoleRedirector -- прямой вызов вместо Queue** -- после рефакторинга убрана queue-based архитектура
2. Формат каждого ADR: Дата, Статус, Контекст, Решение, Причина
3. Добавить ссылку на глобальные ADR-008 (Dict at Boundary), ADR-010 (console_module)

**Критерии приемки:**
- [ ] Файл `DECISIONS.md` создан с минимум 7 ADR
- [ ] Каждый ADR имеет: Дата, Статус, Контекст, Решение, Причина
- [ ] Есть ссылки на глобальные ADR где релевантно

**Вне scope:** Обновление главного DECISIONS.md (это Task 3.3).
**Зависимости:** Task 2.1 (для ADR-CM-006)

---

### Task 3.2 -- Обновить README.md и STATUS.md

**Статус:** [PENDING]
**Уровень:** Junior (Haiku)
**Исполнитель:** docs-writer
**Цель:** Обновить README.md с учетом новых commands и актуализировать STATUS.md.

**Файлы:**
- `Inspector_prototype/multiprocess_framework/modules/console_module/README.md` -- обновить
- `Inspector_prototype/multiprocess_framework/modules/console_module/STATUS.md` -- обновить

**Шаги:**
1. README.md:
   - Добавить секцию "Console Commands" с описанием `reg`, `help`, `status`, `ps`, `stats`
   - Обновить "Структура модуля" -- добавить `commands/`
   - Исправить путь `config/` -> `configs/` в дереве файлов (строка 99)
   - Добавить пример God Mode с register commands
   - Добавить ссылку на DECISIONS.md
2. STATUS.md:
   - Обновить чеклист рефакторинга: добавить этапы 11-13 (cleanup, register commands, docs)
   - Обновить оценки
   - Добавить запись в "История изменений"

**Критерии приемки:**
- [ ] README содержит секцию "Console Commands"
- [ ] README содержит `commands/` в дереве файлов
- [ ] STATUS.md отражает текущий этап
- [ ] Путь `config/` исправлен на `configs/` в README

**Вне scope:** Писать отдельную документацию в docs/. Переводить на английский.
**Зависимости:** Task 2.1, 2.2, 3.1

---

### Task 3.3 -- Заполнить section 6.18 в ARCHITECTURE.md и обновить главный DECISIONS.md

**Статус:** [PENDING]
**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Заполнить section 6.18 в ARCHITECTURE.md и добавить индекс console_module ADR в главный DECISIONS.md.

**Файлы:**
- `Inspector_prototype/multiprocess_framework/ARCHITECTURE.md` -- заполнить section 6.18
- `Inspector_prototype/multiprocess_framework/DECISIONS.md` -- добавить ссылку на console_module/DECISIONS.md

**Шаги:**
1. В ARCHITECTURE.md section 6.18 (после строки 852) -- заполнить по образцу других секций (6.14, 6.15, 6.17):
   - Роль модуля
   - Классы: ConsoleManager, ConsoleAdapter, ConsoleLogChannel, ConsoleRedirector, RegisterCommandHandler, SystemCommandHandler
   - ConsoleConfig: 4 поля (enabled, interactive, title, redirect_stdout)
   - IPlatformConsole -> WindowsConsole / UnixConsole (фабрика)
   - God Mode: ConsoleProcessConfig(ProcessLaunchConfig)
   - Register commands: reg list/get/set/info
   - Диаграмма взаимодействия (ASCII или Mermaid)
2. В главном DECISIONS.md -- добавить строку в индекс модульных решений: `console_module/DECISIONS.md: ADR-CM-001..007`

**Критерии приемки:**
- [ ] Section 6.18 заполнена (не TODO)
- [ ] Содержит: роль, классы, конфиг, платформы, God Mode, register commands
- [ ] Главный DECISIONS.md содержит ссылку на console_module/DECISIONS.md
- [ ] Нет ошибок в Mermaid/ASCII диаграмме

**Вне scope:** Менять другие секции ARCHITECTURE.md. Менять содержимое ADR.
**Зависимости:** Task 3.1

---

### Task 3.4 -- Обновить метрики в 00_overview.md

**Статус:** [PENDING]
**Уровень:** Junior (Haiku)
**Исполнитель:** docs-writer
**Цель:** Заполнить `files_after`, `loc_after`, `tests_after` для модуля #18 в таблице 00_overview.md.

**Файлы:**
- `plans/refactoring/00_overview.md` -- строка 103 (модуль #18)

**Шаги:**
1. Посчитать финальные метрики: `.py` файлы (без tests/__pycache__), LOC, количество тестов
2. Заполнить столбцы `files_after`, `loc_after`, `tests_after` в таблице

**Критерии приемки:**
- [ ] Строка #18 в таблице заполнена полностью
- [ ] Метрики соответствуют реальному состоянию файлов

**Вне scope:** Менять метрики других модулей.
**Зависимости:** Все предыдущие задачи

---

## 3. Порядок выполнения

### Этап 1: Cleanup и platform fixes
- Task 1.1: Удалить legacy console_redirect.py [PENDING]
- Task 1.2: Исправить setattr в process_managers.py [PENDING]
- Task 1.3: Platform fixes (WindowsConsole.close, ConsoleRedirector) [PENDING]
- Task 1.4: Mock-тесты WindowsConsole [PENDING] (зависит от 1.3)

### Этап 2: Register-interactive commands (core M2)
- Task 2.1: RegisterCommandHandler [PENDING] (зависит от 1.1, 1.2)
- Task 2.2: SystemCommandHandler [PENDING] (зависит от 1.1)
- Task 2.3: Тесты для commands [PENDING] (зависит от 2.1, 2.2)

### Этап 3: Документация
- Task 3.1: DECISIONS.md [PENDING] (зависит от 2.1)
- Task 3.2: README.md + STATUS.md [PENDING] (зависит от 2.1, 2.2, 3.1)
- Task 3.3: ARCHITECTURE.md section 6.18 + DECISIONS.md index [PENDING] (зависит от 3.1)
- Task 3.4: Метрики в 00_overview.md [PENDING] (зависит от всех)

---

## 4. Риски и ограничения

1. **RegisterCommandHandler зависит от registers_module API** -- registers_module (#17) уже отрефакторен, но API для "list all registers" и "get register by name" нужно проверить. Если API отсутствует -- Task 2.1 должен использовать fallback через `shared_resources` или config_store.

2. **command_module.register_handler API** -- Task 2.1 предполагает что CommandManager имеет метод `register_handler(command_name, callback)`. Если API отличается -- адаптировать вызов под существующий `handle_command(dict)` dispatch.

3. **God Mode как отдельный процесс** -- RegisterCommandHandler в God Mode процессе не имеет прямого доступа к регистрам других процессов. Команда `reg set` должна отправлять сообщение через RouterManager, а не модифицировать регистр локально. Это архитектурное решение для M2.

4. **Тестирование Windows** -- mock-тесты (Task 1.4) покрывают логику, но реальное поведение ctypes WinAPI проверить можно только на Windows CI. Это допустимый risk.

5. **ConsoleProcessConfig зависит от process_module** -- циклическая зависимость console_module -> process_module (через ProcessLaunchConfig, ManagersConfig). Решена через ленивый import в `__getattr__` (ADR-114). Не трогать.

---

## 5. Definition of Done

- [ ] Legacy `console_redirect.py` удален из process_manager_module
- [ ] `ConsoleConfig` создается через Pydantic конструктор (не setattr)
- [ ] `WindowsConsole.close()` безопасен (не убивает чужую консоль)
- [ ] Mock-тесты для WindowsConsole работают на Linux/macOS
- [ ] `reg list/get/set/info` работают в God Mode
- [ ] `help/status/ps/stats` работают в God Mode
- [ ] DECISIONS.md создан с 7+ ADR
- [ ] ARCHITECTURE.md section 6.18 заполнена
- [ ] README.md и STATUS.md обновлены
- [ ] Все тесты проходят: `pytest console_module/tests/ -v`
- [ ] Метрики в 00_overview.md заполнены
