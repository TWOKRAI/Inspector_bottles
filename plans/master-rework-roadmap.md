# Мастер-роадмап переработки системы Inspector_bottles

> Синтез 6 проверенных измерений + adversarial-вердиктов. Дата сверки всего материала: **2026-06-18**, ветка `feat/draw-mode-rework`.
> Несу ТОЛЬКО то, что скептик подтвердил (CONFIRMED). Понижённое/опровергнутое помечено явно. Каждый dead-code-пункт = «решение владельца — обсудить», ничего к одностороннему удалению.

---

## 1. Контекст и сквозной принцип

**Доки = датированные гипотезы. Код = единственная истина.** Все три плановых дока (CSA, EXEC, CARVE) и аудит (AUDIT 2026-06-13) написаны РАНЬШЕ текущего кода и систематически от него отстают. AUDIT — самый опасный по лагу: датирован между частями comm-system-фиксов, поэтому смешивает закрытое и живое.

**Главный практический вывод верификации:** реальный объём работ **существенно меньше**, чем читается из канона. Несколько «крупных» задач уже сделаны на уровне инфраструктуры (см. §2). Это снимает давление с финальной comm-system-волны.

**Порядок осей (binding-решение владельца #2):** осторожная чистка → carve-out → comm-system S4/S5 ПОСЛЕДНИМИ. Этот порядок — **политика владельца, НЕ техническая зависимость** (скептик подтвердил: cleanup и carve трогают непересекающиеся файлы; S4 технически можно делать в любой момент — реальное ограничение только в hot-path-риске).

**Сквозные binding-факты, подтверждённые на живом коде:**
- modularity = #1 слабость, 0 import-циклов (acyclicity 10000) — CONFIRMED направление;
- carve-поверхность чистая: EventBus + plugin_register_resolver — zero-coupling (0 Qt/mp импортов, CONFIRMED);
- ветка draw-mode чистая и свежая, +36 над main.

### 1.1 Fault-isolation как сквозной критерий приёмки (уточнение владельца 2026-06-18)

**Цель:** «один блок упал ≠ весь pipeline упал» — фреймворк как конструктор *изолированных по отказам* блоков, не только развязанного кода. Наравне с критерием sentrux-модульности ([[feedback_constructor_modularity]]).

**Уже есть даром (процессная архитектура):** границы процессов (`mp.Process` на процесс-воркер — падение одного не роняет соседние), `RestartPolicy`/`auto_restart` (ProcessMonitor), ограниченные очереди + back-pressure, SHM ring-buffer, 0 import-циклов (acyclicity 10000). Изоляция отказов ~на 80% обеспечена самой архитектурой.

**Реальные дыры изоляции = уже найденные находки, закрываются в волнах чистки (отдельной стройки НЕ нужно):**
- **M-err-\*** (W2): hot-path глушит ошибку молча → принцип **contain → report → degrade** (лог + `status=error` + вернуть `[]`), НЕ молчать и НЕ пробрасывать (иначе обрушит воркер).
- **M-race-1** (W3): исключение на тике supervisor роняет весь always-on воркер device_hub → per-item try/except + публичный snapshot (один драйвер упал ≠ хаб лёг).
- **M-leak-\*** (W1): подписки без teardown → утечки/use-after-free при пересборке.

**Acceptance (добавляется в qt-smoke каждой волны):** при правках в зоне модуля — убить/сломать один блок (камера/драйвер/плагин) и убедиться, что соседи живут и деградация видима (лог/status), а не немой обвал.

**Что НЕ делаем сейчас (per владелец «не стоит того»):** отдельную стройку bulkheads/circuit-breaker/chaos-тестов на каждый модуль. Изоляция добивается попутно чисткой (W1–W3), не отдельным заходом против product>engine.

### 1.2 Стратегия миграции: почему НЕ новый пакет с нуля (решение 2026-06-18)

**Решение:** не создаём новый пакет-приложение для рерайта. Чистый целевой пакет уже существует — `multiprocess_framework`. Три режима по типу кода:
- **Универсальное → carve-out во framework** по кирпичику (forcing-function: `interfaces.py` + characterization-тесты + расцепление). Волны W3–W5.
- **App-specific → чистка НА МЕСТЕ** на `refactor/master-rework` (god-split, утечки, мёртвое) — этому коду некуда переезжать. Волны W1/W2/W6.
- **Мёртвое/дубли → за борт** через `git rm` поштучно (owner-decides). Волна W4.

**Почему НЕ рерайт в новый пакет (evidence):** 0 циклов импорта (acyclicity 10000), тесты зелёные (3000+), слои чистые, мёртвого ~2.4% (~2500/106k LOC) — рерайт-ловушка не оправдана. «Уродливый» код часто держит реальные edge-кейсы (принцип «не используется ≠ не нужно»). Новый пакет лишь продублировал бы роль `multiprocess_framework` и заморозил бы продукт до паритета (против product>engine). Единственный легитимный «новый пакет» — опциональный framework-`frontend`-слой как ЦЕЛЬ выноса Qt-универсалий (CSA Q6): scoped-модуль с контрактом, не рерайт.

---

## 2. Сводка устаревшего канона (STALE-CANON corrections)

Каждый пункт — док утверждает одно, живой код показывает другое. Все подтверждены скептиком.

| # | Канон говорит | Реальность кода (verified-2026-06-18) | Что это меняет в роадмапе |
|---|---|---|---|
| SC-1 | FrameShm middleware = 2 класса, «слить 2→1» (CSA §2/§9.2/§12 P2) | Один класс `frame_shm_middleware.py`. Остаток — только `[TRACE]`-логи в `on_receive`, строки **345,357,370,375,387,395,400** | Слияние ГОТОВО. Остаток = 1 правка (снять TRACE), не S4-задача |
| SC-2 | PM bespoke-reply дубль в `_handle_process_command` (CSA §1/§3.6) | Absorbed в `reply_to_request` (commit de689983); метод-обёртка сохранена намеренно (opt-out `manages_own_reply=True`, `process_manager_process.py:183`) | Закрыто |
| SC-3 | **S5 auto-reply надо собрать из 4 ручных вызовов** | **REFUTED.** Auto-reply УЖЕ в generic dispatch-цикле: `_dispatch_command` (`core/router_manager.py:502-506`) авто-reply'ит ВСЕ команды; хендлеры отписываются через `manages_own_reply`. Документировано как landed (`DECISIONS.md:2299`, ADR-COMM-005). «4 ручных места» — фактически одно (PM, намеренный opt-out) | **S5 auto-reply ≈ ноль кода.** Остаток — максимум аудит opt-out'ов. Раздувать как задачу НЕЛЬЗЯ |
| SC-4 | SHM-утечка при `replace_blueprint` (нет `release_process_memory`), gap M2 (CSA §3.7, COMM_ARCH.md:199) | `release_process_memory` есть (`manager.py:375`), в интерфейсе, вызывается на hot-swap (`process_manager_process.py:624`), покрыт ≥4 тест-файлами. COMM_ARCH.md:199 «план P2» врёт | M2 ЗАКРЫТ. Обновить док |
| SC-5 | Телеметрия = todo на push (EXEC S0, CSA §9.10) | `_publish_metrics_to_tree` (`process_heartbeat.py:100`) — self-publish активен | Сделано. Убрать из todo |
| SC-6 | §11 quick-wins частью открыты; `IMessageFactory`/`routers`/`subtype`/`_state_multiplexer`/`DispatcherConfig`/shadow `bridge.py`/`get_field` | Все ЗАКРЫТЫ в коде (a2fccdb5, 45d3873a и др.). CSA-трекинг S8 точен | Не чинить починенное |
| SC-7 | undo: «два движка legacy↔domain» (CSA §5) | Движок ОДИН (domain `CommandDispatcherOrchestrator`); Ctrl+Z/Y на domain (`app.py:459`). ActionBus — retained-but-unbound | Снять STALE-claim в комментах. Дуальность undo разрешена |
| SC-8 | AUDIT M-dead-4: `topology/editor` ~700 LOC мёртв целиком | `TopologyPresenter` (148 LOC) ВНУТРИ пакета ЖИВ — используется `pipeline/presenter.py:159-161` (load/save YAML). Kill касается editor-виджета + детей, НЕ всего пакета | Целиться в editor-виджет, не в presenter |
| SC-9 | AUDIT M-race-1: device_hub `_entries` «без lock» | `_registry_lock`/`_workers_lock` СУЩЕСТВУЮТ в менеджере; гонка — на стыке плагин↔менеджер (плагин обходит через `_manager._entries`). `list_devices()` сам read без лока | Не «нет lock», а «утечка приватного состояния через границу слоя» + read-путь не залочен |
| SC-10 | Числа метрик: modularity 0.4488/4488, quality 7161, покрытие 51.6% | **STALE.** Живой sentrux: modularity raw **0.2700** / score **5134**; quality **7031**; acyclicity 10000 (0 циклов CONFIRMED). Расхождение в 1.6×, хуже чем думали | Любая числовая acceptance-цель строится от **5134/0.2700**, НЕ от 4488 |
| SC-11 | God-файлы по путям `widgets/v3/pipeline/` | `v3/` НЕ существует; реальные пути `widgets/tabs/pipeline/`. LOC: presenter **1827**, factory **1190**, inspector_panel **1151** (в `pipeline/inspector/`) | Задачи с путём `v3/` упадут на «file not found» |
| SC-12 | AUDIT M-cfg-2: recipe = «2 YAML-формата», дубль READ в 2 местах | Форматов 3 (v3/v2/legacy `data:`-envelope); точная `or`-цепочка — в 3 сайтах (`pipeline/presenter.py:1225,1652`; `recipes/presenter.py:394`) + 3 родственные идиомы | READ-normalize нужен, но ТЗ перечисляет 3 точных сайта, не «6 одинаковых» |

**Два «критических утечки», понижённых скептиком (важно — иначе откроем спринт под несуществующую проблему):**

| Канон-claim | Реальность | Вердикт |
|---|---|---|
| M-leak-3 «~68 EventBus subs без teardown» в `pipeline/presenter.py:167-177` | РОВНО **2** подписки (`_topology_sub`:167, `_recipe_activated_sub`:177), обе с сохранёнными handle → отписка тривиальна | **REFUTED число.** Leak реален, но это 2 подписки, не 68 |
| M-leak-2 «state-listeners накапливаются» `app.py:262` | `add_state_listener` вызван ОДИН раз в `run_gui()` startup, не в цикле/switch. Накопления нет. `remove_state_listener` в framework вообще отсутствует | **REFUTED «accumulate».** Реальная (меньшая) проблема: нет инфраструктуры отписки на будущее |

---

## 3. Единственный ПЕРВЫЙ шаг

**W0 → AUDIT re-scan находок M-* со свежими file:line, ПЕРЕД любым кодом (1 дешёвый агент).**

Почему именно это, а не код:
- AUDIT (2026-06-13) — самый лагающий док. Минимум 3 из 6 cleanup-целей имеют смещённые координаты (M-err-2 `capture/plugin.py:122` → реально **152-153**; M-leak-5 `robot/controller.py:134` → реально `robot/calibration/controller.py:111,158` с **частичным** teardown; M-race-1 — lock существует, не для `_entries`). Без re-scan агенты потратят итерацию на «файл не найден / правка уже есть» (риск R3 stale-canon re-fix).
- Re-scan — **входной критерий W1**, не опция. Он переэмитит ВСЕ M-* со свежими координатами и даст честный baseline.
- Сразу за ним по коду: **M-leak-3 teardown 2 подписок presenter** — LIVE-подтверждённая, тривиальная, zero hot-path, доказывает контур чистки одним qt-smoke.

**Формула старта (с поправкой скептика по 7 файлам):**
`коммит draw-mode-хвоста (БЕЗ 7-го файла памяти) → merge draw-mode → main → session_start baseline (от живого 5134) → AUDIT re-scan → M-leak-3`.

---

## 4. Решётка волн W0–W8

> Параллелизм: ≤2 агента без worktree (память `feedback_parallel_agents_commit_race`); >2 — worktree. Hot-path (камеры, kind-каналы) — СТРОГО последовательно.

| Волна | Ось | Содержание | Entry-gate | Exit-gate | sentrux + qt-smoke |
|---|---|---|---|---|---|
| **W0** Фундамент | — | (1) коммит draw-mode-хвоста (7 uncommitted-файлов = multi-instance text_vector — см. §5; **исключить 7-й `feedback_constructor_modularity.md` → отдельный `docs(memory):`**); (2) merge draw-mode→main; (3) срез `refactor/master-rework` от свежего main; (4) **AUDIT re-scan M-* @2026-06-18 с пересчётом file:line**; (5) `session_start` от живого baseline | main зелёный, draw-mode hardware-pending принят владельцем | свежая ветка; обновлённый M-* список; baseline зафиксирован (modularity score **5134** / raw **0.2700**, 0 циклов) | `session_start`; полный qt-smoke до правок |
| **W1** Утечки (C) | C | M-leak-3 (teardown 2 подписок presenter — тривиально), M-leak-2 (завести `remove_state_listener` в framework — на будущее, накопления нет), M-leak-5 (robot/calibration/controller — добавить owner-unbind поверх частичного), M-leak-1/4/6 (по re-scan) | W0 done | teardown/unsubscribe добавлены; тесты на отписку | qt-smoke: пересборка вкладок; sentrux дельта ≥0 |
| **W2** Error-swallows hot-path (C, продукт) | C | M-err-1 (`camera_service/plugin.py:152-155` `except Exception: return []` → чёрный экран), M-err-2 (`capture/plugin.py:152-153`), агрегат M-err-* (~30). **Принцип fault-isolation владельца:** contain→report→degrade (лог + status=error + вернуть `[]`), НЕ проброс (иначе обрушит воркер) | W1 done | hot-path логирует ошибку вместо немого чёрного экрана | **СТРОГО последовательно**; qt-smoke: камера даёт кадры ИЛИ видимую ошибку; FPS ≥ baseline |
| **W3** Races + carve #1 (C+B fan-out) | C \| B | C: M-race-1 (`device_hub` — публичный `snapshot_registry()` под `_registry_lock`, плагин перестаёт читать `_entries`/`_drivers` в 10 местах), M-race-2..4 (по re-scan). **B параллельно:** carve `EventBus` (`domain/event_bus.py`)→framework | W2 done | races под lock/snapshot; EventBus в framework | sentrux: 0 новых циклов; check_rules: 0 reverse-import; qt-smoke полный |
| **W4** Kill-list решения + carve #2 (C+B) | C \| B | C: вынести kill-list владельцу — **per-item owner-decides, НИЧЕГО не удалять**. B: carve `plugin_register_resolver`→framework | W3 done | вердикт владельца по каждому dead-пункту; резолвер в framework | check_rules; qt-smoke не затронут (резолвер pure) |
| **W5** Carve-пилот SystemBuilder (B) | B | Характеризационные тесты launcher (их НЕТ — долг) → вынести **универсальный шов** `SystemLauncher(...) + add_process` (`launch.py:374-394`), НЕ весь класс; `_ORCHESTRATOR_CLASS_PATH:32` → DI-параметр | W4 done; carve-двойка доказала шов | шов в framework; запуск прототипа не сломан; app-завязки (`state.bootstrap`/`assembly`/`config`/`recipes.devices_sync`) остаются в прототипном `SystemBuilder` | **session_end дельта**; qt-smoke `/run-proto` полный цикл |
| **W6** God-file split (параллельный трек) | C (модульность) | presenter.py 1827, factory.py 1190, inspector_panel.py 1151. **Параллельно W3–W5** (отдельный worktree, файлы не пересекаются с carve). Вынести graph↔blueprint codec из presenter | W1 done (утечки в presenter закрыты ДО split) | god-файлы разбиты; #1 драйвер modularity адресован | sentrux modularity дельта от **5134** (числовая цель); qt-smoke: вкладки Pipeline/inspector живы |
| **W7** S4 kind-каналы (comm, hot-path) | A | TRH P3: FrameChannel + EventChannel; **P3.2 StateChannel DEFERRED**; снять TRACE (345-401); завести готовый `resolve_channel_kind` в `_resolve_channels` (~15 строк); характеризационный тест паритета | **W0–W6 done** (policy владельца) | kind-каналы живые; паритет доказан; матрица CSA §9 = acceptance | **HIGH-риск, СТРОГО последовательно**; FPS-baseline ДО; feature-flag откат; qt-smoke; sentrux дельта |
| **W8** S5 финал (comm) | A | **auto-reply УЖЕ работает (SC-3)** → только аудит opt-out'ов `manages_own_reply`; опц. дешёвый thread-guard `request()`; undo-консолидация + ActionBus-вердикт из W4 | W7 done | аудит opt-out'ов закрыт; undo-фичи перенесены ИЛИ ActionBus заморожен (per W4) | qt-smoke: дискретные команды получают результат; sentrux финальная дельта vs W0 |

**Строго последовательно:** W2 (camera hot-path), W7 (kind-каналы), W8-guard. **Безопасный fan-out (≤2/worktree):** W1, W3 (races+EventBus), W4 (kill-list+резолвер), W6 (god-split — отдельный worktree).

---

## 5. Carve-out: Stage-0 карта + рецепт пилота + отложенное

### Stage-0 карта (LOC non-test, verified-2026-06-18)

| Подпакет | LOC | Тег | Carve-вывод |
|---|---|---|---|
| frontend | 41 637 | app-specific (+2 zero-coupling вкрапления) | НЕ кандидат целиком; точечно: `plugin_register_resolver` (near-zero) |
| domain | 4 045 | coupled → NOT-now | только `event_bus.py` = zero-coupling; остальное single-consumer trap |
| adapters | 2 372 | coupled → NOT-now | `CommandDispatcherOrchestrator` намертво на `Project`/`ProjectCommand`/`ProjectEvent` |
| backend | 3 413 | mixed | `SystemBuilder` = пилот |
| registers / recipes | 1 037 / 1 262 | app-specific | не кандидаты |

**Universal-поверхность = ровно 3 точки:** `domain/event_bus.py`, `frontend/bridge/plugin_register_resolver.py`, шов внутри `backend/launch.py`.

### Рецепт пилота (3 шага, по нарастанию риска)

**Шаг 1 — plugin_register_resolver (zero-coupling, бесплатный):** чистая `(dict, str, int) -> str|None`, 1 потребитель (`app.py:534`), тесты есть. Вынести в `process_module/`, thin re-export shim.

**Шаг 2 — EventBus (zero-coupling, с нюансами):**
- `ProjectEvent` — **type-only** (`from __future__ import annotations`, лишь TypeVar bound), не runtime → bound обобщается до structural Event-Protocol.
- **Поправка скептика (обязательна):** потребителей не 2, а **3** (третий — type-level `displays/presenter.py:27,82`); плюс есть ОТДЕЛЬНЫЙ `domain/protocols/event_bus.py` (`EventBusProtocol`/`Subscription`) с ≥4 прод-потребителями (`topology_repository.py`, `config_store.py` и др.). Рецепт обязан: (а) починить type-hint в `displays/presenter.py`; (б) решить судьбу `EventBusProtocol` (выносить вместе или оставить прототипным контрактом) — иначе рассинхрон протокол↔реализация.

**Шаг 3 — SystemBuilder (настоящий пилот, с долгом по тестам):**
- **STALE-CANON CORRECTION (CONFIRMED скептиком):** выносится НЕ класс, а **шов** `SystemLauncher(...) + add_process` (`launch.py:374-394`). `build()` тянет `build_initial_state`/`build_throttle_rules`/`BlueprintAssembler`/`expand_observability`/`recipes.devices_sync` — остаются app-завязками.
- Ед. namespace-завязка `_ORCHESTRATOR_CLASS_PATH` (`:32`) → DI-параметр.
- **Характеризационного теста на `build()` НЕТ** (только `test_assembler.py` на суб-компонент) — hard-долг. Snapshot-тест «blueprint dict → N процессов + orchestrator_config» пишется ПЕРВЫМ.

### Отложено (binding-решение #3)

| Компонент | Почему |
|---|---|
| domain/* (кроме EventBus), adapters/* | single-consumer trap — вынос = вынести весь vision-домен |
| CommandDispatcherOrchestrator | завязан на `Project`/`ProjectCommand`/`ProjectEvent` |
| GuiStateBindings | Qt-binding слой, app-specific (from-doc) |
| DataReceiverBridge | привязан к S5/comm, после S4/S5 (from-doc) |

> **Честная оговорка:** carve трогает 158+64 строки + 1 шов → modularity (score 5134, у пола правила `min_depth 0.6154 < 0.6500` CONFIRMED) почти не сдвинет. Метрику двигает app-side god-split (W6). Carve = доказательство шва и forcing-function, НЕ метрический рычаг.

---

## 6. Kill-list мёртвого кода / дублей

> Все статусы — «решение владельца — обсудить». Принцип: unused != unneeded. Каждый CONFIRMED скептиком, кроме помеченных DOWNGRADED.

| # | Пункт | file:line | Статус сверки 2026-06-18 | Класс | LOC | Решение |
|---|---|---|---|---|---|---|
| K1 | ActionBus runtime-проводка (`_legacy_action_bus`) + пакет `frontend/actions/` | `app.py:470` + `frontend/actions/` | **CONFIRMED runtime-dead; DOWNGRADED «754 LOC удаляемы»** — пакет сцеплен с prod через `roles_panel.py:204` (`V2ActionBuilder`) + no-op presenters (`system/presenter.py:132`, живой Qt-коннект `section.py:230`) | future-reserve (CSA §5: источник 5 undo-фич) | ~754 | **решение владельца — обсудить.** Формулировка: «выпил runtime-проводки + чистка no-op мостов», НЕ «удалить пакет». Заморозить как framework-референс ДО переноса 5 undo-фич ЛИБО выпилить только проводку |
| K2 | ActionBus undo-движок (дубль) | `actions_module/bus.py:326-418` | **CONFIRMED** | proven-duplicate domain CDO | ~90 | решение владельца — обсудить (привязан к K1) |
| K3 | `apply_topology_diff` | `topology_bridge.py:503` | **CONFIRMED dead** (0 prod, serena={}) | unique-but-unused | ~98 | решение владельца — обсудить |
| K4 | `hot_add_process` | `topology_bridge.py:381` | **CONFIRMED dead** | unique-but-unused | ~24 | решение владельца — обсудить |
| K5 | `connect_wire` | `topology_bridge.py:432` | **CONFIRMED dead-chain** (зовётся только из мёртвого K3) | unique-but-unused | ~35 | решение владельца — обсудить |
| K5-warn | `disconnect_wire` | `topology_bridge.py:475` | **НЕ снимать целиком** — держится живым `hot_remove_process` (K5b) | — | — | при killе K3/K4 — `disconnect_wire` ОСТАВИТЬ |
| K5b | `hot_remove_process` | `topology_bridge.py:405` | **HAS-CONSUMERS** (`processes/presenter.py:391`) | НЕ dead | — | НЕ трогать |
| K6 | `CommandPanel` | `controls/command_panel.py:11` | **CONFIRMED dead** (test-only) | unique-but-unused | 45 | решение владельца — обсудить |
| K7 | `ProcessStatusWidget` | `controls/process_status.py:8` | **CONFIRMED dead** (слабейшее звено — догрепнуть `test_bridge.py:87,105`) | unique-but-unused | 72 | решение владельца — обсудить |
| K8 | `TopologyEditorWidget` + дети (plugin_selector/process_list/validation_panel/wire_list) | `topology/editor.py:26` | **CONFIRMED dead** (реф только re-export) | unique-but-unused | ~722 | решение владельца — обсудить |
| K8b | `TopologyPresenter` | `topology/presenter.py` | **HAS-CONSUMERS** (`pipeline/presenter.py:159-161`) — **STALE-CANON: M-dead-4 неточен** | НЕ dead | 148 | НЕ трогать |
| K9 | `Services/Operation_crop` | `Operation_crop/preobrazovanie.py` | **CONFIRMED dead** (0 prod/Plugins/proto; только `STATUS.md` + внутр.) | proven-duplicate плагинов | 858 | решение владельца — обсудить (крупнейший +modularity) |
| K10 | `[TRACE]` debug-логи в FrameShmMiddleware | `frame_shm_middleware.py:345-401` | **CONFIRMED present** (per-frame, gated `%30`) | crutch (leftover) | ~15 | решение владельца — обсудить; **НЕ «нулевой риск»** — hot-path, нужен qt-smoke+FPS-проверка |
| K11 | broadcast fallback-bypass хаба | `process_communication.py:245-247` | **CONFIRMED НЕ dead** (fallback при отсутствии queue_registry) | future-reserve | ~3 | оставить (резервная ветка) |
| K12 | дубль fan-out по chain_targets | `source_producer._send_item` + `pipeline_executor._send_results` | **DOWNGRADED: partial-overlap, НЕ proven-duplicate** — `_send_results` несёт frame_trace.stamp/data_type/SHM-семантику | partial-overlap | ~10×2 | → ось «упрощение», осторожно (не ломать frame_trace) |

**Суммарный «потенциально снимаемый» объём (всё owner-decides):** ~2666 LOC, близко к канон-оценке ~2500. Сильнее всего двигают modularity изолированные под-графы K8/K9/K6-7 — мерить дельтой session_start→session_end.

**Открытый вопрос-блокер (K1/K2):** ActionBus — заморозить как framework-референс для P3-переноса 5 undo-фич ИЛИ выпилить runtime-проводку прототипа (класс оставить)? До ответа K1/K2 не трогать.

---

## 7. Упрощение 8 сложных мест

| Ранг | Место | Цепочка (verified) | Боль | Упрощение | Payoff/Effort |
|---|---|---|---|---|---|
| 1 | **recipe save/load/activation** | `recipes/presenter.py:303` → dispatch(ActivateRecipe) → `read_raw` → branch формата → `unwrap_recipe` (`launch.py:57`) → `apply_topology` → PM hot-swap | 8 | Единая READ-точка разбора формата (симметрично WRITE `normalize_recipe_v3_raw`). **ТЗ: 3 точных сайта** (`pipeline/presenter.py:1225,1652`; `recipes/presenter.py:394`) + отдельно выровнять `calibration/controller.py:27` (двух-форматный) и `if`-идиомы (`recipes:389`/`launch:74`). Не «унифицировать 6» — сломает семантику | ★★★★★ / S |
| 2 | **device-hub supervisor + state-push** | `_supervisor_loop` (`plugin.py:247`) → читает `_manager._entries`/`_drivers` в 10 местах → publish в `devices.state.*` | 7 | Публичный `snapshot_registry()`+`connected_ids()` под `_registry_lock` (заменить и незалоченный `list_devices()`); плагин перестаёт читать приватку | ★★★★ / S |
| 3 | **GUI field-write → register** | A: `SetPluginConfig` (домен, КАНОН, живой `presenter.py:233`); B: FormContext→ActionBus (**test-only, прод `form_ctx=None`** — мёртв, см. K1); C: CommandCatalog→ConnectionMap→IPC | 7 | Зафиксировать путь A каноном. **Поправка скептика: путь B НЕ «живой потребитель ActionBus» — он test-only.** Значит это не «миграция forms→domain», а возможное удаление мёртвого (per K1, owner-decides) | ★★★ / S (понижено с M) |
| 4 | **undo legacy↔domain** | `CommandDispatcherOrchestrator` (`command_dispatcher.py:60`) — единственный live undo | 6 | **Код не нужен** — движок уже один (SC-7). Снять STALE-claim «два движка», обновить комменты | ★★★★ / XS (дока) |
| 5 | **telemetry live-push** | `_publish_metrics_to_tree` (`process_heartbeat.py:100`) → `proxy.set` → GUI subscribe | 5 | carve = упрощение: self-publish-паттерн → переиспользуемый framework-helper/mixin | ★★★ / S |
| 6 | **pipeline graph ↔ topology** | `graph_scene.export_data` ↔ presenter codec ↔ `model.from_topology_dict` | 6 | Вынести graph↔blueprint codec из god-presenter (1827) в `pipeline/graph_topology_codec.py` — чистые dict↔NodeData, тестируемо без Qt (= часть W6) | ★★ / M |
| 7 | **form-binding + dynamic schema** | `factory.py:1124` (9× `_build_*`) ∥ framework `params_form._create_widget` | 6 | **DOWNGRADED скептиком:** «двойной маппинг» заявлен по описанию, не доказан diff'ом сигнатур. **Перед ТЗ — diff двух реализаций**, иначе не трогать | ★★ / M (под вопросом) |
| 8 | **draw-mode point pipeline** | pipeline → `RobotDrawPlugin.process` → queue → forwarder → `DeviceHubClient.request` → driver → modbus (батчи 100/30 + ACK) | 6 | **НЕ ТРОГАТЬ.** Свежий чистый код, hardware-pending. Только задокументировать ACK-контракт `REG_DRAW_DONE_N` | ★ / L — заморозить |

---

## 8. Comm-system S4/S5 — реальный остаток + hot-path реестр + gate

**Реальный остаток МЕНЬШЕ канона.** S4 (kind-каналы) — единственный по-настоящему крупный hot-path-блок; ставится последним из-за РИСКА, не объёма.

### S4 (kind-каналы) — контракт уже написан, нужна проводка

Готово (CONFIRMED): весь контракт в `router_module/routing/` — `resolve_channel_kind` (`routing_table.py:72`), `channel_name` (`:103`), `resolve_route` (`address_aware_channel.py:65`), экспорты. Docstring: «декларация без проводки — это P1».

Остаток S4:

| Задача | Объём | Риск |
|---|---|---|
| Завести `resolve_channel_kind` в `_resolve_channels` (`router_manager.py:951`) | ~15 строк | HOT-PATH |
| Регистрировать kind-каналы при init процесса | проводка | средний |
| Характеризационный тест паритета `_resolve_channels` vs `resolve_route` на всём живом трафике | тесты | обязательный gate |
| Снять `[TRACE]` (345-401) ДО замеров | 7 правок | низкий |
| P3.2 StateChannel | DEFERRED | — |

### S5 — почти ноль кода (SC-3)

| Задача | Реальный остаток |
|---|---|
| auto-reply | **УЖЕ работает** (`_dispatch_command:502-506`). Максимум — аудит opt-out'ов `manages_own_reply` |
| undo-консолидация | решение владельца по K1 (не код) |
| request() thread-guard | опц. дешёвый рантайм-guard (сейчас только docstring) |

### HOT-PATH реестр рисков (кадровый конвейер 21+ FPS)

| ID | Риск | Доказательство | Митигация |
|---|---|---|---|
| HP-1 | **Latency middleware НЕ ИЗМЕРЕН** | 0 `perf_counter`/`monotonic` в `frame_shm_middleware.py` (CONFIRMED, весь файл) | GATE: измерить baseline `on_send`+`on_receive` ДО правки `_resolve_channels` |
| HP-2 | `[TRACE]` на горячем пути | строки 345-401, `%30` | Снять ДО замеров |
| HP-3 | `resolve_channel_kind` на КАЖДЫЙ кадр | `_resolve_channels` на каждый send | O(1) dict-lookup (он такой); профилировать |
| HP-4 | Паритет каналов | **поправка скептика:** легаси-дефолт = `"queue"`, НЕ `"data"` (`_resolve_channels:960`) — характеризационный тест писать на верном допущении | GATE: тест паритета + feature-flag откат |
| HP-5 | `release_process_memory` unlink × in-flight кадр при switch | **DOWNGRADED-to-unverified:** «митигировано двухфазной регистрацией (5cd23192)» взято из памяти, НЕ сверено против S4-сценария | GATE-ВОПРОС: пересверить `replace_blueprint` против переключения kind-каналов (не закрытый риск) |

### Gate перед касанием hot-path (обязательно)

1. Измерить baseline latency (HP-1) — **нулевой шаг S4**.
2. Снять TRACE-логи ДО замеров.
3. Характеризационный тест паритета (на дефолте `"queue"`).
4. Feature-flag `use_kind_channels` — мгновенный откат.
5. qt-mcp smoke живого рецепта (`QT_MCP_PROBE=1`, порт 9142) — FPS не просел.
6. sentrux session_start→session_end дельта.

---

## 9. Реестр рисков проекта + ветка/подготовка почвы

| ID | Риск | В×И | Главный guardrail |
|---|---|---|---|
| R0 | Грязное дерево потеряет draw-mode хвост | 🔴 Выс×Выс | W0: коммит хвоста в draw-mode ДО merge |
| R5 | Engine-over-product | 🔴 Выс×Выс | C-first дёшево; A/B gated по метрике (память `priority_product_over_engine`) |
| R1 | Hot-path breakage S4 | 🔴 Средн×Выс | S4/S5 последними + FPS-baseline + one-revert |
| R6 | Parallel-agent commit race | 🟠 Средн×Выс | ≤2 без worktree; непересекающиеся треки |
| R8 | Удаление нужного «мёртвого» | 🟠 Средн×Выс | owner-decides per-item; ActionBus заморозить |
| R3 | Stale-canon re-fix | 🟠 Выс×Средн | W0 AUDIT re-scan; verified-2026-06-18 на каждой задаче |
| R2 | Single-consumer trap при carve | 🟠 Выс×Средн | только zero-coupling + DI для `_ORCHESTRATOR_CLASS_PATH` |
| R7 | God-gate false-green | 🟠 Средн×Средн | qt-mcp smoke + характеризационные тесты ДО split |
| R4 | Re-derivation | 🟡 Средн×Низк | citation-index (§11), запрет перевыводить ID |

### Стратегия веток (с поправкой скептика по 7 файлам)

**STALE-CANON CORRECTION (CONFIRMED):** «6 uncommitted orthogonal к draw-mode» — НЕВЕРНО. Это **draw-mode хвост: multi-instance плагинов** (`text_main`/`text_name` — оба `TextVectorPlugin`; `text_vector` — draw-mode фича, коммит `06f4398e`). Файлов **7**, не 6:

| Файл | Связь |
|---|---|
| `domain/entities/project.py` (`_plugin_known`) | прямая draw-mode |
| `process_module/generic/plugin_orchestrator.py:193+` (`instance.name = plugin_name`) | прямая (framework-слой → Layer `mixed`) |
| `adapters/catalogs/plugin_catalog.py`, `domain/protocols/plugin_catalog.py` (`class_path`) | поддержка |
| `adapters/stores/registers_backend.py` | поддержка |
| `process_module/tests/test_plugin_orchestrator.py` | тесты |
| **`docs/claude/memory/feedback_constructor_modularity.md`** (7-й) | **НЕ draw-mode** — owner-правка памяти (fault-isolation принцип). **Исключить из фича-коммита → отдельный `docs(memory):`** |

```
W0 (на feat/draw-mode-rework):
  git add <6 файлов БЕЗ feedback_constructor_modularity.md>
  git commit → feat(draw): multi-instance плагины (text_main/text_name)
               Layer: mixed   Refs: plans/<draw-mode slug>.md
  git commit → docs(memory): fault-isolation принцип   (7-й файл отдельно)
  merge feat/draw-mode-rework → main   (после validate.py + run_framework_tests зелёных)
  session_start на свежем main → BASELINE от живого score 5134 / raw 0.2700 / 0 циклов
  git checkout -b refactor/master-rework   (от свежего main с хвостом)
```

---

## 10. Открытые вопросы для владельца

1. **draw-mode хвост:** коммитить 6 файлов как `feat(draw): multi-instance` (Layer `mixed`, рекомендация) или отдельной фичей? 7-й файл (память) — отдельным `docs(memory):` (рекомендация).
2. **AUDIT re-scan нулевым шагом** — подтверждаете? (Рекомендация: да, дёшево, предотвращает R3.)
3. **Старт чистки:** M-leak-3 (тривиально, 2 подписки) → M-err-1 camera_service? (Рекомендация: да.)
4. **ActionBus (K1/K2):** заморозить как framework-референс для P3-переноса 5 undo-фич ИЛИ выпилить runtime-проводку (класс оставить)? **Блокирует K1/K2 и S5-undo.**
5. **EventBus type-bound:** structural Event-Protocol (типобезопасно, рекомендация) или `bound=object`? И судьба `domain/protocols/event_bus.py` при выносе concrete-класса?
6. **`_ORCHESTRATOR_CLASS_PATH`:** DI-параметр (рекомендация — это «развязка одной завязки») или hardcode в composition root (тогда выносится только `build_launcher`, класс не «выносится»)?
7. **Числовая modularity-цель:** ставим acceptance-дельту от живого **score 5134** (НЕ 4488) после W6+carve, мерим session_start→session_end?
8. **Параллелизм:** ≤2 агента без worktree подтверждаем, или сразу worktree-изоляция на 3 трека (cleanup/carve/god-split)?
9. **FPS-baseline (HP-1):** на каком эталонном рецепте с камерой фиксируем перед S4?
10. **HP-5:** пересверить двухфазную регистрацию `replace_blueprint` против S4-переключения каналов как явный GATE (риск не закрыт, только по памяти)?

---

## 11. Приложение: индекс цитат (canon section → verified/stale)

| Canon | Что несёт | Статус против кода 2026-06-18 |
|---|---|---|
| AUDIT H1/H2 | RenameProcess, Hikvision resize | ЗАКРЫТО (from-doc) |
| AUDIT M-leak-2 | `app.py:262` state-listeners | LIVE, но «accumulate» REFUTED (один startup-listener) |
| AUDIT M-leak-3 | `pipeline/presenter.py:167-177` subs | LIVE, но «~68» REFUTED → **2 подписки** |
| AUDIT M-leak-5 | robot bind_fanout | LIVE, путь STALE → `robot/calibration/controller.py:111,158`, teardown частичный |
| AUDIT M-race-1 | device_hub `_entries` | LIVE на стыке слоёв; «без lock» неточно (lock есть, не для `_entries`) |
| AUDIT M-err-1 | camera_service produce() swallow | LIVE CONFIRMED `plugin.py:152-155` |
| AUDIT M-err-2 | capture produce() | LIVE, line STALE → реально `152-153`, не `122` |
| AUDIT M-dead-1 | ActionBus 0 consumers | CONFIRMED runtime-dead; «754 LOC удаляемы» DOWNGRADED (prod-импорты есть) |
| AUDIT M-dead-4 | topology/editor ~700 dead | STALE — `TopologyPresenter` ЖИВ (SC-8) |
| AUDIT M-dead-5 | Operation_crop 858 | LIVE CONFIRMED |
| AUDIT M-god-1/3 | presenter/factory/inspector LOC | LIVE, числа выросли (1827/1190/1151), пути STALE (`v3/`→`tabs/`) |
| AUDIT M-cfg-2 | recipe 2 формата | STALE — форматов 3, дубль в 3 сайтах (SC-12) |
| CSA §1/§2/§3 | единый хаб, каналы | from-doc; §3.6/§3.7 STALE (SC-2/SC-4) |
| CSA §5 | один undo-движок; ActionBus capability | первая часть CONFIRMED (SC-7); ActionBus в коде (K1) |
| CSA §8 | чистка конверта | STALE — всё закрыто (SC-6) |
| CSA §9 | матрица ~80 capabilities | from-doc (acceptance-чеклист) |
| CSA §11 пп.1-24 | quick-wins | БОЛЬШИНСТВО ЗАКРЫТО, S8-трекинг точен |
| CSA §12 P2 FrameShm | слить 2→1 | STALE — слито (SC-1) |
| CSA §15 | carve-таблица | from-doc — сужено владельцем до zero-coupling+SystemBuilder |
| EXEC S0 | telemetry push | CONFIRMED done (SC-5) |
| EXEC S2 | merge gate | CROSSED |
| EXEC S4 | kind-каналы | PENDING (контракт готов, проводка нет) |
| EXEC S5 | auto-reply+undo | auto-reply УЖЕ работает (SC-3); undo = owner-decision |
| CARVE Этап 1 | вынести SystemBuilder | STALE — выносится ШОВ, не класс; char-теста нет (долг) |
| CARVE baseline | modularity 4377/4488 | STALE — живой score 5134 / raw 0.2700 (SC-10) |
| COMM_ARCH.md:199 | release_process_memory план P2 | STALE — закрыто (SC-4) |
