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

Один универсальный метод `process(items) -> items` для всех случаев (1:1, 1:N, N:1, фильтрация, batching).

```python
class ProcessModulePlugin:
    # Существующие: name, category, inputs, outputs, commands, configure(), start(), shutdown()

    def process(self, items: list[dict]) -> list[dict]:
        """Чистая обработка коллекции items.
        items = [{"frame": ndarray, ...meta}].
        Возвращает преобразованный список items.
        Без IPC, без SHM, без PluginContext.
        Default: pass-through (return items).

        Контракт покрывает все семантики:
          1:1   -- [item_in] -> [item_out]            (resize, grayscale, ...)
          1:N   -- [item] -> [item_a, item_b, ...]    (region_split: 1 frame -> N regions)
          N:1   -- [item_a, item_b, ...] -> [merged]  (stitcher: N regions -> 1 canvas)
          N:0   -- [...] -> []                        (фильтрация / отбрасывание)
          N:M   -- [...] -> [...]                     (любая комбинация)
        """
        return items

    def produce(self) -> list[dict]:
        """Только для source-плагинов. Генерация items.
        Default: raise NotImplementedError."""
        raise NotImplementedError(f"Plugin '{self.name}' does not implement produce()")
```

### Декоратор `@for_each` (опциональный сахар)

Простые 1:1 плагины могут декорировать `process` чтобы писать per-item логику. Контракт не меняется — декоратор оборачивает метод так, что снаружи вызывается `process(items) -> list[dict]`.

```python
# multiprocess_framework/modules/process_module/plugins/base.py
import functools

def for_each(func):
    """Сахар: per-item функция -> process(items).
    Возврат функции:
      dict       -> 1:1
      list[dict] -> 1:N (fan-out)
      None       -> фильтрация (item отбрасывается)
    """
    @functools.wraps(func)
    def wrapper(self, items: list[dict]) -> list[dict]:
        result = []
        for item in items:
            out = func(self, item)
            if out is None:
                continue
            if isinstance(out, list):
                result.extend(out)
            else:
                result.append(out)
        return result
    return wrapper
```

**Использование:**

```python
# Простой 1:1 (resize)
class ResizePlugin(ProcessModulePlugin):
    @for_each
    def process(self, item):
        if item.get("frame") is None: return None
        return {**item, "frame": cv2.resize(item["frame"], (w, h))}

# Fan-out 1:N (region_split)
class RegionSplitPlugin(ProcessModulePlugin):
    @for_each
    def process(self, item):
        return [{**item, "frame": region, "region_name": name} for name, region in self._split(item["frame"])]

# Fan-in N:1 (stitcher) -- БЕЗ декоратора
class StitcherPlugin(ProcessModulePlugin):
    def process(self, items):
        return [{"frame": self._stitch(items), "seq_id": items[0]["seq_id"]}]
```

Декоратор использовать или нет — выбор автора плагина. Контракт `process(items) -> items` универсален в обоих случаях.

---

## Открытые архитектурные вопросы

> **CRITICAL:** Эти 8 вопросов должны быть решены **ДО старта Task 5.3**. Иначе риск переделки Tasks 5.4-5.8 после первого e2e. Каждый вопрос имеет статус `OPEN` / `DECIDED` и список вариантов.

### Q1. Routing: куда GenericProcess отправляет результат chain?  `[DECIDED — Вариант D]`

**Контекст:** После прогона items через chain — куда их отправлять по IPC?

**Варианты:**
- **A. `chain_targets: list[str]` в process_config** — статический список targets, задаётся в topology YAML процесса.
- **B. `item["target"]`** — каждый item сам несёт свой target (для fan-out как region_split: разные регионы → разные процессы).
- **C. `wires` из topology** — GenericProcess парсит wires при bootstrap, маршрутизирует по типу выходного канала.
- **D. Гибрид A+B** — `chain_targets` как default, `item["target"]` override per-item.

**Влияет на:** Task 5.3 (routing logic), Task 5.4 (capture target), Task 5.5 (processing pass-through), Task 5.6 (stitcher target), Task 5.7 (output side-effects), Task 5.8 (topology schema).

**Решение: Вариант D — гибрид chain_targets + item["target"].**

- `chain_targets: list[str]` в config процесса — default routing для 90% случаев (простой pipeline, broadcast).
- `item["target"]` — per-item override для fan-out сценариев (region_split: разные регионы → разные процессы).
- Логика Chain Worker: если item содержит `target` → отправить туда; иначе → отправить всем из `chain_targets`.
- Плагин обычно НЕ ставит target (не знает про routing), кроме fan-out где это часть логики разделения.

**Обоснование:**
1. Простые pipeline (camera→processor→gui) работают через статический chain_targets — плагины не знают про routing.
2. Fan-out (region_split) требует per-item routing — только plugin знает какой region куда.
3. Wires из topology (Вариант C) дублируют chain_targets — используем для валидации при boot, не для runtime routing.

---

### Q2. Item schema: типизация контракта между плагинами  `[DECIDED — Вариант C (SchemaBase)]`

**Контекст:** Сейчас `item: dict` — неявный контракт. Какие ключи mandatory, какие optional, как валидируется.

**Варианты:**
- **A. Чистый `dict`** — без типизации, договор в README. Минимум кода, максимум footgun.
- **B. `TypedDict`** в `process_module/generic/item.py` — статическая типизация без runtime overhead.
- **C. `pydantic` dataclass `PipelineItem`** — runtime валидация на boundaries (Data Worker → Chain Worker).
- **D. Dual:** `TypedDict` для in-process, `pydantic` для cross-process boundary.

**Mandatory ключи (минимум):** `frame: ndarray | None`, `camera_id: int`, `seq_id: int`, `timestamp: float`.
**Optional:** `region_name`, `total_regions`, `original_x`, `original_y`, `target`, `frame_id`, ...

**Влияет на:** Task 5.2 (где определить тип), все последующие задачи (импорт типа), Task 5.1 (что InspectorManager видит в item).

**Решение: Вариант C — PipelineItem(SchemaBase) с FieldMeta.**

- `PipelineItem` наследует SchemaBase (единый стиль с регистрами).
- `model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")` — принимает ndarray и произвольные ключи от плагинов.
- Core fields с FieldMeta: `frame`, `camera_id`, `seq_id`, `timestamp` (обязательные); `region_name`, `total_regions`, `original_x`, `original_y`, `target`, `_output_port` (optional).
- Валидация только на boundaries: вход в pipeline (Data Worker) + выход source (produce). В горячем пути между плагинами — dict as-is, zero overhead.
- Debug mode: `validate_items=True` в config → валидация после каждого plugin.process().
- Метаданные FieldMeta потребляются: topology editor GUI (input/output контракт), compatibility checker (совместимость плагинов), автодокументация pipeline.

