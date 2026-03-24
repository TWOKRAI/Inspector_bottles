# Структура Интеграционных Тестов

## 📋 Обзор

Интеграционные тесты организованы по функциональным областям и уровням тестирования.
Каждый файл тестов фокусируется на определенном аспекте фреймворка.

## 🗂️ Организация Тестов

### По Уровню Тестирования

```
integration/
├── test_template_application.py              # Базовый уровень - простые тесты шаблона
├── test_template_application_comprehensive.py  # Расширенный уровень - комплексные тесты
├── test_comprehensive_integration.py       # Полный уровень - все модули вместе
└── test_module_interactions.py             # Уровень взаимодействия - пары модулей
```

### По Функциональным Областям

```
integration/
├── test_comprehensive_integration.py       # Все функциональные области
│   ├── TestApplicationLifecycle          # Жизненный цикл
│   ├── TestFrameworkModules               # Все модули
│   ├── TestInterProcessCommunication      # Коммуникация
│   ├── TestCommandHandling                # Команды
│   ├── TestConfigurationAndData           # Конфигурации и данные
│   ├── TestStatisticsAndMonitoring        # Статистика
│   └── TestExtensibility                  # Расширяемость
│
├── test_module_interactions.py            # Взаимодействие модулей
│   ├── TestBaseManagerProcessModuleInteraction
│   ├── TestProcessModuleWorkerManagerInteraction
│   ├── TestRouterModuleMessageModuleInteraction
│   ├── TestConfigModuleDataSchemaModuleInteraction
│   ├── TestSharedResourcesModuleIntegration
│   └── TestCommandModuleDispatchModuleInteraction
│
├── test_performance.py                    # Производительность
│   ├── TestInterProcessCommunicationPerformance
│   ├── TestMemoryPerformance
│   ├── TestConfigurationPerformance
│   └── TestWorkerPerformance
│
├── test_usage_scenarios.py                # Сценарии использования
│   ├── TestCreateProcessWithWorkers
│   ├── TestInterProcessCommunication
│   ├── TestConfigurationManagement
│   ├── TestErrorHandlingAndRecovery
│   └── TestGracefulShutdown
│
└── test_template_application*.py          # Тесты шаблона
    ├── TestTemplateApplication
    ├── TestProcessIntegration
    └── TestTemplateApplicationComprehensive
```

## 📊 Матрица Покрытия

| Функциональная область | test_comprehensive | test_module_interactions | test_performance | test_usage_scenarios | test_template |
|------------------------|-------------------|-------------------------|------------------|---------------------|---------------|
| Жизненный цикл         | ✅                |                         |                  |                     | ✅            |
| Все модули             | ✅                | ✅                      |                  |                     | ✅            |
| Коммуникация           | ✅                | ✅                      | ✅               | ✅                  | ✅            |
| Команды                | ✅                | ✅                      |                  |                     |               |
| Конфигурации           | ✅                | ✅                      | ✅               | ✅                  | ✅            |
| Производительность     |                   |                         | ✅               |                     |               |
| Сценарии использования |                   |                         |                  | ✅                  |               |
| Расширяемость          | ✅                |                         |                  |                     |               |

## 🎯 Назначение Каждого Файла

### test_comprehensive_integration.py

**Уровень:** Полный интеграционный тест

**Назначение:**
- Проверка всех модулей фреймворка вместе
- Проверка полного жизненного цикла приложения
- Проверка всех типов взаимодействия

**Когда использовать:**
- Для проверки полной функциональности после изменений
- Для демонстрации использования всех модулей
- Для регрессионного тестирования

**Классы тестов:**
1. `TestApplicationLifecycle` - инициализация, запуск, остановка
2. `TestFrameworkModules` - все модули (Worker, Router, Command, Config, DataSchema)
3. `TestInterProcessCommunication` - коммуникация между процессами
4. `TestCommandHandling` - обработка команд
5. `TestConfigurationAndData` - конфигурации и схемы данных
6. `TestStatisticsAndMonitoring` - статистика и мониторинг
7. `TestExtensibility` - расширяемость фреймворка

### test_module_interactions.py

**Уровень:** Тест взаимодействия модулей

**Назначение:**
- Проверка корректности взаимодействия между парами модулей
- Проверка интеграции модулей на низком уровне

**Когда использовать:**
- При изменении взаимодействия между модулями
- Для проверки корректности интеграции новых модулей
- Для отладки проблем взаимодействия

**Классы тестов:**
1. `TestBaseManagerProcessModuleInteraction` - базовый менеджер и процесс
2. `TestProcessModuleWorkerManagerInteraction` - процесс и воркеры
3. `TestRouterModuleMessageModuleInteraction` - маршрутизация и сообщения
4. `TestConfigModuleDataSchemaModuleInteraction` - конфигурации и схемы
5. `TestSharedResourcesModuleIntegration` - общие ресурсы
6. `TestCommandModuleDispatchModuleInteraction` - команды и диспетчеризация

