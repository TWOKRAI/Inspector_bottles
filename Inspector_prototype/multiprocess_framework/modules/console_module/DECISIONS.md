# console_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md) · [`../logger_module/DECISIONS.md`](../logger_module/DECISIONS.md)

## ADR-CM-001: Три уровня использования в едином ConsoleManager

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** ConsoleManager нужно поддерживать различные сценарии:
  1. **Пассивный** (`enabled=True`): показать терминал при инициализации, больше ничего.
  2. **Активный**: управление через runtime-методы (`show()`, `hide()`, `write()`) — вызовы из других менеджеров.
  3. **God Mode** (`interactive=True`): интерактивный stdin → CommandManager → обработчики команд → маршрутизация.
  
  Альтернатива: три отдельных класса (ConsoleManagerPassive, ConsoleManagerActive, GodMode). Но это усложняет:
  - Дублирование lifecycle (initialize, shutdown).
  - Сложный выбор типа при создании.
  - Невозможность переключения в runtime.
  
- **Решение:** Один `ConsoleManager` + один `ConsoleConfig` с полями `enabled`, `interactive`, `redirect_stdout`. Уровень определяется только конфигом; логика в методах проверяет флаги.
- **Причина:** DRY, гибкость runtime, единый lifecycle, простота компоновки в ProcessLaunchConfig.
- **Последствия:** Конфиг полностью управляет поведением; нет неявных состояний. Любой процесс может быть God Mode просто через ConsoleProcessConfig.

---

## ADR-CM-002: God Mode — конфигурация, не отдельный класс

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** «God Mode» (интерактивная консоль) часто воспринимается как отдельный компонент. На самом деле это — набор флагов в ConsoleConfig + ввод в stdin, который парсится в команды.
  
  Почему не отдельный класс GodModeConsole?
  - Дублирует большую часть ConsoleManager.
  - Нарушает единый жизненный цикл (initialize/shutdown).
  - Усложняет связку с LoggerManager и CommandManager.
  
- **Решение:** 
  - `ConsoleConfig.interactive=True` → включить поток чтения stdin.
  - `ConsoleAdapter.setup()` → подключить input callback к CommandManager.
  - Встроенные команды (например, `reg`) регистрируются в CommandManager при setup.
  
- **Причина:** Синхронизация: все три менеджера (ConsoleManager, LoggerManager, CommandManager) инициализируются как часть ProcessModule. Их связка происходит через адаптеры после инициализации, а не в конструкторе.
- **Последствия:** God Mode работает через стандартный ProcessModule, не требуя специального процесса (хотя ConsoleProcessConfig предоставляет удобный preset).

---

## ADR-CM-003: ConsoleLogChannel живет в console_module

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** ConsoleLogChannel реализует ILogChannel и пишет в ConsoleManager. На первый взгляд, это логирование, и он должен быть в logger_module.
  
  Однако:
  - logger_module должна быть НЕ зависима от specific менеджеров (только от IChannel).
  - ConsoleLogChannel это **специфичная интеграция** консоли с логированием.
  - Обратная зависимость: console_module → logger_module (регистрация канала в LoggerManager) приемлема, но не наоборот.
  
- **Решение:** ConsoleLogChannel в `console_module/channels/` как специализированный адаптер.
  - ILogChannel интерфейс остаётся в logger_module.
  - ConsoleLogChannel импортирует ILogChannel, но находится в console_module.
  - ConsoleAdapter при setup добавляет канал в LoggerManager.
  
- **Причина:** 
  - Зависимость идет в правильном направлении: console_module → logger_module.
  - logger_module остаётся независимым от специфик других модулей.
  - Напоминает паттерн logger_module → shared_resources_module (LoggerManager создает каналы-адаптеры для external интеграций).
  
- **Отклонено:** Помещение в logger_module вызвало бы обратную зависимость (logger → console).

---

## ADR-CM-004: IPlatformConsole изолирует платформенную логику

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** Управление терминалом на Windows (WinAPI, AllocConsole, WriteConsoleW, ShowWindow) сильно отличается от Unix (xterm, ANSI sequences, terminal emulator через PTY).
  
  Раньше можно было писать条件ные ветки прямо в ConsoleManager (if sys.platform == 'win32'...), но это нарушает принцип ответственности:
  - ConsoleManager отвечает за lifecycle и public API.
  - Платформенная логика — это implementation detail.
  
- **Решение:**
  - `IPlatformConsole` — абстрактный интерфейс с методами: create(), write(), show(), hide(), close(), read_input(), supports_multiple_windows().
  - `WindowsConsole`, `UnixConsole` — конкретные реализации.
  - `create_platform_console()` в `platforms/__init__.py` — фабрика (выбирает по `sys.platform`).
  - ConsoleManager хранит `self._platform: IPlatformConsole` и делегирует все операции.
  
- **Причина:**
  - Чистота разделения ответственности.
  - Легко добавить новую платформу (например, macOS-specific xterm2 в будущем).
  - Testability: можно подменять IPlatformConsole в unit-тестах.
  
- **Отклонено:** Условные ветки в ConsoleManager.

---

