---
date: 2026-07-07
topic: constructor-master — Ф0 закрыт, Ф1 в работе, трек F (god-split) F.1-F.4 готовы
machine: macOS
branch: feat/constructor-f1 (+ worktree refactor/constructor-godsplit)
---

## Session goal

Старт исполнения мастер-плана `plans/2026-07-06_constructor-master/plan.md` (главная ось:
универсальное → framework, прототип тонкий). Ф0 целиком; Ф1 (backend_ctl v2) и трек F
(god-split) параллельно через делегирование teamlead-агентам с моим ревью.

## Done

- **Ф0 закрыт и вмержен в main (f156589b)**: 0.2 тесты 0 красных (watchdog env-дрейф + tmp_path);
  0.3 sentrux baseline (quality 7174/modularity 5652, min_depth временно 0.60); 0.4 headless-probe
  (FPS hardware-gated, находки: shutdown-hang, BACKEND_CTL≠headless, [ml] extras); 0.5 **GATE G0
  закрыт владельцем** — 13 вердиктов по рекомендациям, ярусы core-15/optional/frozen; 0.6 QUEUE.md
  governing + audit-triage.md (26 позиций аудита затрёкены).
- **Ф1 принято после ревью** (ветка `feat/constructor-f1`): 1.1 событийный канал driver (3f3d36fd),
  1.3 BackendHarness — honest headless, smoke 9.9с (72329d2e), 1.2 обёртки RouterStats/QueueDepths/
  WorkerStatus (8b5fbe26), **1.1b мост push→SocketChannel** в router (8283205d) — state.changed
  теперь доходит до внешнего driver e2e (бывший xfail — зелёный).
- **Трек F принят F.1-F.4** (worktree `../Inspector_bottles_godsplit`): presenter **1860→595 LOC**;
  модули: graph/data.py (Qt-free), graph_codec (391), recipe_io (67, SC-12 закрыт через
  unwrap_recipe), wire_validation (190, Qt-free), runtime_control (277), layout_controller (370),
  mutations (549). 21+ характеризационных тестов ДО разрезов. Полный proto-сьют 2841 passed.
- **Дизайн-заметки**: app_module «рыба» (уровни 0-3, prototype_2 отвергнут) — app-template-idea.md;
  «контактная книжка» (capability manifest v0-v2) — capability-manifest-idea.md; задачи 1.9/1.1b
  вставлены в план. ML-стек установлен (torch 2.12.1 + ort 1.27.0). Пароль админки сброшен
  (пользователь dev; авто-логин через dev_settings.py — пароль в файле, в git не попадает).

## What did NOT work

- **API-нестабильность фоновых агентов** (главная боль конца сессии): 5 обрывов/стойл потока
  («no progress for 600s»/«connection closed mid-response») на агентах F.4/F.5/Ф1.4-1.5.
  Реанимация через SendMessage с картой фактического состояния диска РАБОТАЕТ (F.4 так дожат),
  но стойла повторяются. Урок агентам: «чаще Write на диск, короче пассажи — диск переживает обрыв».
- **`.[ml]` через сборку корневого пакета** — падает (setuptools package discovery); ставить пакеты
  напрямую: `uv pip install onnxruntime onnx torch torchvision`. Плюс сообщение EdgeDetection
  советует `.[ml]`, а torch живёт в `.[ml-torch]` — дрейф подсказки (упомянуть в Ф2).
- **FPS-baseline без железа невозможен** — phone_sketch требует телефон, hikvision камеру;
  честно помечен hardware-gated, повтор на Ф7 G.1.
- **Push state.changed до внешнего сокета не работал архитектурно** (не баг конфига):
  targets=[subscriber]+queue_type=system ищет несуществующую очередь; SocketChannel зовётся только
  channel=-резолвом. Решено мостом 1.1b. ВАЖНО для 1.5: LogRecord-пуш, отправленный С channel-полем,
  уходит channel-резолвом и моста НЕ достигает — слать как DeltaDispatcher: targets+queue_type БЕЗ channel.

