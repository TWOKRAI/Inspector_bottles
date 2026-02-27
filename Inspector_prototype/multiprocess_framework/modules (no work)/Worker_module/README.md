# WorkerModule - Документация

## Обзор

`WorkerModule` предоставляет централизованное управление потоками выполнения (воркерами) для многопроцессной архитектуры. Модуль позволяет создавать, запускать, останавливать и мониторить потоки с поддержкой приоритетов, зависимостей и автоматического перезапуска при ошибках.

**Основные возможности:**
- Управление жизненным циклом потоков
- Приоритеты выполнения (SYSTEM, REALTIME, NORMAL, BATCH, BACKGROUND)
- Зависимости между воркерами
- Автоматический перезапуск при ошибках
- Метрики производительности
- Пауза и возобновление выполнения

## Архитектура

```
WorkerModule
├── WorkerManager - основной менеджер воркеров
├── ThreadConfig - конфигурация потока
├── ThreadPriority - приоритеты выполнения
└── WorkerStatus - статусы состояния воркера
```

## Компоненты

### WorkerManager

Центральный менеджер для управления потоками-воркерами. Предоставляет API для создания, запуска, остановки и мониторинга воркеров.

**Потокобезопасность:**
- Все публичные методы являются потокобезопасными
- Внутренние структуры защищены GIL (Global Interpreter Lock)
- Методы можно вызывать из любого потока без дополнительной синхронизации

**Ограничения:**
- Не предназначен для использования из нескольких процессов, только потоков
- Для межпроцессного взаимодействия используйте `multiprocessing` модуль

### ThreadConfig

Конфигурация потока-воркера, содержащая параметры для настройки поведения:
- `priority` - приоритет потока (ThreadPriority)
- `poll_interval` - интервал опроса (автоматически вычисляется из приоритета)
- `restart_on_failure` - автоматический перезапуск при ошибке
- `max_restarts` - максимальное количество перезапусков
- `dependencies` - список имен воркеров, от которых зависит этот воркер

### ThreadPriority

Приоритеты потоков выполнения:

| Приоритет | Интервал опроса | Описание |
|-----------|----------------|----------|
| `SYSTEM` | 0.001s | Системные потоки (критически важные) |
| `REALTIME` | 0.01s | Потоки реального времени |
| `NORMAL` | 0.1s | Обычные потоки (по умолчанию) |
| `BATCH` | 1.0s | Пакетная обработка |
| `BACKGROUND` | 5.0s | Фоновые задачи |

### WorkerStatus

Статусы состояния воркера:

- `STOPPED` - остановлен
- `RUNNING` - работает
- `ERROR` - ошибка выполнения
- `STOPPING` - в процессе остановки

## Публичные методы (Public API)

### Инициализация

#### `WorkerManager(name: str)`

Создание нового менеджера воркеров.

**Параметры:**
- `name` - имя менеджера (используется для именования потоков)

**Пример:**
```python
manager = WorkerManager("VisionProcess")
```

---

### Создание воркеров

#### `create_worker(worker_name: str, target: Callable, config: ThreadConfig, auto_start: bool = False) -> bool`

Создание нового воркера (потока).

**Параметры:**
- `worker_name` - уникальное имя воркера
- `target` - целевая функция для выполнения (должна принимать `stop_event`, `pause_event`)
- `config` - конфигурация потока (ThreadConfig)
- `auto_start` - автоматический запуск после создания (по умолчанию False)

**Возвращает:**
- `bool` - True если создание успешно, False если воркер уже существует или не выполнены зависимости

**Пример:**
```python
def my_worker(stop_event, pause_event):
    while not stop_event.is_set():
        if pause_event.is_set():
            time.sleep(0.1)
            continue
        # Работа воркера
        process_data()
        time.sleep(0.1)

config = ThreadConfig(priority=ThreadPriority.NORMAL)
manager.create_worker("data_processor", my_worker, config, auto_start=True)
```