**Обоснование:**
1. Единый стиль SchemaBase + FieldMeta везде (регистры, items) — меньше когнитивной нагрузки.
2. Закладываем архитектуру сразу — не переделывать при появлении topology editor.
3. `extra="allow"` позволяет плагинам добавлять любые ключи без изменения schema.
4. Boundary-only validation — приемлемый компромисс performance vs safety.

---

### Q3. Frame ownership и IPC safety  `[DECIDED — Вариант D]`

**Контекст:** `item` содержит `frame: ndarray`. Если кто-то случайно сделает `send_data(item)` — pickle гигабайтного массива в IPC. SHM существует именно чтобы этого избегать.

**Варианты:**
- **A. Дисциплина в коде** — комментарий "frame только in-process, перед IPC удалять и писать в SHM". Нет защиты на уровне типов.
- **B. Два типа:** `LocalItem` (с frame) vs `MessagePayload` (без frame, со ссылкой на SHM slot). Конвертация на boundary GenericProcess.
- **C. Lazy frame-доступ:** `item.frame` — property, читает из SHM при обращении. Pickle сериализует только метаданные.
- **D. Стандарт MessageAdapter:** middleware вытаскивает `frame` перед `send` и кладёт обратно после `receive` (как сейчас, но автоматически для всех item-сообщений).

**Влияет на:** Task 5.3 (где split frame ↔ SHM), Task 5.6 (stitcher cross-process), Task 5.7 (output не отправляет frame дальше).

**Решение: Вариант D — SHM middleware (FrameShmMiddleware).**

- Data Worker (receive): SHM read → `item["frame"] = ndarray` (frame восстановлен из SHM ref).
- Chain Worker (send): `item.pop("frame")` → SHM write → IPC отправляется без frame (только shm_ref + metadata).
- Плагин работает с `item["frame"]` как с обычным ndarray — не знает про SHM.
- Защита автоматическая: невозможно случайно отправить frame через IPC (middleware всегда strip перед send).
- Адаптируется из FrameShmMiddleware прототипа v1 (уже реализован аналогичный паттерн).

**Обоснование:**
1. Плагин полностью изолирован от SHM — чистая функция `process(items) → items`.
2. Невозможна ошибка "забыл убрать frame перед отправкой" — middleware автоматический.
3. FrameShmMiddleware из v1 уже решает эту задачу — адаптация, не написание с нуля.

---

### Q4. Backwards-compat: судьба `register_message_handler` для data flow  `[DECIDED — Вариант B]`

**Контекст:** `register_message_handler(key, handler)` во фреймворке используется на двух уровнях:

**Control plane (system) — нетронуто:**
- `process_module/core/process_module.py:185` — `state.changed` (StateStore IPC)
- `process_module/lifecycle/process_lifecycle.py:151` — все commands из `command_manager` (start_capture, stop_capture, ...)
- `process_manager_module/process/process_manager_process.py:158` — `process.command` (AD-8)
- `process_manager_module/monitor/process_monitor.py:128` — `heartbeat`
- `register_update` — IPC от RegistersManager (см. раздел "Регистры" ниже)

**Data plane (data flow) — мигрируется:**
- 12 плагинов прототипа_2 регистрируют handlers для: `frame_ready`, `region_ready`, `region_processed`, `frame_processed`, `detection_result`. Все дублируют один паттерн (handler сохраняет `_pending_frame_info` → worker_loop читает SHM → обрабатывает → пишет SHM → `io.send_data`). Это и есть тот boilerplate, ради которого затеян рефакторинг.

**Решение: Вариант B — полная миграция data plane в Phase 5.**

- Все 12 плагинов мигрируются на `process(items)` в Tasks 5.5-5.7.
- В GenericProcess (Task 5.3) **не появляется** branch "if плагин зарегистрировал handler — диспатчить через handler". Один путь данных: `IPC → Data Worker → item → InspectorManager → chain_queue → Chain Worker → process() → SHM → IPC`.
- `register_message_handler` как метод RouterManager **остаётся** — используется фреймворком для control plane (state, heartbeat, commands, register_update).
- Capture plugin (source) handler не использует — он остаётся в стороне.

**Обоснование:**
1. Все потребители (12 плагинов) мигрируются в той же фазе — нет внешних API consumers.
2. Control vs data plane — чистое разделение, без exception cases.
3. Между Task 5.3 и Task 5.7 прототип временно не работает (часы до e2e в Task 5.8) — приемлемо для одной фазы.

**Риск:** если в Phase 6/7 понадобится data-handler для side-channel — придётся обосновать и аккуратно вернуть. Это правильный gating против "по привычке зарегистрировать handler в плагине".

**Влияет на:** Task 5.3 (один путь, без backwards-compat кода), Tasks 5.5-5.7 (полная миграция всех плагинов).

---

### Q5. Декомпозиция GenericProcess  `[DECIDED — Вариант B (компоненты + chain_module)]`

**Контекст:** GenericProcess берёт на себя: lifecycle + 3 worker'а + SHM на двух концах + InspectorManager + source-loop + routing + backwards-compat. Риск god-class.

**Варианты:**
- **A. Всё в `generic_process.py`** — как сейчас в плане Task 5.3. Простота, но толстый файл (~600 строк).
- **B. Разбить на компоненты:**
  - `PipelineExecutor` — chain worker + plugin orchestration
  - `DataReceiver` — data worker + IPC→item трансформация
  - `SourceProducer` — source-loop для produce()
  - `GenericProcess` — композиция, lifecycle, configuration

  Каждый компонент тестируется отдельно. ~150-200 строк на компонент.

- **C. Промежуточный** — выделить только `PipelineExecutor` (самая сложная часть), остальное в GenericProcess.

**Влияет на:** Task 5.3 (структура файлов), тестируемость, будущая расширяемость.

**Решение: Вариант B — декомпозиция на компоненты в `process_module/generic/` + интеграция с chain_module.**

Структура:
```
process_module/generic/
  generic_process.py        — ~150 строк, композиция + lifecycle + Wire routing
  data_receiver.py          — ~120 строк, receive loop + FrameShmMiddleware + InspectorManager
  pipeline_executor.py      — ~180 строк, PluginStep адаптер + ChainRunnable/DagRunnable
  source_producer.py        — ~80 строк, produce() loop + SHM write + send
  inspector_manager.py      — ~150 строк, буферизация по (camera_id, seq_id)
```

Ключевые решения:
1. **PipelineExecutor использует chain_module** (ChainRunnable для линейного, DagRunnable для графа). Адаптер `PluginStep` оборачивает `plugin.process()` в `RunnableStep` интерфейс.
2. **Port routing сразу:** плагины декларируют inputs/outputs (Port), internal_wires в topology определяют граф. Auto-detect: есть wires → dag mode, нет → chain mode.
3. **Parallel bundles:** для DAG mode — `detect_parallel_bundles()` + `ParallelChainRunnable` из chain_module. Плагины в параллельной группе исполняются одновременно.
4. **Worker lifecycle** через существующий worker_module (LOOP mode с stop_event + pause_event).
5. **FrameShmMiddleware** адаптируется из прототипа v1.
6. **Не отдельные модули фреймворка** — компоненты используются только GenericProcess, полноценный модуль = overkill.

