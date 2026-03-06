# Оценка идеи: Builder API для многопроцессного приложения

## Идея

Создать объект приложения, в который методами добавляются:
- конфиги процессов (со ссылками на классы с логикой);
- воркеры;
- каналы роутера.

Конфиги — через `data_schema_module` (Pydantic). Всё собирается в одном месте и затем запускается.

**Важно:** Конфиги — это Pydantic-объекты, которые можно модифицировать методами перед добавлением в приложение.

---

## Целевой API (концепция)

```python
from multiprocess_prototype import MultiprocessApplication
from multiprocess_prototype.schemas import ProcessConfig, WorkerConfig

app = MultiprocessApplication()

# Добавить процесс
app.add_process(ProcessConfig(
    name="process_a",
    class_path="multiprocess_prototype.processes.process_a.ProcessAModule",
    workers_count=2,
    queue_maxsize=100,
))

# Добавить второй процесс
app.add_process(ProcessConfig(
    name="process_b",
    class_path="multiprocess_prototype.processes.process_b.ProcessBModule",
    workers_count=2,
))

# Опционально: добавить воркер
app.add_worker("process_a", WorkerConfig(name="worker_1", priority="normal"))

# Опционально: зарегистрировать канал для роутера
app.register_channel("process_a", "data", maxsize=100)

# Запуск
app.run()
```

---

## Конфиги как Pydantic-объекты с методами модификации

Конфиги создаются через `data_schema_module` (Pydantic). Их можно модифицировать методами перед добавлением в приложение.

### Вариант: fluent-методы (model_copy)

```python
from multiprocess_prototype.schemas import ProcessConfig, WorkerConfig

# Создать config
config = ProcessConfig(
    name="process_a",
    class_path="multiprocess_prototype.processes.process_a.ProcessAModule",
)

# Модифицировать методами (Pydantic model_copy — иммутабельно)
config = config.model_copy(update={"workers_count": 2})
config = config.model_copy(update={"queue_maxsize": 200})

# Или добавить обёртки для удобства
config = config.with_workers(3).with_queue_maxsize(100)
```

### Вариант: методы-обёртки на конфиге

```python
@register_schema("ProcessConfig")
class ProcessConfig(BaseModel):
    name: str
    class_path: str
    workers_count: int = 2
    queue_maxsize: int = 100
    workers: List[WorkerConfig] = Field(default_factory=list)
    queues: Optional[Dict[str, dict]] = None

    def with_workers(self, n: int) -> "ProcessConfig":
        return self.model_copy(update={"workers_count": n})

    def with_queue_maxsize(self, n: int) -> "ProcessConfig":
        return self.model_copy(update={"queue_maxsize": n})

    def add_worker(self, worker: WorkerConfig) -> "ProcessConfig":
        return self.model_copy(update={"workers": self.workers + [worker]})

# Использование
config = (
    ProcessConfig(name="process_a", class_path="...ProcessAModule")
    .with_workers(3)
    .with_queue_maxsize(150)
    .add_worker(WorkerConfig(name="worker_1", priority="normal"))
)
app.add_process(config)
```

### Вариант: мутабельные методы (in-place)

```python
def with_workers(self, n: int) -> "ProcessConfig":
    self.workers_count = n
    return self

# config.with_workers(3).with_queue_maxsize(100)
```

**Рекомендация:** использовать `model_copy(update={...})` — иммутабельно, предсказуемо, совместимо с Pydantic. Методы-обёртки (`with_workers`, `add_worker`) упрощают цепочку вызовов.

---

## Альтернативные механизмы

### 1. Builder (текущее предложение)

```python
app = MultiprocessApplication()
app.add_process(ProcessConfig(...)).add_process(ProcessConfig(...))
app.run()
```

**Плюсы:** Явно, гибко, порядок под контролем.  
**Минусы:** Императивно, состояние накапливается, сложнее переиспользовать.

---

### 2. Registry + Declarative Config

```python
# Регистрация типов процессов (один раз)
ProcessRegistry.register("ProcessA", ProcessAModule, ProcessConfigSchema)

# Запуск — только конфиг (YAML/dict)
app = MultiprocessApplication.from_config("app.yaml")
app.run()
```

**app.yaml:**
```yaml
processes:
  - type: ProcessA
    name: process_a
    workers_count: 2
  - type: ProcessB
    name: process_b
```

**Плюсы:** Один источник правды, версионирование, валидация по схеме.  
**Минусы:** Меньше гибкости при программной сборке.

---

### 3. Composable Descriptors (иммутабельно)

```python
app = MultiprocessApplication([
    ProcessDescriptor(name="process_a", class_path="...", workers_count=2),
    ProcessDescriptor(name="process_b", class_path="...", workers_count=2),
])
app.run()
```

Или через цепочку:

```python
app = App.empty().with_process(...).with_process(...)
```

**Плюсы:** Иммутабельность, проще тестировать, композиция.  
**Минусы:** Более многословно.

---

