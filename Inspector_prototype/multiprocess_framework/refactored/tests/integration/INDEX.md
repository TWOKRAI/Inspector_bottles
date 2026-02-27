# Индекс Интеграционных Тестов

## 📁 Структура Папки

```
integration/
├── INDEX.md                          # Этот файл - навигация по всем тестам
├── README.md                          # Основная документация
├── QUICK_START.md                     # Быстрый старт
├── INTEGRATION_TESTS_GUIDE.md         # Подробное руководство по тестам
├── TEST_ISSUES.md                     # Известные проблемы и их решения
├── TESTS_STRUCTURE.md                 # Структура тестов
├── IMPROVEMENTS.md                    # Описание улучшений
├── run_integration_tests.py           # Скрипт для запуска всех тестов
│
├── __init__.py                        # Экспорт основных классов
│
├── test_comprehensive_integration.py  # Комплексные тесты всех модулей
├── test_module_interactions.py        # Тесты взаимодействия модулей
├── test_performance.py                # Тесты производительности
├── test_template_application.py       # Базовые тесты шаблонного приложения
├── test_template_application_comprehensive.py  # Расширенные тесты шаблона
├── test_usage_scenarios.py           # Тесты сценариев использования
│
├── template_app/                      # Шаблонное приложение
│   ├── __init__.py
│   ├── template_application.py        # Главный класс приложения
│   ├── TEMPLATE_GUIDE.md              # Руководство по шаблону
│   │
│   ├── config/                       # Конфигурация приложения
│   │   ├── __init__.py
│   │   └── app_config.py              # Менеджер конфигурации
│   │
│   └── processes/                     # Процессы приложения
│       ├── __init__.py
│       ├── vision_process.py          # Процесс обработки изображений
│       ├── ai_process.py              # Процесс машинного обучения
│       ├── db_process.py               # Процесс работы с БД
│       └── ui_process.py               # Процесс UI (PyQt)
│
└── TEMPLATE_FRAMEWORK_GUIDE.md        # Руководство по использованию фреймворка
    TEMPLATE_USAGE.md                  # Детальное руководство по шаблону
```

## 🎯 Назначение Файлов

### Тестовые Файлы

#### `test_comprehensive_integration.py`
**Назначение:** Комплексные интеграционные тесты, демонстрирующие использование всех модулей фреймворка.

**Содержит классы:**
- `TestApplicationLifecycle` - тесты жизненного цикла приложения
- `TestFrameworkModules` - тесты использования всех модулей
- `TestInterProcessCommunication` - тесты межпроцессного взаимодействия
- `TestCommandHandling` - тесты обработки команд
- `TestConfigurationAndData` - тесты работы с конфигурациями и данными
- `TestStatisticsAndMonitoring` - тесты статистики и мониторинга
- `TestExtensibility` - тесты расширяемости фреймворка

**Когда использовать:** Для проверки полной функциональности фреймворка и всех его модулей.

#### `test_module_interactions.py`
**Назначение:** Тесты взаимодействия между отдельными модулями фреймворка.

**Содержит классы:**
- `TestBaseManagerProcessModuleInteraction` - взаимодействие BaseManager и ProcessModule
- `TestProcessModuleWorkerManagerInteraction` - взаимодействие ProcessModule и WorkerManager
- `TestRouterModuleMessageModuleInteraction` - взаимодействие RouterModule и MessageModule
- `TestConfigModuleDataSchemaModuleInteraction` - взаимодействие ConfigModule и DataSchemaModule
- `TestSharedResourcesModuleIntegration` - интеграция SharedResourcesModule
- `TestCommandModuleDispatchModuleInteraction` - взаимодействие CommandModule и DispatchModule

**Когда использовать:** Для проверки корректности взаимодействия между модулями.

#### `test_performance.py`
**Назначение:** Тесты производительности различных компонентов фреймворка.

**Содержит классы:**
- `TestInterProcessCommunicationPerformance` - производительность межпроцессной коммуникации
- `TestMemoryPerformance` - производительность работы с памятью
- `TestConfigurationPerformance` - производительность работы с конфигурациями
- `TestWorkerPerformance` - производительность воркеров

**Когда использовать:** Для проверки производительности и выявления узких мест.

#### `test_template_application.py`
**Назначение:** Базовые тесты шаблонного приложения.

**Содержит классы:**
- `TestTemplateApplication` - базовые тесты шаблона
- `TestProcessIntegration` - тесты интеграции процессов

**Когда использовать:** Для быстрой проверки работоспособности шаблонного приложения.

#### `test_template_application_comprehensive.py`
**Назначение:** Расширенные тесты шаблонного приложения с использованием фикстур pytest.

**Содержит классы:**
- `TestTemplateApplicationComprehensive` - комплексные тесты (15 тестов)
- `TestTemplateApplicationAsFramework` - тесты использования как фреймворка

**Когда использовать:** Для глубокого тестирования шаблонного приложения.

#### `test_usage_scenarios.py`
**Назначение:** Тесты типичных сценариев использования фреймворка.

**Содержит классы:**
- `TestCreateProcessWithWorkers` - создание процесса с воркерами
- `TestInterProcessCommunication` - межпроцессное взаимодействие
- `TestConfigurationManagement` - управление конфигурациями
- `TestErrorHandlingAndRecovery` - обработка ошибок и восстановление
- `TestGracefulShutdown` - корректное завершение работы