**Переиспользование из фреймворка:**
- `chain_module` — ChainRunnable, DagRunnable, ParallelChainRunnable, topological_sort, detect_parallel_bundles
- `worker_module` — WorkerManager (LOOP mode) для всех worker loops
- `router_module` — AsyncSender/AsyncReceiver для IPC
- `shared_resources_module` — MemoryManager для SHM
- `process_module/plugins/port.py` — Port, are_ports_compatible()
- FrameShmMiddleware из прототипа v1

**Обоснование:**
1. Каждый компонент тестируется изолированно (mock dependencies).
2. chain_module уже реализует execution patterns — не дублируем.
3. Архитектура готова к DAG без переделки (смена config).
4. ~650 строк нового кода вместо монолита 600+.

---

### Q6. Backpressure policy  `[DECIDED — Block + Alert (Process ALL)]`

**Контекст:** `chain_queue = queue.Queue(maxsize=64)`. Что делать когда полна?

**Варианты:**
- **A. Block-with-timeout** (как сейчас в плане) — Data Worker блокируется на `put(timeout=...)`, логирует warning. Cascade: IPC очередь растёт.
- **B. Drop-on-full** — `put_nowait`, при Full — drop item, метрика `dropped_frames++`. Минимизирует latency, теряет данные.
- **C. Drop-oldest** — при Full удалить старейший из очереди и положить новый. Свежие данные приоритет, но сложнее реализация.
- **D. Throttle source** — backpressure до CapturePlugin (skip следующий produce). Только для source-процессов.

**Влияет на:** Task 5.3 (логика queue), метрики, поведение под нагрузкой.

**Решение: Block + Alert — обработать ВСЁ, алерт при sustained lag.**

- **НИКОГДА не drop кадры.** Каждая бутылка ДОЛЖНА быть проверена. Пропуск = дефект на полке.
- `queue.put(timeout=lag_alert_threshold)` — ждём освобождения очереди.
- Если очередь полна дольше threshold (default 2 сек) → алерт "Pipeline overload: не успевает за конвейером".
- После алерта — всё равно ждём и обрабатываем (данные нужны downstream машинам).
- Метрики: `queue_depth`, `max_queue_depth`, `processing_lag_ms`, `overload_events`.

**Доменный контекст:**
- Отбраковщик находится через 5-10 бутылок — есть физический буфер для "догнать".
- Даже если отбраковщик не успел — данные передаются дальше по линии (следующие машины словят).
- Если часто не успевает — проблема конфигурации/оптимизации, не runtime fix. Оператор видит алерт и оптимизирует настройки.

**Конфигурация:**
```yaml
processor:
  backpressure: block_and_alert
  queue_size: 64
  lag_alert_threshold_sec: 2.0
```

**Обоснование:**
1. Для инспекции дефектов потеря кадра = пропуск дефекта.
2. Физический буфер 5-10 бутылок позволяет "догнать" после лага.
3. Downstream машины используют данные даже с задержкой.
4. Sustained lag — это проблема конфигурации, решается оператором.

---

### Q7. Error policy: `plugin.process()` бросает exception  `[DECIDED — Pass-through + Mark Suspect + Circuit Breaker]`

**Контекст:** Что происходит при сбое плагина в середине chain?

**Варианты:**
- **A. Drop + log** (как сейчас в плане) — items теряются, exception логируется, chain продолжает.
- **B. Dead-letter queue** — failed items идут в отдельную очередь / SQLite таблицу для разбора.
- **C. Circuit breaker** — N exception подряд → плагин помечается failed, chain пропускает его.
- **D. Retry with backoff** — N попыток на одном items. Только для transient errors.

**Влияет на:** Task 5.3 (try/except логика), Task 5.7 (database может быть dead-letter sink), наблюдаемость.

**Решение: Pass-through + Mark Suspect + Circuit Breaker (A+C гибрид).**

- **Одна ошибка:** exception логируется, item получает `inspection_status = "not_inspected"`, передаётся дальше (pass-through). Данные НЕ теряются.
- **N ошибок подряд (circuit breaker):** плагин помечается bypassed, chain пропускает его. Алерт "inspection degraded".
- **Критический плагин (detector):** если bypassed → алерт level CRITICAL, все items помечаются "suspect".
- **Auto-reset:** через configurable таймер (default 60 сек) executor пробует включить плагин обратно.
- **Бутылка с `not_inspected`/`suspect`:** shift register помечает → отбраковщик выкидывает (лучше выкинуть хорошую чем пропустить плохую).
- **Данные ВСЕГДА передаются дальше** — downstream машины могут перепроверить.

**Конфигурация:**
```yaml
error_policy:
  max_consecutive_fails: 5
  on_fail: mark_suspect     # item["inspection_status"] = "not_inspected"
  critical_plugins: ["detector"]
  auto_reset_sec: 60
```

**Обоснование:**
1. Для инспекции потеря данных недопустима — pass-through + маркировка.
2. Circuit breaker защищает от cascade failure (плагин спамит exceptions → тормозит pipeline).
3. Suspect items отбраковываются — безопасный fail-mode.
4. Auto-reset позволяет восстановиться после transient error без вмешательства оператора.

---

### Q8. Thread-safety контракт `process()`  `[DECIDED — Вариант B]`

**Контекст:** Сейчас Chain Worker один — process() вызывается последовательно. Если в будущем распараллелим (ThreadPool по items) — `process()` должен быть thread-safe или явно non-reentrant.

**Варианты:**
- **A. Required thread-safe** — фиксируем в base.py docstring как требование к авторам плагинов.
- **B. Декларативно через атрибут** — `class Plugin: thread_safe = True/False`, GenericProcess уважает.
- **C. Не фиксировать** — решим когда дойдём до параллелизма. Риск: переписывать плагины.

**Влияет на:** Task 5.2 (docstring), будущий параллелизм, контракт плагина.

**Решение: Вариант B — декларативно через ClassVar атрибут.**

- `thread_safe: ClassVar[bool] = False` в базовом классе ProcessModulePlugin (default = НЕ thread-safe, safe by default).
- `thread_safe = True` → PipelineExecutor может вызывать process() параллельно (для stateless плагинов в parallel bundles).
- `thread_safe = False` → PipelineExecutor гарантирует sequential execution (lock или single-thread).
- Простые stateless плагины (resize, grayscale, negative, flip) → `thread_safe = True`.
- Плагины с mutable state (frame_counter, database, stitcher) → `thread_safe = False` (default).

