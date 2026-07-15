# Ф7 G.5 — план исполнения (снятие двойной конверсии + zero-copy чтение + протокол владения)

> Создан 2026-07-14 на старте G.5 (после закрытия G.4, merge e6b1bcca). Статусы — ТОЛЬКО
> в [plan.md](plan.md); этот файл — декомпозиция под-шагов, дизайн-развилка и брифы.
> Исполнитель: рекомендация — **Opus 4.8, один заход** (обоснование в §5), ветка
> `feat/constructor-f7` (сбросить на актуальный main, сверить SHA базы — грабли
> worktree-stale-base), isolation: worktree. Sentrux-baseline G.5 — снять `session_start`
> при старте кода.
> Вход: [plan.md](plan.md) §Ф7 строка G.5 (**устарела** — см. §7), перенос из G.4 Вариант A
> ([g4-execution-plan.md](g4-execution-plan.md) §5), [frame-pool-idea.md](frame-pool-idea.md),
> [f7-execution-plan.md](f7-execution-plan.md) §G.5 + §2, baseline.md (tier синтетика).

## 0. Что уже готово (фундамент G.3/G.4, не переделывать)

- **SLOT-header под пул** (`shared_resources_module/memory/format/buffer.py`): 8 байт —
  `generation`(u32, seqlock) + `state`(u8: free/writing/ready/reading) + `refcount`(u8,
  резерв) + reserved(u16). Примитивы `read_generation`/`read_slot_state`/`write_slot_state`/
  `read_refcount`/`write_refcount` есть. Один формат — G.5 его НЕ меняет, только нагружает.
- **seqlock (G.3b)**: reader сверяет generation до/после копии → torn/in-progress = `None`
  (drop + счётчик `frame_torn_reads`/`_stats["torn"]`). Инвариант single-writer-per-slot
  задокументирован в `pack_images` (M4). Корректность кадра — ПО ПОСТРОЕНИЮ.
- **owner+incarnation + кэш SHM-handles читателя** (`FW_SHM_OWNER_INCARNATION` +
  `FW_SHM_HANDLE_CACHE`, жёсткая связка H4): open/mmap/close на кадр снят; stale-процесс
  не пишет в чужой сегмент. **Критично для G.5: кэш handles — обязательное условие
  zero-copy** (см. §1, инженерный факт 3).
- **QoS-профили + per-camera кольца (G.4.a/b, `FW_QOS_PROFILES`)**: `qos_for("data")` →
  `history_depth=4`; глубина кольца per-camera из рецепта/wire (`buffer_slots`) > профиля >
  3. N owner = N изолированных колец. **Ручка глубины для Варианта 1 §3 уже существует.**
- **чистый wire-replace (G.4.d)**: `_teardown_wire_middleware` — switch не оставляет
  стейл-middleware/кэша; стейл-тикеты дропаются read-time по incarnation.
- **громкие счётчики (G.3d, образец)**: plain int в middleware → `RouterManager.get_stats`
  → heartbeat → `state.shm.*` → вкладка Pipeline. Все новые метрики G.5 — этим же путём.
- **паритет доставки (G.2)**: характеризационные тесты на дефолте — гейт «флаг off =
  бит-в-бит» для каждого под-шага G.5.

## 1. СКОУП: две связанные части + инженерные факты

**G.5 = (a) снятие двойной конверсии + zero-copy чтение** (исходный скоуп строки G.5) **+
(b) протокол ВЛАДЕНИЯ слотами** (перенесён из G.4 решением владельца 2026-07-14, Вариант A —
«главный риск фазы»: free-list + release последним читателем + fan-out refcount +
reclaim-on-death + kill-9 fault-injection).

**Почему это ОДНА задача, а не две** (обоснование переноса, зафиксировано в g4-plan §1/§5):
сегодня путь кадра — **copy-out**: reader копирует кадр из слота (`copy=True`,
`_read_one_frame` в buffer.py:437 копирует безусловно) и слот свободен сразу после копии —
владение ненагружено, release неявный. **Zero-copy чтение (a) создаёт первого реального
держателя слота**: reader держит numpy-view прямо в SHM → слот нельзя переиспользовать,
пока view жив → протокол владения (b) впервые получает нагруженного потребителя, которого
можно убить kill-9 и честно протестировать reclaim. G.5 — единственное место, где владение
осмысленно; строить его раньше значило бы слой без потребителя (анти-принцип фазы).

**Инженерные факты, определяющие развилку §3 (из кода, не предположение):**

1. **Двойная конверсия на КАЖДЫЙ кадр**: `router_manager.receive()` собирает
   `Message.from_dict(processed)` (router_manager.py:779/:786; `Message(SchemaBase)` —
   Pydantic) → `DataReceiver.run_loop` тут же разбирает обратно `msg.to_dict()`
   (data_receiver.py:164-165). Путь: data_receiver.py:150 → `process.receive_message` →
   `ProcessCommunication.receive` (process_communication.py:175) → `router.receive(...)` с
   дефолтом `return_messages=True`. Параметр в цепочке НЕ пробрасывается — его надо провести.
   Отдельный сайт `AsyncReceiver._worker` (`_receiver.py:136`) хардкодит
   `return_messages=True` — это listener-поток колбэков (system-plane), data-plane идёт
   sync-поллом DataReceiver; listener НЕ трогать без аудита колбэков.
