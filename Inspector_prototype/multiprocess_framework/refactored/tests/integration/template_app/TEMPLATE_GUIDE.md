# Руководство по использованию шаблонного приложения

Это руководство описывает как использовать шаблонное приложение для создания собственных проектов на основе Multiprocess Framework.

## Обзор

Шаблонное приложение (`template_application.py`) демонстрирует полное использование всех модулей фреймворка и может служить основой для создания реальных проектов.

## Структура шаблона

```
template_app/
├── config/
│   └── app_config.py          # Конфигурация приложения
├── processes/
│   ├── vision_process.py       # Процесс обработки изображений
│   ├── ai_process.py          # Процесс машинного обучения
│   ├── db_process.py          # Процесс работы с БД
│   └── ui_process.py          # Процесс UI (PyQt)
└── template_application.py    # Главное приложение
```

## Быстрый старт

### 1. Создание приложения

```python
from multiprocess_framework.refactored.tests.integration.template_app import (
    TemplateApplication,
    AppConfigManager
)

# Создаем конфигурацию
config_manager = AppConfigManager()
config = config_manager.load_config()

# Создаем и инициализируем приложение
app = TemplateApplication(config=config)
app.initialize()

# Запускаем приложение
app.start()
```

### 2. Использование приложения

```python
# Отправка тестового сообщения
app.send_test_message()

# Получение статистики
stats = app.get_stats()
print(stats)

# Остановка приложения
app.stop()
```

## Создание нового процесса

### Шаг 1: Создание класса процесса

Создайте файл `processes/my_process.py`:

```python
from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.worker_module import (
    WorkerManager, ThreadConfig, ThreadPriority
)

class MyProcess(ProcessModule):
    """
    Мой процесс для выполнения определенной задачи.
    
    Вход:
    - name: Имя процесса
    - shared_resources: SharedResourcesManager для межпроцессного взаимодействия
    - config: Словарь с конфигурацией процесса
    """
    
    def __init__(self, name: str, shared_resources=None, config: dict = None):
        """
        Инициализация процесса.
        
        Args:
            name: Имя процесса
            shared_resources: SharedResourcesManager
            config: Конфигурация процесса
        """
        super().__init__(name=name, shared_resources=shared_resources, config=config)
    
    def initialize(self) -> bool:
        """
        Инициализация процесса.
        
        Выход:
        - bool: True если инициализация успешна
        """
        if not super().initialize():
            return False
        
        # Создаем воркеров
        self._create_workers()
        
        # Регистрируем обработчики команд
        self._register_command_handlers()
        
        return True
    
    def _create_workers(self):
        """Создание воркеров для выполнения работы."""
        def my_worker(stop_event, pause_event):
            """
            Воркер для выполнения работы.
            
            Вход:
            - stop_event: Событие остановки воркера
            - pause_event: Событие паузы воркера
            """
            while not stop_event.is_set():
                if pause_event.is_set():
                    time.sleep(0.1)
                    continue
                
                # Ваша логика здесь
                self._do_work()
                time.sleep(0.1)
        
        # Создаем конфигурацию потока
        thread_config = ThreadConfig(
            name='my_worker',
            priority=ThreadPriority.NORMAL
        )
        
        # Создаем воркера
        self.worker_manager.create_worker(
            name='my_worker',
            target=my_worker,
            config=thread_config,
            auto_start=True  # Автоматический запуск
        )
    
    def _do_work(self):
        """Выполнение работы воркера."""
        # Ваша логика здесь
        pass
    
    def _register_command_handlers(self):
        """Регистрация обработчиков команд."""
        def handle_my_command(command_data):
            """
            Обработчик команды.
            
            Вход:
            - command_data: Данные команды
            
            Выход:
            - dict: Результат выполнения команды
            """
            return {'status': 'success', 'result': 'command executed'}
        
        # Регистрируем команду
        self.command_manager.register_command(
            'my_command',
            handle_my_command
        )
```

### Шаг 2: Регистрация процесса в приложении

В `template_application.py` добавьте:

