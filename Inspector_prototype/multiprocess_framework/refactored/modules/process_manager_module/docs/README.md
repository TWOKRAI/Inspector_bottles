# Документация ProcessManagerModule

## Структура документации

Документация будет добавлена по мере разработки модуля.

## Основные концепции

ProcessManagerModule управляет процессами ОС. Наследуется от BaseManager и использует ObservableMixin.

## Компоненты

- `core/process_manager_core.py` - основная логика управления процессами
- `process/process_manager_process.py` - процесс менеджера (наследуется от ProcessModule)
- `runner/process_runner.py` - запуск процессов ОС