**Обоснование:**
1. ParallelChainRunnable в DAG mode вызывает плагины из parallel bundles одновременно — нужен контракт.
2. Default False = safe by default (автор не думал о thread-safety → не сломается).
3. Opt-in True = осознанное решение автора плагина.

---

## Регистры — control plane между frontend и backend

> **Контекст:** Обсуждение возникло после изучения `multiprocess_prototype/registers/` (v1) и `multiprocess_framework/modules/registers_module/`.

### Что такое регистр

**Регистр** — экземпляр Pydantic-схемы (`SchemaBase`) с богатыми field-level метаданными. Один Python-класс работает на обе стороны (frontend + backend), служит **единственным источником истины** для конфигурации.

```python
@register_schema("ColorMaskRegistersV1")
class ColorMaskRegisters(SchemaBase):
    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("processor",)  # backend-таргет
    )
    min_h: Annotated[int, FieldMeta(
        "Min Hue",                          # label для GUI
        info="Нижняя граница H в HSV",      # tooltip
        min=0, max=179, unit="°",           # валидация + UI hint
        routing=FieldRouting(channel="control_processor"),
    )] = 0
    # ... max_h, min_s, max_s, min_v, max_v
```

**Два потребителя одного класса:**
- **Frontend:** `FrontendRegistersBridge` автогенерит виджет (Slider 0..179, label "Min Hue", unit "°"). Изменение → `rm.set_field_value("color_mask", "min_h", 30)`.
- **Backend:** Plugin читает `self._reg.min_h` — получает свежее значение, обновлённое через IPC.

### Инфраструктура — уже есть во фреймворке

`multiprocess_framework/modules/registers_module/` — полноценный модуль:
- `RegistersManager` — хранение, pub/sub, set_field_value с dispatch
- `build_connection_map_from_registers` — карта register → process из `register_dispatch`
- `dispatch.py`, `routing_map.py` — маршрутизация изменений
- `FrontendRegistersBridge` (frontend_module) — UI-обёртка
- `register_message_handler("register_update", ...)` — control plane на backend

В `prototype_v1` — 8 доменов регистров (camera, processor, renderer, settings, sources, processing, payloads, pipeline). В `prototype_v2` регистров **нет** — плагины читают конфиг из YAML через `cfg.get(key, default)`. Это пробел, который вылезет при росте GUI.

### Связь с Q4 (data plane vs control plane)

`register_update` идёт через тот же механизм `register_message_handler` что мы обсуждали в Q4. Но это **control plane**, не data plane:

| Plane | Сообщения | Механизм | Phase 5 |
|-------|-----------|----------|---------|
| **Data** | `frame_ready`, `region_ready`, `region_processed`, `frame_processed`, `detection_result` | `process(items)` (новое) | мигрируется |
| **Control** | `register_update`, `state.changed`, `heartbeat`, `process.command`, `<command_name>` | `register_message_handler` (как сейчас) | **нетронуто** |

Это окончательно подтверждает Вариант B из Q4: data plane становится один путь, control plane сохраняет существующий механизм.

### Как регистры применимы к плагинам Phase 5

**Сейчас (v2):** плагин читает конфиг при `configure()`:
```python
def configure(self, ctx):
    self._lower_h = ctx.config.get("min_h", 0)  # snapshot, не обновляется
```

Команда `set_hsv_range` для runtime-изменения:
```python
commands = {"set_hsv_range": ...}
def _set_hsv_range(self, lower, upper): ...
```

**С регистрами:**
```python
class ColorMaskPlugin(ProcessModulePlugin):
    def register_schema(self) -> SchemaBase:
        return ColorMaskRegisters()  # экземпляр со defaults

    def configure(self, ctx):
        self._reg = ctx.registers.get("color_mask")  # типизированный экземпляр
        # Опционально: подписка на тяжёлые пересчёты
        ctx.registers.subscribe("color_mask", "min_h", self._rebuild_arrays)

    @for_each
    def process(self, item):
        frame = item.get("frame")
        if frame is None: return None
        lower = (self._reg.min_h, self._reg.min_s, self._reg.min_v)  # авто-update
        upper = (self._reg.max_h, self._reg.max_s, self._reg.max_v)
        # ... cv2.inRange ...
```

**Что меняется:**
- Команды runtime-настройки (set_hsv_range, ...) **удаляются** — заменяются регистрами.
- GUI получает виджеты бесплатно из `FieldMeta` плагина.
- Один источник истины frontend ↔ backend.

### Q9. Регистры — per-plugin vs централизованные  `[DECIDED — External layer + convention mapping]`

**Варианты:**
- **A. Централизованно (как v1):** `multiprocess_prototype_2/registers/{camera,processor,...}/schemas.py`. Плюс — общий вид. Минус — разрастается с ростом плагинов.
- **B. Per-plugin:** регистр живёт рядом с плагином — `plugins/color_mask/{plugin.py, config.py, ...}`. Плюс — плагин самосодержащий, легко добавлять/удалять. Минус — нет общего обзора.
- **C. Гибрид:** общие регистры (camera, settings, theme) — централизованно; плагин-специфичные — рядом с плагином.

**Решение: Регистры = внешний слой на backend, progressive enhancement, convention mapping.**

**Архитектура:**
- Регистры живут в `multiprocess_prototype_2/registers/` (отдельный слой, НЕ внутри плагина).
- Плагин самосодержащий — работает на defaults из config/hardcode без регистров.
- Создание `registers/color_mask.py` = progressive enhancement: этот параметр становится управляемым из GUI.
- Нет регистра → плагин на defaults, ничего не ломается (graceful degradation).

**Маппинг register → plugin:**
- Convention by name: `registers/color_mask.py` → автоматически к `plugins/color_mask/`.
- Topology override: в YAML можно явно указать `register: custom_name`.
- Общие регистры (camera, display): `registers/shared/` — подключаются через topology explicit.

**Разграничение:** регистр читается одним плагином → маппинг по имени. Регистр нужен 2+ потребителям → `registers/shared/`.

**Обоснование:**
1. Плагин = чистая функция, не зависит от register framework (независимость 9/10).
2. "Забыл создать регистр" = не баг, а "параметром нельзя управлять из GUI" (graceful degradation).
3. Добавил файл → GUI получил слайдер. Удалил → плагин на defaults. Zero ceremony.

### Q10. RegistersManager в GenericProcess  `[DECIDED — Вариант A + PM broadcast]`

**Варианты:**
- **A. GenericProcess собирает RegistersManager** — при bootstrap обходит плагины, вызывает `plugin.register_schema()`, формирует RegistersManager. Регистрирует handler `register_update`.
- **B. RegistersManager как отдельный manager-процесс** — один на всю систему, плагины подключаются как клиенты.
- **C. Каждый процесс держит свой RegistersManager** — изолированно, синхронизация через IPC `register_update`.

