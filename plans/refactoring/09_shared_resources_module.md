# Refactoring plan: `shared_resources_module` (модуль #8)

> **Статус:** ✅ Завершено (Steps 0–9, 2026-04-09).  
> **Автор плана:** Claude (Opus 4.6), 2026-04-09.  
> **Исполнитель:** Cursor Composer Agent v2.  
> **Ревьюер:** Claude (Opus 4.6) — ревью проведено, улучшения внесены.  
> **Ссылки:** [00_overview.md](./00_overview.md) · [ARCHITECTURE.md](../../Inspector_prototype/multiprocess_framework/ARCHITECTURE.md)
>
> **Важное отклонение:** Метод точки входа Handle API называется `for_process()`, а не `process()` — конфликт с `BaseManager.process` (ADR-SRM-007). Все примеры ниже оставлены как было в плане для истории; в реальном коде используйте `srm.for_process("name")`.

---

## 0. Контекст

`shared_resources_module` (#8) — центральный модуль фреймворка. Живёт в главном процессе (ProcessManagerProcess), передаётся дочерним через pickle. Управляет: очередями, событиями, SharedMemory, конфигами, состояниями процессов.

**Baseline (2026-04-09):**
- **Файлов:** 41 · **LOC:** 3,221
- **Тестов:** 107 passed, 15 skipped (unit) + 25 passed, 7 skipped (memory)
- **CC max:** 10 (MemoryManager, QueueRegistry)

**Корневая директория модуля:**
```
Inspector_prototype/multiprocess_framework/modules/shared_resources_module/
```
Далее все пути — относительно этой директории.

---

## 1. Проблемы текущего API (почему рефакторим)

| # | Проблема | Где | Влияние |
|---|---------|-----|---------|
| P1 | 5 внутренних менеджеров — public properties (строки 248-266 `core/shared_resources_manager.py`) | Потребители обходят фасад | Нарушение инкапсуляции |
| P2 | 3 способа получить очередь: SRM, ProcessData.queues, QueueRegistry | Путаница в API | Inconsistency |
| P3 | Queues/Events имеют Proxy, Memory — нет | Нет единого паттерна | Неудобство |
| P4 | 6+ мёртвых legacy-методов (строки 296-351 `core/shared_resources_manager.py`), 0 внешних вызовов | Загрязнение API | Мёртвый код |
| P5 | Тройное хранение Queue: `QueueRegistry.registered_queues`, `ProcessData._queues_dict`, SRM property | Дублирование | Рассогласование |
| P6 | `wait_for_event()` (строки 166-185 `events/core/manager.py`) — race condition с put-back | Потеря событий | Баг |
| P7 | `print()` вместо logging в `memory/core/manager.py` строки 188-190, 294-297, 382-385 | Неконсистентность | ADR-026 |
| P8 | `PSR._emit()` (строка 54 `state/process_state_registry.py`) — `except Exception: pass` | Тихие ошибки | Отладка |
| P9 | `validate_memory_access()` возвращает bool — нет причины ошибки | Сложная отладка | Диагностика |

---

## 2. Целевая архитектура

### Before
```python
# 3 пути к очереди:
srm.queue_registry.get_queue("worker", "system")
srm.get_process_data("worker").queues.system
srm.get_process_queue("worker", "system")

# Memory — только через менеджер:
srm.memory_manager.write_images("worker", "frame", imgs, 0)
```

### After
```python
handle = srm.process("worker")
handle.queue("system").send(msg)                  # Очередь
handle.event("stop").set()                        # Событие
handle.memory("frame").write(images, index=0)     # Память
handle.status                                     # → ProcessStatus
handle.config                                     # → dict

# Высокоуровневые операции:
srm.broadcast(msg, exclude="manager")
srm.has_process("worker")
```

---

## 3. Атомарные шаги (пошагово для Composer v2)

---

### Step 0 — Baseline ✅

Уже выполнено. Результат:
- `pytest shared_resources_module/tests/ -v` → **107 passed, 15 skipped**
- `pytest shared_resources_module/memory/tests/ -v` → **25 passed, 7 skipped**

---

### Step 1 — Удалить legacy API + мёртвый код

**Задача:** Удалить 6+ мёртвых методов и 1 мёртвый метод в PSR. Grep подтвердил: 0 внешних вызовов.

#### 1.1. Файл: `core/shared_resources_manager.py`

**Удалить строку 102:**
```python
self.shared_resources: Dict[str, Any] = {}
```

**Удалить строку 126 (в методе shutdown):**
```python
self.shared_resources.clear()
```

**Удалить полностью строки 292-351** (весь блок "Обратная совместимость"):
```python
    # =========================================================================
    # Обратная совместимость (старый API)
    # =========================================================================

    def register_process_state(...) -> bool: ...
    def register_process_with_config(...) -> bool: ...
    def update_process_state(...) -> bool: ...
    def get_process_state(...) -> Optional[Dict[str, Any]]: ...
    def get_all_process_states(...) -> Dict[str, Dict[str, Any]]: ...
    def add_shared_resource(...) -> None: ...
    def get_shared_resource(...) -> Optional[Any]: ...
    def get_data_manager(...) -> Optional[Any]: ...

    @property
    def data_manager(self) -> Optional[Any]: ...
```

**Также в `__getattr__` (строка 384)** удалить `"shared_resources"` из списка:
```python
# Было:
if name.startswith("_") or name in (
    "_process_state_registry", "shared_resources", "_event_manager",
# Стало:
if name.startswith("_") or name in (
    "_process_state_registry", "_event_manager",
```

#### 1.2. Файл: `state/process_state_registry.py`

**Удалить строки 220-231** (метод `register_process_with_config`):
```python
    def register_process_with_config(
        self,
        process_name: str,
        config: Any,
        initial_state: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Регистрация с конфигурацией (ProcessConfiguration или dict)."""
        if hasattr(config, "to_dict"):
            config = config.to_dict()
        elif not isinstance(config, dict):
            config = {}
        return self.register_process(process_name, initial_state=initial_state or {})
```

#### 1.3. Файл: `tests/test_shared_resources_manager.py`

**Обновить класс `TestBackwardCompatibility`** (строки 186-204).

**Удалить тесты:**
- `test_register_process_state` (строки 187-190) — тестирует удалённый метод
- `test_add_shared_resource` (строки 202-204) — тестирует удалённый метод

**Оставить тесты** (они используют живые методы):
- `test_get_process_queue` (строки 192-195) — `get_process_queue()` жив
- `test_get_process_event` (строки 197-200) — `get_process_event()` жив

**Переименовать класс** `TestBackwardCompatibility` → `TestConvenienceAccessors`.

#### 1.4. Верификация Step 1

```bash
cd Inspector_prototype
python -m pytest multiprocess_framework/modules/shared_resources_module/tests/ -v --tb=short
# Ожидание: 105 passed (было 107, минус 2 удалённых теста), 15 skipped
```

#### 1.5. ADR

Создать/обновить `DECISIONS.md` в корне модуля, добавить:
```markdown
### ADR-SRM-001: Удалён legacy API v1

**Дата:** 2026-04-09  
**Решение:** Удалены методы register_process_state, register_process_with_config,
update_process_state, get_process_state, get_all_process_states, add_shared_resource,
get_shared_resource, get_data_manager, data_manager.  
**Причина:** 0 внешних потребителей (подтверждено grep по всему репозиторию).  
**Каноничный API:** `srm.register_process(name, config)` (ADR-018).
```

---

### Step 2 — Создать `ProcessHandle`, `QueueHandle`, `EventHandle`

**Задача:** Новый слой Handle API — единый паттерн доступа к ресурсам процесса.

#### 2.1. Создать файл: `handles/__init__.py`

```python
"""Handle API — единый паттерн доступа к ресурсам процесса."""

from .process_handle import ProcessHandle, QueueHandle, EventHandle

__all__ = ["ProcessHandle", "QueueHandle", "EventHandle"]
```

#### 2.2. Создать файл: `handles/process_handle.py`

```python
"""
ProcessHandle — единый chainable доступ к ресурсам процесса.

Использование:
    handle = srm.process("worker")
    handle.queue("system").send(msg)
    handle.event("stop").set()
    handle.status  # → ProcessStatus
"""

from typing import Any, Dict, List, Optional, TYPE_CHECKING
from multiprocessing import Queue, Event

if TYPE_CHECKING:
    from ..core.shared_resources_manager import SharedResourcesManager
    from ..state.process_data import ProcessData
    from ..types import ProcessStatus


class QueueHandle:
    """
    Обёртка над multiprocessing.Queue с удобными методами.

    Использование:
        handle.queue("system").send(msg)
        data = handle.queue("data").receive(timeout=1.0)
    """

    __slots__ = ("_queue", "_process_name", "_queue_type", "_queue_registry")

    def __init__(
        self,
        queue: Optional[Queue],
        process_name: str,
        queue_type: str,
        queue_registry: Optional[Any] = None,
    ) -> None:
        self._queue = queue
        self._process_name = process_name
        self._queue_type = queue_type
        self._queue_registry = queue_registry

    def send(self, message: Any, timeout: float = 0.0) -> bool:
        """Отправить сообщение в очередь."""
        if self._queue_registry is not None:
            return self._queue_registry.send_to_queue(
                self._process_name, self._queue_type, message, timeout
            )
        if self._queue is None:
            return False
        try:
            if timeout > 0:
                self._queue.put(message, timeout=timeout)
            else:
                self._queue.put_nowait(message)
            return True
        except Exception:
            return False

    def receive(self, timeout: float = 0.0) -> Optional[Any]:
        """Получить сообщение из очереди."""
        if self._queue_registry is not None:
            return self._queue_registry.receive_from_queue(
                self._process_name, self._queue_type, timeout
            )
        if self._queue is None:
            return None
        try:
            return self._queue.get(timeout=timeout) if timeout > 0 else self._queue.get_nowait()
        except Exception:
            return None

    @property
    def size(self) -> int:
        """Текущий размер очереди."""
        if self._queue is None:
            return 0
        try:
            return self._queue.qsize()
        except (NotImplementedError, OSError):
            return 0

    @property
    def is_full(self) -> bool:
        """Очередь заполнена?"""
        return self._queue.full() if self._queue else False

    @property
    def raw(self) -> Optional[Queue]:
        """Low-level доступ к Queue для продвинутых сценариев."""
        return self._queue

    def __repr__(self) -> str:
        return f"QueueHandle('{self._process_name}', '{self._queue_type}')"


class EventHandle:
    """
    Обёртка над multiprocessing.Event с удобными методами.

    Использование:
        handle.event("stop").set()
        handle.event("stop").wait(timeout=5.0)
    """

    __slots__ = ("_event", "_process_name", "_event_name")

    def __init__(
        self,
        event: Optional[Event],
        process_name: str,
        event_name: str,
    ) -> None:
        self._event = event
        self._process_name = process_name
        self._event_name = event_name

    def set(self) -> None:
        """Установить событие."""
        if self._event is not None:
            self._event.set()

    def clear(self) -> None:
        """Сбросить событие."""
        if self._event is not None:
            self._event.clear()

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Ожидать событие. Возвращает True если событие установлено."""
        if self._event is None:
            return False
        return self._event.wait(timeout=timeout)

    @property
    def is_set(self) -> bool:
        """Событие установлено?"""
        return self._event.is_set() if self._event else False

    @property
    def raw(self) -> Optional[Event]:
        """Low-level доступ к Event."""
        return self._event

    def __repr__(self) -> str:
        return f"EventHandle('{self._process_name}', '{self._event_name}')"


class ProcessHandle:
    """
    Единый chainable доступ к ресурсам зарегистрированного процесса.

    Использование:
        handle = srm.process("worker")
        handle.queue("system").send(msg)
        handle.event("stop").set()
        handle.memory("frame").write(images, index=0)
        handle.status   # → ProcessStatus
        handle.config   # → dict
    """

    __slots__ = ("_name", "_srm")

    def __init__(self, name: str, srm: 'SharedResourcesManager') -> None:
        self._name = name
        self._srm = srm

    @property
    def name(self) -> str:
        """Имя процесса."""
        return self._name

    @property
    def data(self) -> Optional['ProcessData']:
        """ProcessData процесса."""
        return self._srm._process_state_registry.get_process_data(self._name)

    @property
    def status(self) -> Optional['ProcessStatus']:
        """Текущий статус процесса."""
        pd = self.data
        return pd.status if pd else None

    @property
    def config(self) -> Optional[dict]:
        """Конфиг процесса из ConfigStore."""
        return self._srm._config_store.get(self._name)

    @property
    def metadata(self) -> Dict[str, Any]:
        """Метаданные процесса."""
        pd = self.data
        return pd.metadata if pd else {}

    def queue(self, queue_type: str) -> QueueHandle:
        """Получить handle к очереди процесса."""
        pd = self.data
        raw_queue = pd.get_queue(queue_type) if pd else None
        return QueueHandle(
            queue=raw_queue,
            process_name=self._name,
            queue_type=queue_type,
            queue_registry=self._srm._queue_registry,
        )

    def event(self, event_name: str) -> EventHandle:
        """Получить handle к событию процесса."""
        pd = self.data
        raw_event = pd.get_event(event_name) if pd else None
        return EventHandle(
            event=raw_event,
            process_name=self._name,
            event_name=event_name,
        )

    def memory(self, memory_name: str) -> 'MemoryHandle':
        """Получить handle к блоку SharedMemory процесса."""
        from .memory_handle import MemoryHandle
        return MemoryHandle(
            memory_manager=self._srm._memory_manager,
            process_name=self._name,
            memory_name=memory_name,
        )

    def __repr__(self) -> str:
        return f"ProcessHandle('{self._name}')"
```

#### 2.3. Добавить `process()` метод в SRM

**Файл:** `core/shared_resources_manager.py`

**Добавить import** после строки 32:
```python
from ..handles import ProcessHandle
```

**Добавить метод** после блока `reinitialize_in_child()` (после строки ~242), перед Properties:
```python
    # =========================================================================
    # Handle API — единый паттерн доступа к ресурсам
    # =========================================================================

    def process(self, name: str) -> 'ProcessHandle':
        """
        Получить unified handle к ресурсам процесса.

        Использование:
            handle = srm.process("worker")
            handle.queue("system").send(msg)
            handle.event("stop").set()
            handle.memory("frame").write(images, index=0)

        Raises:
            KeyError: если процесс не зарегистрирован.
        """
        if not self._process_state_registry.has_process(name):
            raise KeyError(
                f"Process '{name}' not registered. "
                f"Available: {self._process_state_registry.get_process_names()}"
            )
        return ProcessHandle(name, self)

    def has_process(self, name: str) -> bool:
        """Проверить, зарегистрирован ли процесс."""
        return self._process_state_registry.has_process(name)

    def broadcast(
        self,
        message: Any,
        queue_type: str = "system",
        exclude: Optional[str] = None,
    ) -> int:
        """Разослать сообщение всем процессам. Возвращает количество доставок."""
        return self._queue_registry.broadcast_message(message, queue_type, exclude)
```

#### 2.4. Создать тест: `tests/test_handles.py`

```python
"""Тесты для Handle API — ProcessHandle, QueueHandle, EventHandle."""

import pytest
from multiprocessing import Queue, Event

from ..core.shared_resources_manager import SharedResourcesManager
from ..handles import ProcessHandle, QueueHandle, EventHandle
from ..types import ProcessStatus


BASIC_CONFIG = {
    "queues": {
        "system": {"maxsize": 100},
        "data": {"maxsize": 50},
    },
    "events": ["custom_event"],
}


@pytest.fixture
def srm():
    s = SharedResourcesManager()
    s.initialize()
    s.register_process("worker", BASIC_CONFIG)
    return s


class TestProcessHandle:
    def test_process_returns_handle(self, srm):
        handle = srm.process("worker")
        assert isinstance(handle, ProcessHandle)
        assert handle.name == "worker"

    def test_process_missing_raises_key_error(self, srm):
        with pytest.raises(KeyError, match="not_registered"):
            srm.process("not_registered")

    def test_handle_status(self, srm):
        handle = srm.process("worker")
        assert handle.status == ProcessStatus.INITIALIZING

    def test_handle_config(self, srm):
        handle = srm.process("worker")
        cfg = handle.config
        assert cfg is not None
        assert "queues" in cfg

    def test_handle_data(self, srm):
        handle = srm.process("worker")
        assert handle.data is not None
        assert handle.data.name == "worker"

    def test_handle_metadata(self, srm):
        handle = srm.process("worker")
        assert isinstance(handle.metadata, dict)


class TestQueueHandle:
    def test_send_and_receive(self, srm):
        handle = srm.process("worker")
        qh = handle.queue("system")
        assert qh.send({"cmd": "test"})
        msg = qh.receive(timeout=1.0)
        assert msg == {"cmd": "test"}

    def test_receive_empty_returns_none(self, srm):
        handle = srm.process("worker")
        qh = handle.queue("system")
        assert qh.receive() is None

    def test_size(self, srm):
        handle = srm.process("worker")
        qh = handle.queue("system")
        qh.send("msg1")
        qh.send("msg2")
        assert qh.size >= 2

    def test_missing_queue_send_returns_false(self, srm):
        handle = srm.process("worker")
        qh = handle.queue("nonexistent")
        # send через queue_registry → вернёт False если очереди нет
        assert qh.send("test") is False

    def test_raw_returns_queue(self, srm):
        handle = srm.process("worker")
        qh = handle.queue("system")
        assert isinstance(qh.raw, Queue)

    def test_repr(self, srm):
        handle = srm.process("worker")
        qh = handle.queue("system")
        assert "worker" in repr(qh)
        assert "system" in repr(qh)


class TestEventHandle:
    def test_set_and_is_set(self, srm):
        handle = srm.process("worker")
        eh = handle.event("stop")
        assert not eh.is_set
        eh.set()
        assert eh.is_set

    def test_clear(self, srm):
        handle = srm.process("worker")
        eh = handle.event("stop")
        eh.set()
        eh.clear()
        assert not eh.is_set

    def test_wait_returns_true_when_set(self, srm):
        handle = srm.process("worker")
        eh = handle.event("stop")
        eh.set()
        assert eh.wait(timeout=0.1) is True

    def test_wait_returns_false_on_timeout(self, srm):
        handle = srm.process("worker")
        eh = handle.event("stop")
        assert eh.wait(timeout=0.01) is False

    def test_custom_event(self, srm):
        handle = srm.process("worker")
        eh = handle.event("custom_event")
        assert eh.raw is not None
        eh.set()
        assert eh.is_set

    def test_missing_event_is_safe(self, srm):
        handle = srm.process("worker")
        eh = handle.event("nonexistent")
        assert eh.raw is None
        assert eh.is_set is False
        eh.set()  # no-op, не падает
        assert eh.wait(timeout=0.01) is False

    def test_raw_returns_event(self, srm):
        handle = srm.process("worker")
        eh = handle.event("stop")
        assert isinstance(eh.raw, Event)

    def test_repr(self, srm):
        handle = srm.process("worker")
        eh = handle.event("stop")
        assert "worker" in repr(eh)
        assert "stop" in repr(eh)


class TestSRMHighLevel:
    def test_has_process_true(self, srm):
        assert srm.has_process("worker") is True

    def test_has_process_false(self, srm):
        assert srm.has_process("nonexistent") is False

    def test_broadcast(self, srm):
        srm.register_process("worker2", BASIC_CONFIG)
        sent = srm.broadcast({"cmd": "stop_all"})
        assert sent == 2  # worker + worker2

    def test_broadcast_with_exclude(self, srm):
        srm.register_process("worker2", BASIC_CONFIG)
        sent = srm.broadcast({"cmd": "stop"}, exclude="worker")
        assert sent == 1
```

#### 2.5. Верификация Step 2

```bash
cd Inspector_prototype
python -m pytest multiprocess_framework/modules/shared_resources_module/tests/test_handles.py -v --tb=short
# Ожидание: все новые тесты green
python -m pytest multiprocess_framework/modules/shared_resources_module/tests/ -v --tb=short
# Ожидание: 105 + ~24 новых = ~129 passed
```

---

### Step 3 — Создать `MemoryHandle`

**Задача:** Обёртка для SharedMemory по паттерну Handle, как QueueHandle/EventHandle.

#### 3.1. Создать файл: `handles/memory_handle.py`

```python
"""
MemoryHandle — обёртка над SharedMemory для конкретного блока памяти.

Использование:
    mem = handle.memory("frame")
    idx = mem.find_free_index()
    mem.write(images, index=idx)
    imgs = mem.read(index=0)
"""

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from ..memory.core import MemoryManager


class MemoryHandle:
    """
    Обёртка над MemoryManager для одного блока SharedMemory.

    Привязана к конкретному process_name + memory_name.
    Делегирует вызовы в MemoryManager.
    """

    __slots__ = ("_mm", "_process_name", "_memory_name")

    def __init__(
        self,
        memory_manager: 'MemoryManager',
        process_name: str,
        memory_name: str,
    ) -> None:
        self._mm = memory_manager
        self._process_name = process_name
        self._memory_name = memory_name

    def write(
        self,
        images: 'List[np.ndarray]',
        index: int,
        *,
        pack_fast: bool = True,
    ) -> Optional[str]:
        """Записать изображения в слот. Возвращает shm.name или None."""
        return self._mm.write_images(
            self._process_name, self._memory_name, images, index,
            pack_fast=pack_fast,
        )

    def read(
        self,
        index: int,
        n: int = -1,
        *,
        copy: bool = True,
    ) -> 'Optional[List[np.ndarray]]':
        """Прочитать изображения из слота."""
        return self._mm.read_images(
            self._process_name, self._memory_name, index, n, copy=copy,
        )

    def find_free_index(self) -> Optional[int]:
        """Найти свободный слот."""
        return self._mm.find_free_index(self._process_name, self._memory_name)

    def release(self, index: int) -> None:
        """Освободить слот (обнулить и пометить свободным)."""
        self._mm.release_memory(self._process_name, self._memory_name, index)

    def close(self) -> None:
        """Закрыть и освободить SharedMemory блок."""
        self._mm.close_memory(self._process_name, self._memory_name)

    @property
    def exists(self) -> bool:
        """Проверить, существует ли данный блок памяти."""
        data = self._mm.get_memory_data(self._process_name, self._memory_name)
        return data is not None

    def __repr__(self) -> str:
        return f"MemoryHandle('{self._process_name}', '{self._memory_name}')"
```

#### 3.2. Обновить `handles/__init__.py`

```python
"""Handle API — единый паттерн доступа к ресурсам процесса."""

from .process_handle import ProcessHandle, QueueHandle, EventHandle
from .memory_handle import MemoryHandle

__all__ = ["ProcessHandle", "QueueHandle", "EventHandle", "MemoryHandle"]
```

#### 3.3. Создать тест: `tests/test_memory_handle.py`

> **Важно:** Тесты SharedMemory пропускаются на macOS M1/M2. Используй `@pytest.mark.skipif` как в существующих тестах (`memory/tests/test_platform_ops.py`).

```python
"""Тесты для MemoryHandle."""

import sys
import pytest

from ..core.shared_resources_manager import SharedResourcesManager
from ..handles import MemoryHandle


SKIP_SHM = sys.platform == "darwin"
SKIP_REASON = "SharedMemory unreliable on macOS"

MEMORY_CONFIG = {
    "queues": {"system": {"maxsize": 10}},
    "memory": {
        "names": {"frame": (1, (4, 4, 3), "uint8")},
        "coll": 2,
    },
}


@pytest.fixture
def srm():
    s = SharedResourcesManager()
    s.initialize()
    s.register_process("cam", MEMORY_CONFIG)
    yield s
    s.shutdown()


@pytest.mark.skipif(SKIP_SHM, reason=SKIP_REASON)
class TestMemoryHandle:
    def test_memory_returns_handle(self, srm):
        handle = srm.process("cam")
        mem = handle.memory("frame")
        assert isinstance(mem, MemoryHandle)

    def test_memory_exists(self, srm):
        handle = srm.process("cam")
        assert handle.memory("frame").exists is True
        assert handle.memory("nonexistent").exists is False

    def test_find_free_index(self, srm):
        handle = srm.process("cam")
        idx = handle.memory("frame").find_free_index()
        assert idx is not None
        assert idx == 0

    def test_write_and_read(self, srm):
        import numpy as np
        handle = srm.process("cam")
        mem = handle.memory("frame")
        img = np.zeros((4, 4, 3), dtype=np.uint8)
        img[0, 0, 0] = 42
        result = mem.write([img], index=0)
        assert result is not None

        images = mem.read(index=0)
        assert images is not None
        assert len(images) >= 1
        assert images[0][0, 0, 0] == 42

    def test_release(self, srm):
        handle = srm.process("cam")
        mem = handle.memory("frame")
        mem.release(index=0)  # Не падает

    def test_repr(self, srm):
        mem = srm.process("cam").memory("frame")
        assert "cam" in repr(mem)
        assert "frame" in repr(mem)
```

#### 3.4. Верификация Step 3

```bash
cd Inspector_prototype
python -m pytest multiprocess_framework/modules/shared_resources_module/tests/test_memory_handle.py -v --tb=short
# На macOS: все тесты SKIPPED (ожидаемо)
# На Linux/Windows: все тесты PASSED
python -m pytest multiprocess_framework/modules/shared_resources_module/tests/ -v --tb=short
# Проверить что старые тесты не сломаны
```

---

### Step 4 — Обновить SRM фасад: deprecated properties + высокоуровневые методы

**Задача:** Пометить прямой доступ к менеджерам как deprecated, обновить интерфейсы.

#### 4.1. Файл: `core/shared_resources_manager.py`

**Заменить блок Properties (строки 244-266)** на deprecated-обёртки:

```python
    # =========================================================================
    # Properties — внутренние менеджеры (deprecated, используйте srm.process())
    # =========================================================================

    @property
    def config_store(self) -> ConfigStore:
        """Deprecated. Для конфига используйте srm.process(name).config."""
        return self._config_store

    @property
    def process_state_registry(self) -> ProcessStateRegistry:
        """Deprecated. Для данных используйте srm.process(name).data."""
        return self._process_state_registry

    @property
    def queue_registry(self) -> QueueRegistry:
        """Deprecated. Используйте srm.process(name).queue(type)."""
        return self._queue_registry

    @property
    def event_manager(self) -> EventManager:
        """Deprecated. Используйте srm.process(name).event(name)."""
        return self._event_manager

    @property
    def memory_manager(self) -> MemoryManager:
        """Deprecated. Используйте srm.process(name).memory(name)."""
        return self._memory_manager
```

> **Важно:** НЕ ставим `warnings.warn()` на этом этапе — иначе сломаются все тесты фреймворка. Properties остаются рабочими, но помечены в docstring. Warning добавим когда все потребители перейдут на Handle API (в будущих модулях #9-13).

#### 4.2. Добавить `get_all_statuses()` в SRM

**Файл:** `core/shared_resources_manager.py`, после метода `broadcast()`:

```python
    def get_all_statuses(self) -> Dict[str, 'ProcessStatus']:
        """Получить статусы всех процессов."""
        return {
            name: pd.status
            for name, pd in self._process_state_registry.get_all_process_data().items()
        }
```

#### 4.3. Верификация Step 4

```bash
cd Inspector_prototype
python -m pytest multiprocess_framework/modules/shared_resources_module/tests/ -v --tb=short
# Все тесты green — properties всё ещё работают
```

---

### Step 5 — Убрать тройное хранение очередей

**Задача:** PSR (ProcessData._queues_dict) — единственный source of truth. Удалить `QueueRegistry.registered_queues`.

#### 5.1. Файл: `queues/core/manager.py`

**Удалить строку 55:**
```python
self.registered_queues: Dict[str, Dict[str, Queue]] = {}
```

**Заменить на пустой комментарий** (чтобы не сломать нумерацию):
```python
# Queue refs хранятся в PSR (ProcessData._queues_dict) — единственный source of truth
```

**Обновить метод `register_process_queues` (строки 104-123):**
```python
    def register_process_queues(
        self,
        process_name: str,
        queues: Dict[str, Queue],
    ) -> bool:
        """Зарегистрировать очереди в PSR (единственный source of truth)."""
        try:
            self._stats["registered"] += len(queues)
            if self._process_state_registry:
                for queue_type, queue in queues.items():
                    self._process_state_registry.add_queue(process_name, queue_type, queue)
            self._log_debug(f"Registered {len(queues)} queues for '{process_name}'")
            return True
        except Exception as e:
            self._log_error(f"register_process_queues('{process_name}') failed: {e}")
            self._stats["errors"] += 1
            return False
```

**Обновить `get_queue` (строки 136-142):**
```python
    def get_queue(self, process_name: str, queue_type: str) -> Optional[Queue]:
        """Получить очередь из PSR."""
        if self._process_state_registry:
            return self._process_state_registry.get_queue(process_name, queue_type)
        return None
```

**Обновить `get_process_queues` (строка 144-145):**
```python
    def get_process_queues(self, process_name: str) -> Dict[str, Queue]:
        """Получить все очереди процесса из PSR."""
        if self._process_state_registry:
            pd = self._process_state_registry.get_process_data(process_name)
            if pd:
                return dict(pd.queues.items())
        return {}
```

**Обновить `broadcast_message` (строки 188-200):**
```python
    def broadcast_message(
        self,
        message: Any,
        queue_type: str = "system",
        exclude_process: Optional[str] = None,
    ) -> int:
        """Разослать сообщение всем процессам через PSR."""
        if not self._process_state_registry:
            return 0
        sent = 0
        for process_name in list(self._process_state_registry.get_process_names()):
            if exclude_process and process_name == exclude_process:
                continue
            if self.send_to_queue(process_name, queue_type, message):
                sent += 1
        return sent
```

**Обновить `get_queue_sizes` (строки 202-214):**
```python
    def get_queue_sizes(self) -> Dict[str, Dict[str, int]]:
        sizes: Dict[str, Dict[str, int]] = {}
        if not self._process_state_registry:
            return sizes
        for process_name in self._process_state_registry.get_process_names():
            pd = self._process_state_registry.get_process_data(process_name)
            if not pd:
                continue
            sizes[process_name] = {}
            for queue_type in pd.queues:
                queue = pd.get_queue(queue_type)
                if queue is None:
                    continue
                try:
                    sizes[process_name][queue_type] = queue.qsize()
                except (NotImplementedError, OSError, AttributeError):
                    sizes[process_name][queue_type] = 0
        return sizes
```

**Обновить `remove_process_queues` (строки 216-222):**
```python
    def remove_process_queues(self, process_name: str) -> bool:
        """Удалить процесс из PSR (unregister)."""
        if self._process_state_registry and self._process_state_registry.has_process(process_name):
            # Не удаляем из PSR — это задача SRM/PSR
            # Только сбрасываем статистику
            self._stats["removed"] += 1
            return True
        return False
```

**Обновить `get_registered_processes` (строки 224-225):**
```python
    def get_registered_processes(self) -> List[str]:
        if self._process_state_registry:
            return self._process_state_registry.get_process_names()
        return []
```

**Обновить `shutdown` (строки 72-80):**
```python
    def shutdown(self) -> bool:
        try:
            self.is_initialized = False
            self._log_info("QueueRegistry shutdown completed")
            return True
        except Exception as e:
            self._log_error(f"QueueRegistry.shutdown() failed: {e}")
            return False
```

**Обновить `get_stats` (строки 271-279):**
```python
    def get_stats(self) -> Dict[str, Any]:
        process_names = self.get_registered_processes()
        total = sum(
            len(list(self._process_state_registry.get_process_data(p).queues))
            for p in process_names
            if self._process_state_registry and self._process_state_registry.get_process_data(p)
        ) if self._process_state_registry else 0
        queue_stats = {
            **self._stats,
            "total_queues": total,
            "processes_count": len(process_names),
            "processes": process_names,
        }
        return self._merge_stats("queues", queue_stats)
```

#### 5.2. Обновить тест: `tests/test_queue_registry.py`

Убрать все обращения к `qr.registered_queues`. Заменить на проверки через PSR.

**Пример замены:**
```python
# Было:
assert "p1" in qr.registered_queues
# Стало:
assert qr.get_queue("p1", "system") is not None
```

#### 5.3. Верификация Step 5

```bash
cd Inspector_prototype
python -m pytest multiprocess_framework/modules/shared_resources_module/tests/test_queue_registry.py -v --tb=short
python -m pytest multiprocess_framework/modules/shared_resources_module/tests/ -v --tb=short
# Все тесты green
```

---

### Step 6 — MemoryAccessStatus enum + validation

**Задача:** Вместо bool возвращать конкретную причину ошибки.

#### 6.1. Файл: `types/types.py`

**Добавить в конец файла:**
```python
class MemoryAccessStatus(Enum):
    """Результат валидации доступа к SharedMemory."""
    OK = "ok"
    NO_DATA = "no_data"
    INVALID_INDEX = "invalid_index"
    INDEX_OUT_OF_RANGE = "index_out_of_range"
    HANDLE_MISSING = "handle_missing"
    EXCEEDS_MAX_IMAGES = "exceeds_max_images"
    PARAM_MISSING = "param_missing"
```

#### 6.2. Файл: `memory/validation/access.py`

**Полная замена файла:**
```python
"""
Валидация доступа к SharedMemory и операций write/read.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from ...types.types import MemoryAccessStatus


def validate_memory_access(
    memory_data: Optional[Dict],
    shm_name: str,
    index: int,
) -> MemoryAccessStatus:
    """
    Проверить доступ к слоту памяти.

    Returns:
        MemoryAccessStatus.OK если доступ валиден, иначе конкретная причина.
    """
    if not memory_data:
        return MemoryAccessStatus.NO_DATA
    if index < 0:
        return MemoryAccessStatus.INVALID_INDEX
    coll = memory_data.get("coll", {})
    if shm_name not in coll or index >= coll[shm_name]:
        return MemoryAccessStatus.INDEX_OUT_OF_RANGE
    handles = memory_data.get("handles")
    if handles is None or index >= len(handles) or handles[index] is None:
        return MemoryAccessStatus.HANDLE_MISSING
    return MemoryAccessStatus.OK


def validate_write_operation(
    memory_data: Optional[Dict],
    shm_name: str,
    index: int,
    num_images: int,
) -> MemoryAccessStatus:
    """
    Проверить возможность записи num_images изображений в слот.
    """
    if not memory_data:
        return MemoryAccessStatus.NO_DATA
    access = validate_memory_access(memory_data, shm_name, index)
    if access != MemoryAccessStatus.OK:
        return access
    params = memory_data.get("params", {})
    if shm_name not in params:
        return MemoryAccessStatus.PARAM_MISSING
    max_images = params[shm_name][0]
    if num_images > max_images:
        return MemoryAccessStatus.EXCEEDS_MAX_IMAGES
    return MemoryAccessStatus.OK


def clear_memory_slot(
    handles: Optional[List[Any]],
    index: int,
) -> None:
    """Обнулить буфер слота памяти."""
    if not handles or index >= len(handles) or handles[index] is None:
        return
    shm = handles[index]
    try:
        shm.buf[:] = b"\x00" * shm.size
    except Exception:
        pass
```

#### 6.3. Файл: `memory/core/manager.py`

**Обновить 4 call site:**

**write_images (строки 277-282)** — заменить:
```python
        if not val.validate_memory_access(memory_data, shm_name, index):
            self._warn_access(process_name, shm_name, index, "not initialized or invalid index")
            return None
        if not val.validate_write_operation(memory_data, shm_name, index, len(images)):
            self._log_warning(f"Invalid write: index {index} or too many images")
            return None
```
На:
```python
        from ..validation.access import MemoryAccessStatus  # если не импортирован сверху
        # Или импортировать в начале файла: from ...types.types import MemoryAccessStatus

        access = val.validate_memory_access(memory_data, shm_name, index)
        if access != MemoryAccessStatus.OK:
            self._log_warning(
                f"Memory access failed for '{process_name}'/'{shm_name}'[{index}]: {access.value}"
            )
            return None
        write_status = val.validate_write_operation(memory_data, shm_name, index, len(images))
        if write_status != MemoryAccessStatus.OK:
            self._log_warning(
                f"Write validation failed for '{process_name}'/'{shm_name}'[{index}]: {write_status.value}"
            )
            return None
```

> **Важно:** импортировать `MemoryAccessStatus` в начале файла `memory/core/manager.py`:
> ```python
> from ...types.types import MemoryAccessStatus
> ```

**read_images (строка 312)** — заменить:
```python
        if not val.validate_memory_access(memory_data, shm_name, index):
            return None
```
На:
```python
        access = val.validate_memory_access(memory_data, shm_name, index)
        if access != MemoryAccessStatus.OK:
            self._log_warning(
                f"Memory read failed for '{process_name}'/'{shm_name}'[{index}]: {access.value}"
            )
            return None
```

**Удалить метод `_warn_access`** (строки 377-385) — больше не нужен, заменён inline-логированием.

**Удалить print()** на строках 188-191 и 294-297 — заменены на `_log_warning`/`_log_error`.

#### 6.4. Обновить тесты: `memory/tests/test_validation.py`

Обновить существующие тесты — вместо `True/False` проверять конкретные статусы:
```python
from ...types.types import MemoryAccessStatus

def test_none_memory_data_returns_no_data(self):
    assert validate_memory_access(None, "x", 0) == MemoryAccessStatus.NO_DATA

def test_valid_access_returns_ok(self):
    assert validate_memory_access(valid_data, "x", 0) == MemoryAccessStatus.OK

def test_invalid_index_returns_invalid_index(self):
    assert validate_memory_access(valid_data, "x", -1) == MemoryAccessStatus.INVALID_INDEX
```

#### 6.5. Верификация Step 6

```bash
cd Inspector_prototype
python -m pytest multiprocess_framework/modules/shared_resources_module/memory/tests/test_validation.py -v --tb=short
python -m pytest multiprocess_framework/modules/shared_resources_module/tests/ -v --tb=short
```

---

### Step 7 — EventManager.wait_for_event() fix + silent exceptions

**Задача:** Исправить race condition и заменить silent `except: pass` на логирование.

#### 7.1. Файл: `events/core/manager.py`

**Добавить import в начало файла (после строки 5):**
```python
from queue import Empty
```

**Заменить метод `wait_for_event` (строки 166-185):**
```python
    def wait_for_event(
        self,
        event_type: Optional[EventType] = None,
        timeout: float = 1.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Ожидать событие определённого типа с таймаутом.

        Non-matching события сохраняются и возвращаются в очередь после завершения.
        """
        if self._event_queue is None:
            return None

        deadline = time.time() + timeout
        deferred: List[Dict[str, Any]] = []
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                try:
                    event_data = self._event_queue.get(
                        timeout=min(remaining, 0.5)
                    )
                except Empty:
                    continue
                if event_type is None or event_data.get("event_type") == event_type.value:
                    return event_data
                deferred.append(event_data)
        finally:
            for evt in deferred:
                self._event_queue.put(evt)
```

#### 7.2. Файл: `state/process_state_registry.py`

**Заменить строки 54-55** в методе `_emit`:
```python
        except Exception:
            pass
```
На:
```python
        except Exception as e:
            self._log("warning", f"PSR._emit('{event_type_name}') failed: {e}")
```

#### 7.3. Файл: `memory/core/manager.py`

**Удалить все `print()` вызовы** (строки 188-191, 294-297, 382-385).

Конкретно:

**В `_create_with_psr` (строки 188-191)** — удалить:
```python
                print(
                    f"[MemoryManager] ERROR: Cannot create SharedMemory for '{name}'",
                    flush=True,
                )
```

**В `write_images` (строки 294-297)** — удалить:
```python
            print(
                f"[MemoryManager] ERROR: write_images failed for '{process_name}'/'{shm_name}': {e}",
                flush=True,
            )
```

**В `_warn_access` (строки 382-385)** — метод удалён целиком в Step 6.3.

#### 7.4. Верификация Step 7

```bash
cd Inspector_prototype
python -m pytest multiprocess_framework/modules/shared_resources_module/tests/ -v --tb=short
python -m pytest multiprocess_framework/modules/shared_resources_module/memory/tests/ -v --tb=short
# Все тесты green
```

---

### Step 8 — Обновить interfaces.py + __init__.py

#### 8.1. Файл: `core/interfaces.py`

**Добавить новые абстрактные методы** в `ISharedResourcesManager` (после `get_process_names`):

```python
    @abstractmethod
    def process(self, name: str) -> Any:
        """Получить ProcessHandle — единый доступ к ресурсам процесса."""

    @abstractmethod
    def has_process(self, name: str) -> bool:
        """Проверить, зарегистрирован ли процесс."""

    @abstractmethod
    def broadcast(self, message: Any, queue_type: str = "system", exclude: Optional[str] = None) -> int:
        """Разослать сообщение всем процессам."""

    @abstractmethod
    def get_all_statuses(self) -> Dict[str, Any]:
        """Получить статусы всех процессов."""
```

#### 8.2. Файл: `__init__.py`

**Добавить импорт Handle API** (после строки 27):
```python
# Handle API
from .handles import ProcessHandle, QueueHandle, EventHandle, MemoryHandle
```

**Добавить импорт MemoryAccessStatus** (после строки 33):
```python
from .types.types import MemoryAccessStatus
```

**Обновить `__all__`:**
```python
__all__ = [
    # Основной фасад
    "SharedResourcesManager",

    # Handle API (новый)
    "ProcessHandle",
    "QueueHandle",
    "EventHandle",
    "MemoryHandle",

    # Компоненты (deprecated — используйте Handle API)
    "EventManager",
    "QueueRegistry",
    "MemoryManager",
    "ConfigStore",
    "SharedResourcesManagerConfig",
    "DataSchemaAdapter",

    # Данные процессов
    "ProcessData",
    "ProcessDataKeys",
    "QueuesProxy",
    "EventsProxy",
    "ProcessStateRegistry",

    # Типы
    "ProcessStatus",
    "ResourceType",
    "EventType",
    "MemoryAccessStatus",
    "ProcessDataDict",
    "QueueConfigDict",
    "MemoryConfigDict",

    # Интерфейсы
    "IConfigStore",
    "IQueueRegistry",
    "IEventManager",
    "IMemoryManager",
    "IProcessStateRegistry",
    "ISharedResourcesManager",
]
```

#### 8.3. Верификация Step 8

```bash
cd Inspector_prototype
python -c "from multiprocess_framework.modules.shared_resources_module import ProcessHandle, QueueHandle, EventHandle, MemoryHandle, MemoryAccessStatus; print('OK')"
python -m pytest multiprocess_framework/modules/shared_resources_module/tests/ -v --tb=short
```

---

### Step 9 — Документация + ADR

#### 9.1. Создать/обновить `DECISIONS.md`

Создать файл `DECISIONS.md` в корне модуля (если нет) или дополнить:

```markdown
# DECISIONS — shared_resources_module

Локальные архитектурные решения модуля.  
Ссылка на глобальные: [../../DECISIONS.md](../../DECISIONS.md)

---

### ADR-SRM-001: Удалён legacy API v1
**Дата:** 2026-04-09  
**Решение:** Удалены методы register_process_state, register_process_with_config,
update_process_state, get_process_state, get_all_process_states, add_shared_resource,
get_shared_resource, get_data_manager, data_manager.  
**Причина:** 0 внешних потребителей (подтверждено grep). Каноничный API: register_process() (ADR-018).

### ADR-SRM-002: ProcessHandle как единый паттерн доступа
**Дата:** 2026-04-09  
**Решение:** Введён ProcessHandle + QueueHandle + EventHandle + MemoryHandle.  
**Причина:** 3 пути доступа к очередям, отсутствие MemoryProxy. Handle унифицирует: `srm.process(name).queue(type).send(msg)`.

### ADR-SRM-003: PSR — единственный source of truth для очередей
**Дата:** 2026-04-09  
**Решение:** Удалён QueueRegistry.registered_queues cache. Все lookup идут через PSR.  
**Причина:** Тройное хранение Queue refs приводило к потенциальному рассогласованию.

### ADR-SRM-004: MemoryAccessStatus enum вместо bool
**Дата:** 2026-04-09  
**Решение:** validate_memory_access() и validate_write_operation() возвращают MemoryAccessStatus enum.  
**Причина:** bool не давал причины ошибки. Enum включает: NO_DATA, INVALID_INDEX, INDEX_OUT_OF_RANGE, HANDLE_MISSING, EXCEEDS_MAX_IMAGES.

### ADR-SRM-005: Менеджеры скрыты за фасадом
**Дата:** 2026-04-09  
**Решение:** Properties config_store, process_state_registry, queue_registry, event_manager, memory_manager помечены как deprecated. Доступ через srm.process(name).  
**Причина:** Прямой доступ к менеджерам нарушал инкапсуляцию фасада.
```

#### 9.2. Обновить `STATUS.md`

```markdown
# STATUS — shared_resources_module

**Текущая стадия:** ✅ Refactoring v4.1 завершён (2026-04-09)

## Метрики after:
- Файлов: ~45 (было 41, +4 handles)
- LOC: ~3,500 (было 3,221, +350 handles, -140 legacy)
- Тестов: ~155 (было 132, +24 handles)
- CC max: 8 (было 10, улучшен QueueRegistry)

## Что изменилось:
- ✅ Handle API (ProcessHandle, QueueHandle, EventHandle, MemoryHandle)
- ✅ Удалён legacy API (0 потребителей)
- ✅ PSR — единственный source of truth для Queue
- ✅ MemoryAccessStatus enum вместо bool
- ✅ Fix race condition в wait_for_event()
- ✅ Убраны print() fallbacks → logging
- ✅ PSR._emit() логирование вместо silent pass
```

#### 9.3. Обновить README.md

**Добавить раздел "Quick Start" с Handle API:**

```markdown
## Quick Start (Handle API)

```python
srm = SharedResourcesManager()
srm.initialize()
srm.register_process("worker", {
    "queues": {"system": {"maxsize": 100}},
    "events": ["custom_event"],
})

# Единый паттерн доступа:
handle = srm.process("worker")

# Очереди
handle.queue("system").send({"cmd": "start"})
msg = handle.queue("system").receive(timeout=1.0)

# События
handle.event("stop").set()
handle.event("stop").wait(timeout=5.0)

# Память (SharedMemory)
handle.memory("frame").write(images, index=0)
imgs = handle.memory("frame").read(index=0)

# Высокоуровневые операции
srm.broadcast({"cmd": "stop_all"})
srm.has_process("worker")  # → True
srm.get_all_statuses()     # → {"worker": ProcessStatus.INITIALIZING}
```
```

#### 9.4. Обновить `plans/refactoring/00_overview.md`

Найти строку модуля #8 и обновить статус на ✅ DONE.

#### 9.5. Верификация Step 9

```bash
cd Inspector_prototype
python -m pytest multiprocess_framework/modules/shared_resources_module/tests/ -v --tb=short
python -m pytest multiprocess_framework/modules/shared_resources_module/memory/tests/ -v --tb=short
# Финальный полный прогон:
python scripts/run_framework_tests.py
python scripts/validate.py
```

---

## 4. Порядок зависимостей (схема)

```
Step 0 (baseline) ✅
  ↓
Step 1 (удалить legacy) — самостоятельный
  ↓
Step 2 (ProcessHandle + QueueHandle + EventHandle) ←── ядро
  ↓
Step 3 (MemoryHandle) — зависит от Step 2
  ↓
Step 4 (обновить SRM фасад) — зависит от Step 2, 3
  ↓
Step 5 (PSR source of truth) ─┐
Step 6 (MemoryAccessStatus)   ├── параллельно, независимы
Step 7 (wait_for_event fix)   ─┘
  ↓
Step 8 (interfaces + exports) — после всех code changes
  ↓
Step 9 (документация + ADR) — в конце
```

---

## 5. Чеклист для ревьюера (Claude Opus)

После реализации Composer v2, ревьюер проверяет:

- [ ] **Step 1:** Legacy методы удалены, `shared_resources` dict удалён, тесты обновлены
- [ ] **Step 2:** `handles/process_handle.py` создан, `ProcessHandle.queue()` → `QueueHandle`, `.event()` → `EventHandle`
- [ ] **Step 2:** `srm.process("name")` работает, `KeyError` для несуществующего процесса
- [ ] **Step 2:** `srm.has_process()`, `srm.broadcast()` работают
- [ ] **Step 3:** `handles/memory_handle.py` создан, `MemoryHandle.write/read/find_free_index/release` работают
- [ ] **Step 4:** Properties менеджеров помечены deprecated в docstring
- [ ] **Step 5:** `QueueRegistry.registered_queues` удалён, все lookup через PSR
- [ ] **Step 6:** `MemoryAccessStatus` enum добавлен, `validate_memory_access()` возвращает enum
- [ ] **Step 7:** `wait_for_event()` использует deferred list (не put-back в цикле)
- [ ] **Step 7:** `PSR._emit()` логирует ошибки вместо `except: pass`
- [ ] **Step 7:** Все `print()` в memory/core/manager.py удалены
- [ ] **Step 8:** `__init__.py` экспортирует Handle классы и `MemoryAccessStatus`
- [ ] **Step 8:** `ISharedResourcesManager` содержит `process()`, `has_process()`, `broadcast()`, `get_all_statuses()`
- [ ] **Step 9:** `DECISIONS.md` содержит ADR-SRM-001..005
- [ ] **Тесты:** Все тесты green (`pytest shared_resources_module/tests/ -v`)
- [ ] **Pickle:** `pickle.dumps(srm) → loads → reinitialize_in_child()` работает
- [ ] **Нет регрессий:** `python scripts/run_framework_tests.py` и `python scripts/validate.py` green

---

## 6. Оценка влияния

| Фаза | Steps | Файлов | LOC delta | Риск |
|------|-------|--------|-----------|------|
| A: Подготовка | 0-1 | 3 | -60 | Низкий |
| B: Handle API | 2-4 | 7 (+3 новых) | +350 | **Средний** |
| C: Внутренние | 5-7 | 4 | +30/-80 | Средний |
| D: Интерфейсы | 8-9 | 6 | +100 (docs) | Низкий |
| **Итого** | 0-9 | **~15** | **+360 code, -140 legacy** | Средний |

## 7. Оценка качества

| Критерий | Before | After |
|----------|--------|-------|
| API удобство | 5/10 | **9/10** |
| Инкапсуляция | 4/10 | **8/10** |
| Консистентность | 5/10 | **9/10** |
| Чистота кода | 6/10 | **8/10** |
| Расширяемость | 5/10 | **8/10** |
| **Итого** | **6.1/10** | **8.5/10** |
