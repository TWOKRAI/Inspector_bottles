# DECISIONS — shared_resources_module

Локальные архитектурные решения модуля.  
Глобальный журнал: [../../DECISIONS.md](../../DECISIONS.md)

---

## ADR-SRM-001: Удалён legacy API v1

**Дата:** 2026-04-09  
**Решение:** Удалены методы SRM: `register_process_state`, `register_process_with_config`, `update_process_state`, `get_process_state`, `get_all_process_states`, `add_shared_resource`, `get_shared_resource`, `get_data_manager`, `data_manager`, словарь `shared_resources`. Удалены `register_process_with_config` из PSR.  
**Причина:** Каноничный путь — `register_process()` (ADR-018) и `process_state_registry.register_process` / `update_state` для bundle/тонких сценариев. Доступ к схемам данных — через `DataSchemaAdapter` при необходимости.  
**Миграция:** `process_module`, `process_manager_module` переведены на `process_state_registry`.

## ADR-SRM-002: ProcessHandle как единый паттерн доступа

**Дата:** 2026-04-09  
**Решение:** Введены `ProcessHandle`, `QueueHandle`, `EventHandle`, `MemoryHandle`; методы фасада `for_process()` (не `process()` — конфликт с `BaseManager.process`), `has_process()`, `broadcast()`, `get_all_statuses()`.  
**Причина:** Несколько путей к очередям и отсутствие единого паттерна для памяти; Handle унифицирует доступ.

## ADR-SRM-003: PSR — единственный source of truth для очередей

**Дата:** 2026-04-09  
**Решение:** Удалён локальный кэш `QueueRegistry.registered_queues`; broadcast и статистика идут через PSR.  
**Причина:** Устранение тройного хранения ссылок на `Queue`.

## ADR-SRM-004: MemoryAccessStatus enum вместо bool

**Дата:** 2026-04-09  
**Решение:** `validate_memory_access()` и `validate_write_operation()` возвращают `MemoryAccessStatus`.  
**Причина:** Диагностируемая причина отказа вместо голого `bool`.

## ADR-SRM-005: Менеджеры за фасадом (docstring deprecated)

**Дата:** 2026-04-09  
**Решение:** Properties `config_store`, `process_state_registry`, `queue_registry`, `event_manager`, `memory_manager` помечены в docstring как deprecated; без `warnings.warn` до миграции потребителей. Handle API: `srm.for_process(name)`.  
**Причина:** Инкапсуляция фасада; постепенный переход на Handle API.

## ADR-SRM-006: EventManager.wait_for_event — отложенный put-back

**Дата:** 2026-04-09  
**Решение:** Несовпадающие события копятся в списке и возвращаются в очередь в `finally`, цикл использует `queue.Empty`.  
**Причина:** Устранение гонки при немедленном `put` обратно в цикле ожидания.

## ADR-SRM-007: Имя метода `for_process()` вместо `process()`

**Дата:** 2026-04-09  
**Решение:** Единая точка входа Handle API называется `srm.for_process("name")`, а не `srm.process("name")`.  
**Причина:** `BaseManager` (от которого наследуется SRM) хранит `self.process` — ссылку на родительский ProcessModule. Метод `process()` перекрывался бы атрибутом экземпляра и вызывался бы как `None(...)`.  
**Альтернативы:** (1) переименовать BaseManager.process → _host_process (большой diff); (2) process_handle() (длиннее). Выбран прагматичный компромисс — `for_process()` короткий, однозначный, не конфликтует.

## ADR-SRM-008: SharedResourcesManagerConfig — SchemaBase с параметрами модуля

**Дата:** 2026-04-09  
**Решение:** Конфиг расширен с 3 полей (stub) до 8 полей: default_queue_maxsize, event_wait_poll_interval, default_memory_coll, cleanup_stale_shm_on_init, standard_events.  
**Причина:** Конфиг должен реально управлять поведением модуля (паттерн SchemaBase как во всех модулях), а не быть заглушкой.

## ADR-SRM-010: `EventManager` (SRM, cross-proc) vs `event_module.EventBus` (in-proc) — НЕ дубль, только коллизия имён

**Дата:** 2026-07-11
**Статус:** Принято (зеркало основной записи)
**Refs:** `docs/audits/2026-07-10_module-responsibility-duplication-map.md` §1/§4 (N1), decision-log Ф5-добора в `plans/2026-07-06_constructor-master/plan.md` (Q1), `multiprocess_framework/docs/MODULES_RESPONSIBILITY_MAP.md` §2 «Три оси событий», основная запись — [`event_module/DECISIONS.md`](../event_module/DECISIONS.md) EVT-002

