# Phase 5: Data Pipeline Architecture

**Date:** 2026-05-05
**Status:** DRAFT

## Overview

Рефакторинг GenericProcess: замена текущей модели (плагины сами работают с IPC/SHM через `register_message_handler`, `_pending_frame_info`, `mm.read_images()`) на чистую data pipeline архитектуру с тремя воркерами. Плагины становятся чистыми функциями `process(items) -> items` без знания об IPC/SHM.

## Текущая проблема

Каждый processing-плагин дублирует один и тот же boilerplate:
1. `register_message_handler("frame_ready", self._on_frame_ready)` -- подписка на IPC
2. `self._pending_frame_info` -- буфер между handler и worker
3. `mm.read_images(owner, shm_name, shm_index)` -- чтение из SHM
4. `mm.write_images(owner, slot, [result], 0)` -- запись в SHM
5. `self._ctx.io.send_data(target, "frame_ready", out_data)` -- отправка IPC
6. Свой worker loop с `stop_event`/`pause_event`

Это нарушает SRP (плагин знает про SHM layout, IPC протокол), создает дублирование (70+ строк boilerplate в каждом плагине) и затрудняет тестирование.

## Целевая архитектура

```
GenericProcess
  +-- System Worker (есть)   -- receive(channel_types=['system']), команды
  +-- Data Worker (новый)    -- receive(channel_types=['data']), SHM read, InspectorManager
  +-- Chain Worker (новый)   -- plugin.process(items), SHM write, IPC send
```

**Data flow:**
```
IPC msg (frame_ready/region_ready)
  --> Data Worker: SHM middleware читает frame --> item = {"frame": ndarray, **meta}
  --> InspectorManager: буферизация по seq_id (если fan-in)
  --> internal queue: list[dict] (готовая коллекция)
  --> Chain Worker: plugin.process(items) --> SHM write --> IPC send
```

## Новый контракт плагина

```python
class ProcessModulePlugin:
    # Существующие: name, category, inputs, outputs, commands, configure(), start(), shutdown()

    def process(self, items: list[dict]) -> list[dict]:
        """Чистая обработка. items = [{"frame": ndarray, ...meta}].
        Без IPC, без SHM, без PluginContext.
        Default: return items (pass-through)."""

    def produce(self) -> list[dict]:
        """Только для source-плагинов. Генерация items.
        Default: raise NotImplementedError."""
```

## Порядок выполнения

### Phase 5.1: Инфраструктура (фреймворк)
- Task 5.1: InspectorManager
- Task 5.2: Расширение ProcessModulePlugin (process/produce)
- Task 5.3: Data Worker + Chain Worker в GenericProcess

### Phase 5.2: Миграция плагинов (прототип)
- Task 5.4: CapturePlugin --> produce()
- Task 5.5: Processing-плагины --> process()
- Task 5.6: StitcherPlugin --> process() (fan-in)
- Task 5.7: Output-плагины --> process()

### Phase 5.3: Интеграция и тесты
- Task 5.8: Topology обновление и e2e тест

---

## Задачи

### Task 5.1 -- InspectorManager

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** Создать InspectorManager -- компонент буферизации items по seq_id для fan-in сценариев
**Context:** В текущей архитектуре stitcher сам буферизует регионы по seq_id с timeout. Эта логика должна быть вынесена в универсальный менеджер внутри GenericProcess. InspectorManager принимает item из Data Worker, проверяет наличие `total_regions` в метаданных, буферизует по seq_id, и когда коллекция готова -- отдает `list[dict]` в очередь для Chain Worker.

**Files:**
- `multiprocess_framework/modules/process_module/generic/inspector_manager.py` -- СОЗДАТЬ
- `multiprocess_framework/modules/process_module/generic/__init__.py` -- добавить экспорт
- `multiprocess_framework/modules/process_module/tests/test_inspector_manager.py` -- СОЗДАТЬ

**Steps:**
1. Создать класс `InspectorManager` с интерфейсом:
   ```python
   class InspectorManager:
       def __init__(self, timeout_sec: float = 0.5, on_ready: Callable[[list[dict]], None] = None):
           """on_ready -- callback для отправки готовых коллекций в Chain Worker."""

       def on_item(self, item: dict) -> None:
           """Принять один item. Если fan-in не нужен (нет total_regions) -- сразу вызывает on_ready([item]).
           Если fan-in (total_regions > 0) -- буферизует по seq_id, вызывает on_ready когда все собраны или timeout."""

       def check_timeouts(self) -> None:
           """Проверить и выдать просроченные коллекции. Вызывается периодически из Data Worker."""
   ```