```python
def _create_processes(self):
    """Создание процессов ОС через ProcessManagerCore."""
    processes_base_path = 'multiprocess_framework.refactored.tests.integration.template_app.processes'
    
    # Ваш процесс
    if self.config.my_process_enabled:
        my_config = {
            'setting1': 'value1',
            'setting2': 42
        }
        class_path = f'{processes_base_path}.my_process.MyProcess'
        result = self.process_manager.create_process(
            name='my_process',
            class_path=class_path,
            config=my_config,
            priority='normal'
        )
        if result:
            self.process_names.append('my_process')
```

## Работа с конфигурациями

### Создание конфигурации

```python
# В template_application.py
app_config_dict = {
    'my_setting': 'value',
    'another_setting': 42
}
self.config_manager.create_config('my_config', app_config_dict)
```

### Использование конфигурации

```python
# В процессе
my_config = self.config_manager.get_config('my_config')
value = my_config.get('my_setting')
```

## Межпроцессное взаимодействие

### Отправка сообщения

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
self.router_manager.send_message(message)
```

### Получение сообщений

```python
# Получение сообщений
messages = self.receive(timeout=0.1)
for msg in messages:
    # Обработка сообщения
    self._handle_message(msg)
```

## Обработка ошибок

### В воркере

```python
def my_worker(stop_event, pause_event):
    while not stop_event.is_set():
        try:
            # Ваша логика
            self._do_work()
        except Exception as e:
            # Логирование ошибки
            self._log_error(f"Error in worker: {e}")
            # Продолжаем работу или перезапускаем
            time.sleep(1)
```

### В процессе

```python
def initialize(self) -> bool:
    try:
        if not super().initialize():
            return False
        # Инициализация компонентов
        return True
    except Exception as e:
        self._log_error(f"Failed to initialize process: {e}")
        return False
```

## Примеры использования

### Пример 1: Простой процесс с одним воркером

```python
class SimpleProcess(ProcessModule):
    def initialize(self) -> bool:
        if not super().initialize():
            return False
        
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                print("Working...")
                time.sleep(1)
        
        config = ThreadConfig(priority=ThreadPriority.NORMAL)
        self.worker_manager.create_worker("worker", worker, config, auto_start=True)
        return True
```

### Пример 2: Процесс с несколькими воркерами

```python
class MultiWorkerProcess(ProcessModule):
    def initialize(self) -> bool:
        if not super().initialize():
            return False
        
        # Воркер 1
        def worker1(stop_event, pause_event):
            while not stop_event.is_set():
                self._task1()
                time.sleep(0.1)
        
        # Воркер 2
        def worker2(stop_event, pause_event):
            while not stop_event.is_set():
                self._task2()
                time.sleep(0.1)
        
        config = ThreadConfig(priority=ThreadPriority.NORMAL)
        self.worker_manager.create_worker("worker1", worker1, config, auto_start=True)
        self.worker_manager.create_worker("worker2", worker2, config, auto_start=True)
        return True
```

## Входы и выходы компонентов

### TemplateApplication

**Вход:**
- `config: AppConfig` — конфигурация приложения

**Выход:**
- `stats: Dict[str, Any]` — статистика приложения
- Состояние процессов через `get_stats()`

### ProcessModule

**Вход:**
- `name: str` — имя процесса
- `shared_resources: SharedResourcesManager` — общие ресурсы
- `config: dict` — конфигурация процесса

**Выход:**
- Состояние процесса через `get_stats()`
- Сообщения через RouterManager

### WorkerManager

**Вход:**
- `worker_name: str` — имя воркера
- `target: Callable` — функция воркера
- `config: ThreadConfig` — конфигурация потока

**Выход:**
- Статус воркера через `get_worker_status()`
- Метрики через `get_worker_metrics()`

## Следующие шаги

1. Изучите существующие процессы в `processes/`
2. Создайте свой процесс на основе шаблона
3. Добавьте обработку ошибок
4. Добавьте логирование
5. Протестируйте процесс
6. Интегрируйте в приложение

## Дополнительные ресурсы

- [Архитектура фреймворка](../../../docs/ARCHITECTURE_REFERENCE.md)
- [Обзор фреймворка](../../../docs/FRAMEWORK_OVERVIEW.md)
- [Документация модулей](../../../modules/)

---

**Примечание:** Это шаблон для демонстрации возможностей фреймворка. Для реального проекта удалите тестовую логику и добавьте свою бизнес-логику.

