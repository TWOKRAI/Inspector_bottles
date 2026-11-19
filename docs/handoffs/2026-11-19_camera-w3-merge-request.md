# Камера W3 — запрос на слияние в main и стык с полосой Ф (лид К, сессия `inspector-bottles-4c`, 2026-11-19)

Адресаты: координатор и лид Ф. Файл, не сообщение (правило полосы). Слот слияния на этом Mac недоступен: `machine.lock` нет, `machine_gate.sh merge-begin` отказывает (код 2, «нет координатора»). `main` стоит в worktree `lane-f-merge` (полоса Ф), поэтому лид К в `main` не пишет. Слияние делает тот, кто держит слот `main`.

## Что готово к слиянию

| Ветка | HEAD | Что | Ворота |
|---|---|---|---|
| `feat/camera-2-3c` | `fc4aa1cca` | Task 2.3c (команды Р7 без порта) | ревью Opus раунд 3 — APPROVED, 11 мутаций из 11 по прогнозу |
| `feat/camera-2-3d` | `a28c03897` | Task 2.3d (содержит 2.3c; в неё влиты `fc4aa1cca` и `main` `767d61329`); последний коммит — тестовая фикстура `declarations_snapshot` (см. ниже) | ревью Opus раунд 2 — APPROVED (диф до `82e479760`; позже только доки и conftest) |
| `feat/camera-device-w3` | этот коммит (см. `git rev-parse feat/camera-device-w3`) | только документы: план 2.3c/2.3d, handoff К, стенд `camera_device_demo`, отчёты | код не затрагивает |

Ветки 2.3c и 2.3d — ff-совместимы по порядку: `feat/camera-2-3c` → `feat/camera-2-3d` → `feat/camera-device-w3`. `git merge-tree` (2026-11-19): `main` + `feat/camera-2-3d` без конфликтов; `feat/camera-2-3d` + `feat/camera-device-w3` без конфликтов; `feat/camera-2-3d` + `feat/run-state-2-2c` без конфликтов.

Тесты на дереве `feat/camera-2-3d` (`machine_gate.sh medium`, основной `.venv`, Mac): `Services/camera_device/tests` — 371 passed, 10 skipped, 0 failed, 3 прогона подряд (52,8 / 52,2 / 52,6 с); `Services/hikvision_camera/tests` + `multiprocess_framework/modules/tests/test_one_connector_per_point.py` — 306 passed, 15 skipped. Три каталога одной сессией (`Services/camera_device/tests` + `Services/hikvision_camera/tests` + `test_one_connector_per_point`) на `a28c03897`: 677 passed, 25 skipped, 0 errors, rc 0, два прогона подряд (57,4 / 57,2 с). Подробности и открытое — `docs/reports/2026-11-19_camera-device-service_W3.md`.

Сводные файлы (`ORDER.md`, индекс ADR, `python -m scripts.sync`) правит слот слияния. `scripts.sync --check` на ветке 2.3d — «ADR-документация синхронизирована».

## Найдено при слиянии (не из 2.3c/2.3d): утечка реестра объявлений метрик

Те же три каталога одной сессией на ветке до `a28c03897` давали 677 passed + 1 error на teardown `framework_metric_catalogue_guard` (`multiprocess_framework/modules/tests/conftest.py:51`): лишние метрики `dropped`, `errors`, `frames`, `param_errors_count`, `pending`. Воспроизведено на чистом `main` (`767d61329`): `Services/camera_device/tests/test_plugin_observability.py` + `test_one_connector_per_point.py` → 37 passed, 1 error. Причина: плагин камеры (2.3b, в `main`) зовёт `ctx.declare_metric`, тесты не возвращали реестр; `Services` входит в `testpaths` (`pyproject.toml`), поэтому ошибку получал и общий `make test`. Правка — `Services/camera_device/tests/conftest.py`: autouse-фикстура `declarations_snapshot` (близнец `Plugins/sim/robot_host/tests/conftest.py`). После правки: пара — 37 passed, три каталога — 677 passed.

## Для лида Ф: стык по `plugin_base.py`

Ветка `feat/run-state-2-2c` (`99a9e84d5`, readiness камеры) правит `Services/camera_device/plugin_base.py` — файл полосы К. Её слияние — только после 2.3c/2.3d в `main`. Когда 2.3c и 2.3d в `main` (это решает держатель слота), Ф сливает 2.2c и проверяет, что readiness не ломает `Services/camera_device/tests/test_plugin_*` и `test_live_apply_*` (371 passed — исходная точка). Место под readiness — ниже `cmd_get_status` (по контракту Ф от 11-17).

Открытое для Ф по 4.2a: контракт readiness для плагина камеры — файлом (хук `readiness(ctx)`, ключ `run_locked_commands`, политика `readiness: {hold_s, severity}`). Предложение К по `run_locked_commands`: блокировать в running `release_device`, `take_device`; не блокировать `apply_params`, `read_params`, `get_status`, `list_devices`, `describe_params`, `reset_stats`, `trigger_software`. Итог решает владелец.

## Чего К не делает без слова

W4 (4.2a, 4.2b, 4.3, 4.4, 6.1, 6.3) — без слова владельца. Временные деревья (`cam-2-3c-tester`, `cam-2-3d-tester`, `cam-2-3c-inj`, `cam-2-4b-dev` и т. п.) — только по слову владельца.

## Что осталось открытым / ненадёжно

- Слияние в `main` не сделано: нет слота. Срок «2.3c/2.3d в `main` к железу ≈ 2026-11-22» держится на том, кто сольёт.
- Код возврата прогона 2 из трёх не зафиксирован (есть итоговая строка 371 passed, 0 failed).
- Конфликты слияния проверены `git merge-tree` на состоянии 2026-11-19; если `main` сдвинется, перепроверить.
- Остатки без владельца-решения записаны в `docs/claude/OPEN_QUESTIONS.md` (две строки от 2026-11-19): DEBUG-утечка значения в `set_field_value`; `bindings()` вне `try` в `cmd_apply_params`.
