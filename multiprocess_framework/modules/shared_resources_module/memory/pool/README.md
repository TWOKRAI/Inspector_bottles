# memory/pool — пул кадровых слотов SHM (владение по цепочке)

Часть **консолидации памяти** (Ф7 H-задача). Держит семантику **владения слотом кольца SHM**
за Protocol-фасадом в модуле памяти, а не в транспортном `router_module`.

## Зачем

G.5.d/e построили loan-протокол (free-list + refcount + release + reclaim) прямо в
`FrameShmMiddleware` — ~200 строк семантики владения в **транспортном** модуле + мёртвый
второй учёт `index_usage` в `MemoryManager`. H-задача сводит владение в один модуль:
транспорт становится чистым адаптером и делегирует пулу через DI.

## Контракт (`interfaces.FramePool`, Protocol)

| Метод | iceoryx2/DDS | Смысл |
|-------|--------------|-------|
| `acquire() -> int \| None` | loan | взять свободный слот (refcount==0); None = исчерпание → drop-на-источнике |
| `commit(idx, num_consumers)` | publish | refcount = число loan-aware потребителей (fan-out) |
| `release(tickets) -> int` | release | owner-side декремент по пачке тикетов (guard'ы: stale/gen/dup) |
| `reclaim(dead_reader) -> int` | — | реклейм займов мёртвого читателя (kill-9 без release) |
| `reset()` | — | сброс в «всё свободно» (realloc кольца) |
| `snapshot_stats() -> PoolStats` | — | счётчики (released/reclaimed/exhausted) для наблюдаемости |

`LoanTicket` — pickle-safe dict `{index, generation, reader}` (Dict at Boundary).

## Модель конкурентности

refcount мутирует **ТОЛЬКО процесс-владелец** (owner-side) — кросс-процессного atomic RMW в
CPython нет по построению (отклонение варианта В2 mp.Lock, g5-план §8). Безопасность от
torn-кадра даёт **seqlock** (G.3) + **post-use re-check** (В1), НЕ этот учёт: любая ошибка
учёта здесь безопасна (преждевременное освобождение → writer перезапишет → generation drift
→ drop, не порча). `gen_reader` инжектируется в реализацию → пул SHM-агностичен.

## Реализации

- `LoanLedger` — руками на CPython (текущая, дефолт).
- *(Этап 3, по триггеру TECH_STACK §7)* — Rust/iceoryx2 под тем же Protocol; транспорт не трогается.

## Активность

Пул создаётся транспортом ТОЛЬКО при включённом `FW_SHM_LOAN_PROTOCOL`. Флаг off →
транспорт идёт прежним слепым round-robin, пул не инстанцируется (откат бит-в-бит).

Тесты: `../tests/test_frame_pool.py` (contract-тесты фасада).