**Особенности:**
- Проверяет уникальность имени воркера
- Проверяет, что все зависимости существуют и запущены
- Создает поток с событиями остановки и паузы

---

### Управление жизненным циклом

#### `start_worker(worker_name: str) -> bool`

Запуск воркера.

**Параметры:**
- `worker_name` - имя воркера для запуска

**Возвращает:**
- `bool` - True если запуск успешен, False если воркер не найден

**Пример:**
```python
if manager.start_worker("data_processor"):
    print("Воркер запущен")
```

**Особенности:**
- Если воркер уже запущен, возвращает True без повторного запуска
- Если поток был завершен, создает новый поток для перезапуска

---

#### `stop_worker(worker_name: str, timeout: float = 5.0) -> bool`

Остановка воркера.

**Параметры:**
- `worker_name` - имя воркера для остановки
- `timeout` - таймаут ожидания завершения потока в секундах (по умолчанию 5.0)

**Возвращает:**
- `bool` - True если воркер найден и остановка инициирована, False если воркер не найден

**Пример:**
```python
manager.stop_worker("data_processor", timeout=10.0)
```

---

#### `restart_worker(worker_name: str, timeout: float = 5.0) -> bool`

Перезапуск воркера.

**Параметры:**
- `worker_name` - имя воркера для перезапуска
- `timeout` - таймаут ожидания остановки в секундах (по умолчанию 5.0)

**Возвращает:**
- `bool` - True если перезапуск успешен, False если воркер не найден

**Пример:**
```python
manager.restart_worker("data_processor")
```

---

#### `pause_worker(worker_name: str) -> bool`

Приостановка выполнения воркера.

**Параметры:**
- `worker_name` - имя воркера для приостановки

**Возвращает:**
- `bool` - True если пауза установлена, False если воркер не найден

**Важно:** Воркер должен проверять `pause_event` в своем цикле.

**Пример:**
```python
manager.pause_worker("data_processor")
```

---

#### `resume_worker(worker_name: str) -> bool`

Возобновление выполнения воркера.

**Параметры:**
- `worker_name` - имя воркера для возобновления

**Возвращает:**
- `bool` - True если пауза снята, False если воркер не найден

**Пример:**
```python
manager.resume_worker("data_processor")
```

---

#### `start_all_workers()`

Запуск всех зарегистрированных воркеров.

**Пример:**
```python
manager.start_all_workers()
```

**Примечание:** Воркеры запускаются в порядке их регистрации. Воркеры с зависимостями должны быть созданы в правильном порядке.

---

#### `stop_all_workers()`

Остановка всех зарегистрированных воркеров.

**Пример:**
```python
manager.stop_all_workers()
```

---

### Мониторинг и статус

#### `is_worker_running(worker_name: str) -> bool`

Проверка, запущен ли воркер.

**Параметры:**
- `worker_name` - имя воркера

**Возвращает:**
- `bool` - True если воркер запущен и работает, False в противном случае

**Пример:**
```python
if manager.is_worker_running("data_processor"):
    print("Воркер работает")
```

---

#### `get_worker_status(worker_name: str) -> Optional[Dict]`

Получение детального статуса воркера.

**Параметры:**
- `worker_name` - имя воркера

**Возвращает:**
- `Optional[Dict]` - словарь со статусом или None если воркер не найден

**Структура возвращаемого словаря:**
```python
{
    'name': str,                    # Имя воркера
    'status': str,                  # Статус ('stopped', 'running', 'error', 'stopping')
    'is_alive': bool,               # Жив ли поток
    'restart_count': int,           # Количество перезапусков
    'last_error': Optional[str],    # Последняя ошибка
    'metrics': Dict                 # Метрики производительности
}
```

**Пример:**
```python
status = manager.get_worker_status("data_processor")
if status:
    print(f"Статус: {status['status']}")
    print(f"Перезапусков: {status['restart_count']}")
```

