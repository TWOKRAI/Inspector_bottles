# Руководство по Тестированию Multiprocess Framework

## 📋 Содержание

- [Установка зависимостей](#установка-зависимостей)
- [Запуск тестов](#запуск-тестов)
- [Список всех тестов](#список-всех-тестов)
- [Структура тестов](#структура-тестов)
- [Интеграционные тесты](#интеграционные-тесты)
- [Покрытие кода](#покрытие-кода)

---

## Установка зависимостей

### Базовые зависимости

```bash
pip install pytest pytest-cov
```

### Все зависимости для разработки

```bash
pip install -e ".[dev]"
```

---

## Запуск тестов

### Все тесты в refactored

```bash
# Из корня проекта
pytest src/multiprocess_framework/refactored -v

# С покрытием кода
pytest src/multiprocess_framework/refactored --cov=src/multiprocess_framework/refactored --cov-report=html -v
```

### Конкретный модуль

```bash
# BaseManager
pytest src/multiprocess_framework/refactored/modules/base_manager/tests -v

# ProcessModule
pytest src/multiprocess_framework/refactored/modules/process_module/tests -v

# RouterModule
pytest src/multiprocess_framework/refactored/modules/router_module/tests -v
```

### Конкретный тест

```bash
# Конкретный файл
pytest src/multiprocess_framework/refactored/modules/base_manager/tests/test_base_manager.py -v

# Конкретный тест
pytest src/multiprocess_framework/refactored/modules/base_manager/tests/test_base_manager.py::TestBaseManager::test_create_manager -v
```

### С маркерами

```bash
# Только юнит-тесты
pytest src/multiprocess_framework/refactored -m unit -v

# Только интеграционные тесты
pytest src/multiprocess_framework/refactored -m integration -v

# Быстрые тесты
pytest src/multiprocess_framework/refactored -m fast -v

# Медленные тесты
pytest src/multiprocess_framework/refactored -m slow -v
```

### С подробным выводом

```bash
# Подробный вывод
pytest src/multiprocess_framework/refactored -v -s

# С выводом print
pytest src/multiprocess_framework/refactored -v -s --capture=no
```

---

## Список всех тестов

### BaseManager Module (Основа всех менеджеров)

**Расположение:** `modules/base_manager/tests/`

| Файл | Тесты | Описание |
|------|-------|----------|
| [test_base_manager.py](modules/base_manager/tests/test_base_manager.py) | `test_create_manager`<br>`test_initialize`<br>`test_shutdown`<br>`test_attach_adapter`<br>`test_get_adapter`<br>`test_magic_adapter_access`<br>`test_stats`<br>`test_events` | Тесты базового менеджера: создание, инициализация, адаптеры, статистика, события |
| [test_observable_mixin.py](modules/base_manager/tests/test_observable_mixin.py) | `test_logging`<br>`test_statistics`<br>`test_error_handling`<br>`test_auto_proxy`<br>`test_private_methods` | Тесты ObservableMixin: логирование, статистика, обработка ошибок |
| [test_plugin_system.py](modules/base_manager/tests/test_plugin_system.py) | `test_register_plugin`<br>`test_load_plugin`<br>`test_plugin_lifecycle`<br>`test_plugin_events` | Тесты системы плагинов: регистрация, загрузка, жизненный цикл |
| [test_refactored_mixin.py](modules/base_manager/tests/test_refactored_mixin.py) | `test_unified_mixin`<br>`test_backward_compatibility`<br>`test_performance` | Тесты унифицированного миксина: совместимость, производительность |

**Интеграционные тесты:**
- [test_base_manager_integration.py](../tests/test_base_manager_integration.py) - Интеграционные тесты BaseManager и BaseAdapter

---

### ProcessModule (Эго - Базовый Процесс)

**Расположение:** `modules/process_module/tests/`

| Файл | Тесты | Описание |
|------|-------|----------|
| [test_process_module.py](modules/process_module/tests/test_process_module.py) | `test_create_process`<br>`test_initialize`<br>`test_shutdown`<br>`test_lifecycle`<br>`test_managers` | Тесты базового процесса: создание, инициализация, жизненный цикл, менеджеры |

---

### ProcessManagerModule (Сверхэго - Координатор)

**Расположение:** `modules/process_manager_module/tests/`

*Тесты пока не реализованы*

---

### WorkerModule (Ид - Потоки Выполнения)

**Расположение:** `modules/worker_module/tests/`

| Файл | Тесты | Описание |
|------|-------|----------|
| [test_worker_manager.py](modules/worker_module/tests/test_worker_manager.py) | `test_create_worker`<br>`test_start_worker`<br>`test_stop_worker`<br>`test_worker_priority`<br>`test_worker_metrics`<br>`test_auto_restart` | Тесты менеджера воркеров: создание, запуск, остановка, приоритеты, метрики |

---

### RouterModule (Спинной Мозг - Нервная Система)

**Расположение:** `modules/router_module/tests/`

| Файл | Тесты | Описание |
|------|-------|----------|
| [test_router_manager.py](modules/router_module/tests/test_router_manager.py) | `test_create_router`<br>`test_register_channel`<br>`test_send_message`<br>`test_receive_message`<br>`test_poll_messages`<br>`test_channel_routing` | Тесты менеджера маршрутизации: создание, каналы, отправка/получение сообщений |
| [test_channels.py](modules/router_module/tests/test_channels.py) | `test_queue_channel`<br>`test_internal_channel`<br>`test_log_channel`<br>`test_custom_channel` | Тесты каналов: очереди, внутренние, лог, пользовательские |

---

### MessageModule (Мысли/Сигналы)

**Расположение:** `modules/message_module/tests/`

| Файл | Тесты | Описание |
|------|-------|----------|
| [test_message.py](modules/message_module/tests/test_message.py) | `test_create_general_message`<br>`test_create_command_message`<br>`test_create_log_message`<br>`test_create_system_message`<br>`test_message_validation`<br>`test_message_serialization` | Тесты создания сообщений: типы сообщений, валидация, сериализация |
| [test_schemas.py](modules/message_module/tests/test_schemas.py) | `test_message_schema`<br>`test_command_schema`<br>`test_log_schema`<br>`test_system_schema` | Тесты схем сообщений: валидация схем, структура данных |

---

### ConfigModule (ДНК - Базовая)

**Расположение:** `modules/config_module/tests/`

| Файл | Тесты | Описание |
|------|-------|----------|
| [test_config_manager.py](modules/config_module/tests/test_config_manager.py) | `test_create_config`<br>`test_get_set_config`<br>`test_hierarchical_config`<br>`test_hot_reload`<br>`test_config_validation` | Тесты менеджера конфигурации: создание, получение/установка, иерархия, hot-reload |
| [test_config_section.py](modules/config_module/tests/test_config_section.py) | `test_create_section`<br>`test_section_access`<br>`test_section_validation` | Тесты секций конфигурации: создание, доступ, валидация |
| [test_config.py](modules/config_module/tests/test_config.py) | `test_base_config`<br>`test_config_inheritance`<br>`test_config_defaults` | Тесты базовой конфигурации: наследование, значения по умолчанию |

---

### DataSchemaModule (ДНК - Расширенная)

**Расположение:** `modules/data_schema_module/tests/`

| Файл | Тесты | Описание |
|------|-------|----------|
| [test_schema_registry.py](modules/data_schema_module/tests/test_schema_registry.py) | `test_register_schema`<br>`test_get_schema`<br>`test_schema_validation` | Тесты реестра схем: регистрация, получение, валидация |
| [test_factory.py](modules/data_schema_module/tests/test_factory.py) | `test_create_model`<br>`test_model_validation`<br>`test_model_conversion`<br>`test_dna_factory` | Тесты фабрики моделей: создание, валидация, конвертация, ДНК |
| [test_converters.py](modules/data_schema_module/tests/test_converters.py) | `test_dict_to_model`<br>`test_model_to_dict`<br>`test_json_conversion`<br>`test_yaml_conversion` | Тесты конвертеров: dict, JSON, YAML, модели |
| [test_validators.py](modules/data_schema_module/tests/test_validators.py) | `test_pydantic_validation`<br>`test_custom_validators`<br>`test_validation_errors` | Тесты валидаторов: Pydantic, пользовательские, ошибки |
| [test_utils.py](modules/data_schema_module/tests/test_utils.py) | `test_helpers`<br>`test_references`<br>`test_migration` | Тесты утилит: помощники, ссылки, миграция |
| [test_version_manager.py](modules/data_schema_module/tests/test_version_manager.py) | `test_version_registration`<br>`test_version_migration`<br>`test_version_compatibility` | Тесты менеджера версий: регистрация, миграция, совместимость |
| [test_schema_visualizer.py](modules/data_schema_module/tests/test_schema_visualizer.py) | `test_visualize_schema`<br>`test_generate_diagram`<br>`test_export_formats` | Тесты визуализации схем: визуализация, диаграммы, экспорт |
| [test_schema_documentation_generator.py](modules/data_schema_module/tests/test_schema_documentation_generator.py) | `test_generate_docs`<br>`test_doc_formats`<br>`test_doc_templates` | Тесты генерации документации: генерация, форматы, шаблоны |

**Всего тестов в модуле: 53** ✅

---

### SharedResourcesModule (Память и Архив)

**Расположение:** `modules/shared_resources_module/tests/`

| Файл | Тесты | Описание |
|------|-------|----------|
| [test_shared_resources_manager.py](modules/shared_resources_module/tests/test_shared_resources_manager.py) | `test_create_manager`<br>`test_register_process`<br>`test_get_process_data`<br>`test_dynamic_access` | Тесты главного менеджера: создание, регистрация процессов, получение данных |
| [test_queue_registry.py](modules/shared_resources_module/tests/test_queue_registry.py) | `test_create_queues`<br>`test_send_to_queue`<br>`test_receive_from_queue`<br>`test_broadcast_message` | Тесты реестра очередей: создание, отправка, получение, broadcast |
| [test_memory_manager.py](modules/shared_resources_module/tests/test_memory_manager.py) | `test_create_memory`<br>`test_write_images`<br>`test_read_images`<br>`test_release_memory`<br>`test_find_free_index` | Тесты менеджера памяти: создание, запись/чтение изображений, освобождение |
| [test_event_manager.py](modules/shared_resources_module/tests/test_event_manager.py) | `test_emit_event`<br>`test_subscribe`<br>`test_wait_for_event`<br>`test_event_types` | Тесты менеджера событий: отправка, подписка, ожидание, типы событий |

---

### LoggerModule (Система Мониторинга)

**Расположение:** `modules/logger_module/tests/`

*Тесты пока не реализованы*

---

### CommandModule (Исполнительная Система)

**Расположение:** `modules/command_module/tests/`

| Файл | Тесты | Описание |
|------|-------|----------|
| [test_command_manager.py](modules/command_module/tests/test_command_manager.py) | `test_register_command`<br>`test_handle_command`<br>`test_command_metadata`<br>`test_command_scenarios` | Тесты менеджера команд: регистрация, выполнение, метаданные, сценарии |
| [test_command_adapter.py](modules/command_module/tests/test_command_adapter.py) | `test_adapter_setup`<br>`test_adapter_execute`<br>`test_adapter_list` | Тесты адаптера команд: настройка, выполнение, список команд |
| [test_base_command_manager.py](modules/command_module/tests/test_base_command_manager.py) | `test_base_interface`<br>`test_abstract_methods` | Тесты базового менеджера команд: интерфейс, абстрактные методы |

---

### DispatchModule (Рефлексы)

**Расположение:** `modules/dispatch_module/tests/`

| Файл | Тесты | Описание |
|------|-------|----------|
| [test_dispatcher.py](modules/dispatch_module/tests/test_dispatcher.py) | `test_create_dispatcher`<br>`test_register_handler`<br>`test_dispatch_message`<br>`test_multiple_strategies` | Тесты диспетчера: создание, регистрация обработчиков, диспетчеризация |
| [test_strategies.py](modules/dispatch_module/tests/test_strategies.py) | `test_exact_match`<br>`test_pattern_match`<br>`test_fallback_match`<br>`test_chain_match` | Тесты стратегий: точное совпадение, паттерн, fallback, цепочки |
| [test_types.py](modules/dispatch_module/tests/test_types.py) | `test_dispatch_strategy`<br>`test_handler_info`<br>`test_scenario` | Тесты типов данных: стратегии, информация об обработчиках, сценарии |
| [test_scenario_builder.py](modules/dispatch_module/tests/test_scenario_builder.py) | `test_build_scenario`<br>`test_scenario_execution`<br>`test_scenario_validation` | Тесты построителя сценариев: построение, выполнение, валидация |

---

### ConsoleModule (Интерфейс с Внешним Миром)

**Расположение:** `modules/console_module/tests/`

| Файл | Тесты | Описание |
|------|-------|----------|
| [test_console_manager.py](modules/console_module/tests/test_console_manager.py) | `test_create_manager`<br>`test_console_output`<br>`test_console_input` | Тесты менеджера консоли: создание, вывод, ввод |
| [test_console_channel.py](modules/console_module/tests/test_console_channel.py) | `test_channel_creation`<br>`test_channel_io` | Тесты канала консоли: создание, ввод/вывод |
| [test_console_redirector.py](modules/console_module/tests/test_console_redirector.py) | `test_redirect_stdout`<br>`test_redirect_stderr` | Тесты редиректора консоли: перенаправление stdout/stderr |
| [test_basic.py](modules/console_module/test_basic.py) | `test_basic_functionality` | Базовые тесты функциональности консоли |

---

### Интеграционные тесты

**Расположение:** `tests/`

| Файл | Тесты | Описание |
|------|-------|----------|
| [test_base_manager_integration.py](tests/test_base_manager_integration.py) | `test_manager_adapter_integration`<br>`test_observable_mixin_integration`<br>`test_plugin_system_integration`<br>`test_full_lifecycle` | Интеграционные тесты BaseManager: менеджер-адаптер, ObservableMixin, плагины, полный жизненный цикл |
| [test_triada_integration.py](tests/test_triada_integration.py) | `test_process_manager_process_module_integration`<br>`test_worker_manager_integration`<br>`test_full_triada_workflow` | Интеграционные тесты "Тройцы": ProcessManagerCore-ProcessModule-WorkerManager, полный workflow |

---

## Структура тестов

### Организация тестов

```
refactored/
├── modules/
│   └── {module_name}/
│       └── tests/
│           ├── __init__.py
│           ├── test_*.py          # Юнит-тесты модуля
│           └── ...
│
└── tests/
    ├── test_base_manager_integration.py    # Интеграционные тесты
    └── test_triada_integration.py          # Интеграционные тесты "Тройцы"
```

### Стандарт именования

- **Файлы тестов:** `test_*.py`
- **Классы тестов:** `Test*`
- **Функции тестов:** `test_*`

### Структура теста

```python
"""
Тесты для {ModuleName}.
"""

import pytest
from ..core.module_name import ModuleClass


class TestModuleClass:
    """Тесты для ModuleClass."""
    
    def test_create_module(self):
        """Тест создания модуля."""
        module = ModuleClass("test_module")
        assert module.name == "test_module"
    
    def test_initialize(self):
        """Тест инициализации модуля."""
        module = ModuleClass("test_module")
        result = module.initialize()
        assert result is True
        assert module.is_initialized is True
```

---

## Интеграционные тесты

### Текущие интеграционные тесты

1. **test_base_manager_integration.py** - Интеграция BaseManager и BaseAdapter
2. **test_triada_integration.py** - Интеграция "Тройцы" (ProcessManagerCore-ProcessModule-WorkerManager)

### Планируемые интеграционные тесты

- [ ] Интеграция RouterModule с MessageModule
- [ ] Интеграция ProcessModule с SharedResourcesModule
- [ ] Интеграция ConfigModule с DataSchemaModule
- [ ] Интеграция LoggerModule с RouterModule
- [ ] Интеграция CommandModule с DispatchModule
- [ ] Полная интеграция всех модулей

---

## Покрытие кода

### Запуск с покрытием

```bash
# HTML отчет
pytest src/multiprocess_framework/refactored --cov=src/multiprocess_framework/refactored --cov-report=html -v

# Консольный отчет
pytest src/multiprocess_framework/refactored --cov=src/multiprocess_framework/refactored --cov-report=term-missing -v

# XML отчет (для CI/CD)
pytest src/multiprocess_framework/refactored --cov=src/multiprocess_framework/refactored --cov-report=xml -v
```

### Просмотр отчета

После генерации HTML отчета откройте `htmlcov/index.html` в браузере.

---

## Статистика тестов

### Общее количество тестов

**Собрано тестов:** 221 тест  
**Работающих тестов:** 188 тестов (14 с ошибками импорта)  
**Прошло тестов:** 161 тест ✅  
**Провалилось тестов:** 27 тестов ❌  
**Процент успешности:** 73% (161/188)

**Подробный статус:** См. [TEST_STATUS.md](TEST_STATUS.md)

- **BaseManager:** 4 файла тестов (40+ тестов)
  - test_base_manager.py: 10 тестов
  - test_observable_mixin.py: 10 тестов
  - test_plugin_system.py: 6 тестов
  - test_refactored_mixin.py: 7 тестов
  
- **ProcessModule:** 1 файл тестов (13 тестов)
  - test_process_module.py: 13 тестов
  
- **WorkerModule:** 1 файл тестов (13 тестов)
  - test_worker_manager.py: 13 тестов
  
- **RouterModule:** 1 файл тестов (9 тестов)
  - test_channels.py: 9 тестов
  
- **MessageModule:** 0 файлов тестов (ошибки импорта)
  
- **ConfigModule:** 0 файлов тестов (ошибки импорта)
  
- **DataSchemaModule:** 8 файлов тестов (53 теста)
  - test_converters.py: 2 теста
  - test_factory.py: 11 тестов
  - test_schema_documentation_generator.py: 15 тестов
  - test_schema_registry.py: 2 теста
  - test_schema_visualizer.py: 13 тестов
  - test_utils.py: 3 теста
  - test_validators.py: 1 тест
  - test_version_manager.py: 6 тестов
  
- **SharedResourcesModule:** 0 файлов тестов (ошибки импорта)
  
- **CommandModule:** 3 файла тестов (18 тестов)
  - test_base_command_manager.py: 5 тестов
  - test_command_adapter.py: 6 тестов
  - test_command_manager.py: 12 тестов
  
- **DispatchModule:** 4 файла тестов (42 теста)
  - test_dispatcher.py: 15 тестов
  - test_scenario_builder.py: 11 тестов
  - test_strategies.py: 11 тестов
  - test_types.py: 5 тестов
  
- **ConsoleModule:** 0 файлов тестов (ошибки импорта)
  
- **Интеграционные:** 2 файла тестов (20 тестов)
  - test_base_manager_integration.py: 14 тестов
  - test_triada_integration.py: 6 тестов

**Всего:** 38 файлов тестов, 221 тест собран, но есть проблемы с импортами в некоторых модулях

### Проблемы с импортами и тестами

Следующие модули имеют проблемы и требуют исправления:

1. **ConfigModule** - неправильный импорт `base_manager.interfaces` (ошибки импорта)
2. **ConsoleModule** - неправильный импорт `base_manager.interfaces` (ошибки импорта)
3. **MessageModule** - отсутствует функция `generate_message_id` в utils (ошибки импорта)
4. **RouterModule** - неправильный импорт `Dispatch_module` в test_router_manager.py (ошибка импорта)
5. **SharedResourcesModule** - неправильный импорт `process_module.process_state_registry` (ошибки импорта)
6. **WorkerModule** - все тесты провалились из-за `WorkerRegistry.is_enabled` (27 провалов)
7. **ProcessModule** - 3 теста провалились из-за ObservableMixin (3 провала)
8. **BaseManager** - 1 тест провалился (`test_error_tracking`)
9. **DataSchemaModule** - 1 тест провалился (`test_data_converter_roundtrips` - Pydantic v2)
10. **DispatchModule** - 1 тест провалился (`test_reorder_handler`)

**Подробный статус:** См. [TEST_STATUS.md](TEST_STATUS.md)

---

## Рекомендации

### Перед коммитом

```bash
# Запустить все тесты
pytest src/multiprocess_framework/refactored -v

# Проверить покрытие
pytest src/multiprocess_framework/refactored --cov=src/multiprocess_framework/refactored --cov-report=term-missing
```

### При разработке нового модуля

1. Создать папку `tests/` в модуле
2. Создать `__init__.py` в папке тестов
3. Написать тесты для всех публичных методов
4. Запустить тесты: `pytest modules/{module_name}/tests -v`
5. Проверить покрытие: `pytest modules/{module_name}/tests --cov=modules/{module_name}`

---

*Руководство по тестированию v1.0*  
*Inspector Bottle V2 - Multiprocess Framework*

