# 06. Маппинг на multiprocess_framework

## 1. Текущий прототип (Inspector_bottles)

Фреймворк уже используется для прототипа инспекции бутылок. Существующие процессы:

| Процесс | Класс | Задача |
|---------|-------|--------|
| Camera | UnifiedCameraProcess | Захват изображений |
| Processor | ProcessorProcess | Обработка / детекция |
| Render | RendererProcess | Визуализация результатов |
| RobotSimulator | RobotSimulatorProcess | Эмуляция робота |
| Database | DatabaseProcess | Хранение данных |
| GUI | GuiProcess | PyQt5 интерфейс оператора |

**Архитектура один-в-один ложится на задачу упаковки рулонов.** Нужна адаптация, не переписывание.

## 2. Процессы для комплекса упаковки фольги

### 2.1. Схема процессов (один промПК, 4 линии)

```
SystemLauncher
    │
    ├── ProcessManagerProcess
    │       │
    │       ├─── [Линия 1]
    │       │       ├── CameraGrabProcess_L1      (4 камеры GigE)
    │       │       ├── InspectionProcess_L1       (YOLO inference + классический CV)
    │       │       ├── BarcodeProcess_L1          (QR/штрихкоды)
    │       │       └── LineControlProcess_L1      (решения: годен/брак, команды PLC)
    │       │
    │       ├─── [Линия 2]
    │       │       ├── CameraGrabProcess_L2
    │       │       ├── InspectionProcess_L2
    │       │       ├── BarcodeProcess_L2
    │       │       └── LineControlProcess_L2
    │       │
    │       ├─── [Линия 3] ... (аналогично)
    │       ├─── [Линия 4] ... (аналогично)
    │       │
    │       ├─── [Общие]
    │       │       ├── GpuInferenceProcess        (единый GPU inference для всех линий)
    │       │       ├── PlcBridgeProcess            (связь с Delta PLC по Modbus TCP)
    │       │       ├── ArchiveProcess              (запись в БД + файловый архив)
    │       │       ├── StatisticsProcess           (счётчики, агрегация, экспорт)
    │       │       └── GuiProcess                  (PyQt5 HMI, 1 экран)
    │       │
    │       └─── [Опциональные]
    │               ├── BoxControlProcess           (контроль вложений + весовой)
    │               └── RemoteAccessProcess         (удалённый доступ, диагностика)
```

### 2.2. Описание каждого процесса

#### CameraGrabProcess (×4, по одному на линию)

| Параметр | Значение |
|----------|----------|
| Базовый класс | ProcessModule (аналог UnifiedCameraProcess) |
| Камеры | 3-4 Hikrobot GigE (через MVS SDK) |
| Режим | Hardware trigger (от энкодера/датчика) |
| Выход | Набор кадров (dict: {cam_id: frame_bytes}) → в shared memory |
| IPC | data queue → InspectionProcess, BarcodeProcess |
| CPU ядра | 1-2 на процесс |
| Особенности | Должен поддерживать переключение ROI при смене номенклатуры |

```python
# Псевдокод CameraGrabProcess
class CameraGrabProcess(ProcessModule):
    def on_start(self):
        self.cameras = [HikCamera(ip) for ip in self.config.camera_ips]
        for cam in self.cameras:
            cam.set_trigger_mode(HARDWARE)
            cam.start_grabbing()
    
    def work_cycle(self):
        frames = {}
        for cam in self.cameras:
            frame = cam.grab_one(timeout=1000)  # ms
            frames[cam.id] = frame
        
        # Отправить кадры на обработку
        self.send_message(target="inspection", channel="frames", data=frames)
        self.send_message(target="barcode", channel="frames", data=frames)
```

#### GpuInferenceProcess (×1, общий)

| Параметр | Значение |
|----------|----------|
| Базовый класс | ProcessModule |
| GPU | NVIDIA RTX A2000, CUDA + TensorRT |
| Модель | YOLOv8m/v11m (FP16, TensorRT optimized) |
| Вход | Кадры от InspectionProcess (preprocessed) |
| Выход | Детекции (bboxes, classes, confidences) |
| IPC | data queue (in) → data queue (out) |
| Особенности | Batching: собирает кадры из всех линий, inference batch-ом |

**Почему отдельный процесс для GPU:**
- GPU — разделяемый ресурс между 4 линиями
- Batching на GPU эффективнее 4 отдельных вызовов
- Изоляция: crash GPU процесса не роняет grab/control
- Можно менять модель без остановки камер