## Key decisions made

- G0: FREEZE chain_module/dispatch-фичи/console God-Mode/frontend-флагман; KILL (в Ф8, per-item)
  data_schema-мертвецы и K3-K9; ядро = 15 модулей, не «core-8» аудита.
- app_module: хуки двух сортов (build-time callable / runtime import-path+dict — spawn-safe);
  GenericProcessApp строго в app_module; minimal_app строится одновременно с 5.11/5.12;
  multiprocess_prototype_2 ОТВЕРГНУТ (strangler fig на месте).
- backend_ctl остаётся тулингом на корне (НЕ Services/ — направление зависимостей противоположное);
  на Ф1.7/Ф5 ядро driver.py (framework-clean) может уехать во framework.
- F.4: владение GUI-состоянием осталось в presenter (тесты мутируют поля напрямую) — операции
  в контроллерах через host-ссылку; 595 LOC — честный остаток вместо целевых ~400.
- Правило (в памяти): бэкенд агентам тестировать через backend_ctl/harness, qt-mcp только для GUI.

## In-flight (НЕ закоммичено, агенты оборваны — состояние на диске)

- ~~main checkout, Ф1.4+1.5~~ — **ЗАКРЫТ после написания handoff**: коммиты 09a359d9 (1.4:
  config.reload + logger.sink.enable|disable + tap-инфраструктура, единый путь
  `apply_observability_reconfigure` для watcher и IPC) + 0e102895 (1.5: RouterPushChannel по
  ADR-CRM-006, log_tail/log_untail в driver). Верифицировано: 470 passed (logger+error+process+
  backend_ctl, вкл. 2 live harness_smoke). **Известная граница** (в plan.md:107): tail дочернего
  процесса не доходит до внешнего сокета — канал 'backend_ctl' есть только в router'е PM;
  cross-process relay — кандидат в задачу при 1.7/1.9 или Ф2.
- ~~worktree, F.5~~ — **ЗАКРЫТ после написания handoff**: коммиты 1093aca1 (38 характеризационных
  тестов) + da7c9a5d (factory.py 1190 LOC → пакет kinds/_common/builders_binding/builders_legacy/
  json_editor/__init__; Н-5: `_rm_old_value` ×3 → 1). Верифицировано: forms 95 passed, полный
  proto 2879 passed, дерево чистое. Отклонение от дизайн-дока: реестр KindBuilders НЕ введён
  (заблокирован тест-контрактом `test_register_type_overrides_builder` — `_BUILDERS` обязан остаться
  dict[str, fn]) — отложен в E4/G2 (Ф5.6), записано в plan.md и Rejected-trailer.

## Next step

In-flight пуст — всё закоммичено и верифицировано. Следующая задача: **Ф1.9 контактная книжка v0**
(`introspect.capabilities` в PM + `driver.capabilities()` + `dump_capabilities` →
docs/contracts/CAPABILITIES.yaml + CI-gate; дизайн в capability-manifest-idea.md; команды 1.4/1.5
уже несут metadata.description — войдут в свод). Затем 1.7 (MCP-обёртка; заодно решить cross-process
relay для tail детей) → F.6 (inspector_panel → 5 секций, последний разрез трека F) →
MERGE-GATE F (qt-smoke обоих рецептов + sentrux modularity ≥ 5900 + merge в main).

## Files changed

Закоммичено: см. `git log main..feat/constructor-f1` (8 коммитов) и
`git -C ../Inspector_bottles_godsplit log main..HEAD` (7 коммитов F.1-F.5-тесты).
Незакоммичено (in-flight, main checkout): backend_ctl/driver.py, error_manager.py,
logger_module/{__init__,core/logger_manager,log_enums}.py, builtin_commands.py,
observability_reload.py, + новые: logger_module/channels/router_push_channel.py,
backend_ctl/tests/test_observability.py, logger_module/tests/{test_log_tap,test_sink_control}.py,
process_module/tests/test_observability_commands.py.
Незакоммичено (worktree): frontend/forms/factory/kinds.py.