**Решение: Вариант A — локальный RegistersManager в GenericProcess + PM как broadcast hub при boot.**

**Архитектура:**
- Владелец состояния регистров — GenericProcess (локальный RegistersManager, только свои плагины).
- При boot: GenericProcess сканирует `registers/` для своих плагинов → отправляет schemas + current values в ProcessManager.
- ProcessManager собирает от ВСЕХ процессов → формирует полный каталог → broadcast ВСЕМ (включая GUI).
- GUI — не special case, просто ещё один процесс получивший каталог (симметрично).
- Runtime update: GUI → direct IPC → target GenericProcess (`register_update`), target → PM → broadcast (`register_changed`).
- PM в runtime — только relay broadcast, не в hot path.

**Протокол (3 типа сообщений):**
- `register_schemas` — при boot, GenericProcess → PM (schemas + values)
- `register_update` — runtime, GUI → target process (изменение значения)
- `register_changed` — runtime, target process → PM → broadcast all (уведомление об изменении)

**Отличие от StateStore:**
- StateStore = runtime state (fps, frame_count, connection_status) — меняется само.
- Registers = user config (HSV thresholds, scale) — меняет пользователь.
- Разные домены, разные протоколы. В будущем можно связать (register_changed → пишем в StateStore для наблюдаемости).

**Обоснование:**
1. Локальное чтение быстрое (plugin читает self._reg.min_h без IPC).
2. PM = discovery hub, не SPOF в runtime.
3. Симметричная раздача: GUI, другие процессы — все получают каталог одинаково.
4. Lightweight протокол (3 msg types) vs StateStore overkill.

---

## Порядок выполнения

### Phase 5.1: Инфраструктура (фреймворк)
- Task 5.1: InspectorManager
- Task 5.2: Расширение ProcessModulePlugin (process/produce + опционально register_schema)
- Task 5.3: Data Worker + Chain Worker в GenericProcess
- Task 5.9: Per-plugin registers integration *(новая, после Q9/Q10)*

### Phase 5.2: Миграция плагинов (прототип)
- Task 5.4: CapturePlugin --> produce()
- Task 5.5: Processing-плагины --> process() (color_mask использует регистр вместо команды)
- Task 5.6: StitcherPlugin --> process() (fan-in)
- Task 5.7: Output-плагины --> process()

### Phase 5.3: Интеграция и тесты
- Task 5.8: Topology обновление и e2e тест

---

### Task 5.9 -- Per-plugin registers integration

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** Интегрировать RegistersManager с GenericProcess согласно решениям Q9 (external layer + convention mapping) и Q10 (локальный RegistersManager + PM broadcast): плагины опционально экспортируют register_schema, GenericProcess собирает регистры при bootstrap, регистрирует handler `register_update`, обеспечивает плагину доступ через `ctx.registers`.

**Context:** Регистры существуют во фреймворке (`registers_module`), активно использовались в prototype_v1. В prototype_v2 их пока нет — плагины читают конфиг из YAML. Эта задача переносит control-plane инфраструктуру в новую архитектуру v2. Организация по Q9: регистры в `multiprocess_prototype_2/registers/` (внешний слой), convention mapping по имени (`registers/color_mask.py` → `plugins/color_mask/`). Владелец состояния по Q10: локальный RegistersManager в GenericProcess, PM = broadcast hub при boot.

**Files:**
- `multiprocess_framework/modules/process_module/plugins/base.py` — добавить `register_schema(self) -> SchemaBase | None` (default: None)
- `multiprocess_framework/modules/process_module/plugins/base.py` — расширить PluginContext полем `registers: RegistersManager | None`
- `multiprocess_framework/modules/process_module/generic/generic_process.py` — bootstrap RegistersManager из plugin schemas, handler `register_update`, boot-time `register_schemas` → PM, relay `register_changed` → PM
- `multiprocess_prototype_2/registers/color_mask.py` — СОЗДАТЬ: ColorMaskRegisters(SchemaBase) с FieldMeta (min_h, max_h, min_s, max_s, min_v, max_v)
- `multiprocess_prototype_2/plugins/color_mask/plugin.py` — proof-of-concept: читать `ctx.registers` вместо команды set_hsv_range

**Steps:**
1. Добавить в `ProcessModulePlugin.base.py` метод `register_schema(self) -> SchemaBase | None`:
   ```python
   def register_schema(self) -> "SchemaBase | None":
       """Опциональный регистр плагина. Если None — плагин на defaults из config.
       Convention: возвращённая схема маппится на plugin.name в RegistersManager."""
       return None
   ```

2. Расширить `PluginContext` полем `registers: RegistersManager | None = None` — плагин проверяет сам, есть ли регистр.

3. В `generic_process.py` bootstrap RegistersManager (решение Q10):
   - Сканировать `multiprocess_prototype_2/registers/` — найти файлы по convention (`{plugin_name}.py`).
   - Для каждого плагина: если файл регистра существует → импортировать схему → `RegistersManager.register(plugin.name, schema_instance)`.
   - Вызвать `plugin.configure(ctx)` уже с заполненным `ctx.registers`.
   - Зарегистрировать handler: `register_message_handler("register_update", self._on_register_update)`.

4. При boot отправить schemas в ProcessManager (Q10, протокол `register_schemas`):
   ```python
   schemas_payload = registers_manager.export_schemas()  # dict: name → schema dict
   self._ctx.io.send_data("process_manager", "register_schemas", schemas_payload)
   ```

5. В `_on_register_update(msg)` handler:
   - `registers_manager.set_field_value(msg["register"], msg["field"], msg["value"])`.
   - Relay в PM: `send_data("process_manager", "register_changed", {...})`.

6. **Создать `multiprocess_prototype_2/registers/color_mask.py`** — proof-of-concept:
   ```python
   from multiprocess_framework.modules.data_schema_module import SchemaBase, FieldMeta
   from typing import Annotated

   class ColorMaskRegisters(SchemaBase):
       min_h: Annotated[int, FieldMeta("Min Hue", min=0, max=179, unit="°")] = 0
       max_h: Annotated[int, FieldMeta("Max Hue", min=0, max=179, unit="°")] = 179
       min_s: Annotated[int, FieldMeta("Min Saturation", min=0, max=255)] = 50
       max_s: Annotated[int, FieldMeta("Max Saturation", min=0, max=255)] = 255
       min_v: Annotated[int, FieldMeta("Min Value", min=0, max=255)] = 50
       max_v: Annotated[int, FieldMeta("Max Value", min=0, max=255)] = 255
   ```

7. **Рефакторить `color_mask/plugin.py`** (proof-of-concept):
   - В `configure(ctx)`: `self._reg = ctx.registers` (если None — fallback на config.get()).
   - В `process(item)`: `lower = (self._reg.min_h, ...)` если reg есть, иначе `self._lower`.
   - Команда `set_hsv_range` удаляется — заменена регистром.

