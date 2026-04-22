# Руководство по Использованию Шаблона как Фреймворка

## 📋 Обзор

Шаблонное приложение (`template_app`) - это полноценный пример использования Multiprocess Framework, который можно использовать как основу для создания собственных многопроцессных приложений.

## 🏗️ Архитектура Шаблона

```
TemplateApplication (Главное приложение)
├── SharedResourcesManager (Архив для всех процессов)
├── ConfigManager (Управление конфигурациями)
├── DataSchemaManager (Работа со схемами данных)
├── ProcessManagerCore (Управление процессами ОС)
└── Процессы (создаются через ProcessManagerCore):
    ├── VisionProcess (Обработка изображений)
    ├── AIProcess (Машинное обучение)
    ├── DBProcess (Работа с БД)
    └── UIProcess (PyQt интерфейс)
```

## 🚀 Быстрый Старт

### 1. Базовое Использование

```python
from multiprocess_framework.tests.integration.template_app import (
    TemplateApplication,
    AppConfigManager,
    AppConfig
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

### 2. Кастомная Конфигурация

```python
# Создаем кастомную конфигурацию
custom_config = AppConfig(
    vision_process_enabled=True,
    ai_process_enabled=False,  # Отключаем AI процесс
    db_process_enabled=True,
    ui_process_enabled=False,
    vision_workers_count=4,  # Больше воркеров
    queue_maxsize=200
)

app = TemplateApplication(config=custom_config)
app.initialize()
app.start()
# ...
app.stop()
```

## 📖 Использование как Шаблон

### Создание Собственного Процесса

1. **Создайте файл процесса** в `template_app/processes/your_process.py`:

```python
from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.worker_module import (
    WorkerManager, ThreadConfig, ThreadPriority
)
from multiprocess_framework.modules.message_module import Message

class YourProcess(ProcessModule):
    """Ваш процесс."""
    
    def __init__(self, name: str, shared_resources=None, config: dict = None):
        super().__init__(name=name, shared_resources=shared_resources, config=config)
        self.workers_count = config.get('workers_count', 1) if config else 1
    
    def initialize(self) -> bool:
        if not super().initialize():
            return False
        
        # Создаем воркеры
        self._create_workers()
        
        # Регистрируем обработчики команд
        self._register_command_handlers()
        
        self.log_info("YourProcess initialized", module=self.name)
        return True
    
    def _create_workers(self):
        """Создание воркеров."""
        def worker_func(stop_event, pause_event, worker_id=0):
            """Функция воркера."""
            self.log_info(f"Worker {worker_id} started", module=self.name)
            
            while not stop_event.is_set():
                if pause_event.is_set():
                    time.sleep(0.1)
                    continue
                
                # Получаем сообщения
                messages = self.receive(timeout=0.1)
                for message in messages:
                    self._process_message(message, worker_id)
                
                time.sleep(0.01)
            
            self.log_info(f"Worker {worker_id} stopped", module=self.name)
        
        for i in range(self.workers_count):
            thread_config = ThreadConfig(
                name=f'worker_{i}',
                priority=ThreadPriority.NORMAL
            )
            self.worker_manager.create_worker(
                name=f'worker_{i}',
                target=worker_func,
                config=thread_config
            )
    
    def _process_message(self, message, worker_id):
        """Обработка сообщения."""
        # Ваша логика обработки
        pass
    
    def _register_command_handlers(self):
        """Регистрация обработчиков команд."""
        def handle_command(command_data):
            return {'status': 'success'}
        
        self.command_manager.register_command('your_command', handle_command)
```

2. **Зарегистрируйте процесс** в `template_application.py`:

```python
# В методе _create_processes()
if self.config.your_process_enabled:
    your_config = {'workers_count': 2}
    class_path = f'{processes_base_path}.your_process.YourProcess'
    result = self.process_manager.create_process(
        name='your_process',
        class_path=class_path,
        config=your_config,
        priority='normal'
    )
    if result:
        self.process_names.append('your_process')
```

### Работа с Конфигурациями

```python
# Получение конфигурации
app_config = app.config_manager.get_config('app')
value = app_config.get('key')

# Обновление конфигурации
app_config.set('key', 'new_value')

# Создание новой конфигурации
app.config_manager.create_config('my_config', {
    'setting1': 'value1',
    'setting2': 42
})
```

### Работа со Схемами Данных

```python
# Регистрация схемы
schema = {
    'type': 'object',
    'properties': {
        'name': {'type': 'string'},
        'age': {'type': 'integer'}
    }
}
app.data_schema_manager.create_schema('person', schema)

