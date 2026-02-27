# Быстрое руководство по запуску тестов

## 🚀 Быстрый старт

### Запуск всех тестов

```bash
# Из корня проекта
python src/multiprocess_framework/refactored/run_all_tests.py
```

### Запуск тестов конкретного модуля

```bash
# Используя скрипт
python src/multiprocess_framework/refactored/run_all_tests.py --module worker_module

# Или напрямую через pytest/unittest
pytest src/multiprocess_framework/refactored/modules/worker_module/tests -v
```

### Проверка модуля (структура, импорты, тесты, валидация)

```bash
python src/multiprocess_framework/refactored/check_module.py worker_module --all
```

## 📋 Модули и типы тестов

### Pytest тесты (большинство модулей)

```bash
# WorkerModule
pytest src/multiprocess_framework/refactored/modules/worker_module/tests -v

# ProcessModule
pytest src/multiprocess_framework/refactored/modules/process_module/tests -v

# DispatchModule
pytest src/multiprocess_framework/refactored/modules/dispatch_module/tests -v

# BaseManager
pytest src/multiprocess_framework/refactored/modules/base_manager/tests -v

# DataSchemaModule
pytest src/multiprocess_framework/refactored/modules/data_schema_module/tests -v

# MessageModule
pytest src/multiprocess_framework/refactored/modules/message_module/tests -v

# SharedResourcesModule
pytest src/multiprocess_framework/refactored/modules/shared_resources_module/tests -v
```

### Unittest тесты

```bash
# ConsoleModule
python -m unittest discover -s src/multiprocess_framework/refactored/modules/console_module/tests -p "test_*.py" -v

# ConfigModule
python -m unittest discover -s src/multiprocess_framework/refactored/modules/config_module/tests -p "test_*.py" -v
```

## 🔧 Полезные опции

### Подробный вывод ошибок

```bash
pytest src/multiprocess_framework/refactored/modules/worker_module/tests -v --tb=long
```

### Покрытие кода

```bash
pytest src/multiprocess_framework/refactored/modules/worker_module/tests --cov=modules/worker_module --cov-report=html
```

### Только конкретный тест

```bash
pytest src/multiprocess_framework/refactored/modules/worker_module/tests/test_worker_manager.py::TestWorkerManager::test_create_manager -v
```

## ✅ Ожидаемые результаты

После исправлений ожидается:

- **WorkerModule:** 13/13 тестов ✅
- **ProcessModule:** 13/13 тестов ✅
- **DispatchModule:** 42/42 тестов ✅
- **BaseManager:** 33/33 тестов ✅
- **DataSchemaModule:** 53/53 тестов ✅
- **MessageModule:** Все тесты ✅
- **SharedResourcesModule:** Все тесты ✅
- **ConsoleModule:** Все тесты ✅
- **ConfigModule:** Все тесты ✅

## 🛠️ Скрипты

### run_all_tests.py

Запуск всех тестов или конкретного модуля:

```bash
# Все тесты
python src/multiprocess_framework/refactored/run_all_tests.py

# Конкретный модуль
python src/multiprocess_framework/refactored/run_all_tests.py --module worker_module

# Только pytest тесты
python src/multiprocess_framework/refactored/run_all_tests.py --pytest-only

# Только unittest тесты
python src/multiprocess_framework/refactored/run_all_tests.py --unittest-only
```

### check_module.py

Проверка модуля (структура, импорты, тесты, валидация):

```bash
# Все проверки
python src/multiprocess_framework/refactored/check_module.py worker_module --all

# Только тесты
python src/multiprocess_framework/refactored/check_module.py worker_module --tests

# Только валидация
python src/multiprocess_framework/refactored/check_module.py worker_module --validate
```

## 📊 Валидация модулей

```bash
# Все модули
python -m multiprocess_framework.refactored.tools.validate_all_modules

# Конкретный модуль
python -m multiprocess_framework.refactored.tools.validate_all_modules worker_module
```

## 🎯 Приоритет проверки

1. **Критичные модули (исправлены):**
   - WorkerModule
   - ProcessModule
   - DispatchModule
   - BaseManager
   - DataSchemaModule

2. **Модули с правильным кодом:**
   - MessageModule
   - SharedResourcesModule
   - ConsoleModule
   - ConfigModule

3. **Остальные модули:**
   - RouterModule
   - CommandModule
   - LoggerModule

---

**Все исправления выполнены. Запустите тесты для проверки!**

