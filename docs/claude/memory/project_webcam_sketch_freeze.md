---
name: project_webcam_sketch_freeze
description: "webcam_sketch: фриз Процессов — уточнён 2026-07-16, ГЛАВНАЯ причина блокирующий IPC-шторм в Qt main thread (не только Qt-C++ стойл); закрыто планом gui-telemetry-read-model / ADR-136"
metadata:
  node_type: memory
  type: project
---

**UPDATE 2026-07-16 (план [[project_gui_telemetry_read_model]], ADR-136):** диагноз ниже («стойло в Qt C++,
Python ни при чём») был **неполным — уточнён и частично опровергнут**. Полная root-cause-цепочка (доказана
по коду, не гипотеза): `ProcessesTab._sync_nav()` жадно строила панели ВСЕХ процессов → каждый `bindings.bind()`
звал `ensure_subscription(pattern)` → **блокирующий `router.request(timeout=5.0)` в Qt main thread** на КАЖДЫЙ
уникальный паттерн подписки (~60–150 подряд; дедуп шёл по точному совпадению строки, хотя покрывающие
wildcard'ы `processes.**`/`system.**` уже были активны) + сервер на каждый subscribe копировал ВСЁ дерево
состояния (`_replay_initial_state` → `get_subtree("")`) + каскад обнаружения runtime-воркеров пересобирал
`WorkerTable` по одному обнаружению. Т.е. **главный вклад в фриз давал Python-уровень (блокирующий IPC-шторм
в main thread), а не только Qt-C++ layout/paint-стойло** на глубокой вложенности панелей (которое тоже
реально и устранено отдельно ленивыми панелями, см. хвост 0.4 плана). Закрыто планом
`plans/gui-telemetry-read-model.md` (Фазы 0-3): coverage-check вместо строкового дедупа + async-subscribe
(`sync=False`) + prefix-replay + единый `TelemetryViewModel` (read-model) + debounce/lazy panels. Инвариант
зафиксирован **ADR-136** (`multiprocess_framework/DECISIONS.md`) и enforced тестом
`test_tab_open_invariant.py::test_opening_all_tabs_does_no_blocking_ipc`.

---

**Исходная запись (2026-07-15, отдана Фабле на ревью), сохранена для истории.** Рецепт `webcam_sketch` =
клон `phone_sketch` с источником вебкамера (`CapturePlugin` вместо `PhoneCameraPlugin`,
ориентация точек через `robot_scale.swap_axes`, как в phone_sketch). Работает, но
**открытие вкладки «Процессы» вешает GUI намертво**.

**Диагноз (доказан, не гипотеза — но НЕПОЛОН, см. UPDATE выше):** фриз — **Qt-уровень (C++), НЕ Python.**
Инструмент: env `INSPECTOR_STALL_DUMP=1` → `faulthandler.dump_traceback_later(5, repeat=True)`
в `run_gui` (app.py) пишет стеки всех потоков в `<INSPECTOR_LOG_DIR>/gui_stall_dump.log`.
Во ВСЕХ 163 срезах main-поток gui — в `app.py:788 app.exec()` **без единого Python-фрейма
сверху** → стойл внутри Qt (layout/paint/внутренний блок), наш Python-код ни при чём.
gui-статы шли ровно (~630/10с) и оборвались РЕЗКО (не деградация). Почему `phone_sketch`
не висел: телефон шлёт кадры редко (по фото), вебкамера — непрерывно → нагрузка выше
(рабочая гипотеза, не доказана).

**Уже применено (uncommitted, ветка `feat/feature-flags-registry`):**
- `adapters/stores/topology_repository.py`: **мемоизация `load()`** — раньше `Topology.from_dict()`
  (полный Pydantic-разбор) на КАЖДЫЙ вызов, а presenter дёргает `load()` десятки раз на открытии
  вкладки (`is_protected`/`get_processes`/`get_workers` на каждую панель/кнопку). Кэш инвалидируется
  в `set_topology`. Убрал Python-лаг «3-4 сек», но НЕ жёсткий C++-фриз. 198 тестов adapters ок.
- Рецепт: TEED `inference_every_n: 2` + `source_target_fps: 25` (нативный темп камеры) → плавно.
- Stall-дамп в app.py (env-gated) — оставить как инфру.

**Data-plane overload (отдельно от фриза):** при `source_target_fps: 60` вылазит
`[lines] DataReceiver: pipeline overload (queue full)` — очередь ЖДЁТ, а не дропает.
Graceful drop-oldest («не успел → выкинул слот») сидит за флагом **`FW_QOS_PROFILES`**
(Ф7 dark-launch, default OFF — см. [[project_feature_flags_registry]]). На 25fps overload'а нет.

**Фабле — направления (частично устарело, см. UPDATE):** (A) бисект ProcessesTab: по очереди отключать
trace-box / таблицы воркеров / live-биндинги (`_panels.py`), ловить виновный виджет; (B) WinDbg на
зависший PID gui → нативный C++-стек. Presenter/bindings уже прочитаны: биндинги приходят
в GUI-поток (QueuedConnection, `bindings.py:395`), телеметрия троттлится 1Гц
(`build_throttle_rules`) — флуд исключён.

Связано: [[feedback_qt_widget_patterns]], [[feedback_qt_mcp_smoke_verification]], [[project_processes_tab]], [[project_gui_telemetry_read_model]].