**Контекст/Решение:** идентичны EVT-002 (см. полный текст там) — приводится здесь только
затем, чтобы решение находилось локально при чтении DECISIONS.md обоих модулей, а не
только одного. Кратко:

- `EventManager` (`events/core/manager.py:22`) — **межпроцессный** примитив: `emit`
  доставляет и локальным подписчикам, и в роутер (pickle-safe), часть слоя
  «межпроцессные ресурсы» SRM.
- `event_module.EventBus` (`event_bus.py:81`) — **in-process** typed pub/sub, отдельный
  leaf-модуль, другая ось.
- Имена **НЕ переименовываются** (владелец, 2026-07-10, Принцип №1). Вектор на будущее:
  консолидация `EventManager` dual-write в единый транспорт `router.send` по
  [ADR-COMM-001](../../DECISIONS.md#adr-comm-001-routersendmessage--единственный-способ-отправки-каналы-по-kind--канонический-транспорт)
  (план `transport-router-hub`); переименование `EventManager` (если понадобится) —
  только в связке с этой консолидацией, не отдельным рефактором.

**Причина/Альтернативы/Последствия:** см. EVT-002 — не дублируются здесь во избежание
рассинхронизации двух копий текста.

---

## ADR-SRM-009: unregister_process — единая точка снятия процесса

**Дата:** 2026-07-04  
**Решение:** Публичный `SharedResourcesManager.unregister_process(name)` — симметрия к `register_process` (ADR-018): освобождает SHM (`memory_manager.release_process_memory`), удаляет запись PSR (очереди/события/метаданные) и конфиг ConfigStore. Идемпотентен. Контракт `MemoryManager.release_process_memory` СУЖЕН до «только память» — прежний скрытый `psr.unregister_process` внутри него удалён.  
**Причина:** Снятие процесса с PSR выполнялось побочным эффектом освобождения памяти — скрытая связанность: cleanup-фаза hot-swap чистила очереди мёртвого процесса «случайно», через release SHM. При эволюции memory-слоя очереди/события утекали бы в routing_map новых детей (broadcast наполняет никем не читаемые Queue). Потребитель — `PM._cleanup_process_resources` (switch рецепта, rollback).  
**Refs:** plans/2026-07-04_topology-switch-hardening.md (Task 1.4).

---

## ADR-SRM-011: Заголовок слота SHM под пул + seqlock + owner/incarnation (Ф7 G.3)

**Дата:** 2026-07-14
**Статус:** Принято
**Refs:** [plans/2026-07-06_constructor-master/plan.md](../../../plans/2026-07-06_constructor-master/plan.md) (Ф7 G.3), [frame-pool-idea.md](../../../plans/2026-07-06_constructor-master/frame-pool-idea.md), [observability-messaging-vision.md](../../../plans/2026-07-06_constructor-master/observability-messaging-vision.md) §5.3/5.4/5.7, `docs/audits/2026-07-12_recipe-lifecycle-audit.md` (B-6/B-8/B-9)

**Контекст.** Кадровый ring-of-3 писал слоты round-robin **без синхронизации**: reader
копирует буфер (`unpack_images(copy=True)`), writer может перезаписать тот же слот во
время memcpy (numpy отпускает GIL на больших массивах) → **torn frame** (тихая порча
для инспекции; принятый долг до G.3). Репродьюсер `test_seqlock.py`: на кадре 1024×1024×3
воспроизводит ~25% порванных кадров. Плюс имя SHM без owner/incarnation (B-6/B-7): на POSIX
`output_frames_0` двух процессов коллидируют; stale-процесс мог писать в чужой сегмент.

**Решение — ОДИН формат заголовка слота, спроектированный сразу под будущий frame-pool
(G.4), не два.** Перед существующим блоком изображений (`num_images` + per-image) добавлен
фиксированный 8-байтовый SLOT-header (little-endian):

```
offset 0  : generation  uint32  seqlock: нечётное = запись в процессе, чётное = стабильно
offset 4  : state        uint8   0=free 1=writing 2=ready 3=reading (lifecycle пула, G.4)
offset 5  : refcount     uint8   fan-out: сколько читателей держат слот (G.4)
offset 6  : reserved     uint16  выравнивание / будущие флаги (пул/QoS)
offset 8  : num_images   uint32  СУЩЕСТВУЮЩИЙ заголовок блока (сдвинут +8)
offset 12 : per-image (h,w,c uint32 + dtype char) + payload + padding  (как было)
```

`SLOT_HEADER_SIZE = 8`. G.4 (пул/владение) НЕ переопределяет формат — `state`/`refcount`
уже здесь. Контракт совместим с семантикой iceoryx2 loan/publish (frame-pool-idea): free →
loan(writing) → publish(ready) → read(reading, refcount) → release(free).

**Seqlock-протокол (только когда формат seqlock-слота включён):**
- writer (`pack_images`, seqlock=True): `generation += 1` (нечётное) ДО записи payload,
  `generation += 1` (чётное) ПОСЛЕ; `state` = writing→ready.
- reader (`unpack_images`, verify_seqlock=True): читает `g1`; если нечётное — запись идёт
  → `None` (drop). Копирует payload. Читает `g2`; если `g1 != g2` — writer перезаписал под
  читателем → `None` (drop). Иначе кадр валиден. **Порванный кадр не возвращается
  никогда** — гонка превращается в честный drop + счётчик, не в тихую порчу.

**Флаг формата — на слот, стамповка при создании (консистентность size↔write↔read).**
`MemoryManager(seqlock_frames=...)` (ctor > env `FW_SHM_SEQLOCK` > конфиг > **False**).
При `create_memory_dict` флаг слота пишется в `pd.custom["memory_seqlock"][name]` (PSR,
pickle-safe — виден consumer-процессам после `reinitialize_handles`) и в `_MemoryMeta.seqlock`
(standalone). `write_images`/`read_images`/`calculate_buffer_size` читают флаг слота — layout
самосогласован. Дефолт **False = байт-в-байт прежний 4-байтовый заголовок**; откат = флаг off.
Cross-process сырой fallback (`FrameShmMiddleware._read_shm_from_actual_name`) узнаёт формат из
поля `shm_seqlock` в IPC-сообщении (Dict at Boundary — флаг едет с координатами).

**Owner/incarnation в имени SHM (B-6/B-7), флаг `FW_SHM_OWNER_INCARNATION` (дефолт False).**
При включении имя = `{slot}__{owner}__{pid}__{inc}_{idx}` (свежая инкарнация на КАЖДОЕ
создание, не только на hot-swap-retry). Два живых источника с одним slot-именем в разных
процессах больше не коллидируют (owner+pid+inc уникальны); stale-процесс не переиспользует
чужое имя после switch (HP-5: in-flight сообщение со старым именем читает пусто/своё, не
чужой кадр). Consumer читает ФАКТИЧЕСКИЕ имена (PSR memory_names / shm_actual_name) — суффикс
прозрачен, как и раньше.

**Startup-cleanup осиротевших РАНТАЙМ-слотов (§5.4), флаг `FW_SHM_PREFIX_CLEANUP` (дефолт False).**
`cleanup_known_shm_at_startup` чистил только имена из конфиг-`memory`; живой `output_frames`
выделяется ЛЕНИВО (нет в конфиге) → после `kill -9` осиротевшие сегменты висят (POSIX
`/dev/shm`). Добавлен prefix-scan: по базовым префиксам кадровых слотов (owner-имена +
`output_frames`) на Linux сканируется `/dev/shm`, на Windows — best-effort open+close
(ОС сама освобождает mapping при гибели последнего handle → на Windows осиротевших почти нет).

**Альтернативы (отвергнуты).**
- *Отдельный seqlock-заголовок vs. поля пула отдельным форматом* — отвергнут: G.4 переписал бы
  формат второй раз («одним вскрытием» — один формат сразу под пул).
- *Мьютекс/atomics на слот* — отвергнут: seqlock без блокировок дешевле на hot-path (writer
  никогда не ждёт reader — живую камеру тормозить нельзя), под GIL инкремент generation
  практически атомарен; для будущего true-lock-free refcount поле зарезервировано.
- *Всегда-on формат seqlock* — отвергнут: правило фазы (feature-flag, дефолт = старое; откат
  = флаг off, «бит-в-бит прежнее»).

**Последствия.** Torn-frame исключён по построению при seqlock-on (репродьюсер: 25% → 0).
Формат готов к пулу G.4 без переделки. Три ортогональных флага (seqlock / owner-incarnation /
prefix-cleanup) — независимый откат каждого. Per-frame путь без Pydantic (голый struct на
memoryview). Дефолты OFF — в прод включаются на G.7 (flip флага + soak).
