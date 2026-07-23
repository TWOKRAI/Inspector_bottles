# Живая приёмка Фазы 4 — truth-holes-closure (2026-07-23)

**Рецепт:** `webcam_sketch`, флаги `FW_STATE_COALESCE=1 FW_STATE_QUEUE=1 BACKEND_CTL=1`, 8 процессов.
**План:** [`plans/truth-holes-closure.md`](../../plans/truth-holes-closure.md), Фаза 4 (задачи 4.1–4.5).
**Как проверялось:** свежим процессом-драйвером (`BackendDriver`), а НЕ через запущенный
MCP-сервер — он держит код на момент старта и новых ручек не знает. Это ровно то ограничение,
которое Task 4.5 и записал в доки; здесь оно подтвердилось на первом же шаге.

## Task 4.1 — `introspect.telemetry` (readback gate)

| Что | Живое значение |
|---|---|
| `gate_active` у `lines` на boot | **false** + честная `note` «gate выключен — все метрики каждый тик (нет секции telemetry.publish)» |
| `gated_metrics` | `[fps, latency_ms, effective_hz, cycle_duration_ms, shm]` — каталог против опечаток |
| `throttle_rules` у ProcessManager | **7 правил**, все `0.05` с (`processes.**.state.fps`, `…latency_ms`, `…uptime`, `…frame_count`, `…drops`, `…workers.*.effective_hz`, `…workers.*.cycle_duration_ms`) |

Вторая плоскость (central-троттл) перестала быть невидимой: раньше её значения нельзя было
прочитать вообще — только вывести из того, с какой частотой метрика доходит до дерева.

## Task 4.2 — доставка ≠ применение

Пара на одной и той же метрике `lines.fps`:

| Шаг | Результат |
|---|---|
| `telemetry_set(fps, enabled=false, verify=true)` | `semantics="delivered"`, `reached=1`, **`verified_effect=true`**, `observed={enabled: false, interval_sec: 1.0}` |
| `telemetry_set(fps, enabled=true, verify=true)` | **`verified_effect=true`**, `observed={enabled: true, interval_sec: 1.0}` |
| `telemetry_set(latency, …)` — опечатка (`latency_ms`) | **`verified_effect=false`**, причина: «метрика не входит в GATED_METRICS — правило записано, но ничего не гейтит» |

Ключевое: у всех трёх вызовов серверный охват одинаков (`reached=1` — доставлено), и только
readback различает применённое от бесполезного. Раньше третий случай был неотличим от первых двух.

## Task 4.3 — «кто душит очередь X» + потери в интроспекции

`introspect_router_stats("ProcessManager")` на живой системе:

| Сигнал | Значение |
|---|---|
| Очередей под учётом | **9** |
| `gui_state` — топ-отправитель | **`StateStore`, put=901**, lost=0 ← вот кто наполняет state-очередь |
| `gui_system` / `lines_system` / прочие `*_system` | топ-отправитель **`ProcessManager`**, put 31–35, lost=0 |
| `queue_never_drop_loss_total` | **0** (при флагах Ф1 безвозвратных потерь нет) |
| `queue_system_evict_blocked` | **0** |
| `queue_data_evicted` | **106** — drop_oldest штатно роняет старое вместо блокировки |

Контраст с baseline'ом Фазы 1 (тот же рецепт БЕЗ флагов): тогда `gui_system` был 100/100,
`system_evict_blocked` 1466, доставка 15%. Теперь на вопрос «кто душит» есть прямой ответ
с именем отправителя, а не только «очередь полна».

## Task 4.4 — `process_restart_verified`

| Что | Значение |
|---|---|
| Рестарт `lines` | `restarted=true`, **pid 4712 → 22124**, `instance_restarts` **0 → 1**, `alive=true`, `elapsed` **6.42 с** |
| Ответ самой команды | `success=true` — сохранён как **справка**, вердикт вынесен по pid |
| Несуществующий процесс `linez` | `restarted=false` + «не найден в supervision-снимке», **ни одной разрушающей команды не отправлено** |
| Readback нового инстанса | `introspect.telemetry` отвечает (`success=true`), `gate_active=false` — новый инстанс взял boot-конфиг (адресные правки не персистятся, поведение PM by design) |

## Итог

Все четыре инструментальные задачи Фазы 4 доказаны на живой системе, не на моках.
Задача 4.5 (доки) подтверждена самим ходом прогона: MCP-сервер действительно не знал новых
ручек, и приёмка пошла через свежий процесс — как теперь и написано в README.
