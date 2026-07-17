# План: telemetry-coherence-remediation — когерентность частотного контракта телеметрии

- **Slug:** telemetry-coherence-remediation
- **Дата:** 2026-07-16
- **Ветка:** feat/telemetry-coherence (ответвить от feat/telemetry-publish-control)
- **Статус:** DRAFT
- **Продолжает:** [`telemetry-publish-control.md`](telemetry-publish-control.md) (управляемая публикация)
  и [`gui-telemetry-read-model.md`](gui-telemetry-read-model.md) (дешёвое GUI-чтение)

---

## Context

Fable-архитектурное ревью всей системы управляемой телеметрии (2026-07-16, суммарная оценка
ДО→ПОСЛЕ **24→42 из 60**; вердикт сохранён в `.claude/agent-memory/investigator/
project_telemetry_branch_verdict.md`) подтвердило крупный шаг вперёд, но вскрыло долг
**когерентности частотного контракта** — единственную ось, где система осталась слабой (5→6),
и ось «простота», где случился регресс (6→5):

1. **Три частотные плоскости вместо одной** (находка D, MEDIUM/design): реальная лестница —
   `heartbeat_interval` (5.0с, задаётся ОДИН раз в `ProcessHeartbeat.start()`, вне telemetry-контракта)
   → publisher-gate (`interval_sec`) → центральный `ThrottleMiddleware`. Верхняя ступень доминирует
   и не управляется: publisher `interval_sec < 5с` — тихий no-op, дефолтный центральный троттл 1.0с
   на каденции 5с — тоже no-op. «Поднять частоту» невозможно ни одной ручкой новой control-plane.
2. **Full-apply вместо дельты** (находка A, HIGH): `telemetry_set(plane="throttle")` через
   `set_rules` ЗАМЕНЯЕТ весь набор центральных правил — «точечная» правка стирает дефолт-защиту
   остальных метрик; `update_rule`/`remove_rule` (PC 0.1) — мёртвый API, 0 продакшн-потребителей.
   Сюда же известный residual «publisher-plane full-apply».
3. **Две семантики пустоты и boot≠reload** (находки B, C): `throttle: {}` на boot → хардкод-дефолты,
   на hot-reload → снять ВСЕ правила; `config.reload path=<file>` на ребёнке применяет глобальный
   `publish` БЕЗ per-process overlay рецепта (boot мержит, reload — нет).
4. Мелкие протечки: опечатки в `metrics`-ключах — тихий no-op (E); осиротение covered-подписок (F);
   гигиена `_last_pass`/`_pending` (G).

Цель плана: **один частотный авторитет, дельта-семантика, boot ≡ reload** — и закрытие долга
простоты (вырезать legacy-путь GUI, поднять read-model во framework). Фаза 1 — **блокер Фазы 4
GUI** плана telemetry-publish-control (крутилки частоты нельзя строить поверх лестницы, где две
из трёх ступеней не управляются, а «точечная» правка сносит защиту).

**Предусловие:** незакоммиченные фиксы ревью в working tree ветки feat/telemetry-publish-control
(`driver.py`, `assembler.py`, `_panels.py`, `process_manager_process.py`) закоммитить ДО ответвления.

---

## Фаза 1 — Частотный авторитет + дельта-семантика (БЛОКЕР Фазы 4 GUI)

### Task 1.1 — Дельта-семантика telemetry-переконфигурации (`mode: merge|replace`) ✅ DONE (92d6f6f6)
**Level:** Senior (Opus)
**Assignee:** teamlead
**Layer:** framework
**Goal:** «точечная» правка меняет ровно одно правило/метрику, не стирая остальные — на ОБЕИХ плоскостях (закрывает находку A + известный residual «publisher-plane full-apply»).
**Files:** `multiprocess_framework/modules/process_module/managers/telemetry_reload.py`,
`multiprocess_framework/modules/process_module/heartbeat/process_heartbeat.py`,
`multiprocess_framework/modules/process_module/commands/builtin_commands.py`,
`multiprocess_framework/modules/process_manager_module/process/process_manager_process.py`,
`backend_ctl/driver.py`, tests рядом с каждым.
**Steps:**
1. `apply_telemetry_reconfigure(section, *, mode="replace"|"merge", ...)`: `replace` — текущее
   поведение (backward-compat, дефолт); `merge` — дельта поверх живого состояния.
2. Publisher-плоскость в `merge`-режиме: heartbeat хранит текущую effective-секцию
   (`gate._config` уже фактически есть — сделать её источником), `reconfigure_telemetry(delta,
   mode="merge")` строит новый gate из `deep_merge(current_effective, delta)`.
3. Throttle-плоскость в `merge`-режиме: `update_rule(pattern, interval)` per-правило вместо
   `set_rules` (значение `null`/спец-маркер в дельте → `remove_rule`). Оживает мёртвый API PC 0.1.
4. Прокинуть `mode` сквозь `telemetry.reconfigure` / `telemetry.broadcast` / `config.reload`
   (`data["telemetry_mode"]` или ключ в секции — выбрать одно, задокументировать).
5. `backend_ctl.telemetry_set` переключить на `mode="merge"` (он и обещает точечность);
   `telemetry_reconfigure` — оставить `replace`-дефолт, добавить параметр `mode`.
6. Убрать из docstring `telemetry_set` предупреждение о full-apply (заменить описанием merge);
   добавить предупреждение о wipe в `replace`-ветку `telemetry_reconfigure`.