## ADR-CM-005: ConsoleProcessConfig наследует ProcessLaunchConfig

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** God Mode часто запускается как **отдельный процесс** (не главный процесс приложения). Нужен способ скомпоновать ProcessModule с инициализированным ConsoleConfig.
  
  Вариант 1: Функция-helper build_god_mode_process() → ProcessModule.
  Вариант 2: Наследовать ProcessLaunchConfig и переопределить defaults.
  
- **Решение:** `ConsoleProcessConfig(ProcessLaunchConfig)`:
  ```python
  class ConsoleProcessConfig(ProcessLaunchConfig):
      process_name = "console_app"
      managers = ManagersConfig(
          console=ConsoleConfig(enabled=True, interactive=True, ...),
          ...
      )
  ```
  
  Вызов: `config = ConsoleProcessConfig(); process = config.build()` → готовый ProcessModule.
  
- **Причина:**
  - Стандартная конвенция: один конфиг → один ProcessModule через `.build()`.
  - Ленивый импорт внутри _god_managers() избегает циклической зависимости ProcessLaunchConfig → ManagersConfig → console_module.
  
- **Отклонено:** Отдельная функция build_god_mode_process() в console_module.__init__ — нарушает symmetry с другими конфигами.

---

## ADR-CM-006: RegisterCommandHandler в console_module

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** Команда `reg list / reg get / reg set / reg info` управляет регистрами через интерактивную консоль. Где реализовать обработчик?
  
  Вариант 1: В registers_module как часть публичного API.
  Вариант 2: В command_module как часть обработчиков команд.
  Вариант 3: В console_module как специфичная интеграция консоли с регистрами.
  
- **Решение:** `RegisterCommandHandler` в `console_module/commands/register_commands.py`:
  - Это **прикладная команда**, а не core менеджмент регистров.
  - Зависит от IConsoleManager (для вывода) и registers_manager (для доступа).
  - Регистрируется в CommandManager только если консоль interactive.
  - При setup в ConsoleAdapter регистрируется в CommandManager.
  
- **Причина:**
  - registers_module должен быть независим от того, как к нему обращаются (console, IPC, API).
  - Команды работают с терминалом (форматирование выхода, текстовые таблицы), это задача console_module.
  - Паттерн: встроенные консольные команды живут в console_module; registry/execution — в command_module.
  
- **Отклонено:** Помещение в registers_module вызвало бы обратную зависимость (registers → console).

---

## ADR-CM-007: ConsoleRedirector — прямой вызов вместо Queue

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** Перенаправление sys.stdout / sys.stderr в ConsoleManager.write().
  
  Старый подход (до рефакторинга):
  ```python
  class ConsoleRedirector:
      def write(self, data: str) -> None:
          self._queue.put(('write', data))  # async Queue
  # Отдельный поток читает очередь и вызывает console_manager.write()
  ```
  
  Проблемы:
  - Лишняя очередь, лишний поток.
  - Race condition при shutdown.
  - Сложная синхронизация state (is_closed).
  
- **Решение:** Прямой вызов IConsoleManager:
  ```python
  class ConsoleRedirector:
      def __init__(self, console_manager: IConsoleManager) -> None:
          self._console = console_manager
      
      def write(self, data: str) -> None:
          if not self._closed:
              try:
                  self._console.write(data, level="STDOUT")
              except Exception:
                  # fallback на stderr
                  pass
  ```
  
  - Синхронный вызов (write не блокирует, если только ConsoleManager.write() не блокирует).
  - Сохраняет оригинальные stdout/stderr для restore() в случае ошибки.
  
- **Причина:**
  - Простота и надежность.
  - ConsoleManager.write() быстрая (просто пишет в платформенный терминал или буферизирует).
  - Ненужная асинхронность добавляет complexity без выгоды.
  
- **Последствия:** Мертвый код `console_redirect.py` (если был) удален.

---

## ADR-CM-008: RegisterCommandHandler — standalone класс с опциональными зависимостями

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** Консольная команда `reg list / get / set / info` нужна для God Mode, но не все процессы имеют RegistersManager. Как обработчик должен работать в процессах без регистров?

- **Решение:**
  - `RegisterCommandHandler` — **standalone-класс**, не наследует BaseManager.
  - Зависимости (registers_manager, router_manager) передаются опциональными параметрами:
    ```python
    handler = RegisterCommandHandler(
        registers_manager=process.registers_manager,
        router_manager=process.router_manager,
    )
    ```
  - Если менеджер `None` → возвращается graceful сообщение: `"RegistersManager is not available."`
  - Поддержка позднего связывания: `set_registers_manager(mgr)`, `set_router_manager(mgr)`.

- **Причина:**
  - Отказоустойчивость: ошибка в одной команде не ломает весь обработчик.
  - Testability: команды тестируются с mock-менеджерами, без полного ProcessModule.
  - Универсальность: обработчик работает в любом процессе.
  
- **Последствия:**
  - RegisterCommandHandler не требует BaseManager или LoggerManager.
  - Регистрируется в CommandManager только если доступен registers_manager.

---