2. Буферизация: `dict[int, dict[str, dict]]` -- `{seq_id: {region_name: item}}`
3. Коллекция готова когда: `len(buffer[seq_id]) >= total_regions` или `time.monotonic() - timestamp > timeout_sec`
4. Thread-safety: `threading.Lock` на буфер (Data Worker может вызывать on_item из одного потока, но check_timeouts может вызываться параллельно)
5. Очистка старых записей (>2x timeout) в check_timeouts
6. Логирование через callback `log_info`/`log_error` (передаются в конструктор)

**Acceptance criteria:**
- [ ] Без fan-in (нет `total_regions` в item): `on_item({"frame": ..., "seq_id": 1})` --> немедленно вызывает `on_ready([item])`
- [ ] С fan-in: 3 items с `total_regions=3, seq_id=5` --> вызывает `on_ready([item1, item2, item3])` после третьего
- [ ] Timeout: 2 из 3 items + timeout --> вызывает `on_ready([item1, item2])` при check_timeouts
- [ ] Thread-safe: concurrent on_item не вызывает race condition
- [ ] Тесты: >= 8 тестов (happy path, fan-in, timeout, cleanup, thread-safety)

**Out of scope:** Не менять существующие файлы GenericProcess (это Task 5.3). Не трогать IPC/SHM.
**Edge cases:** total_regions=0 (трактовать как "нет fan-in"), total_regions=1 (один item = готово), дублирование region_name в одном seq_id (перезаписать с warning)
**Dependencies:** Нет

---

### Task 5.2 -- Расширение ProcessModulePlugin

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Добавить методы `process()` и `produce()` в базовый класс ProcessModulePlugin
**Context:** Новый контракт плагина: processing-плагины реализуют `process(items) -> items`, source-плагины реализуют `produce() -> items`. Старые методы (`configure`, `start`, `shutdown`) остаются для обратной совместимости и lifecycle.

**Files:**
- `multiprocess_framework/modules/process_module/plugins/base.py` -- добавить методы

**Steps:**
1. Добавить в класс `ProcessModulePlugin` метод `process()`:
   ```python
   def process(self, items: list[dict]) -> list[dict]:
       """Обработка items. Override в processing/output-плагинах.
       Default: pass-through (return items).
       items -- список {"frame": ndarray, ...metadata}.
       Чистая обработка: без IPC, без SHM, без PluginContext."""
       return items
   ```
2. Добавить метод `produce()`:
   ```python
   def produce(self) -> list[dict]:
       """Генерация items. Override в source-плагинах.
       Default: raise NotImplementedError."""
       raise NotImplementedError(f"Plugin '{self.name}' does not implement produce()")
   ```
3. Добавить property `is_source` -> bool: `return self.category == "source"`
4. НЕ делать process/produce абстрактными (чтобы не ломать существующие плагины вроде heartbeat)

**Acceptance criteria:**
- [ ] `process()` существует с default pass-through
- [ ] `produce()` существует с default NotImplementedError
- [ ] `is_source` property работает
- [ ] Существующие плагины (heartbeat, frame_counter) не ломаются -- они не переопределяют process/produce и это OK

**Out of scope:** Не менять плагины прототипа (это Task 5.4-5.7). Не удалять старые абстрактные методы configure/start.
**Dependencies:** Нет

---

### Task 5.3 -- Data Worker + Chain Worker в GenericProcess

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Добавить Data Worker и Chain Worker в GenericProcess, интегрировать InspectorManager, переключить data flow с прямых message_handler на pipeline через внутреннюю очередь
**Context:** Это центральная задача рефакторинга. Data Worker заменяет текущий `_data_receiver_loop` -- он не только вызывает `router_manager.receive()`, но и превращает IPC-сообщения в items (через SHM middleware) и передает в InspectorManager. Chain Worker получает готовые `list[dict]` из очереди и прогоняет через `plugin.process()`, затем записывает результат в SHM и отправляет IPC.

**Files:**
- `multiprocess_framework/modules/process_module/generic/generic_process.py` -- рефакторинг
- `multiprocess_framework/modules/process_module/generic/generic_process_config.py` -- возможно расширить конфиг (chain_targets, shm_slot_prefix)

