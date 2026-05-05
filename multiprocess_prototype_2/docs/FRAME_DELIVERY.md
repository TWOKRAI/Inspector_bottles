# Доставка кадров между процессами (Frame Delivery)

## Архитектура

```
CapturePlugin (camera_0 process)
  │  cv2.read() → numpy frame
  │  RingBufferWriter.write(frame) → SHM (pre-allocated, OS-level shared memory)
  │  io.send_data(target, "frame_ready", {shm_actual_name, shm_index, width, height, ...})
  │     ↓ queue_registry.send_to_queue(target, "data", msg_dict)
  │     ↓ multiprocessing.Queue (лёгкий dict без numpy)
  ▼
GuiProcess (gui process)
  │  router_manager.receive(channel_types=["data"])
  │     → FrameShmMiddleware.on_receive(msg):
  │        shm_actual_name → SharedMemory(name=..., create=False) → numpy frame
  │        msg["frame"] = frame
  │  → DataReceiverBridge.dispatch(msg_dict)
  │     → frame_received.emit(msg_dict)  [Qt Signal, cross-thread]
  ▼
Qt Main Thread
  │  _on_frame_received(msg_dict)
  │     frame = msg_dict["frame"]  (numpy BGR)
  │     camera_presenter.on_frame(frame)
  │        → BGR→RGB → QImage → QPixmap → CameraView.update_pixmap()
  ▼
  Экран
```

## Ключевые проблемы и решения (Phase 4 debug)

### 1. PluginConfig отбрасывает unknown fields

**Проблема:** `frame_targets: [gui]` в topology YAML терялось при прохождении через
`_restore_plugin_configs()` → `CapturePluginConfig.model_validate(pdict)`.
Pydantic модель не знала поле `frame_targets` и отбрасывала его.

**Симптом:** CapturePlugin получал `cfg.get("frame_targets") == None` → fallback на
`processor_{camera_id}` → кадры уходили в несуществующий processor_0.

**Решение:** Добавить `frame_targets` поле в `CapturePluginConfig` (plugins/capture/config.py).

**Правило:** Все runtime-конфигурируемые параметры плагина **должны быть объявлены**
в его PluginConfig-классе. Иначе Pydantic их отбросит при валидации.

---

### 2. SHM изоляция между OS-процессами

**Проблема:** GUI-процесс не имеет handles к SHM-блокам камеры.
`MemoryManager.read_images()` в GUI возвращает None — он не создавал эту память.

**Решение:** CapturePlugin передаёт `shm_actual_name` (полное OS-имя с PID) в IPC-сообщении.
`FrameShmMiddleware.on_receive()` в GUI использует fallback:
```python
shm = SharedMemory(name=shm_actual_name, create=False)  # открыть существующий блок
frame = np.frombuffer(shm.buf, ...).reshape(h, w, c).copy()
shm.close()
```

**На Windows** SHM имена содержат PID процесса-создателя (например `camera_0_frame_19840_0`).
Без передачи actual_name потребитель не может угадать имя.

---

### 3. send_message() минует middleware

**Проблема:** `ProcessCommunication.send_to_process()` использует `queue_registry.send_to_queue()`
напрямую — **без вызова router.send()**, а значит без send middleware.

Если плагин пытается отправить numpy frame через `send_message()` — middleware не срабатывает,
numpy идёт через pickle в multiprocessing.Queue (медленно или crash).

**Решение для send_frame:** В `ProcessIO.send_frame()` вручную применяем send middleware:
```python
processed = router._send_mw.apply(msg_dict)  # middleware записывает в SHM
self._p.send_message(target, processed)       # отправляет только координаты
```

**Текущая реализация:** CapturePlugin записывает в SHM напрямую через RingBufferWriter
(pre-allocated), отправляет только координаты через `io.send_data()`. Это обходит проблему.

---

### 4. cv2.VideoCapture backend на Windows

**Проблема:** Дефолтный MSMF backend не поддерживает некоторые камеры.
`CvCapture_MSMF::initStream Failed` → `cap.read()` крашится с assertion.

**Решение:** Использовать DirectShow backend:
```python
self._cap = cv2.VideoCapture(self._device_id, cv2.CAP_DSHOW)
```

---

### 5. Qt Signal(dict) не передаёт numpy

**Проблема:** `Signal(dict)` при queued connection (cross-thread) может потерять numpy array.

**Решение:** Использовать `Signal(object)` — Qt передаёт Python object as-is.

---

## Конфигурация

### Topology YAML (camera → GUI напрямую)

```yaml
processes:
  - process_name: camera_0
    plugins:
      - plugin_class: multiprocess_prototype_2.plugins.capture.plugin.CapturePlugin
        plugin_name: capture
        camera_id: 0
        device_id: 0
        frame_targets:
          - gui        # ← кому отправлять кадры

  - process_name: gui
    process_class: multiprocess_prototype_2.frontend.process.GuiProcess
    plugins: []
```

### Topology YAML (camera → processor → GUI)

```yaml
processes:
  - process_name: camera_0
    plugins:
      - plugin_class: ...CapturePlugin
        frame_targets:
          - processor_0

  - process_name: processor_0
    plugins:
      - plugin_class: ...ColorMaskPlugin
        frame_targets:
          - gui        # после обработки → в GUI

  - process_name: gui
    process_class: ...GuiProcess
    plugins: []
```
