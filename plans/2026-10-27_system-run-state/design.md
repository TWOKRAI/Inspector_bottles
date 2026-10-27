# Design: состояние работы системы — «готов → ЗАПУСТИТЬ → работает → ОСТАНОВИТЬ»

Спецификация к [`plan.md`](plan.md). Факты — чтение `main` `3aa2c0b8f` (2026-10-27), индекс qex устарел — всё ниже
найдено `git grep`/чтением; номера строк сверять перед правкой (файлы PM у полосы Ф, они сдвинутся после 1.10/1.11).

## 1. Требование владельца (дословно, 2026-10-27)

1. «при старте РЕЦЕПТ не должен запускаться. Он прогружается, но для полноценной работы нужно нажать кнопку ЗАПУСТИТЬ.
   И есть кнопка остановить. Сейчас неправильно что при запуске рецепт сразу активен. Должна система полностью поднять
   все узлы и дать готовность после чего разрешать нажимать кнопку ЗАПУСКА».
2. Уточнение (через координатора): «сначала получить от каждого узла процесса и модуля состояние готовности (по рецепту),
   и когда все готовы — давать разрешение на запуск». Требования, не варианты:
   - R1 иерархическая самоотчётная готовность: плагин/устройство → процесс (все его плагины) → система (все процессы,
     **которых требует рецепт**);
   - R2 молчание = НЕ готов (liveness-фолбэк барьера для гейта START не годится);
   - R3 готовность непрерывна: потеря во время работы → не готов / авария, реакция определена;
   - R4 каждое «не готов» несёт именованные причины (узел + причина) в state; находки preflight C-55b — такие причины.
3. «подтягивай промышленные стандарты» — раздел §9.

## 2. Что есть в коде (факты)

| механизм | где | что даёт | годится? |
|---|---|---|---|
| Барьер готовности процессов | `process_manager_module/process/process_manager_process.py:4211` `_wait_processes_ready`; boot `:4311` `_wait_boot_ready`; волны `:3518-3555`; ADR `process_manager_module/DECISIONS.md:131` | per-process `mp.Event`, ребёнок взводит в конце `run()` (`process_module/core/process_module.py:1305,1392`) | **как гейт START — нет:** на дедлайне живой без события → `True` («liveness-fallback», DECISIONS.md:131; boot идёт дальше с WARNING `:4330-4333`). Одноразовый, не непрерывный |
| Событие готовности системы | `launcher/system_launcher.py:111` создаёт, PM взводит `_announce_ready` (`process_manager_process.py:342-355`); ребёнку — `_sources_ready_event` (`runner/process_runner.py:411-412`, ADR-PMM-034 DECISIONS.md:1596) | источник ждёт его до первого `produce()` | **образец проводки** `mp.Event` PM → ребёнок; само событие не годится: срок preroll 10 с, потом источник стартует (ADR-PMM-034 п.2) и событие не снимается |
| Пауза источника | `process_module/generic/source_producer.py:127-147` | `run_loop` на `pause_event.is_set()` не зовёт `produce()`, сбрасывает темп | **да** — тот же цикл проверит событие работы |
| Хуки плагина `pause`/`resume`, состояние `PAUSED` | `process_module/plugins/base.py:88-94` (`PAUSED` «ресурсы удерживаются»), `:1540-1551`, `_do_pause/_do_resume` `:1602-1614` | пустые умолчания, нужная форма (как C-55b/C-60) | **да.** Живых вызовов нет (`git grep _do_pause` — только `base.py` и `plugin_test_bench.py:99,104`): публичный путь без вызывающего = контракт (принцип 3), получает первого потребителя |
| `worker.pause_all` / `process.pause` | `process_module/commands/builtin_commands.py:290-333`; PM `:569`, `:3959-3964` | пауза всех не-системных воркеров процесса | **нет как механизм** — грубо: паузит и воркеры устройств, и телеметрию плагинов; не знает плагинов |
| Здоровье процесса | `process_module/health/state.py` (`ctx.health`), схема `health/schema.py:37-53` (`ok/degraded/failed`), публикация `publish_health` `state.py:677` через heartbeat-прокси в `processes.<n>.health.*` | непрерывный самоотчёт ребёнка в state-дерево PM без нового канала | **образец канала.** Готовность — другая ось (камера ещё не открыта ≠ деградация), отдельные листья тем же путём |
| StateStore | в процессе PM: `app_module/orchestrator.py:377-420`; публикация PM — `_state_op("handle_state_set", {"path": ...})` (`process_manager_process.py:1876-1880`, `system.switch.unstoppable`) | GUI получает дельты | **да.** Но state-plane опционален (minimal_app без него, `orchestrator.py:388-392`) → нужна ещё команда-снимок |
| Активация рецепта | `multiprocess_framework/modules/recipe/service.py:122-129` (`recipe.activate`); проводка `multiprocess_prototype/orchestrator.py:78-90` (исполнитель `pm-lifecycle-submit`), `build_recipe_service` `:146-187` → `pm._cmd_topology_apply` | смена топологии | рецепт = топология; boot поднимает активный рецепт (`ManifestStore.pipeline`) и плагины сразу `READY → RUNNING` (`plugin_orchestrator.py:197`) — это и есть «сразу активен» |
| Preflight C-55b (полоса С, не в main) | бриф `plans/word-layout/tasks/C-55b.md` (коммит `101d49607`) | классовый хук `preflight(config) -> list[PreflightFinding]` (`error/warning/info`), сборщик в `plugins/manifest.py`, вызов в `SystemLauncher.run()/start()` до спавна; `error` → `PreflightFailed`, спавна нет | **источник причин R4** после слияния; сегодня boot с `error` не стартует вовсе |
| Состояния/команды работы системы | `git grep -n -i "run_state\|system_state\|start_work\|stop_work\|system\.start\|system\.run"` по `*.py` — 0 совпадений в framework/prototype | — | нет; подтверждено |