### test_performance.py

**Уровень:** Тест производительности

**Назначение:**
- Проверка производительности различных компонентов
- Выявление узких мест в производительности
- Бенчмарки для оптимизации

**Когда использовать:**
- После изменений, влияющих на производительность
- Для проверки производительности перед релизом
- Для оптимизации узких мест

**Классы тестов:**
1. `TestInterProcessCommunicationPerformance` - производительность коммуникации
2. `TestMemoryPerformance` - производительность памяти
3. `TestConfigurationPerformance` - производительность конфигураций
4. `TestWorkerPerformance` - производительность воркеров

### test_usage_scenarios.py

**Уровень:** Тест сценариев использования

**Назначение:**
- Проверка типичных сценариев использования фреймворка
- Демонстрация best practices
- Проверка надежности системы

**Когда использовать:**
- Для проверки типичных сценариев использования
- Для демонстрации использования фреймворка
- Для проверки надежности

**Классы тестов:**
1. `TestCreateProcessWithWorkers` - создание процесса с воркерами
2. `TestInterProcessCommunication` - межпроцессная коммуникация
3. `TestConfigurationManagement` - управление конфигурациями
4. `TestErrorHandlingAndRecovery` - обработка ошибок
5. `TestGracefulShutdown` - корректное завершение

### test_template_application.py

**Уровень:** Базовый тест шаблона

**Назначение:**
- Быстрая проверка работоспособности шаблонного приложения
- Базовые тесты основных функций

**Когда использовать:**
- Для быстрой проверки после изменений
- Для начального знакомства с шаблоном
- Для проверки базовой функциональности

**Классы тестов:**
1. `TestTemplateApplication` - базовые тесты шаблона
2. `TestProcessIntegration` - интеграция процессов

### test_template_application_comprehensive.py

**Уровень:** Расширенный тест шаблона

**Назначение:**
- Полное тестирование шаблонного приложения
- Использование фикстур pytest
- 15 комплексных тестов

**Когда использовать:**
- Для полного тестирования шаблона
- Для проверки всех аспектов шаблона
- Для демонстрации использования фикстур

**Классы тестов:**
1. `TestTemplateApplicationComprehensive` - 15 комплексных тестов
2. `TestTemplateApplicationAsFramework` - использование как фреймворка

## 🔄 Зависимости Между Тестами

```
test_template_application.py (базовый)
    ↓
test_template_application_comprehensive.py (расширенный)
    ↓
test_module_interactions.py (взаимодействие)
    ↓
test_comprehensive_integration.py (полный)
    ↓
test_performance.py (производительность)
    ↓
test_usage_scenarios.py (сценарии)
```

## 📝 Рекомендации по Использованию

### Для Разработчиков

1. **Начните с базовых тестов:**
   ```bash
   pytest test_template_application.py -v
   ```

2. **Затем запустите расширенные:**
   ```bash
   pytest test_template_application_comprehensive.py -v
   ```

3. **Проверьте взаимодействие модулей:**
   ```bash
   pytest test_module_interactions.py -v
   ```

4. **Запустите полные интеграционные тесты:**
   ```bash
   pytest test_comprehensive_integration.py -v
   ```

5. **Проверьте производительность:**
   ```bash
   pytest test_performance.py -v -s
   ```

6. **Проверьте сценарии использования:**
   ```bash
   pytest test_usage_scenarios.py -v
   ```

### Для CI/CD

Рекомендуемый порядок запуска в CI/CD:

```bash
# 1. Быстрые базовые тесты
pytest test_template_application.py -v

# 2. Тесты взаимодействия (быстрые)
pytest test_module_interactions.py -v

# 3. Полные интеграционные тесты
pytest test_comprehensive_integration.py -v

# 4. Сценарии использования
pytest test_usage_scenarios.py -v

# 5. Расширенные тесты шаблона
pytest test_template_application_comprehensive.py -v

# 6. Производительность (опционально, может быть медленным)
pytest test_performance.py -v -s
```

## 🎓 Лучшие Практики

1. **Запускайте тесты в правильном порядке** - от простых к сложным
2. **Используйте фикстуры** - для переиспользования кода
3. **Изолируйте тесты** - каждый тест должен быть независимым
4. **Документируйте тесты** - описывайте что проверяет каждый тест
5. **Используйте try/finally** - для гарантированной очистки ресурсов

## 📚 Связанные Документы

- [INDEX.md](INDEX.md) - навигация по всем файлам
- [README.md](README.md) - основная документация
- [INTEGRATION_TESTS_GUIDE.md](INTEGRATION_TESTS_GUIDE.md) - подробное руководство

