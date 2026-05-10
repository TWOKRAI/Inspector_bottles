# Отладка доставки кадров — Phase 5 (region_pipeline)

Документация проблем и решений при интеграции data pipeline (GenericProcess с region_split) с GUI. Применено при запуске `region_pipeline` topology.

---

## 1. `chain_targets` терялись в Pydantic

**Симптом:**
```
SourceProducer: camera_0 produced frame, targets=[]
```
Камера производит кадры (LED горит), но в логах `targets=[]` — кадры никуда не отправляются.

**Root Cause:**
- `ProcessConfig` в `blueprint.py` не имел поля `chain_targets`
- YAML задавал `chain_targets: [preprocessor]`, но Pydantic (SchemaBase) отбрасывал unknown field
- `GenericProcessConfig` ожидал `targets` при инициализации, но они не прокидывались из blueprint

**Решение:**
- Добавлены поля `chain_targets: list[str] = Field(default_factory=list)` и `source_target_fps: int = 30` в `ProcessConfig` (blueprint.py)
- `ProcessConfig.as_generic_config()` теперь прокидывает `chain_targets` → `GenericProcessConfig(targets=self.chain_targets)`
- Регулярное проверяется: YAML → blueprint → GenericProcessConfig должны иметь одинаковые имена полей

**Файлы:**
- `multiprocess_framework/modules/process_module/generic/blueprint.py`

---

## 2. `Message` vs `dict` в DataReceiver

**Симптом:**
```
KeyError: "Field 'frame' is not a valid message field"
SourceProducer worker thread crashed
```

**Root Cause:**
- `RouterManager.receive_message()` возвращает `Message` — Pydantic SchemaBase с фиксированными полями (`type`, `channel`, `payload`, `targets`)
- `FrameShmMiddleware.restore_frame()` пытается записать `msg["frame"] = ...` — поля `frame` нет в схеме Message
- Python dict допускает добавление любых ключей, но Pydantic-объект — нет

**Решение:**
- В `DataReceiver.run_loop()` перед передачей в middleware: `msg_dict = msg.to_dict()`
- Middleware работает с dict, может добавлять `msg_dict["frame"] = numpy_array`
- Перед отправкой через IPC снова валидируется/сериализуется

**Правило:**
На границе между слоями: **Message → dict → обработка → сохранение в dict → отправка**. Никогда не пытаться изменять Pydantic-объект.

**Файлы:**
- `multiprocess_framework/modules/process_module/generic/data_receiver.py`

---

## 3. SHM изоляция между OS-процессами

**Симптом:**
```
FrameShmMiddleware(generic): read_images пусто (camera_0/output_frames[0])
```
Preprocessor (отдельный OS-процесс) не может прочитать SHM `camera_0` (создан в другом процессе).

**Root Cause:**
- Каждый OS-процесс имеет свой `MemoryManager` экземпляр (привязан к процессу)
- `FrameShmMiddleware.restore_frame()` в generic-модуле использует `MemoryManager.read_images()`, которая не находит SHM другого процесса
- В отличие от router-версии middleware, generic-версия не имела fallback через `shm_actual_name`

**Решение:**
- Добавлен fallback в generic `FrameShmMiddleware.restore_frame()`:
```python
try:
    images = self._mm.read_images(...)  # MemoryManager данного процесса
except (KeyError, ValueError):
    # Fallback: открыть SHM по actual_name (передан в msg)
    shm = SharedMemory(name=shm_actual_name, create=False)
    frame = np.frombuffer(shm.buf, dtype=np.uint8).reshape(h, w, c).copy()
    shm.close()
```
- На Windows имена типа `camera_0_frame_19840_0` содержат PID создателя — essential для fallback

**Файлы:**
- `multiprocess_framework/modules/process_module/generic/frame_shm_middleware.py`

---

## 4. `BufferError: cannot close exported pointers exist`

**Симптом:**
```
BufferError: cannot close exported pointers exist
  File ".../multiprocess_framework/modules/process_module/generic/frame_shm_middleware.py", line 147
    shm.close()
```
Массовые ошибки при закрытии SharedMemory в fallback-чтении (проблема 3).

**Root Cause:**
- `np.frombuffer(shm.buf)` создаёт numpy array с reference на буфер SHM
- При вызове `shm.close()` в `finally` буфер ещё используется (несмотря на `.copy()` — промежуточный массив `arr` жив в scope)
- Numpy сохраняет reference на исходный buffer до garbage collection

**Решение:**
- Явное удаление intermediate переменных перед close:
```python
arr = np.frombuffer(shm.buf, dtype=np.uint8)
buf = arr.reshape(h, w, c).copy()
del arr  # освобождаем reference
shm.close()
return buf
```
- Аналогичный fix в `router_module/middleware/frame_shm_middleware.py`

**Правило:**
При работе с `SharedMemory.buf` и numpy: **всегда явно delete intermediate arrays перед close()**.

**Файлы:**
- `multiprocess_framework/modules/process_module/generic/frame_shm_middleware.py`
- `multiprocess_framework/modules/router_module/middleware/frame_shm_middleware.py`

---

## 5. Разные размеры регионов ломали SHM write

**Симптом:**
```
FrameShmMiddleware: write_images вернул None (region_splitter/output_frames[2])
```
Постоянно для index `[2]` — всегда None, остальные пишут успешно.

**Root Cause:**
- RegionSplitPlugin выдаёт 3 региона разных форм: (320x240), (640x480), (800x600)
- SHM аллоцируется **lazy** по форме первого кадра (320x240, буфер ~230KB)
- Когда third region (800x600, буфер ~1.4MB) пишется в SHM — не влезает
- `MemoryManager.write_images()` возвращает None при ошибке allocation

