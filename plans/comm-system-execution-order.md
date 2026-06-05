# Plan: Порядок исполнения comm-system + observability (sequencing / оркестрация)

- **Slug:** comm-system-execution-order
- **Дата:** 2026-06-04 (обновлено 2026-06-05)
- **Статус:** S0/S1/S3 DONE — осталось S2 (merge) → S4 → S5
- **Тип:** meta / cross-cutting — НЕ новый код, а порядок над 5 существующими планами
- **Ветка:** работает поверх `feat/comm-system-target-architecture` и `feat/observability-control-plane` (см. §«Ветки»)

> **СВЕРКА С РЕАЛЬНОСТЬЮ (2026-06-05).** С момента написания (04.06) сделано больше, чем в порядке ниже:
> - **S0 (telemetry-A) — DONE.** Решено НЕ через Option A bridge-reuse, а через `telemetry-self-publish-redesign.md` (процесс сам публикует fps/latency в дерево; FPS числами, статусы зелёные). qt-smoke 2026-06-05 подтвердил. План self-publish заархивирован.
> - **S1 (observability + §11 CRM) — частично/моот.** План `2026-06-03_observability-control-plane/` так и НЕ был написан (есть только ветка `feat/observability-control-plane`). §11 CRM-пункты #16/#17/#18 закрыты в составе P0 §11. `reconfigure()`/hot-reload — отдельная работа, появится при реальной потребности (не блокирует).
> - **S3 (§11 quick-wins) — DONE.** Весь P0 §11 (пп.1-22, вкл. hot-path осторожную зону) закрыт 2026-06-05 (5 коммитов + qt-smoke). См. `comm-system-target-architecture.md` трекинг S8.
> - **Осталось:** **S2** (merge ветки в main — 303 коммита, FF-возможен) → **S4** (kind-каналы TRH P3/P4 = comm-system P1/P2) → **S5** (авто-reply/undo/carve-out). Порядок ниже актуален для S2-S5.

> **Зачем этот файл.** Пять планов (ниже) — это пять срезов ОДНОЙ цели, но с пересекающейся
> нумерацией фаз и расходящимися ветками. Болит не архитектура (она цельная), а **координация**.
> Этот документ — единый порядок + зафиксированные решения сессии 2026-06-04, чтобы в новом
> чате не перечитывать всё заново.

---

## Цель (один абзац)

**RouterManager = единый хаб control-plane.** Всё (команды / конфиг / телеметрия-как-данные)
идёт через `router.send`; каналы выбираются по `kind`; адрес иерархический (`proc.worker`);
реактивный StateStore понижается до capability. Пять планов — грани этой цели.

## Карта планов (иерархия истины)

| План | Роль | Статус |
|------|------|--------|
| [`comm-system-target-architecture.md`](comm-system-target-architecture.md) | **Канон + матрица сохранности §9 + «почему»**. Справочник, НЕ план исполнения. | ревью B+ 8/10 |
| [`2026-05-31_transport-router-hub/plan.md`](2026-05-31_transport-router-hub/plan.md) | **Движок-план.** Фундамент: адресация + хаб-на-отправке. Владелец kind-каналов. | P0–P2 **DONE**, P3–P5 манифест |
| [`telemetry-delivery-simplification.md`](telemetry-delivery-simplification.md) | Дочерний к comm-system §12 P0 (подзадача телеметрии). | DRAFT |
| [`2026-06-03_observability-control-plane/plan.md`](2026-06-03_observability-control-plane/plan.md) | Параллельная подсистема: Logger/Error/Stats + hot-reload. | DRAFT |
| [`ULTRACODE_BACKLOG.md`](ULTRACODE_BACKLOG.md) | Вектор исполнения §11 quick-wins (fan-out). | накопитель |

---

## Решения сессии 2026-06-04 (фиксируем, чтобы не переоткрывать)

1. **Телеметрия: делаем A, откладываем D.** Шаг 0 (A) чинит видимый баг «—» минимальным
   риском (замена `_StateDeltaEmitter`/`invokeMethod` → проверенный bridge кадров). D
   (snapshot-канал + `TelemetryViewModel` + вырезание реактивных биндингов) — здравая, но
   **преждевременная** цель: её обоснование (20 проц × 50 метрик × 10 вкладок) — масштаб,
   которого нет. Противоречит `priority_product_over_engine`. → **STOP после A**, D — за gate
   реального масштаба (появился 2-й реактивный потребитель ИЛИ замер показал боль двойного glob).
