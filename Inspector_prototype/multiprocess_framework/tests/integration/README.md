# Интеграционные тесты фреймворка

Тесты, проверяющие взаимодействие компонентов фреймворка multiprocess_framework.

## Структура

- `test_launcher_integration.py` - интеграция SystemLauncher с ProcessManagerBootstrap
- `test_main_launcher.py` - тесты главного запускателя системы
- `test_integration.py` - общие интеграционные тесты SharedResources

## Отличие от unit тестов

**Unit тесты** (в `test_*_module/`):
- Тестируют отдельные модули изолированно
- Быстрые
- Не требуют запуска всей системы

**Интеграционные тесты** (здесь):
- Тестируют взаимодействие компонентов фреймворка
- Проверяют работу SystemLauncher
- Могут быть медленнее unit тестов
- Требуют запуска процессов

## Запуск

```bash
# Все интеграционные тесты
pytest src/multiprocess_framework/tests/integration/

# Конкретный тест
pytest src/multiprocess_framework/tests/integration/test_launcher_integration.py

# С подробным выводом
pytest src/multiprocess_framework/tests/integration/ -v
```

## Что тестируется

1. **SystemLauncher** - запуск и остановка системы процессов
2. **ProcessManagerBootstrap** - инициализация ProcessManager
3. **SharedResources** - взаимодействие процессов через общие ресурсы
4. **Взаимодействие процессов** - коммуникация между процессами
