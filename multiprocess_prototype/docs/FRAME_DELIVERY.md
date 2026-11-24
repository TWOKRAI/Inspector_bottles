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
  │  router_manager.receive(channel_types=["data"])   [копии из SHM здесь НЕТ: on_receive в router не стоит;
  │     оговорка - ниже, раздел «Копия из SHM - в Qt-потоке» (wire role=receiver)]
  │  → DataReceiverBridge.dispatch(msg_dict)
  │     → frame_mailbox.put(sender, msg_dict, nbytes)  [ящик «последний на ключ», без Qt;
  │        сообщение лежит КАК ЕСТЬ: кадр — ссылка data["_shm_refs"]["frame"], без массива]
  ▼
Qt Main Thread
  │  FramePump: таймер на ключ (период из fps_limit слота) → take(sender)
  │  → _show_taken(msg_dict) → bridge.restore_for_show(msg_dict):
  │        FrameShmMiddleware.on_receive: ВСЕ ссылки сообщения → КОПИЯ из SHM (msg["frame"], data[key])
  │  → _on_frame_received(msg_dict)
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

### 5. Кадры больше не идут сигналом Qt

**Было:** кадр передавался `Signal(object)` (`frame_received`) на каждый кадр; при потоке
выше скорости показа очередь событий Qt росла без предела (память и «замерзший» GUI).

**Стало:** `dispatch` кладёт кадр в `LatestMailbox` (`bridge.frame_mailbox`), а `ndarray`
отдаёт насос `FramePump` в Qt-потоке. `Signal(object)` для кадра не используется;
`frame_received` больше не эмитится из `dispatch` (сигнал и `set_frame_callback`
сохранены в классе моста, но `dispatch` их не вызывает).

---

## Путь кадра в gui: ящик → насос → слот

```
data_receiver (worker thread)
  │  DataReceiverBridge.dispatch(msg_dict)  — ветка кадра (is_frame_message: ключ frame,
  │     data_type frame/frame_ready ИЛИ ссылка data["_shm_refs"]["frame"])
  │     frame_mailbox.put(key=sender, item=msg_dict, nbytes=frame.nbytes или 0 для ссылки)
  │     (sender не строка → ключ ""; без _deliver.emit и без frame_received.emit; копии из SHM нет)
  ▼
LatestMailbox  — не больше ОДНОГО кадра на ключ; новый put вытесняет старый
  ▼
FramePump (Qt main thread)  — QTimer на ключ, период = ceil(1000 / fps_limit) мс
  │  take(sender) → sink(sender, msg_dict) = _show_taken
  │     bridge.restore_for_show(msg_dict) — копия ссылок из SHM, один раз, в Qt-потоке
  │     None (ссылка перезаписана/порвана или нет восстановителя) → кадр не показан, слот держит прежний
  ▼
_on_frame_received(msg_dict)
  │  resolve_display_id(sender → слот по blueprint.displays)
  ▼
ImagePanelWidget.display_frame(слот, frame)
```

- **Ключ ящика и насоса — `sender`** (имя процесса-отправителя), а не id дисплея.
  Предел частоты насос берёт из слота дисплея, на который sender маршрутизируется
  (`build_frame_routing` + `build_panel_displays`): `{sender: fps_limit дисплея}`.
- **`fps_limit` дисплея** (секция `displays` рецепта): число — как есть; нет ключа,
  `None`, не число, NaN — 30.0; `0` — потолок 60 Гц (его применяет насос).
  Потолок насоса — 60 Гц, меньше 1 Гц не бывает.
- **Два sender на один дисплей** получают каждый свой таймер с тем же `fps_limit`
  (следствие ключа = sender): суммарная частота показа на слот может превышать предел.
- **Память тракта** = число ключей × 1 кадр при любой частоте входа
  (`frame_mailbox.stats()["max_bytes_held"]`).
- **Копия из SHM — в Qt-потоке при показе (T5).** Раньше её делал router-middleware
  `FrameShmMiddleware.on_receive` в потоке приёма на КАЖДОЕ сообщение; теперь он в
  `add_receive_middleware` не стоит. Мост (`DataReceiverBridge.set_frame_restorer`, в gui —
  `on_receive`) копирует ссылки сообщения ОДИН раз, в `restore_for_show`, для кадра, который насос
  вынул для показа (и для не-кадровых `state`/`observability`/`command` со ссылками — в
  `_handle_payload`). `restore_for_show` зовётся только в Qt-потоке (читатель SHM gui один).
  Копия независима от слота кольца (presenter держит собственный массив), view (`restore_frame`)
  для gui запрещён. Сообщение без ссылок (inline `frame`) проходит без изменений.
  Оговорка: проводка `wire.configure role=receiver` на gui (`builtin_commands.py:3810-3811`) ставит
  СВОЙ `on_receive` в router (`add_receive_middleware`); такая копия идёт в потоке приёма и в
  `shm_bytes_read` читателя `_recv_frame_mw` не видна.