2. **A держит обе двери, D захлопывает StateChannel.** Поэтому: **принят A → transport-router-hub
   P3.2 (StateChannel) = deferred** до появления реактивного потребителя. Это снимает скрытый
   конфликт планов (D vs P3.2).
3. **telemetry-A и observability-control-plane — параллельно, НЕ серилизовать.** Ноль пересечения
   файлов (state_store/frontend vs logger/error/stats/channel_routing/config). Оба готовы до
   рискового S4/S5.
4. **observability нужен ДО S4/S5** (горячий путь кадров) — там hot-reload уровней и чистый
   `reconfigure()` реально окупаются. НЕ ради отладки телеметрии (тот баг ловили `print`, не
   логами — логгер у сломанных объектов не был провязан; см. comm-system §12 P0, «урок измерения»).
5. **Свернуть §11 CRM-мелочи в проход observability** — #16 (мёртвый Dispatcher в LoggerManager),
   #17 (два CRM-конфига), #18 (`AsyncSenderBuffer.flush` no-op). Те же файлы — не ходить дважды.
6. **Фундамент transport-router-hub P0–P2 обязан лечь в `main` ПЕРЕД S4/S5.** Иначе comm-system
   P1 переизобретёт `_deliver_by_targets`/addressing → конфликт веток.
7. **Один владелец kind-каналов = transport-router-hub P3/P4.** comm-system §12 P1 — это дубль;
   переразметить как ссылку, не как отдельную работу. Матрица §9 comm-system = acceptance-чеклист.
8. **Сквозная нумерация.** Коллизия `P2` (TRH = адресация done; CSA = авто-reply) врёт в
   трекинге. Префиксы: `TRH-Pn` / `CSA-Pn`.

---

## Порядок исполнения

```
S0 ✅DONE (telemetry)   self-publish-redesign (не Option A)  [FPS зелёный, qt-smoke ok]
S1 ✅частично (CRM)     §11 #16/17/18 закрыты; observability-план не написан
S3 ✅DONE (гигиена)     comm-system §11 quick-wins пп.1-22    [закрыто 2026-06-05]
        │
S2 (gate) ⬅СЕЙЧАС      merge ветки → main (303 коммита, FF)  [фундамент под движок]
        │
S4 (движок, после S2)  kind-каналы: TRH P3/P4            [= CSA P1; ОДИН владелец]
        │                    └─ P3.2 StateChannel = deferred (решение #2)
S5 (движок, поздно)    CSA P2/P3: авто-reply, undo, carve-out
```

### S0 — telemetry-A (продукт, видимый фикс) — **СТАРТ ЗДЕСЬ**
- **План:** [`telemetry-delivery-simplification.md`](telemetry-delivery-simplification.md), Шаг 0 = A.
- **Задачи:** 1.1 (reuse bridge + удалить `_StateDeltaEmitter`) → 1.2 (multi-subscriber bridge)
  → 2.1 (fail-loud) → 3.1 (воркеры hz → ProcessMonitor fps/latency) → 3.2 (system.health) → 4.1 (replay).
