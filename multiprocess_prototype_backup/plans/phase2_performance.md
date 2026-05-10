# Plan: Phase 2 -- Performance & Scaling

**Date:** 2026-04-23
**Status:** DONE

## Overview

Фаза 2 нацелена на производительность и масштабируемость: end-to-end метрики latency,
динамическое разрешение SHM, batch INSERT в БД, масштабирование Processor (1 per Camera).
Зависит от Фазы 1 (ShmRegionSpec, heartbeat, cleanup -- завершены).

## Граф зависимостей

```
Phase 1 (DONE)
  |
  +-- Task 1.1 (ShmRegionSpec) --+--> Task 2.2 (динамическое разрешение SHM)
  |                               |
  |                               +--> Task 2.4 (Processor scaling -- использует ShmRegionSpec)
  |
  +-- Task 1.4 (heartbeat/restart) --> [Phase 3]
  
Task 2.1 (latency) -------> параллельно, независим
Task 2.3 (batch INSERT) ---> параллельно, независим
Task 2.2 (SHM resize) -----> зависит от 1.1 (DONE)
Task 2.4 (N processors) ---> зависит от 1.1 (DONE), наиболее сложная
```

## Порядок исполнения

### Параллельный блок A (независимые задачи)
- Task 2.1: Метрики latency (end-to-end) [DONE]
- Task 2.3: Batch INSERT в БД [DONE]

### Параллельный блок B (зависят от блока A только организационно)
- Task 2.2: Динамическое разрешение SHM per camera [DONE]

### Последовательный блок C (самая сложная, архитектурная)
- Task 2.4: Processor масштабирование (1 per Camera) [DONE]

---

## Детальные спецификации

### Task 2.1 -- Метрики latency (end-to-end)

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Измерять и отображать сквозную задержку от захвата кадра до отображения в GUI, с логированием percentiles.

**Контекст:**
Сейчас CameraService измеряет FPS, но нет данных о сквозной задержке (capture -> processor -> renderer -> GUI display). Без этих метрик невозможно диагностировать bottleneck. Timestamp `time.perf_counter()` нужно прокидывать через IPC-сообщения на каждом этапе pipeline. ВАЖНО: `time.perf_counter()` монотонный, но **не кросс-процессный** (разная точка отсчёта в каждом процессе). Для кросс-процессных измерений нужен `time.time()` или `time.monotonic()` (последний тоже не гарантирует кросс-процессность на всех ОС). Рекомендация: использовать `time.time()` для кросс-процессных timestamps, а `time.perf_counter()` для внутрипроцессных замеров (processor_start/end и т.п.).

**Файлы:**
- `services/camera/service.py` -- добавить `capture_ts` в метаданные `capture_and_publish()` (строка ~231, dict `notification_data`)
- `backend/processes/camera/adapter.py` -- прокинуть `capture_ts` в `send_frame_to_processor()`
- `services/processor/service.py` -- добавить `processor_start_ts`/`processor_end_ts` в `_build_detection_result()` и оба пути обработки (`_process_frame_legacy`, `_process_frame_via_chain`)
- `services/renderer/service.py` -- добавить `renderer_start_ts`/`renderer_end_ts` в `render_frame()`, прокинуть в notification dict
- `backend/processes/gui/handlers.py` -- новый handler `handle_latency_update` или расширение `_handle_new_frame` в `process.py`
- `backend/processes/gui/process.py` -- вычислить `gui_display_ts` и `e2e_latency` в `_handle_new_frame()`, отправить в window
- `services/metrics/latency.py` -- **новый файл**: класс `LatencyTracker` (кольцевой буфер значений, вычисление p50/p95/p99, периодическое логирование)
- `frontend/windows/main_window/window.py` -- отображение latency в StatusBar (строка ~219, метод `_update_status_bar` или новый permanent widget)

**Шаги:**

