# Руководство по Тестированию Multiprocess Framework

## 📋 Содержание

- [Быстрый Старт](#быстрый-старт)
- [Запуск Тестов](#запуск-тестов)
- [Список Тестов](#список-тестов)
- [Покрытие Кода](#покрытие-кода)
- [Интеграционные Тесты](#интеграционные-тесты)
- [Написание Новых Тестов](#написание-новых-тестов)

---

## 🚀 Быстрый Старт

### Установка зависимостей

```bash
# Активация виртуального окружения
# Windows PowerShell
. venv\Scripts\Activate.ps1

# Linux/Mac
source venv/bin/activate

# Установка pytest и зависимостей
pip install pytest pytest-cov pytest-mock
```

### Запуск всех тестов

```bash
# Из корня проекта
pytest src/multiprocess_framework/refactored/ -v

# С покрытием кода
pytest src/multiprocess_framework/refactored/ --cov=src/multiprocess_framework/refactored --cov-report=html
```

---

## 🧪 Запуск Тестов

### Все тесты в refactored

```bash
# Все тесты
pytest src/multiprocess_framework/refactored/ -v

# Только юнит-тесты
pytest src/multiprocess_framework/refactored/ -v -m unit

# Только интеграционные тесты
pytest src/multiprocess_framework/refactored/ -v -m integration

# Быстрые тесты
pytest src/multiprocess_framework/refactored/ -v -m fast

# Медленные тесты
pytest src/multiprocess_framework/refactored/ -v -m slow
```

### Тесты конкретного модуля

```bash
# BaseManager
pytest src/multiprocess_framework/refactored/modules/base_manager/tests/ -v

# ProcessModule
pytest src/multiprocess_framework/refactored/modules/process_module/tests/ -v

# WorkerModule
pytest src/multiprocess_framework/refactored/modules/worker_module/tests/ -v

# RouterModule
pytest src/multiprocess_framework/refactored/modules/router_module/tests/ -v

# MessageModule
pytest src/multiprocess_framework/refactored/modules/message_module/tests/ -v

# ConfigModule
pytest src/multiprocess_framework/refactored/modules/config_module/tests/ -v

# DataSchemaModule
pytest src/multiprocess_framework/refactored/modules/data_schema_module/tests/ -v

# SharedResourcesModule
pytest src/multiprocess_framework/refactored/modules/shared_resources_module/tests/ -v

# LoggerModule
pytest src/multiprocess_framework/refactored/modules/logger_module/tests/ -v

# CommandModule
pytest src/multiprocess_framework/refactored/modules/command_module/tests/ -v

# DispatchModule
pytest src/multiprocess_framework/refactored/modules/dispatch_module/tests/ -v

# ConsoleModule
pytest src/multiprocess_framework/refactored/modules/console_module/tests/ -v
```

### Конкретный тест-файл

```bash
# Конкретный файл
pytest src/multiprocess_framework/refactored/modules/base_manager/tests/test_base_manager.py -v

# Конкретный тест
pytest src/multiprocess_framework/refactored/modules/base_manager/tests/test_base_manager.py::TestBaseManager::test_create_manager -v
```

### С покрытием кода

```bash
# Покрытие всего refactored
pytest src/multiprocess_framework/refactored/ \
    --cov=src/multiprocess_framework/refactored \
    --cov-report=html \
    --cov-report=term

# Покрытие конкретного модуля
pytest src/multiprocess_framework/refactored/modules/base_manager/tests/ \
    --cov=src/multiprocess_framework/refactored/modules/base_manager \
    --cov-report=html

# Минимальное покрытие 80%
pytest src/multiprocess_framework/refactored/ \
    --cov=src/multiprocess_framework/refactored \
    --cov-report=html \
    --cov-fail-under=80
```

---

## 📝 Список Тестов

### Интеграционные Тесты (refactored/tests/)

#### [test_base_manager_integration.py](tests/test_base_manager_integration.py)
**Описание:** Интеграционные тесты для BaseManager и BaseAdapter.

**Тесты:**
- `TestManagerAdapterIntegration` - Интеграция менеджера и адаптера
- `TestObservableMixinIntegration` - Интеграция ObservableMixin
- `TestFullWorkflow` - Полный рабочий процесс
- `TestErrorScenarios` - Сценарии ошибок

#### [test_triada_integration.py](tests/test_triada_integration.py)
**Описание:** Интеграционные тесты для "Тройцы создания циклов" (ProcessManagerCore, ProcessModule, WorkerManager).

**Тесты:**
- `TestTriadaIntegration::test_triada_initialization` - Инициализация всех трех классов
- `TestTriadaIntegration::test_triada_workflow` - Полный рабочий процесс Тройцы
- `TestTriadaIntegration::test_triada_error_handling` - Обработка ошибок

---

### BaseManager Module (modules/base_manager/tests/)

#### [test_base_manager.py](modules/base_manager/tests/test_base_manager.py)
**Описание:** Юнит-тесты для BaseManager.

**Тесты:**
- `TestBaseManager::test_create_manager` - Создание менеджера
- `TestBaseManager::test_initialize` - Инициализация менеджера
- `TestBaseManager::test_shutdown` - Завершение работы менеджера
- `TestBaseManager::test_attach_adapter` - Подключение адаптера
- `TestBaseManager::test_get_adapter` - Получение адаптера
- `TestBaseManager::test_magic_adapter_access` - Magic-доступ к адаптеру
- `TestBaseManager::test_stats` - Статистика менеджера
- `TestBaseManager::test_events` - События менеджера

#### [test_observable_mixin.py](modules/base_manager/tests/test_observable_mixin.py)
**Описание:** Тесты для ObservableMixin.

**Тесты:**
- `TestObservableMixin::test_logging` - Логирование через ObservableMixin
- `TestObservableMixin::test_statistics` - Статистика через ObservableMixin
- `TestObservableMixin::test_error_handling` - Обработка ошибок

#### [test_refactored_mixin.py](modules/base_manager/tests/test_refactored_mixin.py)
**Описание:** Тесты для рефакторенного ObservableMixin.

**Тесты:**
- `test_private_methods` - Приватные методы
- `test_auto_proxy` - Автоматические прокси-методы
- `test_both_methods` - Оба типа методов
- `test_register_manager` - Регистрация менеджеров
- `test_enable_disable` - Включение/отключение функций
- `test_context_manager` - Контекстный менеджер
- `test_decorators` - Декораторы

#### [test_plugin_system.py](modules/base_manager/tests/test_plugin_system.py)
**Описание:** Тесты для системы плагинов.

**Тесты:**
- `test_plugin_registration` - Регистрация плагинов
- `test_plugin_proxy_methods` - Прокси-методы плагинов
- `test_plugin_private_methods` - Приватные методы плагинов
- `test_dynamic_plugin_registration` - Динамическая регистрация
- `test_multiple_plugins` - Множественные плагины
- `test_plugin_with_auto_proxy` - Плагины с auto_proxy

---

### ProcessModule (modules/process_module/tests/)

#### [test_process_module.py](modules/process_module/tests/test_process_module.py)
**Описание:** Тесты для ProcessModule.

**Тесты:**
- `TestProcessModule::test_initialization` - Инициализация процесса
- `TestProcessModule::test_lifecycle` - Жизненный цикл процесса
- `TestProcessModule::test_managers` - Управление менеджерами
- `TestProcessModule::test_communication` - Коммуникация процесса

---

### WorkerModule (modules/worker_module/tests/)

#### [test_worker_manager.py](modules/worker_module/tests/test_worker_manager.py)
**Описание:** Тесты для WorkerManager.

**Тесты:**
- `TestWorkerManager::test_create_worker` - Создание воркера
- `TestWorkerManager::test_start_stop_worker` - Запуск/остановка воркера
- `TestWorkerManager::test_worker_priorities` - Приоритеты воркеров
- `TestWorkerManager::test_worker_metrics` - Метрики воркеров
- `TestWorkerManager::test_worker_restart` - Перезапуск воркеров

---

### RouterModule (modules/router_module/tests/)

#### [test_router_manager.py](modules/router_module/tests/test_router_manager.py)
**Описание:** Тесты для RouterManager.

**Тесты:**
- `TestRouterManager::test_initialization` - Инициализация роутера
- `TestRouterManager::test_register_channel` - Регистрация каналов
- `TestRouterManager::test_send_message` - Отправка сообщений
- `TestRouterManager::test_receive_message` - Получение сообщений
- `TestRouterManager::test_poll_messages` - Опрос сообщений

#### [test_channels.py](modules/router_module/tests/test_channels.py)
**Описание:** Тесты для каналов сообщений.

**Тесты:**
- `TestMessageChannelInterface` - Интерфейс каналов
- `TestQueueChannel` - Канал очередей

---

### MessageModule (modules/message_module/tests/)

#### [test_message.py](modules/message_module/tests/test_message.py)
**Описание:** Тесты для сообщений.

**Тесты:**
- `TestMessageCreation` - Создание сообщений
- `TestMessageValidation` - Валидация сообщений
- `TestMessageConversion` - Конвертация сообщений
- `TestFluentAPI` - Fluent API
- `TestDictInterface` - Интерфейс словаря
- `TestOtherMessageTypes` - Другие типы сообщений
- `TestYAMLConversion` - Конвертация YAML

#### [test_schemas.py](modules/message_module/tests/test_schemas.py)
**Описание:** Тесты для схем сообщений.

**Тесты:**
- `TestSchemaCreation` - Создание схем
- `TestSchemaInfo` - Информация о схемах
- `TestSchemaValidation` - Валидация схем
- `TestSchemaFromDict` - Создание из словаря
- `TestSchemaClone` - Клонирование схем
- `TestSchemaPerformance` - Производительность схем

---

### ConfigModule (modules/config_module/tests/)

#### [test_config_manager.py](modules/config_module/tests/test_config_manager.py)
**Описание:** Тесты для ConfigManager.

**Тесты:**
- `TestConfigManager::test_initialization` - Инициализация
- `TestConfigManager::test_get_set` - Получение/установка значений
- `TestConfigManager::test_update` - Обновление конфигурации
- `TestConfigManager::test_reload` - Перезагрузка конфигурации

#### [test_config_section.py](modules/config_module/tests/test_config_section.py)
**Описание:** Тесты для ConfigSection.

**Тесты:**
- `TestConfigSection::test_create_section` - Создание секции
- `TestConfigSection::test_get_set` - Получение/установка значений

#### [test_config.py](modules/config_module/tests/test_config.py)
**Описание:** Тесты для BaseConfig.

**Тесты:**
- `TestConfig::test_create_config` - Создание конфигурации
- `TestConfig::test_validation` - Валидация конфигурации

---

### DataSchemaModule (modules/data_schema_module/tests/)

#### [test_schema_registry.py](modules/data_schema_module/tests/test_schema_registry.py)
**Описание:** Тесты для SchemaRegistry.

**Тесты:**
- `test_schema_registry_basic_flow` - Базовый поток работы
- `test_schema_registry_thread_safety` - Потокобезопасность

#### [test_factory.py](modules/data_schema_module/tests/test_factory.py)
**Описание:** Тесты для ModelFactory.

**Тесты:**
- `test_create_manager` - Создание менеджера
- `test_create_manager_with_defaults` - Создание с дефолтами
- `test_from_dict` - Создание из словаря
- `test_from_dict_with_schema_name` - Создание из словаря с именем схемы
- `test_create_manager_auto_register` - Автоматическая регистрация
- `test_from_dict_missing_schema` - Отсутствующая схема
- `test_create_manager_missing_schema` - Отсутствующая схема при создании

#### [test_version_manager.py](modules/data_schema_module/tests/test_version_manager.py)
**Описание:** Тесты для VersionManager.

**Тесты:**
- `test_create_version` - Создание версии
- `test_get_current_version` - Получение текущей версии
- `test_get_version` - Получение версии
- `test_get_version_history` - История версий
- `test_rollback` - Откат версии
- `test_compare_versions` - Сравнение версий

#### [test_converters.py](modules/data_schema_module/tests/test_converters.py)
**Описание:** Тесты для конвертеров данных.

**Тесты:**
- `test_data_converter_roundtrips` - Конвертация туда-обратно
- `test_data_converter_file_operations` - Операции с файлами

#### [test_validators.py](modules/data_schema_module/tests/test_validators.py)
**Описание:** Тесты для валидаторов.

**Тесты:**
- `test_data_validator_variants` - Варианты валидации

#### [test_utils.py](modules/data_schema_module/tests/test_utils.py)
**Описание:** Тесты для утилит.

**Тесты:**
- `test_utils_nested_and_merge` - Вложенные структуры и слияние
- `test_data_reference_and_conversion` - Ссылки и конвертация данных
- `test_data_reference_from_dict` - Ссылки из словаря

#### [test_schema_visualizer.py](modules/data_schema_module/tests/test_schema_visualizer.py)
**Описание:** Тесты для визуализации схем.

**Тесты:**
- `test_visualize_schema_text` - Визуализация в тексте
- `test_visualize_schema_json` - Визуализация в JSON
- `test_visualize_schema_html` - Визуализация в HTML
- `test_visualize_schema_mermaid` - Визуализация в Mermaid
- `test_visualize_schema_missing_schema` - Отсутствующая схема
- `test_visualize_schema_invalid_format` - Неверный формат
- `test_visualize_schema_with_options` - Визуализация с опциями
- `test_visualize_all_schemas` - Визуализация всех схем
- `test_save_visualization` - Сохранение визуализации
- `test_register_formatter` - Регистрация форматтера
- `test_list_formats` - Список форматов
- `test_extract_schema_info` - Извлечение информации о схеме
- `test_format_all_as_html` - Форматирование всех как HTML

#### [test_schema_documentation_generator.py](modules/data_schema_module/tests/test_schema_documentation_generator.py)
**Описание:** Тесты для генератора документации схем.

**Тесты:**
- `test_generate_documentation_markdown` - Генерация Markdown
- `test_generate_documentation_rst` - Генерация RST
- `test_generate_documentation_html` - Генерация HTML
- `test_generate_documentation_with_examples` - Генерация с примерами
- `test_generate_documentation_without_examples` - Генерация без примеров
- `test_generate_documentation_all_schemas` - Генерация для всех схем
- `test_generate_api_reference` - Генерация API справочника
- `test_save_documentation` - Сохранение документации
- `test_register_formatter` - Регистрация форматтера
- `test_list_formats` - Список форматов
- `test_extract_schema_info` - Извлечение информации о схеме

---

### SharedResourcesModule (modules/shared_resources_module/tests/)

#### [test_shared_resources_manager.py](modules/shared_resources_module/tests/test_shared_resources_manager.py)
**Описание:** Тесты для SharedResourcesManager.

**Тесты:**
- `TestSharedResourcesManager::test_initialization` - Инициализация
- `TestSharedResourcesManager::test_register_process` - Регистрация процесса
- `TestSharedResourcesManager::test_get_process_data` - Получение данных процесса
- `TestSharedResourcesManager::test_update_process_state` - Обновление состояния

#### [test_queue_registry.py](modules/shared_resources_module/tests/test_queue_registry.py)
**Описание:** Тесты для QueueRegistry.

**Тесты:**
- `TestQueueRegistry::test_create_queues` - Создание очередей
- `TestQueueRegistry::test_send_receive` - Отправка/получение сообщений
- `TestQueueRegistry::test_broadcast` - Рассылка сообщений

#### [test_memory_manager.py](modules/shared_resources_module/tests/test_memory_manager.py)
**Описание:** Тесты для MemoryManager.

**Тесты:**
- `TestMemoryManager::test_create_memory` - Создание памяти
- `TestMemoryManager::test_write_read_images` - Запись/чтение изображений
- `TestMemoryManager::test_release_memory` - Освобождение памяти

#### [test_event_manager.py](modules/shared_resources_module/tests/test_event_manager.py)
**Описание:** Тесты для EventManager.

**Тесты:**
- `TestEventManager::test_emit_event` - Отправка события
- `TestEventManager::test_subscribe` - Подписка на события
- `TestEventManager::test_wait_for_event` - Ожидание события

---

### CommandModule (modules/command_module/tests/)

#### [test_command_manager.py](modules/command_module/tests/test_command_manager.py)
**Описание:** Тесты для CommandManager.

**Тесты:**
- `TestCommandManager::test_register_command` - Регистрация команды
- `TestCommandManager::test_execute_command` - Выполнение команды
- `TestCommandManager::test_command_metadata` - Метаданные команды

#### [test_command_adapter.py](modules/command_module/tests/test_command_adapter.py)
**Описание:** Тесты для CommandAdapter.

**Тесты:**
- `TestCommandAdapter::test_setup` - Настройка адаптера
- `TestCommandAdapter::test_register` - Регистрация через адаптер
- `TestCommandAdapter::test_execute` - Выполнение через адаптер

#### [test_base_command_manager.py](modules/command_module/tests/test_base_command_manager.py)
**Описание:** Тесты для BaseCommandManager.

**Тесты:**
- `TestBaseCommandManager::test_abstract_methods` - Абстрактные методы
- `TestBaseCommandManager::test_interface` - Интерфейс

---

### DispatchModule (modules/dispatch_module/tests/)

#### [test_dispatcher.py](modules/dispatch_module/tests/test_dispatcher.py)
**Описание:** Тесты для Dispatcher.

**Тесты:**
- `TestDispatcher::test_register_handler` - Регистрация обработчика
- `TestDispatcher::test_dispatch` - Диспетчеризация сообщений
- `TestDispatcher::test_multiple_strategies` - Множественные стратегии

#### [test_types.py](modules/dispatch_module/tests/test_types.py)
**Описание:** Тесты для типов данных.

**Тесты:**
- `TestDispatchStrategy` - Стратегии диспетчеризации
- `TestHandlerInfo` - Информация об обработчике
- `TestScenario` - Сценарии

#### [test_strategies.py](modules/dispatch_module/tests/test_strategies.py)
**Описание:** Тесты для стратегий диспетчеризации.

**Тесты:**
- `TestExactMatchStrategy` - Точное совпадение
- `TestPatternMatchStrategy` - Паттерн-матчинг
- `TestFallbackMatchStrategy` - Fallback стратегия
- `TestChainMatchStrategy` - Цепочки (сценарии)

#### [test_scenario_builder.py](modules/dispatch_module/tests/test_scenario_builder.py)
**Описание:** Тесты для ScenarioBuilder.

**Тесты:**
- `TestScenarioBuilder::test_build_scenario` - Построение сценария
- `TestScenarioBuilder::test_scenario_execution` - Выполнение сценария

---

### ConsoleModule (modules/console_module/tests/)

#### [test_console_manager.py](modules/console_module/tests/test_console_manager.py)
**Описание:** Тесты для ConsoleManager.

**Тесты:**
- `TestConsoleManager::test_initialization` - Инициализация
- `TestConsoleManager::test_enable_disable` - Включение/отключение
- `TestConsoleManager::test_send_message` - Отправка сообщений

#### [test_console_channel.py](modules/console_module/tests/test_console_channel.py)
**Описание:** Тесты для ConsoleChannel.

**Тесты:**
- `TestConsoleChannel::test_create_channel` - Создание канала
- `TestConsoleChannel::test_send_message` - Отправка сообщений

#### [test_console_redirector.py](modules/console_module/tests/test_console_redirector.py)
**Описание:** Тесты для ConsoleRedirector.

**Тесты:**
- `TestConsoleRedirector::test_redirect` - Перенаправление вывода
- `TestConsoleRedirector::test_restore` - Восстановление вывода

#### [test_basic.py](modules/console_module/test_basic.py)
**Описание:** Базовые тесты для ConsoleModule.

**Тесты:**
- `test_imports` - Импорты
- `test_console_manager_init` - Инициализация менеджера
- `test_console_manager_lifecycle` - Жизненный цикл менеджера
- `test_console_manager_enable` - Включение менеджера
- `test_console_manager_send_message` - Отправка сообщений
- `test_console_channel` - Канал консоли
- `test_console_redirector` - Перенаправление консоли
- `test_console_manager_redirect` - Перенаправление менеджера

---

## 📊 Покрытие Кода

### Текущее покрытие

Для проверки покрытия кода используйте:

```bash
# Покрытие всего refactored
pytest src/multiprocess_framework/refactored/ \
    --cov=src/multiprocess_framework/refactored \
    --cov-report=html \
    --cov-report=term-missing

# Открыть HTML отчет
# Windows
start htmlcov/index.html

# Linux/Mac
open htmlcov/index.html
```

### Целевое покрытие

- **Минимум:** 70% для всех модулей
- **Целевое:** 80% для критичных модулей
- **Идеальное:** 90% для базовых модулей (BaseManager, ProcessModule)

---

## 🔗 Интеграционные Тесты

### Текущие интеграционные тесты

1. **test_base_manager_integration.py** - Интеграция BaseManager и BaseAdapter
2. **test_triada_integration.py** - Интеграция Тройцы (ProcessManagerCore, ProcessModule, WorkerManager)

### Планируемые интеграционные тесты

1. **test_process_communication.py** - Коммуникация между процессами
2. **test_router_integration.py** - Интеграция RouterModule с другими модулями
3. **test_shared_resources_integration.py** - Интеграция SharedResourcesModule
4. **test_message_flow.py** - Поток сообщений через всю систему
5. **test_config_integration.py** - Интеграция ConfigModule с ProcessModule
6. **test_data_schema_integration.py** - Интеграция DataSchemaModule

---

## ✍️ Написание Новых Тестов

### Структура теста

```python
"""
Тесты для MyModule.
"""

import pytest
from multiprocess_framework.refactored.modules.my_module import MyManager


class TestMyManager:
    """Тесты для MyManager."""
    
    def test_initialization(self):
        """Тест инициализации."""
        manager = MyManager("test_manager")
        assert manager.manager_name == "test_manager"
        assert manager.is_initialized is False
    
    def test_initialize(self):
        """Тест инициализации менеджера."""
        manager = MyManager("test_manager")
        result = manager.initialize()
        assert result is True
        assert manager.is_initialized is True
    
    def test_shutdown(self):
        """Тест завершения работы."""
        manager = MyManager("test_manager")
        manager.initialize()
        result = manager.shutdown()
        assert result is True
        assert manager.is_initialized is False
```

### Использование фикстур

```python
import pytest

@pytest.fixture
def my_manager():
    """Фикстура для создания менеджера."""
    manager = MyManager("test_manager")
    manager.initialize()
    yield manager
    manager.shutdown()

def test_with_fixture(my_manager):
    """Тест с использованием фикстуры."""
    assert my_manager.is_initialized is True
```

### Маркировка тестов

```python
import pytest

@pytest.mark.unit
def test_unit_test():
    """Юнит-тест."""
    pass

@pytest.mark.integration
def test_integration_test():
    """Интеграционный тест."""
    pass

@pytest.mark.slow
def test_slow_test():
    """Медленный тест."""
    pass

@pytest.mark.fast
def test_fast_test():
    """Быстрый тест."""
    pass
```

---

## 📈 Статистика Тестов

### Общее количество тестов

- **Юнит-тесты:** ~150+
- **Интеграционные тесты:** 2 (планируется больше)
- **Всего:** ~152+

### Покрытие модулей

| Модуль | Тесты | Покрытие |
|--------|--------|-----------|
| BaseManager | 4 файла | Высокое |
| ProcessModule | 1 файл | Среднее |
| WorkerModule | 1 файл | Среднее |
| RouterModule | 2 файла | Среднее |
| MessageModule | 2 файла | Высокое |
| ConfigModule | 3 файла | Среднее |
| DataSchemaModule | 7 файлов | Высокое |
| SharedResourcesModule | 4 файла | Среднее |
| CommandModule | 3 файла | Среднее |
| DispatchModule | 4 файла | Высокое |
| ConsoleModule | 4 файла | Среднее |

---

## 🐛 Отладка Тестов

### Запуск с отладкой

```bash
# С подробным выводом
pytest src/multiprocess_framework/refactored/ -v -s

# С остановкой на первой ошибке
pytest src/multiprocess_framework/refactored/ -x

# С выводом print
pytest src/multiprocess_framework/refactored/ -s

# С pdb отладчиком
pytest src/multiprocess_framework/refactored/ --pdb
```

### Полезные опции pytest

```bash
# Показать локальные переменные при ошибке
pytest --tb=long

# Показать только краткую информацию
pytest --tb=short

# Не показывать traceback
pytest --tb=no

# Показать самые медленные тесты
pytest --durations=10

# Запустить только упавшие тесты
pytest --lf

# Запустить только новые тесты
pytest --ff
```

---

## ✅ Чеклист для Новых Тестов

- [ ] Тест использует pytest (не unittest)
- [ ] Тест имеет описательный docstring
- [ ] Тест изолирован (не зависит от других тестов)
- [ ] Тест использует фикстуры для setup/teardown
- [ ] Тест помечен маркером (@pytest.mark.unit или @pytest.mark.integration)
- [ ] Тест проверяет как успешные, так и ошибочные сценарии
- [ ] Тест использует assert с понятными сообщениями
- [ ] Тест покрывает критичные пути выполнения

---

*Руководство по тестированию v1.0*  
*Inspector Bottle V2 - Multiprocess Framework*