Тесты, которые держат liveness-фолбэк (R2 не должен их сломать):
`process_manager_module/tests/test_apply_topology.py:492` `test_liveness_fallback_when_no_event`;
`tests/test_startup_voices_windowed_acceptance.py:133,148,169` (голос фолбэка INFO → WARNING);
`tests/test_liveness_fallback_series_guards.py:120`; `process_module/tests/test_t54_*` (preroll ADR-PMM-034).

## 3. Решение (рекомендация менеджера; архитектуру утверждает `cto`, Task 0.1)

### 3.1. Кто владеет и где видно

- **Владелец машины состояний — PM** (`process_manager_module`): он поднимает топологию рецепта, держит барьер,
  `system.shutdown`, `topology.apply`, StateStore. Не `recipe` (сервис поверх PM, его нет без `recipes:` в манифесте),
  не `app_module` (это подкласс PM для приложений — framework должен уметь сам, принцип 1). Чистая логика переходов —
  новый файл `process_manager_module/process/run_state.py` (функция/класс без IO, юнит-тесты без процессов); проводка —
  в `process_manager_process.py`.
- **Публикация:** `system.run.state` (строка состояния), `system.run.reasons` (список причин §3.3),
  `system.run.since` (время входа), `system.run.last_fault` (последняя авария с причинами), через `_state_op`.
- **Снимок по команде:** `system.run.status` (класс R — на приёмном потоке) отдаёт то же dict'ом — для `backend_ctl` и
  приложений без state-plane.
- **Команды:** `system.run.start`, `system.run.stop` — к PM. GUI, пульт (строки 15–17), `backend_ctl` — только
  вызывающие (принцип 6). Имя `system.stop` не берём: путается с `system.shutdown`.

### 3.2. Состояния (подмножество PackML, §9.1)

| наше (state) | по-русски (GUI) | PackML | вход | START | STOP |
|---|---|---|---|---|---|
| `booting` | поднимается | Resetting | boot; `topology.apply`/`recipe.activate` | отказ `not_ready` | no-op |
| `not_ready` | не готов | Stopped (с причинами) | не все требуемые узлы готовы | отказ, ответ несёт причины | no-op |
| `ready` | готов | Idle | все требуемые узлы готовы, нет `failure` | → `running` | no-op |
| `running` | работает | Execute | START из `ready` | no-op (`already_running`) | → `stopping` |
| `stopping` | останавливается | Stopping | STOP; по аварии — сразу, без шагов «домой» | отказ | no-op |
| `fault` | авария | Aborted | потеря готовности в `running` (R3) | отказ | no-op; выход сам, см. ниже |
| `shutting_down` | завершение | — | `system.shutdown` | отказ | отказ |