1. Создать `services/metrics/__init__.py` и `services/metrics/latency.py`:
   ```
   class LatencyTracker:
       __init__(self, log_interval_sec: float = 10.0, buffer_size: int = 1000)
       record(self, e2e_ms: float) -> None  # добавить в буфер
       percentiles(self) -> dict[str, float]  # {"p50": ..., "p95": ..., "p99": ...}
       maybe_log(self) -> None  # если прошло >= log_interval_sec, залогировать percentiles
   ```
   Использовать `collections.deque(maxlen=buffer_size)` для буфера. `numpy.percentile` или ручной расчёт через sorted.

2. В `services/camera/service.py`, метод `capture_and_publish()`:
   - После строки `timestamp = time.time()` (строка ~222) добавить `capture_ts = time.time()`
   - Добавить `"capture_ts": capture_ts` в `notification_data` dict (строка ~232)

3. В `services/processor/service.py`:
   - В `_process_frame_legacy()`: сохранить `processor_start_ts = time.time()` перед `detect()`, `processor_end_ts = time.time()` после. Прокинуть оба в `_build_detection_result()`.
   - В `_process_frame_via_chain()`: аналогично вокруг `runnable.execute()`.
   - В `_build_detection_result()`: добавить в result dict:
     - `"capture_ts": metadata.get("capture_ts")`
     - `"processor_start_ts": processor_start_ts`
     - `"processor_end_ts": processor_end_ts`

4. В `services/renderer/service.py`, метод `render_frame()`:
   - `renderer_start_ts = time.time()` в начале метода
   - `renderer_end_ts = time.time()` после `apply_detection_overlays()`
   - Добавить в `notification` dict: `capture_ts`, `processor_start_ts`, `processor_end_ts`, `renderer_start_ts`, `renderer_end_ts` -- все прокинуть из `data`

5. В `backend/processes/gui/process.py`, метод `_handle_new_frame()`:
   - После чтения кадров из SHM: `gui_display_ts = time.time()`
   - Вычислить: `e2e_latency_ms = (gui_display_ts - data.get("capture_ts", gui_display_ts)) * 1000`
   - Создать `LatencyTracker` в `_init_application_threads()` как `self._latency_tracker`
   - Вызвать `self._latency_tracker.record(e2e_latency_ms)` и `self._latency_tracker.maybe_log()`
   - Передать `e2e_latency_ms` в window через новый метод `update_latency()`

6. В `frontend/windows/main_window/window.py`:
   - Добавить `QLabel` для latency в StatusBar (permanent widget) в `_update_status_bar()` или `_init_ui()`
   - Реализовать `update_latency(self, latency_ms: float)` -- обновить label: `f"Latency: {latency_ms:.0f}ms"`
   - Рядом с существующим `update_camera_fps()` (строка ~290)

**Критерии приёмки:**
- [ ] В StatusBar отображается `Latency: Xms`, обновляется каждый кадр
- [ ] В логах каждые 10с: `Latency p50=XXms p95=XXms p99=XXms`
- [ ] `capture_ts` присутствует в IPC-payload `frame_ready`, `detection_result`, `rendered_frame_ready`
- [ ] Тест: `LatencyTracker` корректно считает p50/p95/p99 для известного набора данных
- [ ] Latency < 100мс при 25fps на simulator (проверить вручную)

**Вне scope:**
- Не менять логику FPS-измерения (уже работает)
- Не добавлять метрики в БД (только логи + StatusBar)
- Не менять IPC-протокол (только расширение payload дополнительными полями)

**Edge cases:**
- `capture_ts` отсутствует в data (старые сообщения) -- использовать `gui_display_ts` как fallback, latency = 0
- Пустой буфер LatencyTracker -- percentiles возвращают 0.0
- Кросс-процессный drift `time.time()` -- допустимо для прототипа, точность до нескольких мс

---

### Task 2.2 -- Динамическое разрешение SHM per camera

**Уровень:** Senior (Opus, normal thinking)
**Исполнитель:** teamlead
**Цель:** Поддержать два режима разрешения SHM (resize и native) с динамическим пересозданием при смене камеры в runtime.

