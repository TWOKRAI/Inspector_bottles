# Руководство по Использованию Шаблонного Приложения

## 📋 Обзор

Шаблонное приложение (`template_app`) - это полноценный пример использования Multiprocess Framework, демонстрирующий все возможности фреймворка в реальном сценарии.

## 🏗️ Архитектура

```
TemplateApplication (Главное приложение)
├── SharedResourcesManager (Архив для всех процессов)
├── ConfigManager (Управление конфигурациями)
├── DataSchemaManager (Работа со схемами данных)
├── ProcessManagerCore (Управление процессами ОС)
└── Процессы:
    ├── VisionProcess (Обработка изображений)
    ├── AIProcess (Машинное обучение)
    ├── DBProcess (Работа с БД)
    └── UIProcess (PyQt интерфейс)
```

## 🚀 Быстрый Старт

### 1. Базовое использование

```python
from multiprocess_framework.tests.integration.template_app import (
    TemplateApplication,
    AppConfigManager
)

# Создаем конфигурацию
config_manager = AppConfigManager()
config = config_manager.load_config()

# Создаем приложение
app = TemplateApplication(config=config)

# Инициализируем
if app.initialize():
    # Запускаем
    app.start()
    
    # Отправляем тестовое сообщение
    app.send_test_message()
    
    # Получаем статистику
    stats = app.get_stats()
    print(stats)
    
    # Останавливаем
    app.stop()
```

### 2. Настройка конфигурации

```python
from multiprocess_framework.tests.integration.template_app import AppConfig

# Создаем кастомную конфигурацию
config = AppConfig(
    vision_process_enabled=True,
    ai_process_enabled=True,
    db_process_enabled=True,
    ui_process_enabled=False,  # Отключаем UI для серверного режима
    vision_workers_count=2,
    ai_workers_count=1,
    db_workers_count=1,
    log_level="DEBUG"
)

app = TemplateApplication(config=config)
```

## 📦 Компоненты

### VisionProcess

Процесс обработки изображений с использованием воркеров.

**Особенности:**
- Использует `WorkerManager` для параллельной обработки
- Получает сообщения через `RouterManager`
- Отправляет результаты в `AIProcess`

**Пример использования:**

```python
vision_process = VisionProcess(
    name='vision_process',
    shared_resources=shared_resources,
    config={'workers_count': 2}
)
vision_process.initialize()
```

### AIProcess

Процесс машинного обучения и анализа.

**Особенности:**
- Получает обработанные изображения от `VisionProcess`
- Выполняет анализ с помощью AI моделей
- Отправляет результаты в `DBProcess`

### DBProcess

Процесс работы с базой данных.

**Особенности:**
- Сохраняет результаты анализа
- Использует `ConfigManager` для хранения статистики
- Предоставляет команды для получения данных

### UIProcess

Процесс пользовательского интерфейса (PyQt).

**Особенности:**
- Опциональный процесс (можно отключить)
- Получает данные от всех процессов
- Отправляет команды другим процессам
- Работает в headless режиме если PyQt не установлен

## 🔄 Межпроцессное Взаимодействие

### Отправка сообщений

```python
from multiprocess_framework.modules.message_module import Message

# Создание сообщения
message = Message.create(
    type='data',
    sender='vision_process',
    targets=['ai_process'],
    data={
        'type': 'processed_image',
        'image_data': image_bytes,
        'image_id': 'img_001'
    }
)

# Отправка через RouterManager
vision_process.router_manager.send_message(message)
```

### Получение сообщений

```python
# В процессе
messages = process.receive(timeout=0.1)
for msg in messages:
    if msg.type == 'data':
        # Обработка данных
        process_data(msg.data)
```

## 🎛️ Управление Воркерами

### Создание воркера

