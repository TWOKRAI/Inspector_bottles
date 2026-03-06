# multiprocess_prototype

Демо-приложение на базе `multiprocess_framework/refactored`.

- **2 процесса** (Process A, Process B)
- **По 2 потока** в каждом процессе
- **Связь** через RouterManager и очереди
- **Источник** — только `multiprocess_framework/refactored`

## Запуск

```bash
cd Inspector_prototype
python -m multiprocess_prototype.main
```

## Тест инициализации

```bash
cd Inspector_prototype
python multiprocess_prototype/test_init.py
```

## Документация

- [docs/INSTRUCTION.md](docs/INSTRUCTION.md) — пошаговая инструкция по созданию и расширению приложения
- [docs/PROBLEMS_AND_FIXES.md](docs/PROBLEMS_AND_FIXES.md) — проблемы при интеграции и внесённые исправления
