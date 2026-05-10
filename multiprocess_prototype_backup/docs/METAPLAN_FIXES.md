# Метаплан: исправление проблем multiprocess_prototype

> **Дата:** 2026-04-23 | **Источник:** ARCHITECTURE.md, раздел 13

---

## Система оценки

Каждая проблема оценивается по 5 критериям (1-5 баллов):

| Критерий | Что значит |
|----------|-----------|
| **Влияние** | Насколько сильно бьёт по системе если не чинить (5 = критично, 1 = косметика) |
| **Вероятность** | Как часто проявляется на практике (5 = постоянно, 1 = раз в жизни) |
| **Сложность** | Трудоёмкость реализации (5 = просто, 1 = архитектурный рефакторинг). **Инвертировано**: чем проще — тем выше балл |
| **ROI** | Отдача от вложений (5 = огромная, 1 = минимальная) |
| **Зависимости** | Блокирует ли другие задачи (5 = блокер, 1 = изолировано) |

**Итоговый приоритет** = (Влияние × 2 + Вероятность × 1.5 + Сложность + ROI × 1.5 + Зависимости) / 7

---

## Сводная таблица

| # | Проблема | Влияние | Вероятн. | Сложн. | ROI | Завис. | **Итого** | Фаза |
|---|---------|---------|----------|--------|-----|--------|-----------|------|
| P10 | Нет auto-restart процессов | 5 | 4 | 3 | 5 | 5 | **4.36** | 1 |
| P1 | Processor = SPOF | 5 | 3 | 2 | 4 | 4 | **3.79** | 2 |
| P2 | Нет heartbeat/health check | 4 | 3 | 4 | 4 | 4 | **3.79** | 1 |
| P3 | Жёсткие SHM-размеры | 4 | 4 | 3 | 4 | 3 | **3.64** | 2 |
| P8 | Дублирование SHM-размеров | 4 | 4 | 4 | 4 | 3 | **3.79** | 1 |
| P9 | Нет валидации profiles | 3 | 3 | 5 | 3 | 2 | **3.14** | 1 |
| P11 | SHM cleanup при crash | 4 | 3 | 4 | 3 | 2 | **3.21** | 1 |
| P5 | Нет batch INSERT в БД | 3 | 3 | 4 | 3 | 1 | **2.79** | 2 |
| P7 | Нет метрик latency | 3 | 5 | 4 | 4 | 2 | **3.50** | 2 |
| P13 | GUI: нет "backend не отвечает" | 3 | 2 | 5 | 3 | 1 | **2.71** | 3 |
| P6 | Ring Buffer: множественные readers | 2 | 2 | 3 | 2 | 1 | **2.00** | 3 |
| P4 | GUI polling вместо событий | 2 | 5 | 3 | 2 | 1 | **2.50** | 3 |
| P12 | Qt thread safety (потенциальная) | 3 | 1 | 4 | 2 | 1 | **2.14** | 3 |

---

## Фаза 1 — Фундамент устойчивости (быстрые высокоэффектные фиксы)

**Цель:** система перестаёт падать молча, конфиг валидируется, SHM не течёт.
**Оценка трудозатрат:** 3-5 дней

### Task 1.1 — P8: Единый источник SHM-размеров (per-region)
**Итого:** 3.79 | **Сложность:** средняя (3/5)

**Проблема:** `CameraConfig.resolution_width/height` и `CAMERA_SHM_WIDTH/HEIGHT` в `constants.py` — два независимых места. Рассогласование = crash или corrupted данные в SHM. Кроме того, все SHM-слоты одного размера — нельзя иметь разные разрешения для разных регионов/камер.

**Ключевое требование:** SHM-размеры определяются **по региону** (camera region), а не глобально.

**Решение:**
1. Удалить `CAMERA_SHM_WIDTH / CAMERA_SHM_HEIGHT` из `services/camera/constants.py`
2. Ввести `ShmRegionSpec` — описание одного SHM-региона:
   ```python
   class ShmRegionSpec(SchemaBase):
       name: str          # "camera_0_frame", "processor_mask", ...
       width: int
       height: int
       channels: int = 3
       slots: int = 1     # для Ring Buffer: slots = ring_buffer_size
   ```