---

#### `get_all_workers_status() -> Dict[str, Dict]`

Получение статусов всех воркеров.

**Возвращает:**
- `Dict[str, Dict]` - словарь статусов всех воркеров, ключ - имя воркера

**Пример:**
```python
all_statuses = manager.get_all_workers_status()
for name, status in all_statuses.items():
    print(f"{name}: {status['status']}")
```

---

#### `get_worker_metrics(worker_name: str) -> Optional[Dict]`

Получение метрик производительности воркера.

**Параметры:**
- `worker_name` - имя воркера

**Возвращает:**
- `Optional[Dict]` - словарь с метриками или None если воркер не найден

**Структура возвращаемого словаря:**
```python
{
    'total_runtime': float,         # Общее время работы (секунды)
    'last_run_duration': float,     # Длительность последнего запуска
    'successful_runs': int,         # Количество успешных запусков
    'failed_runs': int,             # Количество неудачных запусков
    'restart_count': int,           # Количество перезапусков
    'avg_run_time': float,          # Среднее время выполнения
    'start_time': Optional[float],  # Время последнего запуска
    'uptime': float                 # Время работы с момента запуска
}
```

**Пример:**
```python
metrics = manager.get_worker_metrics("data_processor")
if metrics:
    print(f"Успешных запусков: {metrics['successful_runs']}")
    print(f"Среднее время: {metrics['avg_run_time']}s")
```

---

## Примеры использования

### Базовый пример

```python
from src.Modules.Worker_module import WorkerManager, ThreadConfig, ThreadPriority
import time

# Создание менеджера
manager = WorkerManager("MyProcess")

# Определение функции воркера
def data_processor(stop_event, pause_event):
    while not stop_event.is_set():
        if pause_event.is_set():
            time.sleep(0.1)
            continue
        
        # Обработка данных
        process_data()
        time.sleep(0.1)

# Создание конфигурации
config = ThreadConfig(
    priority=ThreadPriority.NORMAL,
    restart_on_failure=True,
    max_restarts=3
)

# Создание и запуск воркера
manager.create_worker("processor", data_processor, config, auto_start=True)

# Работа...

# Остановка воркера
manager.stop_worker("processor")
```

### Воркеры с зависимостями

```python
# Создаем первый воркер (базовый)
def base_worker(stop_event, pause_event):
    initialize_system()
    while not stop_event.is_set():
        time.sleep(0.1)

config1 = ThreadConfig(priority=ThreadPriority.SYSTEM)
manager.create_worker("base", base_worker, config1, auto_start=True)
time.sleep(0.1)  # Ждем запуска

# Создаем зависимый воркер
def dependent_worker(stop_event, pause_event):
    while not stop_event.is_set():
        process_dependent_task()
        time.sleep(0.1)

config2 = ThreadConfig(
    priority=ThreadPriority.NORMAL,
    dependencies=["base"]  # Зависит от базового воркера
)
manager.create_worker("dependent", dependent_worker, config2, auto_start=True)
```

### Автоматический перезапуск при ошибках

```python
def unreliable_worker(stop_event, pause_event):
    # Может упасть с ошибкой
    if random.random() < 0.1:
        raise RuntimeError("Случайная ошибка")
    
    while not stop_event.is_set():
        do_work()
        time.sleep(0.1)

config = ThreadConfig(
    priority=ThreadPriority.NORMAL,
    restart_on_failure=True,  # Включить автоперезапуск
    max_restarts=5             # Максимум 5 перезапусков
)

manager.create_worker("unreliable", unreliable_worker, config, auto_start=True)
```

### Мониторинг воркеров