2. **В CPython НЕТ кросс-процессного atomic RMW** на байте SHM-header (`shm.buf` — обычный
   memoryview). Fan-out `refcount++/--` из нескольких процессов небезопасен без внешнего
   примитива. Отсюда развилка §3.
3. **Zero-copy требует живого handle**: путь без кэша (`_read_shm_from_actual_name`,
   frame_shm_middleware.py:295-299) закрывает SharedMemory в `finally` сразу после чтения —
   с `copy=False` это use-after-close (BufferError на close при экспортированном view или
   доступ к отвязанной памяти). **Гейт: zero-copy активируется ТОЛЬКО при
   `FW_SHM_HANDLE_CACHE` (+ его связке `FW_SHM_OWNER_INCARNATION`) и `FW_SHM_SEQLOCK`;
   иначе — громкий отказ активации флага (лог) + тихий copy-режим.**
4. **View живёт дольше receive-потока**: item с view уезжает DataReceiver → `chain_queue` →
   PipelineExecutor (другой поток). «Окно использования» кончается не в restore_frame, а
   когда звено дочитало вход — там и должен стоять seqlock re-check (§4, G.5.b).

**Инвариант ПЕРЕМЕННОЙ формы кадра внутри pipeline (дизайн-вход владельца 2026-07-14).**
Плагин может менять форму/размер кадра (grayscale 3→1, resize, crop). Сегодня это работает
by design, и G.5 обязан это СОХРАНИТЬ (факты из кода, перепроверять не нужно):

- Слот выделяется под `max_shape=(max_h,max_w,max_c)` (`calculate_buffer_size`,
  buffer.py:102-118); у КАЖДОГО кадра пишется per-image заголовок
  `struct.pack("III", h, w, c)` + dtype-char (buffer.py:145-147 legacy / :197-199 fast) —
  ФАКТИЧЕСКИЕ размеры. Reader берёт реальные h/w/c ИЗ per-image заголовка, не из max
  (`read_single_frame`/`_read_one_frame`, buffer.py:392/:426). ⇒ меньший кадр
  (grayscale/resize/crop) влезает и читается по факт-размерам, без проблем.
- Guard на превышение: кадр > max_shape → `ValueError("... exceeds max ...")`
  (buffer.py:143-144/:195-196); dtype ≠ expected → `ValueError("dtype mismatch")`
  (buffer.py:139/:191). Под seqlock ловится в try/except `pack_images` (buffer.py:263-273)
  → слот FREE, num_images=0, исключение вверх → `write_images` → None → **громкий
  pickle-fallback (G.3d)**. Это НЕ порча — честная деградация с криком.

**Что это означает для G.5 (4 требования — в §6 как тесты):**

1. **Форма zero-copy view — из per-image заголовка, НЕ из max_shape.** `restore_frame(copy=
   False)` строит view на под-регион слота (h·w·c из заголовка); брать max_shape → view
   потянет хвост padding/соседнего кадра. Самое тонкое место связки zero-copy × переменная
   форма.
2. **dtype/каналы через view**: grayscale (uint8, c=1) как view —
   `np.ndarray(buffer=..., shape=(h,w,c))` корректно строит 2D/3D; проверить grayscale +
   цветной в ОДНОМ кольце.
3. **Sizing пула = max кадр, реально пересекающий ГРАНИЦУ этой камеры.** C6(d) держит
   внутрицепочечные grayscale/resize/crop В ПРОЦЕССЕ (chain внутри воркера, без IPC между
   звеньями) → слот покрывает только boundary-crossing кадры (вход + выход цепочки), НЕ
   промежуточные трансформы. Не раздувать глубину/размер под промежуточные значения.
4. **Инвариант «max покрывает границу»**: если реальный boundary-кадр превышает объявленный
   max (напр. колоризатор 1→3 при max_c=1) — сегодня это громкий pickle-fallback, НЕ порча;
   зафиксировано как ОЖИДАЕМОЕ поведение. Zero-copy при превышении НЕ отдаёт битый view
   (write не состоялся → нет slot-меты → restore идёт fallback-путём / drop, не мусор).

**GUI data-path (решение владельца 2026-07-14):** остаётся `restore_frame(copy=True)` —
zero-copy только на data-plane цепочки инспекции; Qt держит пиксели дольше любого окна.
Помечено «запомнить, пересмотреть по триггеру» (Qt hold/release view). Попутно нит G.3:
зарегистрировать GUI `_recv_frame_mw` в router-stats (torn/drop на дисплее видимы).

## 2. Декомпозиция под-шагов (feature-flag на каждый, коммит на шаг)

Решение владельца 2026-07-14 (§5): **строим ОБА примитива владения — В1 (пол by-construction)
+ В3 (owner-mediated loan/release) — сразу**. Пять под-шагов a→e, каждый за своим флагом.