**Контекст:**
Task 1.1 ввёл `ShmRegionSpec` -- размеры SHM per-region, но они фиксируются при старте. При переключении webcam 640->1080 в runtime SHM остаётся 640x480, а камера resize'ит каждый кадр. Нужен opt-in native-режим, при котором SHM пересоздаётся под нативное разрешение камеры. Это архитектурно сложная задача: нужна координация ProcessManager -> Camera -> Processor -> Renderer через IPC при пересоздании SHM-региона.

**Файлы:**
- `config/shm_region.py` -- добавить `ShmRegionSpec.with_size(new_w, new_h) -> ShmRegionSpec` (immutable copy с новыми размерами)
- `backend/processes/camera/config.py` -- добавить `CameraConfig.shm_native_resolution: bool = False`
- `services/camera/service.py` -- в `capture_and_publish()`: если native mode и frame.shape != SHM shape, отправить `shm_region_change_request` через порт; в resize mode -- resize как сейчас
- `services/camera/ports.py` -- добавить метод `request_shm_resize(new_width, new_height)` в `CameraOutputPort`
- `backend/processes/camera/adapter.py` -- реализовать `request_shm_resize()`: отправить IPC `shm_region_change_request` в `process_manager`
- `backend/processes/camera/process.py` -- handler для ответа `shm_region_changed` от ProcessManager (подтверждение пересоздания)
- `backend/processes/processor/process.py` -- handler для `shm_region_changed` (переоткрыть SHM handle через memory_manager)
- `backend/processes/renderer/process.py` -- handler для `shm_region_changed` (переоткрыть SHM handle)
- `frontend/windows/main_window/window.py` -- отображение актуального разрешения per camera в StatusBar

**Шаги:**

1. В `config/shm_region.py` добавить метод:
   ```python
   def with_size(self, width: int, height: int) -> "ShmRegionSpec":
       return ShmRegionSpec(name=self.name, width=width, height=height,
                            channels=self.channels, slots=self.slots)
   ```

2. В `CameraConfig` добавить поле `shm_native_resolution: bool = False`.

3. В `services/camera/service.py`:
   - В конструкторе сохранить `self._shm_native = config.get("shm_native_resolution", False)`
   - В `capture_and_publish()`: 
     - Если `self._shm_native` и frame.shape отличается от `(self._height, self._width)`:
       - Вызвать `self._out.request_shm_resize(frame.shape[1], frame.shape[0])`
       - Обновить `self._width`, `self._height`
       - НЕ resize'ить frame
     - Если не native -- resize как сейчас (без изменений)
   - Добавить `handle_shm_resized(new_w, new_h)` -- обновить внутренние размеры после подтверждения от ProcessManager

4. В `services/camera/ports.py` добавить `request_shm_resize(new_width: int, new_height: int) -> None` в ABC `CameraOutputPort`.

5. В `backend/processes/camera/adapter.py` реализовать `request_shm_resize()`:
   ```python
   def request_shm_resize(self, new_width: int, new_height: int) -> None:
       self._io.send_data("process_manager", "shm_region_change_request", {
           "camera_id": self._camera_id,
           "region_name": f"camera_{self._camera_id}_frame",
           "new_width": new_width,
           "new_height": new_height,
       })
   ```

6. На стороне ProcessManager (фреймворк): обработать `shm_region_change_request`:
   - Unlink старый SHM-регион
   - Reallocate с новым shape
   - Отправить `shm_region_changed` в camera, processor, renderer с новыми размерами

7. В `backend/processes/processor/process.py` и `renderer/process.py`:
   - Добавить handler для `shm_region_changed`:
     - Закрыть старый SHM handle
     - Переоткрыть через `memory_manager` с новым shape
     - Обновить внутренний target_width/height сервиса

8. В StatusBar добавить `"Resolution: 640x480"` label, обновляемый через handler `handle_resolution_update` при каждом `rendered_frame_ready` (поля width/height уже есть в notification).

**Критерии приёмки:**
- [ ] resize-режим (default): камера 1920x1080 -> SHM 640x480, кадр масштабирован (текущее поведение сохранено)
- [ ] native-режим: `shm_native_resolution: true` в конфиге -> SHM пересоздан под нативное разрешение камеры
- [ ] Переключение камеры в runtime (switch_camera_type) с native mode -> SHM пересоздан, все consumers переключились без crash
- [ ] GUI: StatusBar показывает актуальное разрешение per camera
- [ ] Тест: mock ProcessManager, отправить shm_region_change_request -> подтверждение shm_region_changed -> camera/processor/renderer обновлены