«Загружен» владельца = момент до спавна; отдельным состоянием не публикуется (никто не успеет его увидеть: state-plane
поднимается вместе с PM) — **вопрос владельцу В1**. `stopping` после завершения → `ready`/`not_ready` по текущей
готовности. `fault` → по завершении аварийной остановки и снятии причин → `not_ready`/`ready`; `last_fault` остаётся
до следующего START (подтверждение = нажатие START, ISA-18.2, §9.5) — **В4**.

### 3.3. Готовность (R1, R2, R4)

**Причина** — dict: `{"node": "<процесс>[.<плагин>]", "severity": "failure|check_function|out_of_spec|maintenance",
"reason": "<текст>", "source": "readiness|preflight|liveness|report"}`. Шкала — NAMUR NE 107 (§9.2). START блокирует
только `failure` (и `check_function` — **вопрос CTO К3**).

**Уровень плагина.** Новый необязательный метод `ProcessModulePlugin.readiness(self, ctx) -> list[dict]` (пустой список
= готов), форма как у C-55b/C-60: метод с пустым умолчанием, без реестра. Контракт: быстро (без IO, читает своё
состояние — «камера открыта», «модель загружена», «робот подключён»), не бросает (исключение → причина `failure`
«readiness() упал: …»). Плагины без метода — готовы, как только `RUNNING`/`PAUSED`.

**Уровень процесса.** Ребёнок на такте heartbeat (тот же прокси, что `publish_health`, `health/state.py:677`) пишет
`processes.<n>.readiness = {"ready": bool, "reasons": [...], "paused": bool, "updated_at": t}`; `ready` = все плагины
готовы и `run()` дошёл до `_announce_ready`. `paused` = все плагины в `PAUSED` (подтверждение STOP, §3.5).

**Уровень системы (PM).** Требуемый набор = процессы применённой топологии рецепта (то, что PM уже считает текущим
после `topology.apply`/boot). Для каждого: нет листа `readiness` или `updated_at` старше `3 × heartbeat_interval` →
причина `failure` `source: liveness` «нет отчёта о готовности» (**молчание = не готов**, R2); процесс мёртв → `failure`
«процесс не жив»; иначе — его причины. Оценка непрерывная — на такте монитора PM (существующий поток монитора), плюс
сразу при START.

**Почему отдельный сигнал, а не правка барьера.** Барьер (`_wait_processes_ready`) обслуживает boot-волны, switch и
restart; liveness-фолбэк там сознателен (медленный ребёнок не роняет boot, DECISIONS.md:131) и закреплён тестами §2.
Гейт START строится на другом сигнале (лист `readiness`) и барьер не меняет. Плата: два понятия «готов» — «процесс
поднялся» (барьер) и «узел готов к работе» (гейт); различие пишется в ADR. Вариант «сделать барьер строгим» отвергнут:
ломает boot с медленной ML-моделью и 4 файла тестов.

**Preflight C-55b → причины (Task 1.6).** При включённом гейте работы (§3.6) `error` preflight не прерывает boot, а
передаётся PM в конфиге (dict) и становится причиной `failure` `source: preflight` до перезапуска/смены рецепта;
`warning` → `out_of_spec`, `info` → `maintenance` (не блокируют). Гейт выключен → поведение C-55b (отказ до спавна) не
меняется. `recipe.activate` с `error` — отказ, как в C-55b.3: старый рецепт остаётся (**В5**).

### 3.4. Что делает START / STOP с плагинами и данными

Механизм — **один `mp.Event` работы на систему** (`run_event`), проводка как у ADR-PMM-034, но создаёт его PM (он
спавнит детей; launcher не трогаем):

- PM → `ProcessRegistry` → kwargs `Process` → `run_process_function(..., run_event=...)` → атрибут ребёнка →
  `SourceProducer`: цикл `run_loop` не зовёт `produce()`, пока событие снято (как ветка `pause_event`
  `source_producer.py:144-147`), **без срока** (в отличие от preroll).
- Ребёнок держит маленький системный воркер-наблюдатель события: фронт «взведено» → `_do_resume` всех плагинов;
  фронт «снято» → `_do_pause` всех плагинов; после подъёма плагинов, до `_announce_ready`, при снятом событии — сразу
  `_do_pause` (плагины в `PAUSED`, ресурсы удержаны). Это первый живой вызывающий `pause/resume` — новых хуков нет.