```python
from multiprocess_framework.modules.worker_module import (
    ThreadConfig, ThreadPriority
)

def worker_func(stop_event, pause_event):
    while not stop_event.is_set():
        if pause_event.is_set():
            continue
        # Ваша логика
        process_data()

thread_config = ThreadConfig(
    name='my_worker',
    priority=ThreadPriority.NORMAL
)

process.worker_manager.create_worker(
    name='my_worker',
    target=worker_func,
    config=thread_config
)
```

### Управление воркерами

```python
# Запуск всех воркеров
process.worker_manager.start_all_workers()

# Остановка воркера
process.worker_manager.stop_worker('my_worker')

# Получение статуса
status = process.worker_manager.get_worker_status('my_worker')
```

## ⚙️ Работа с Конфигурациями

### Использование ConfigManager

```python
# Создание конфигурации
config_manager.create_config('my_config', {
    'setting1': 'value1',
    'setting2': 42
})

# Получение конфигурации
my_config = config_manager.get_config('my_config')
value = my_config.get('setting1')

# Изменение значения
my_config.set('setting1', 'new_value')
```

### Использование DataSchemaManager

```python
# Создание схемы
schema_data = {
    'name': 'MySchema',
    'fields': {
        'field1': {'type': 'str', 'required': True},
        'field2': {'type': 'int', 'default': 0}
    }
}

data_schema_manager.create_schema('MySchema', schema_data)

# Валидация данных
validated_data = data_schema_manager.validate('MySchema', {'field1': 'test'})
```

## 🧪 Тестирование

### Запуск интеграционных тестов

```bash
# Все тесты
pytest src/multiprocess_framework/tests/integration/ -v

# Конкретный тест
pytest src/multiprocess_framework/tests/integration/test_template_application.py::TestTemplateApplication::test_app_initialization -v
```

### Написание своих тестов

```python
import pytest
from multiprocess_framework.tests.integration.template_app import (
    TemplateApplication,
    AppConfig
)

def test_my_feature():
    config = AppConfig(
        vision_process_enabled=True,
        ai_process_enabled=False,
        db_process_enabled=False
    )
    
    app = TemplateApplication(config=config)
    app.initialize()
    
    try:
        # Ваши тесты
        assert app.vision_process is not None
        assert app.vision_process.is_initialized is True
    finally:
        app.stop()
```

## 🔧 Расширение Шаблона

### Добавление нового процесса

1. Создайте файл `my_process.py` в `template_app/processes/`
2. Наследуйтесь от `ProcessModule`
3. Реализуйте методы `initialize()` и `shutdown()`
4. Добавьте логику воркеров и обработчиков команд
5. Зарегистрируйте процесс в `TemplateApplication._create_processes()`

### Добавление новых модулей

1. Создайте модуль используя `BaseManager` и `ObservableMixin`
2. Зарегистрируйте модуль в процессе через `register_manager()`
3. Используйте модуль через `ObservableMixin` прокси-методы

## 📚 Дополнительные Ресурсы

- [Архитектура фреймворка](../../docs/ARCHITECTURE_REFERENCE.md)
- [Документация модулей](../../modules/)
- [Руководство по интеграционным тестам](../INTEGRATION_TESTS_GUIDE.md)

## ⚠️ Важные Замечания

1. **Порядок инициализации важен:**
   - Сначала `SharedResourcesManager`
   - Затем менеджеры (`ConfigManager`, `DataSchemaManager`)
   - Потом `ProcessManagerCore`
   - И только потом процессы

2. **Всегда очищайте ресурсы:**
   ```python
   try:
       app.start()
       # Ваш код
   finally:
       app.stop()  # Всегда вызывайте stop()
   ```

3. **Многопроцессность:**
   - Процессы работают в отдельных процессах ОС
   - Используйте очереди для передачи данных
   - Не передавайте несериализуемые объекты

4. **PyQt интеграция:**
   - Установите PyQt6: `pip install PyQt6`
   - UI процесс работает в headless режиме если PyQt не установлен
   - Используйте `QTimer` для периодической обработки сообщений