**Вне scope:**
- Не менять MemoryManager фреймворка (reallocate_region -- отдельная задача фреймворка, если нет -- сделать unlink+create)
- Не реализовывать hot-swap нескольких SHM-регионов одновременно
- Не менять ring_buffer.py (он уже работает с любым shape через memory_manager)

**Edge cases:**
- Camera отправляет shm_region_change_request, а ProcessManager ещё не ответил -- camera продолжает resize к старым размерам, не блокируется
- Несколько быстрых переключений подряд -- обрабатывается последний request, промежуточные отбрасываются (debounce по camera_id)
- native mode + hikvision 4K -> SHM 3840x2160 -> проверить memory limits (warning в лог если > 50MB per region)

**Зависимости:** Task 1.1 (ShmRegionSpec -- DONE)

---

### Task 2.3 -- Batch INSERT в БД

**Уровень:** Middle (Sonnet, normal thinking)
**Исполнитель:** developer
**Цель:** Буферизовать детекции и записывать пачками через executemany() вместо поштучных INSERT, с гарантией flush при shutdown.

**Контекст:**
При 25fps x 5 детекций получается 125 INSERT/с. Текущая реализация в `DatabaseService.save_detections()` делает отдельный INSERT на каждую детекцию (цикл, строка 24-34 в `services/database/service.py`). SQLite WAL помогает, но batch INSERT через executemany() существенно быстрее. Буфер нужно flush'ить по двум условиям: размер >= batch_size ИЛИ время >= flush_interval.

**Файлы:**
- `services/database/service.py` -- добавить буфер `_pending`, логику flush, метод `flush()`, изменить `save_detections()`
- `backend/processes/database/config.py` -- добавить `batch_size: int = 50`, `flush_interval_sec: float = 1.0`
- `backend/processes/database/process.py` -- прокинуть batch_size/flush_interval в DatabaseService, flush при shutdown
- `backend/processes/database/commands.py` -- добавить команду `db.flush` для принудительного flush

**Шаги:**

1. В `backend/processes/database/config.py` добавить поля:
   ```python
   batch_size: int = 50
   flush_interval_sec: float = 1.0
   ```

2. В `services/database/service.py` переделать `DatabaseService`:
   - Добавить в `__init__`:
     ```python
     self._pending: list[dict] = []
     self._batch_size: int = batch_size
     self._flush_interval: float = flush_interval_sec
     self._last_flush_time: float = time.time()
     ```
   - Изменить `save_detections()`:
     - Валидировать каждую детекцию через `DetectionSchema.model_validate(d)`
     - Добавить `row = entity.model_dump(exclude_none=True, exclude={"id"})` в `self._pending`
     - Вызвать `self._maybe_flush()`
     - Возвращать `{"status": "buffered", "pending": len(self._pending)}`
   - Добавить `_maybe_flush()`:
     ```python
     def _maybe_flush(self) -> None:
         now = time.time()
         if len(self._pending) >= self._batch_size or \
            (now - self._last_flush_time) >= self._flush_interval:
             self.flush()
     ```
   - Добавить `flush()`:
     ```python
     def flush(self) -> dict:
         if not self._pending:
             return {"status": "ok", "rows": 0}
         try:
             # executemany: все строки с одинаковыми столбцами
             first = self._pending[0]
             cols = ", ".join(f'"{k}"' for k in first.keys())
             placeholders = ", ".join(f":{k}" for k in first.keys())
             sql = f'INSERT INTO "detections" ({cols}) VALUES ({placeholders})'
             self._out.execute_many(sql, self._pending)
             count = len(self._pending)
             self._pending.clear()
             self._last_flush_time = time.time()
             return {"status": "success", "rows": count}
         except Exception as e:
             self._out.log_error(f"db.flush failed: {e}")
             return {"status": "error", "reason": str(e)}
     ```