- **`bytes_held` ящика для ссылок — 0:** ящик байтов кадра не держит (форма кадра едет в заголовке
  слота, читать её значило бы обращаться к SHM в потоке приёма). Inline `frame` считается по
  `nbytes`, как раньше. `max_bytes_held` при потоке ссылок остаётся 0.
- **Потери копии:** ссылка, перезаписанная кольцом (stale) или порванная при чтении (torn), даёт
  `None` из `on_receive`: сообщение отбрасывается ЦЕЛИКОМ (нечитаемая `mask` роняет и `frame`),
  кадр не показан, следующий тик берёт новое сообщение из ящика. Счётчики: `frame_stale_drops`,
  `frame_torn_reads`, `frame_restore_failures` в `introspect.router_stats` (middleware остаётся
  зарегистрированным через `register_frame_middleware`) и `bridge.restore_dropped` (единица —
  сообщение). `middleware_dropped` у gui на кадрах больше не растёт. Новый механизм потерь: stale-ссылка
  вытесняет из ящика хороший кадр, и тик пуст (до T5 stale умирал в receive, прежний кадр оставался).
- **Насос считает `shown` и тик, в котором копия не удалась** (sink не бросает): строка FPS берёт
  «показано» из `_shown_by_slot`, он stale не считает — расхождение осознанное.
- **Вытеснение** из ящика не освобождает слот кольца SHM: `gui` — copy-out потребитель
  (`FrameShmMiddleware` отдаёт копию), вытесненный кадр собирает сборщик мусора.
- **Время кадра** (`capture_ns`, `capture_ts`) доходит до `_on_frame_received`
  без изменений; кадр со временем раньше предыдущего показывается (фильтра «время
  только вперёд» нет).
- **Кадр до насоса**: кадр, пришедший в `dispatch` до создания насоса и первого
  `set_keys`, остаётся в ящике и показывается первым тиком.
- **Рецепт без секции `displays`, sender без привязки к дисплею или дисплей выключен:**
  ключа в `set_keys` нет, ключ находит скан насоса (раз в 100 мс) и ставит ему скрытые
  30 Гц — задержка до 100 мс на первый кадр; кадр уходит в слот «main».

---

## Конфигурация

### Topology YAML (camera → GUI напрямую)

```yaml
processes:
  - process_name: camera_0
    plugins:
      - plugin_class: Plugins.sources.capture.plugin.CapturePlugin
        plugin_name: capture
        camera_id: 0
        device_id: 0
        frame_targets:
          - gui        # ← кому отправлять кадры

  - process_name: gui
    process_class: multiprocess_prototype.frontend.process.GuiProcess
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

---

## Phase 5 Debug (region_pipeline)

При интеграции data pipeline (GenericProcess с region_split) обнаружены и решены **8 критических проблем** доставки кадров:

1. **`chain_targets` терялись в Pydantic** — ProcessConfig не объявлял поле, Pydantic отбрасывал YAML-значение
2. **`Message` vs `dict` в DataReceiver** — middleware пытался добавить "frame" в неизменяемый Pydantic-объект
3. **SHM изоляция между OS-процессами** — missing fallback через `shm_actual_name` в generic middleware
4. **`BufferError` при close() SharedMemory** — numpy array с reference на буфер блокировал close
5. **Разные размеры регионов ломали write** — SHM lazy-alloc не рассчитывал на разные формы регионов
6. **Bridge не маршрутизировал кадры** — dispatch() не распознавал type="data" как frame
7. **Qt Signal из non-QThread** — AutoConnection не работает для worker threads, нужен callback
8. **Python import shadowing** — одновременно `bridge.py` (файл) и `bridge/` (пакет) создавали конфликт

Полная диагностика, симптомы и решения → **[FRAME_DELIVERY_DEBUG.md](FRAME_DELIVERY_DEBUG.md)**.

**Применение:** При запуске нового pipeline topology с GenericProcess используйте checklist в конце FRAME_DELIVERY_DEBUG.md.