**Acceptance criteria:**
- [ ] `ProcessModulePlugin.register_schema()` существует с default None
- [ ] `PluginContext.registers: RegistersManager | None` поле присутствует
- [ ] GenericProcess при bootstrap находит `registers/color_mask.py` по convention и передаёт ctx.registers в ColorMaskPlugin
- [ ] GenericProcess при boot отправляет `register_schemas` в ProcessManager
- [ ] GenericProcess регистрирует handler `register_update`, применяет изменение к RegistersManager + relay в PM
- [ ] `multiprocess_prototype_2/registers/color_mask.py` создан с 6 полями FieldMeta
- [ ] color_mask plugin читает HSV thresholds из `ctx.registers` вместо команды set_hsv_range
- [ ] Плагин без регистра (например resize) работает без изменений — graceful degradation
- [ ] Тесты: bootstrap convention scan, register_update handler, graceful degradation без регистра (≥ 5 тестов)

**Out of scope:** Frontend integration (FrontendRegistersBridge) — отдельная фаза. PM-side broadcast implementation (ProcessManager принимает register_schemas — реализуется в PM task отдельно). Миграция всех плагинов на регистры — постепенно, color_mask первый как proof-of-concept.
**Dependencies:** Task 5.2, Task 5.3

---

## Задачи

### Task 5.1 -- InspectorManager

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** Создать InspectorManager -- компонент буферизации items по seq_id для fan-in сценариев
**Context:** В текущей архитектуре stitcher сам буферизует регионы по seq_id с timeout. Эта логика должна быть вынесена в универсальный менеджер внутри GenericProcess. InspectorManager принимает item из Data Worker, проверяет наличие `total_regions` в метаданных, буферизует по seq_id, и когда коллекция готова -- отдает `list[dict]` в очередь для Chain Worker.

**Мотивация:** В сценарии «N камер -> один processing-процесс» каждая камера может слать свои регионы (например, по 3 ROI). Без отдельного буфера на каждую камеру seq_id=5 от camera_1 смешается с seq_id=5 от camera_2, и stitcher склеит каши. InspectorManager изолирует коллекции по `(camera_id, seq_id)` и отдает в Chain Worker полную коллекцию одной камеры.

**Files:**
- `multiprocess_framework/modules/process_module/generic/inspector_manager.py` -- СОЗДАТЬ
- `multiprocess_framework/modules/process_module/generic/__init__.py` -- добавить экспорт
- `multiprocess_framework/modules/process_module/tests/test_inspector_manager.py` -- СОЗДАТЬ

> **Решение по размещению:** оставляем внутри `process_module/generic/`, не выносим в отдельный модуль. InspectorManager используется только GenericProcess; полноценный модуль (interfaces.py + README + STATUS + tests + регистрация) — overkill для ~150 строк. Если позже всплывет reuse вне GenericProcess — вынесем.

**Steps:**
1. Создать класс `InspectorManager` с интерфейсом:
   ```python
   class InspectorManager:
       def __init__(self, timeout_sec: float = 0.5, on_ready: Callable[[list[dict]], None] = None):
           """on_ready -- callback для отправки готовых коллекций в Chain Worker."""

       def on_item(self, item: dict) -> None:
           """Принять один item. Если fan-in не нужен (нет total_regions) -- сразу вызывает on_ready([item]).
           Если fan-in (total_regions > 0) -- буферизует по (camera_id, seq_id), вызывает on_ready когда все собраны или timeout."""

       def check_timeouts(self) -> None:
           """Проверить и выдать просроченные коллекции. Вызывается периодически из Data Worker."""
   ```
2. Буферизация: `dict[tuple[int, int], dict[str, dict]]` — `{(camera_id, seq_id): {region_name: item}}`. Составной ключ обязателен — иначе пересекаются seq_id из разных камер.
3. `camera_id` берется из item (default 0, если плагин его не проставил — для одно-камерного сценария). `seq_id` — из item, default 0.
4. Коллекция готова когда: `len(buffer[(cam, seq)]) >= total_regions` или `time.monotonic() - timestamp > timeout_sec`
5. Thread-safety: `threading.Lock` на буфер (Data Worker может вызывать on_item из одного потока, но check_timeouts может вызываться параллельно)
6. Очистка старых записей (>2x timeout) в check_timeouts
7. Логирование через callback `log_info`/`log_error` (передаются в конструктор)

**Acceptance criteria:**
- [ ] Без fan-in (нет `total_regions` в item): `on_item({"frame": ..., "seq_id": 1})` → немедленно вызывает `on_ready([item])`
- [ ] С fan-in: 3 items с `total_regions=3, camera_id=0, seq_id=5` → вызывает `on_ready([item1, item2, item3])` после третьего
- [ ] **Multi-camera изоляция:** items с `(camera_id=0, seq_id=5)` и `(camera_id=1, seq_id=5)` буферизуются раздельно, on_ready вызывается дважды по разным коллекциям
- [ ] Timeout: 2 из 3 items + timeout → вызывает `on_ready([item1, item2])` при check_timeouts
- [ ] Thread-safe: concurrent on_item не вызывает race condition
- [ ] Тесты: >= 9 тестов (happy path, fan-in, multi-camera, timeout, cleanup, thread-safety)

**Out of scope:** Не менять существующие файлы GenericProcess (это Task 5.3). Не трогать IPC/SHM.
**Edge cases:** total_regions=0 (трактовать как "нет fan-in"), total_regions=1 (один item = готово), дублирование region_name в одном (camera_id, seq_id) — перезаписать с warning, item без camera_id — трактовать camera_id=0.
**Dependencies:** Нет

---

### Task 5.2 -- Расширение ProcessModulePlugin + декоратор @for_each

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Добавить универсальные методы `process()` / `produce()` и helper-декоратор `@for_each` в базовый класс ProcessModulePlugin
**Context:** Один контракт `process(items) -> items` покрывает все семантики (1:1, 1:N, N:1, фильтрация, batching). Декоратор `@for_each` — опциональный сахар для простых 1:1 / 1:N плагинов: позволяет писать per-item логику. Контракт это не меняет — `@for_each` оборачивает метод так, что снаружи вызывается `process(items) -> list[dict]`.

Source-плагины реализуют `produce() -> items`. Старые методы (`configure`, `start`, `shutdown`) остаются для обратной совместимости и lifecycle.

**Files:**
- `multiprocess_framework/modules/process_module/plugins/base.py` -- добавить методы и декоратор