# Валидация данных
data = {'name': 'John', 'age': 30}
validated = app.data_schema_manager.validate('person', data)
```

### Межпроцессное Взаимодействие

```python
# Создание сообщения
message = Message.create(
    type='data',
    sender='process1',
    targets=['process2'],
    data={'key': 'value'}
)

# Отправка через SharedResourcesManager
queue = app.shared_resources.queue_registry.get_queue('process2', 'input')
queue.put(message.to_dict())

# Получение сообщений (внутри процесса)
messages = process.receive(timeout=0.1)
for msg in messages:
    # Обработка сообщения
    pass
```

### Добавление PyQt Процесса

1. **Создайте UI процесс** в `template_app/processes/ui_process.py`:

```python
from multiprocess_framework.modules.process_module import ProcessModule
from PyQt6.QtWidgets import QApplication, QMainWindow

class UIProcess(ProcessModule):
    """Процесс с PyQt интерфейсом."""
    
    def __init__(self, name: str, shared_resources=None, config: dict = None):
        super().__init__(name=name, shared_resources=shared_resources, config=config)
        self.app = None
        self.window = None
    
    def initialize(self) -> bool:
        if not super().initialize():
            return False
        
        # Создаем QApplication
        self.app = QApplication([])
        
        # Создаем главное окно
        self.window = QMainWindow()
        self.window.setWindowTitle("Your Application")
        
        self.log_info("UI Process initialized", module=self.name)
        return True
    
    def run_ui(self):
        """Запуск UI."""
        if self.window:
            self.window.show()
            self.app.exec()
    
    def shutdown(self) -> bool:
        if self.app:
            self.app.quit()
        return super().shutdown()
```

2. **Запустите UI процесс**:

```python
if config.ui_process_enabled:
    # UI процесс запускается отдельно
    ui_process = UIProcess(...)
    ui_process.initialize()
    ui_process.run_ui()  # Блокирующий вызов
```

## 🔧 Расширение Шаблона

### Добавление Новых Модулей

1. Создайте модуль в соответствующей папке
2. Используйте `BaseManager` и `ObservableMixin` для единообразия
3. Зарегистрируйте модуль в процессе через `register_manager()`

### Добавление Новых Менеджеров

```python
from multiprocess_framework.modules.base_manager import BaseManager, ObservableMixin

class YourManager(BaseManager, ObservableMixin):
    def __init__(self, manager_name: str):
        BaseManager.__init__(self, manager_name=manager_name)
        ObservableMixin.__init__(self, managers={}, config={}, auto_proxy=True)
    
    def initialize(self) -> bool:
        # Ваша логика инициализации
        return True
```

### Использование Сторонних Модулей

```python
# В вашем процессе
def initialize(self) -> bool:
    if not super().initialize():
        return False
    
    # Создаем сторонний модуль
    your_module = YourModule()
    your_module.initialize()
    
    # Регистрируем в ObservableMixin
    self.register_manager('your_module', your_module)
    
    # Теперь доступен через прокси-методы
    # self.your_module_method()
    
    return True
```

## 📚 Структура Папок

```
template_app/
├── __init__.py
├── template_application.py    # Главное приложение
├── config/
│   ├── __init__.py
│   └── app_config.py         # Конфигурация приложения
└── processes/
    ├── __init__.py
    ├── vision_process.py     # Процесс обработки изображений
    ├── ai_process.py         # Процесс машинного обучения
    ├── db_process.py         # Процесс работы с БД
    └── ui_process.py         # Процесс UI (PyQt)
```

## ⚠️ Важные Замечания

1. **Порядок инициализации:**
   - Сначала создается `SharedResourcesManager`
   - Затем `ConfigManager` и `DataSchemaManager`
   - Потом `ProcessManagerCore`
   - И только потом процессы через `ProcessManagerCore.create_process()`

2. **Очистка ресурсов:**
   - Всегда вызывайте `shutdown()` для всех менеджеров и процессов
   - Используйте `try/finally` для гарантированной очистки

3. **Многопроцессность:**
   - Процессы работают в отдельных процессах ОС
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

## 📖 Дополнительные Ресурсы

- [Архитектура фреймворка](../../docs/ARCHITECTURE_REFERENCE.md)
- [Обзор фреймворка](../../docs/FRAMEWORK_OVERVIEW.md)
- [Документация модулей](../../modules/)