```python
class GpuInferenceProcess(ProcessModule):
    def on_start(self):
        self.model = YOLO("best.pt").to("cuda")
        self.model.fuse()  # TensorRT optimization
    
    def work_cycle(self):
        # Собрать batch из очереди (от всех линий)
        batch = self.collect_batch(max_size=16, timeout=50)  # ms
        
        if batch:
            results = self.model.predict(batch, batch=len(batch))
            for line_id, result in zip(batch.line_ids, results):
                self.send_message(
                    target=f"inspection_L{line_id}",
                    channel="detections",
                    data=result.to_dict()
                )
```

#### InspectionProcess (×4, по одному на линию)

| Параметр | Значение |
|----------|----------|
| Базовый класс | ProcessModule (аналог ProcessorProcess) |
| Вход | Кадры от CameraGrab + детекции от GpuInference |
| Выход | Вердикт: PASS/REJECT + список дефектов |
| Логика | Preprocessing → отправка на GPU → получение детекций → postprocessing → решение |
| CPU | 1-2 ядра (preprocessing: resize, normalize, ROI) |

#### PlcBridgeProcess (×1)

| Параметр | Значение |
|----------|----------|
| Базовый класс | ProcessModule |
| Протокол | Modbus TCP (pymodbus) к Delta DVP/AS |
| Функции | Чтение: датчики, энкодеры, статусы. Запись: OK/REJECT, скорость, E_STOP |
| Цикл | 50-100 мс (опрос PLC) |
| Особенности | Должен быть максимально стабильным, минимум логики |

```python
class PlcBridgeProcess(ProcessModule):
    def on_start(self):
        self.plc = ModbusTcpClient(self.config.plc_ip, port=502)
        self.plc.connect()
    
    def work_cycle(self):
        # Чтение статусов с PLC
        status = self.plc.read_holding_registers(0, count=20)
        self.send_message(target="broadcast", channel="plc_status", data=status)
        
        # Обработка команд от InspectionProcess
        cmd = self.receive_message(channel="plc_command", timeout=10)
        if cmd:
            if cmd["action"] == "reject":
                self.plc.write_register(100 + cmd["line"], 1)  # REJECT signal
            elif cmd["action"] == "speed":
                self.plc.write_register(200 + cmd["line"], cmd["value"])
```

#### ArchiveProcess (×1)

| Параметр | Значение |
|----------|----------|
| Базовый класс | ProcessModule (аналог DatabaseProcess) |
| Хранение | SQLite (метаданные) + файловая система / NAS (изображения) |
| Данные | Каждый рулон: timestamp, линия, номенклатура, вердикт, дефекты, штрихкод, путь к фото |
| Ретенция | 1 год (требование ТЗ) |
| Экспорт | Excel (openpyxl), JSON API для dashboard |

#### GuiProcess (×1)

| Параметр | Значение |
|----------|----------|
| Базовый класс | ProcessModule + GuiProcessMixin |
| Фреймворк | PyQt5 |
| Экраны | Главный (4 линии), рецепты, статистика, аварийный журнал, настройки |
| Требования ТЗ | Русский язык, выбор продукции, ручной/авто режим, аварийные сообщения |

#### StatisticsProcess (×1)

| Параметр | Значение |
|----------|----------|
| Базовый класс | ProcessModule |
| Функции | Счётчики продукции (ТЗ п.64), агрегация по сменам, экспорт в dashboard |
| Данные | Рулонов/мин, коробов/мин, % брака, uptime, OEE |
| Выход | В GUI + в файл + в сеть предприятия (ТЗ п.87) |

## 3. IPC — потоки данных

```
CameraGrab_L1 ──frames──► InspectionProcess_L1 ──preprocessed──► GpuInferenceProcess
                                    ▲                                      │
                                    │                              detections
                                    └──────────────────────────────────────┘
                                    │
                              verdict (PASS/REJECT)
                                    │
                    ┌───────────────┼───────────────────┐
                    ▼               ▼                   ▼
            PlcBridgeProcess   ArchiveProcess    StatisticsProcess
            (reject signal)    (save to DB)      (update counters)
                    │
                    ▼
              Delta PLC
         (конвейер, сброс)
```

### Типы сообщений (Dict at Boundary)

