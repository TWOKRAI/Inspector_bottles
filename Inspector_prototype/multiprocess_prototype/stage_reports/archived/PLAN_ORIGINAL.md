# План реализации тестового приложения Inspector Prototype

**Версия:** 1.0  
**Дата:** 2026-03-15  
**Цель:** Полнофункциональный прототип из 5 процессов, использующий все ключевые механизмы Multiprocess Framework v2.0  
**Исполнитель:** AI-агент (Sonnet 4.6), следующий этапам пошагово

---

## Оглавление

1. [Обзор архитектуры](#1-обзор-архитектуры)
2. [Структура проекта](#2-структура-проекта)
3. [Этап 0: Подготовка инфраструктуры](#3-этап-0-подготовка-инфраструктуры)
4. [Этап 1: CameraProcess](#4-этап-1-cameraprocess)
5. [Этап 2: ProcessorProcess](#5-этап-2-processorprocess)
6. [Этап 3: RendererProcess](#6-этап-3-rendererprocess)
7. [Этап 4: RobotSimulatorProcess](#7-этап-4-robotsimulatorprocess)
8. [Этап 5: GuiProcess (PyQt)](#8-этап-5-guiprocess-pyqt)
9. [Этап 6: main.py и интеграция](#9-этап-6-mainpy-и-интеграция)
10. [Этап 7: Обратная связь и статистика](#10-этап-7-обратная-связь-и-статистика)
11. [Этап 8: Тестирование и отладка](#11-этап-8-тестирование-и-отладка)
12. [Схемы взаимодействия](#12-схемы-взаимодействия)
13. [Оценка и рекомендации](#13-оценка-и-рекомендации)

---

## 1. Обзор архитектуры

### 1.1 Пять процессов и их роли

```
┌─────────────────────────────────────────────────────────────────┐
│                    ProcessManagerProcess                         │
│                    (создаётся фреймворком)                       │
└───────┬──────┬──────┬──────┬──────┬─────────────────────────────┘
        │      │      │      │      │
   ┌────▼──┐┌──▼───┐┌─▼────┐┌▼─────┐┌▼────┐
   │Camera ││Proc- ││Rend- ││Robot ││ GUI │
   │Process││essor ││erer  ││Simul.││Proc.│
   └───┬───┘└──┬───┘└──┬───┘└──┬───┘└──┬──┘
       │       │       │       │       │
       │  shared memory │       │       │
       ├───────►────────┤       │       │
       │  DATA msg      │       │       │
       ├───────►────────┤       │       │
       │       │ DATA   │       │       │
       │       ├────────►       │       │
       │       │        │ CMD   │       │
       │       │        ├───────►       │
       │       │        │ DATA  │       │
       │       │        ├───────────────►
       │  CMD  │        │       │       │
       ◄───────────────────────────────┤
       │       │        │       │       │
```

### 1.2 Таблица процессов

| Процесс | Класс | Воркеры | Команды | Shared Memory |
|---------|-------|---------|---------|---------------|
| **camera** | `CameraProcess` | `capture_worker` (LOOP) | `start`, `stop`, `set_fps`, `set_resolution` | owner: `camera_frame` |
| **processor** | `ProcessorProcess` | `processing_worker` (LOOP) | `set_threshold`, `set_min_area` | consumer: `camera_frame` |
| **renderer** | `RendererProcess` | `render_worker` (LOOP) | `set_output_dir` | consumer: `camera_frame`, owner: `rendered_frame` |
| **robot** | `RobotSimulatorProcess` | `robot_worker` (LOOP) | `reject_item` | — |
| **gui** | `GuiProcess` | — (QTimer) | — (отправляет команды другим) | consumer: `rendered_frame` |

### 1.3 Принципы реализации

1. **Dict at Boundary** (ADR-008): все данные через Queue/Router — только `dict`
2. **SharedMemory по именам** (ADR-019): кадры передаются через shared memory, уведомления — через лёгкие DATA-сообщения
3. **Owner/Consumer** для SharedMemory: Camera создаёт (`create=True`), остальные открывают (`create=False`)
4. **Воркеры с stop_event** (worker_module): все циклические задачи через `WorkerManager`
5. **Команды через CommandManager**: каждый процесс регистрирует обработчики
6. **Конфигурация через SchemaBase**: валидация через Pydantic, подписки на изменения
7. **Конфиг с build()** (HasBuild): каждый конфиг реализует `build() -> (name, proc_dict)` для `process()` из data_schema_module — `launcher.add_process(*process(CameraConfig()))`
8. **GUI без воркеров**: PyQt работает в главном потоке, QTimer для опроса сообщений

---

## 2. Структура проекта

```
Inspector_prototype/multiprocess_prototype/
├── __init__.py                          # Версия, описание пакета
├── main.py                              # Точка входа: SystemLauncher
├── PLAN.md                              # Этот файл
├── README.md                            # Описание и инструкции запуска
│
├── configs/                             # Конфигурационные схемы
│   ├── __init__.py
│   ├── camera_config.py                 # CameraConfig(SchemaBase)
│   ├── processor_config.py              # ProcessorConfig(SchemaBase)
│   ├── renderer_config.py               # RendererConfig(SchemaBase)
│   ├── robot_config.py                  # RobotConfig(SchemaBase)
│   └── gui_config.py                    # GuiConfig(SchemaBase)
│
├── processes/                           # Процессы приложения
│   ├── __init__.py                      # Реэкспорт всех процессов
│   ├── camera_process.py                # CameraProcess(ProcessModule)
│   ├── processor_process.py             # ProcessorProcess(ProcessModule)
│   ├── renderer_process.py              # RendererProcess(ProcessModule)
│   ├── robot_simulator_process.py       # RobotSimulatorProcess(ProcessModule)
│   └── gui_process.py                   # GuiProcess(ProcessModule)
│
├── gui/                                 # GUI компоненты
│   ├── __init__.py
│   └── main_window.py                   # InspectorWindow(QMainWindow)
│
└── utils/                               # Утилиты
    ├── __init__.py
    └── frame_generator.py               # Генератор тестовых кадров (имитация камеры)
```

### 2.1 Почему плоская структура процессов (не вложенные папки)

Существующий прототип использовал вложенную структуру (`processes/process_1/process_1_module.py`). Для 5 процессов это избыточно. Каждый процесс — один файл (~100-150 строк). Конфиги вынесены в `configs/` отдельно, потому что они используются и в `main.py` при регистрации, и внутри процессов.

---

## 3. Этап 0: Подготовка инфраструктуры

### 3.1 Файл `utils/frame_generator.py`

Генератор тестовых кадров для имитации камеры. Создаёт numpy-массив с цветными пятнами.

```python
import numpy as np
import time

class FrameGenerator:
    """Имитация камеры: генерирует кадры с цветными пятнами."""
    
    def __init__(self, width: int = 640, height: int = 480):
        self.width = width
        self.height = height
        self._frame_count = 0
    
    def generate_frame(self) -> np.ndarray:
        """Генерирует кадр с движущимся цветным пятном."""
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = (30, 30, 30)  # тёмно-серый фон
        
        self._frame_count += 1
        # Красное пятно, движущееся по синусоиде
        cx = int(self.width / 2 + 150 * np.sin(self._frame_count * 0.05))
        cy = int(self.height / 2 + 100 * np.cos(self._frame_count * 0.03))
        radius = 30
        y, x = np.ogrid[-cy:self.height - cy, -cx:self.width - cx]
        mask = x**2 + y**2 <= radius**2
        frame[mask] = (0, 0, 255)  # красный (BGR)
        
        return frame
    
    @property
    def frame_count(self) -> int:
        return self._frame_count
```

**Зачем:** Позволяет тестировать без реальной камеры. В продакшене заменяется на `cv2.VideoCapture`.

### 3.2 Файл `configs/__init__.py`

```python
from .camera_config import CameraConfig
from .processor_config import ProcessorConfig
from .renderer_config import RendererConfig
from .robot_config import RobotConfig
from .gui_config import GuiConfig

__all__ = [
    "CameraConfig", "ProcessorConfig", "RendererConfig",
    "RobotConfig", "GuiConfig",
]
```

### 3.3 Конфигурационные схемы

Каждая схема наследует `SchemaBase` из `data_schema_module`. Поля описываются через `Annotated[type, FieldMeta(...)]`. **Обязательно:** метод `build() -> (name, proc_dict)` (протокол HasBuild) для интеграции с `process()` — `launcher.add_process(*process(CameraConfig()))`.

**Документация:** `modules/data_schema_module/README.md`, `modules/data_schema_module/container/config_converters.py` (process, build_process_with_workers)

#### `configs/camera_config.py`

```python
from typing import Annotated
from multiprocess_framework.refactored.modules.data_schema_module import (
    SchemaBase, FieldMeta, register_schema,
)

@register_schema("CameraConfig")
class CameraConfig(SchemaBase):
    """Конфигурация процесса захвата видео."""
    process_name: str = "camera"
    fps: Annotated[int, FieldMeta("Частота кадров", min=1, max=120)] = 30
    resolution_width: Annotated[int, FieldMeta("Ширина кадра", min=320, max=1920)] = 640
    resolution_height: Annotated[int, FieldMeta("Высота кадра", min=240, max=1080)] = 480
    device_id: Annotated[int, FieldMeta("ID камеры", min=0, max=10)] = 0
    use_simulator: bool = True  # True = FrameGenerator, False = cv2.VideoCapture

    def build(self) -> tuple[str, dict]:
        """HasBuild: (name, proc_dict) для launcher.add_process(*process(CameraConfig()))."""
        return (self.process_name, {
            "class": "multiprocess_prototype.processes.camera_process.CameraProcess",
            "queues": {"system": {"maxsize": 100}, "data": {"maxsize": 50}},
            "priority": "high",
            "workers": {},
            "config": self.model_dump(),
        })
```

#### `configs/processor_config.py`

```python
@register_schema("ProcessorConfig")
class ProcessorConfig(SchemaBase):
    """Конфигурация процесса обработки кадров."""
    process_name: str = "processor"
    threshold: Annotated[float, FieldMeta("Порог детекции", min=0.0, max=255.0)] = 200.0
    min_area: Annotated[int, FieldMeta("Мин. площадь пятна", min=10, max=10000)] = 500
    color_lower: list = [0, 0, 150]   # нижняя граница BGR для красного
    color_upper: list = [100, 100, 255]  # верхняя граница BGR для красного

    def build(self) -> tuple[str, dict]:
        return (self.process_name, {"class": "...", "queues": {...}, "config": self.model_dump(), ...})
```

#### `configs/renderer_config.py`

```python
@register_schema("RendererConfig")
class RendererConfig(SchemaBase):
    """Конфигурация процесса отрисовки."""
    process_name: str = "renderer"
    output_dir: str = "./output_frames"
    save_frames: bool = False   # сохранять кадры на диск
    draw_bboxes: bool = True    # рисовать bounding boxes
```

#### `configs/robot_config.py`

```python
@register_schema("RobotConfig")
class RobotConfig(SchemaBase):
    """Конфигурация симулятора робота."""
    process_name: str = "robot"
    log_file: str = "./robot_actions.log"
    reject_delay: Annotated[float, FieldMeta("Задержка отбраковки, сек", min=0.0, max=5.0)] = 0.5
```

#### `configs/gui_config.py`

```python
@register_schema("GuiConfig")
class GuiConfig(SchemaBase):
    """Конфигурация GUI-процесса."""
    process_name: str = "gui"
    window_title: str = "Inspector Prototype"
    window_width: Annotated[int, FieldMeta("Ширина окна", min=400, max=1920)] = 1024
    window_height: Annotated[int, FieldMeta("Высота окна", min=300, max=1080)] = 768
    poll_interval_ms: Annotated[int, FieldMeta("Интервал опроса сообщений, мс", min=5, max=100)] = 16

    def build(self) -> tuple[str, dict]:
        return (self.process_name, {"class": "...", "queues": {...}, "config": self.model_dump(), ...})
```

**Примечание:** RendererConfig и RobotConfig — аналогично, каждый имеет `build()`.

---

## 4. Этап 1: CameraProcess

**Документация для изучения:**
- `modules/process_module/README.md` — жизненный цикл, API ProcessModule
- `modules/worker_module/README.md` — создание воркеров, ThreadConfig
- `modules/shared_resources_module/README.md` — MemoryManager, SharedMemory
- `modules/message_module/README.md` — MessageAdapter, типы сообщений
- `modules/command_module/README.md` — CommandManager, регистрация команд

### 4.1 Ответственность

CameraProcess захватывает видеокадры (реальная камера или имитация), пишет их в shared memory и уведомляет ProcessorProcess через лёгкое DATA-сообщение.

### 4.2 Команды

| Команда | Аргументы | Действие |
|---------|-----------|----------|
| `start_capture` | — | Запуск/возобновление захвата |
| `stop_capture` | — | Пауза захвата |
| `set_fps` | `{"fps": int}` | Изменить FPS |
| `set_resolution` | `{"width": int, "height": int}` | Изменить разрешение |

### 4.3 Shared Memory

CameraProcess является **owner** блока `camera_frame`:
- Параметры: `(1, (480, 640, 3), "uint8")` — 1 изображение, 480x640x3, uint8
- Количество буферов (`coll`): `2` — двойная буферизация (пока один пишется, другой читается)

### 4.4 Воркер `capture_worker`

```python
def _capture_worker(self, stop_event, pause_event):
    """Циклический захват кадров. Режим LOOP."""
    frame_count = 0
    while not stop_event.is_set():
        if pause_event.is_set():
            time.sleep(0.05)
            continue
        
        # 1. Захватить кадр
        frame = self._generator.generate_frame()
        frame_count += 1
        timestamp = time.time()
        
        # 2. Найти свободный слот в shared memory
        mm = self.shared_resources.memory_manager
        free_idx = mm.find_free_index("camera", "camera_frame")
        if free_idx is None:
            free_idx = 0  # перезапись старого
        
        # 3. Записать кадр в shared memory
        shm_name = mm.write_images("camera", "camera_frame", [frame], free_idx)
        
        # 4. Отправить лёгкое уведомление (Dict at Boundary!)
        if shm_name:
            notification = {
                "type": "data",
                "sender": "camera",
                "targets": ["processor"],
                "data_type": "frame_ready",
                "data": {
                    "frame_id": frame_count,
                    "timestamp": timestamp,
                    "shm_name": "camera_frame",
                    "shm_index": free_idx,
                    "width": frame.shape[1],
                    "height": frame.shape[0],
                },
            }
            self.send_message("processor", notification)
        
        # 5. Соблюдать FPS
        delay = 1.0 / self._fps
        time.sleep(delay)
```

### 4.5 Реализация CameraProcess

```python
import time
from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.worker_module import (
    ThreadConfig, ExecutionMode,
)

class CameraProcess(ProcessModule):
    
    def initialize(self) -> bool:
        self.log_info("CameraProcess initializing...")
        
        # Параметры из конфига
        self._fps = self.get_config("fps", 30)
        self._width = self.get_config("resolution_width", 640)
        self._height = self.get_config("resolution_height", 480)
        self._use_simulator = self.get_config("use_simulator", True)
        self._capturing = True
        
        # Генератор кадров
        if self._use_simulator:
            from multiprocess_prototype.utils.frame_generator import FrameGenerator
            self._generator = FrameGenerator(self._width, self._height)
        
        # Shared Memory для кадров (owner)
        mm = self.shared_resources.memory_manager
        mm.create_memory_dict("camera", {
            "camera_frame": (1, (self._height, self._width, 3), "uint8"),
        }, coll=2)
        
        # Регистрация команд
        self.command_manager.register_command("start_capture", self._cmd_start)
        self.command_manager.register_command("stop_capture", self._cmd_stop)
        self.command_manager.register_command("set_fps", self._cmd_set_fps)
        self.command_manager.register_command("set_resolution", self._cmd_set_resolution)
        
        # Создание воркера
        config = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "capture_worker", self._capture_worker, config, auto_start=True
        )
        
        self.is_initialized = True
        self.log_info(f"CameraProcess ready: {self._width}x{self._height} @ {self._fps} FPS")
        return True
    
    def _cmd_start(self, data):
        self._capturing = True
        self.log_info("Capture started")
        return {"status": "ok"}
    
    def _cmd_stop(self, data):
        self._capturing = False
        self.log_info("Capture stopped")
        return {"status": "ok"}
    
    def _cmd_set_fps(self, data):
        new_fps = data.get("fps", self._fps)
        self._fps = max(1, min(120, new_fps))
        self.log_info(f"FPS set to {self._fps}")
        return {"status": "ok", "fps": self._fps}
    
    def _cmd_set_resolution(self, data):
        self._width = data.get("width", self._width)
        self._height = data.get("height", self._height)
        if self._use_simulator:
            from multiprocess_prototype.utils.frame_generator import FrameGenerator
            self._generator = FrameGenerator(self._width, self._height)
        self.log_info(f"Resolution set to {self._width}x{self._height}")
        return {"status": "ok"}
    
    def shutdown(self) -> bool:
        self.log_info("CameraProcess shutting down...")
        mm = self.shared_resources.memory_manager
        mm.close_all("camera")
        self.is_initialized = False
        return True
```

### 4.6 Важные детали

- **SharedMemory создаётся в `initialize()`** камеры (owner). ProcessManager уже зарегистрировал процесс, MemoryManager доступен через `self.shared_resources.memory_manager`.
- **Уведомление — лёгкое**: содержит только метаданные (frame_id, timestamp, имя блока, индекс). Сам кадр НЕ передаётся через очередь — только через shared memory.
- **FPS контролируется** через `time.sleep(1.0 / self._fps)` в конце цикла воркера.
- **Команды** изменяют атрибуты экземпляра. Воркер читает их на каждой итерации.

---

## 5. Этап 2: ProcessorProcess

### 5.1 Ответственность

Получает уведомления от Camera, читает кадр из shared memory, ищет цветные пятна, отправляет координаты в Renderer.

### 5.2 Команды

| Команда | Аргументы | Действие |
|---------|-----------|----------|
| `set_threshold` | `{"threshold": float}` | Изменить порог детекции |
| `set_min_area` | `{"min_area": int}` | Изменить мин. площадь |

### 5.3 Воркер `processing_worker`

```python
def _processing_worker(self, stop_event, pause_event):
    """Получает кадры, обрабатывает, шлёт результаты."""
    while not stop_event.is_set():
        if pause_event.is_set():
            time.sleep(0.05)
            continue
        
        # Получить сообщение из очереди (с таймаутом!)
        msg = self.receive_message(timeout=0.1)
        if msg is None:
            continue
        
        msg_dict = msg if isinstance(msg, dict) else msg.to_dict()
        data_type = msg_dict.get("data_type", "")
        
        if data_type != "frame_ready":
            continue
        
        data = msg_dict.get("data", {})
        frame_id = data.get("frame_id", 0)
        shm_index = data.get("shm_index", 0)
        timestamp = data.get("timestamp", 0)
        
        # Читать кадр из shared memory
        mm = self.shared_resources.memory_manager
        images = mm.read_images("camera", "camera_frame", shm_index, n=1)
        if not images or len(images) == 0:
            continue
        
        frame = images[0]
        t_start = time.time()
        
        # Обработка: поиск цветных пятен
        detections = self._detect_color_blobs(frame)
        
        processing_time = time.time() - t_start
        
        # Отправить результаты в Renderer
        result_msg = {
            "type": "data",
            "sender": "processor",
            "targets": ["renderer"],
            "data_type": "detection_result",
            "data": {
                "frame_id": frame_id,
                "shm_name": "camera_frame",
                "shm_index": shm_index,
                "detections": detections,  # список dict с bbox
                "processing_time": processing_time,
                "timestamp": timestamp,
            },
        }
        self.send_message("renderer", result_msg)
        
        # Обратная связь в Camera
        feedback = {
            "type": "event",
            "sender": "processor",
            "targets": ["camera"],
            "event_type": "frame_processed",
            "data": {
                "frame_id": frame_id,
                "processing_time": processing_time,
            },
        }
        self.send_message("camera", feedback)
```

### 5.4 Метод детекции

```python
def _detect_color_blobs(self, frame):
    """Простая детекция цветных пятен по порогу яркости красного канала."""
    import numpy as np
    
    lower = np.array(self._color_lower, dtype=np.uint8)
    upper = np.array(self._color_upper, dtype=np.uint8)
    
    # Маска по цветовому диапазону
    mask = np.all((frame >= lower) & (frame <= upper), axis=2).astype(np.uint8)
    
    # Поиск связанных компонент (без OpenCV, простая реализация)
    # Для прототипа достаточно найти bounding box ненулевых пикселей
    detections = []
    ys, xs = np.where(mask > 0)
    if len(ys) >= self._min_area:
        x_min, x_max = int(xs.min()), int(xs.max())
        y_min, y_max = int(ys.min()), int(ys.max())
        area = int(len(ys))
        cx = (x_min + x_max) // 2
        cy = (y_min + y_max) // 2
        detections.append({
            "bbox": [x_min, y_min, x_max, y_max],
            "center": [cx, cy],
            "area": area,
        })
    
    return detections
```

### 5.5 Полная реализация ProcessorProcess

Аналогична CameraProcess по структуре:
- `initialize()` — загрузка конфига, регистрация команд, создание воркера
- `_cmd_set_threshold()`, `_cmd_set_min_area()` — обработчики команд
- `shutdown()` — логирование завершения

---

## 6. Этап 3: RendererProcess

### 6.1 Ответственность

Получает результаты от Processor, читает оригинальный кадр из shared memory камеры, рисует bounding boxes, записывает результат в shared memory для GUI, отправляет координаты дефектов в RobotSimulator.

### 6.2 Shared Memory

RendererProcess является:
- **Consumer** блока `camera_frame` (чтение оригинала)
- **Owner** блока `rendered_frame` (запись кадра с отрисованными результатами)

```python
# В initialize():
mm = self.shared_resources.memory_manager
mm.create_memory_dict("renderer", {
    "rendered_frame": (1, (480, 640, 3), "uint8"),
}, coll=2)
```

### 6.3 Воркер `render_worker`

```python
def _render_worker(self, stop_event, pause_event):
    while not stop_event.is_set():
        if pause_event.is_set():
            time.sleep(0.05)
            continue
        
        msg = self.receive_message(timeout=0.1)
        if msg is None:
            continue
        
        msg_dict = msg if isinstance(msg, dict) else msg.to_dict()
        if msg_dict.get("data_type") != "detection_result":
            continue
        
        data = msg_dict.get("data", {})
        frame_id = data.get("frame_id")
        shm_index = data.get("shm_index", 0)
        detections = data.get("detections", [])
        
        # 1. Читать оригинальный кадр
        mm = self.shared_resources.memory_manager
        images = mm.read_images("camera", "camera_frame", shm_index, n=1)
        if not images:
            continue
        
        frame = images[0].copy()  # Копия! Не модифицируем оригинал
        
        # 2. Отрисовать bounding boxes
        for det in detections:
            bbox = det.get("bbox", [0, 0, 0, 0])
            x1, y1, x2, y2 = bbox
            # Рисуем прямоугольник (без OpenCV, через numpy)
            frame[y1:y2, x1:min(x1+2, x2), :] = [0, 255, 0]  # левая граница
            frame[y1:y2, max(x2-2, x1):x2, :] = [0, 255, 0]  # правая
            frame[y1:min(y1+2, y2), x1:x2, :] = [0, 255, 0]  # верхняя
            frame[max(y2-2, y1):y2, x1:x2, :] = [0, 255, 0]  # нижняя
        
        # 3. Записать отрендеренный кадр в shared memory для GUI
        free_idx = mm.find_free_index("renderer", "rendered_frame") or 0
        mm.write_images("renderer", "rendered_frame", [frame], free_idx)
        
        # 4. Уведомить GUI о новом кадре
        gui_notification = {
            "type": "data",
            "sender": "renderer",
            "targets": ["gui"],
            "data_type": "rendered_frame_ready",
            "data": {
                "frame_id": frame_id,
                "shm_name": "rendered_frame",
                "shm_index": free_idx,
                "detections_count": len(detections),
            },
        }
        self.send_message("gui", gui_notification)
        
        # 5. Если есть детекции — отправить координаты роботу
        if detections:
            robot_cmd = {
                "type": "command",
                "sender": "renderer",
                "targets": ["robot"],
                "command": "reject_item",
                "data": {
                    "frame_id": frame_id,
                    "defects": detections,
                },
            }
            self.send_message("robot", robot_cmd)
        
        # 6. Обратная связь
        feedback = {
            "type": "event",
            "sender": "renderer",
            "targets": ["camera"],
            "event_type": "frame_rendered",
            "data": {"frame_id": frame_id},
        }
        self.send_message("camera", feedback)
```

### 6.4 Опциональное сохранение на диск

```python
if self._save_frames:
    import os
    os.makedirs(self._output_dir, exist_ok=True)
    # Сохраняем как raw numpy (без OpenCV для минимальности зависимостей)
    np.save(os.path.join(self._output_dir, f"frame_{frame_id:06d}.npy"), frame)
```

---

## 7. Этап 4: RobotSimulatorProcess

### 7.1 Ответственность

Имитирует робота-отбраковщика. Получает команды с координатами дефектов, логирует их в файл.

### 7.2 Реализация

Самый простой процесс. Один воркер, одна команда.

```python
class RobotSimulatorProcess(ProcessModule):
    
    def initialize(self) -> bool:
        self.log_info("RobotSimulator initializing...")
        
        self._log_file = self.get_config("log_file", "./robot_actions.log")
        self._reject_delay = self.get_config("reject_delay", 0.5)
        self._action_count = 0
        
        self.command_manager.register_command("reject_item", self._cmd_reject)
        
        config = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "robot_worker", self._robot_worker, config, auto_start=True
        )
        
        self.is_initialized = True
        return True
    
    def _cmd_reject(self, data):
        """Обработчик команды отбраковки."""
        frame_id = data.get("frame_id", 0)
        defects = data.get("defects", [])
        self._action_count += 1
        
        for defect in defects:
            center = defect.get("center", [0, 0])
            area = defect.get("area", 0)
            self.log_info(
                f"REJECT #{self._action_count}: frame={frame_id}, "
                f"pos=({center[0]}, {center[1]}), area={area}"
            )
            self._write_to_log(frame_id, center, area)
        
        return {"status": "ok", "action_id": self._action_count}
    
    def _robot_worker(self, stop_event, pause_event):
        """Обработка входящих сообщений."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            
            msgs = self.receive(timeout=0.1)
            for msg in msgs:
                msg_dict = msg if isinstance(msg, dict) else msg
                cmd = msg_dict.get("command")
                if cmd and self.command_manager:
                    self.command_manager.handle_command(msg_dict)
            
            time.sleep(0.05)
    
    def _write_to_log(self, frame_id, center, area):
        """Запись действия робота в файл."""
        import datetime
        ts = datetime.datetime.now().isoformat()
        line = f"{ts} | frame={frame_id} | x={center[0]} y={center[1]} | area={area}\n"
        try:
            with open(self._log_file, "a") as f:
                f.write(line)
        except Exception as e:
            self.log_error(f"Failed to write robot log: {e}")
    
    def shutdown(self) -> bool:
        self.log_info(f"RobotSimulator shutting down. Total actions: {self._action_count}")
        return True
```

---

## 8. Этап 5: GuiProcess (PyQt)

**Это самый сложный процесс. Требует особого подхода.**

### 8.1 Особенности GUI-процесса

1. **PyQt QApplication запускается в методе `run()`**, а не в воркере
2. **QTimer** используется для периодического опроса сообщений (каждые 16 мс ≈ 60 Hz)
3. **Воркеры НЕ используются** — PyQt работает в главном потоке
4. **Команды отправляются** из GUI-потока через `self.send_message()`
5. **Кадры получаются** из shared memory по уведомлениям

### 8.2 Структура GuiProcess

```python
import sys
import time
import numpy as np
from multiprocess_framework.refactored.modules.process_module import ProcessModule


class GuiProcess(ProcessModule):
    """
    GUI-процесс с PyQt.
    
    ВАЖНО: run() запускает QApplication.exec_() — это блокирующий вызов.
    QTimer опрашивает входящие сообщения каждые poll_interval_ms мс.
    Воркеры НЕ создаются.
    """
    
    def initialize(self) -> bool:
        self.log_info("GuiProcess initializing...")
        
        self._poll_interval = self.get_config("poll_interval_ms", 16)
        self._window_title = self.get_config("window_title", "Inspector Prototype")
        self._window_width = self.get_config("window_width", 1024)
        self._window_height = self.get_config("window_height", 768)
        
        self.is_initialized = True
        self.log_info("GuiProcess ready")
        return True
    
    def run(self):
        """Основной цикл GUI — запускает QApplication."""
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import QTimer
        from multiprocess_prototype.gui.main_window import InspectorWindow
        
        app = QApplication(sys.argv)
        
        self._window = InspectorWindow(
            title=self._window_title,
            width=self._window_width,
            height=self._window_height,
            process=self,  # передаём ссылку на процесс для отправки команд
        )
        self._window.show()
        
        # QTimer для опроса сообщений
        self._timer = QTimer()
        self._timer.timeout.connect(self._poll_messages)
        self._timer.start(self._poll_interval)
        
        # QTimer для проверки stop_event
        self._stop_timer = QTimer()
        self._stop_timer.timeout.connect(lambda: self._check_stop(app))
        self._stop_timer.start(100)  # каждые 100 мс
        
        app.exec_()
    
    def _poll_messages(self):
        """Вызывается QTimer. Читает входящие сообщения."""
        msgs = self.receive(timeout=0.001)  # неблокирующий
        for msg in msgs:
            msg_dict = msg if isinstance(msg, dict) else msg
            data_type = msg_dict.get("data_type", "")
            
            if data_type == "rendered_frame_ready":
                self._handle_new_frame(msg_dict.get("data", {}))
    
    def _handle_new_frame(self, data):
        """Получен новый отрендеренный кадр."""
        shm_index = data.get("shm_index", 0)
        frame_id = data.get("frame_id", 0)
        
        # Читаем из shared memory
        mm = self.shared_resources.memory_manager
        images = mm.read_images("renderer", "rendered_frame", shm_index, n=1)
        if images and len(images) > 0:
            self._window.update_frame(images[0], frame_id)
    
    def _check_stop(self, app):
        """Проверка stop_event для graceful shutdown."""
        if self.should_stop():
            app.quit()
    
    # === Методы для вызова из GUI (через кнопки) ===
    
    def gui_start_capture(self):
        """Кнопка Start."""
        self.send_message("camera", {
            "type": "command",
            "command": "start_capture",
            "sender": "gui",
            "targets": ["camera"],
            "data": {},
        })
    
    def gui_stop_capture(self):
        """Кнопка Stop."""
        self.send_message("camera", {
            "type": "command",
            "command": "stop_capture",
            "sender": "gui",
            "targets": ["camera"],
            "data": {},
        })
    
    def gui_set_fps(self, fps: int):
        """Слайдер FPS."""
        self.send_message("camera", {
            "type": "command",
            "command": "set_fps",
            "sender": "gui",
            "targets": ["camera"],
            "data": {"fps": fps},
        })
    
    def gui_set_threshold(self, threshold: float):
        """Слайдер порога."""
        self.send_message("processor", {
            "type": "command",
            "command": "set_threshold",
            "sender": "gui",
            "targets": ["processor"],
            "data": {"threshold": threshold},
        })
    
    def shutdown(self) -> bool:
        self.log_info("GuiProcess shutting down")
        return True
```

### 8.3 InspectorWindow (gui/main_window.py)

```python
import numpy as np
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSlider, QGroupBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap


class InspectorWindow(QMainWindow):
    """Главное окно Inspector Prototype."""
    
    def __init__(self, title, width, height, process):
        super().__init__()
        self.process = process  # GuiProcess — для отправки команд
        self.setWindowTitle(title)
        self.resize(width, height)
        
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        
        # Левая панель — видео
        self._video_label = QLabel("Waiting for frames...")
        self._video_label.setAlignment(Qt.AlignCenter)
        self._video_label.setMinimumSize(640, 480)
        self._video_label.setStyleSheet("background-color: #1e1e1e; color: white;")
        main_layout.addWidget(self._video_label, stretch=3)
        
        # Правая панель — управление
        control_panel = QVBoxLayout()
        main_layout.addLayout(control_panel, stretch=1)
        
        # Кнопки Start/Stop
        btn_group = QGroupBox("Управление камерой")
        btn_layout = QVBoxLayout(btn_group)
        
        self._btn_start = QPushButton("▶ Start")
        self._btn_start.clicked.connect(self.process.gui_start_capture)
        self._btn_start.setStyleSheet("padding: 10px; font-size: 14px;")
        btn_layout.addWidget(self._btn_start)
        
        self._btn_stop = QPushButton("■ Stop")
        self._btn_stop.clicked.connect(self.process.gui_stop_capture)
        self._btn_stop.setStyleSheet("padding: 10px; font-size: 14px;")
        btn_layout.addWidget(self._btn_stop)
        
        control_panel.addWidget(btn_group)
        
        # Слайдер FPS
        fps_group = QGroupBox("FPS")
        fps_layout = QVBoxLayout(fps_group)
        self._fps_label = QLabel("30 FPS")
        self._fps_slider = QSlider(Qt.Horizontal)
        self._fps_slider.setRange(1, 60)
        self._fps_slider.setValue(30)
        self._fps_slider.valueChanged.connect(self._on_fps_changed)
        fps_layout.addWidget(self._fps_label)
        fps_layout.addWidget(self._fps_slider)
        control_panel.addWidget(fps_group)
        
        # Слайдер порога
        thresh_group = QGroupBox("Порог детекции")
        thresh_layout = QVBoxLayout(thresh_group)
        self._thresh_label = QLabel("200")
        self._thresh_slider = QSlider(Qt.Horizontal)
        self._thresh_slider.setRange(0, 255)
        self._thresh_slider.setValue(200)
        self._thresh_slider.valueChanged.connect(self._on_threshold_changed)
        thresh_layout.addWidget(self._thresh_label)
        thresh_layout.addWidget(self._thresh_slider)
        control_panel.addWidget(thresh_group)
        
        # Статус
        self._status_label = QLabel("Status: waiting")
        self._status_label.setStyleSheet("color: gray; padding: 5px;")
        control_panel.addWidget(self._status_label)
        
        # Счётчик кадров
        self._frame_counter_label = QLabel("Frames: 0")
        control_panel.addWidget(self._frame_counter_label)
        
        control_panel.addStretch()
        
        self._frame_count = 0
    
    def update_frame(self, frame: np.ndarray, frame_id: int):
        """Обновить отображение кадра. Вызывается из QTimer callback."""
        self._frame_count += 1
        h, w, ch = frame.shape
        bytes_per_line = ch * w
        
        # BGR -> RGB для Qt
        rgb_frame = frame[:, :, ::-1].copy()
        
        q_img = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(q_img)
        scaled = pixmap.scaled(
            self._video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._video_label.setPixmap(scaled)
        
        self._frame_counter_label.setText(f"Frames: {self._frame_count}")
        self._status_label.setText(f"Status: active | Frame #{frame_id}")
    
    def _on_fps_changed(self, value):
        self._fps_label.setText(f"{value} FPS")
        self.process.gui_set_fps(value)
    
    def _on_threshold_changed(self, value):
        self._thresh_label.setText(str(value))
        self.process.gui_set_threshold(float(value))
```

### 8.4 Важные замечания по GUI

1. **`process` передаётся в конструктор окна** — это ссылка на `GuiProcess`. Через неё окно вызывает `process.gui_start_capture()` и т.д. Это безопасно, потому что всё в одном потоке.

2. **`update_frame()` вызывается из `_poll_messages()`** → из QTimer → из главного потока Qt. Нет проблем с потокобезопасностью.

3. **`_check_stop()`** — отдельный QTimer каждые 100 мс проверяет, не пришёл ли сигнал остановки от ProcessManager. Если да — закрывает приложение.

4. **Нет воркеров** — весь код GUI работает в главном потоке через event loop Qt.

5. **Компоненты из `Inspector_prototype/App/UI/Components/`** пока не используются — они привязаны к `RegistersManager`, который не совместим с новым ConfigManager. Создаём минимальные виджеты. В будущем `SliderControlEnhanced` и `CheckboxControlEnhanced` будут адаптированы.

---

## 9. Этап 6: main.py и интеграция

### 9.1 Точка входа

**Конфиги с build()** — каждый процесс регистрируется через `process(Config())` из data_schema_module. Валидация через SchemaBase, Dict at Boundary через HasBuild.

```python
"""
Inspector Prototype — точка входа.

Запускает 5 процессов через SystemLauncher:
  camera → processor → renderer → robot
                                → gui
"""

import sys
import os

# PYTHONPATH должен включать Inspector_prototype/
# чтобы импорты multiprocess_framework и multiprocess_prototype работали


def main() -> int:
    from multiprocess_framework.refactored.modules.process_manager_module import (
        SystemLauncher,
    )
    from multiprocess_framework.refactored.modules.data_schema_module import process
    from multiprocess_prototype.configs import (
        CameraConfig, ProcessorConfig, RendererConfig,
        RobotConfig, GuiConfig,
    )
    
    launcher = SystemLauncher(stop_timeout=10.0)
    
    # Конфиги с build() — валидация + Dict at Boundary
    launcher.add_process(*process(CameraConfig()))
    launcher.add_process(*process(ProcessorConfig()))
    launcher.add_process(*process(RendererConfig()))
    launcher.add_process(*process(RobotConfig()))
    launcher.add_process(*process(GuiConfig()))
    
    print("=" * 60)
    print("  Inspector Prototype — 5 Process Demo")
    print("  Press Ctrl+C to stop")
    print("=" * 60)
    
    launcher.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### 9.2 Запуск

```bash
cd Inspector_prototype
PYTHONPATH=. python -m multiprocess_prototype.main
```

Или:

```bash
cd Inspector_prototype
python multiprocess_prototype/main.py
```

### 9.3 Порядок инициализации (важно!)

```
SystemLauncher.run()
  → ProcessSpawner.launch_orchestrator()
    → ProcessManagerProcess.initialize()
      → SRM.register_process("camera", config)    # Queue + Event
      → SRM.register_process("processor", config)
      → SRM.register_process("renderer", config)
      → SRM.register_process("robot", config)
      → SRM.register_process("gui", config)
      → ProcessRegistry.start_all()
        → fork/spawn 5 процессов
          → Каждый: srm.reinitialize_in_child()
          → Каждый: process.initialize()
          → Каждый: process.run()
```

### 9.4 Shared Memory — кто создаёт, кто потребляет

| Блок | Owner (создаёт) | Consumers (читают) |
|------|-----------------|-------------------|
| `camera_frame` | `CameraProcess.initialize()` | `ProcessorProcess`, `RendererProcess` |
| `rendered_frame` | `RendererProcess.initialize()` | `GuiProcess` |

**Проблема:** Shared memory должна быть создана owner-процессом ПРЕЖДЕ чем consumer попытается её прочитать.

**Решение:** Consumers не падают если shared memory ещё не готова — `read_images()` возвращает `None`, воркер просто пропускает итерацию. Через 1-2 секунды после запуска все shared memory блоки уже созданы.

---

## 10. Этап 7: Обратная связь и статистика

### 10.1 Механизмы обратной связи

```
Camera ──frame_ready──► Processor ──detection_result──► Renderer ──rendered_frame_ready──► GUI
   ◄──frame_processed──  Processor                        │
   ◄──frame_rendered───  Renderer                         │
                                                          ├──reject_item──► Robot
```

| Сообщение | Тип | От | К | Содержание |
|-----------|-----|---|---|------------|
| `frame_ready` | DATA | camera | processor | frame_id, shm_index, timestamp |
| `frame_processed` | EVENT | processor | camera | frame_id, processing_time |
| `detection_result` | DATA | processor | renderer | frame_id, detections[], shm_index |
| `rendered_frame_ready` | DATA | renderer | gui | frame_id, shm_index, detections_count |
| `frame_rendered` | EVENT | renderer | camera | frame_id |
| `reject_item` | COMMAND | renderer | robot | frame_id, defects[] |

### 10.2 Сбор статистики

Каждый процесс логирует метрики через `self.log_info()` (через ObservableMixin → LoggerManager):

```python
# В CameraProcess — после каждых 100 кадров:
if frame_count % 100 == 0:
    elapsed = time.time() - self._stats_start_time
    actual_fps = 100.0 / elapsed if elapsed > 0 else 0
    self.log_info(
        f"[PERF] camera: frames={frame_count}, "
        f"actual_fps={actual_fps:.1f}, target_fps={self._fps}"
    )
    self._stats_start_time = time.time()

# В ProcessorProcess — после каждого кадра:
self.log_info(
    f"[PERF] processor: frame={frame_id}, "
    f"processing_time={processing_time*1000:.1f}ms, "
    f"detections={len(detections)}"
)
```

### 10.3 Опционально: StatsCollectorProcess (6-й процесс)

Если нужен отдельный сборщик статистики:

```python
class StatsCollectorProcess(ProcessModule):
    """Подписан на все EVENT-сообщения типа frame_processed, frame_rendered."""
    
    def initialize(self):
        self._metrics = {
            "total_frames": 0,
            "total_detections": 0,
            "avg_processing_time": 0.0,
        }
        # Воркер читает все входящие сообщения и агрегирует
        ...
```

Рекомендация: **не включать в первую версию**. Достаточно логов через `LoggerManager`. StatsManager (ADR-022) можно добавить позже.

---

## 11. Этап 8: Тестирование и отладка

### 11.1 Минимальный тест без GUI

Для начала запустить без GUI-процесса. Закомментировать `add_process("gui", ...)` в `main.py`. Camera → Processor → Renderer → Robot должны обмениваться сообщениями.

### 11.2 Тест shared memory изолированно

```python
# test_shared_memory.py
from multiprocess_framework.refactored.modules.shared_resources_module import (
    SharedResourcesManager,
)
from multiprocess_prototype.utils.frame_generator import FrameGenerator
import numpy as np

srm = SharedResourcesManager()
srm.initialize()

mm = srm.memory_manager
mm.create_memory_dict("test", {
    "test_frame": (1, (480, 640, 3), "uint8"),
}, coll=2)

gen = FrameGenerator()
frame = gen.generate_frame()

# Запись
result = mm.write_images("test", "test_frame", [frame], 0)
print(f"Write result: {result}")

# Чтение
images = mm.read_images("test", "test_frame", 0, n=1)
print(f"Read shape: {images[0].shape if images else 'None'}")
print(f"Match: {np.array_equal(frame, images[0]) if images else False}")

mm.close_all()
srm.shutdown()
```

### 11.3 Тест обмена сообщениями (2 процесса)

Запустить только Camera + Processor, убедиться что DATA-сообщения `frame_ready` доходят.

### 11.4 Отладка

- **Сообщения не доходят**: проверить `targets` в сообщении, проверить что RouterManager инициализирован
- **SharedMemory ошибки**: проверить что owner создал блок до того как consumer пытается читать
- **GUI зависает**: проверить что `_poll_messages()` не блокируется (timeout=0.001)
- **Процесс не завершается**: проверить `stop_event.is_set()` в воркерах, QTimer `_check_stop`

### 11.5 Чеклист перед запуском

- [ ] `PYTHONPATH` включает `Inspector_prototype/`
- [ ] `numpy` установлен
- [ ] `PyQt5` установлен (для GUI)
- [ ] `pydantic` v2 установлен
- [ ] Нет `sys.path.insert` в production-коде
- [ ] Все импорты абсолютные (между модулями)
- [ ] Все данные через очереди — только `dict`

---

## 12. Схемы взаимодействия

### 12.1 Полный поток данных (от захвата до отображения)

```
Шаг 1: CameraProcess._capture_worker()
    │ Генерирует кадр (FrameGenerator или cv2)
    │ Пишет в SharedMemory: camera_frame[idx]
    │ Отправляет DATA "frame_ready" → ProcessorProcess
    ▼
Шаг 2: ProcessorProcess._processing_worker()
    │ Получает "frame_ready" (msg из очереди)
    │ Читает кадр из SharedMemory: camera_frame[idx]
    │ Ищет цветные пятна → detections[]
    │ Отправляет DATA "detection_result" → RendererProcess
    │ Отправляет EVENT "frame_processed" → CameraProcess (обратная связь)
    ▼
Шаг 3: RendererProcess._render_worker()
    │ Получает "detection_result"
    │ Читает оригинальный кадр из SharedMemory: camera_frame[idx]
    │ Рисует bounding boxes
    │ Пишет в SharedMemory: rendered_frame[idx]
    │ Отправляет DATA "rendered_frame_ready" → GuiProcess
    │ Отправляет COMMAND "reject_item" → RobotSimulatorProcess
    │ Отправляет EVENT "frame_rendered" → CameraProcess (обратная связь)
    ▼
Шаг 4: GuiProcess._poll_messages() (QTimer, 60 Hz)
    │ Получает "rendered_frame_ready"
    │ Читает из SharedMemory: rendered_frame[idx]
    │ Обновляет QLabel через QPixmap
    ▼
Шаг 5: RobotSimulatorProcess._cmd_reject()
    │ Логирует координаты дефекта в файл
```

### 12.2 Поток команд от GUI

```
GUI: кнопка "Start" → process.gui_start_capture()
    │ self.send_message("camera", {command: "start_capture"})
    ▼
Camera: command_manager.handle_command() → _cmd_start()
    │ self._capturing = True

GUI: слайдер FPS → process.gui_set_fps(25)
    │ self.send_message("camera", {command: "set_fps", data: {fps: 25}})
    ▼
Camera: _cmd_set_fps({fps: 25}) → self._fps = 25

GUI: слайдер порога → process.gui_set_threshold(150.0)
    │ self.send_message("processor", {command: "set_threshold", data: {threshold: 150.0}})
    ▼
Processor: _cmd_set_threshold({threshold: 150.0}) → self._threshold = 150.0
```

---

## 13. Оценка и рекомендации

### 13.1 Оценка сложности по этапам

| Этап | Сложность | Время | Риски |
|------|-----------|-------|-------|
| Этап 0: Инфраструктура | Низкая | 15 мин | — |
| Этап 1: CameraProcess | Средняя | 30 мин | SharedMemory API |
| Этап 2: ProcessorProcess | Средняя | 25 мин | Чтение SharedMemory из другого процесса |
| Этап 3: RendererProcess | Средняя | 30 мин | Двойной доступ к SharedMemory |
| Этап 4: RobotSimulator | Низкая | 15 мин | — |
| Этап 5: GuiProcess | **Высокая** | 45 мин | PyQt + multiprocessing, QTimer |
| Этап 6: main.py | Низкая | 15 мин | PYTHONPATH, class_path |
| Этап 7: Статистика | Низкая | 15 мин | — |
| Этап 8: Тестирование | Средняя | 30 мин | Интеграционные баги |

### 13.2 Возможные упрощения

1. **Без shared memory**: передавать кадры как `frame.tobytes()` в DATA-сообщении. Проще, но медленнее (сериализация + десериализация через Queue). Подходит для 5-10 FPS.

2. **Без GUI-процесса**: начать с 4 процессов, GUI добавить позже. Результаты смотреть через логи.

3. **Без двойной буферизации**: `coll=1` вместо `coll=2`. Проще, но возможны гонки.

4. **cv2 вместо numpy для рисования**: если OpenCV доступен, `cv2.rectangle()` и `cv2.putText()` дают лучший результат. Но добавляет зависимость.

### 13.3 Альтернативный вариант передачи кадров (без SharedMemory)

Если SharedMemory вызывает трудности, можно передавать кадры через Queue:

```python
# Камера отправляет:
frame_bytes = frame.tobytes()
msg = {
    "type": "data",
    "sender": "camera",
    "targets": ["processor"],
    "data_type": "frame_data",
    "data": {
        "frame_id": frame_count,
        "frame_bytes": frame_bytes,  # bytes — pickle-safe
        "shape": list(frame.shape),
        "dtype": str(frame.dtype),
    },
}
self.send_message("processor", msg)

# Процессор восстанавливает:
frame = np.frombuffer(data["frame_bytes"], dtype=data["dtype"])
frame = frame.reshape(data["shape"])
```

**Плюсы:** Не нужна SharedMemory, проще отладка.  
**Минусы:** ~300KB на кадр через Queue, копирование, медленнее.  
**Рекомендация:** Начать с Queue, потом перейти на SharedMemory.

### 13.4 Ссылки на документацию по этапам

| Что делаем | Документ |
|-----------|----------|
| Создание процесса | `modules/process_module/README.md` — жизненный цикл |
| Создание воркера | `modules/worker_module/README.md` — ThreadConfig, ExecutionMode |
| Отправка сообщений | `modules/router_module/README.md` — RouterManager, send/receive |
| Регистрация команд | `modules/command_module/README.md` — CommandManager |
| SharedMemory | `modules/shared_resources_module/README.md` — MemoryManager |
| Dict at Boundary | `DECISIONS.md` ADR-008 |
| SharedMemory по именам | `DECISIONS.md` ADR-019, ADR-021 |
| Конфигурация | `modules/config_module/README.md`, `docs/USAGE_GUIDE.md` |
| Graceful shutdown | `docs/FRAMEWORK_OVERVIEW.md` — Фаза 4 |
| Типы сообщений | `docs/ARCHITECTURE_REFERENCE.md` — таблица §6 |

---

## Приложение A: Чеклист реализации

```
Этап 0:
  [ ] utils/frame_generator.py — FrameGenerator
  [ ] configs/camera_config.py — CameraConfig(SchemaBase)
  [ ] configs/processor_config.py — ProcessorConfig(SchemaBase)
  [ ] configs/renderer_config.py — RendererConfig(SchemaBase)
  [ ] configs/robot_config.py — RobotConfig(SchemaBase)
  [ ] configs/gui_config.py — GuiConfig(SchemaBase)
  [ ] configs/__init__.py

Этап 1:
  [ ] processes/camera_process.py — CameraProcess
  [ ] Тест: запуск CameraProcess в изоляции

Этап 2:
  [ ] processes/processor_process.py — ProcessorProcess
  [ ] Тест: Camera + Processor обмениваются сообщениями

Этап 3:
  [ ] processes/renderer_process.py — RendererProcess
  [ ] Тест: Camera + Processor + Renderer — полный пайплайн

Этап 4:
  [ ] processes/robot_simulator_process.py — RobotSimulatorProcess
  [ ] Тест: Robot получает команды reject_item

Этап 5:
  [ ] processes/gui_process.py — GuiProcess
  [ ] gui/main_window.py — InspectorWindow
  [ ] Тест: GUI отображает кадры, кнопки работают

Этап 6:
  [ ] main.py — SystemLauncher с 5 процессами
  [ ] Тест: полный запуск всех 5 процессов
  [ ] Тест: Ctrl+C → graceful shutdown

Этап 7:
  [ ] Логирование метрик (FPS, время обработки)
  [ ] Обратная связь (frame_processed, frame_rendered)

Этап 8:
  [ ] Тест shared memory изолированно
  [ ] Тест 2 процесса (Camera + Processor)
  [ ] Тест 4 процесса (без GUI)
  [ ] Полный тест 5 процессов
```

---

## Приложение B: Зависимости

```
# requirements.txt (для прототипа)
numpy>=1.21
pydantic>=2.0
PyQt5>=5.15
```

OpenCV (`opencv-python`) — опционально. Прототип работает без него (используется numpy для рисования и FrameGenerator для имитации камеры).

---

## Приложение C: Известные ограничения и TODO

1. **SharedMemory lifetime**: Owner должен вызвать `unlink()` при shutdown. Если процесс крашится без graceful shutdown — shm-блоки утекают. Решение: `ProcessManagerProcess` при cleanup вызывает `mm.close_all()`.

2. **macOS fork safety**: На macOS `fork()` может вызвать проблемы с PyQt. Если GUI не запускается — использовать `spawn` start method: `multiprocessing.set_start_method('spawn')`.

3. **Порядок запуска**: Camera должна создать SharedMemory раньше, чем Processor попытается читать. Текущее решение — consumer просто пропускает итерацию если данных нет. Альтернатива — добавить EVENT "camera_ready" и ждать его.

4. **Размер SharedMemory**: фиксирован при создании (640x480x3 = 921600 байт + заголовки). При изменении разрешения нужно пересоздавать блок (не реализовано в прототипе).

5. **GUI процесс на macOS/Linux**: PyQt может требовать запуск в главном процессе (не fork). Если проблема — запускать GUI в main process, остальные как дочерние.

---

**Конец плана.**

**Последнее обновление:** 2026-03-15