**Acceptance:**
- [x] Тест: `telemetry_set(plane="throttle", metric=X, interval_sec=Y)` меняет ТОЛЬКО правило X — остальные правила (`rules`-снимок до/после) не тронуты — `test_telemetry_commands.py::test_throttle_merge_changes_only_target_rule`, `test_telemetry_reload.py::test_merge_updates_single_rule_keeps_others`
- [x] Тест: `telemetry_set(plane="publisher", metric="fps", enabled=False)` выключает только fps — прочие `metrics`-override живого gate сохранены — `test_telemetry_reconfigure.py::test_merge_preserves_other_metric_overrides`, `test_telemetry_commands.py::test_publish_merge_keeps_other_metric_overrides`
- [x] Тест: `mode="replace"` бит-в-бит воспроизводит прежнее поведение (характеризация) — `test_telemetry_reload.py::test_replace_mode_calls_set_rules`, `test_telemetry_reconfigure.py::test_replace_mode_wipes_other_overrides`, `test_telemetry_driver.py::test_replace_default_omits_mode_on_wire`
- [x] Тест: merge-удаление правила (маркер `None`) реально зовёт `remove_rule` и правило исчезает — `test_telemetry_reload.py::test_merge_none_marker_removes_rule`, `test_telemetry_commands.py::test_throttle_merge_none_removes_rule`
- [x] grep: `update_rule`/`remove_rule` имеют продакшн-потребителя (`telemetry_reload.py::_apply_throttle`, не только тесты)
**Out of scope:** тик heartbeat (Task 1.2), персист дельты через hot-swap (Task 3.2), GUI.

> **Контракт `mode` (решение teamlead, 92d6f6f6):** `data["telemetry_mode"]` — ключ-СОСЕД `publish`/`throttle` (НЕ внутри секции), т.к. секция уходит в config-билдеры (`TelemetryPublishConfig.from_dict`) и должна оставаться чистым config-dict. На проводе присутствует ТОЛЬКО при `merge` (`replace` — прежний конверт бит-в-бит, backward-compat старых сообщений). Маркер удаления throttle-правила — `None` (JSON null; `0` остаётся валидной «полной блокировкой»). `publish_section=None` выключает gate НЕЗАВИСИМО от mode.

### Task 1.2 — Тик публикации в telemetry-контракте (`publish.tick_sec`) ✅ DONE (03449743)
**Level:** Senior (Opus)
**Assignee:** teamlead
**Layer:** framework
**Goal:** частота публикации управляется telemetry-контрактом (boot + runtime), а не захардкоженным `heartbeat_interval=5.0` — закрывает находку D (верхняя ступень лестницы).
**Files:** `multiprocess_framework/modules/process_module/configs/telemetry_publish_config.py`,
`multiprocess_framework/modules/process_module/heartbeat/process_heartbeat.py`,
`multiprocess_framework/modules/process_module/heartbeat/telemetry.py`, tests.
**Steps:**
1. `TelemetryPublishConfig.tick_sec: float | None = None` — период телеметрийного тика;
   `None` → прежний `heartbeat_interval` (backward-compat).
2. Вариант реализации — выбрать teamlead'ом и зафиксировать в DECISIONS: (а) heartbeat-воркер
   тикает `min(heartbeat_interval, tick_sec)`, heartbeat-сообщение PM шлётся по своему прежнему
   расписанию (счётчик тиков), телеметрия — по `tick_sec`; ИЛИ (б) отдельный воркер
   `telemetry_publisher` со своим `stop_event.wait(tick_sec)`. Критерий: heartbeat-контракт с
   ProcessMonitor (liveness) НЕ меняет частоту — иначе ложные «process dead».
3. `reconfigure_telemetry` применяет новый `tick_sec` живьём (перевзвод интервала ожидания
   воркера; допустимо срабатывание на следующем тике).
4. Валидация: `interval_sec < tick_sec` у метрики — WARNING-лог «частота метрики ограничена тиком»
   (не тихий no-op).
**Вариант реализации (ADR-PM-016):** выбран **(а)** — один heartbeat-воркер тикает `min(heartbeat_interval, tick_sec)`, телеметрия каждый тик (gate rate-limit), heartbeat-СООБЩЕНИЕ + health/obs/GC по расписанию liveness (`_heartbeat_due`, порог `tick/2`). Отвергнут (б) отдельный воркер (второй lifecycle + дубль снимка воркеров + дележ health/obs/GC).
**Acceptance:**
- [x] Тест (fake-clock/интеграция): `tick_sec=0.5` → телеметрийный merge выходит ~2 Гц при `heartbeat_interval=5.0`; heartbeat-сообщения PM остаются ~0.2 Гц — `test_telemetry_tick.py::TestCadenceFastTelemetry::test_telemetry_two_hz_heartbeat_stays_slow` (20 merge/2 hb за 10с)
- [x] Тест: `tick_sec=None` → каденция публикации бит-в-бит прежняя (характеризация) — `test_telemetry_tick.py::TestCadenceBackwardCompat` (телеметрия = такт heartbeat)
- [x] Тест: runtime-смена `tick_sec` через `telemetry.reconfigure` меняет каденцию без рестарта — `test_telemetry_tick.py::TestRuntimeTickChange` (`_telemetry_tick` 5.0→0.5 живьём + cadence-run)
- [x] Тест: `interval_sec < tick_sec` → WARNING в логе, метрика публикуется на каждом тике — `test_telemetry_tick.py::TestCappedMetricWarning`
- [x] Доп. (замечание ревьюера 1.1): неизвестный `mode` → error-dict, не молчаливый replace — `test_telemetry_reload.py::TestUnknownModeRejected`
**Out of scope:** liveness-контракт heartbeat→ProcessMonitor (частота heartbeat-сообщений не меняется); центральный троттл (Task 1.3).