3. `CameraConfig` создаёт свой `ShmRegionSpec` из своего разрешения:
   - Камера 0 (640×480) → `ShmRegionSpec(name="camera_0_frame", width=640, height=480, slots=3)`
   - Камера 1 (1280×720) → `ShmRegionSpec(name="camera_1_frame", width=1280, height=720, slots=3)`
4. Processor/Renderer получают список регионов из `AppConfig` → знают размер каждой камеры
5. `AppConfig.all_shm_regions() → list[ShmRegionSpec]` — собирает ВСЕ регионы:
   - от каждой камеры (camera_N_frame)
   - от процессора (processor_mask per camera)
   - от рендерера (rendered_frame, mask_frame per camera)
   - от воркеров (worker_K_result)
6. Валидация при сборке: каждый consumer проверяет что регион, который он читает, существует

**Файлы:**
- `config/shm_region.py` — новый файл: `ShmRegionSpec(SchemaBase)`
- `services/camera/constants.py` — удалить константы
- `config/app.py` — `all_shm_regions()`, прокидка регионов в дочерние конфиги
- `backend/processes/camera/config.py` — `shm_region()` метод
- `backend/processes/processor/config.py` — список входных регионов
- `backend/processes/renderer/config.py` — список входных/выходных регионов
- `backend/shm/ring_buffer.py` — shape из ShmRegionSpec, не из констант

**Критерии приёмки:**
- [ ] Нет импортов `CAMERA_SHM_WIDTH/HEIGHT` нигде в коде
- [ ] Камера 0 (640×480) и камера 1 (1280×720) — разные SHM-регионы разного размера
- [ ] Processor знает размер каждого региона отдельно
- [ ] Тест: 2 камеры с разными разрешениями → SHM-регионы правильных размеров
- [ ] Тест: несуществующий регион → ошибка при запуске, не crash в runtime

---

### Task 1.2 — P9: Валидация settings_profiles.yaml
**Итого:** 3.14 | **Сложность:** простая (5/5)

**Проблема:** YAML профиль загружается как сырой dict без проверки. Невалидные значения (`camera_count: -1`, `ring_buffer_size: 0`) → undefined behavior.

**Решение:**
1. Создать `SettingsProfile(SchemaBase)` с Pydantic-валидаторами
2. Загрузка через `SettingsProfile.model_validate(yaml_dict)`
3. Ограничения:
   - `camera_count: int, ge=1, le=16`
   - `ring_buffer_size: int, ge=2, le=10`
   - `worker_pool_size: int, ge=0, le=8`
   - `camera_source_type: Literal["simulator", "webcam", "hikvision", "file"]`
4. При ошибке — fallback на `default` профиль с логом warning

**Файлы:**
- `config/settings_profile.py` — новый файл: `SettingsProfile(SchemaBase)`
- `main.py` — `_load_cameras_from_profile()` через SettingsProfile
- `frontend/managers/settings_yaml_store.py` — валидация при загрузке

**Критерии приёмки:**
- [ ] Невалидный YAML → fallback на default + warning в лог
- [ ] `camera_count: -1` → ValidationError
- [ ] `camera_source_type: "unknown"` → ValidationError

---

### Task 1.3 — P11: SHM cleanup при старте и аварийном завершении
**Итого:** 3.21 | **Сложность:** средняя (4/5)

**Проблема:** После kill -9 SHM-сегменты остаются. На Linux — файлы в `/dev/shm/`. Накапливаются со временем.

**Решение:**
1. При старте `main.py` — вызвать `cleanup_stale_shm(prefix="inspector_")`:
   - Проверить `/dev/shm/` (Linux) или Registry (Windows) на сегменты с нашим prefix
   - Если процесс-владелец мёртв → unlink
2. Добавить `atexit.register(cleanup)` в каждый процесс
3. Naming convention: все SHM-имена с prefix `inspector_` (сейчас — произвольные)

**Файлы:**
- `backend/shm/cleanup.py` — новый файл: `cleanup_stale_shm()`
- `main.py` — вызов cleanup при старте
- `backend/shm/ring_buffer.py` — naming convention с prefix

**Критерии приёмки:**
- [ ] После kill -9 и повторного запуска — нет утечки SHM
- [ ] Cleanup не удаляет SHM живых процессов
- [ ] Работает на Windows и Linux

