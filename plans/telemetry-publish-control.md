# План: telemetry-publish-control — управляемая публикация телеметрии (частота + вкл/выкл)

- **Slug:** telemetry-publish-control
- **Дата:** 2026-07-16
- **Ветка:** feat/telemetry-publish-control (ответвить от feat/gui-telemetry-read-model после её закрытия)
- **Статус:** DRAFT (согласован дизайн: publisher-gate primary + центральный троттл вторым — решение владельца 2026-07-16)
- **Продолжает:** [`gui-telemetry-read-model.md`](gui-telemetry-read-model.md) — тот сделал дешёвое GUI-**чтение**;
  этот делает управляемую **запись/публикацию** («публиковать ровно столько, сколько надо»).

---

## Context (диагноз по коду, замерено Explore-агентом 2026-07-16)

Владелец: хочу задавать **частоту опроса per-параметр/группа** и **вкл/выкл**, менять **в реальном времени
через конфиг ИЛИ через backend_ctl**, чтобы не грузить систему; управлять «через statistics manager».
Разведка вскрыла три факта, определяющих дизайн:

1. **Текущий per-параметр троттл — de-facto no-op на телеметрию.** `build_throttle_rules()`
   (`multiprocess_prototype/backend/state/manager_setup.py:9`) даёт `{glob → min_interval}`, но
   `ThrottleMiddleware.before_merge` НЕ переопределён (`state_store_module/middleware/throttle.py`) —
   наследует пропускающий дефолт. А телеметрия публикуется через `proxy.merge` (heartbeat), значит правила
   `processes.**.state.fps: 1.0` не действуют. Реальный rate-limit сейчас — только период heartbeat (5 с,
   глобально на процесс). **«Частота per-параметр» пока фикция.**
2. **Телеметрия идёт не через StatsManager.** `StatsManager` (`statistics_module`) пишет в локальные каналы,
   remote-транспорта в дерево нет (docstring). Публикация fps/latency/hz — через self-publish heartbeat
   (`process_module/heartbeat/process_heartbeat.py::_publish_metrics_to_tree` → `build_worker_telemetry`
   → `proxy.merge`). Значит «управлять через stats manager» = разместить **плоскость управления**
   (тумблеры/конфиг) в stats/observability-плоскости, а **гейтить публикацию — у источника (heartbeat)**.
3. **Две плоскости управления** (развести явно):
   - **Publisher-gate** (в каждом процессе): что вообще СЧИТАТЬ и публиковать и как часто. Выключенная
     метрика не считается → максимум «не грузить». ← **ГЛАВНЫЙ рычаг** (выбор владельца).
   - **Центральный троттл** (в оркестраторе, `StateStoreManager` middleware): rate-limit записи в дерево/IPC.
     ← **вторым**, как страховка IPC. Требует фикса (merge-путь + рантайм-мутабельность).

## Принцип (кандидат в локальный/глобальный ADR)

**«Ошибки — всегда; логи/статистика/телеметрия — управляемо (вкл/выкл + частота), декларативно из конфига
и в рантайме, у источника».** Framework даёт контракт и механизм; приложение задаёт значения рецептом.

- **Framework-first:** контракт публикации (schema), publisher-gate, рантайм-команды, fan-out — во фреймворке
  (`process_module`/`state_store_module`/observability/backend_ctl). Прототип лишь конфигурирует (recipe/system.yaml).
- **Errors always-on** (инвариант, сохраняем): ошибки не выключаются конфигом.
- **Идемпотентность:** один и тот же путь применения конфига для boot / file-watch / IPC `config.reload` / backend_ctl.
- **Декларативность:** дефолты + per-process override; в рантайме — дельты поверх.

---

## Целевой контракт конфига (framework schema, черновик)

Новая секция (framework `TelemetryPublishConfig`, `data_schema`), значения — в `system.yaml` (глобальные
дефолты) и per-process в `blueprint.processes[].telemetry` (override):

```yaml
telemetry:
  publish:
    default_interval_sec: 1.0          # дефолтная частота публикации метрики
    metrics:                            # per-метрика/группа override (по суффиксу пути)
      fps:               {enabled: true,  interval_sec: 1.0}
      latency_ms:        {enabled: true,  interval_sec: 1.0}
      effective_hz:      {enabled: true,  interval_sec: 1.0}
      cycle_duration_ms: {enabled: false}                      # тяжёлая — opt-in
      shm:               {enabled: true,  interval_sec: 5.0}
    # errors — всегда, не конфигурируется
  throttle:                             # центральный store-троттл (вторая плоскость, IPC-страховка)
    "processes.**.state.fps": 1.0
    "processes.**.workers.*.effective_hz": 1.0
```

