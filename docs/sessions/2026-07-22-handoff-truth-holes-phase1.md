# Handoff — truth-holes-closure, Фаза 1 закрыта (2026-07-22)

**Ветка:** `fix/truth-holes-closure` (11 коммитов, в origin НЕ пушено, дерево чистое)
**План:** [`plans/truth-holes-closure.md`](../../plans/truth-holes-closure.md)
**Аудит live:** [`docs/audits/2026-07-22_phase1-flip-webcam-sketch.md`](../audits/2026-07-22_phase1-flip-webcam-sketch.md)

## Что сделано

**Гигиена:** предшественник `backend-ctl-proof-discipline` был закрыт по гейту, но не слит —
слит в `main` fast-forward до `9a0f4137`; `truth-holes-closure` заведён как преемник
(правило «один активный план на инструмент»); QUEUE.md синхронизирован.

**Фаза 1 — ЗАКРЫТА** (гашение gui-шторма), оба флага **default OFF**:

| Задача | Коммит | Суть |
|---|---|---|
| 1.1 | `2c2bd721` | tick-коалесцирование дельт per-subscriber (`FW_STATE_COALESCE`, 120мс, cap 200) |
| 1.2 | `b2c37e5c` | очередь класса `state` для state.changed (`FW_STATE_QUEUE`, drop_oldest) |
| 1.3 | — | пропущена по замеру (measure-gated, давления на Qt-поток нет) |
| 1.4 | `d2cf7691` | ui_*-плоскость доказана парой (закрыто вечное «ui_* NA») |

**Фаза 3** — `2a48ebe8`: корень несрабатывающей ротации логов (два `_SafeRotatingFileHandler`
на один `messages.log` → на Windows rename падает WinError32). Фикс — общий refcounted
хэндлер по abs-path.

**Фиксы по ревью Fable** (2 итерации, обе находки + остаток закрыты):
- `d1ee9402` — **реальный баг**: гонка cap-flush → бесшумная потеря до 200 дельт под штормом.
  Закрыт инвариантом «единственный отправитель» (cap будит flusher, не шлёт сам).
- `d1d3e4ef` — тот же инвариант для initial-replay (`enqueue_replay`).
- `bd8f4478` — реген golden-снэпшотов прототипа (ветка была красная).

**Фаза 6 заведена** (`ed339cf9`) — снятие лесов: план НЕ закрыт, пока флаги не **удалены**,
а не только флипнуты.

**Новый DRAFT-план** — [`plans/telemetry-pull-on-demand.md`](../../plans/telemetry-pull-on-demand.md):
телеметрия по опросу (уровни) + push (фронты). Ждёт go-ahead владельца.

## Live-результат (webcam_sketch, пара OFF→ON)

| Метрика | OFF | ON |
|---|---|---|
| Безвозвратные потери в gui | 597+ за 30с | **0** |
| `errors` / `system_evict_blocked` | 1461 / 1466 | **0 / 0** |
| Доставка | 267/1728 = 15 % | **270/270 = 100 %** |
| `gui_system` | 100/100 | **0** |
| gui отвечает на команды | нет | **да** |

## Что дальше

1. **Фаза 2** — правда supervision: `pid`/`started_at`/`manual_restarts` в `supervision.status`
   (reuse-restart не бампает incarnation осознанно — нужен другой маркер замены инстанса).
2. **Фаза 4** — инструментальный трек (4.1 readback телеметрийного gate → 4.2 verify,
   4.3 «кто душит очередь X», 4.4 `process_restart_verified` после 2.1, 4.5 доки).
3. **Фаза 5** — закрывающий live-прогон.
4. **Фаза 6** — флип дефолтов → soak → **удалить** оба флага (6.3 ждёт инвентарь
   levels-vs-edges из `telemetry-pull-on-demand`).

## Грабли этой сессии (не повторять)

- **Самопроверка гонку не поймала.** Я прочитал код, прогнал тесты, специально разобрал
  гонку cap-flush и заключил «гонки нет» — ошибся. Поймало независимое Fable-ревью.
  Unit-тесты тоже молчали (не гоняли конкурентный multi-thread flush).
- **Live обманул бы.** На `dualcam_synth` шторма нет (gui в main-процессе недостижим для
  backend_ctl) → баг не срабатывает → «live чисто». Мерить шторм **только на `webcam_sketch`**.
- **Трейлер `Tested:` был неполным** — не гонял suite прототипа, ветка была красная.
  Аддитивные правки `DEFAULT_QUEUES` текут в golden-снэпшоты.
- **«No handler for key» врёт про причину** — сразу после boot gui объявлен готовым по
  liveness-fallback ДО регистрации команд; сообщение читается как «фичи нет». На прогретой
  системе тот же вызов проходит. Residual для Ф4/Ф5.

## Запуск live (для повтора)

```bash
# baseline (флаги OFF)
BACKEND_CTL=1 .venv/Scripts/python multiprocess_prototype/run.py webcam_sketch
# флип + qt-mcp для ui_*
QT_MCP_PROBE=1 FW_STATE_COALESCE=1 FW_STATE_QUEUE=1 BACKEND_CTL=1 \
  .venv/Scripts/python multiprocess_prototype/run.py webcam_sketch
```
Строго один инстанс (порт 8765). Гасить: `system.shutdown` → TaskStop.