**Решение:**
- Graceful fallback в `FrameShmMiddleware.strip_and_write()`:
```python
result = self._mm.write_images(...)
if result is None:
    # SHM write не удался (размер,락и т.п.)
    # Frame остаётся в item dict
    return item  # идёт через pickle в IPC
```
- На стороне consumer `restore_frame()` проверяет presence перед чтением из SHM:
```python
if "frame" in msg and msg["frame"] is not None:
    return msg  # уже восстановлен из pickle
```

**Правило:**
SHM — best-effort delivery. Graceful fallback на pickle для frames that don't fit.

**Файлы:**
- `multiprocess_framework/modules/process_module/generic/frame_shm_middleware.py`

---

## 6. Bridge не маршрутизировал кадры

**Симптом:**
```
Frontend bridge dispatch called with type='data'
But _on_frame_received slot never invoked
```
GUI получает сообщения с `has_frame=True`, но slot никогда не вызывается.

**Root Cause:**
- Pipeline отправляет: `msg = {"type": "data", "data": item}`
- Bridge в `dispatch()` проверял только: `if data_type in ("frame_ready", "frame")`
- Тип "data" не совпадал → кадры уходили в catch-all `command_response` signal вместо `frame_received`

**Решение:**
- Добавлена проверка `or "frame" in msg_dict` в dispatch():
```python
if data_type in ("frame_ready", "frame") or ("frame" in msg_dict and msg_dict.get("frame") is not None):
    self.frame_received.emit(msg_dict)
```
- Также проверка на `msg_dict.get("has_frame") == True` при наличии explicit флага

**Файлы:**
- `multiprocess_prototype/frontend/bridge_impl.py` (или `bridge.py` если переписан)

---

## 7. Qt Signal из non-QThread не доставлялся

**Симптом:**
```
DataReceiverBridge.dispatch() вызывается → frame_received.emit(msg_dict) отрабатывает
Но slot _on_frame_received() никогда не вызывается на Qt main thread
```

**Root Cause:**
- `data_receiver` worker — обычный Python thread (через `WorkerManager`), **не QThread**
- PySide6 `Signal.emit()` из non-QThread использует `AutoConnection` по умолчанию
- Для кросс-потоковых сигналов нужен явный `Qt.QueuedConnection`
- Bridge сам не является `QObject` (статический класс), поэтому signal delivery неопределён

**Решение:**
- Переписан bridge — внутренний `_deliver = Signal(object)` с явным `Qt.QueuedConnection`
- Вместо публичных signals используются callback-методы:
```python
@Slot(object)
def _on_deliver(self, msg_dict):
    if self._on_frame_callback:
        self._on_frame_callback(msg_dict)

def set_frame_callback(self, callback):
    self._on_frame_callback = callback
```
- App при создании bridge регистрирует callback:
```python
bridge.set_frame_callback(self.presenter._on_frame_received)
```

**Правило:**
Не полагаться на direct signals из worker threads. Использовать явные callbacks + QThread-level signal retransmission.

**Файлы:**
- `multiprocess_prototype/frontend/bridge_impl.py`
- `multiprocess_prototype/frontend/app.py` (регистрация callback)

---

## 8. `bridge.py` vs `bridge/` пакет — Python import shadowing

**Симптом:**
```
AttributeError: 'DataReceiverBridge' object has no attribute 'set_frame_callback'
Method exists in code but not visible at runtime
```

**Root Cause:**
- Существуют одновременно:
  - `multiprocess_prototype/frontend/bridge.py` (файл)
  - `multiprocess_prototype/frontend/bridge/` (пакет с `__init__.py`)
- Python при `from .bridge import DataReceiverBridge`:
  1. Приоритизирует пакет → `bridge/__init__.py`
  2. Там импортируется `from .bridge_impl import DataReceiverBridge`
  3. Правки в `bridge.py` (файл) **никогда не загружаются**

**Решение:**
- Источник истины: `bridge_impl.py` (в пакете `bridge/`)
- Обновлен `bridge_impl.py` с новыми методами
- `bridge.py` (файл) — legacy stub, игнорируется
- `bridge/__init__.py` явно импортирует из `bridge_impl.py`

**Правило:**
Избегать одновременно `module.py` и `module/` пакета. Если миграция — удалить старый файл или сделать его явным re-export.

**Файлы:**
- `multiprocess_prototype/frontend/bridge_impl.py` (источник)
- `multiprocess_prototype/frontend/bridge/__init__.py` (явный импорт)

---

## Summary: Phase 5 Frame Delivery Checklist

При запуске новой pipeline topology с GenericProcess:

- [ ] **Blueprint:** все `chain_targets`, `source_target_fps` объявлены в `ProcessConfig`
- [ ] **Message → dict:** middleware получает dict, не Pydantic-объект
- [ ] **SHM fallback:** restore_frame() имеет fallback через `shm_actual_name`
- [ ] **Buffer cleanup:** явный `del arr` перед `shm.close()`
- [ ] **Graceful SHM:** write_images возвращает None → fallback на pickle
- [ ] **Bridge routing:** dispatch() проверяет `"frame" in msg_dict`
- [ ] **Signal threading:** явный callback, не direct cross-thread signals
- [ ] **Import resolution:** убедиться что `bridge/` пакет приоритизирован, `bridge.py` удалён или реexported

---

## Ссылки

- [FRAME_DELIVERY.md](FRAME_DELIVERY.md) — архитектура Phase 4
- `multiprocess_framework/docs/MODULES_OVERVIEW.md` — общая архитектура middleware
- `multiprocess_framework/DECISIONS.md` → локальные DECISIONS.md модулей для SHM и Message-handling
