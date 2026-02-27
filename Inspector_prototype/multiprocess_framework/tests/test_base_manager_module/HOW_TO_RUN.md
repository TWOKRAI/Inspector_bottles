# Как запустить тесты

## Простой способ

```bash
# 1. Активируйте виртуальное окружение
venv\Scripts\Activate.ps1

# 2. Убедитесь что вы в корневой директории проекта
cd C:\Users\INNOTECH\Desktop\PROJECT_INNOTECH\Inspector_bottle_V2

# 3. Запустите все тесты
pytest src/multiprocess_framework/tests/test_base_manager_module/ -v
```

**Важно:** Запускайте pytest из корневой директории проекта, где находится папка `src`.

## Детальные команды

### Все тесты модуля
```bash
pytest src/multiprocess_framework/tests/test_base_manager_module/ -v
```

### Конкретный файл тестов
```bash
# BaseManager
pytest src/multiprocess_framework/tests/test_base_manager_module/test_base_manager.py -v

# BaseAdapter
pytest src/multiprocess_framework/tests/test_base_manager_module/test_base_adapter.py -v

# ObservableMixin
pytest src/multiprocess_framework/tests/test_base_manager_module/test_observable_mixin.py -v
```

### Конкретный тест
```bash
pytest src/multiprocess_framework/tests/test_base_manager_module/test_base_manager.py::TestBaseManager::test_initialization_with_name_only -v
```

### С покрытием кода
```bash
pytest src/multiprocess_framework/tests/test_base_manager_module/ --cov=src.multiprocess_framework.modules.Base_manager_module --cov-report=html
```

После этого откройте `htmlcov/index.html` в браузере.

### Полезные опции
```bash
# Показать print statements
pytest src/multiprocess_framework/tests/test_base_manager_module/ -v -s

# Остановиться на первой ошибке
pytest src/multiprocess_framework/tests/test_base_manager_module/ -v -x

# Показать локальные переменные при ошибке
pytest src/multiprocess_framework/tests/test_base_manager_module/ -v -l
```

## Если pytest не найден

Убедитесь что:
1. Виртуальное окружение активировано
2. pytest установлен: `pip install pytest pytest-cov`

## Проверка что все работает

```bash
# Проверка что pytest видит тесты
pytest src/multiprocess_framework/tests/test_base_manager_module/ --collect-only

# Должно показать список всех тестов
```

