# G.7 — гайд по тесту на Windows (2026-07-16)

**Ветка:** `feat/mem-module-consolidation` (tip `3c1b6c67`; H-ремедиация в `b3576c12`).
**Цель:** снять реальные FPS/p99/аллокации с флипнутыми флагами кадрового тракта на Windows
(соак обоих рецептов), сравнить с baseline. Реальный вердикт эффективности — отсюда, не с
macOS-peek (тот в `plans/2026-07-06_constructor-master/baseline.md` §G.7 — только ориентир).

## 0. Предпосылки
- `BACKEND_CTL=1`, `QT_QPA_PLATFORM=offscreen` (агентские прогоны без окон; ручной GUI — без offscreen).
- Всё за флагами: **дефолт off = бит-в-бит прежнее поведение** (откат = снять флаг, кода не трогать).

## 1. Флаги G.7 (env, значение `1` = on)
Жёсткие связки резолвит транспорт: `ZERO_COPY ⊃ HANDLE_CACHE ⊃ OWNER_INCARNATION` — включать
цепочку целиком, иначе слой сам деградирует (с логом).

| Флаг | Что включает |
|---|---|
| `FW_SHM_SEQLOCK` | seqlock-формат слота (torn-frame → честный drop, не порча) |
| `FW_SHM_LOAN_PROTOCOL` | пул владения слотом (loan/publish/release/reclaim, single-writer) |
| `FW_SHM_OWNER_INCARNATION` | owner+pid+incarnation в имени SHM (нет коллизий после switch/kill) |
| `FW_SHM_HANDLE_CACHE` | кэш SHM-handles у читателя (снимает open/mmap/close на кадр) |
| `FW_SHM_ZERO_COPY` | view в слот вместо копии на чтении (+ post-use re-check) |
| `FW_QOS_PROFILES` | глубина кольца из QoS-профиля + видимый `data_evicted` |
| `FW_GC_FREEZE` | `gc.freeze()` startup-объектов (короче паузы GC) |
| `FW_GC_SCHEDULED` | (опц., measurement-gated) ручной GC в паузах — pump в heartbeat |
| `FW_DATA_PLANE_DICTS` | per-frame plain dict (без Pydantic-пересборки) |

PowerShell пример (флип всей кадровой цепочки):
```powershell
$env:BACKEND_CTL=1; $env:FW_SHM_SEQLOCK=1; $env:FW_SHM_LOAN_PROTOCOL=1
$env:FW_SHM_OWNER_INCARNATION=1; $env:FW_SHM_HANDLE_CACHE=1; $env:FW_SHM_ZERO_COPY=1
$env:FW_QOS_PROFILES=1; $env:FW_GC_FREEZE=1
```

## 2. Замер
**Синтетик-tier (кросс-платформенный probe, same-tier как baseline):**
```
python -m backend_ctl.g1_perf_probe 30
```
Снимает FPS источник/потребитель, latency p50/p99 (capture/send/receive/restore), границ/кадр.
Прогнать по 3-5 раз off и on — на Windows числа устоятся, вариативность видна.

**Реальные рецепты (soak):** поднять `phone_sketch` / `webcam_sketch` (или Hikvision, если
железо есть) с флагами on на несколько минут; смотреть FPS/p99 в GUI (вкладка Pipeline) или
через `introspect` backend_ctl.

**Аллокации/кадр:** `AllocProfiler` (`process_module/generic/alloc_profile.py`, tracemalloc)
на соаке — байт/блоков на кадр on↔off.

## 3. Что СМОТРЕТЬ (watch-list H-ремедиации)
- **Single-writer guard:** в логах НЕ должно быть `RuntimeError: обнаружен ВТОРОЙ писатель
  кадрового кольца`. Если появился — топология положила source+processing в один процесс
  (в 29 рецептах такого нет; сигнал о новой/битой топологии, а не о баге пула).
- **Счётчики (heartbeat → state.shm / introspect):** `frame_loan_exhausted` (читатели
  отстают), `frame_stale_drops` (view перезаписан под re-check), `close_errors` (ошибки close
  handle — рост = утечка при частых wire.deconfigure), `data_evicted` (QoS drop).
- **num_consumers = 1 (резидуал G.H):** при fan-out на >1 loan-aware потребителя refcount
  занижен → лишние `stale_drops`/дропы. Это ОЖИДАЕМО до проводки num_consumers из топологии
  (часть полной G.7). На одиночном потребителе — не проявляется.
- **kill -9 / switch рецепта:** осиротевшие SHM — на Windows ОС сама освобождает mapping при
  гибели последнего handle (осиротевших почти нет); `FW_SHM_PREFIX_CLEANUP` (дефолт off) —
  best-effort. Проверить, что после switch backend_ctl-socket жив (gate G.7).

## 4. Платформенные оговорки (Windows vs macOS/Linux)
- **SHM cleanup:** Windows освобождает сегмент при закрытии последнего handle (нет unlink как
  на POSIX) → осиротевшие сегменты почти не копятся; prefix-scan `/dev/shm` — Linux-only (на
  Windows no-op, best-effort open+close).
- **Имя SHM:** owner+pid+incarnation; лимит длины имени (`PSHMNAMLEN`) — только macOS-проблема,
  на Windows не актуальна.
- `resource_tracker`-варнинги multiprocessing на Windows звучат иначе — не путать с ошибкой.

## 5. Gate G.7 (критерии приёмки)
FPS ≥ baseline (same-tier) · p99 ≤ baseline · backend_ctl-socket жив после switch · drop-счётчики
видимы · откат = флаг off. + резидуалы: провести `num_consumers` из топологии; E2E release живым
транспортом; incarnation-guard; реальный kill-9.

## Ориентир (macOS-peek 2026-07-15, НЕ вердикт)
restore p99 4.14→0.35 ms (~12×), restore p50 0.59→0.088 ms (6.7×), capture p99 2.30→0.49 ms,
FPS 28.7≈28.5 (упор в источник). Windows-числа могут отличаться — это и есть цель теста.
