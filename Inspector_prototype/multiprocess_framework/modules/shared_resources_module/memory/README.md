# memory — SharedMemory для изображений

## Назначение

Подмодуль управления разделяемой памятью (SharedMemory) для передачи изображений между процессами. Pickle-safe паттерн (ADR-019): в ProcessData хранятся только имена shm-блоков; handles пересоздаются в дочерних процессах через `reinitialize_handles()`.

## Импорты

```python
from shared_resources_module.memory import MemoryManager
# или
from shared_resources_module.memory.core import MemoryManager
```

## Точки входа

| Класс/функция | Метод | Описание |
|---------------|-------|----------|
| MemoryManager | `initialize()` | Инициализация |
| MemoryManager | `shutdown()` | Завершение работы, unlink (owner) |
| MemoryManager | `create_memory_dict(process_name, memory_names, coll)` | Создать блоки SharedMemory |
| MemoryManager | `write_images(process_name, shm_name, images, index)` | Записать изображения |
| MemoryManager | `read_images(process_name, shm_name, index, n)` | Прочитать изображения |
| MemoryManager | `reinitialize_handles()` | Открыть shm по именам (consumer) |

## Зависимости

- **Зависит от:** `base_manager`, `shared_resources_module.core.interfaces`
- **Используется в:** `SharedResourcesManager`, `CameraProcess`, `ProcessorProcess`, `RendererProcess`

## Пример

```python
from shared_resources_module.memory import MemoryManager
import numpy as np

mm = MemoryManager()
mm.initialize()

# Создать блок: 2 изображения, 480x640x3, uint8, 2 слота (coll=2)
memory_names = {"camera_frame": (2, (480, 640, 3), np.uint8)}
mm.create_memory_dict("camera", memory_names, coll=2)

# Записать
idx = mm.find_free_index("camera", "camera_frame")
img = np.zeros((480, 640, 3), dtype=np.uint8)
mm.write_images("camera", "camera_frame", [img], index=idx)

# Прочитать
frames = mm.read_images("camera", "camera_frame", index=idx)

mm.shutdown()
```

## Формат буфера

```
[4 bytes: num_images (uint32)]
[per-image: 12 bytes (h,w,c uint32) + 1 byte (dtype char) + payload + padding]
```

Каждый слот изображения имеет фиксированный размер `max_h * max_w * max_c * itemsize` для быстрого доступа по индексу.

## Режимы скорости (pack/unpack)

| Параметр | По умолчанию | Описание |
|----------|--------------|----------|
| `write_images(..., pack_fast=True)` | True | np.copyto — ~2× быстрее записи |
| `read_images(..., copy=True)` | True | Копия — безопасно. copy=False — view, ~2× быстрее, данные до следующей записи |

Подробнее: [docs/FORMATS.md](docs/FORMATS.md)

## Платформенные заметки

| Платформа | Приоритет | Особенности |
|-----------|-----------|-------------|
| **Windows** | 1 | `unlink()` — no-op; память освобождается при close последнего handle |
| **Linux** | 2 | POSIX shm; stale cleanup перед create; unlink при shutdown |
| **macOS** | dev | Аналогично Linux; на M1/M2 возможны баги (cpython#117262) |

Owner process (ProcessManager): `create=True`, `unlink()` при shutdown.
Consumer process: `create=False`, `close()` при shutdown.

## Паттерн get_stats (пример для queues, events)

MemoryManager использует `ManagerStatsMixin` из `shared_resources_module.mixins`:

```python
class MemoryManager(BaseManager, ObservableMixin, IMemoryManager, ManagerStatsMixin):
    def get_stats(self) -> Dict[str, Any]:
        mem_stats = {
            **self._stats,
            "processes_with_handles": len(self._local_handles),
            "is_owner": self._is_owner,
        }
        return self._merge_stats("memory", mem_stats)
```

Для queues/events: наследовать `ManagerStatsMixin`, вызывать `_merge_stats("queues", ...)` или `_merge_stats("events", ...)`.

## Структура модуля

```
memory/
├── __init__.py           # Публичный API: MemoryManager
├── interfaces.py         # Re-export IMemoryManager
├── core/
│   ├── __init__.py       # MemoryManager, _MemoryMeta
│   ├── manager.py        # Оркестратор
│   └── types.py          # _MemoryMeta
├── format/
│   ├── __init__.py
│   └── buffer.py         # pack/unpack, calculate_buffer_size
├── platform/
│   ├── __init__.py
│   └── shm.py            # create_shm_block, close_shm, is_posix
├── validation/
│   ├── __init__.py
│   └── access.py         # validate_memory_access, clear_memory_slot
├── docs/
│   └── FORMATS.md
├── tests/
├── README.md
└── STATUS.md
```

## Связь с другими модулями

```
memory
    │
    ├── использует → base_manager (BaseManager, ObservableMixin)
    ├── использует → shared_resources_module.core.interfaces (IMemoryManager)
    ├── использует → shared_resources_module.mixins (ManagerStatsMixin)
    ├── использует → shared_resources_module.state (ProcessStateRegistry)
    │
    └── используется в → SharedResourcesManager
    └── используется в → CameraProcess, ProcessorProcess, RendererProcess
```
