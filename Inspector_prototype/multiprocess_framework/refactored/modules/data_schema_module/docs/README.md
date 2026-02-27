# Документация data_schema_module

## Основные документы

| Документ | Описание |
|----------|----------|
| [QUICK_REFERENCE.md](QUICK_REFERENCE.md) | **Для AI и новых разработчиков** — принципы работы, взаимосвязи, типичный workflow (понять модуль без изучения всех файлов) |
| [STRUCTURE.md](STRUCTURE.md) | Структура модуля, компоненты (registry, utils, FieldSchema, registers_io) |
| [DIAGRAMS.md](DIAGRAMS.md) | **Диаграммы классов и потоков** — что с чем связано и для чего |
| [EVALUATION.md](EVALUATION.md) | Оценка модуля (баллы, лишнее, рекомендации) |
| [DISCOVERY_AND_PACKAGES.md](DISCOVERY_AND_PACKAGES.md) | Discovery и регистрация по пакетам (Registers/Data), было → стало, пример использования |
| [EVALUATION_FRAMEWORK_AND_REGISTERS.md](EVALUATION_FRAMEWORK_AND_REGISTERS.md) | **Оценка в баллах** связки data_schema_module + App.Registers: завершённость, эффективность, риски, вердикт |

## Дополнительно

- [USER_GUIDE.md](USER_GUIDE.md) — руководство пользователя (часть примеров по старому API)
- [TOOLS_GUIDE.md](TOOLS_GUIDE.md) — SchemaVisualizer, SchemaDocumentationGenerator
- [EXTENDING_GUIDE.md](EXTENDING_GUIDE.md) — расширение форматеров визуализации
- [DNA_USAGE_EXAMPLES.md](DNA_USAGE_EXAMPLES.md) — примеры ДНК компонентов (опционально)
- [examples/](examples/) — примеры кода (в т.ч. [03_registers_and_data_packages.py](examples/03_registers_and_data_packages.py) — discovery по суффиксу)

Актуальный API и быстрый старт — в [../README.md](../README.md).
