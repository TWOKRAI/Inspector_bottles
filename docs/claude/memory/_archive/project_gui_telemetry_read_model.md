---
name: project_gui_telemetry_read_model
description: "GUI read-model телеметрии ЗАКРЫТ 2026-07-16 (Фазы 0-3, ADR-136): запись-всегда/чтение-локально/история-по-запросу, TelemetryViewModel, инвариант-тест 0 блокирующего IPC; follow-up telemetry-publish-control"
metadata:
  node_type: memory
  type: project
---

**План `plans/gui-telemetry-read-model.md` ЗАКРЫТ 2026-07-16** (ветка `feat/gui-telemetry-read-model`,
Фазы 0-3; коммиты c0b2eb4a/194ccbd0/b1c1f581/a2039360/de9486c2/dd5f992b/9050387f/4d33e21d). Реактивирует
Option D из `plans/telemetry-delivery-simplification.md` (теперь SUPERSEDED — Option D реализован как
read-model поверх работающего потока дельт, не как отдельный snapshot-канал).

**Триггер:** открытие вкладки «Процессы» фризило GUI на ~5с. Диагноз (см. [[project_webcam_sketch_freeze]],
уточнено этим планом): корень — не только Qt-C++ стойл, а **блокирующий `router.request` в Qt main thread**
на КАЖДЫЙ уникальный паттерн подписки (шторм ~60-150 подряд, дедуп по точной строке при уже активных
покрывающих wildcard'ах) + deep-copy всего дерева состояния на каждый replay + жадная постройка N панелей.

**Принцип (зафиксирован ADR-136, `multiprocess_framework/DECISIONS.md`):** «запись — всегда, чтение —
локально, история — по запросу» (паттерн вкладки «Наблюдаемость», ADR-083). Backend публикует телеметрию
постоянно (троттлинг 1 Гц) независимо от открытых вкладок; GUI держит ОДИН локальный read-model, наполняемый
ОДНИМ wildcard-потоком, заведённым при старте; виджеты читают только локально.

**Механизмы (Фазы 0-2):**
- **Coverage-check** (`state_proxy.py::ensure_subscription`) — новый паттерн, покрытый уже ПОДТВЕРЖДЁННЫМ
  (`_confirmed_patterns`) активным паттерном, не создаёт новую подписку (glob-матчер `pattern_covers`).
- **Async subscribe** (`subscribe(..., sync=False)`) — непокрытые паттерны уходят fire-and-forget из
  `bindings._ensure`, ни одного `router.request` из main thread; отказ сервера логируется (не тишина).
- **Prefix-replay** (`_replay_initial_state`) — копирует `get_subtree(prefix)` статического префикса
  паттерна, а не весь корень (`get_subtree("")`).
- **`TelemetryViewModel`** (`multiprocess_prototype/frontend/state/telemetry_view_model.py`) — единственный
  локальный read-model GUI: второй потребитель wildcard-потока дельт (`bridge.add_state_listener`),
  батч-сигнал `updated(list[tuple[path,value]])` (коалесинг, не по каждой дельте), `get`/`snapshot` для
  late-binding без похода на сервер, `history()` — кольцевые буферы ~10 мин по числовым метрикам
  (fps/latency/uptime/hz/cycle). Панели «Процессов» (`_panels.py`) переведены на VM — в VM-режиме НЕ зовут
  `bind`/`ensure_subscription` на телеметрию вообще (легаси-путь сохранён для немигрированных вкладок).
- **`TelemetryHistorySource`** (`telemetry_history.py`) — read-only pull из `telemetry.db` (пишет плагин
  `telemetry_sink`) для глубины за пределами ring-буфера: даунсемпл, whitelist метрик (закрыта SQL-инъекция
  через имя метрики), отказоустойчиво к отсутствию БД; чтение вне main thread через `RequestRunner`.
- **Debounce + lazy panels** — обнаружение runtime-воркеров коалесируется `QTimer.singleShot(50)`; открытие
  вкладки строит только активную `SingleProcessPanel`, не N панелей на N процессов.

**Enforcement:** `test_tab_open_invariant.py::test_opening_all_tabs_does_no_blocking_ipc` — все 7 вкладок
через `register_all_tabs()` поверх РЕАЛЬНОГО `GuiStateBindings`/`GuiStateProxy` со spy-router; красный при
появлении блокирующего `router.request` или неподтверждённого серверного `state.subscribe` на покрытом пути.

**Осознанно НЕ сделано (Task 3.1, решение Director 2026-07-16):** дуальный VM/legacy-путь в `_panels.py` и
`cache_snapshot`-replay в `GuiStateBindings` НЕ вырезаны — зависят немигрированные вкладки
(devices/calibration/recipes/settings/...). Инвариант уже enforced coverage-check'ом для ВСЕХ вкладок
независимо от миграции на VM; удаление кода — «меньше слоёв», не смена поведения. Отдельная задача: миграция
остальных вкладок тем же VM-паттерном по мере надобности.

**Follow-up (отдельный план, решение владельца 2026-07-16): `plans/telemetry-publish-control.md`.**
Этот план — про дешёвое GUI-**чтение**; follow-up — про управление **публикующей** стороной (частота
опроса per-параметр/группу, вкл/выкл через statistics manager, чтобы не грузить систему). Кирпичи уже
есть: per-паттерн троттл `build_throttle_rules()` (сейчас хардкод) → сделать config-driven; observability
control-plane ([[project_observability_control_plane]]) — готовый канал рантайм-изменений;
`ObservableMixin` per-slot тумблеры — есть, не проброшены в hot-reload-конфиг. Не хватает: троттл из
конфига, вкл/выкл публикации метрики/группы, fan-out на дочерние процессы.

**Почему (мотивация):** read-model поверх УЖЕ РАБОТАЮЩЕГО потока дельт (self-publish, см.
[[project_telemetry_self_publish]]) — меньший риск и объём работы, чем полная переделка канала доставки
(отклонённый Option D-as-snapshot-channel: третий data-plane путь бэкенд→GUI против унификации).
**Как применять:** для НОВОЙ вкладки с телеметрией — сразу читать `TelemetryViewModel` (get/snapshot/history),
НЕ заводить точечные `bindings.bind()` на пути телеметрии процессов (coverage-check это не запретит технически,
но плодит легаси-путь, который план сознательно не вырезал). Для истории глубже ring-буфера — читать через
`TelemetryHistorySource`, не через прямой SQL к `telemetry.db`.

Связано: [[project_telemetry_self_publish]], [[project_webcam_sketch_freeze]], [[project_processes_workers_runtime]], [[project_observability_control_plane]].