3. В `services/database/ports.py` (или где определён `DatabaseOutputPort`):
   - Добавить метод `execute_many(sql: str, params: list[dict]) -> None`

4. В `backend/processes/database/adapter.py`:
   - Реализовать `execute_many()` через `self._sql_manager.execute_many()` или `self._sql_manager.execute()` с executemany
   - Проверить поддержку executemany в SQLManager фреймворка -- если нет, обернуть в транзакцию с циклом execute

5. В `backend/processes/database/process.py`:
   - В `_init_custom_managers()` прокинуть `batch_size` и `flush_interval_sec` из app_cfg в DatabaseService:
     ```python
     self._service = DatabaseService(
         output=adapter,
         batch_size=app_cfg.get("batch_size", 50),
         flush_interval_sec=app_cfg.get("flush_interval_sec", 1.0),
     )
     ```
   - В `shutdown()` перед `sql_manager.shutdown()` вызвать `self._service.flush()`

6. В `backend/processes/database/commands.py`:
   - Добавить `"db.flush": lambda msg: service.flush()` в command table

7. Добавить периодический flush по таймеру (если нет непрерывного потока детекций):
   - В `DatabaseProcess` добавить worker thread (или проверять таймер при каждом receive_message) который вызывает `service._maybe_flush()` каждые `flush_interval_sec`

**Критерии приёмки:**
- [ ] При 25fps x 5 детекций: INSERT пачками по ~50 записей, не поштучно
- [ ] При shutdown (graceful): последний batch flush'ится, данные не теряются
- [ ] Команда `db.flush` принудительно flush'ит буфер
- [ ] Тест: добавить 1000 детекций -> все 1000 в БД после flush
- [ ] Тест: batch_size=10, добавить 25 детекций -> 2 flush'а по 10, 5 в буфере до таймера/shutdown
- [ ] Тест: flush_interval=0.5, добавить 3 детекции, подождать 0.6с -> flush вызван

**Вне scope:**
- Не менять DetectionSchema
- Не менять SQLManager фреймворка (работать через его API)
- Не добавлять batch для других таблиц (только detections)

**Edge cases:**
- Пустой буфер при shutdown -- flush ничего не делает, не crash
- Разные столбцы в разных детекциях (exclude_none) -- все rows должны иметь одинаковый набор ключей для executemany; при несовпадении -- fallback на поштучный INSERT
- Ошибка в середине batch -- залогировать, не терять весь batch (retry или сохранить failed rows)

---

### Task 2.4 -- Processor масштабирование (Вариант A: 1 per Camera)

**Уровень:** Senior+ (Opus, extended thinking)
**Исполнитель:** teamlead
**Цель:** Запускать N ProcessorProcess (по одному на камеру), каждая Camera отправляет frame_ready в свой Processor, все Processor'ы шлют detection_result в общий Renderer.

**Контекст:**
Сейчас один ProcessorProcess обрабатывает кадры от всех камер. При 4 камерах x 25fps = 100 кадров/с -- bottleneck. Нужно масштабирование: N Processor'ов с уникальными именами `processor_0`, `processor_1`, ...
Каждый привязан к своей камере. Renderer остаётся один -- принимает detection_result от всех Processor'ов. Это архитектурное изменение: меняется конфигурация процессов, IPC-маршрутизация, SHM-ownership.

**ВАЖНО:** Текущий `AppConfig.processor` -- единственный `ProcessorConfig`. Нужно заменить на `list[ProcessorConfig]` или генерировать N конфигов.

