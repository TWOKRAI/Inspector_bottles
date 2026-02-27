# Тесты для Console_module

## Запуск тестов

```bash
# Все тесты модуля
pytest tests/Test_Console_module/

# Конкретный файл
pytest tests/Test_Console_module/test_console_manager.py

# С выводом
pytest tests/Test_Console_module/ -v

# С покрытием
pytest tests/Test_Console_module/ --cov=src.Modules.Console_module
```

## Структура тестов

- `test_console_manager.py` - основные тесты ConsoleManager
  - Базовые операции
  - Группировка процессов
  - Кастомные каналы
  - Интеграция с Router
  - Перенаправление вывода

## Покрытие

Тесты покрывают:
- ✅ Настройку консолей для процессов
- ✅ Группировку процессов
- ✅ Создание кастомных каналов
- ✅ Интеграцию с RouterManager
- ✅ Перенаправление stdout/stderr
- ✅ Управление жизненным циклом консолей


