# Stage 3: Config-driven SharedMemory

## Цель

Перевести создание SharedMemory с жёстко заданных имён на конфигурацию через `config["memory"]`, чтобы имена и параметры задавались в `CameraConfig` и `RendererConfig`, а не в коде процессов.

## Изменения

### 1. Конфиги

**`configs/camera_config.py`** — в `build()` добавлена секция `memory`:

```python
def build(self) -> dict:
    d = super().build()
    d["memory"] = {
        "names": self.memory_names,
        "coll": self.memory_coll,
    }
    return d
```

**`configs/renderer_config.py`** — аналогично:

```python
def build(self) -> dict:
    d = super().build()
    d["memory"] = {
        "names": self.memory_names,
        "coll": self.memory_coll,
    }
    return d
```

### 2. Процессы

**`processes/camera_process.py`** — SharedMemory создаётся из `self.get_config("memory")`:

- Если `memory_cfg` задан: используются `names` и `coll` из конфига
- Если нет: fallback на жёстко заданные значения (`["camera_frame"], {"camera_frame": {...}}`)

**`processes/renderer_process.py`** — то же самое:

- `memory_cfg` из `self.get_config("memory")`
- Fallback: `["camera_frame"], {"camera_frame": {...}}`

### 3. Важно

SharedMemory **создаётся в процессе-владельце** (Camera, Renderer), а не в ProcessManager, потому что:

- У каждого процесса свой `SharedResourcesManager` (SRM)
- Регистрация памяти идёт в SRM процесса
- ProcessManager не имеет доступа к SRM дочерних процессов

Поэтому `memory` в конфиге — это параметры для создания памяти внутри процесса, а не предварительная регистрация в родителе.

## Формат `memory` в конфиге

```python
{
    "names": ["camera_frame"],  # список имён блоков
    "coll": {                   # коллекция описаний блоков
        "camera_frame": {
            "shape": (480, 640, 3),
            "dtype": "uint8",
            "offset": 0,
        }
    }
}
```

Структура совместима с `shm_utils.create_shared_memory()` и `MemoryManager.create_memory()`.

## Результат

- Имена и параметры SharedMemory задаются в конфигах
- Процессы читают конфиг через `get_config("memory")`
- Сохранён fallback на старые значения для обратной совместимости
