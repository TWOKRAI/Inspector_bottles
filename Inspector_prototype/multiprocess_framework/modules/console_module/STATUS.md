# console_module — Статус рефакторинга

## Текущий этап: 8 / 8 (завершён)

## Оценки (0-10)

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| Код (читаемость, стандарты) | 8 | Чистая архитектура, SOLID, relative imports |
| Тесты (покрытие) | 7 | pytest, 5 файлов, lifecycle/write/input/redirect/adapter |
| Документация (README, interfaces) | 9 | interfaces.py + README: импорты, точки входа, зависимости, примеры, примечания |
| Связанность (меньше = лучше) | 8 | IPlatformConsole изолирует платформенную логику |
| Дублирование | 8 | Нет дублирования, вся платформенная логика в platforms/ |
| Работоспособность | 7 | Базовая реализация работает, сложные WinAPI — optional |

## Чеклист рефакторинга

- [x] Этап 1: interfaces.py — IPlatformConsole + IConsoleManager переписаны
- [x] Этап 2: platforms/ — WindowsConsole, UnixConsole, фабрика
- [x] Этап 3: ConsoleConfig(SchemaBase) создан
- [x] Этап 4: ConsoleManager полностью переписан (BaseManager + ObservableMixin + IConsoleManager)
- [x] Этап 5: ConsoleLogChannel(ILogChannel) — мост LoggerManager → ConsoleManager
- [x] Этап 6: ConsoleRedirector рефакторинг — убрана Queue, прямой вызов manager.write()
- [x] Этап 7: ConsoleAdapter(BaseAdapter) — интеграция с LoggerManager и CommandManager
- [x] Этап 8: Интеграция в ProcessModule (process_module.py, process_managers.py, process_lifecycle.py)
- [x] Этап 9: ConsoleProcessConfig(SchemaBase) — God Mode: `ManagersConfig` + `ProcessLaunchConfig.build()`, без shared `_GOD` default
- [x] Этап 10: pytest тесты (5 файлов), STATUS.md и README.md обновлены

## Архитектурные решения

- **Dict at Boundary** (ADR-008): конфиг принимается как dict в ProcessManagers, внутри — ConsoleConfig
- **IPlatformConsole**: вся платформенная логика изолирована; ConsoleManager только вызывает `self._platform.xxx()`
- **ConsoleLogChannel живёт в console_module**, не в logger_module (согласно плану)
- **God Mode = конфигурация**, не отдельный код: `ConsoleConfig(enabled=True, interactive=True)`

## Известные проблемы / ограничения

- Windows WinAPI (AllocConsole, ShowWindow) — базовая реализация, работает через ctypes; дополнительные окна через subprocess при необходимости
- Linux headless (без GUI): `supports_multiple_windows()` → False, `create_console()` вернёт False
- `enable_input()` блокирует поток: `_platform.read_input()` вызывает `input()`, что не прерывается сигналами на Windows

## История изменений

| Дата | Что сделано | Этап |
|------|-------------|------|
| 2026-03-11 | Начальное состояние | 0 |
| 2026-03-14 | Полный рефакторинг по плану console_module_refactoring | 4 |
| 2026-03-14 | Очистка: удалены legacy (ConsoleChannel, window_process, test_basic, docs/, IConsoleChannel) | 8 |