| Шаг | Суть | Флаг | Риск |
|---|---|---|---|
| **G.5.a** | **Снятие двойной конверсии**: пробросить `return_messages=False` от data-plane call-site (`DataReceiver` → `receive_message` → `ProcessCommunication.receive` → `router.receive`); dict проходит сквозь без Message-пересборки; `msg.to_dict()`-ветка в data_receiver остаётся guard'ом (hasattr) для отката | `FW_DATA_PLANE_DICTS` | низкий (плумбинг параметра; receive() уже работает с dict внутри) |
| **G.5.b** | **Zero-copy чтение**: `restore_frame(copy=False)` — оба пути (`MemoryManager.read_images(copy=False)` — параметр уже есть; `read_single_frame`/`_read_one_frame` — параметр `copy` ДОБАВИТЬ, buffer.py:437 сейчас копирует безусловно); форма view из per-image заголовка (§1 инвариант); item несёт мету view (`shm_actual_name`, `generation`, флаг view); гейт активации по факту 3 §1 (handle-cache+incarnation+seqlock) | `FW_SHM_ZERO_COPY` | средний (lifetime view × потоки × wrap) |
| **G.5.c** | **В1 — безопасный ПОЛ by-construction**: глубокое кольцо + seqlock. Глубина per-camera ≥ длина цепочки × 2 (ручка G.4.b; прод-значение в тесте); **seqlock re-check generation ПОСЛЕ использования** (checkpoint в executor, §4) → drop результата + `frame_stale_drops`++. Гарантирует безопасность ДАЖЕ если release-сообщение В3 потеряно или читатель убит (torn исключён, слот реклеймится обёртыванием кольца). Страховка под В3, не конкурент | `FW_SHM_ZERO_COPY` (checkpoint = часть zero-copy floor) | средний |
| **G.5.d** | **В3 — owner-mediated loan/release/refcount (строгое владение)**: free-list у owner; loan слота при записи; release-сообщение читателя (**обязательно батч/async — см. риск-нот §5**); refcount мутирует ТОЛЬКО owner-процесс (кросс-процессного RMW нет по построению); строгий never-drop + back-pressure к источнику; контракт 1:1 iceoryx2 loan/publish/release | `FW_SHM_LOAN_PROTOCOL` | **высокий** (главный риск фазы) |
| **G.5.e** | **Reclaim-on-death + kill-9 fault-injection (для ОБОИХ уровней)**: (1) «убил читателя БЕЗ release» → В1-пол реклеймит обёртыванием кольца, torn нет; (2) «убил читателя-владельца loan» → В3-reclaim по incarnation/супервизору возвращает loan в free-list. Дропов после reclaim нет, SHM не течёт (startup-cleanup G.3(c) — вторая линия). Оба сценария — обязательные тесты | тесты (без нового флага; В3-ветка под `FW_SHM_LOAN_PROTOCOL`) | высокий |

Порядок: G.5.a → G.5.b → G.5.c → G.5.d → G.5.e. После каждого — прицельный pytest + полный
`run_framework_tests.py` (`QT_QPA_PLATFORM=offscreen`); BackendHarness-smoke при
рантайм-эффекте; коммит. Все флаги default-off (откат бит-в-бит, паритет G.2), flip — G.7.
**Композиция В1+В3:** В1 — безопасность (пол), В3 — детерминированное владение поверх; при
любом сбое В3 (потеря release/смерть) система откатывается на безопасность В1, не на torn.

## 3. ГЛАВНАЯ РАЗВИЛКА — примитив владения (три варианта × три оси)