### Task 1.3 — Центральный троттл: страховка, а не второй авторитет ✅ DONE (173f5ff4)
**Level:** Senior (Opus)
**Assignee:** teamlead
**Layer:** mixed
**Goal:** при активном publisher-gate центральный троттл не может молча отменить поднятие частоты — publisher становится единственным авторитетом частоты (закрывает residual #6 плана telemetry-publish-control + вторую половину находки D).
**Files:** `multiprocess_prototype/backend/state/manager_setup.py` (дефолты),
`multiprocess_framework/modules/process_manager_module/process/process_manager_process.py`
(`_cmd_telemetry_broadcast`), `multiprocess_framework/modules/process_module/managers/telemetry_reload.py`, tests.
**Steps:**
1. Решение владельца из residual #6 — реализовать вариант «дефолт заведомо мягче»: дефолт-правила
   `_default_throttle_rules()` пересчитать относительно эффективного тика (например 2×
   `publish.tick_sec`|мин. publisher-интервал; минимально — задокументированная константа-множитель).
2. В `telemetry.broadcast`/`telemetry.reconfigure` при merge-применении publisher-дельты с
   `interval_sec` НИЖЕ central-правила той же метрики — автоматически ослабить central-правило
   (через `update_rule` из Task 1.1) ЛИБО вернуть в результате явный `capped_by_throttle`-флаг
   (выбрать одно; «no silent caps» обязателен).
3. Задокументировать инвариант в `multiprocess_framework/DECISIONS.md` (ADR: «троттл — страховка,
   publisher — авторитет») + `python -m scripts.sync`.
**Решение step 2 (teamlead):** выбран **`capped_by_throttle`-флаг**, НЕ auto-relax (зафиксировано ADR-PM-017). Auto-relax молча снёс бы операторскую страховку (runaway-публикатор авто-снял бы защиту); дефолт-мягкость (step 1) уже обеспечивает «частота реально растёт» в дефолт-сценарии без жертвы страховкой. ADR — в `process_module/DECISIONS.md` (серия ADR-PM-*, консистентно с 1.1/1.2), в global-индекс проброшен через `scripts.sync` (`ADR-PM-001…017`).
**Acceptance:**
- [x] Тест: поднятие частоты метрики через publisher (interval < central-правила) → эффективная частота в дереве РЕАЛЬНО растёт (сквозной тест store+gate) ИЛИ инициатор получает явный `capped_by_throttle` — `test_integration.py::TestManagerSetup::test_raised_publisher_frequency_reaches_store_via_soft_default` (реально растёт при мягком дефолте) + `test_telemetry_broadcast.py::TestCappedByThrottle::test_publisher_raise_below_central_rule_is_flagged` (флаг при строгом операторском правиле)
- [x] Тест: дефолт-правила не режут дефолтную каденцию публикации (характеризация текущих рецептов) — `test_integration.py::TestManagerSetup::test_soft_defaults_do_not_cut_publisher_cadence`
- [x] ADR в индексе, `scripts/validate.py` чист — ADR-PM-017, `validate.py` зелёный (ADR-дрифт синхронизирован)
- [x] Доп (finding-1 ревью 1.2): битый mode → `success=False` через все 3 хендлера — `test_telemetry_broadcast.py::TestUnknownModeRejected`, `test_telemetry_commands.py::TestUnknownModeSurfaced` (reconfigure+config.reload)
**Out of scope:** полное удаление центрального троттла (остаётся как IPC-страховка от сбойного публикатора).

### Task 1.4 — Cap-детекция на адресном (per-process) пути ✅ DONE (f64a6700)
**Level:** Senior (Opus)
**Assignee:** teamlead
**Layer:** framework
**Goal:** адресный `telemetry.reconfigure` к ОДНОМУ ребёнку (не broadcast) либо тоже детектит
`capped_by_throttle`, либо осознанно и громко отказывает в поднятии частоты — вместо текущего
молчания (cap там сейчас не детектится вообще, см. ADR-PM-017 Known-gap). **БЛОКЕР per-process
крутилки частоты в Фазе 4** плана telemetry-publish-control (broadcast-путь уже покрыт Task 1.3,
поэтому Фаза 1 в целом закрыта — но эта задача обязательна ДО появления per-process
GUI-регулятора частоты).
**Files:** `backend_ctl/driver.py` (`telemetry_reconfigure` — точка ветвления адресный/broadcast,
`telemetry_set` docstring — обновить под выбранный вариант),
`multiprocess_framework/modules/process_manager_module/process/process_manager_process.py`
(потенциальная точка перехвата, если решение — маршрутизировать адресную команду через PM),
`multiprocess_framework/modules/process_module/commands/builtin_commands.py`
(`_cmd_telemetry_reconfigure` — сегодняшняя точка приёма на ребёнке, `_resolve_store_throttle`
всегда `None`), `multiprocess_framework/modules/process_module/managers/telemetry_reload.py`
(`detect_throttle_caps` — переиспользовать, не дублировать логику), tests рядом с каждым.
**Steps:**
1. Зафиксировать причину пробела: адресный `telemetry.reconfigure` сегодня уходит от driver'а
   НАПРЯМУЮ ребёнку (`driver.py::telemetry_reconfigure`, ветка `process not in (None, "all", "*")`)
   — PM не в пути, перехватывать нечем; на ребёнке `resolve_store_throttle(self)` всегда `None`
   (central-троттл живёт только на оркестраторе) — `detect_throttle_caps` там принципиально
   невозможен без изменения маршрута.
2. Выбрать один из двух вариантов (решает teamlead, зафиксировать в DECISIONS):
   - (а) **Перехват в PM** — адресную `telemetry.reconfigure` тоже пускать транзитом через PM
     (аналогично broadcast), чтобы PM мог вызвать `detect_throttle_caps` с СВОИМ
     `resolve_store_throttle(self)` до форварда конкретному ребёнку и вернуть `capped_by_throttle`
     в результате адресной команды;
   - (б) **Осознанный явный отказ** — маршрут не меняется (адресная команда идёт ребёнку напрямую),
     но `telemetry_set(plane="publisher", ...)` на КОНКРЕТНЫЙ процесс с интервалом, который заведомо
     ниже известного central-правила, возвращает громкий `error`-dict («per-process raise
     недоступен без видимости central-правил — используй `process="all"`»), а не молчаливый success.
3. Реализовать выбранный вариант; обновить докстринг `telemetry_set`/`telemetry_reconfigure`
   (`backend_ctl/driver.py`) под факт.
4. Обновить ADR-PM-017 (`process_module/DECISIONS.md`): Known-gap закрыт (вариант а) либо
   переформулирован в «осознанное ограничение» (вариант б) + `python -m scripts.sync`.

> **Решение teamlead (2026-07-17): вариант (а) «перехват в PM».** Вариант (б) «явный отказ»
> отвергнут — он не разблокировал бы per-process крутилку Фазы 4 (она как раз про адресное
> поднятие частоты ОДНОМУ процессу), ради которой Task 1.4 и делается. Реализация: и адресный,
> и fan-out путь driver'а теперь идут транзитом через PM (`telemetry.broadcast`); адресный кейс
> помечается `data["target"]=<процесс>` — PM детектит `capped_by_throttle` СВОИМ
> `resolve_store_throttle(self)` (переиспользован `detect_throttle_caps`, не дублирован) и
> форвардит `publish` ОДНОМУ ребёнку через новый примитив `_send_child_command`
> (`comm.send_to_process`); `throttle` применяется центрально (троттл оркестратор-глобален).
> Прямой driver→child путь ретрополнен (на нём cap был принципиально не детектируем).
> **Trade-off:** адресный путь стал fire-and-forward — per-child `applied` заменён охватом
> `reached` 0/1 (синхронный сбор ответа ребёнка в хендлере PM дедлочил бы message_processor).
> Зафиксировано в ADR-PM-017 (Amendment Task 1.4).

**Acceptance:**
- [x] Тест: адресный `telemetry.reconfigure` (один процесс, НЕ `"all"`) с publisher-interval ниже
  известного central-правила → `capped_by_throttle` в результате (вариант а) — НЕ тихий success —
  `test_telemetry_broadcast.py::TestAddressedViaPm::test_addressed_publish_below_central_rule_is_flagged`
  (+ адресация к одному ребёнку `test_addressed_publish_sends_to_single_child_not_broadcast`,
  throttle центрально `test_addressed_throttle_applies_centrally`, драйвер-маршрут
  `test_telemetry_driver.py::TestTelemetryReconfigureAddressing::test_addressed_process_routes_via_pm_with_target`)
- [x] Регресс: broadcast-путь (`process="all"`, Task 1.3) не сломан — `test_telemetry_broadcast.py`
  зелёный без изменений своей логики (fan-out ветка нетронута; `target in (None,"","all","*")` → прежнее поведение)
- [x] ADR-PM-017 обновлён (Known-gap → Amendment «закрыт, вариант а»), `scripts/validate.py` чист (ADR-синхронизация OK)
**Out of scope:** GUI-крутилка частоты (сама реализация UI — Фаза 4 плана
telemetry-publish-control); изменение дефолтных central-правил (Task 1.3 закрыта, не трогаем).

---

## Фаза 2 — Когерентность контракта (boot ≡ reload, видимые ошибки)

> **✅ ФАЗА 2 ЗАКРЫТА** (ветка `feat/telemetry-coherence-phase2`, коммиты ff8d5745 · dc7594e6 ·
> 93589f7f merged bab99c10; ревью-фиксы ab9a5a9b + fresh-read). Task 2.3 исполнен параллельным
> агентом в worktree, слит без конфликтов. Гейт: 853 тестов process_module+app_module зелёные,
> ruff + pyright чисто.
>
> **Ревью (Sonnet + Opus, 2 итерации) — исправлено:**
> - HIGH (Sonnet): watcher откатывал троттл на несвязанной перезагрузке файла → diff-гейт.
> - major A+B (Opus): (A) сид `last_throttle` boot-декларацией — закрыт silent-cap на 1-м reload
>   при сконфигурированном throttle; (B) КЛЮЧЕВОЕ — watcher-`Config` аддитивен (`Config.update` =
>   `deep_merge`), удалённый throttle оставался stale → `make_telemetry_on_reload` теперь читает
>   throttle СВЕЖИМ из `config_path` (как ручной `config.reload`), удаление/сброс реально видны;
>   тесты переписаны на реальные файлы (репрезентативно проду, не свежие `Config`).
> - minor C (Opus): расхождение семантики отсутствующего throttle-ключа watcher↔ручной
>   `config.reload` — оставлено осознанно: watcher — декларативный boot≡reload-путь (сброс при
>   реальном удалении), ручная команда трогает только явно присутствующие секции (не клоббит
>   runtime-дельту на несвязанном ручном reload). Задокументировано.
>
> **Долги (отдельные тикеты, не блок):** 2 golden `test_build_characterization` (дифф в
> `orchestrator_config`, есть на origin/main, не телеметрия); `pyqtgraph` в pyproject, не в `.venv`.
> Следующее — Фаза 3 (гигиена + долг простоты).

### Task 2.1 — Единая семантика `throttle: {}` на boot и hot-reload ✅ DONE (ff8d5745)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Layer:** mixed
**Goal:** один и тот же YAML даёт одно и то же состояние троттла при рестарте и при hot-reload (закрывает находку B).
**Files:** `multiprocess_framework/modules/process_module/managers/telemetry_reload.py`
(`apply_telemetry_reconfigure`, `make_telemetry_on_reload`),
`multiprocess_prototype/backend/state/manager_setup.py`, tests.
**Steps:**
1. Зафиксировать семантику (предложение): пустой/отсутствующий `throttle` ВЕЗДЕ означает
   «дефолт-правила» — `apply_telemetry_reconfigure` при `section["throttle"] in (None, {})` ставит
   дефолты, а не `set_rules({})`. Для явного «снять все правила» ввести отдельный маркер
   (например `throttle: {"__clear__": true}` или отдельная команда).
2. Дефолты доставить в framework-слой без обратного импорта прототипа: колбэк/значение
   `default_rules` передаётся в `make_telemetry_on_reload(...)` и хранится
   `apply_telemetry_reconfigure`-вызывающими (источник — `build_throttle_rules`).
3. Удаление throttle-секции из файла при reload → тоже возврат к дефолтам (сейчас — stale).
**Acceptance:**
- [x] Тест: `throttle: {}` через watcher/config.reload → живые правила == `_default_throttle_rules()` (та же таблица, что при boot)
- [x] Тест: явный clear-маркер → правила пусты
- [x] Тест: reload файла БЕЗ throttle-ключа после кастомных правил → дефолты (не stale) — через diff-гейт (throttle реально удалён из файла)
**Out of scope:** publish-плоскость (её семантика None/dict не меняется).

### Task 2.2 — `config.reload` из файла: сохранить per-process overlay ✅ DONE (dc7594e6)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Layer:** mixed
**Goal:** file-reload телеметрии на ребёнке даёт тот же effective-конфиг, что и рестарт (закрывает находку C).
**Files:** `multiprocess_prototype/backend/assembly/assembler.py`,
`multiprocess_framework/modules/process_module/commands/builtin_commands.py` (`_cmd_config_reload`), tests.
**Steps:**
1. Assembler при наличии per-process override кладёт его ОТДЕЛЬНО в
   `proc_dict["config"]["telemetry_override"]` (сырая дельта рецепта) — рядом с уже собранной
   merged-секцией `telemetry`.
2. `_cmd_config_reload` в файловом фолбэке: `effective = deep_merge(loaded["telemetry"],
   get_config("telemetry_override") or {})` (мержится только `publish`-часть; `throttle` — как есть).
3. inline-путь (`data["telemetry"]`) НЕ трогать — явная секция от оператора применяется как есть.
**Acceptance:**
- [x] Тест: процесс с recipe-override `metrics.fps.enabled=false` после `config.reload path=system.yaml` сохраняет override (gate.resolve("fps") == (False, ...)), глобальные изменения из файла применены
- [x] Тест: процесс без override — поведение бит-в-бит прежнее (характеризация)
- [x] Golden-снапшоты build: новый ключ `telemetry_override` появляется ТОЛЬКО у процессов с override (проверено юнит-фикстурами `test_assembler.py`; живых рецептов с override пока нет — синтетика)
**Out of scope:** watcher-fan-out publisher-gate детям (Task 3.2), персист runtime-дельты (Task 3.2).

### Task 2.3 — Валидация `metrics`-ключей против GATED_METRICS ✅ DONE (93589f7f)
**Level:** Middle (Sonnet)
**Assignee:** developer
**Layer:** framework
**Goal:** опечатка в имени метрики — видимая диагностика, не тихий no-op (закрывает находку E).
**Files:** `multiprocess_framework/modules/process_module/configs/telemetry_publish_config.py`,
`multiprocess_framework/modules/process_module/heartbeat/telemetry.py` (экспорт `GATED_METRICS` —
разорвать потенциальный циклический импорт: константу перенести в configs либо в отдельный модуль), tests.
**Steps:**
1. `TelemetryPublishConfig.unknown_metrics() -> set[str]` — ключи `metrics` вне `GATED_METRICS`.
2. WARNING-лог со списком неизвестных ключей в местах сборки gate (`_build_telemetry_gate`,
   `reconfigure_telemetry`) и в результате `telemetry.reconfigure` (`{"unknown_metrics": [...]}` —
   видно инициатору backend_ctl/GUI).
3. НЕ отвергать секцию (forward-compat: новые метрики в старом процессе не должны ронять reload).
**Acceptance:**
- [x] Тест: `metrics: {latency: {...}}` → WARNING с точным именем + `unknown_metrics=["latency"]` в ответе команды; gate строится, известные метрики работают
- [x] Тест: все ключи известны → ни WARNING, ни поля в ответе
**Out of scope:** белый список как hard-fail; изменение состава GATED_METRICS.

---

## Фаза 3 — Гигиена + долг простоты

> **✅ ФАЗА 3 ЗАКРЫТА** (ветка `feat/telemetry-coherence-phase2`). 3.1/3.3/3.4/3.5 DONE; 3.2 частично
> (шаг 3 fan-out отложен). 3.3/3.4/3.5 исполнены параллельными агентами (worktree), 3.1/3.2 — основной
> тред. Гейт: ruff+pyright чисто; ~1900 backend + 1030 frontend/PM/throttle зелёные (2 pre-existing
> env-провала: bare-import `frontend_module.*` в patch, pyqtgraph 0.14.0 — оба на origin/main).
>
> **Ревью (Sonnet многоугловое → Opus целенаправленное):**
> - Sonnet: HIGH (interfaces.py F822 — пропущен импорт реэкспорта) + 3 MED (restart_process не доигрывал
>   дельту; нет интеграционного теста apply_topology→replay; lazy-prune слепа к `interval=0`-правилам) →
>   всё исправлено `906bafa7`.
> - Opus: APPROVE-with-nits; 3 Sonnet-фикса подтверждены; оси read-model/concurrency/covered-subs/3.1×2.2
>   чисты по коду. Реальная находка — персист хранил лишь ПОСЛЕДНЮЮ дельту (при ≥2 merge respawn терял
>   предыдущие) → исправлено аккумуляцией `deep_merge` `555e6caa`.
>
> **Follow-up тикеты (не блок):** (1) шаг 3 Task 3.2 — watcher fan-out publish с per-child override-мержем;
> (2) known-gap смешанных merge→replace-цепочек в персисте (replace сбрасывает накопленное — приемлемо);
> (3) minor pre-existing: серверная семантика `state.unsubscribe` для async/реактивированных covered-подписок
> (sub_id локальный uuid4 vs серверный — потенциальный orphan, унаследован из штатного async-subscribe, не от 3.3).

### Task 3.1 — Типизировать `ProcessConfig.telemetry` (убрать raw-blueprint pre-scan) ✅ DONE (43368466)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Layer:** mixed
**Goal:** per-process telemetry — typed-поле схемы, а не чтение сырого dict до `model_validate` (vector #3, часть 1).
**Files:** framework-схема процесса blueprint (`SystemBlueprint`/`ProcessConfig` в
`data_schema_module` — уточнить точный модуль по `SystemBlueprint.model_validate`-пути),
`multiprocess_prototype/backend/assembly/assembler.py` (`_extract_per_process_telemetry` — удалить), tests.
**Steps:**
1. Объявить `telemetry: dict | None = None` (или typed `TelemetrySection`) в `ProcessConfig`.
2. Assembler читает `topology.processes[i].telemetry` после валидации; raw pre-scan удалить.
3. Характеризация: build-снапшоты обоих живых рецептов не меняются.
**Acceptance:**
- [x] Тест: per-process override доезжает до `get_config("telemetry")` (существующие тесты overlay зелёные без raw-скана)
- [x] grep: `_extract_per_process_telemetry` отсутствует
- [x] Golden-снапшоты `test_build_characterization.py` без диффа proc_dict'ов
**Out of scope:** семантика merge (не меняется), другие поля ProcessConfig.

### Task 3.2 — Персист runtime-дельты в PM + fan-out publisher-gate из watcher ⚠️ ЧАСТИЧНО (c0b6e01b: шаги 1-2-4; шаг 3 отложен)

> **Шаги 1, 2, 4 DONE** (c0b6e01b): PM хранит `_telemetry_runtime_delta`, доигрывает после `apply_topology`
> (residual #7 закрыт), `publish=None` broadcast сбрасывает персист. **Шаг 3 (watcher фанит publish-часть
> детям) ОТЛОЖЕН** — обнаружен клоббер-риск: `_broadcast_command` рассылает publish ВСЕМ детям единообразно
> (`comm.broadcast`), затирая per-process override, сохранённый Task 2.2 (boot≢reload для процесса с override).
> Корректный fan-out требует per-child мержа override (адресные send'ы с `telemetry_override` каждого ребёнка
> ИЛИ merge на стороне ребёнка) — отдельное решение владельца, пересекается с семантикой операторского
> broadcast (тот тоже uniform). Acceptance-тест «правка publish файла → у детей пересобран gate» — под шагом 3.
**Level:** Senior (Opus)
**Assignee:** teamlead
**Layer:** framework
**Goal:** runtime-правка телеметрии переживает hot-swap/respawn детей, а правка файла доезжает до publisher-gate детей (закрывает известный residual #7, известный follow-up «file-watch fan-out», усиливает Task 2.2).
**Files:** `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py`,
`multiprocess_framework/modules/process_module/managers/telemetry_reload.py`
(`make_telemetry_on_reload`), `multiprocess_framework/modules/app_module/orchestrator.py`, tests.
**Steps:**
1. PM хранит `_telemetry_runtime_delta` (последняя применённая publish-дельта/секция + mode из
   Task 1.1) — обновляется в `_cmd_telemetry_broadcast`.
2. После `apply_topology`/respawn PM доигрывает сохранённую дельту новым детям адресным
   `telemetry.reconfigure` (или общим broadcast) — runtime-состояние ≡ до свитча.
3. Watcher оркестратора: `make_telemetry_on_reload` дополнительно фанит `publish`-часть детям через
   готовый примитив `_broadcast_command` (гейт от шторма: только при реальном изменении секции —
   сравнение с последней применённой).
4. Явная команда сброса дельты (`telemetry.reset` или `publish=None` broadcast) очищает персист.
**Acceptance:**
- [x] Тест: broadcast-дельта → hot-swap рецепта → у пересозданного ребёнка gate отражает дельту (не boot-дефолт)
- [ ] Тест: правка publish-секции файла → watcher → у детей пересобран gate (mock-children/охват)
- [x] Тест: повторный reload файла БЕЗ изменений секции → 0 broadcast'ов (нет шторма)
- [x] Тест: сброс дельты → respawn берёт boot-конфиг
**Out of scope:** персист на диск (только память PM); throttle-плоскость (живёт в оркестраторе, respawn её не теряет).

### Task 3.3 — Covered-подписки: ре-адопция при снятии покрывающего паттерна ✅ DONE (d1cb407c)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Layer:** framework
**Goal:** covered-подписка не остаётся молча без потока при unsubscribe покрывающей (закрывает находку F).
**Files:** `multiprocess_framework/modules/state_store_module/proxy/state_proxy.py` (`unsubscribe`), tests.
**Steps:**
1. В `unsubscribe` при снятии последнего sub_id подтверждённого паттерна: найти covered-подписки,
   которые покрывал ТОЛЬКО он (`_covered_sub_ids` × `pattern_covers`), и для каждой — либо
   переусыновить на другой подтверждённый покрывающий, либо отправить собственный async-subscribe
   (паттерн 0.2), убрав sub_id из `_covered_sub_ids`.
2. Лог с маркером `[re-adopt]` + счётчик (наблюдаемость как у async-subscribe).
**Acceptance:**
- [x] Тест: subscribe wildcard (sync) → ensure узкого (covered) → unsubscribe wildcard → узкому отправлен собственный `state.subscribe` (spy-router)
- [x] Тест: два покрывающих — снятие одного НЕ создаёт новой подписки (переусыновление)
- [x] Регресс: прежние coverage-тесты зелёные
**Out of scope:** серверная сторона; sync-ре-подписка (только async — инвариант «0 блокирующего IPC»).

### Task 3.4 — Гигиена ThrottleMiddleware: чистка таймингов мёртвых путей ✅ DONE (d7670228)
**Level:** Middle (Sonnet)
**Assignee:** developer
**Layer:** framework
**Goal:** `_last_pass`/`_pending` не растут бессрочно через hot-swap'ы и не сбрасывают stale-значения при flush (закрывает находку G).
**Files:** `multiprocess_framework/modules/state_store_module/middleware/throttle.py`,
`multiprocess_framework/modules/state_store_module/manager/state_store_manager.py` (вызов при
удалении поддерева — если есть delete-путь), tests.
**Steps:**
1. `prune(prefix)` — удалить тайминги/pending путей под префиксом (звать при удалении поддерева
   процесса из дерева, если такой хук есть; иначе — периодический lazy-prune по размеру:
   при `len(_last_pass) > N` выбросить записи старше max-интервала правил × K).
2. `flush()` — отдавать pending с меткой возраста ЛИБО отбрасывать записи старше порога
   (задокументировать выбор), чтобы shutdown не писал давно исчезнувшие значения.
**Acceptance:**
- [x] Тест: prune по префиксу убирает тайминги/pending только своего поддерева
- [x] Тест: рост словарей ограничен при потоке уникальных путей (lazy-prune срабатывает)
- [x] Регресс: 40 тестов test_throttle.py зелёные
**Out of scope:** семантика троттла (интервалы/правила не меняются).

### Task 3.5 — Read-model во framework + вырезание legacy bind-пути
**Level:** Senior (Opus)
**Assignee:** teamlead
**Layer:** mixed
**Goal:** «любое приложение получает телеметрию даром» — и на read-стороне: VM+HistorySource во `frontend_module`, оставшиеся вкладки на VM-паттерне, legacy-пути удалены (vector #4, возврат балла «простоты»).
**Files:** `multiprocess_prototype/frontend/state/telemetry_view_model.py` и
`telemetry_history.py` → `multiprocess_framework/modules/frontend_module/...` (+ interfaces.py,
README, STATUS, tests — правило проекта №2), `multiprocess_prototype/frontend/widgets/tabs/`
(devices/calibration/recipes/settings — миграция), `multiprocess_prototype/frontend/state/bindings.py`
(`cache_snapshot`-replay), `multiprocess_prototype/frontend/widgets/tabs/processes/_panels.py`
(legacy-ветки `_connect_bindings_legacy`), tests.
**Steps:**
1. Перенос VM+HistorySource во frontend_module (generic: tracked_suffixes/путь БД — параметры);
   прототип — тонкая конфигурация. Слои импортов не нарушать (framework не знает прототип).
2. Мигрировать оставшиеся вкладки на VM-паттерн (тем же способом, что «Процессы» Task 1.3
   gui-telemetry-read-model).
3. Вырезать: legacy-ветки панелей, `cache_snapshot`-replay из `GuiStateBindings`, мёртвые точечные
   bind'ы. Инвариант-тест вкладок остаётся зелёным.
4. Возможен сплит на 3.5a (перенос) / 3.5b (миграция+вырезание) — решает teamlead при декомпозиции.
**Acceptance:**
- [x] `test_tab_open_invariant.py` зелёный для всех вкладок ПОСЛЕ вырезания legacy
- [x] grep: `_connect_bindings_legacy` / `cache_snapshot` отсутствуют в прототипе
- [x] Импорт-границы: `mcp__sentrux__check_rules` чист (frontend_module не импортирует прототип)
- [ ] qt-smoke по правилу `feedback_qt_mcp_smoke_verification`: proto + qt_snapshot, все вкладки живые
**Out of scope:** новый функционал вкладок; формат доставки дельт (ADR-COMM-001 не трогаем).

---

## Уже известные follow-ups — размещение в этом плане

| Известный residual | Куда вошёл |
|---|---|
| publisher-plane full-apply (`telemetry_set` пересобирает секцию целиком) | **Task 1.1** (mode=merge закрывает обе плоскости) |
| две плоскости троттла с равными дефолтами каскадируют (residual #6) | **Task 1.3** |
| file-watch fan-out publisher-gate детям | **Task 3.2** (шаг 3) |
| runtime-дельта теряется при hot-swap (residual #7) | **Task 3.2** (шаги 1–2) |
| Task 3.1 gui-read-model: дуальный VM/legacy-путь не вырезан | **Task 3.5** |

Windows test-debt (2 фейла app_module) — вне скоупа, отдельный тикет (pre-existing).

---

## Финальная приёмка (Fable holistic, Фазы 1-3, 2026-07-18)

Холистическое балльное ревью всей системы телеметрии по диффу `origin/main..HEAD` + Фаза 1 (main).
Траектория оценки: **24 → 42 → 47 из 60**. Вердикт: **цель плана достигнута, к merge в main готова с оговорками**.

| Ось | После | Δ от 42 | Кратко |
|---|---|---|---|
| Архитектура (когерентность) | 8/10 | +2 | Лестница управляема на 3 ступенях, ADR-PM-016/017, cap-детекция на обоих путях, boot≡reload |
| Паттерны | 8/10 | +1 | Один идемпотентный apply-путь, дельта-маркеры, diff-гейт свежего файла, MVVM read-model |
| Модульность | 8/10 | +1 | GATED_METRICS в configs, typed telemetry, generic VM+History во framework |
| Эффективность | 7/10 | +1 | lazy-prune одна len()-проверка, коалесинг сигнала, единый снимок; бенчей частотного пути нет |
| Безопасность/надёжность | 8/10 | +1 | SQL whitelist+параметризация, silent no-op → наблюдаемые, thread-контракт prune |
| Стиль/согласованность (простота) | 8/10 | +3 | legacy вырезан, один read-model, образцовые «почему»-комментарии |

**Оставшиеся долги (follow-up тикеты, НЕ блок merge, кроме qt-smoke):**

| # | Sev | Что | Куда |
|---|---|---|---|
| W1 | MED | Watcher не фанит publish-plane детям (шаг 3 Task 3.2) — декларативность лестницы не замкнута | реши ДО Фазы 4 GUI |
| W2 | MED | Адресные per-process runtime-дельты не персистятся → respawn теряет точечную правку | вместе с W1 (per-child overlay) |
| W3 | LOW/MED | cap-детекция матчит по суффиксу-листу → wildcard-лист операторского правила невидим (возможен тихий срез) | WARNING или абзац в ADR-PM-017 |
| W4 | LOW | `_stale_age_threshold` = K×max(интервал) глобально — редкое правило 60с раздувает порог гигиены | per-rule порог (опц.) |
| W5 | LOW→страт. | `GATED_METRICS` закрыт для приложений — своя метрика приложения = «опечатка»-WARNING; предел универсальности конструктора | стратегический тикет |
| W6 | LOW | ~~дрифт DEFAULT_TRACKED_SUFFIXES vs GATED_METRICS в докстринге~~ — **исправлено** (докстринг уточнён) | ✅ закрыт |
| qt | — | qt-smoke Task 3.5 (`feedback_qt_mcp_smoke_verification`) — не выполнен | до/сразу после merge |

**Vs commercial best practices:** publisher-gate+tick_sec = аналог OTel Views+MetricReader, ВЫШЕ типового по
явной cap-диагностике между слоями; read-model (ring+SQLite-ro) — коммерческий уровень. Отставание — до
desired-state контроллер-паттерна (W1 + персист только в памяти PM) и расширяемость реестра метрик (W5).

---

## Verification (весь план)

1. **Сквозной частотный тест** (главный, закрывает суть плана): смена частоты метрики через
   `backend_ctl.telemetry_set` проходит ВСЕ три ступени — эффективная частота обновлений пути в
   дереве StateStore реально меняется в обе стороны (вверх и вниз), либо инициатор получает явный
   cap-сигнал. Ни одного тихого no-op.
2. Точечная правка (обе плоскости) не трогает соседние правила/метрики (снимок до/после).
3. boot ≡ reload: один YAML → одно состояние (троттл и publish, с per-process override).
4. hot-swap: runtime-дельта воспроизводится на пересозданных детях.
5. `python scripts/validate.py` + `python scripts/run_framework_tests.py` + тесты прототипа зелёные
   (эталон: 2 pre-existing Windows app_module); sentrux не хуже baseline
   (`session_start` до Фазы 1 → `session_end` после Фазы 3); инвариант-тест вкладок зелёный.
6. qt-smoke после Фазы 3 (правило `feedback_qt_mcp_always_probe`): `QT_MCP_PROBE=1`, вкладки живые.

## Риски

| Риск | Митигация |
|---|---|
| Task 1.2 ломает liveness (ProcessMonitor считает процесс мёртвым при смене тика) | Инвариант в acceptance: частота heartbeat-СООБЩЕНИЙ не меняется; телеметрийный тик — отдельный контур |
| mode=merge усложняет контракт (третий параметр) | `replace` — дефолт, бит-в-бит характеризация; merge включается только явно (driver `telemetry_set`) |
| Auto-ослабление central-правила (1.3) прячет страховку | Альтернатива в задаче — явный `capped_by_throttle`; выбор зафиксировать ADR |
| Watcher-fan-out (3.2) даёт broadcast-шторм на каждый reload | Гейт «только при изменении секции» — под тестом (0 broadcast'ов без диффа) |
| Перенос VM во framework (3.5) тянет Qt-зависимость framework-слоя | frontend_module УЖЕ PySide6-слой framework; проверить `check_rules` |
| Миграция вкладок (3.5) — регрессии в редко открываемых вкладках | Инвариант-тест + qt-smoke каждой вкладки; сплит 3.5a/3.5b |
| Параллельные агенты склеивают коммиты | Правило `feedback_parallel_agents_commit_race`: макс 2 без worktree; фазы — последовательно |

## Порядок и трассируемость

- Фазы строго последовательно: 1 → 2 → 3; внутри фазы задачи параллелятся с оглядкой на риск коммит-гонки.
- Каждый коммит: `Refs: plans/telemetry-coherence-remediation.md` + trailers `Why:`/`Layer:` (hook отклонит без них).
- Закрытие задачи: `[x]` + hash в этом файле (правило `feedback_plan_checkboxes`).
- **Фаза 4 GUI плана telemetry-publish-control НЕ стартует до закрытия Фазы 1 этого плана.**