---

### Task 1.4 — P2 + P10: Heartbeat + auto-restart
**Итого:** P2=3.79, P10=4.36 | **Сложность:** средняя (3/5)

**Проблема:** ProcessMonitor проверяет `is_alive()` (OS-уровень), но не знает зависли ли внутренности. И даже при обнаружении смерти — не перезапускает.

**Решение (2 подзадачи):**

**1.4a — Heartbeat:**
1. Каждый ProcessModule отправляет `heartbeat` каждые N секунд (по умолчанию 5с)
2. ProcessMonitor ведёт `last_heartbeat[process_name]`
3. Если `now - last_heartbeat > timeout` (15с) → статус `UNRESPONSIVE`
4. Heartbeat = системное сообщение через system-очередь

**1.4b — Auto-restart:**
1. ProcessManagerProcess: при `is_alive() == False` или `UNRESPONSIVE`:
   - Логирует событие
   - Вызывает `restart_process(name)` (уже есть как команда в фреймворке)
   - Max retries = 3, потом статус `FAILED`
2. Конфигурация: `RestartPolicy(max_retries=3, backoff_sec=2.0)` в ProcessLaunchConfig

**Файлы:**
- Фреймворк: `process_module/core/` — добавить heartbeat в базовый цикл
- Фреймворк: `process_manager_module/process/monitor.py` — watchdog + restart
- `config/app.py` — `restart_policy` в конфигах процессов
- Каждый `backend/processes/*/config.py` — добавить restart_policy

**Критерии приёмки:**
- [ ] Heartbeat виден в логах ProcessMonitor
- [ ] Kill camera → auto-restart через 2с
- [ ] 4-й подряд crash → статус FAILED, нет бесконечного цикла
- [ ] Тест: `UNRESPONSIVE` через 15с без heartbeat

---

## Фаза 2 — Производительность и масштабирование

**Цель:** система работает стабильно под нагрузкой, есть метрики, Processor не bottleneck.
**Оценка трудозатрат:** 5-8 дней
**Зависит от:** Фаза 1 (особенно P8 — единый источник размеров)

### Task 2.1 — P7: Метрики latency (end-to-end)
**Итого:** 3.50 | **Сложность:** средняя (4/5)

**Проблема:** FPS измеряется, но задержка от захвата до отображения — нет. Невозможно диагностировать bottleneck.

**Решение:**
1. В `frame_ready` IPC-сообщение добавить `capture_timestamp` (time.perf_counter())
2. Каждый процесс добавляет свой timestamp в metadata:
   - `processor_start_ts`, `processor_end_ts`
   - `renderer_start_ts`, `renderer_end_ts`
   - `gui_display_ts`
3. GUI считает: `e2e_latency = gui_display_ts - capture_timestamp`
4. Отображение в StatusBar: `Latency: 52ms`
5. Логирование percentiles каждые 10с: p50, p95, p99

**Файлы:**
- `backend/processes/camera/adapter.py` — добавить `capture_ts` в `frame_ready`
- `backend/processes/processor/process.py` — timestamps обработки
- `backend/processes/renderer/process.py` — timestamps рендера
- `backend/processes/gui/handlers.py` — вычисление e2e latency
- `frontend/widgets/` — отображение latency

**Критерии приёмки:**
- [ ] StatusBar показывает latency в мс
- [ ] В логах каждые 10с: p50/p95/p99
- [ ] Тест: latency < 100мс при 25fps на simulator

---

### Task 2.2 — P3: Динамическое разрешение SHM per camera
**Итого:** 3.64 | **Сложность:** средняя (3/5)

**Проблема:** После Task 1.1 SHM-регионы имеют размер per-region, но он фиксируется при старте. Нельзя менять разрешение камеры в runtime (например, при переключении webcam 640→1080).

**Решение (зависит от Task 1.1 — ShmRegionSpec уже есть):**
1. При смене камеры (`switch_camera_type`) определить новое разрешение бэкенда
2. Два режима:
   - **resize (default):** камера всегда resize к `ShmRegionSpec.width × height` → SHM не пересоздаётся
   - **native (opt-in):** `CameraConfig.shm_native_resolution = True` → SHM = нативное разрешение камеры. Требует пересоздания SHM-региона + уведомление всех consumers