### 4. Гибрид: Config + Builder

```python
# Основной путь — из конфига
app = MultiprocessApplication.from_config("app.yaml")

# Дополнение программно
app.add_process(ProcessConfig(...))

app.run()
```

**Плюсы:** Конфиг для типового сценария, Builder для переопределений.  
**Минусы:** Два способа задать одно и то же.

---

### 5. Blueprint / Template

```python
# Шаблон процесса
vision_blueprint = ProcessBlueprint(
    class_path="...VisionProcess",
    default_workers=2,
    default_queues={"system": 100, "data": 50},
)

# Использование с переопределениями
app.add_process(vision_blueprint.instantiate(name="vision_1", workers_count=3))
app.add_process(vision_blueprint.instantiate(name="vision_2"))
```

**Плюсы:** Переиспользование, DRY.  
**Минусы:** Дополнительный слой абстракции.

---

### 6. Schema-first + Auto-discovery

```python
# Конфиг ссылается на классы по пути
# Схемы подтягиваются из data_schema_module по имени
app = MultiprocessApplication.from_config({
    "processes": [
        {"name": "process_a", "schema": "ProcessAConfig", "workers_count": 2},
    ]
})
```

**Плюсы:** Схемы — единственный источник структуры.  
**Минусы:** Нужна дисциплина именования и регистрации схем.

---

## Сравнение механизмов

| Механизм | Гибкость | Простота | Переиспользование | Валидация | Рекомендация |
|----------|----------|----------|-------------------|-----------|--------------|
| Builder | Высокая | Средняя | Низкая | Pydantic | Хорош для MVP |
| Registry + Config | Средняя | Высокая | Высокая | По схеме | Для production |
| Descriptors | Высокая | Средняя | Высокая | Pydantic | Для тестов и композиции |
| Config + Builder | Высокая | Высокая | Средняя | Оба | Оптимальный баланс |
| Blueprint | Высокая | Средняя | Очень высокая | Pydantic | При множестве похожих процессов |
| Schema-first | Средняя | Высокая | Высокая | Строгая | При жёсткой типизации |

---

## Рекомендуемый механизм: Config + Builder

Комбинация даёт:

1. **Конфиги через data_schema_module** — Pydantic-модели с валидацией.
2. **Методы модификации конфигов** — `with_workers()`, `add_worker()` и т.п. для удобной настройки.
3. **Конфиг (YAML/JSON)** — основной способ для типовых приложений.
4. **Builder** — для программной сборки и переопределений.
5. **Единый внутренний формат** — оба пути строят один и тот же `processes_config`.

```python
# Конфиг как Pydantic-объект с методами
config = (
    ProcessConfig(name="process_a", class_path="...ProcessAModule")
    .with_workers(3)
    .with_queue_maxsize(150)
    .add_worker(WorkerConfig(name="worker_1"))
)
app.add_process(config)

# Вариант 1: только конфиг
app = MultiprocessApplication.from_config("app.yaml")

# Вариант 2: только builder
app = MultiprocessApplication().add_process(...).add_process(...)

# Вариант 3: конфиг + дополнения
app = MultiprocessApplication.from_config("app.yaml").add_process(extra_process)
```

Реализация: `from_config()` парсит YAML, валидирует через Pydantic, заполняет внутренний `_processes`. Builder и конфиг пишут в одну структуру. Конфиги — Pydantic-модели с fluent-методами (`model_copy`).

---

## Оценка

### Оценка: 8/10 (реализуемо и полезно)

| Аспект | Оценка | Комментарий |
|--------|--------|-------------|
| Понятность | Высокая | Fluent API, явная сборка приложения |
| Расширяемость | Высокая | Добавление процессов/воркеров без изменения кода |
| Интеграция с data_schema | Высокая | ProcessConfig, WorkerConfig как Pydantic-модели |
| Интеграция с framework | Средняя | Нужны адаптеры к ProcessManagerCore, WorkerManager |
| Сложность реализации | Средняя | ~2–3 дня для MVP |

---

## Как сейчас

### Текущая схема

1. **app.py** — создаёт `SharedResourcesManager`, `ConfigManager`, `QueueRegistry`, `ProcessManagerCore`.
2. **Вручную** — `register_process_state`, `create_and_register_queues`, `create_process` для каждого процесса.
3. **ProcessModule** — `_create_workers()` захардкожен в каждом классе (ProcessAModule, ProcessBModule).
4. **Каналы** — создаются в `ProcessCommunication.register_router_channels()` из очередей процесса.

### Ограничения

- Дублирование логики для каждого процесса.
- Воркеры задаются внутри ProcessModule, а не в конфиге.
- Нет единой точки входа для сборки приложения.
- Конфиги — обычные dict, без валидации.

---

## Возможность реализации

### 1. MultiprocessApplication (Builder)