Рантайм-дельта (через `config.reload` inline-override ИЛИ backend_ctl `telemetry.set`):
`{process?: <имя|all>, metric: <имя|группа>, enabled?: bool, interval_sec?: float, plane?: publisher|throttle}`.

---

## Фазы

### Фаза 0 — Фундамент: починить и раскрыть троттл (framework, небольшая, разблокирует всё)

#### Task 0.1 — ThrottleMiddleware: merge-путь + рантайм-мутабельность ✅ DONE
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework
**Статус:** ✅ DONE — per-leaf `before_merge` + `set_rules`/`update_rule`/`remove_rule` + `pipeline.get`/`get_middleware`; ADR-SS-018; тесты `test_throttle.py` (40) зелёные.
**Goal:** троттл реально применяется к телеметрии (merge) и правила меняются в рантайме.
**Files:** `state_store_module/middleware/throttle.py`, `.../manager/state_store_manager.py`,
  `.../middleware/base.py` (пайплайн — доступ по имени), tests.
**Steps:** 1. Переопределить `ThrottleMiddleware.before_merge` (rate-limit per-path как `before_set`; учесть,
  что merge несёт поддерево — троттлить по корню правила/пути). 2. Добавить `set_rules(rules)`/`update_rule(pattern, interval)`
  (+ потокобезопасно). 3. `MiddlewarePipeline.get(name)` / `StateStoreManager.get_middleware(name)` для доступа
  к живому `ThrottleMiddleware`. 4. Не ломать `before_set`-поведение и существующие тесты `test_throttle.py`.
**Acceptance:** тест: merge-дельта троттлится по правилу (2 быстрых merge → 1 проходит); `update_rule` меняет
  интервал живьём (spy по времени); `before_set` не регрессировал.

### Фаза 1 — Publisher-gate: per-метрика вкл/выкл + частота (ГЛАВНЫЙ рычаг, framework)

#### Task 1.1 — Контракт `TelemetryPublishConfig` (schema) ✅ DONE
**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer:** framework
**Статус:** ✅ DONE — `process_module/configs/telemetry_publish_config.py` (`MetricRule` + `TelemetryPublishConfig`, `@register_schema`); `resolve(metric)->(enabled, interval)` с наследованием default; `from_dict`/`to_dict` round-trip; экспорт в `configs/__init__.py` + ленивый в `process_module/__init__.py`; тесты `test_telemetry_publish_config.py`.
**Goal:** декларативный контракт публикации (framework schema, Dict-at-Boundary).
**Files:** новый `process_module/configs/telemetry_publish_config.py` (`@register_schema`), `interfaces.py`, tests.
**Steps:** 1. `TelemetryPublishConfig(SchemaBase)`: `default_interval_sec`, `metrics: dict[str, MetricRule]`
  (`enabled: bool`, `interval_sec: float | None`). 2. Хелпер `resolve(metric_suffix) -> (enabled, interval)`
  с дефолтами. 3. `expand`/merge global+per-process.
**Acceptance:** резолв метрики с дефолтом/override; неизвестная метрика → default enabled; errors не конфигурируемы.

#### Task 1.2 — Publisher-gate в heartbeat ✅ DONE
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework
**Статус:** ✅ DONE — `heartbeat/telemetry.py`: `build_worker_telemetry` принял `allowed_metrics` (выключенная метрика не считается/не в payload; `status` вне гейта); новый `TelemetryGate` (per-метрика `_next_due` rate-limit, паттерн `io_peek`). `heartbeat/process_heartbeat.py`: `_build_telemetry_gate()` из `get_config("telemetry").publish` (нет секции → None → всё как раньше), `_loop` считает `allowed` один раз и пробрасывает в `_publish_metrics_to_tree` + `_publish_router_shm_stats_to_tree` (shm-гейт). health/errors/status — вне гейта. Тесты `test_telemetry_gate.py`.
**Goal:** процесс не считает/не публикует выключенные метрики и уважает per-метрика частоту.
**Files:** `process_module/heartbeat/process_heartbeat.py` (`_publish_metrics_to_tree`),
  `heartbeat/telemetry.py` (`build_worker_telemetry` — принять фильтр enabled-метрик), rate-limiter per-метрика
  (переиспользовать паттерн `process_module/plugins/io_peek.py` — `_next_due`), tests.
