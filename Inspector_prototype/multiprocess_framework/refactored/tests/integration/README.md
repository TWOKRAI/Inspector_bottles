# Интеграционные Тесты и Шаблонное Приложение

Этот раздел содержит интеграционные тесты и шаблонное приложение для демонстрации использования Multiprocess Framework.

## 📋 Содержание

- [Быстрый старт](#-быстрый-старт)
- [Структура](#-структура)
- [Назначение](#-назначение)
- [Использование](#-использование)
- [Документация](#-документация)
- [Примеры](#-примеры)

> 💡 **Совет:** Начните с [INDEX.md](INDEX.md) для навигации по всем файлам и их назначению.

## 📁 Структура

```
integration/
├── INDEX.md                          # Навигация по всем файлам и их назначению
├── README.md                          # Эта документация
├── QUICK_START.md                     # Быстрый старт за 5 минут
├── INTEGRATION_TESTS_GUIDE.md         # Подробное руководство по тестам
│
├── test_comprehensive_integration.py  # Комплексные тесты всех модулей
├── test_module_interactions.py        # Тесты взаимодействия модулей
├── test_performance.py                # Тесты производительности
├── test_template_application.py       # Базовые тесты шаблонного приложения
├── test_template_application_comprehensive.py  # Расширенные тесты шаблона
├── test_usage_scenarios.py           # Тесты сценариев использования
│
├── template_app/                      # Шаблонное приложение
│   ├── template_application.py        # Главный класс приложения
│   ├── TEMPLATE_GUIDE.md              # Руководство по шаблону
│   ├── config/                        # Конфигурация приложения
│   │   └── app_config.py              # Менеджер конфигурации
│   └── processes/                     # Процессы приложения
│       ├── vision_process.py          # Процесс обработки изображений
│       ├── ai_process.py              # Процесс машинного обучения
│       ├── db_process.py               # Процесс работы с БД
│       └── ui_process.py              # Процесс UI (PyQt)
│
└── TEMPLATE_FRAMEWORK_GUIDE.md        # Руководство по использованию фреймворка
    TEMPLATE_USAGE.md                  # Детальное руководство по шаблону
```

> 📖 **Подробнее:** См. [INDEX.md](INDEX.md) для детального описания каждого файла.

## 🎯 Назначение

### Интеграционные Тесты

Интеграционные тесты проверяют:

1. **Взаимодействие всех модулей фреймворка** - корректная работа всех компонентов вместе
2. **Межпроцессную коммуникацию** - передача данных между процессами
3. **Жизненный цикл приложения** - инициализация, запуск, остановка
4. **Производительность** - скорость работы компонентов
5. **Обработку ошибок** - корректное восстановление после сбоев

### Шаблонное Приложение

Шаблонное приложение демонстрирует:

1. **Использование всех модулей фреймворка:**
   - `ProcessManagerCore` - управление процессами ОС
   - `ProcessModule` - базовый класс процессов
   - `WorkerManager` - управление потоками
   - `ConfigManager` - работа с конфигурациями
   - `DataSchemaManager` - работа со схемами данных
   - `RouterManager` - маршрутизация сообщений
   - `CommandManager` - обработка команд
   - `LoggerManager` - логирование
   - `SharedResourcesManager` - общие ресурсы

2. **Межпроцессное взаимодействие:**
   - Отправка сообщений между процессами
   - Использование очередей и каналов
   - Работа с SharedResourcesManager

3. **Управление жизненным циклом:**
   - Инициализация процессов
   - Запуск и остановка процессов
   - Управление воркерами

## 🚀 Быстрый Старт

### Запуск шаблонного приложения

```python
from multiprocess_framework.refactored.tests.integration.template_app import (
    TemplateApplication,
    AppConfigManager
)

# Создаем конфигурацию
config_manager = AppConfigManager()
config = config_manager.load_config()

# Создаем и запускаем приложение
app = TemplateApplication(config=config)
app.initialize()
app.start()

# Отправляем тестовое сообщение
app.send_test_message()

# Получаем статистику
stats = app.get_stats()
print(stats)

# Останавливаем приложение
app.stop()
```

### Запуск интеграционных тестов

```bash
# Все интеграционные тесты
pytest src/multiprocess_framework/refactored/tests/integration/ -v

# Конкретный тест
pytest src/multiprocess_framework/refactored/tests/integration/test_template_application.py::TestTemplateApplication::test_app_initialization -v
```

## 📖 Использование как Шаблон

### 1. Создание нового процесса

```python
from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.worker_module import (
    WorkerManager, ThreadConfig, ThreadPriority
)

class MyProcess(ProcessModule):
    def __init__(self, name: str, shared_resources=None, config: dict = None):
        super().__init__(name=name, shared_resources=shared_resources, config=config)
    
    def initialize(self) -> bool:
        if not super().initialize():
            return False
        
        # Создаем воркеры
        self._create_workers()
        
        # Регистрируем обработчики команд
        self._register_command_handlers()
        
        return True
    
    def _create_workers(self):
        def worker_func(stop_event, pause_event):
            while not stop_event.is_set():
                # Ваша логика здесь
                pass
        
        thread_config = ThreadConfig(
            name='my_worker',
            priority=ThreadPriority.NORMAL
        )
        
        self.worker_manager.create_worker(
            name='my_worker',
            target=worker_func,
            config=thread_config
        )
    
    def _register_command_handlers(self):
        def handle_my_command(command_data):
            return {'status': 'success'}
        
        self.command_manager.register_command(
            'my_command',
            handle_my_command
        )
```

### 2. Работа с конфигурациями

```python
from multiprocess_framework.refactored.modules.config_module import ConfigManager

# Создание менеджера конфигураций
config_manager = ConfigManager(manager_name="config_manager")
config_manager.initialize()

# Создание конфигурации
config_manager.create_config('my_config', {
    'setting1': 'value1',
    'setting2': 42
})

# Получение конфигурации
my_config = config_manager.get_config('my_config')
value = my_config.get('setting1')
```

### 3. Межпроцессное взаимодействие

```python
from multiprocess_framework.refactored.modules.message_module import Message

# Создание сообщения
message = Message.create(
    type='data',
    sender='process1',
    targets=['process2'],
    data={'key': 'value'}
)

# Отправка через RouterManager
process1.router_manager.send_message(message)

# Получение сообщений
messages = process1.receive(timeout=0.1)
for msg in messages:
    # Обработка сообщения
    pass
```

### 4. Добавление PyQt процесса

```python
from multiprocess_framework.refactored.tests.integration.template_app.processes.ui_process import UIProcess

# В главном приложении
if config.ui_process_enabled:
    ui_process = UIProcess(
        name='ui_process',
        shared_resources=self.shared_resources,
        config={'ui_enabled': True}
    )
    ui_process.initialize()
    ui_process.start()
    
    # Запуск UI
    ui_process.run_ui()
```

## 🔧 Расширение Шаблона

### Добавление нового процесса

1. Создайте файл в `template_app/processes/your_process.py`
2. Наследуйтесь от `ProcessModule`
3. Реализуйте методы `initialize()` и `shutdown()`
4. Добавьте логику воркеров и обработчиков команд
5. Зарегистрируйте процесс в главном приложении

### Добавление новых модулей

1. Создайте модуль в соответствующей папке
2. Используйте `BaseManager` и `ObservableMixin` для единообразия
3. Зарегистрируйте модуль в процессе через `register_manager()`

## 📚 Дополнительные Ресурсы

- [Архитектура фреймворка](../../docs/ARCHITECTURE.md)
- [Руководство по использованию шаблона](./TEMPLATE_FRAMEWORK_GUIDE.md)
- [Руководство по использованию шаблона (детальное)](./TEMPLATE_USAGE.md)
- [Руководство по тестированию](../../docs/TESTING_GUIDE.md)
- [Документация модулей](../../modules/)

## 🧪 Запуск Тестов

```bash
# Все интеграционные тесты
pytest src/multiprocess_framework/refactored/tests/integration/ -v

# Только шаблонное приложение
pytest src/multiprocess_framework/refactored/tests/integration/test_template_application*.py -v

# Конкретный тест
pytest src/multiprocess_framework/refactored/tests/integration/test_template_application_comprehensive.py::TestTemplateApplicationComprehensive::test_01_initialization -v
```

## ⚠️ Важные Замечания

1. **Порядок инициализации:**
   - Сначала создается `SharedResourcesManager`
   - Затем `ConfigManager` и другие менеджеры
   - Потом `ProcessManagerCore`
   - И только потом процессы

2. **Очистка ресурсов:**
   - Всегда вызывайте `shutdown()` для всех менеджеров и процессов
   - Используйте `try/finally` для гарантированной очистки

3. **Многопроцессность:**
   - Помните что процессы работают в отдельных процессах ОС
   - Используйте очереди для передачи данных между процессами
   - Не передавайте несериализуемые объекты

4. **Тестирование:**
   - Используйте интеграционные тесты для проверки взаимодействия
   - Мокируйте внешние зависимости (БД, файлы и т.д.)
   - Тестируйте каждый процесс отдельно и вместе

## 🎓 Примеры Использования

Смотрите файлы в `template_app/` для примеров:
- `vision_process.py` - обработка данных с воркерами
- `ai_process.py` - работа с моделями ML
- `db_process.py` - работа с базой данных
- `ui_process.py` - интеграция с PyQt