```python
class MultiprocessApplication:
    def __init__(self):
        self._processes: Dict[str, ProcessConfig] = {}
        self._workers: Dict[str, List[WorkerConfig]] = {}  # process_name -> workers
        self._channels: List[ChannelConfig] = []

    def add_process(self, config: ProcessConfig) -> "MultiprocessApplication":
        self._processes[config.name] = config
        return self

    def add_worker(self, process_name: str, config: WorkerConfig) -> "MultiprocessApplication":
        self._workers.setdefault(process_name, []).append(config)
        return self

    def register_channel(self, process_name: str, channel_type: str, **kwargs) -> "MultiprocessApplication":
        self._channels.append({"process": process_name, "type": channel_type, **kwargs})
        return self

    def run(self):
        # Собрать processes_config
        # Запустить SystemLauncher
        ...
```

### 2. Схемы через data_schema_module + методы модификации

```python
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from multiprocess_framework.refactored.modules.data_schema_module import register_schema

@register_schema("ProcessConfig")
class ProcessConfig(BaseModel):
    name: str
    class_path: str
    workers_count: int = 2
    queue_maxsize: int = 100
    workers: List["WorkerConfig"] = Field(default_factory=list)
    queues: Optional[Dict[str, dict]] = None
    priority: str = "normal"

    def with_workers(self, n: int) -> "ProcessConfig":
        return self.model_copy(update={"workers_count": n})

    def with_queue_maxsize(self, n: int) -> "ProcessConfig":
        return self.model_copy(update={"queue_maxsize": n})

    def add_worker(self, worker: "WorkerConfig") -> "ProcessConfig":
        return self.model_copy(update={"workers": [*self.workers, worker]})

@register_schema("WorkerConfig")
class WorkerConfig(BaseModel):
    name: str
    priority: str = "normal"
```

### 3. Воркеры из конфига

Сейчас воркеры создаются в `ProcessAModule._create_workers()`. Чтобы задавать их извне:

**Вариант A:** Универсальный `ConfigurableProcessModule`:

```python
class ConfigurableProcessModule(ProcessModule):
    def _create_workers(self):
        workers_config = self.config.get("workers", [])
        if not workers_config:
            workers_config = [{"name": f"worker_{i}"} for i in range(self.config.get("workers_count", 2))]
        for w in workers_config:
            self.worker_manager.create_worker(w["name"], self._default_worker, ThreadConfig(...))
```

**Вариант B:** Оставить логику в ProcessModule, но передавать `workers` в конфиг. Процесс сам решает, как создавать воркеров (по умолчанию — из `workers_count`).

### 4. Каналы роутера

Каналы уже создаются из очередей в `ProcessCommunication.register_router_channels()`. Очереди задаются в `process_config["queues"]`. Дополнительные каналы можно задавать в конфиге:

```python
process_config["channels"] = [
    {"name": "data", "queue_type": "data", "maxsize": 100},
]
```

---

## План реализации (MVP)

### Фаза 1: Builder + ProcessConfig

1. Схемы в `multiprocess_prototype/schemas/`:
   - `ProcessConfig` (Pydantic)
   - `WorkerConfig` (Pydantic)
2. `MultiprocessApplication`:
   - `add_process(config)`
   - `run()` — сборка `processes_config` и запуск `SystemLauncher`
3. Доработка `ProcessManagerProcess` — создание процессов из `processes_config` (как в плане).

### Фаза 2: Воркеры из конфига

1. `ProcessConfig.workers: List[WorkerConfig]` — опционально.
2. `ConfigurableProcessModule` или расширение `ProcessModule` — чтение `workers` из конфига.
3. `app.add_worker(process_name, WorkerConfig)` — добавление в `ProcessConfig` перед запуском.

### Фаза 3: Каналы

1. `ProcessConfig.channels` — список каналов.
2. `app.register_channel(process_name, channel_type, **kwargs)` — добавление в конфиг процесса.
3. `ProcessCommunication` — поддержка `channels` из конфига (если не хватает стандартных очередей).

---

## Рекомендации

1. **Механизм:** Config + Builder — конфиг как основной путь, Builder для дополнений.
2. Начать с Фазы 1 — Builder + ProcessConfig + SystemLauncher.
3. Добавить `from_config(path)` — загрузка из YAML/JSON с валидацией.
4. Использовать `data_schema_module` для `ProcessConfig` и `WorkerConfig`.
5. `add_process` — принимать `ProcessConfig` или dict (для совместимости).
6. `add_worker` и `register_channel` — реализовать после стабилизации базового сценария.
7. `app.py` оставить как тонкую обёртку или удалить после перехода на Builder.

---

## Сравнение с текущим подходом

| Критерий | Сейчас (app.py) | Builder API |
|----------|------------------|-------------|
| Добавление процесса | 15+ строк кода | 1 вызов `add_process()` |
| Валидация конфига | Нет | Pydantic |
| Воркеры | В коде ProcessModule | В конфиге (опционально) |
| Расширяемость | Копирование кода | Методы add_* |
| Точка входа | `MultiprocessPrototypeApp` | `MultiprocessApplication` |