**Steps:**
1. Добавить `import queue` и создать `self._chain_queue = queue.Queue(maxsize=64)` -- внутренняя очередь между Data Worker и Chain Worker
2. Создать `InspectorManager` в `_init_application_threads()` с callback `on_ready=self._chain_queue.put`
3. Рефакторить `_data_receiver_loop` в новый `_data_worker_loop`:
   - Вызывает `router_manager.receive(channel_types=["data"])` как раньше
   - НО: вместо диспатча в message_handler'ы плагинов -- собирает сообщения, формирует items:
     ```python
     item = {"frame": msg.get("frame"), **msg.get("data", {})}
     ```
   - Передает item в `inspector_manager.on_item(item)`
   - Периодически вызывает `inspector_manager.check_timeouts()`
4. Создать `_chain_worker_loop`:
   - Ожидает `self._chain_queue.get(timeout=0.05)`
   - Получает `list[dict]` (items)
   - Прогоняет через каждый plugin в порядке объявления:
     ```python
     for plugin in self._plugins:
         if plugin.is_source:
             continue  # source не участвует в chain
         items = plugin.process(items)
         if not items:
             break
     ```
   - После chain: для каждого item с frame -- SHM write через `memory_manager.write_images()`
   - IPC send результата в targets (из конфига процесса или из item["target"])
5. Для source-плагинов: создать `_source_worker_loop`:
   - Вызывает `plugin.produce()` в цикле
   - Для каждого item: SHM write + IPC send (через `self._ctx.io.send_data()`)
   - Заменяет текущий подход CapturePlugin с собственным worker
6. Обратная совместимость: если плагин переопределил configure() с register_message_handler -- это нормально, Data Worker просто не будет формировать items для таких сообщений (handler вызовется в receive). Постепенная миграция.
7. Определить как из config/topology берутся targets для отправки результата chain. Варианты:
   - `process_config.chain_targets: list[str]` -- в конфиге процесса
   - Из item["target"] -- каждый item может указать свой target
   - Fallback: `wires` из topology задают routing

**Acceptance criteria:**
- [ ] Data Worker запускается и получает DATA-сообщения
- [ ] SHM middleware по-прежнему читает frame из SHM в msg["frame"]
- [ ] InspectorManager буферизует items с total_regions
- [ ] Chain Worker прогоняет items через plugin.process()
- [ ] Результат записывается в SHM и отправляется по IPC
- [ ] Source-плагины работают через produce() loop
- [ ] Обратная совместимость: heartbeat и frame_counter (не переопределившие process()) работают как pass-through
- [ ] Старый `_data_receiver_loop` удален

**Out of scope:** Не мигрировать конкретные плагины (это Tasks 5.4-5.7). Не менять system_threads.py.
**Edge cases:**
- chain_queue полна (maxsize=64): Data Worker блокируется на put с timeout, логирует warning
- plugin.process() бросает exception: логировать, пропускать items (не крашить worker)
- items пустой после plugin.process(): прервать chain, не отправлять IPC
- Source-плагин + processing-плагин в одном процессе: source генерирует, processing обрабатывает
**Dependencies:** Task 5.1, Task 5.2

---

### Task 5.4 -- CapturePlugin: миграция на produce()

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Переписать CapturePlugin на новый контракт: produce() вместо собственного worker + SHM write + IPC send
**Context:** CapturePlugin -- source-плагин. В новой архитектуре он реализует `produce()`, а SHM write + IPC send делает GenericProcess._source_worker_loop(). Capture loop (cv2.read) остается в produce().

**Files:**
- `multiprocess_prototype_2/plugins/capture/plugin.py` -- рефакторинг

**Steps:**
1. Реализовать `produce()`:
   ```python
   def produce(self) -> list[dict]:
       """Захватить один кадр с камеры. Возвращает items."""
       if not self._is_capturing or self._cap is None:
           return []
       ret, frame = self._cap.read()
       if not ret or frame is None:
           return []
       # Resize если нужно
       if frame.shape[1] != self._width or frame.shape[0] != self._height:
           frame = cv2.resize(frame, (self._width, self._height))
       self._frame_count += 1
       return [{
           "frame": frame,
           "camera_id": self._camera_id,
           "frame_id": self._frame_count,
           "timestamp": time.monotonic(),
       }]
   ```
2. Убрать `_capture_loop` (worker создается GenericProcess)
3. В `start()`: убрать создание capture_worker -- GenericProcess сам создаст source_worker
4. Оставить `configure()`: ring buffer (SHM pre-allocation), команды start_capture/stop_capture
5. Оставить `_start_capture()` / `_stop_capture()` -- управление камерой через команды
6. Убрать `_ctx.io.send_data()` -- GenericProcess отправляет
7. Убрать прямую SHM запись через RingBufferWriter -- GenericProcess пишет через стандартный механизм
   - НО: RingBufferWriter нужен для pre-allocation. Оставить pre-allocation в configure(), а запись делегировать GenericProcess
   - Альтернатива: передавать ring_buffer hint в item metadata, GenericProcess использует его

