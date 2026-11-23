# Стартовый промпт — Полоса Д2 — диагностика красных на macOS, хвосты полосы Д (координатор inspector-bottles-9e, 2026-11-19)

Сводка веток, порядок слияния и общие правила — `2026-11-19_lane-prompts-index.md`. Вставлять блок ниже в новый чат целиком.

```
ВКЛАДКА: Полоса Д2 · красные PM-тесты на macOS → реестр хвостов Д
ROLE: lead of lane Д2 (дефекты), реестр plans/queue/defects.md (читать из main), статус из git main. Полоса Д закрыта 2026-11-16 (`d89188e7b`).
READ FIRST: docs/reports/2026-11-16_lane-D_summary.md и docs/reports/2026-11-16_lane-D_qr-reader-order-dependency.md (в main); plans/queue/defects.md (C-36, C-91, C-92, C-82, C-85); docs/reports/2026-11-17_system-run-state_lane-f-checkpoint.md §2 п.1; docs/claude/OPEN_QUESTIONS.md.
GOAL: четыре независимые задачи без железа, каждая — своя ветка от main, свой конвейер; по порядку. Слот писателя занимает только на п.3–4.
ЗАДАЧИ:
  1. Диагностика: `multiprocess_framework/modules/process_manager_module/tests` целиком — 141 failed + 5 errors одинаково на базе (`c6bae7d09`) и на ветке Ф (`7c3cbede4`), на macOS. Гипотеза Ф: реальные spawn + POSIX-семафоры (OSError 28). Нужно: воспроизвести ОДНИМ прогоном (два параллельно дают 546–582 красных из-за перегрузки), сгруппировать красные по причине, отделить «платформа macOS» от «настоящий дефект», дать лиду Ф список файлов, которые можно гонять по отдельности. Только diagnose-and-report (investigator/debugger); код PM не править — это Ф.
  2. C-36 (дополнить): system-очередь ребёнка гибнет навсегда после kill (стенд C-92: kill №99 `camera_0`, №103 `consumer_0`; ~0,4 % на kill; ребёнок глух, `routing.refresh` теряется, супервизор показывает `running`) — шире C-36. Дополнить строку реестра; воспроизвести детектором «`routing.refresh` … потеряна`»; fix-forward в framework — отдельной задачей после диагностики (investigator → teamlead), не в обход.
  3. Красные из «попутно найдено» итога Д: 6 в `multiprocess_prototype` (`test_integration::test_shutdown_cleans_proxy`, `test_entities_roundtrip::test_every_pick_key_reaches_framework_from_domain`, `test_app_foundation_names`, `test_gui_process`, `test_headless_process`, `test_system_dashboard`) и `test_unapplied_metadata_check::test_m10_recipe_set_is_the_known_22` (23 рецепта вместо 22). Сначала проверить на чистом main (на main не проверялось), потом реестр, потом чинить причину.
  4. Системное решение по `PluginRegistry.discover()` после `clear()`/`restore()` (контракт реестра): teamlead/владелец; до решения класс остаётся хрупким. Остаточные хвосты Д: `stop_all_workers` (`core/worker_manager.py:228-253`) не берёт `_start_lock` (2 такта из 80), остаточный риск D2d в `_spawn_thread_locked`.
ГРАНИЦЫ: не писать в `process_manager_process.py` и `launcher/spawner.py` (Ф), `Services/camera_device` (К), вкладку робота и `Services/device_hub` (Р2/Пульт), `multiprocess_prototype/frontend/widgets/tabs/services/robot/`. Файлы, где диагностика и Ф пересекаются, — список лиду Ф до правки (его имя — в первой строке ЕГО `ListAgents`; сейчас живой сессии Ф нет — писать файлом в `plans/queue/inbox/`).
PIPELINE: «Task launch convention» (cite): стадия 0 reviewer sonnet, слепой tester один раз на механизм ДО кода, инъекции с предсказаниями до прогона, ревью, стенд числами; для диагностики п.1 — investigator (haiku-инвентарь логов первым, brief < ~100K).
LOAD: координатор — первая строка `ListAgents` координатора (сейчас `inspector-bottles-9e`); первое сообщение — своё имя сессии. Mac, `machine.lock` нет: все прогоны через `machine_gate.sh` (абсолютный путь), heavy — только в своём окне; свой `INSPECTOR_PID_FILE`.
COMMITS: Conventional Commits + Why:/Layer:/Refs: plans/queue/defects.md (или план задачи); слияние отдельным коммитом `feat(...)`; Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>; stage явных путей.
LIMITS: 2 итерации на петлю, на третьей вверх; красный, которого нет в `defects.md`, блокирует слияние — регистрировать.
REPORT: `docs/reports/<дата>_lane-D2_<задача>.md`, по-русски, числа, непустое «что осталось открытым / ненадёжно».
ОТКРЫТО ДЛЯ ВЛАДЕЛЬЦА: решения по C-82 (три, `plans/queue/inbox/2026-11-01_inspector-bottles-ca_2.md`) — не здесь, Ф; решение по контракту `PluginRegistry.discover()` — п.4.
```