```python
# Кадры от камеры
{
    "type": "frames",
    "line_id": 1,
    "timestamp": 1712678400.123,
    "roll_id": "L1-2026-04-09-00001",
    "frames": {
        "cam1": <bytes>,  # через shared memory
        "cam2": <bytes>,
        "cam3": <bytes>,
        "cam4": <bytes>
    },
    "recipe": "foil_290x10_opp"
}

# Результат инспекции
{
    "type": "inspection_result",
    "line_id": 1,
    "roll_id": "L1-2026-04-09-00001",
    "timestamp": 1712678400.169,
    "verdict": "REJECT",  # или "PASS"
    "defects": [
        {"class": "spot", "confidence": 0.92, "bbox": [120, 80, 45, 30], "camera": "cam1"},
        {"class": "wrinkle_opp", "confidence": 0.87, "bbox": [200, 150, 60, 20], "camera": "cam2"}
    ],
    "barcode": "4607001234567",
    "inspection_time_ms": 46
}

# Команда PLC
{
    "type": "plc_command",
    "line_id": 1,
    "action": "reject",  # или "pass", "speed_up", "speed_down", "e_stop"
    "timestamp": 1712678400.170
}
```

## 4. Shared Memory для кадров

Кадры 5MP (~10 MB raw) не должны передаваться через Queue (pickle overhead). Используем shared memory:

```python
# В CameraGrabProcess:
# Запись кадра в shared memory (SharedResourcesModule)
shm_key = f"frame_L{line_id}_{cam_id}"
self.shared_resources.write(shm_key, frame_bytes)

# В InspectionProcess:
# Чтение из shared memory (zero-copy если numpy)
frame = self.shared_resources.read(shm_key)
```

Фреймворк уже поддерживает это через `shared_resources_module`.

## 5. Конфигурация (ConfigStore)

```python
# Пример config для линии
class LineConfig(BaseModel):
    line_id: int = 1
    camera_ips: list[str] = ["192.168.1.101", "192.168.1.102", "192.168.1.103", "192.168.1.104"]
    plc_ip: str = "192.168.1.200"
    trigger_mode: str = "hardware"  # или "software"
    inspection_model: str = "yolov8m_foil_v1.pt"
    confidence_threshold: float = 0.5
    recipe_db: str = "recipes.db"

class SystemConfig(BaseModel):
    lines: list[LineConfig] = [LineConfig(line_id=i) for i in range(1, 5)]
    gpu_device: int = 0
    archive_path: str = "/data/archive"
    archive_retention_days: int = 365
    hmi_language: str = "ru"
```

## 6. Что нужно доработать в фреймворке

| Компонент | Текущее состояние | Что нужно | Сложность |
|-----------|-------------------|-----------|-----------|
| ProcessModule | Есть | Готов, без изменений | - |
| CameraGrab | UnifiedCameraProcess (USB/OpenCV) | Адаптация под Hikrobot GigE SDK (MVS) | Средняя |
| Inspection | ProcessorProcess (бутылки) | Новая логика детекции (рулоны, новые классы) | Средняя |
| GPU Inference | Внутри ProcessorProcess | Выделить в отдельный процесс (batching) | Средняя |
| PLC Bridge | Нет | Новый ProcessModule (pymodbus) | Средняя |
| Barcode | Нет | Новый ProcessModule (pyzbar) | Низкая |
| Archive | DatabaseProcess (SQLite) | Расширить: файловый архив + ретенция | Низкая |
| GUI | GuiProcess (PyQt5) | Новые экраны под задачу фольги | Высокая |
| Statistics | StatsManager (базовый) | Расширить: OEE, экспорт, dashboard | Средняя |
| Recipe Manager | Нет | Новый компонент: БД рецептов на 280 номенклатур | Средняя |
| Box Control | Нет (RobotSimulator) | Новый: контроль вложений + весовой | Низкая |

## 7. Масштабирование: от 1 до 4 линий

```python
# main.py — точка входа

launcher = SystemLauncher(stop_timeout=10.0)

# Общие процессы
launcher.add_process(*gpu_inference_process(GpuConfig()))
launcher.add_process(*plc_bridge_process(PlcConfig()))
launcher.add_process(*archive_process(ArchiveConfig()))
launcher.add_process(*statistics_process(StatsConfig()))
launcher.add_process(*gui_process(GuiConfig()))

# Процессы линий (масштабируем циклом)
for line_id in range(1, NUM_LINES + 1):
    line_cfg = LineConfig(line_id=line_id)
    launcher.add_process(*camera_grab_process(line_cfg))
    launcher.add_process(*inspection_process(line_cfg))
    launcher.add_process(*barcode_process(line_cfg))
    launcher.add_process(*line_control_process(line_cfg))

launcher.run()
```

**Итого процессов:** 5 общих + 4 × 4 линейных = **21 процесс** на одном ПК.
При 12C/20T i7-12700 — нагрузка распределится по ядрам. Большинство процессов idle 90% времени (ждут trigger от камеры).
