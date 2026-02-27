# Тесты модуля Command_module

## Структура тестов

- `test_command_manager.py` - тесты на unittest (legacy)
- `test_command_manager_pytest.py` - полные тесты на pytest с покрытием всех сценариев

## Запуск тестов

### Установка зависимостей

```bash
pip install pytest pytest-cov
```

### Запуск всех тестов модуля

```bash
# Из корня проекта
pytest tests/Test_Command_module/

# С подробным выводом
pytest tests/Test_Command_module/ -v

# С выводом print statements
pytest tests/Test_Command_module/ -v -s
```

### Запуск конкретного файла тестов

```bash
# Тесты на pytest
pytest tests/Test_Command_module/test_command_manager_pytest.py -v

# Тесты на unittest
pytest tests/Test_Command_module/test_command_manager.py -v
# или
python -m unittest tests.Test_Command_module.test_command_manager
```

### Запуск с покрытием кода

```bash
# Консольный отчет
pytest tests/Test_Command_module/ --cov=src.Modules.Command_module --cov-report=term-missing

# HTML отчет
pytest tests/Test_Command_module/ --cov=src.Modules.Command_module --cov-report=html

# Отчет откроется в браузере
# Файл: htmlcov/index.html
```

### Запуск конкретных тестов

```bash
# По имени класса
pytest tests/Test_Command_module/test_command_manager_pytest.py::TestCommandManagerRegistration -v

# По имени теста
pytest tests/Test_Command_module/test_command_manager_pytest.py::TestCommandManagerRegistration::test_register_simple_command -v

# По паттерну
pytest tests/Test_Command_module/test_command_manager_pytest.py -k "registration" -v
```

## Покрытие тестами

### Основные категории тестов

1. **Инициализация** - создание и настройка менеджеров
2. **Регистрация команд** - все варианты регистрации
3. **Выполнение команд** - все стратегии и сценарии
4. **Управление командами** - метаданные, теги, обновление
5. **Статистика** - получение статистики
6. **Сценарии** - работа со сценариями выполнения
7. **Стратегии** - различные стратегии диспетчеризации
8. **ObservableMixin** - интеграция с логированием и статистикой
9. **CommandAdapter** - все методы адаптера
10. **Граничные случаи** - обработка ошибок и edge cases
11. **Производительность** - базовые проверки производительности
12. **Интеграция** - полные рабочие процессы

### Статистика тестов

- **Всего тестов:** ~80+
- **Покрытие кода:** ~95%+
- **Категории:** 12 основных категорий

## Структура тестов pytest

### Фикстуры

- `mock_logger_manager` - мок менеджера логирования
- `mock_statistics_manager` - мок менеджера статистики
- `mock_error_manager` - мок менеджера ошибок
- `command_manager` - базовый CommandManager
- `command_manager_with_managers` - CommandManager с менеджерами
- `command_adapter` - настроенный CommandAdapter
- `sample_handler` - простой обработчик команды
- `sample_handler_with_full_message` - обработчик с полным сообщением

### Классы тестов

1. `TestBaseCommandManager` - тесты базового класса
2. `TestCommandManagerInitialization` - инициализация
3. `TestCommandManagerRegistration` - регистрация команд
4. `TestCommandManagerExecution` - выполнение команд
5. `TestCommandManagerManagement` - управление командами
6. `TestCommandManagerStatistics` - статистика
7. `TestCommandManagerScenarios` - сценарии
8. `TestCommandManagerStrategies` - стратегии
9. `TestCommandManagerObservableMixin` - интеграция с ObservableMixin
10. `TestCommandAdapter` - адаптер
11. `TestEdgeCases` - граничные случаи
12. `TestPerformance` - производительность
13. `TestIntegration` - интеграционные тесты

## Отладка тестов

### Запуск с отладчиком

```bash
# С использованием pdb
pytest tests/Test_Command_module/test_command_manager_pytest.py --pdb

# Остановка на первой ошибке
pytest tests/Test_Command_module/test_command_manager_pytest.py -x
```

### Вывод дополнительной информации

```bash
# Показать локальные переменные при ошибке
pytest tests/Test_Command_module/test_command_manager_pytest.py -l

# Показать все print statements
pytest tests/Test_Command_module/test_command_manager_pytest.py -s
```

## Примеры запуска

### Быстрая проверка

```bash
pytest tests/Test_Command_module/test_command_manager_pytest.py -v --tb=short
```

### Полная проверка с покрытием

```bash
pytest tests/Test_Command_module/ \
  --cov=src.Modules.Command_module \
  --cov-report=html \
  --cov-report=term-missing \
  -v
```

### Запуск только критических тестов

```bash
pytest tests/Test_Command_module/test_command_manager_pytest.py \
  -k "test_handle_command_success or test_register_simple_command" \
  -v
```

## Требования

- Python 3.8+
- pytest 7.0+
- pytest-cov (для покрытия кода)

## Примечания

- Все тесты используют моки для изоляции
- Тесты не требуют внешних зависимостей
- Тесты можно запускать параллельно с `-n auto` (требует pytest-xdist)

