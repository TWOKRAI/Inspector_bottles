# Ф7 G.4 — план исполнения (QoS-профили + пулы/кольца per-camera)

> Создан 2026-07-14 на старте G.4 (после закрытия G.3, merge b54b4689). Статусы — ТОЛЬКО
> в [plan.md](plan.md); этот файл — декомпозиция под-шагов, дизайн-развилка и брифы.
> Исполнитель: Opus 4.8 (главный чат), ветка `feat/constructor-f7` (сброшена на main 7568b48a),
> sentrux-baseline G.4: quality 7093 (session_start 2026-07-14).
> Вход: [plan.md](plan.md) §Ф7 строка G.4, [frame-pool-idea.md](frame-pool-idea.md),
> [observability-messaging-vision.md](observability-messaging-vision.md) §5.7,
> [f7-execution-plan.md](f7-execution-plan.md) §G.4, аудит B-7/B-8/B-9.

## 0. Что уже готово (фундамент G.3, не переделывать)

- **SLOT-header под пул** (`shared_resources_module/memory/format/buffer.py`): 8 байт —
  `generation`(u32) + `state`(u8: free/writing/ready/reading) + `refcount`(u8, резерв) +
  reserved(u16). Один формат за флагом `FW_SHM_SEQLOCK`. `write_slot_state`/`read_slot_state`/
  `read_refcount`/`write_refcount` — примитивы уже есть.
- **seqlock**: гонка reader↔writer → `None` (drop), не torn. torn 24.8%→0. Корректность
  кадра — ПО ПОСТРОЕНИЮ.
- **owner+incarnation в имени SHM** (`FW_SHM_OWNER_INCARNATION`): stale-процесс не пишет в
  чужой сегмент; мультикамера без коллизий имён (B-6/B-7 первая половина).
- **кэш SHM-handles читателя** (`FW_SHM_HANDLE_CACHE`, связан с incarnation): open/mmap/close
  на кадр снят.
- **громкие счётчики** (G.3(d)): `frame_pickle_fallbacks`/`frame_torn_reads` в middleware →
  `RouterManager.get_stats` → heartbeat → `state.shm.*`.
- **kind-таксономия каналов** (G.2, `resolve_channel_kind`: state.*→state, command→system,
  data→data): kind-каналы `{process}_{kind}` за флагом `use_kind_channels`. **QoS-профили
  G.4 вешаются НА эту таксономию** (профиль per kind).
- **образец drop-политики**: `channel_routing_module/observability/bounded_channel.py`
  (`drop_oldest`/`drop_newest` + монотонный `dropped` + `written`). Зрелая референс-модель
  «терять можно, молчать нельзя».

## 1. КЛЮЧЕВАЯ РАЗВИЛКА СКОУПА (решение владельца до кода — §5)

**Инженерный факт, определяющий объём G.4:**

Сегодня путь кадра — **copy-out**: consumer читает слот и `.copy()`-ит кадр (`copy=True`),
слот освобождается СРАЗУ после чтения. Ring-of-3 «работает», потому что к моменту, когда
writer доходит до слота повторно (через `coll` кадров), reader давно скопировал. Зачем это
важно для G.4:

1. **Настоящее «владение слотом до release последним читателем» становится НАГРУЖЕННЫМ только
   с G.5** (`restore_frame(copy=False)` — zero-copy, reader держит view в слот → слот НЕЛЬЗЯ
   перезаписать, пока reader не отпустил). До G.5 release происходит неявно сразу после копии.
2. **В CPython нет кросс-процессного atomic RMW** на байте SHM-header (`buf` — обычный
   memoryview). Fan-out `refcount(u8)++/--` из нескольких процессов безопасно требует ЛИБО
   per-region `multiprocessing.Lock` (захват лока на КАЖДЫЙ кадр КАЖДОГО читателя — хоп на
   hot-path), ЛИБО owner-mediated release (IPC-сообщение на кадр на читателя — убивает смысл
   zero-copy). **Глубокое кольцо + seqlock + state-байт даёт ТУ ЖЕ безопасность** (reader,
   не успевший до перезаписи → seqlock drop + громкий счётчик) БЕЗ всякого atomic.