3. Для native-режима:
   - Camera отправляет `shm_region_changed` → ProcessManager
   - ProcessManager: unlink старый SHM → allocate новый → уведомить consumers
   - Consumers (Processor, Renderer) переоткрывают SHM handle
4. GUI показывает актуальное разрешение каждой камеры в StatusBar

**Файлы:**
- `config/shm_region.py` — `ShmRegionSpec.resize()` / `.reallocate()`
- `services/camera/service.py` — resize к ShmRegionSpec или passthrough
- `backend/processes/camera/adapter.py` — `shm_region_changed` при native
- Фреймворк: `MemoryManager` — `reallocate_region(name, new_shape)`

**Критерии приёмки:**
- [ ] resize-режим: камера 1920×1080 → SHM 640×480, кадр масштабирован
- [ ] native-режим: камера 1920×1080 → SHM 1920×1080, Processor/Renderer читают полный кадр
- [ ] Переключение камеры в runtime → SHM пересоздан, все consumers переключились
- [ ] GUI: отображение актуального разрешения per camera

---

### Task 2.3 — P5: Batch INSERT в БД
**Итого:** 2.79 | **Сложность:** средняя (4/5)

**Проблема:** 125 INSERT/с при 25fps × 5 детекций. SQLite WAL помогает, но не идеально.

**Решение:**
1. `DatabaseService` — внутренний буфер `_pending: list[DetectionSchema]`
2. Flush по условию: `len(_pending) >= batch_size` ИЛИ `time_since_last_flush >= flush_interval`
3. Batch INSERT: `executemany()` в одной транзакции
4. Конфигурация: `DatabaseConfig.batch_size = 50`, `flush_interval_sec = 1.0`
5. Flush при shutdown (не терять последние детекции)

**Файлы:**
- `services/database/service.py` — batch логика
- `backend/processes/database/config.py` — `batch_size`, `flush_interval`
- `backend/processes/database/process.py` — flush при shutdown

**Критерии приёмки:**
- [ ] При 25fps × 5 детекций: INSERT раз в 0.4с (50 записей), не 125 раз/с
- [ ] При shutdown: последний batch сохранён
- [ ] Тест: 1000 детекций → все в БД

---

### Task 2.4 — P1: Processor масштабирование (N:M)
**Итого:** 3.79 | **Сложность:** сложная (2/5)

**Проблема:** Один Processor на все камеры. При 4 камерах по 25fps = 100 кадров/с — bottleneck.

**Решение (два варианта, выбрать один):**

**Вариант A — 1 Processor per Camera (простой):**
1. `AppConfig` создаёт N ProcessorProcess'ов: `processor_0`, `processor_1`, ...
2. Каждая Camera отправляет `frame_ready` в свой Processor
3. Каждый Processor отправляет `detection_result` в общий Renderer
4. Минус: дублирование ресурсов (детектор × N)

**Вариант B — Shared Processor Pool (сложный):**
1. Один Dispatcher-процесс принимает `frame_ready` от всех камер
2. Round-robin/load-aware распределение по Processor_0..M
3. Плюс: эффективнее при неравномерной нагрузке
4. Минус: дополнительный процесс + сложная логика

**Рекомендация:** Вариант A для прототипа (проще, надёжнее).

**Файлы:**
- `config/app.py` — `all_process_configs()` создаёт N ProcessorProcess'ов
- `backend/processes/processor/config.py` — `camera_id` привязка
- `backend/processes/camera/adapter.py` — `frame_ready` → конкретный `processor_N`
- `backend/processes/processor/process.py` — фильтрация по camera_id

**Критерии приёмки:**
- [ ] 4 камеры → 4 processor'а, каждый обрабатывает свою камеру
- [ ] Detection results от всех → один Renderer
- [ ] Тест: 4 камеры-симулятора × 25fps, все обрабатываются

---

## Фаза 3 — Polish (качество жизни)

**Цель:** удобство использования, защита от граблей.
**Оценка трудозатрат:** 2-3 дня
**Зависит от:** Фаза 1

### Task 3.1 — P13: GUI watchdog "Backend не отвечает"
**Итого:** 2.71 | **Сложность:** простая (5/5)

