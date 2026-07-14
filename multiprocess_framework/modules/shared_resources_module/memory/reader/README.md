# memory/reader — reader-side кадровый тракт SHM

Часть **консолидации памяти** (Ф7 H-задача, Этап 2). Держит чтение кадра у потребителя за
Protocol-фасадом в модуле памяти, а не в транспортном `router_module`.

## Зачем

G.3/G.5.b/c построили кэш SHM-handles + zero-copy view + post-use re-check прямо в
`FrameShmMiddleware`, причём приватный `_cache_lock` дёргал ещё и `PipelineExecutor`
(cross-module доступ к внутренностям транспорта). H-задача сводит reader в один модуль:
транспорт делегирует, синхронизация кэша — внутреннее дело reader'а.

## Контракт (`interfaces.FrameReader`, Protocol)

| Метод | Смысл |
|-------|-------|
| `read_frame(name, seqlock, *, copy, view_meta) -> frame\|None` | чтение одного кадра (кэш handles; `copy=False` → view + мета для re-check) |
| `view_valid(shm_view_name, gen_at_read) -> bool` | post-use re-check (G.5.c): слот не перезаписан под живым view |
| `close()` | закрыть все кэшированные handles (teardown) |
| `stale_drops` (property) | сколько view дропнуто re-check'ом (наблюдаемость) |

## Синхронизация (гонка закрыта по построению)

Кэш читают ДВА потока процесса: `DataReceiver` (на чтении) и `PipelineExecutor` (на
re-check). `ShmFrameReader` держит СВОЙ lock и сериализует `dict`+`close` — гонка «close()
рвёт backing-mmap под read_generation на другом потоке» невозможна, т.к. внешний код больше
НЕ трогает кэш напрямую (раньше executor лез в приватный `_cache_lock`/`_shm_handle_cache`
транспорта).

## Жёсткие связки флагов (резолвит транспорт, reader получает согласованные)

`zero_copy` ⊃ `cache_enabled` ⊃ `owner_incarnation` (G.5): view живёт после чтения → нужен
кэш (иначе сегмент закрыт, view повис); кэш безопасен только при смене имени на каждый
realloc (owner_incarnation). Под `zero_copy` эвикция с `close()` ОТКЛЮЧЕНА.

## Реализации

- `ShmFrameReader` — на `multiprocessing.shared_memory` (текущая).
- *(Этап 3, по триггеру TECH_STACK §7)* — Rust/iceoryx2 под тем же Protocol.

Тесты reader-тракта: `../../../router_module/tests/test_g5b_zero_copy.py`,
`test_g5c_stale_recheck.py` (через транспорт-делегацию).