**Acceptance criteria:**
- [ ] `produce()` возвращает `[{"frame": ndarray, "camera_id": int, "frame_id": int, "timestamp": float}]`
- [ ] Нет прямого обращения к `io.send_data()` или `memory_manager`
- [ ] `is_source == True`
- [ ] Команды start_capture/stop_capture работают
- [ ] FPS throttle обеспечивается GenericProcess (через target_interval в config)

**Out of scope:** Не менять GenericProcess (уже сделано в 5.3). Не менять config.py.
**Edge cases:** Камера не открыта -- produce() возвращает []. auto_start=True -- _start_capture() вызывается в start().
**Dependencies:** Task 5.2, Task 5.3

---

### Task 5.5 -- Processing-плагины: миграция на process()

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Переписать processing-плагины (resize, grayscale, negative, flip, color_mask, frame_counter) на чистый process(items) -> items
**Context:** Каждый плагин сейчас содержит 70+ строк boilerplate (message_handler, pending_info, SHM read/write, worker loop, IPC send). В новой архитектуре все это заменяется на одну функцию process().

**Files:**
- `multiprocess_prototype_2/plugins/resize/plugin.py`
- `multiprocess_prototype_2/plugins/grayscale/plugin.py`
- `multiprocess_prototype_2/plugins/negative/plugin.py`
- `multiprocess_prototype_2/plugins/flip/plugin.py`
- `multiprocess_prototype_2/plugins/color_mask/plugin.py`
- `multiprocess_prototype_2/plugins/frame_counter/plugin.py`

**Steps:**
1. **resize/plugin.py**: Заменить весь IPC/SHM boilerplate на:
   ```python
   def process(self, items: list[dict]) -> list[dict]:
       result = []
       for item in items:
           frame = item.get("frame")
           if frame is None:
               result.append(item)
               continue
           # target size calculation (уже есть)
           resized = cv2.resize(frame, (new_w, new_h), interpolation=self._interp)
           result.append({**item, "frame": resized, "width": new_w, "height": new_h})
       return result
   ```
   Убрать: `_on_frame_ready`, `_process_loop`, `_pending_frame_info`, `_ctx`, создание worker в start(), `register_message_handler` в configure(). Оставить configure() для чтения конфига (scale_factor, interpolation).

2. **grayscale/plugin.py**: Аналогично:
   ```python
   def process(self, items):
       return [{**item, "frame": cv2.cvtColor(cv2.cvtColor(item["frame"], cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)} for item in items if item.get("frame") is not None]
   ```
   Убрать режим standalone/region -- не нужен, GenericProcess маршрутизирует.

3. **negative/plugin.py**:
   ```python
   def process(self, items):
       return [{**item, "frame": np.asarray(255 - item["frame"], dtype=np.uint8)} for item in items if item.get("frame") is not None]
   ```

4. **flip/plugin.py**:
   ```python
   def process(self, items):
       return [{**item, "frame": cv2.flip(item["frame"], 0)} for item in items if item.get("frame") is not None]
   ```

5. **color_mask/plugin.py**: 
   ```python
   def process(self, items):
       result = []
       for item in items:
           frame = item.get("frame")
           if frame is None: continue
           hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
           mask = cv2.inRange(hsv, self._lower, self._upper)
           mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
           result.append({**item, "frame": mask_bgr})
       return result
   ```
   Оставить команду `set_hsv_range` и её регистрацию в configure().

6. **frame_counter/plugin.py**: Оставить process() как pass-through с подсчетом:
   ```python
   def process(self, items):
       self._frame_count += len(items)
       # ... FPS log ...
       return items
   ```
   Убрать register_message_handler.

7. Для каждого плагина:
   - Убрать: `register_message_handler`, `_pending_frame_info`, `_ctx`, worker creation в start(), `_process_loop`, `io.send_data`, `mm.read_images`, `mm.write_images`
   - Оставить: `configure()` для чтения конфига, `start()` (пустой или no-op), `shutdown()` (пустой или cleanup)
   - configure() больше НЕ использует ctx.router_manager, ctx.memory_manager, ctx.worker_manager