**Решение:**
1. `_poll_messages()` — трекать время последнего `rendered_frame_ready`
2. Если > 5с без кадров → показать warning overlay на DisplayWindow
3. Если > 15с → показать dialog "Backend не отвечает. Перезапустить?"
4. Кнопка "Перезапустить" → system command `restart_all`

**Файлы:**
- `backend/processes/gui/process.py` — watchdog timer
- `frontend/widgets/display_window/` — warning overlay
- `frontend/commands.py` — команда restart

**Критерии приёмки:**
- [ ] 5с без кадров → жёлтый overlay "Ожидание..."
- [ ] 15с → dialog с кнопкой перезапуска

---

### Task 3.2 — P4: Event-driven GUI (опционально)
**Итого:** 2.50 | **Сложность:** средняя (3/5)

**Решение:**
1. Создать `QueueWatcher(QThread)` — поток, который блокируется на `queue.get()`
2. При получении сообщения → `emit(signal)` в main thread
3. MainWindow подключает slot к signal
4. Убрать QTimer polling

**Плюсы:** меньше CPU при простое, мгновенная реакция.
**Минусы:** дополнительный QThread, сложнее отладка.

**Рекомендация:** низкий приоритет. Polling при 16мс — приемлемо для прототипа.

---

### Task 3.3 — P12: Гарантия Qt thread safety
**Итого:** 2.14 | **Сложность:** простая (4/5)

**Решение:**
1. Аудит: найти все места обновления виджетов — убедиться что из main thread
2. Добавить assertion: `assert QThread.currentThread() == QApplication.instance().thread()`
3. В debug-режиме: decorator `@ensure_main_thread` на критичные методы

**Файлы:**
- `frontend/` — аудит всех widget.update() вызовов
- `frontend/app_context.py` — `@ensure_main_thread` decorator

---

### Task 3.4 — P6: Ring Buffer: регистрация читателей
**Итого:** 2.00 | **Сложность:** средняя (3/5)

**Решение:**
1. `RingBufferWriter.register_reader(name)` / `unregister_reader(name)`
2. Writer ведёт `_readers: dict[str, ReaderState]`
3. Drop-oldest per-reader: каждый читатель независимо отстаёт
4. Метрика: `writer.stats()` → drops per reader

**Рекомендация:** низкий приоритет. Текущая реализация работает для фиксированного набора читателей.

---

## Дорожная карта

```
Фаза 1 (3-5 дней)         Фаза 2 (5-8 дней)         Фаза 3 (2-3 дня)
─────────────────          ─────────────────          ─────────────────
Task 1.1 P8 SHM единый  → Task 2.2 P3 SHM динамич.
Task 1.2 P9 Валидация      Task 2.1 P7 Latency
Task 1.3 P11 SHM cleanup   Task 2.3 P5 Batch INSERT
Task 1.4 P2+P10 HB+restart Task 2.4 P1 N Processors   Task 3.1 P13 Watchdog
                                                       Task 3.2 P4 Event GUI
                                                       Task 3.3 P12 Qt safety
                                                       Task 3.4 P6 Ring readers
```

**Зависимости:**
```
Task 1.1 (P8) ──блокирует──► Task 2.2 (P3)
Task 1.4 (P10) ─блокирует──► Task 3.1 (P13)  (restart = основа для watchdog)
```

**Параллелизм внутри фаз:**
- Фаза 1: Task 1.1 + 1.2 + 1.3 параллельно, Task 1.4 — отдельно (фреймворк)
- Фаза 2: Task 2.1 + 2.3 параллельно, Task 2.2 после 1.1, Task 2.4 — отдельно
- Фаза 3: все параллельно

---

## Рекомендация по приоритету (если нужно выбрать 3 задачи)

1. **Task 1.4 (P2 + P10)** — heartbeat + auto-restart. Без этого система "молча умирает". Самый высокий ROI.
2. **Task 1.1 (P8)** — единый источник SHM-размеров. Убирает класс трудноотлаживаемых багов (memory corruption). Быстро.
3. **Task 2.1 (P7)** — метрики latency. Без данных невозможно оптимизировать. Быстрая реализация, огромная диагностическая ценность.
