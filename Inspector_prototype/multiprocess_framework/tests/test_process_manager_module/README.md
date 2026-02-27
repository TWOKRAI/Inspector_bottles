# Тесты для Process_manager_module

## Структура тестов

Тесты разделены по компонентам для лучшей организации:

### 1. `test_process_config.py`
Тесты для `ProcessConfig` - управление конфигурацией процессов:
- Добавление и получение конфигураций
- Валидация конфигураций
- Загрузка из словаря
- Обновление и удаление конфигураций

### 2. `test_process_priority.py`
Тесты для `ProcessPriority` - управление приоритетами:
- Регистрация приоритетов
- Валидация приоритетов
- Маппинг приоритетов

### 3. `test_process_status.py`
Тесты для `ProcessStatus` - мониторинг статуса:
- Получение статуса процессов
- Подсчет живых/завершенных процессов
- Статистика процессов

### 4. `test_process_lifecycle.py`
Тесты для `ProcessLifecycle` - управление жизненным циклом:
- Добавление процессов
- Запуск процессов
- Остановка процессов
- Получение списков процессов

### 5. `test_queue_registry.py`
Тесты для `QueueRegistry` - реестр очередей:
- Регистрация очередей
- Отправка сообщений
- Broadcast сообщений
- Получение статистики

### 6. `test_process_interaction_manager.py`
Тесты для `ProcessInteractionManager`:
- Инициализация
- Доступ к queue_registry и memory_manager
- Конфигурация
- Регистрация очередей

### 7. `test_process_manager.py`
Тесты для `ProcessManager` - главный класс:
- Инициализация с композицией
- Создание процессов
- Инициализация процессов
- Получение статуса и статистики

### 8. `test_main_launcher.py`
Тесты для `SystemLauncher`:
- Инициализация
- Получение статуса и статистики

## Запуск тестов

### Через unittest:
```bash
python3 -m unittest tests.Test_Process_manager_module.test_process_config -v
python3 -m unittest tests.Test_Process_manager_module.test_process_priority -v
python3 -m unittest tests.Test_Process_manager_module.test_process_status -v
python3 -m unittest tests.Test_Process_manager_module.test_process_lifecycle -v
python3 -m unittest tests.Test_Process_manager_module.test_queue_registry -v
python3 -m unittest tests.Test_Process_manager_module.test_process_interaction_manager -v
python3 -m unittest tests.Test_Process_manager_module.test_process_manager -v
python3 -m unittest tests.Test_Process_manager_module.test_main_launcher -v
```

### Через pytest (если установлен):
```bash
pytest tests/Test_Process_manager_module/ -v
```

## Покрытие тестами

### ProcessConfig
- ✅ Добавление конфигураций
- ✅ Получение конфигураций
- ✅ Валидация конфигураций
- ✅ Загрузка из словаря
- ✅ Обновление и удаление

### ProcessPriority
- ✅ Регистрация приоритетов
- ✅ Получение приоритетов
- ✅ Валидация приоритетов
- ✅ Маппинг приоритетов

### ProcessStatus
- ✅ Получение статуса
- ✅ Подсчет процессов
- ✅ Статистика
- ✅ Проверка состояния

### ProcessLifecycle
- ✅ Добавление процессов
- ✅ Запуск процессов
- ✅ Остановка процессов
- ✅ Получение списков

### QueueRegistry
- ✅ Регистрация очередей
- ✅ Отправка сообщений
- ✅ Broadcast
- ✅ Получение статистики
- ✅ Очистка очередей

### ProcessInteractionManager
- ✅ Инициализация
- ✅ Доступ к реестрам
- ✅ Конфигурация
- ✅ Регистрация очередей

### ProcessManager
- ✅ Инициализация
- ✅ Создание процессов
- ✅ Инициализация процессов
- ✅ Получение статуса

### SystemLauncher
- ✅ Инициализация
- ✅ Получение статуса

## Примечания

- Некоторые тесты могут требовать установки зависимостей
- Тесты жизненного цикла работают с реальными процессами ОС
- Тесты приоритетов могут не работать на всех платформах (требуются права администратора)