```python
# Проверка статуса
status = manager.get_worker_status("processor")
print(f"Статус: {status['status']}")
print(f"Ошибок: {status['last_error']}")

# Получение метрик
metrics = manager.get_worker_metrics("processor")
print(f"Успешных запусков: {metrics['successful_runs']}")
print(f"Неудачных запусков: {metrics['failed_runs']}")
print(f"Среднее время работы: {metrics['avg_run_time']}s")

# Мониторинг всех воркеров
all_statuses = manager.get_all_workers_status()
for name, status in all_statuses.items():
    print(f"{name}: {status['status']}")
```

### Пауза и возобновление

```python
# Приостановка воркера
manager.pause_worker("processor")

# ... выполнение других задач ...

# Возобновление работы
manager.resume_worker("processor")
```

### Использование в ProcessModule

```python
from src.Modules.Process_module import ProcessModule
from src.Modules.Worker_module import ThreadConfig, ThreadPriority

class MyProcess(ProcessModule):
    def setup(self):
        # WorkerManager доступен через managers_component
        worker_manager = self.managers_component.worker_manager
        
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                # Работа воркера
                self.process_data()
                time.sleep(0.1)
        
        config = ThreadConfig(priority=ThreadPriority.NORMAL)
        worker_manager.create_worker("data_worker", worker, config, auto_start=True)
```

## Лучшие практики

### 1. Правильная обработка событий в воркере

Всегда проверяйте `stop_event` и `pause_event` в цикле воркера:

```python
def good_worker(stop_event, pause_event):
    while not stop_event.is_set():
        if pause_event.is_set():
            time.sleep(0.1)  # Небольшая задержка при паузе
            continue
        
        # Основная работа
        do_work()
        time.sleep(0.1)
```

### 2. Использование приоритетов

Выбирайте правильный приоритет для вашего воркера:

- `SYSTEM` - только для критически важных системных задач
- `REALTIME` - для задач, требующих быстрого отклика
- `NORMAL` - для большинства обычных задач
- `BATCH` - для пакетной обработки данных
- `BACKGROUND` - для фоновых задач, не требующих быстрого отклика

### 3. Обработка ошибок

Используйте автоматический перезапуск только для временных ошибок:

```python
config = ThreadConfig(
    restart_on_failure=True,
    max_restarts=3  # Ограничьте количество перезапусков
)
```

### 4. Зависимости между воркерами

Создавайте воркеры с зависимостями в правильном порядке:

```python
# 1. Создайте базовые воркеры
manager.create_worker("base", base_worker, config1, auto_start=True)
time.sleep(0.1)  # Дождитесь запуска

# 2. Создайте зависимые воркеры
manager.create_worker("dependent", dependent_worker, config2, auto_start=True)
```

### 5. Корректное завершение

Всегда останавливайте воркеры при завершении:

```python
try:
    # Работа приложения
    pass
finally:
    manager.stop_all_workers()
```

## Ограничения и известные проблемы

1. **Циклические зависимости:** Текущая реализация не проверяет циклические зависимости между воркерами. Избегайте создания циклических зависимостей.

2. **Межпроцессное взаимодействие:** Модуль предназначен только для управления потоками внутри одного процесса. Для межпроцессного взаимодействия используйте `multiprocessing`.

3. **Длительные операции:** Длительные операции в целевых функциях могут блокировать основной поток. Используйте асинхронные операции или разбивайте работу на части.

4. **Таймаут остановки:** Если воркер не завершится за указанный таймаут, он будет помечен как остановленный, но поток может продолжать работать.

## Тестирование

Модуль покрыт комплексными тестами в `tests/Test_Worker_module/`:

- Базовые операции (создание, запуск, остановка)
- Зависимости между воркерами
- Пауза и возобновление
- Обработка ошибок
- Автоматический перезапуск
- Метрики производительности
- Граничные случаи
- Потокобезопасность

Запуск тестов:
```bash
pytest tests/Test_Worker_module/ -v
```

## См. также

- [ProcessModule](../Process_module/README.md) - базовый класс процессов
- [Multiprocessing Architecture](../../../docs/MULTIPROCESSING_ARCHITECTURE.md) - архитектура многопроцессной системы

