---
name: project_webcam_sketch_freeze
description: "webcam_sketch: вкладка Processes вешает GUI намертво — это Qt-C++ стойл (не Python, доказано stall-дампом); отдано Фабле на ревью; topology.load() кэш + перф-фиксы применены"
metadata:
  node_type: memory
  type: project
---

**Задача-хвост (2026-07-15, отдана Фабле на ревью).** Рецепт `webcam_sketch` =
клон `phone_sketch` с источником вебкамера (`CapturePlugin` вместо `PhoneCameraPlugin`,
ориентация точек через `robot_scale.swap_axes`, как в phone_sketch). Работает, но
**открытие вкладки «Процессы» вешает GUI намертво**.

**Диагноз (доказан, не гипотеза):** фриз — **Qt-уровень (C++), НЕ Python.**
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

**Фабле — направления:** (A) бисект ProcessesTab: по очереди отключать trace-box /
таблицы воркеров / live-биндинги (`_panels.py`), ловить виновный виджет; (B) WinDbg на
зависший PID gui → нативный C++-стек. Presenter/bindings уже прочитаны: биндинги приходят
в GUI-поток (QueuedConnection, `bindings.py:395`), телеметрия троттлится 1Гц
(`build_throttle_rules`) — флуд исключён.

Связано: [[feedback_qt_widget_patterns]], [[feedback_qt_mcp_smoke_verification]], [[project_processes_tab]].
