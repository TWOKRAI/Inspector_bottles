# memory/reader — reader-side кадровый тракт SHM

Часть **консолидации памяти** (Ф7 H-задача, Этап 2). Держит чтение кадра у потребителя за
Protocol-фасадом в модуле памяти, а не в транспортном `router_module`.

## Зачем

G.3/G.5.b/c построили (тогда за флагами, см. «Режим один» ниже) кэш SHM-handles + zero-copy view + post-use re-check прямо в
`FrameShmMiddleware`, причём приватный `_cache_lock` дёргал ещё и `PipelineExecutor`
(cross-module доступ к внутренностям транспорта). H-задача сводит reader в один модуль:
транспорт делегирует, синхронизация кэша — внутреннее дело reader'а.

## Контракт (`interfaces.FrameReader`, Protocol)

| Метод | Смысл |
|-------|-------|
| `read_ref(name, gen, *, copy, key) -> frame\|None` | чтение кадра по ссылке (Task 4.4): сверка `gen` до и после; `copy=False` → read-only view; `key=(owner, slot, idx)` — ключ кэша handles |
| `view_valid(shm_view_name, gen_at_read, *, key) -> bool` | post-use re-check (G.5.c): слот не перезаписан под живым view |
| `retire(key)` — только `ShmFrameReader`, не в Protocol | убрать handle ключа (кэп у вызывающего: мост держит LRU по имени, 32) |
| `close()` | закрыть все кэшированные handles и отложенные (`_retired`) — teardown |
| `stale_drops`, `torn_reads` (properties) | сколько чтений/view дропнуто по расхождению `gen` / порвано перезаписью |
| `close_errors`, `deferred_closes` — только `ShmFrameReader`, не в Protocol | ошибки закрытия и handles, отложенные из-за живого view; в телеметрию не экспортируются |

## Синхронизация (гонка закрыта по построению)

Кэш читают ДВА потока процесса: `DataReceiver` (на чтении) и `PipelineExecutor` (на
re-check). `ShmFrameReader` держит СВОЙ lock и сериализует `dict`+`close` — гонка «close()
рвёт backing-mmap под read_generation на другом потоке» невозможна, т.к. внешний код больше
НЕ трогает кэш напрямую (раньше executor лез в приватный `_cache_lock`/`_shm_handle_cache`
транспорта).

## Режим один (Task 4.7b, 2026-10-02)

Флаги `FW_SHM_ZERO_COPY`, `FW_SHM_HANDLE_CACHE`, `FW_SHM_OWNER_INCARNATION` удалены из реестра.
Кэш handles всегда включён; ключ — `(owner, slot, idx)` из ссылки (без owner — `(name,)`), кэпа 8 нет.
Handle с живым view при отставке не закрывается: он уходит в `_retired` (счётчик `deferred_closes`
у reader'а) и закрывается на следующей отставке либо в `close()`. Пайплайн получает view только
для чтения, `on_receive` копирует. Бывшая связка `zero_copy ⊃ cache ⊃ owner_incarnation` теперь
выполняется по построению: имя меняется на каждое создание сегмента всегда.

## Реализации

- `ShmFrameReader` — на `multiprocessing.shared_memory` (текущая).
- *(Этап 3, по триггеру TECH_STACK §7)* — Rust/iceoryx2 под тем же Protocol.

Тесты reader-тракта: `../../../router_module/tests/test_g5b_zero_copy.py`,
`test_g5c_stale_recheck.py` (через транспорт-делегацию).