- **STOP после A.** D НЕ начинаем (решение #1).
- **Файлы:** `state_store_module/proxy/gui_state_proxy.py`, `frontend/process.py`, `bridge_impl.py`,
  `frontend/state/bindings.py`, `process_manager_module/monitor/process_monitor.py`, `worker_module`.
- **Приёмка (главная):** qt-mcp — `/run-proto` → вкладка «Процессы» → индикаторы ЗЕЛЁНЫЕ,
  FPS/Latency числа, «Активно: N» (N>0). pytest-qt недостаточно (memory `feedback_qt_mcp_smoke_verification`).
- **Worktree:** НЕТ — это приоритет, нужен живой qt-mcp smoke в основном дереве.
- **Ветка:** `feat/comm-system-target-architecture`.

### S1 — observability-control-plane + §11 CRM-уборка (движок-гигиена, параллельно S0)
- **План:** [`2026-06-03_observability-control-plane/plan.md`](2026-06-03_observability-control-plane/plan.md).
- **Минимум для debug-ценности:** Task 1.1 (vertical slice: `reconfigure()` + invalidate cache)
  + Task 3.3 (ConfigFileWatcher → live). Phase 2 (sink-реестр) и полная схема — по аппетиту, можно отложить.
- **Свернуть сюда §11:** #16, #17, #18 (те же CRM-файлы — решение #5).
- **Phase 4 (design-only):** привязать IPC-команду `config.reload`/`logger.sink.enable` к
  командному пути хаба (`router.send(command=…)` → handler → `reconfigure()`), НЕ новый механизм.
- **Файлы:** `channel_routing_module/core/*`, `logger_module`, `error_module/stats`, `config_module/tools/watcher.py`,
  `config_module/core/config.py`, прокидка в прототипе. **Ноль пересечения с S0.**
- **Worktree:** ДА — изолировать (`isolation: worktree`), чтобы не словить commit-race с S0
  (memory `feedback_parallel_agents_commit_race`: макс 2 без worktree; здесь S0 без, S1 в worktree).
- **Ветка:** `feat/observability-control-plane`.

### S2 — merge transport-router-hub P0–P2 → main (gate перед движком)
- Проверить, влит ли `refactor/transport-router-hub` (P0–P2: addressing + хаб-на-отправке) в `main`.
- Если нет — smoke (`/run-proto`, кадры идут, 0 ERROR) → merge. **Без этого S4/S5 конфликтуют** (решение #6).
- Сверить с S0/S1: после их merge — пересобрать ветки от свежего main.

### S3 — comm-system §11 quick-wins (мёртвый код, fan-out)
- **План:** [`ULTRACODE_BACKLOG.md`](ULTRACODE_BACKLOG.md) + [`comm-system §11`](comm-system-target-architecture.md).
- §11 пп. 1–4, 7, 8, 9, 11, 13, 14, 19 (нулевой риск) + критичные пп. 20–22 (потеря сообщений
  `_route_to_worker`, нарушение main-thread контракта). **Исключить:** #16/#17/#18 (ушли в S1),
  телеметрийные пункты (ушли в S0).
- **Кандидат на ultracode** (fan-out ≥4–5 независимых) — когда наберётся масса. Сейчас можно
  max-режимом по 1.
- **Worktree:** ДА если ultracode-залп.

### S4 — kind-каналы (движок, после S2) — ОДИН владелец
- **План:** [`transport-router-hub P3/P4`](2026-05-31_transport-router-hub/plan.md) (investigation-first).
- P3.1 FrameChannel + слияние 2× FrameShmMiddleware; **P3.2 StateChannel — DEFERRED** (решение #2);
  P3.3 EventChannel; P4 миграция отправителей + удаление обходов.
- **Acceptance-чеклист:** матрица §9 comm-system. Риск HIGH (горячий путь) — rollback-план CSA §12.
- comm-system §12 P1 здесь НЕ исполняется отдельно — это тот же набор (решение #7).

### S5 — CSA P2/P3 (поздно, обсудить)
- авто-reply по `request_id` в `receive()`; PM `_handle_process_command` → `reply_to_request`.
- undo: 4 фичи в `CommandDispatcherOrchestrator` (`undo_to`/`record`/RBAC-hook/audit); ActionBus из проводки.
- carve-out prototype→framework (CSA §15): `GuiStateBindings`, `EventBus`, `DataReceiverBridge`, резолвер `plugin_name`.

---

## Правки в планах (консолидация — отдельный docs(plans) проход)

Можно сделать заодно или после S0/S1:
1. comm-system → пометить «канон-справочник»; §12 P1 → ссылка на TRH P3/P4 (убрать дубль).
2. Сквозная нумерация TRH-Pn / CSA-Pn (убрать коллизию `P2`).
3. Зафиксировать развилку: «принят A; TRH P3.2 StateChannel = deferred» — в ОБОИХ планах.
4. telemetry-плану — явный STOP-gate после A + критерий входа в D.
5. observability Phase 4 — строка про командный путь хаба.
6. ULTRACODE_BACKLOG — отметить «= comm-system §11 P0», не дублировать с S0.

---

## Старт в новой сессии (точка входа)

1. **S0 Task 1.1** (`telemetry-delivery-simplification.md`, Senior+/teamlead): reuse bridge для
   state-дельт + удалить `_StateDeltaEmitter`. Vertical slice — доказывает контур одним qt-mcp smoke.
2. Параллельно (worktree) — **S1 Task 1.1** observability vertical slice (`reconfigure()` + invalidate cache).
3. Перед движком — **S2** проверить merge TRH P0–P2 в main.

> Каждый коммит: Conventional Commits + `Why:` + `Layer:` + `Refs: plans/<slug>.md`.
> S0 → `Refs: plans/telemetry-delivery-simplification.md`; S1 → `Refs: plans/2026-06-03_observability-control-plane/phase-N.md`.

## Ветки

- S0 → `feat/comm-system-target-architecture` (основное дерево).
- S1 → `feat/observability-control-plane` (worktree-изоляция при параллели с S0).
- S2 → merge `refactor/transport-router-hub` в `main`, затем rebase веток.
- S4/S5 → продолжение `refactor/transport-router-hub` / `feat/comm-system-target-architecture`.
