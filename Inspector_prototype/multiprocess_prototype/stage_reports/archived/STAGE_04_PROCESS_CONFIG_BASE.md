# Stage 4: Упрощение конфигов — базовый ProcessConfigBase

## Цель

Устранить дублирование в конфигах процессов: общая структура `proc_dict` (class, queues, priority, workers, config, managers) вынесена в базовый класс `ProcessConfigBase`.

## Изменения

### 1. Новый файл `configs/base_config.py`

```python
class ProcessConfigBase(SchemaBase):
    process_name: str = "base"

    def _build_proc_dict(
        self,
        class_path: str,
        *,
        queues: Optional[Dict[str, Any]] = None,
        priority: str = "normal",
        memory: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """Собрать общую структуру proc_dict для add_process()."""
        # class, queues, priority, workers, config, managers
        # + memory при необходимости
```

### 2. Рефакторинг конфигов

Все конфиги наследуют `ProcessConfigBase` вместо `SchemaBase`:

| Конфиг | class_path | priority | queues | memory |
|--------|------------|----------|--------|--------|
| CameraConfig | camera_process.CameraProcess | high | default | camera_frame |
| ProcessorConfig | processor_process.ProcessorProcess | high | default | — |
| RendererConfig | renderer_process.RendererProcess | normal | default | rendered_frame |
| GuiConfig | gui_process.GuiProcess | normal | default | — |
| RobotConfig | robot_simulator_process.RobotSimulatorProcess | low | 50/20 | — |

### 3. Пример использования

**До:**
```python
def build(self) -> tuple[str, dict]:
    from multiprocess_prototype.configs.app_config import get_default_managers_config
    return (self.process_name, {
        "class": "multiprocess_prototype.processes.processor_process.ProcessorProcess",
        "queues": {"system": {"maxsize": 100}, "data": {"maxsize": 50}},
        "priority": "high",
        "workers": {},
        "config": self.model_dump(),
        "managers": get_default_managers_config(),
    })
```

**После:**
```python
def build(self) -> tuple[str, dict]:
    proc_dict = self._build_proc_dict(
        "multiprocess_prototype.processes.processor_process.ProcessorProcess",
        priority="high",
    )
    return (self.process_name, proc_dict)
```

### 4. Дефолтные значения

- `queues`: `{"system": {"maxsize": 100}, "data": {"maxsize": 50}}`
- `priority`: `"normal"`
- RobotConfig переопределяет queues: `50/20`, priority: `"low"`

## Результат

- Убрано дублирование `get_default_managers_config()` и общей структуры
- Добавление нового процесса — только `class_path`, `priority`, опционально `memory`/`queues`
- Единая точка изменения дефолтов — `ProcessConfigBase._build_proc_dict()`