- Рестарт ребёнка в `running` — событие наследуется взведённым, ребёнок поднимается сразу в работу; гонок команд нет
  (событие, а не IPC-рассылка, которую ребёнок без обработчика уронил бы — класс гонки C-57).

**Работает в `ready`/`not_ready`:** процессы, heartbeat, команды, state, телеметрия, логи, связь с устройствами
(device_hub держит соединение — иначе готовность «робот подключён» не проверить), веб/GUI-серверы. **Не работает:**
кадры источников (поэтому и вся обработка, и задания роботу). Превью камеры в GUI в `ready` — **В2** (рекомендация:
нет в 1.0; позже — флаг источника `run_gated: false`).

Варианты, отвергнутые для механизма:

| вариант | минус |
|---|---|
| Только IPC-рассылка `plugins.pause_all` детям | рестарт/поздний ребёнок не знает состояния; гонка «команда до обработчика» (C-57); подтверждение — отдельный канал |
| `worker.pause_all` | паузит воркеры устройств и телеметрию; плагины не узнают |
| Гейтить в каждом плагине по своему флагу | N реализаций одного и того же; принцип 4 |

### 3.5. Последовательность STOP и аварии (IEC 60204-1, §9.3)

- **STOP (оператор)** = останов категории 1/2: `stopping` → шаги `pre_stop` (точка из `gui-graceful-close` Task 1.4,
  `pre_stop.py`, источник — конфиг PM/рецепт; «домой» робота — шаг T5.3e) → снять `run_event` → ждать `paused: true`
  у всех требуемых процессов, срок `run_stop_timeout_s` (умолчание 10 с) → `ready`/`not_ready`. Срок истёк →
  `not_ready` с причиной `failure` «<процесс> не подтвердил остановку». Лента: хук `pause()` плагина ленты (ПЧ) — стоп
  ленты (Task 2.2).
- **Авария (потеря готовности в `running`)** — реакцию определяет framework одинаково для всех: `fault` → снять
  `run_event` **сразу**, шаги `pre_stop` («домой») пропускаются (как `force` в gui-graceful-close 1.4) → ждать
  `paused` → `last_fault` = причины. Робот: хук `pause()` его плагина = стоп движения на месте (кат. 2), не «домой»
  (**В3**). Что «потеря готовности» — **все** требуемые процессы; порог дребезга — `readiness_grace_s` (умолчание 0)
  (**К4**).
- **Рестарт упавшего ребёнка в `running`** — это потеря готовности → `fault` → система останавливается; супервизор
  поднимает процесс как сейчас; после возврата готовности — `ready`, START снова за оператором (**В6**).
- `system.shutdown` из любого состояния → `shutting_down`; graceful-путь сначала выполняет STOP-последовательность, если
  было `running` (согласовать с gui-graceful-close 1.4: один `pre_stop`, не два).
- **Программный STOP — не аварийный останов.** E-stop — аппаратная функция безопасности (ISO 13849 / IEC 62061), этот
  план её не реализует и не заменяет.

### 3.6. Включение (обратная совместимость)

Ключ конфига PM `run_gate: bool`. **Умолчание framework — `false`**: `run_event` создаётся взведённым, состояние
публикуется (`ready ↔ running` без гейта источников) — framework-тесты, minimal_app, line_sim, стенды не меняются.
Прототип включает `run_gate: true` в манифесте (Task 2.1) и учит стендовые сценарии слать `system.run.start` после
`ready` (**К1**). Наблюдаемость — без новых флагов: состояние — несколько листьев state, ноль кадров.

### 3.7. Смена рецепта и правка топологии на ходу

`topology.apply` (оба пути: `recipe.activate` и редактор топологии GUI) в `running` → отказ
`{"success": False, "error": "running", "message": "сначала ОСТАНОВИТЬ"}`; в остальных состояниях → `booting` → по
готовности `ready`/`not_ready`, **никогда не `running` сам**. Проверка — в PM `_cmd_topology_apply` (одна точка на оба
пути). Параметры на ходу (`param`, поле «Слово», решение 25) — не `topology.apply`, не блокируются (**В7**).

## 4. Контракт для GUI / пульта / backend_ctl

`system.run.status` и state `system.run.*`:

```
{"state": "ready", "since": 1793000000.0,
 "start_allowed": true,
 "reasons": [{"node": "recog.ml_inference", "severity": "out_of_spec", "reason": "…", "source": "preflight"}],
 "last_fault": null | {"at": t, "reasons": [...]}}
```

Кнопка ЗАПУСТИТЬ активна ⇔ `start_allowed`; неактивная показывает первую причину `failure` (ISA-101, §9.5).
ОСТАНОВИТЬ активна ⇔ `state == "running"`. Ответы команд: `system.run.start` → `{"success": bool, "state": ...,
"error": "not_ready|already_running|stopping|shutting_down", "reasons": [...]}`.

## 5. Соседи и владение файлами

| сосед | что берём | что даём | конфликт |
|---|---|---|---|
| `lifecycle-stop-ownership` 1.10/1.11, C-60 (полоса Ф) | исполнитель L-команд (`pm-lifecycle-submit`), честный стоп | — | `process_manager_process.py`, `process_registry.py`, `process_runner.py` у Ф до merge 1.10 (C-60 — `plugins/base.py`) → Ф1 после merge 1.10 и C-60 |
| C-55b (полоса С) | `PreflightFinding`, сборщик, вызов в launcher | причины `preflight` → `not_ready` | `plugins/base.py`, `plugins/manifest.py`, `system_launcher.py` у С до merge C-55b → Task 1.2, 1.6 после |
| `gui-graceful-close` 1.4 | точка `pre_stop` (шаги «домой») | STOP переиспользует её | `process_manager_process.py`; один `pre_stop` на STOP и shutdown |
| `robot-protocol-v2` T5.3e (Р2) | команда «домой» как шаг `pre_stop` | — | `Plugins/hub/device_hub/plugin.py` — Р2; Task 2.2 через координатора |
| `pult-control-panel` (строки 15–17) | — | `system.run.*`, команды START/STOP, причины | кнопки пульта = вызывающие этих команд |

## 6. Риски

- Стенды и e2e, ждущие кадров сразу после boot, станут красными при `run_gate: true` — перечень вызывающих собрать до
  Task 2.1 (Haiku-опись).
- Хуки `pause/resume` зовутся из потока наблюдателя, параллельно `process()` плагина: реализации в Task 2.2 должны
  быть потокобезопасны; ADR пишет это в контракт.
- Готовность по heartbeat-такту: задержка перехода `ready` до `3 × heartbeat_interval`; приемлемо для оператора, но
  число — в приёмке Task 2.4.
- Плагины, которые грузят тяжёлое в фоне после `start()` (проверить `ml_inference`), объявят готовность рано, если не
  реализуют `readiness()` — Task 2.2.

## 7. Не делаем в 1.0

Held/Suspended (голодание ленты, нет диска), режимы Production/Maintenance/Manual, OPC UA-сервер, квитирование аварий
отдельной командой, превью в `ready`, частичный запуск (часть узлов), аппаратный e-stop.

## 8. Проверки, которые нужны до кода (ненадёжно сейчас)

- Как heartbeat ребёнка попадает в StateStore PM при `run_gate` в приложении без state-plane — тогда гейт неисполним;
  Task 1.3 при `run_gate: true` без state-plane → отказ старта PM с текстом (не тихо «никогда не готов»).
- Номера строк `process_manager_process.py` после 1.10/1.11.
- Где в GUI место кнопок (`multiprocess_prototype/frontend/windows/` — не сверено).

## 9. Соответствие стандартам

Издания и URL сверил web-researcher координатора (2026-10-27); где он пишет «не подтверждено» — так и помечено.

| стандарт | издание | источник |
|---|---|---|
| PackML (модель состояний) | OPC 30050 v1.01, 2020-11-11 | https://reference.opcfoundation.org/PackML/docs/ |
| ANSI/ISA-TR88.00.02 | 2022 — **не подтверждено** | — |
| NAMUR NE 107 | ред. 2017-04-10 | https://www.namur.net/en/publications/news-archive/ne-107-has-been-revised.html |
| IEC 60204-1 | Ed. 6.0 2016 + AMD1:2021 (сводная 6.1); определения категорий — по вторичному источнику | https://webstore.iec.ch/publication/71256 |
| OPC 10000-100 (DI) | 1.05.0, 2025-11-15 | https://reference.opcfoundation.org/DI/docs/ |
| ANSI/ISA-18.2 | 2016; состояния аварии — по вторичному источнику | https://isa.org/standards-and-publications/isa-standards/isa-18-series-of-standards |
| ANSI/ISA-101.01 | 2015 — **не подтверждено** | — |