**Файлы:**
- `config/app.py` -- заменить `processor: ProcessorConfig` на `processors: list[ProcessorConfig]`, изменить `all_process_configs()`, `model_post_init()` для генерации N процессоров
- `backend/processes/processor/config.py` -- добавить `camera_id: int = 0`, изменить `process_name` на `f"processor_{camera_id}"`, добавить `shm_region()` метод для per-camera SHM масок
- `backend/processes/camera/adapter.py` -- изменить target в `send_frame_to_processor()`: `processor` -> `f"processor_{self._camera_id}"`
- `backend/processes/processor/process.py` -- `FrameShmMiddleware` owner/slot привязать к конкретной camera_id (сейчас hardcoded `owner="camera"`, `slot="camera_frame"` -- нужно `owner=f"camera_{camera_id}"`, `slot=f"camera_{camera_id}_frame"`)
- `backend/processes/processor/adapter.py` -- target `"renderer"` остаётся без изменений (один Renderer)
- `backend/processes/renderer/process.py` -- `FrameShmMiddleware` должен уметь читать SHM от разных camera owners; сейчас hardcoded `owner="camera"`, `slot="camera_frame"` -- нужно динамически определять owner из данных сообщения
- `main.py` -- без изменений (уже итерирует `all_process_configs()`)
- `backend/processes/renderer/config.py` -- без изменений (memory layout рендерера не зависит от количества процессоров)

**Шаги:**

1. **Конфигурация (config/app.py):**
   - Заменить `processor: ProcessorConfig = ProcessorConfig()` на `processors: list[ProcessorConfig] = []`
   - В `model_post_init()`: если `processors` пуст, создать N ProcessorConfig (один per camera):
     ```python
     if not self.processors:
         processors = []
         for cam in self.cameras:
             processors.append(ProcessorConfig(
                 camera_id=cam.camera_id,
                 resolution_width=cam.resolution_width,
                 resolution_height=cam.resolution_height,
             ))
         object.__setattr__(self, "processors", processors)
     ```
   - Обновить `all_process_configs()`:
     ```python
     configs = [*self.cameras, *self.processors, ...]
     ```
   - Обновить `all_shm_regions()` -- процессоры тоже предоставляют регионы через `shm_region()`
   - Обеспечить backward compat: если `processor:` (единственный) указан в старых конфигах, преобразовать в `processors: [processor]`

2. **ProcessorConfig (backend/processes/processor/config.py):**
   - Добавить `camera_id: int = 0`
   - Изменить `process_name` на динамический:
     ```python
     def model_post_init(self, __context):
         object.__setattr__(self, "process_name", f"processor_{self.camera_id}")
     ```
   - Обновить `memory` property -- SHM слот маски привязан к camera_id:
     ```python
     @property
     def memory(self) -> dict:
         return {
             f"processor_{self.camera_id}_mask": (self.resolution_height, self.resolution_width, 3),
             "coll": 2,
         }
     ```
   - Добавить `shm_region() -> ShmRegionSpec` для маски processor'а

3. **CameraAdapter (backend/processes/camera/adapter.py):**
   - Изменить `send_frame_to_processor()`:
     ```python
     def send_frame_to_processor(self, data: dict) -> None:
         data_with_id = {**data, "camera_id": self._camera_id}
         target = f"processor_{self._camera_id}"
         self._io.send_data(target, "frame_ready", data_with_id)
     ```

4. **ProcessorProcess (backend/processes/processor/process.py):**
   - В `_init_application_threads()`:
     - Получить `camera_id` из конфига: `camera_id = app_cfg.get("camera_id", 0)`
     - `FrameShmMiddleware` -- owner и slot привязать к camera_id:
       ```python
       self._recv_frame_mw = FrameShmMiddleware(
           self.memory_manager,
           owner=f"camera_{camera_id}",
           slot=f"camera_{camera_id}_frame",
       )
       ```
     - Mask middleware -- slot привязать к camera_id:
       ```python
       self._send_mask_mw = FrameShmMiddleware(
           self.memory_manager,
           owner=self.name,
           slot=f"processor_{camera_id}_mask",
       )
       ```

5. **ProcessorAdapter (backend/processes/processor/adapter.py):**
   - `send_detection_to_renderer()` -- без изменений (target "renderer" один)
   - `write_mask_to_shm()` -- slot имя должно соответствовать конфигу:
     ```python
     def __init__(self, process, camera_id: int = 0):
         self._io = ProcessIO(process)
         self._camera_id = camera_id
         
     def write_mask_to_shm(self, mask):
         slot = f"processor_{self._camera_id}_mask"
         result = self._io.write_frames_to_shm(self._io._p.name, slot, [mask])
         ...
     ```