**Acceptance criteria:**
- [ ] Каждый плагин имеет `process(items) -> items`
- [ ] Ни один processing-плагин не обращается к `ctx.router_manager`, `ctx.memory_manager`, `ctx.io`, `ctx.worker_manager`
- [ ] Каждый плагин <= 60 строк (сейчас 100-180)
- [ ] color_mask сохраняет runtime-команду set_hsv_range
- [ ] frame_counter считает кадры через process()

**Out of scope:** Не трогать capture (Task 5.4), stitcher (Task 5.6), database/frame_saver (Task 5.7).
**Dependencies:** Task 5.2

---

### Task 5.6 -- StitcherPlugin: миграция на process() (fan-in)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Переписать StitcherPlugin на process(items) -> items, используя InspectorManager для буферизации
**Context:** Stitcher -- единственный плагин с fan-in логикой. Сейчас он сам буферизует регионы по seq_id. В новой архитектуре буферизация делается InspectorManager (Task 5.1), а stitcher получает уже готовую коллекцию items.

**Files:**
- `multiprocess_prototype_2/plugins/stitcher/plugin.py` -- рефакторинг

**Steps:**
1. Реализовать `process(items)`:
   ```python
   def process(self, items: list[dict]) -> list[dict]:
       """items -- коллекция регионов (уже собранная InspectorManager).
       Склеить на canvas по координатам."""
       canvas = self._stitch(items)
       if canvas is None:
           return []
       # Вернуть один item с canvas
       return [{
           "frame": canvas,
           "camera_id": self._camera_id,
           "seq_id": items[0].get("seq_id", 0),
           "frame_id": items[0].get("frame_id", 0),
           "timestamp": time.monotonic(),
       }]
   ```
2. Рефакторить `_stitch()`: вместо чтения из SHM по shm_name -- брать frame прямо из item:
   ```python
   def _stitch(self, items: list[dict]) -> np.ndarray | None:
       # canvas size из metadata
       # для каждого item: frame = item["frame"], coords = item["original_x"], item["original_y"]
       # наложить на canvas
   ```
3. Убрать: `_buffer`, `_buffer_timestamps`, `_buffer_lock`, `_on_region_processed`, `_process_loop`, `_find_ready_frame`, `_read_via_actual_name`, worker creation, register_message_handler
4. configure(): оставить чтение expected_regions, camera_id, layout
5. В topology для stitcher-процесса InspectorManager должен знать total_regions. Это передается через метаданные item (region_split добавляет total_regions в каждый item).

**Acceptance criteria:**
- [ ] `process(items)` принимает список регионов, возвращает `[{"frame": canvas}]`
- [ ] Нет SHM read внутри stitcher -- frame берется из item["frame"]
- [ ] Нет threading.Lock, нет буферизации -- это делает InspectorManager
- [ ] Нет register_message_handler, нет worker creation
- [ ] Плагин <= 80 строк (сейчас ~293)

**Out of scope:** Не менять InspectorManager или GenericProcess.
**Edge cases:** items пустой -- return []. Регион без frame -- пропустить (черная область). canvas_width/canvas_height = 0 -- return [].
**Dependencies:** Task 5.1, Task 5.2, Task 5.3

---

### Task 5.7 -- Output-плагины: миграция на process()

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Переписать output-плагины (database, frame_saver) на process(items) -> items
**Context:** Output-плагины -- конечные точки pipeline. Они принимают items, выполняют side-effect (сохранение на диск / запись в БД), и могут возвращать items дальше (pass-through) или пустой список.

**Files:**
- `multiprocess_prototype_2/plugins/database/plugin.py`
- `multiprocess_prototype_2/plugins/frame_saver/plugin.py`

**Steps:**
1. **database/plugin.py**:
   ```python
   def process(self, items: list[dict]) -> list[dict]:
       for item in items:
           self._add_to_buffer(item, item.get("event_type", "frame_processed"))
       return items  # pass-through для chain
   ```
   Убрать: `register_message_handler`, `_on_detection_result`, `_on_frame_processed`
   Оставить: `configure_managers()` или `configure()` для SQLite init, `_flush_loop` worker для периодического flush (этот worker остается -- он для фоновой задачи, не для data processing), команды flush/get_stats.

2. **frame_saver/plugin.py**:
   ```python
   def process(self, items: list[dict]) -> list[dict]:
       for item in items:
           self._frame_count += 1
           if self._frame_count % self._save_every_n == 0:
               self._save_frame_from_item(item)
       return items  # pass-through
   ```
   Убрать: `register_message_handler`, `_on_frame_ready`, `_save_loop` worker, `_pending_frame_info`
   Оставить: configure() для чтения конфига, shutdown()