Отсюда два когерентных скоупа G.4 — см. §5 (вопрос владельцу). Общая часть (под-шаги
G.4.a/b/d) одинакова в обоих; различие — только в G.4.c/e (протокол владения).

## 2. Декомпозиция под-шагов (feature-flag на каждый, коммит на шаг)

| Шаг | Суть | Флаг | Риск | Общий для A/B? |
|---|---|---|---|---|
| **G.4.a** | **QoS-профили kind** `QoSProfile{reliability, history_depth, drop_policy, deadline_ms}` per kind (system=reliable/never-drop, data=keep_last+drop_oldest+счётчик); унификация 3 политик переполнения на один профиль + один паттерн drop→state | `FW_QOS_PROFILES` | низкий (контракт+плумбинг) | ✅ да |
| **G.4.b** | **Боевые per-camera кольца**: глубина кольца настраивается per-camera (buffer_slots рецепта/wire, дефолт = `history_depth` профиля data), раньше жёстко 3 и buffer_slots игнорировался (B-8). Изоляция per-camera (свой owner = своё кольцо, общего слота нет). **Дроп на wrap под copy-out**: гонка reader↔writer ловится seqlock → `frame_torn_reads` (G.3); глубже кольцо → реже. Occupancy-детект «перезапись НЕпрочитанного слота» (громкий drop-на-источнике) требует владения → **G.5**, здесь НЕТ | `FW_QOS_PROFILES` (единый гейт G.4; `FW_FRAME_RING_DEPTH` из наброска — НЕ вводили) | средний | ✅ да |
| **G.4.d** | **B-7 остаток**: refresh SHM-handles получателя на switch — реализовано как ЧИСТАЯ замена wire на re-issue (`_teardown_wire_middleware` снимает старый middleware с router'а ДО нового; раньше молча перезаписывал → утечка + стейл-кэш). Дренаж стейл-тикетов = точечный read-time drop по incarnation (G.3), кросс-процессный дренаж живой очереди ОТВЕРГНУТ (роняет валидные кадры, костыль). Тесты switch×кадры (B-7/B-9) | (без нового флага — чистка lifecycle, корректность на incarnation G.3) | средний (lifecycle switch) | ✅ да |
| **G.4.c/e** | **Протокол владения** (free-list + release-by-last-reader + fan-out refcount + reclaim-on-death + kill-9 fault-injection) — **ТОЛЬКО в скоупе B** (см. §5). В скоупе A — задокументирован, переносится в G.5 (где zero-copy делает его нагруженным и тестируемым) | — | **высокий** (главный риск фазы) | ❌ только B |

Порядок: G.4.a → G.4.b → G.4.d → (G.4.c/e если скоуп B). После каждого — прицельный pytest
+ полный `run_framework_tests.py`; BackendHarness-smoke при рантайм-эффекте; коммит.

## 3. Унификация 3 политик переполнения (G.4.a, детализация)

| # | Поверхность | Сейчас | После G.4.a |
|---|---|---|---|
| 1 | Наблюдаемость | `BoundedChannel` drop_oldest/drop_newest + `dropped` (зрелая) | остаётся эталоном; QoS-профиль kind=observability/data ссылается на неё |
| 2 | Кадры (data-plane) | `FrameShmMiddleware`: seqlock-drop + `frame_torn_reads`; ring round-robin слепой | QoS data-профиль: keep_last=depth + drop_oldest + громкий счётчик (G.4.b даёт occupancy) |
| 3 | Очереди system/data (`queues/core/manager.py`, mp.Queue) | политика переполнения не единообразна | QoS system-профиль: reliable/never-drop (backpressure/явная ошибка, НЕ тихий drop — поглощает 3.3); data-профиль: drop_oldest+счётчик |

Инвариант (сквозное правило Ф7 п.2): **system никогда не дропается молча**; data/наблюдаемость
— drop_oldest + счётчик потерь → heartbeat → state (по health-схеме 2.1) → вкладка Pipeline.

## 4. Брифы под-шагов (детализируются перед исполнением каждого)

- **G.4.a** — где живёт kind-таксономия: `router_module/routing` (`resolve_channel_kind`,
  `channel_name`), профиль вешать per kind; проводка в send-путь (`_resolve_channels`/
  `_select_queue_type`) и в queue-manager под `FW_QOS_PROFILES`; счётчики drop → get_stats →
  heartbeat (образец G.3(d)). НЕ трогать корректность seqlock.
- **G.4.b** — middleware `_write_frame_into_slot` + `MemoryManager.write_images`/`index_usage`;
  occupancy через `state`-байт header (writer FREE→WRITING→READY; на wrap READY-непрочитанный →
  drop-oldest++); глубина из конфига/рецепта per-camera; keying по owner (процесс-источник) +
  stream-id. Прод-значения глубины хотя бы в одном тесте.
- **G.4.d** — switch/replace_blueprint: `process_manager_module/process/process_manager_process.py`
  + `topology/blueprint.py`; дренаж очередей получателей (найти сайт приёма data —
  `process_module/generic/data_receiver.py`); refresh handles protected (`release_process_memory`/
  handle-кэш). Тест switch×in-flight кадр (B-9 репродьюсер уже есть в G.3 — переиспользовать).
- **G.4.c/e** (скоуп B) — free-list в `MemoryManager` (owner-side); release последним читателем;
  fan-out refcount через per-region `multiprocessing.Lock` (единственный корректный примитив в
  CPython); reclaim по incarnation/супервизору; fault-injection kill-9 читателя. **Главный риск —
  Opus, отдельный тщательный заход, fault-injection обязателен.**

## 5. Развилка §1 — РЕШЕНО владельцем 2026-07-14: **Вариант A**

> **Решение (2026-07-14, простым языком): «механику владения подносом — вместе с G.5».**
> G.4 = a+b+d (QoS-профили + боевые per-camera кольца с громким drop + switch-drain).
> Настоящий протокол владения (free-list + release последним читателем + fan-out refcount +
> reclaim-on-death + kill-9 fault-injection) **переносится в G.5**, где zero-copy делает его
> нагруженным и осмысленно тестируемым (есть держатель слота, которого можно убить), и примитив
> выбирается с реальным потребителем. Ничего не выбрасывается: header G.3 уже несёт state/refcount.
> plan.md G.4 acceptance «слот не переиспользуется до release / kill-9 reclaim» → цель G.5.

**Сколько протокола владения слотами приземляется в G.4, если читатели ещё copy-out до G.5?**

- **A (рекомендация) — «Фундамент сейчас, владение с G.5».** G.4 = a+b+d: QoS-профили +
  боевые per-camera кольца с ГРОМКИМ drop + switch-drain. Настоящий loan/release/refcount +
  reclaim-on-death → **G.5**, где zero-copy делает их нагруженными и осмысленно тестируемыми
  (есть реальный держатель слота, которого можно убить), и примитив выбирается с реальным
  потребителем в руках. Строго меньше слоёв/риска при той же итоговой функциональности; ничего
  не выбрасывается (header уже несёт state/refcount). Матчит product>engine / fewer layers /
  fix-forward / «не переделывать по многу раз».
- **B — «Полный frame-pool сейчас» (буквальный acceptance plan.md G.4).** a+b+d + протокол
  владения (free-list + release + fan-out refcount через per-region Lock + reclaim-on-death +
  kill-9 fault-injection) СЕЙЧАС, хотя потребитель zero-copy (G.5) ещё не существует → протокол
  крутится вхолостую, добавляет лок на hot-path, а reclaim-тест слаб без держателя слота.
  Плюс: граница G.4/G.5 как в плане; протокол доказан до касания copy-elision.

Оценка «до/после» и обновление plan.md G.4 acceptance — по решению владельца.

## 6. Ревью G.4 (3 Sonnet-финдера, 2026-07-14) + фиксы

Углы: (1) корректность+откат+конкурентность, (2) честность тестов+acceptance, (3) cross-file+hot-path+доки.
Подтверждено чистым: откат бит-в-бит remove_old_if_full при флаге off; wire-replace teardown-до-create
корректен и идемпотентен; НЕТ протокола владения (Вариант A соблюдён); нет циклов импорта (sentrux 9/9);
qos_for не на per-frame пути; switch-тест faithful (mutation-проба: падает без owner+incarnation).

Находки и фиксы (все закрыты до merge):

| # | Sev | Находка | Фикс |
|---|---|---|---|
| 1 | HIGH | `buffer_slots` дефолтит в 4 в `_cmd_wire_setup`/`_reissue` ещё до Ф7 → честить его безусловно = глубина 3→4 на merge (не откат бит-в-бит) | config-глубину (wire/generic) гейтим за `FW_QOS_PROFILES`; off → None → 3. +2 теста |
| 2 | HIGH | Доки (qos.py/g4-plan/plan) заявляли «громкий счётчик drop-oldest на wrap кольца», которого в Варианте A НЕТ (occupancy → G.5) | честные доки: wrap-гонка → seqlock `frame_torn_reads` (G.3); occupancy-drop → G.5 |
| 3 | MED | `queue_system_evict_blocked` в router.get_stats, но heartbeat не публиковал (асимметрия с data_evicted) | добавлен в `_publish_router_shm_stats_to_tree` + тест |
| 4 | MED | plan «system никогда не дропается» опускает «молча» (полная system-очередь роняет через Full, но ГРОМКО) | wording plan.md → «не дропается **молча**» |
| 5 | LOW | data_evicted/system_evict_blocked plain-int из потенциально нескольких воркер-тредов (QueueRegistry — один инстанс) — возможен недосчёт advisory-телеметрии | нота в ADR-SRM-012 |
| 6 | LOW | plan §2 флаг `FW_FRAME_RING_DEPTH`; реально единый `FW_QOS_PROFILES` · deconfigure-лог потерял role · тесты 2 камеры не 3 · стейл-коммент «владение G.4» | §2 обновлён; изоляция 2-камер достаточна (N независимых по построению); коммент buffer.py → G.5 |

## 7. Финальный вердикт Fable (2026-07-14, фокус владельца: универсальность конструктора)

**APPROVE-WITH-NITS** — merge `feat/constructor-f7` → main одобрен. Ключевое: **100% diff в движке**
(ноль строк в `multiprocess_prototype/`/`Services/`/`Plugins/`) — буквальное framework-first.
Что стало универсальнее: (1) `QoSProfile` — переиспользуемый примитив конструктора (frozen, без
зависимостей, инвариант reliable⟺never, контракт-тест), любое приложение опирается; (2) словарь
kind==queue_type — универсальные классы груза, не Inspector-специфика; (3) DDS/iceoryx2-совместимый
контракт = задел под смену транспорта; (4) минус 2 хардкода переполнения без нового слоя (fewer-layers
по существу); (5) per-source кольца (keying по owner — любой источник, N изолированных); (6) чистый
wire-replace = живучесть ЛЮБОГО switch топологии; (7) видимость потерь штатным heartbeat-путём даром
для любого приложения; (8) Вариант A = «не строить слой без нагруженного потребителя».

**Ниты (не блокеры → G.5/G.7 бэклог):** (1) BoundedChannel задокументирован, но не подключён к профилю
(«3 поверхности» = 2 wired + 1 documented — дожать при G.7); (2) нет extension-point прикладных kind в
`QOS_PROFILES` (register_profile — ступень универсальности, вход H.3/G.5); (3) два имени ручки
`buffer_slots`/`frame_ring_depth` — унифицировать в схеме рецепта; (4) `queue_*`-счётчики под именем
`state.shm.*` (путь универсален, имя не идеально); (5) `deadline_ms` инертен (контракт без реализации —
пересмотреть при потребителе). **Чек-лист G.7-флипа:** soak со сдвигом глубины wire-колец 3→4
(следствие pre-Ф7 дефолта `buffer_slots=4`) — главный поведенческий сдвиг при флипе.