| Ось | **В1: глубокое кольцо + seqlock, БЕЗ явного refcount** | **В2: refcount через per-region `multiprocessing.Lock`** | **В3: owner-mediated free-list (loan/publish/release)** |
|---|---|---|---|
| Механика | reader держит view; после использования сверяет generation → drop если writer обернул кольцо; глубина ≥ цепочка × 2 делает гонку редкой | истинный release-by-last-reader: лок → refcount±1 → анлок на КАЖДЫЙ кадр КАЖДОГО читателя | owner ведёт free-list; читатель шлёт release-сообщение (батч/async); refcount мутирует ТОЛЬКО owner — RMW-проблема исчезает по построению |
| **Универсально** | header (state/refcount) сохранён, контракт не сужается; семантика = Fast DDS data-sharing (reader detect-overwrite-and-drop) — индустрийный паттерн, но НЕ loan/release | примитив CPython-специфичный, в iceoryx2/DDS не переносится; контракт замусоривается локом | **1:1 iceoryx2 loan/publish/release** — миграция транспорта = замена реализации под тем же контрактом (TECH_STACK §7); задел strict-QoS (`reliability=reliable` на data) |
| **Эффективно** | **ноль локов, ноль IPC, ноль syscalls на кадр** — единственный вариант с нулевой добавкой к hot-path | −1 lock-хоп на кадр × читателя (uncontended единицы мкс, contended — джиттер p99): прямо противоречит цели G.5 (мы кадр экономим ~1 мс копии, чтобы добавить лок?) | +1 release-IPC на кадр × читателя, НО батчируемо (release раз в N кадров / piggyback) и вне критического пути кадра — амортизированно малая цена |
| **Безопасно** | torn невозможен (seqlock); **kill-9 безвреден по построению — читатель не держит НИЧЕГО, reclaim тривиален (нечего reclaim'ить)**; минус: владение вероятностное — нет строгого «слот не переиспользуется до release», нет back-pressure к источнику, occupancy-детект невозможен (writer не отличает прочитанный READY от непрочитанного) | **ФАТАЛЬНО: kill -9 читателя, держащего Lock = вечный deadlock пула** (CPython mp.Lock без robust-семантики pthread) — провал по главному критерию фазы (kill-9 fault-injection обязателен) | строгое владение: слот не переиспользуется до release; kill-9 → loan погибшего reclaim'ится по incarnation (машинерия нужна, но детерминированная); честный back-pressure/occupancy → громкий drop-на-источнике |

**Рекомендация Fable (через линзу «универсальная, эффективная, безопасная»):**

- **В2 — ОТКЛОНИТЬ** без вопроса владельцу: провал сразу по двум осям (лок на hot-path +
  невосстановимый deadlock при kill-9). Единственный «честный atomic» CPython оказывается
  самым опасным примитивом фазы.
- **В1 — дефолт G.5**: даёт ровно те свойства, которые владелец назвал целями (слот под
  читателем не порождает torn — гонка детектится и дропается ГРОМКО; kill-9 не ломает и не
  течёт — по построению), при нулевой цене на hot-path и без нового слоя. Это продолжение
  логики Варианта A G.4: не строить протокол, пока нет потребителя его СТРОГИХ гарантий.
  Честная граница В1: гарантия вероятностная (глубина vs окно обработки), back-pressure к
  источнику отсутствует — при устойчиво медленном читателе он молча живёт на дропах
  (но видимых: `frame_stale_drops`/`frame_torn_reads` → state).
- **В3 — строгое владение (iceoryx2 loan/publish/release 1:1)**: истинный never-drop +
  back-pressure к источнику; refcount мутирует только owner-процесс. Цена — release-IPC на
  кадр (обязательно батч/async, риск-нот §5).

**Изначальная рекомендация Fable была: В1 сейчас + В3 по триггеру** (минимум машинерии при
доказуемой безопасности). **Владелец 2026-07-14 решил иначе — оба сразу** (§5): В1 как пол,
В3 поверх, «чтобы потом не беспокоиться». Оба примитива композируются (В1 страхует В3).
Kill-9 fault-injection (G.5.e) обязателен для обоих уровней — В1 доказывает «нечему течь»,
В3 — reclaim по incarnation.

## 4. Брифы под-шагов (детализируются перед исполнением каждого)

- **G.5.a** — цепочка проброса: `data_receiver.py:150` (`self._receive(...)`) →
  `process_module.py:554 receive_message` → `process_communication.py:291/154` →
  `router_manager.py:718 receive(return_messages=...)`. За флагом data-plane call-site
  передаёт `return_messages=False`; router уже умеет (ветки :779/:786). `_receiver.py:136`
  (AsyncReceiver) НЕ трогать (system-plane, колбэки могут ждать Message) — только
  зафиксировать аудитом. qex-first: свериться, что ни один data-plane потребитель не зовёт
  методы Message на результате (`.to_dict` guard в data_receiver остаётся). Паритет-тест:
  флаг off → в receive-пути рождается Message (бит-в-бит G.2); флаг on → plain dict,
  контент идентичен.
- **G.5.b** — точки: `restore_frame` (frame_shm_middleware.py:348, оба пути),
  `read_images(copy=...)` (manager.py:359 — параметр есть, пробросить),
  `read_single_frame`/`_read_one_frame` (buffer.py:391/:426 — параметр `copy` добавить,
  base-offset уже учтён). Мета view в item: `shm_actual_name` + `generation` на момент
  чтения + маркер «frame — view». **Checkpoint re-check**: место — там, где звено дочитало
  вход (PipelineExecutor после прогона плагинов над входным кадром / перед emit результата;
  точную точку исполнитель выбирает по коду executor'а с обоснованием в ADR): generation
  изменился → drop item + `frame_stale_drops`++ (plain int → get_stats → heartbeat, образец
  G.3d). Эвикция из handle-кэша/`close_handle_cache` при живом view → BufferError: обработать
  (deferred close / try-except с учётом, что eviction уже глотает исключение — см.
  frame_shm_middleware.py:239-245, задокументировать поведение честно). **GUI data-path
  (`multiprocess_prototype/frontend/process.py:44`, on_receive) остаётся `restore_frame(
  copy=True)`** — Qt держит пиксели дольше любого разумного окна; zero-copy только на
  data-plane цепочки инспекции. Пересмотр GUI-zero-copy — отдельный заход по триггеру (Qt
  hold/release view), помечено «запомнить». Попутно закрыть нит G.3: зарегистрировать GUI
  `_recv_frame_mw` в router-stats (torn/drop на дисплей-пути видимы; однострочник prototype).
- **G.5.c (В1 — пол by-construction)** — политика глубины: per-camera `buffer_slots`/
  `history_depth` (ручки G.4.b) ≥ длина цепочки камеры × 2 (frame-pool-idea п.5/7);
  прод-глубина хотя бы в одном тесте; **checkpoint re-check** — тот же механизм, что в §4
  G.5.b (это и есть страховка В1); контракт-доки в buffer.py/qos.py: В1 гарантирует
  безопасность даже при потере release/смерти читателя (torn исключён по построению).
- **G.5.d (В3 — строгое владение)** — free-list в MemoryManager (owner-side); loan слота при
  записи; **release-сообщение читателя строго батч/async** (см. риск-нот §5) через штатный
  system-канал, НЕ на per-frame критическом пути; refcount мутирует ТОЛЬКО owner-процесс
  (кросс-процессного RMW нет по построению — вот почему В2 не нужен); контракт release-msg:
  Dict at Boundary `{slot, index, generation, reader, incarnation}`. Строгий never-drop +
  back-pressure к источнику при исчерпании free-list (громкий drop-на-источнике, счётчик).
- **G.5.e — fault-injection (ОБА уровня)**: (1) «kill -9 читателя БЕЗ release» → В1-пол:
  писатель продолжает, слот реклеймится обёртыванием кольца, torn нет; (2) «kill -9
  читателя-владельца loan» → В3-reclaim: loan погибшего возвращён в free-list по incarnation,
  пул не исчерпывается. Реальный `Process.kill()`, не мок; второй читатель жив; дропов после
  восстановления нет; `ls /dev/shm`-инвариант — сегменты не текут; Linux-ветку прогнать где
  доступно, на Windows — skip с пометкой как в G.3. Переиспользовать репродьюсеры G.3
  (torn / HP-5 switch×in-flight).

## 5. Развилка §3 — РЕШЕНО владельцем 2026-07-14: **ОБА примитива сразу (В1 + В3)**

> **Решение (2026-07-14, простым языком): «сделать как полагается, чтобы потом не
> беспокоиться».** Владелец осознанно усилил скоуп против минимальной рекомендации Fable
> (была: В1 сейчас + В3 по триггеру) — G.5 реализует **полный frame-pool сразу**.

**Что строим:**

- **В1 (глубокое кольцо + seqlock) — безопасный ПОЛ by-construction** (G.5.c): kill-9
  читателя безвреден (держателя-view сносит, слот реклеймится обёртыванием кольца, torn
  исключён seqlock'ом). Ноль локов/IPC на hot-path.
- **Поверх него В3 (owner-mediated loan/release/refcount + reclaim-on-death) — строгое
  владение** (G.5.d): контракт 1:1 с iceoryx2 loan/publish/release; истинный never-drop +
  back-pressure к источнику; refcount мутирует только owner-процесс (кросс-процессного RMW
  нет по построению).

**Они КОМПОЗИРУЮТСЯ, не конкурируют.** В1 — страховка: гарантирует безопасность, даже если
release-сообщение В3 потеряно или читатель убит до release. В3 — детерминированное владение
и back-pressure поверх пола. При любом сбое В3 система откатывается на безопасность В1, не на
torn. Это и есть цель фазы: **универсально** (iceoryx2-контракт, задел смены транспорта) +
**эффективно** (zero-copy; release батчируется/async) + **безопасно** (пол by-construction +
истинный reclaim).

**В2 (refcount через per-region `multiprocessing.Lock`) — ОТКЛОНЁН.** Причина: kill -9
читателя, держащего Lock, = вечный deadlock пула (CPython mp.Lock без robust-семантики
pthread — осиротевший лок не освобождается) → провал по главному критерию фазы (kill-9
fault-injection обязателен). В3 обходит это, не используя кросс-процессный лок вовсе: refcount
живёт и мутирует только в owner-процессе, читатели шлют release-сообщения.

**⚠️ Честный риск-нот (ключевое инженерное требование G.5.d):** цена В3 — **release-IPC на
кадр на читателя**. На hot-path его НЕЛЬЗЯ слать синхронно, иначе IPC съедает весь выигрыш
zero-copy (мы экономим ~1 мс копии, чтобы добавить IPC-хоп на кадр?). **Обязателен
батчинг/async-агрегация release'ов**: amortized batch по N кадров ИЛИ piggyback на heartbeat
ИЛИ отдельный low-priority release-поток. Release едет вне критического пути кадра. Это —
главное требование под-шага владения; проверяется в ревью (угол 6) и замером p99 (acceptance).

**Модель-исполнитель: Opus 4.8, ОДИН заход на весь G.5 (a→e) «одним вскрытием».** Полный
протокол владения = ещё больше оснований за Opus. Обоснование: (1) исходная раскладка «G.5 =
Sonnet, механика» устарела — задача вобрала полный протокол владения («главный риск фазы» по
f7-plan §1); (2) ядро риска — конкурентность lifetime view × wrap кольца × kill-9 × потоки
executor'а × батч-release × reclaim по incarnation — верхний край по модельной политике;
(3) правило «одним вскрытием, один агент»: a→e сцеплены (checkpoint из c — страховка под loan
из d; kill-9 из e проверяет оба уровня), шов-handoff посреди связки дороже; (4) урок G.6
(промах по охвату у Sonnet) на задаче, где охват = безопасность памяти, — не тот риск, что
стоит экономии. Ревью-финдеры — Sonnet (§6), свод и вердикт — Fable.

## 6. План ревью + чек-лист исполнителю

**G.5 — рисковое вскрытие → полное 8-угловое ревью перед merge** (финдеры Sonnet, свод и
вердикт — Fable). Углы:

1. **Lifetime view / use-after-close**: все пути, где view переживает handle (эвикция кэша,
   `close_handle_cache`, wire-replace G.4.d, deconfigure, grow-realloc со сменой имени);
   BufferError-обработка; unlink×view (POSIX страницы живы пока mapped — сверить Windows).
2. **Корректность checkpoint**: окно между последним чтением байт и re-check generation;
   double-wrap кольца (generation u32 через 2^32 — теоретический ABA); item с view,
   пересекающий поток executor'а.
3. **Паритет отката**: каждый флаг off = бит-в-бит (характеризация G.2 до/после); дефолты
   не сдвинуты (грабли G.4 ревью-находка №1 — скрытые сдвиги дефолтов).
4. **Честность kill-9 теста**: реальный kill, не мок; прод-значения глубины/флагов
   (грабли «тест-параметры прячут окно дефекта»); негативный кейс воспроизводится до фикса.
5. **Cross-file потребители**: все консумеры data-plane результата receive (GUI, backend_ctl
   tap, recorder-плагины, worker-handlers) — никто не зовёт Message-методы / не мутирует
   view in-place (in-place мутация view = запись в ЧУЖОЙ SHM-слот!).
6. **Hot-path дисциплина + батч-release (В3)**: ноль новых аллокаций/локов/Pydantic на
   per-frame пути; метрики plain int → get_stats → heartbeat (фасады, образец
   frame_torn_reads); никаких самодельных счётчиков с локами. **Отдельно: release-IPC В3
   НЕ синхронный на кадр** — батч/async/piggyback (риск-нот §5); замером доказать, что p99 не
   вырос от release-трафика (иначе В3 съел выигрыш zero-copy).
7. **Мультикамера/нагрузка**: изоляция колец при wrap под нагрузкой; load-независимые
   assert'ы (урок флака full-HD G.3 — assert только инварианты безопасности).
7b. **Переменная форма кадра × zero-copy (дизайн-вход владельца, §1 инвариант)** —
   обязательные тесты: (i) кадр СИЛЬНО меньше max (crop 100×100 в слоте под 1920×1080) →
   zero-copy view имеет правильный shape из per-image заголовка, НЕ тянет padding/соседний
   кадр; (ii) grayscale (uint8, c=1) + цветной в ОДНОМ кольце через view — 2D/3D строится
   корректно; (iii) sizing слота = max boundary-crossing кадр камеры (НЕ промежуточные
   внутрицепочечные трансформы — C6(d) держит их в процессе); (iv) boundary-кадр >
   объявленного max (колоризатор 1→3 при max_c=1) → `frame_pickle_fallbacks`++ (громкий
   fallback G.3d), zero-copy НЕ отдаёт битый view (write не состоялся → нет slot-меты).
8. **Контракт/доки**: iceoryx2-совместимость header'а (loan/publish/release) точна;
   композиция В1+В3 задокументирована (В1 = пол, В3 = строгое владение поверх); GUI copy-out
   помечен «пересмотреть по триггеру»; ADR (router/shared_resources DECISIONS.md) + `python
   -m scripts.sync`; строка G.5 plan.md обновлена (§7).

**Чек-лист правил фазы (исполнителю):**

- Ветка `feat/constructor-f7` от актуального main (сверить SHA базы!), isolation: worktree.
- Каждый рантайм-эффект за feature-flag (конфиг+env, ctor > env > конфиг как F3), дефолт =
  старое поведение; flip — только G.7.
- Наблюдаемость строго через фасады (LoggerManager/ErrorManager/StatsManager); образец —
  `frame_torn_reads` → `RouterManager.get_stats` → heartbeat → `state.shm.*`.
- Per-frame путь БЕЗ Pydantic; Dict at Boundary; конверт кадра — системные поля несёт движок
  (`_CARRIED_SYSTEM_FIELDS`).
- Тесты: `python scripts/run_framework_tests.py` + прицельный pytest;
  **`QT_QPA_PLATFORM=offscreen` обязательно**; прод-значения параметров хотя бы в одном
  тесте; BackendHarness-smoke; **kill-9 fault-injection читателя обязателен**.
- Коммиты: Conventional Commits + `Why:`/`Layer:` +
  `Refs: plans/2026-07-06_constructor-master/plan.md`; коммит на каждый под-шаг.
- НЕ трогать скоуп соседних задач (G.7 flip, G.8 drain, G.9 GC/msgspec); qex-first при
  поиске использований.

**Acceptance G.5 (сводно, ДЕТЕРМИНИРОВАННЫЙ):** паритет доставки G.2 зелёный (все флаги off =
бит-в-бит); p99 ≤ baseline same-tier (tier синтетика: restore p99 1.255 мс — ожидаем ощутимое
снижение, send+restore ~1 мс/кадр; receive-конверсия 0.097/0.180 мс → ~0; release-трафик В3
p99 не поднимает); переменная форма кадра через zero-copy корректна (§6 угол 7b); слот НЕ
переиспользуется до release последним читателем (В3); при потере release / смерти читателя —
reclaim по incarnation, torn исключён В1-полом, дропов после reclaim нет; kill -9
читателя-владельца → пул восстанавливается, SHM не течёт.

## 7. Строка G.5 в plan.md — ФИНАЛЬНАЯ формулировка (заменить строку ~342)

Единственная формулировка под расширенный скоуп «оба примитива сразу» (применяет оркестратор):

> | G.5 | [ ] | **Zero-copy тракт чтения + полный протокол владения слотом (frame-pool, оба примитива сразу — решение владельца 2026-07-14, [g5-execution-plan.md](g5-execution-plan.md)):** (a) снятие двойной конверсии — `return_messages=False` на data-plane (dict без пересборки в Message/Pydantic на кадр); (b) `restore_frame(copy=False)` — reader держит view в слот, форма из per-image заголовка (переменная форма grayscale/resize/crop сохранена), гейт только при handle-cache+incarnation+seqlock; (c) **В1 — безопасный ПОЛ by-construction:** глубокое кольцо + seqlock re-check generation ПОСЛЕ использования → drop+счётчик при гонке (глубина per-camera ≥ длина цепочки × 2); (d) **В3 — owner-mediated loan/release/refcount поверх пола:** строгий never-drop + back-pressure к источнику, контракт 1:1 iceoryx2 loan/publish/release, refcount только owner-side (кросс-процессного RMW нет), release-IPC **обязательно батч/async** (не на per-frame пути); (e) reclaim-on-death + **kill-9 fault-injection обязателен для ОБОИХ уровней** (убил читателя без release → В1-пол реклеймит; убил читателя-владельца → В3-reclaim по incarnation). В2 (refcount через mp.Lock) отклонён — deadlock пула при kill-9 (CPython без robust-mutex). Строго после G.3 (seqlock) и G.4 (кольца/QoS). Все под-шаги за флагами (`FW_DATA_PLANE_DICTS`/`FW_SHM_ZERO_COPY`/`FW_SHM_LOAN_PROTOCOL`), дефолт off, flip на G.7. | паритет G.2 зелёный (флаги off = бит-в-бит); p99 ≤ baseline same-tier (release-трафик В3 p99 не поднимает); переменная форма кадра через zero-copy корректна; **слот не переиспользуется до release последним читателем (В3)**; при потере release / смерти читателя — reclaim по incarnation, torn исключён В1-полом, дропов после reclaim нет; **kill -9 читателя-владельца → пул восстанавливается**, SHM не течёт | M+M |

## 8. В3 — детальный дизайн owner-mediated loan/release (перед кодом G.5.d/e)

> Добавлено оркестратором 2026-07-14 перед реализацией В3 (владелец: «без костылей,
> как полагается»). В1-пол (a/b/c) уже даёт безопасность; В3 — детерминированное
> владение + строгий never-drop + back-pressure поверх. Всё за `FW_SHM_LOAN_PROTOCOL`,
> default-off. В3 НЕ переопределяет В1: при любом сбое В3 (потеря release/смерть) система
> откатывается на безопасность В1 (re-check → drop, не corruption).

### 8.1 Модель (iceoryx2 loan/publish/release, 1:1)
- **Producer (owner)** держит free-list слотов кольца: `refcount[idx]` (0 = свободен,
  >0 = выдан N читателям). Мутирует ТОЛЬКО owner-процесс → кросс-процессного atomic RMW
  нет по построению (вот почему В2/mp.Lock не нужен).
- **loan-on-write:** вместо слепого `write_index % coll` producer берёт СВОБОДНЫЙ слот
  (refcount==0). Пишет кадр, ставит `refcount[idx] = num_consumers`. Свободных нет
  (читатели отстали) → **громкий drop-на-ИСТОЧНИКЕ** (счётчик `frame_loan_exhausted` +
  throttled лог), кадр НЕ отправляется (это и есть back-pressure-сигнал; НЕ pickle-fallback).
- **release:** consumer, ДОЧИТАВ view (та же точка, что re-check G.5.c в executor),
  отправляет release-тикет владельцу. **Строго БАТЧ/ASYNC** (не на per-frame критическом
  пути): copic накапливает тикеты, флашит пачкой (по K или на такте) через system-канал.
- **release-handler (owner):** на пачку тикетов — по каждому (idx, generation) сверяет
  generation с текущим займом слота (guard от stale-release прошлого займа) → декремент
  `refcount[idx]` → 0 = слот свободен (назад в free-list).

### 8.2 Решённые развилки (выбраны дефолты, без костылей)
1. **Откуда `num_consumers` (fan-out refcount)?** — из конфигурации middleware (кол-во
   targets камеры), как subscriber-registry в iceoryx2. Ставится в ctor (`num_consumers`,
   дефолт 1). **✅ Проводка из топологии — G.7 (fix `fe0f4d41`, 2026-07-15):** `generic_process`
   считает loan-aware цели из `chain_targets` (copy-out/GUI исключены, они release не шлют);
   0 loan-aware → пул не создаётся (round-robin В1), исключая исчерпание на GUI-only fan-out.
   Дополнительно разнесены две роли: `loan_protocol_enabled` (сырой флаг, роль консьюмера —
   release вверх) vs создание своего пула (только num_consumers>0, роль владельца).
   Ошибка счёта НЕ ведёт к порче: занижен → слот освободится рано → В1 re-check дропнет;
   завышен → слот подержится дольше (потенц. loan-exhaustion, виден счётчиком). Безопасно.
2. **Исчерпание free-list: block или drop?** — **drop-на-источнике громкий** (дефолт, по
   плану). Живую камеру блокировать нельзя (кадры теряются в железе); drop+счётчик =
   честный back-pressure-сигнал. Строгий never-drop-потребитель (запись на диск) достигается
   ДОСТАТОЧНОЙ глубиной кольца (не блокировкой) — конфиг рецепта. Block-семантику НЕ вводим
   (риск дедлока источника); если появится потребитель, которому нужен именно block —
   отдельная задача с явным решением владельца.
3. **Каденс батча release?** — накопитель на consumer + флаш по порогу (K тикетов) ИЛИ на
   такте существующего механизма (heartbeat/периодический). НЕ синхронный send на кадр.
   Точный порог K — прод-значение в тесте; дефолт K=8 (≈ глубина кольца), флаш также на
   teardown (не потерять хвост).
4. **Транспорт release?** — system-канал (надёжный, never-drop QoS G.4.a), Dict at Boundary
   `{type:"shm_release", owner, slot, index, generation, reader, incarnation}`. Пачкой —
   один конверт со списком тикетов (амортизация границы).
5. **Guard от stale-release:** тикет несёт `generation` прочитанного кадра; handler
   декрементит ТОЛЬКО если generation совпадает с текущим займом слота (иначе тикет от
   прошлого займа того же idx — игнор). Плюс `incarnation` — тикеты от прошлой инкарнации
   consumer'а игнорируются (после его рестарта).

### 8.3 Reclaim-on-death (G.5.e)
- Owner трекает, КАКОМУ consumer'у (reader+incarnation) выдан каждый слот (не только
  счётчик, но и множество держателей на слот — для точного reclaim).
- Смерть consumer'а (supervisor-событие / смена incarnation в processes.*) → owner
  force-освобождает ВСЕ слоты, где этот (reader,incarnation) был держателем: декремент за
  него, снятие из множества; refcount→0 = свободен. Второй живой держатель НЕ теряет свой
  займ.
- Вторая линия (страховка): В1 re-check + startup-cleanup осиротевших сегментов G.3(c).
- **kill-9 fault-injection обязателен** (G.5.e): (1) убил читателя БЕЗ release → В1-пол
  реклеймит обёртыванием; (2) убил читателя-держателя loan → В3-reclaim по incarnation
  возвращает слот; дропов после восстановления нет, SHM не течёт.

### 8.4 Декомпозиция В3 (коммит на шаг, всё за FW_SHM_LOAN_PROTOCOL)
- **G.5.d-1:** owner-side free-list (`refcount[]` + держатели), loan-on-write (свободный
  слот вместо round-robin), громкий `frame_loan_exhausted` при исчерпании. БЕЗ release ещё
  → под флагом кольцо исчерпается (ожидаемо; release в d-2 замыкает). Тесты: loan занимает
  слот; исчерпание → drop+счётчик; off = слепой round-robin бит-в-бит.
- **G.5.d-2:** release-путь: накопитель+флаш на consumer (executor, точка re-check),
  system-конверт пачкой; owner release-handler с generation/incarnation-guard → декремент
  → free. Тесты: loan→release→слот свободен; stale-release игнор; батч флашит по порогу и
  на teardown; НЕ на per-frame пути (счётчик отправок release ≪ кадров).
- **G.5.e:** reclaim-on-death + kill-9 fault-injection (оба уровня).

### 8.5 Инварианты (проверять в ревью)
- refcount мутирует ТОЛЬКО owner (grep: нет записи refcount из consumer-пути).
- release НЕ на per-frame критическом пути (батч; замер: release-конвертов ≪ кадров).
- В3-off = В1-поведение бит-в-бит (слепой round-robin + re-check).
- Любой сбой В3 (потеря release, смерть, ошибка счёта) → откат на В1-безопасность (drop,
  НЕ corruption), никогда на torn/stale-frame наружу.
- system-канал release never-drop (QoS G.4.a); потеря release НЕ ведёт к вечному займу
  (страховка reclaim + В1).
