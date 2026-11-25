# Передача: стенд на коде волны 1 (дорожка K, 2026-11-25)

Читатель: новая сессия Claude Code. Задача: запустить стенд на камерах и проверить волну 1 вместе с владельцем.

## Разрешение и границы
- Владелец сказал запускать стенд в новом чате (2026-11-25). Перезапуск процессов и стенда — по его слову.
- Старый чат продолжает волну 2. Не пиши в деревья `mco-integ`, `mco-d-*`, `mco-plan2`.
- Код не правь. Замечания пиши в `D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/docs/reviews/2026-11-25_stand-wave1.md`, не коммить.
- Ответы владельцу по-русски, простыми словами.
- Не `taskkill /IM`. Остановка — `system_shutdown` (backend_ctl).

## Полный прогон тестов объединённой ветки
Статус на 13:58: **окно под стенд открыто.**

- `scripts/run_framework_tests.py` на `91193ab39` + передача: 3 failed, 14676 passed, 47 skipped, 2 xfailed.
  - `logger_module/tests/test_std_logger_guard.py` — красный был до волны 1.
  - `tests/test_gc_policy_guard.py` — `gc.collect` в двух тестах прототипа (тракт кадров GUI), волна 1 их не меняла.
  - `tests/test_declarations_leak_order_independence.py` — причина не установлена, разбор после стенда. Это про независимость тестов от порядка, не про поведение на стенде.
- `Services` на `ea65a3334`: 8405 passed, 28 skipped, 2 xpassed, 0 красных.
- `scripts/validate.py` на `ea65a3334`: ошибок и предупреждений нет.
- `Plugins` на `ab615c933` (14:53–15:08): 1 failed, 2812 passed, 4 skipped, 1 xfailed.
  `test_no_silent_swallows_in_plugins`: 10 мест в `device_hub`, `frame_buffer`, `frame_saver`, `robot_io`,
  `word_layout`. Красный до волны 1: `git diff main..HEAD -- Plugins` пуст.
- `multiprocess_prototype` (15:08–15:14): 1 failed, 5344 passed, 14 skipped.
  `test_catalog_kind_roundtrip`: в эталоне нет `robot_io.forward_ok` и `robot_io.last_dropped_job`
  (поля добавлены `be4e63783`, до волны 1).
- Итого не разобран один красный: `test_declarations_leak_order_independence`.

## Дерево стенда
`D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.claude/worktrees/mco-stand` — detached `ea65a3334` (`integ/multicam-obs`: волна 1 слита целиком, включая две последние правки считывателя).

## Запуск (Git Bash, в фоне)
```bash
cd /d/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.claude/worktrees/mco-stand
MAIN=/d/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles
D=logs_live/k_wave1; mkdir -p $D
bash "$MAIN/scripts/machine_gate.sh" status
env PYTHONPATH="$PWD" BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 QT_MCP_PROBE=1 PYTHONUTF8=1 INSPECTOR_LOG_DIR=$D \
  bash "$MAIN/scripts/machine_gate.sh" heavy inspector-bottles-K "$MAIN/.venv/Scripts/python.exe" \
  multiprocess_prototype/frontend/run.py hikvision_id3013_quad --autostart > $D/stdout.txt 2>&1
```
- Окно берётся так: `machine_gate.sh request inspector-bottles-K stand <минуты> "<что>"`, потом `release`. Код выхода 75 — команда не запускалась.
- Не `uv sync`. Убедись по логу, что код взят из `mco-stand`, а не из основной копии.
- Приборы: `camera_0` DA1689923 (.20, gain в рецепте не задан), `camera_1` DA1689977 (.5, gain 23), считыватели `.10` и `.11` (у `.11` самотриггер).

## Что проверить (волна 1)
1. **Личность камеры.** В логе строка `CameraDevicePlugin: device opened ...`; в state плагина камеры ключи `identity` и `stream`. Если прибор виден через две сетевые карты — WARNING о дубле перечисления и выбрана запись в подсети камеры.
2. **Потери кадров.** Метрики `incomplete`, `lost_packets`, `lost_frames`, `trigger_lost` (есть и при нуле). `reset_stats` их обнуляет.
3. **Триггер считывателя на ходу.** `set_register_verified` для `trigger_mode` / `trigger_period_ms` / `trigger_source`: захват перезапускается, в логе строка `CodeReaderSdkPlugin[<id>]: apply field=...`. Проверь отказ узла: должен быть откат к прежнему режиму и `degraded`. Команда `set_config` подписчиков не будит — известный предел, не пользуйся ею для этой проверки.
4. **Имя процесса в логах.** Строки плагина с фазы `configure` содержат имя процесса.
5. **Не проверено на железе:** MAC и `nTriggerIndex = 0 -> None` у камеры; длительность перезапуска захвата считывателя.

## Что волна 1 НЕ меняет (не считать новым дефектом)
- Выдернутый кабель камеры: тишина, состояние `grabbing`, сама не восстанавливается. Считыватель восстановился сам, но тоже молча. Это волна 2 (W2-a, W2-b, W2-c).
- Замерший кадр вместо «нет сигнала» — волна 2.
- Перезапуск процесса в прогоне поднимает `fault` и останавливает все источники. Выход: «Квитировать», затем «Запустить» (`run_ack`, `run_start`). Не проверено: оживает ли после этого перезапущенная камера. Перед выводом «всё зависло» читай `system.run`. Разбор: `docs/reviews/2026-11-25_incident-restart-freeze.md` (в дереве `mco-integ`).
- `release_device` / `take_device` в прогоне отказывают всем, включая MCP (ADR-PM-062).

## Ориентиры с утреннего прогона (`main` `743641727`)
Камера 25 fps; GUI принимает ~131 кадр/с, показывает ~82/с; GUI ~0,72 ядра; RSS 453–942 МБ (разброс не объяснён).