**Steps:** 1. Пробросить `TelemetryPublishConfig` процесса в heartbeat (`get_config("telemetry")`). 2.
  `build_worker_telemetry` фильтрует метрики по enabled; выключенная — не считается (не звать `cycle_metrics` для неё,
  если возможно) и не кладётся в payload. 3. Per-метрика/группа частота: publisher-side `_next_due[metric]` — не
  публиковать чаще interval_sec (в пределах тика heartbeat). 4. Errors/status — всегда.
**Acceptance:** тест: выключенная метрика отсутствует в payload и её тайминг не считается; per-метрика interval
  прореживает публикацию; включённая по дефолту работает как прежде.

#### Task 1.3 — Конфиг-плумбинг до ребёнка ✅ DONE
**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer:** mixed
**Статус:** ✅ DONE — `SystemConfig.telemetry` (`TelemetrySection.publish: TelemetryPublishConfig | None = None`,
  `throttle` — задел Фазы 2); `BlueprintAssembler` читает per-process `blueprint.processes[].telemetry` из СЫРОГО
  dict (до `model_validate`, т.к. `ProcessConfig` не объявляет typed-поле) и мержит (`deep_merge`) поверх
  глобального `telemetry_dict` конструктора → `proc_dict["config"]["telemetry"] = {"publish": ...}` — ТОЛЬКО
  когда задано хоть где-то (backward-compat: нет секции нигде → ключ `telemetry` отсутствует у ВСЕХ процессов
  → `TelemetryGate` не строится, PC 1.2). `launch.py` прокидывает `sys_config.telemetry.publish.model_dump()`
  (или `None`) в assembler как `telemetry_dict`. `system.yaml` — закомментированный пример, дефолт не активен.
  Golden-снапшоты (`test_build_characterization.py`) обновлены осознанно (`sys_config.telemetry` — новый ключ,
  `publish: null`; proc_dict'ы рецептов НЕ изменились — проверено diff'ом). 31 новый тест (`test_telemetry_
  section.py` + `TestTelemetryOverlay`/интеграция с `ProcessConfigHandler.get_config` в `test_assembler.py`).
  **Известный пробел (вне Files-скоупа задачи):** `orchestrator_hooks.py::configure_topology_engine` (hot-swap
  путь) строит свой `BlueprintAssembler` БЕЗ `telemetry_dict` — глобальный default из `system.yaml` не доедет
  до процессов, пересобранных через runtime-замену рецепта (per-process override в самом рецепте — доедет,
  т.к. читается assembler'ом из raw blueprint независимо). Follow-up для Фазы 3 или отдельный тикет.
**Goal:** секция `telemetry` доезжает до каждого процесса.
**Files:** `backend/config/schemas.py` (`SystemConfig.telemetry`), `backend/assembly/assembler.py`
  (overlay per-process, как observability), `backend/launch.py`, `system.yaml`, пример в рецепте, tests.
**Acceptance:** per-process override поверх global default доходит до `get_config("telemetry")`; характеризация build.

### Фаза 2 — Config-driven центральный троттл (заменить хардкод)

#### Task 2.1 — `build_throttle_rules` из конфига
**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer:** mixed
**Goal:** правила центрального троттла — из `telemetry.throttle` конфига, не хардкод.
**Files:** `backend/state/manager_setup.py` (читать из sys_config), `backend/launch.py:321,364`, tests.
**Steps:** 1. `build_throttle_rules(sys_config)` — из `telemetry.throttle` (fallback на прежние дефолты для
  совместимости). 2. Правила → `orchestrator_config["state_throttle_rules"]` (существующий канал). Теперь
  троттл config-driven + (Фаза 0) рантайм-мутабельный.
**Acceptance:** правила из конфига применяются; пустой конфиг → дефолты; характеризация.

### Фаза 3 — Рантайм-управление: config hot-reload + backend_ctl + fan-out (framework)

#### Task 3.1 — Hot-reload телеметрии единым путём
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework
**Goal:** изменение `telemetry`-секции применяется в рантайме тем же путём, что observability.
**Files:** расширить `ObservabilityConfig`/новую секцию + `observability_reload.py::apply_observability_reconfigure`
  (добавить 4-го получателя: publisher-gate процесса и/или центральный троттл оркестратора), `config_module` watcher, tests.
**Steps:** 1. `apply_telemetry_reconfigure(section, *, heartbeat/publisher_gate, store_throttle)` — идемпотентно.
  2. Подключить к file-watch (оркестратор) и к `config.reload` IPC (`builtin_commands.py::_cmd_config_reload` —
  принять `data["telemetry"]`). 3. Меняет живой publisher-gate (в процессе) и/или `ThrottleMiddleware.update_rule`
  (в оркестраторе).
**Acceptance:** тест: inline `config.reload` с `telemetry`-секцией → метрика выключилась/частота сменилась без рестарта.

#### Task 3.2 — backend_ctl команда `telemetry.*`
**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer:** framework
**Goal:** управление из backend_ctl (и из GUI через тот же router-путь).
**Files:** `process_module/commands/builtin_commands.py` (новый `_register_telemetry_commands`: `telemetry.set`
  {metric, enabled?, interval_sec?, plane?}), `backend_ctl/driver.py` (обёртка `telemetry_set(process, ...)`),
  `introspect.handlers`-видимость, tests.
**Acceptance:** тест: команда меняет publisher-gate/троттл адресата; отсутствие приёмника видно через introspect.

#### Task 3.3 — Fan-out на всех детей
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework
**Goal:** применить telemetry-конфиг ко ВСЕМ процессам одной командой (закрыть пробел ADR-CRM-006 Phase 4 для этого кейса).
**Files:** `process_manager_module/process/process_manager_process.py` (переиспользовать `comm.broadcast` /
  `_broadcast_routing_refresh`-путь либо цикл `send_message` по `get_process_names()`), driver fan-out, tests.
**Acceptance:** тест: `telemetry.set process=all ...` долетает до всех живых детей (broadcast/relay), включая после hot-swap.

### Фаза 4 — GUI-контролы + docs (прототип, переиспользует read-model)

#### Task 4.1 — GUI: тумблеры/частота метрик
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** prototype
**Goal:** в панели процесса/observability — вкл/выкл метрик + частота; запись через command-result-bridge (router),
  чтение статуса — из read-model (gui-telemetry-read-model). Контролы переиспустимы (constructor-виджеты).
**Acceptance:** qt-smoke: тумблер выключает метрику (график перестаёт расти), частота меняется live.

#### Task 4.2 — ADR + memory
**Level:** Middle (Sonnet) · **Assignee:** tech-writer · **Layer:** docs
**Goal:** ADR «управляемая публикация: errors always-on, logs/stats/telemetry — вкл/выкл+частота у источника,
  рантайм»; обновить memory (реверс части `feedback_all_components_base_manager`? — нет; связать
  `[[project_observability_control_plane]]`, `[[project_telemetry_self_publish]]`). `scripts.sync`.

---

## Framework-first карта (что где живёт)

| Слой | Что | Файлы |
|------|-----|-------|
| **framework** | контракт `TelemetryPublishConfig`, publisher-gate, ThrottleMiddleware-фикс, hot-reload, backend_ctl-команды, fan-out | `process_module`, `state_store_module`, `process_manager_module`, `backend_ctl` |
| **prototype** | значения конфига (system.yaml/recipe), GUI-контролы | `backend/config`, `recipes/*`, `frontend/widgets/tabs/*` |

Любое приложение на фреймворке получает управляемую публикацию даром — задаёт лишь значения.

## Риски

| Риск | Митигация |
|------|-----------|
| Троттл no-op на merge (найдено) | Фаза 0.1 переопределяет `before_merge` — иначе весь план бесполезен; закрыть ПЕРВОЙ |
| Две плоскости путают пользователя | Явное поле `plane: publisher|throttle`; дефолт — publisher (главный рычаг) |
| Fan-out отсутствует | Фаза 3.3 переиспользует `comm.broadcast`/`process.relay`; адресный relay после hot-swap |
| Выключение метрики ломает GUI-график | GUI деградирует gracefully (read-model: нет данных → пусто), уже так |
| «через stats manager» ≠ реальный поток | Плоскость управления в stats/observability-конфиге; данные — heartbeat. Задокументировать в ADR |
| Регресс телеметрии | Характеризационные тесты payload heartbeat до/после; errors always-on под тестом |

## Verification (весь план)
1. Выключенная метрика: не в payload, тайминг не считается (юнит) + график в GUI пуст (qt-smoke).
2. Частота per-метрика: публикация прореживается (замер) через конфиг И через backend_ctl.
3. Hot-reload: `config.reload`/file-watch/backend_ctl меняют вкл-выкл/частоту без рестарта; fan-out на всех детей.
4. Центральный троттл: merge-путь реально троттлится; правила из конфига; рантайм-мутация.
5. `scripts/run_framework_tests.py` + прототип зелёные; sentrux не хуже baseline; errors always-on.