6. **RendererProcess (backend/processes/renderer/process.py):**
   - Проблема: `FrameShmMiddleware(owner="camera", slot="camera_frame")` -- hardcoded. При N камерах каждый detection_result приходит от другого processor'а, но ссылается на SHM другой камеры.
   - Решение: убрать FrameShmMiddleware для camera frame из инициализации. Вместо этого в `_render_worker()` определять owner/slot из данных сообщения (`data.get("camera_id")`) и читать напрямую через memory_manager:
     ```python
     camera_id = data.get("camera_id", 0)
     images = mm.read_images(f"camera_{camera_id}", f"camera_{camera_id}_frame", shm_index, n=1)
     ```
   - Аналогично для mask -- определять processor по camera_id:
     ```python
     mask_owner = f"processor_{camera_id}"
     mask_slot = f"processor_{camera_id}_mask"
     ```

7. **Backward compat (config/app.py):**
   - Добавить `@property processor` для backward compat (возвращает `processors[0]` если есть)
   - Если кто-то использует `app.processor` -- deprecation warning

**Критерии приёмки:**
- [ ] 4 камеры-симулятора -> 4 processor'а (`processor_0` ... `processor_3`), каждый обрабатывает кадры только своей камеры
- [ ] Detection results от всех processor'ов -> один Renderer, корректно отображаются в GUI
- [ ] SHM масок: `processor_0_mask`, `processor_1_mask`, ... -- отдельные регионы
- [ ] 1 камера (default) -- всё работает как раньше (backward compat)
- [ ] Тест: `AppConfig(cameras=[cam0, cam1])` -> `all_process_configs()` содержит `processor_0`, `processor_1`
- [ ] Тест: `CameraAdapter(camera_id=1).send_frame_to_processor()` -> target = `"processor_1"`
- [ ] При 4 камерах x 25fps -- все кадры обрабатываются (нет голодания)

**Вне scope:**
- Не реализовывать Вариант B (Shared Processor Pool) -- отдельная задача
- Не менять worker_pool (ProcessorWorker) -- они остаются привязаны к отдельному processor'у
- Не менять Renderer на N рендереров -- один Renderer достаточно для прототипа
- Не менять GUI pipeline -- он уже поддерживает multi-camera через camera_id

**Edge cases:**
- Camera 0 запущена, Camera 1 ещё нет -- processor_1 idle, не crash
- Processor crash -> auto-restart (Phase 1 heartbeat) -> processor должен переинициализировать SHM middleware
- Разные разрешения камер -> каждый processor получает свой resolution_width/height из конфига
- worker_pool_size > 0 + N processors: каждый processor создаёт свои worker'ы -- нужно уникальные имена worker-процессов

**Зависимости:** Task 1.1 (ShmRegionSpec -- DONE)

---

## Риски и ограничения

1. **Task 2.2 (native SHM resize):** Зависит от возможностей MemoryManager фреймворка. Если `reallocate_region()` не поддерживается -- нужен workaround через unlink + create. Возможно потребуется изменение фреймворка (scope creep).

2. **Task 2.4 (N Processors):** Самая рискованная задача. Меняет IPC-маршрутизацию и SHM-ownership. Нужно тщательное тестирование backward compat (1 камера) и multi-camera (4 камеры). Рекомендация: worktree isolation.

3. **Task 2.3 (Batch INSERT):** Низкий риск, но нужно проверить поддержку executemany в SQLManager фреймворка. Если нет -- обернуть в транзакцию.

4. **Кросс-процессные timestamps (Task 2.1):** `time.time()` имеет разрешение ~1мс и может иметь jitter при NTP sync. Для прототипа приемлемо.

5. **Порядок реализации:** Tasks 2.1 и 2.3 полностью независимы -- можно делать параллельно. Task 2.2 можно начать сразу (зависимость от 1.1 уже выполнена). Task 2.4 лучше делать последней -- она самая сложная и может повлиять на результаты Tasks 2.1/2.2.
