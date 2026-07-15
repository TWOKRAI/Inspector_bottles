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
При включении имя = `{slot}_{owner}_{pid}_{inc}_{idx}` (одинарные `_` — `_unique_base_name`
в `memory/platform/shm.py`; `owner` опционален, при отсутствии просто пропускается в
join'е). PID — на ВСЕХ платформах (не только Windows, H2): на POSIX процессный счётчик
инкарнаций сбрасывается в каждом интерпретаторе заново, без pid два процесса дали бы
одно и то же имя. Свежая инкарнация на КАЖДОЕ создание, не только на hot-swap-retry.
Два живых источника с одним slot-именем в разных процессах больше не коллидируют
(owner+pid+inc уникальны); stale-процесс не переиспользует чужое имя после switch (HP-5:
in-flight сообщение со старым именем читает пусто/своё, не чужой кадр). Consumer читает
ФАКТИЧЕСКИЕ имена (PSR memory_names / shm_actual_name) — суффикс прозрачен, как и раньше.

**macOS: лимит длины имени (H3).** `PSHMNAMLEN ≈ 31` — полное имя `{slot}_{owner}_{pid}_{inc}`
(без `_{idx}`) детерминированно схлопывается в `{slot[:10]}_{blake2s8}` (`_bounded_name`),
если превышает `_MAX_BASE_NAME_LEN = 26` (запас под `_{idx}` до coll=64). Хеш от ПОЛНОГО
имени сохраняет уникальность, укороченный префикс — для читаемости в логах/отладке.

**Startup-cleanup осиротевших РАНТАЙМ-слотов (§5.4), флаг `FW_SHM_PREFIX_CLEANUP` (дефолт False).**
`cleanup_known_shm_at_startup` чистил только имена из конфиг-`memory`; живой `output_frames`
выделяется ЛЕНИВО (нет в конфиге) → после `kill -9` осиротевшие сегменты висят (POSIX
`/dev/shm`). Добавлен prefix-scan: по базовым префиксам кадровых слотов (config-регионы,
извлечённые `extract_memory_region_names` — M8a, + безусловно `output_frames`) на Linux
сканируется `/dev/shm`, на Windows — best-effort open+close (ОС сама освобождает mapping
при гибели последнего handle → на Windows осиротевших почти нет). На macOS enumeration
недоступен вообще (POSIX shm там не файлы `/dev/shm`) — no-op, чистит сама ОС (M8b).
⚠️ Расширение списка префиксов config-регионами (M8a) пропорционально расширяет
multi-backend-риск, задокументированный в `cleanup_orphaned_by_prefix` (допущение «ОДИН
активный backend»): стартующий backend может снести живые сегменты соседа не только по
`output_frames`, но и по любому совпадающему config-имени — потому флаг дефолтно off.

**Схлопывание legacy/seqlock layout'ов — после G.7.** Пока ДВА параллельных формата слота
(`seqlock=False` — 4-байтовый заголовок, `seqlock=True` — 8-байтовый SLOT-header) сосуществуют
за флагом (откат = флаг off). Убрать ветвление и оставить один формат — только после G.7
(флаг включён в проде + soak-период показал отсутствие регрессий); раньше — преждевременно,
путь отката должен оставаться дешёвым.

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

## ADR-SRM-012: QoS-профили класса груза — единый источник политики переполнения (Ф7 G.4.a)

**Дата:** 2026-07-14
**Статус:** Принято
**Refs:** [plans/2026-07-06_constructor-master/plan.md](../../../plans/2026-07-06_constructor-master/plan.md) (Ф7 G.4), [g4-execution-plan.md](../../../plans/2026-07-06_constructor-master/g4-execution-plan.md) §3

**Контекст.** Политика переполнения гнёзд доставки была раздублирована в ТРЁХ местах разной
формы: (1) наблюдаемость — `BoundedChannel` (drop_oldest/drop_newest + `dropped`); (2) очереди
— `QueueRegistry.remove_old_if_full` хардкод `queue_type == "system"` (never-drop) vs else
(тихое drop_oldest БЕЗ счётчика); (3) кадровые кольца SHM — round-robin без политики. Data-дроп
из очереди был **тихим** (комментарий «Полная QoS-модель — Ф7 G.4»), нарушая правило Ф3.3
«терять можно, молчать — нельзя».

**Решение.** `shared_resources_module/qos.py` — `QoSProfile{reliability, history_depth,
drop_policy, deadline_ms}` (frozen dataclass, чистые данные) + реестр `QOS_PROFILES`, ключи
которого СОВПАДАЮТ с kind (`resolve_channel_kind`) и `queue_type`. Инвариант профиля: `reliable
⟺ never-drop`. Единый вердикт `qos_for(kind).never_drop` для всех трёх поверхностей вместо
трёх хардкодов. Профили-дефолты: system/command=reliable/never; data=best_effort/drop_oldest/
depth 4/33мс; state=drop_oldest/depth 1 (coalesce); observability/log=drop_oldest/depth 1024.

Проводка G.4.a (за флагом `FW_QOS_PROFILES`, дефолт off = бит-в-бит): `remove_old_if_full`
берёт вердикт never-drop из профиля вместо хардкода (для system/data идентично → флип
безопасен); **новый всегда-on счётчик `data_evicted`** (+ throttled WARNING) делает data-дроп
ВИДИМЫМ; surface в `RouterManager.get_stats` → heartbeat → `state.shm.queue_data_evicted`
(тот же путь, что SHM-счётчики G.3). Структура профиля совместима с DDS/iceoryx2 QoS
(reliability/history/deadline) — миграция транспорта = замена бэкенда под тем же контрактом.

**Альтернативы (отвергнуты).** *Оставить 3 хардкода* — дрейф политик, тихий data-дроп.
*Профиль в router/channel_routing* — новое ребро импорта в `shared_resources` (очередь — там);
qos.py в shared_resources, router дотянется по существующему ребру. *Всегда-on проводка без
флага* — правило фазы (feature-flag, откат = флаг off); счётчик `data_evicted` — телеметрия,
поведение drop не меняет, потому всегда-on (образец G.3-счётчиков).

**Последствия.** Один источник правды QoS под 3 поверхности; data-дроп виден в state (вкладка
Pipeline); задел под G.4.b (глубина кольца = `history_depth`) и G.5. Дефолт OFF — flip на G.7.

**Нота о конкурентности счётчиков (ревью 2026-07-14).** `data_evicted`/`system_evict_blocked` —
plain-int `+= 1` без lock (по образцу G.6 `frame_boundary_crossings`). В отличие от per-camera
`FrameShmMiddleware`, `QueueRegistry` — ОДИН инстанс на процесс, `send_to_queue`→`remove_old_if_full`
может зваться из нескольких воркер-тредов → под GIL инкремент почти-атомарен, но при плотном fan-in
возможен редкий недосчёт. Это **advisory-телеметрия** (сигнал «теряем/блокируем», не точный учёт для
логики) — недосчёт приемлем; вводить lock на hot-path send ради точности счётчика — нет (правило фазы
«без локов на горячем пути»). Точный per-drop учёт не требуется ни одним потребителем.

## ADR-SRM-013: Владение слотом за фасадом `FramePool` + снос мёртвого `index_usage` (Ф7 G.H)

**Дата:** 2026-07-14
**Статус:** Принято
**Refs:** [plans/2026-07-06_constructor-master/plan.md](../../../plans/2026-07-06_constructor-master/plan.md) (Ф7 G.H), [h-memory-consolidation-plan.md](../../../plans/2026-07-06_constructor-master/h-memory-consolidation-plan.md), ADR-SRM-011 (заголовок слота), ADR-SRM-012 (QoS)

**Контекст.** G.5.d/e построили loan-протокол владения слотом (free-list + refcount +
released-множества + reclaim) прямо в транспортном `router_module/FrameShmMiddleware` — ~200
строк семантики владения ПАМЯТЬЮ вне модуля памяти. Директива владельца (2026-07-14): память —
ОДИН модуль с фасадом/интерфейсом/взаимозаменяемостью (в пределе — подмена на Rust/iceoryx2), без
костылей. Вдобавок в `MemoryManager` жил **мёртвый первый учёт занятости**: `index_usage`
(`memory_index_usage` в PSR + `_MemoryMeta.index_usage`) писался только в `0`, «used=1» никто не
ставил → `find_free_index` всегда возвращал слот 0. G.5 построил ВТОРОЙ (настоящий) учёт рядом с
недоделанным первым.

**Решение.** (1) **Фасад `memory.pool.FramePool`** (Protocol) + реализация `LoanLedger` в
`shared_resources_module/memory/pool/`: `acquire`/`commit(idx,n)`/`release(tickets)`/
`reclaim(reader)`/`reset`/`snapshot_stats` — сигнатуры 1:1 с прежней логикой middleware и с
контрактом iceoryx2/DDS `loan/publish/release`. `gen_reader` (чтение поколения своего слота под
seqlock) **инжектируется** в реализацию → пул SHM-агностичен. Транспорт держит пул через DI и
делегирует; счётчики `frame_loan_exhausted`/`slots_released`/`slots_reclaimed` стали read-only
property транспорта, читающими `pool.snapshot_stats()` (единственный источник). (2) **Снос мёртвого
`index_usage`/`find_free_index`** во всех локусах: `_MemoryMeta`, `create_memory_dict`,
`get_memory_data` (ключ `index_usage` убран из возврата), `release_memory` (осталась только
очистка слота), `close_memory` (ключ), PSR-бандл (`process_registry` producer +
`bundle_builder` child-reconstruct), `MemoryHandle.find_free_index`. Реальный free-list с
владением по цепочке — теперь только у пула (owner-side).

**Модель конкурентности.** refcount мутирует ТОЛЬКО процесс-владелец (кросс-процессного atomic RMW
в CPython нет — отклонение В2 mp.Lock, g5-план §8). Безопасность от torn даёт seqlock (ADR-SRM-011)
+ post-use re-check (В1), НЕ этот учёт: любая ошибка учёта безопасна (преждевременное освобождение →
writer перезапишет → generation drift → drop, не порча).

**Альтернативы (отвергнуты).** *Оставить владение в middleware* — размазанность памяти по 2 модулям,
дорогая замена транспорта. *`index_usage` как backing пула* — пул owner-process-local (не в PSR),
а `index_usage` был per-PSR-массив; смешивать per-process и per-PSR учёт — костыль; снос чище.
*ABC вместо Protocol* — Protocol (runtime_checkable) даёт взаимозаменяемость без наследования
(критерий подмены на Rust-реализацию под тем же контрактом).

**Последствия.** Транспорт → чистый адаптер (Этап 2 добьёт reader-side handle-кэш за фасад
`FrameReader`). Замена на Rust/iceoryx2 (Этап 3, триггер TECH_STACK §7) = новая реализация под тем
же Protocol, middleware/executor не трогаются. Всё за `FW_SHM_LOAN_PROTOCOL` (дефолт off = слепой
round-robin, бит-в-бит); пул создаётся только под флагом. PSR-бандл стал легче на один мёртвый массив.

**Донастройка (H-ревью фазы G, 2026-07-14).** Ревью выявило: модель single-writer была *заявлена*,
но не *закреплена* кодом, а «DI» был self-construction в транспорте. Исправлено «как полагается»:

- **Single-writer enforced (lock-free).** `LoanLedger.acquire` связывает поток-писатель на первом
  вызове и бросает `RuntimeError` на втором ином потоке (write-write в один слот, который seqlock НЕ
  ловит, → громкий отказ, а не тихая порча). Топология source+processing в одном процессе кодом не
  используется (29 рецептов), но теперь и не допускается молча.
- **State-машина слота.** `acquire` РЕЗЕРВИРУЕТ слот (WRITING), `commit` публикует (READY), новый
  `abort` возвращает loan без publish (WRITING→FREE; неудачная запись иначе утекла бы). release/reclaim
  (поток message_processor) трогают только READY → с WRITING-слотом писателя не пересекаются ПО
  ПОСТРОЕНИЮ, без lock (iceoryx2 loan/publish/abort).
- **Настоящий DI.** `FrameShmMiddleware.__init__` принимает `pool=`/`reader=` (инжект выигрывает,
  None → дефолт-фабрика) → подмена реализации (Rust/iceoryx2) действительно не трогает транспорт.
- **reader-side:** `ShmFrameReader.read_frame` читает буфер под тем же lock, что close (гонка
  close↔read закрыта и для read, не только re-check); ошибки close() считаются (`close_errors`), не
  глотаются молча. Reader получил изолированный contract-тест (симметрия с `FramePool`).

**Амендмент (2026-07-15, финальное Fable-ревью фазы G): смена писателя.** Guard «первый acquire
связывает поток навсегда» конфликтовал с G.8 (drain→detach→stop воркера, затем create нового:
middleware и пул переживают воркера — новый поток-писатель получал бы `RuntimeError` на первом
кадре). Семантика уточнена до **«один писатель В КАЖДЫЙ МОМЕНТ»**: при несовпадении ident
проверяется живость связанного потока (скан `threading.enumerate` — только на холодном пути
смены); мёртв → перепривязка, жив → прежний громкий `RuntimeError`. Инвариант памяти не ослаблен —
запрещены только ОДНОВРЕМЕННЫЕ писатели (их seqlock не ловит); последовательная передача роли
безопасна (drain гарантирует завершение кадра до detach).