### 9.1. PackML (OPC 30050 v1.01; ISA-TR88.00.02 — издание не подтверждено)

Состояния OPC 30050: Aborting, Aborted, Clearing, Stopped, Stopping, Resetting, Idle, Starting, Execute, Suspending,
Suspended, Unsuspending, Holding, Held, Unholding, Completing, Complete; режимы Production, Maintenance, Manual.
Деление на «действующие» (`*-ing` и Execute) и «ожидающие» (остальные) — **наше прочтение**, источником не подтверждено:
у нас действующие — `booting`, `running`, `stopping`; ожидающие — `not_ready`, `ready`, `fault`.

| PackML | наше | 1.0 |
|---|---|---|
| Resetting | `booting` | да (подъём узлов, ожидание готовности) |
| Idle | `ready` | да |
| Stopped | `not_ready` (+ причины) | да; в PackML Stopped → Reset → Idle — у нас переход автоматический по готовности, без команды Reset |
| Starting | — | нет: START мгновенный (взвод события) |
| Execute | `running` | да |
| Stopping | `stopping` | да |
| Aborting / Aborted | `fault` (переход + состояние схлопнуты) | да, одно состояние |
| Clearing | — | нет: выход из `fault` автоматический по готовности (**В4**) |
| Held/Holding/Unholding, Suspended/Suspending/Unsuspending | — | нет в 1.0: голодание ленты/нет диска — причина `out_of_spec` в `running`, не состояние (**В8**) |
| Complete/Completing | — | нет: непрерывный процесс |
| Режимы Production/Maintenance/Manual | — | нет; кандидат после 1.0 (Manual = пульт без гейта) |

### 9.2. NAMUR NE 107 (ред. 2017-04-10) — символы и цвета не подтверждены

| NE 107 | наше `severity` | C-55b | блокирует START |
|---|---|---|---|
| Failure (F) | `failure` | `error` | да |
| Function check (C) | `check_function` | — | **К3** (рекомендация: да — узел в калибровке/обслуживании) |
| Out of specification (S) | `out_of_spec` | `warning` | нет, показ |
| Maintenance required (M) | `maintenance` | `info` | нет, показ |
| OK | нет причин | — | — |

Не берём: цветовую/иконную нотацию NE 107 как требование (это ISA-101/GUI).

### 9.3. IEC 60204-1 (Ed. 6.1 сводная), категории останова

| категория | смысл | у нас |
|---|---|---|
| 0 | немедленное снятие энергии | не программная функция; ближайшее — `system.shutdown mode=force` / HALT драйвера; **не** STOP |
| 1 | управляемый останов, затем снятие энергии | STOP оператора с шагом `pre_stop` «домой → серво OFF» (T5.3e «Остановить») |
| 2 | управляемый останов, энергия остаётся | авария `fault`: `pause()` — стоп движения на месте; также `process.stop` отдельного процесса (поток останавливается, привод под питанием) |

**Аварийный останов (e-stop) — аппаратная функция безопасности (ISO 13849 / IEC 62061). Программный STOP и `fault`
этого плана e-stop'ом не являются и его не заменяют.**

### 9.4. OPC UA — PackML companion (OPC 30050 v1.01), Device Integration (OPC 10000-100 1.05.0)

Только проверка имён: `system.run.state` ↔ PackML `CurrentState`, `system.run.reasons` ↔ DI `DeviceHealth` (NE 107-
шкала в DI) + сообщения. Плоские пути state отображаются в узлы без переименования. OPC UA в 1.0 нет.

### 9.5. ISA-18.2-2016 (аварийная сигнализация) и ISA-101.01 (HMI, издание не подтверждено)

Состояния аварии ISA-18.2 (по вторичному источнику): Normal, Unacknowledged, Acknowledged, RTN Unacknowledged, Shelved,
Suppressed by Design, Out of Service. Берём только Unacknowledged → Acknowledged. Берём: авария имеет состояние подтверждения (у нас `last_fault` гасится нажатием START — подтверждение действием;
отдельная кнопка «Квитировать» — **В4**); неактивная кнопка показывает почему (первая причина `failure`, список — по
наведению/раскрытию). Не берём: приоритеты, shelving, рационализацию аварий.