**Steps:**
1. Добавить в класс `ProcessModulePlugin` метод `process()`:
   ```python
   def process(self, items: list[dict]) -> list[dict]:
       """Обработка items. Override в processing/output-плагинах.
       Default: pass-through (return items).
       items -- список {"frame": ndarray, ...metadata}.
       Чистая обработка: без IPC, без SHM, без PluginContext.

       Покрывает все семантики:
         1:1   resize, grayscale, negative, ...
         1:N   region_split
         N:1   stitcher
         N:0   фильтрация (return [])
         batch frame_counter, FPS log
       """
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
4. Добавить декоратор `for_each` рядом с классом (модульная функция, не метод):
   ```python
   import functools

   def for_each(func):
       """Сахар: per-item функция -> process(items) -> list[dict].
       Применяется к методу process плагина.
       Возврат декорируемой функции:
         dict       -> 1:1
         list[dict] -> 1:N (fan-out)
         None       -> фильтрация
       """
       @functools.wraps(func)
       def wrapper(self, items: list[dict]) -> list[dict]:
           result = []
           for item in items:
               out = func(self, item)
               if out is None:
                   continue
               if isinstance(out, list):
                   result.extend(out)
               else:
                   result.append(out)
           return result
       return wrapper
   ```
5. Добавить атрибут класса `thread_safe` (решение Q8):
   ```python
   from typing import ClassVar

   class ProcessModulePlugin:
       thread_safe: ClassVar[bool] = False
       """PipelineExecutor уважает этот флаг при DAG/parallel execution.
       False (default) — sequential, safe by default.
       True — разрешает параллельный вызов process() (только для stateless плагинов)."""
   ```
6. НЕ делать process/produce абстрактными (чтобы не ломать существующие плагины вроде heartbeat — они получают pass-through по умолчанию).
7. Экспортировать `for_each` из `multiprocess_framework/modules/process_module/plugins/__init__.py` рядом с `ProcessModulePlugin`.

**Acceptance criteria:**
- [ ] `process()` существует с default pass-through
- [ ] `produce()` существует с default NotImplementedError
- [ ] `is_source` property работает
- [ ] `thread_safe: ClassVar[bool] = False` присутствует в базовом классе
- [ ] `for_each` декоратор экспортирован, работает на методе плагина
- [ ] Декоратор корректно обрабатывает `dict` (append), `list[dict]` (extend), `None` (skip)
- [ ] Существующие плагины (heartbeat, frame_counter) не ломаются — они не переопределяют process/produce и это OK
- [ ] Тесты base.py: >= 6 тестов (default process pass-through, produce raises, is_source для разных category, thread_safe default False, @for_each для 1:1, @for_each для 1:N через list, @for_each фильтрация через None)

**Out of scope:** Не менять плагины прототипа (это Task 5.4-5.7). Не удалять старые абстрактные методы configure/start.
**Dependencies:** Нет

---

### Task 5.3 -- Компонентная архитектура GenericProcess (DataReceiver + PipelineExecutor + SourceProducer)

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Реализовать компонентную декомпозицию GenericProcess согласно решению Q5: DataReceiver, PipelineExecutor, SourceProducer как отдельные файлы + интеграция с chain_module, FrameShmMiddleware, block+alert backpressure (Q6), pass-through+circuit breaker error policy (Q7)
**Context:** Это центральная задача рефакторинга. Вместо монолита — четыре компонента по ~80-180 строк каждый. PipelineExecutor использует chain_module (ChainRunnable/DagRunnable). DataReceiver оборачивает FrameShmMiddleware + InspectorManager. SourceProducer управляет produce()-loop. GenericProcess — тонкая обёртка-композиция.

**Files:**
- `multiprocess_framework/modules/process_module/generic/data_receiver.py` — СОЗДАТЬ (~120 строк)
- `multiprocess_framework/modules/process_module/generic/pipeline_executor.py` — СОЗДАТЬ (~180 строк)
- `multiprocess_framework/modules/process_module/generic/source_producer.py` — СОЗДАТЬ (~80 строк)
- `multiprocess_framework/modules/process_module/generic/generic_process.py` — рефакторинг (композиция, ~150 строк)
- `multiprocess_framework/modules/process_module/generic/generic_process_config.py` — расширить: `chain_targets: list[str]`, `queue_size: int = 64`, `lag_alert_threshold_sec: float = 2.0`, `error_policy` секция

**Steps:**
1. **Создать `data_receiver.py`** — компонент приёма и трансформации IPC-сообщений в items:
   - Конструктор принимает `router_manager`, `inspector_manager`, `chain_queue`, `shm_middleware`, `log_*` callbacks
   - Метод `run_loop(stop_event)`: `router_manager.receive(channel_types=["data"])` в цикле
   - Для каждого сообщения: `shm_middleware.restore_frame(msg)` → `item = {**msg}` → `inspector_manager.on_item(item)`
   - Периодически (каждые ~0.1 сек): `inspector_manager.check_timeouts()`
   - Backpressure (Q6): `chain_queue.put(items, timeout=lag_alert_threshold_sec)` — если `Full` → алерт + retry; метрики `queue_depth`, `overload_events`

2. **Создать `pipeline_executor.py`** — компонент исполнения chain через chain_module:
   - Конструктор принимает `plugins: list[ProcessModulePlugin]`, `chain_targets: list[str]`, `shm_middleware`, `sender`, `error_policy_config`
   - Адаптер `PluginStep(plugin)` — оборачивает `plugin.process()` в интерфейс `RunnableStep` из chain_module
   - Метод `build_chain(wires=None)`: если wires переданы → `DagRunnable` с `detect_parallel_bundles()`, иначе → `ChainRunnable` (линейный)
   - Метод `run_loop(chain_queue, stop_event)`: `chain_queue.get(timeout=0.05)` → `chain.run(items)` → `shm_middleware.strip_frame(item)` + SHM write → IPC send (с учётом Q1: `item.get("target")` или `chain_targets`)
   - Error policy (Q7): try/except вокруг каждого PluginStep — одна ошибка → `item["inspection_status"] = "not_inspected"` + pass-through; N подряд → plugin.bypassed = True + алерт; auto-reset через таймер

3. **Создать `source_producer.py`** — компонент produce()-loop для source-плагинов:
   - Конструктор принимает `plugin: ProcessModulePlugin`, `shm_middleware`, `sender`, `chain_targets`, `target_interval_sec`, `log_*` callbacks
   - Метод `run_loop(stop_event)`: `plugin.produce()` в цикле с `target_interval_sec` throttle
   - Для каждого item: `shm_middleware.strip_frame(item)` + SHM write → IPC send в `chain_targets`
   - Smart sleep: `time.monotonic()` до и после produce() → вычитаем из target_interval_sec

4. **Рефакторить `generic_process.py`** — тонкая композиция (только lifecycle + компоненты):
   - `_init_application_threads()`: создаёт `InspectorManager`, `FrameShmMiddleware`, `DataReceiver`, `PipelineExecutor`, `SourceProducer` (если есть source-плагины)
   - Запускает каждый компонент как отдельный LOOP worker через `worker_module.WorkerManager`
   - Метод `_on_receive(items)` как callback из InspectorManager → `chain_queue.put`
   - Из config берёт `chain_targets`, `queue_size`, `lag_alert_threshold_sec`, `error_policy`

5. **Расширить `generic_process_config.py`**:
   ```python
   class GenericProcessConfig(SchemaBase):
       chain_targets: list[str] = []          # Q1: default routing targets
       queue_size: int = 64                    # Q6: internal chain_queue maxsize
       lag_alert_threshold_sec: float = 2.0   # Q6: backpressure alert threshold
       error_policy: ErrorPolicyConfig = ...  # Q7: max_consecutive_fails, critical_plugins, auto_reset_sec
   ```

6. **Wire routing при boot** (Q1): в `_init_application_threads()` парсить `wires` из topology → передать в `PipelineExecutor.build_chain(wires)`. Если wires есть → DAG mode, нет → chain mode.

7. **FrameShmMiddleware интеграция** (Q3): адаптировать из прототипа v1 (`multiprocess_prototype/`). Два метода: `restore_frame(msg) -> dict` (SHM ref → ndarray в msg["frame"]) и `strip_frame(item) -> shm_ref` (ndarray → SHM write, убрать из item). Middleware живёт в `generic/frame_shm_middleware.py`.

**Acceptance criteria:**
- [ ] Файлы `data_receiver.py`, `pipeline_executor.py`, `source_producer.py` созданы, каждый ≤ 200 строк
- [ ] `generic_process.py` после рефакторинга ≤ 180 строк (только lifecycle + композиция)
- [ ] DataReceiver: SHM middleware восстанавливает frame из shm_ref, items передаются в InspectorManager
- [ ] PipelineExecutor: ChainRunnable используется для линейного pipeline (без wires)
- [ ] PipelineExecutor: DagRunnable используется при наличии internal_wires в topology
- [ ] Backpressure (Q6): queue.put с timeout; при Full > lag_alert_threshold_sec — алерт логируется; кадры НЕ дропаются
- [ ] Error policy (Q7): exception в plugin.process() → item["inspection_status"]="not_inspected" + pass-through; N подряд → plugin.bypassed=True + алерт
- [ ] Routing (Q1): item с "target" → отправить туда; без "target" → отправить в chain_targets
- [ ] Source-плагины работают через SourceProducer.run_loop → produce() → SHM write → IPC send
- [ ] Старый `_data_receiver_loop` и монолитный chain-код удалены из generic_process.py
- [ ] Тесты: каждый компонент тестируется изолированно с mock dependencies (≥ 5 тестов на компонент)

**Out of scope:** Не мигрировать конкретные плагины прототипа (это Tasks 5.4-5.7). Не менять system_threads.py. RegistersManager интеграция — Task 5.9.
**Edge cases:**
- chain_queue полна: блокируемся, НЕ дропаем; алерт если > threshold
- plugin.process() бросает exception: pass-through + mark_suspect; N подряд → circuit breaker
- items пустые после plugin.process(): chain прерывается, IPC send не происходит
- Source + processing плагин в одном процессе: SourceProducer генерирует → items через InspectorManager → PipelineExecutor
- Процесс без source-плагинов: SourceProducer не создаётся
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

Простые 1:1 плагины используют декоратор `@for_each` (Task 5.2) для per-item логики. `frame_counter` — без декоратора (нужен batching для FPS).

1. **resize/plugin.py**:
   ```python
   from multiprocess_framework.modules.process_module.plugins import for_each

   @for_each
   def process(self, item):
       frame = item.get("frame")
       if frame is None:
           return None
       new_w, new_h = self._compute_target_size(frame)
       resized = cv2.resize(frame, (new_w, new_h), interpolation=self._interp)
       return {**item, "frame": resized, "width": new_w, "height": new_h}
   ```
   Убрать: `_on_frame_ready`, `_process_loop`, `_pending_frame_info`, `_ctx`, создание worker в start(), `register_message_handler` в configure(). Оставить configure() для чтения конфига (scale_factor, interpolation).

2. **grayscale/plugin.py**:
   ```python
   @for_each
   def process(self, item):
       frame = item.get("frame")
       if frame is None: return None
       gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
       return {**item, "frame": cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)}
   ```
   Убрать режим standalone/region — не нужен, GenericProcess маршрутизирует.

3. **negative/plugin.py**:
   ```python
   @for_each
   def process(self, item):
       frame = item.get("frame")
       if frame is None: return None
       return {**item, "frame": np.asarray(255 - frame, dtype=np.uint8)}
   ```

4. **flip/plugin.py**:
   ```python
   @for_each
   def process(self, item):
       frame = item.get("frame")
       if frame is None: return None
       return {**item, "frame": cv2.flip(frame, 0)}
   ```

5. **color_mask/plugin.py**:
   ```python
   @for_each
   def process(self, item):
       frame = item.get("frame")
       if frame is None: return None
       hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
       mask = cv2.inRange(hsv, self._lower, self._upper)
       return {**item, "frame": cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)}
   ```
   Оставить команду `set_hsv_range` и её регистрацию в configure().

6. **frame_counter/plugin.py** — БЕЗ декоратора (нужен размер пачки для FPS log):
   ```python
   def process(self, items):
       self._frame_count += len(items)
       now = time.monotonic()
       if now - self._last_log_time >= self._log_interval:
           fps = self._frame_count / (now - self._last_log_time)
           self._log_info(f"FPS: {fps:.1f} (total: {self._frame_count})")
           self._last_log_time = now
           self._frame_count = 0
       return items
   ```
   Убрать register_message_handler.

7. Для каждого плагина:
   - Убрать: `register_message_handler`, `_pending_frame_info`, `_ctx`, worker creation в start(), `_process_loop`, `io.send_data`, `mm.read_images`, `mm.write_images`
   - Оставить: `configure()` для чтения конфига, `start()` (пустой или no-op), `shutdown()` (пустой или cleanup)
   - configure() больше НЕ использует ctx.router_manager, ctx.memory_manager, ctx.worker_manager

**Acceptance criteria:**
- [ ] Каждый 1:1 плагин использует `@for_each` поверх `process`
- [ ] frame_counter использует обычный `process(items)` для batching
- [ ] Ни один processing-плагин не обращается к `ctx.router_manager`, `ctx.memory_manager`, `ctx.io`, `ctx.worker_manager`
- [ ] Каждый плагин <= 60 строк (сейчас 100-180)
- [ ] color_mask сохраняет runtime-команду set_hsv_range
- [ ] frame_counter считает кадры через process()

**Out of scope:** Не трогать capture (Task 5.4), stitcher (Task 5.6), database/frame_saver (Task 5.7).
**Dependencies:** Task 5.2



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