**Когда использовать:** Для проверки типичных сценариев использования.

### Шаблонное Приложение (`template_app/`)

#### `template_application.py`
**Назначение:** Главный класс шаблонного приложения, демонстрирующий использование всех модулей фреймворка.

**Основные методы:**
- `initialize()` - инициализация всех менеджеров и процессов
- `start()` - запуск приложения
- `stop()` - остановка приложения
- `send_test_message()` - отправка тестового сообщения
- `get_stats()` - получение статистики

**Когда использовать:** Как шаблон для создания собственных приложений.

#### `config/app_config.py`
**Назначение:** Менеджер конфигурации приложения.

**Содержит:**
- `AppConfig` - класс конфигурации приложения
- `AppConfigManager` - менеджер для загрузки/сохранения конфигурации

**Когда использовать:** Для управления конфигурацией приложения.

#### `processes/`
**Назначение:** Примеры процессов, демонстрирующие использование фреймворка.

**Процессы:**
- `vision_process.py` - процесс обработки изображений
- `ai_process.py` - процесс машинного обучения
- `db_process.py` - процесс работы с БД
- `ui_process.py` - процесс UI (PyQt)

**Когда использовать:** Как примеры для создания собственных процессов.

## 📚 Документация

### `README.md`
Основная документация по интеграционным тестам и шаблонному приложению.

### `QUICK_START.md`
Быстрый старт - как начать использовать за 5 минут.

### `INTEGRATION_TESTS_GUIDE.md`
Подробное руководство по интеграционным тестам с примерами.

### `TEMPLATE_FRAMEWORK_GUIDE.md`
Руководство по использованию шаблонного приложения как фреймворка.

### `TEMPLATE_USAGE.md`
Детальное руководство по использованию шаблона.

### `template_app/TEMPLATE_GUIDE.md`
Руководство по шаблонному приложению.

## 🚀 Быстрый Навигация

### Хочу запустить тесты
→ См. [QUICK_START.md](QUICK_START.md)

### Хочу понять структуру тестов
→ См. [INTEGRATION_TESTS_GUIDE.md](INTEGRATION_TESTS_GUIDE.md)

### Хочу использовать шаблонное приложение
→ См. [TEMPLATE_FRAMEWORK_GUIDE.md](TEMPLATE_FRAMEWORK_GUIDE.md)

### Хочу создать свой процесс
→ См. `template_app/processes/` и [TEMPLATE_USAGE.md](TEMPLATE_USAGE.md)

### Хочу понять архитектуру
→ См. [README.md](README.md) и документацию в `../../docs/`

## 🔍 Поиск по Назначению

### Тестирование жизненного цикла
→ `test_comprehensive_integration.py::TestApplicationLifecycle`

### Тестирование модулей
→ `test_comprehensive_integration.py::TestFrameworkModules`
→ `test_module_interactions.py`

### Тестирование коммуникации
→ `test_comprehensive_integration.py::TestInterProcessCommunication`
→ `test_usage_scenarios.py::TestInterProcessCommunication`

### Тестирование производительности
→ `test_performance.py`

### Тестирование шаблонного приложения
→ `test_template_application.py`
→ `test_template_application_comprehensive.py`

### Примеры использования
→ `template_app/` - все файлы
→ `test_usage_scenarios.py`

## 📖 Рекомендуемый Порядок Изучения

1. **Начните с быстрого старта:**
   - Прочитайте [QUICK_START.md](QUICK_START.md)
   - Запустите тесты

2. **Изучите шаблонное приложение:**
   - Прочитайте [README.md](README.md)
   - Изучите `template_app/template_application.py`
   - Посмотрите примеры процессов в `template_app/processes/`

3. **Изучите тесты:**
   - Прочитайте [INTEGRATION_TESTS_GUIDE.md](INTEGRATION_TESTS_GUIDE.md)
   - Изучите `test_template_application.py` (самый простой)
   - Изучите `test_comprehensive_integration.py` (самый полный)

4. **Создайте свое приложение:**
   - Используйте `template_app/` как шаблон
   - Следуйте [TEMPLATE_USAGE.md](TEMPLATE_USAGE.md)

## 🎓 Лучшие Практики

1. **Всегда используйте try/finally** для очистки ресурсов
2. **Используйте фикстуры pytest** для переиспользования кода
3. **Документируйте тесты** - описывайте что проверяет каждый тест
4. **Изолируйте тесты** - каждый тест должен быть независимым
5. **Используйте time.sleep()** для синхронизации процессов

## 🔗 Связанные Документы

- [README.md](README.md) - основная документация
- [QUICK_START.md](QUICK_START.md) - быстрый старт
- [INTEGRATION_TESTS_GUIDE.md](INTEGRATION_TESTS_GUIDE.md) - подробное руководство
- [TESTS_STRUCTURE.md](TESTS_STRUCTURE.md) - структура тестов
- [TEST_ISSUES.md](TEST_ISSUES.md) - известные проблемы и их решения ⚠️
- [IMPROVEMENTS.md](IMPROVEMENTS.md) - описание улучшений
- [run_integration_tests.py](run_integration_tests.py) - скрипт для запуска тестов
- [Архитектура фреймворка](../../docs/ARCHITECTURE.md)
- [Руководство по тестированию](../../docs/TESTING_GUIDE.md)
- [Документация модулей](../../modules/)