3. Для обоих: configure() больше НЕ использует `ctx.router_manager`, `ctx.worker_manager` (кроме database flush worker -- см. ниже)
4. Database: flush worker остается как фоновая задача. Его создание можно оставить в start() через ctx.worker_manager. Это допустимое исключение -- flush не связан с data flow.

**Acceptance criteria:**
- [ ] `process(items)` принимает items, выполняет side-effect, возвращает items (pass-through)
- [ ] database: запись в буфер происходит через process(), не через message_handler
- [ ] frame_saver: сохранение через process(), не через message_handler
- [ ] database: периодический flush worker сохранен
- [ ] Нет register_message_handler для data processing

**Out of scope:** Не менять формат SQLite таблицы. Не менять логику batch insert.
**Dependencies:** Task 5.2

---

### Task 5.8 -- Topology обновление и e2e тест

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Обновить topology YAML для работы с новой data pipeline архитектурой, проверить e2e flow
**Context:** Topology может потребовать новые поля (chain_targets, source_fps_target). Wires могут использоваться GenericProcess для автоматического routing. Также нужно убедиться что region_pipeline.yaml работает end-to-end.

**Files:**
- `multiprocess_prototype_2/topology/region_pipeline.yaml` -- обновить при необходимости
- `multiprocess_prototype_2/topology/pipeline.yaml` -- обновить при необходимости
- `multiprocess_prototype_2/topology/camera_grayscale.yaml` -- обновить при необходимости
- `multiprocess_framework/modules/process_module/generic/generic_process_config.py` -- расширить если нужны chain_targets

**Steps:**
1. Определить нужны ли новые поля в topology процесса:
   - `chain_targets: list[str]` -- куда GenericProcess отправляет результат chain
   - Или targets берутся из wires (парсинг при bootstrap)
   - Или targets берутся из plugin config (как сейчас -- `frame_targets`, `target`)
2. Для region_split: убедиться что total_regions добавляется в metadata каждого item (чтобы InspectorManager знал сколько ждать)
3. Для region_pipeline.yaml: region_split должен генерировать items с total_regions=3 (2 ROI + default)
4. Проверить: camera -> resize -> region_split -> (negative|grayscale|flip) -> stitcher -> gui
5. Проверить: camera -> grayscale -> output (pipeline.yaml)
6. Добавить `chain_targets` в ProcessConfig если нужно (или использовать plugin-level `target`)

**Acceptance criteria:**
- [ ] `region_pipeline.yaml` работает end-to-end с новой архитектурой
- [ ] `pipeline.yaml` работает end-to-end
- [ ] Routing между процессами корректен
- [ ] InspectorManager корректно буферизует регионы для stitcher

**Out of scope:** Не создавать новые topology. GUI (Phase 4) не затрагивается.
**Edge cases:** Процесс без processing-плагинов (только source). Процесс с несколькими processing-плагинами в chain.
**Dependencies:** Task 5.3, Task 5.4, Task 5.5, Task 5.6, Task 5.7

---

## Риски и ограничения

1. **Обратная совместимость**: Плагины, которые используют register_message_handler (heartbeat и другие), должны продолжать работать. GenericProcess должен поддерживать оба режима (legacy message_handler и новый process()) на переходный период.

2. **Source + Processing в одном процессе**: Если в процессе есть и source, и processing плагин -- source генерирует items, processing обрабатывает. GenericProcess должен корректно маршрутизировать items от source_worker в chain_queue.

3. **RingBufferWriter**: CapturePlugin сейчас использует RingBufferWriter для pre-allocation SHM. В новой архитектуре GenericProcess должен уметь использовать ring buffer или стандартный write_images. Возможно потребуется передать hint в item metadata.

4. **Performance**: Внутренняя queue.Queue добавляет overhead. При 25 FPS это ~40ms на кадр -- queue.put/get < 1us, не критично.

5. **Stitcher cross-process SHM**: Stitcher сейчас использует `_read_via_actual_name()` для чтения SHM из другого процесса. В новой архитектуре frame уже будет в item["frame"] (прочитан middleware в Data Worker) -- проблема решается автоматически.

6. **region_split**: Этот плагин имеет 1:N семантику (1 item -> N items). process() должен корректно возвращать N items с total_regions в metadata. GenericProcess отправляет каждый item в свой target (из item["target"]).