## ADR-CM-009: SystemCommandHandler не зависит от registers_module

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** Системные команды `help / status / ps / stats` универсальны и должны работать в любом процессе, включая те, что без регистров. Но регистр-специфичные команды (reg ...) нужны другому обработчику.

- **Решение:**
  - `SystemCommandHandler` в `console_module/commands/system_commands.py` содержит только универсальные команды.
  - `RegisterCommandHandler` — отдельный класс для `reg ...` команд.
  - Оба регистрируются независимо в ConsoleAdapter.setup():
    ```python
    system_handler = SystemCommandHandler(process_info=process)
    register_handler = RegisterCommandHandler(registers_manager=...)
    
    command_manager.register_command("help", system_handler.help)
    command_manager.register_command("status", system_handler.status)
    command_manager.register_command("ps", system_handler.ps)
    command_manager.register_command("stats", system_handler.stats)
    command_manager.register_command("reg", register_handler.handle)
    ```

- **Причина:**
  - Разделение ответственности: системные команды отдельно от регистр-команд.
  - SystemCommandHandler = минимальная утилита, не зависит от registers_module.
  - Простота расширения: новые системные команды добавляются в SystemCommandHandler.
  
- **Последствия:**
  - SystemCommandHandler работает в процессах без registers_manager.
  - Каждый обработчик отвечает за свой набор команд.

---

## ADR-CM-010: `help` команда показывает весь реестр команд динамически

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** В God Mode могут быть встроенные команды (help, status, ps, stats, reg) + пользовательские команды (если приложение добавляет свои). Как `help` покажет все доступные команды?

- **Решение:**
  - `SystemCommandHandler.help()` принимает опциональный реестр команд:
    ```python
    def help(self, command_registry: Optional[Dict[str, str]] = None) -> str:
        if command_registry:
            for name in sorted(command_registry):
                description = command_registry[name]
                lines.append(f"  {name:<20} {description}")
    ```
  - ConsoleAdapter при регистрации `help` передаёт весь реестр из CommandManager.
  - Если реестр недоступен → fallback на встроенные команды.

- **Причина:**
  - Динамичность: `help` отражает реальное состояние доступных команд в runtime.
  - Никаких хардкодов: добавил новую команду в CommandManager → `help` её покажет.
  
- **Последствия:**
  - `help` работает в процессах без регистров (использует fallback).
  - Полная видимость всех команд в God Mode.

---

## ADR-CM-011: `reg set` отправляет broadcast через RouterManager

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** Команда `reg set <name>.<field> <value>` меняет значение регистра локально в текущем процессе (через RegistersManager.set_field_value()). Как оповестить остальные процессы об изменении?

- **Решение:**
  - `RegisterCommandHandler._cmd_set()` вызывает `self._registers.set_field_value()`.
  - RegistersManager при set_field_value():
    1. Обновляет значение в Pydantic модели.
    2. Вызывает registered observers.
    3. Вызывает send_callback (если установлен), который отправляет broadcast через RouterManager.
  - Broadcast сообщение содержит: `{"type": "register_update", "register": name, "field": field_name, "value": value}`
  - Другие процессы получают сообщение и обновляют локальную копию регистра.

- **Причина:**
  - God Mode может управлять состоянием системы через консоль.
  - Изменение синхронизируется через IPC (RouterManager), не через сетевые вызовы.
  - Все изменения логируются как входящие сообщения (traceable).
  
- **Последствия:**
  - RegisterCommandHandler зависит от router_manager для broadcast.
  - При отсутствии router_manager `reg set` всё равно работает, но broadcast не отправляется.

---

## ADR-CM-012: `reg info` показывает FieldMeta и FieldRouting

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** Команда `reg info <name>` должна помочь пользователю понять структуру регистра, включая тип поля, описание и маршрутизацию. Как выводить метаинформацию?

- **Решение:**
  - `RegisterCommandHandler._cmd_info()` выводит `model_fields` регистра и метаданные:
    ```python
    meta_dict = self._registers.get_field_metadata(register_name, field_name)
    # Возвращает: {
    #   "description": "Process running state",
    #   "type": <class 'bool'>,
    #   "routing_channel": "control_channel",
    #   "constraints": {...}
    # }
    ```
  - Фильтруются пустые значения (None, "", [], {}) для компактности.
  - Формат вывода: чистая таблица с field_name → metadata.

- **Причина:**
  - Пользовательское API для инспекции регистров из консоли.
  - FieldMeta/FieldRouting содержат полезную информацию (constraints, routing).
  - Работает с любыми регистрами, не требует изменений при добавлении новых полей.
  
- **Последствия:**
  - `reg info` работает только если доступен registers_manager.
  - Возвращает "Register not found" / "Field not found" с понятными сообщениями.

---

## Ссылки на глобальные ADR

- **ADR-008: Dict at Boundary** — ConsoleConfig, ConsoleProcessConfig передаются как dict на границах процессов; внутри процесса — Pydantic. На примере ConsoleManager: конфиг принимается как ConsoleConfig (Pydantic), а в shared_resources_module всегда dict.
  
- **ADR-010: console_module — менеджер терминальных окон** — глобальное решение, про статус module в экосистеме. Локальные ADR CM-001..CM-012 детализируют design.
