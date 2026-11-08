# C-30 · финальное слияние `fix/recipe-save-noise` в локальный main · 2026-11-08

Сессия inspector-bottles-93 (полоса Д, macOS). Решение владельца 2026-11-07: «merge да, push нет».

## Итог

- Влито fast-forward: `main` = `bb5d53330` (до слияния `a5eb6d382`). 55 файлов, +3532/−126 относительно `a5eb6d382`.
- `git push` не выполнялся: `origin/fix/recipe-save-noise` занята сессией `-48`, хук sentrux красный и на main. `main` впереди `origin/main` на 87 коммитов.
- Main уходил вперёд трижды за время работы (`50010cdb4` → `5db2a4d51` → `a5eb6d382`); ветка трижды подтягивала его merge-коммитом (`173897d22`, `353f94b3f`, `bb5d53330`). Один конфликт — `docs/claude/OPEN_QUESTIONS.md`, обе дописанные записи оставлены.

## Прогоны (интерпретатор `.venv` 3.12, `QT_QPA_PLATFORM=offscreen`, через `machine_gate.sh heavy`; на Mac `machine.lock` нет)

| Прогон | Дерево | Результат |
|---|---|---|
| `scripts/validate.py` | ветка `173897d22` | 3 FAIL: память-теги, индекс `BY-MODULE*.md`, G6 R6 `close_coordinator.py:95` |
| `scripts/validate.py` | main `50010cdb4` | те же 3 FAIL |
| `scripts/validate.py` | ветка `bb5d53330` и main `5db2a4d51` | по 2 FAIL (память-теги, `BY-MODULE*.md`); G6 R6 снят коммитом `5db2a4d51` соседней полосы |
| `multiprocess_prototype/backend/tests` | `173897d22` | 282 passed, 18 skipped (в handoff 11-07 было «298» — другой набор) |
| framework suite (`run_framework_tests.py --continue-on-collection-errors`) | ветка `173897d22`, 19 мин 45 с | 164 failed, 12553 passed, 48 skipped, 7 errors |
| framework suite | main `5db2a4d51`, 22 мин 38 с | 89 failed, 12531 passed, 48 skipped, 4 errors |
| точечно 218 тестов (объединение красных обоих прогонов) | main `5db2a4d51` | 10 failed, 208 passed (10 мин 30 с) |
| то же | ветка `353f94b3f` | **те же 10 failed**, 208 passed (10 мин 17 с); разности красных 0 в обе стороны |
| `recipe/tests` без `test_yaml_patch.py` | `bb5d53330` | 361 passed, 5 skipped |
| `test_stand_substitute_m1_m2.py` (замена M1/M2) | `bb5d53330` | 5 passed |

## Сверка красных с `plans/queue/defects.md` и inbox

- validate, память (теги и `BY-MODULE*.md`): красные на чистом main; заявка `plans/queue/inbox/2026-11-06_inspector-bottles-28_2.md` (C-13 вернулся) — записано.
- G6 R6 `close_coordinator.py:95`: красный на main `50010cdb4`, в реестрах не было; починен на main коммитом `5db2a4d51`.
- Шум полного framework suite (разброс красных 89 ↔ 164 между прогонами, ветка ↔ main): `OSError(28, 'No space left on device')` в `create_queues` на Mac при свободных ГиБ — заявка `plans/queue/inbox/2026-11-07_inspector-bottles-e8_2.md`. Мои два прогона это подтверждают: полные списки красных расходятся в обе стороны (`process_manager_module` 100/85, `shared_resources_module` 0/64), а те же тесты по отдельности на обоих деревьях дают одинаковые 10 красных.
- Эти 10 красных (на main и на ветке одни и те же): 6 × `process_manager_module/tests/test_cv_threads.py` и 2 × `config_module/tests/test_watcher.py` — заявка `…e8_1.md` (записана, причина не выяснена); 2 × корневые `tests/test_declarations_leak_order_independence.py::…` и `tests/test_module_tiers.py::test_no_test_dir_is_invisible_to_every_runner` — в моём точечном прогоне запускались из `multiprocess_framework/modules`, в реестрах не найдены, причину не разбирал (возможно артефакт cwd моего прогона).
- `recipe/tests/test_yaml_patch.py` не собирается (нет `hypothesis`): заявка `…e8_2.md`; это НЕ зелёный suite.

## Долг и замена

Записаны в `plans/2026-10-26_recipe-save-noise/plan.md` («Долг на момент слияния») и в строке 3 `plans/queue/ORDER.md`: M1–M3 и M5 «ожидает стенда/камеры»; M1/M2 подкреплены Qt-offscreen ЗАМЕНОЙ (`test_stand_substitute_m1_m2.py`), не стендом.

## Открыто и ненадёжно

- Корневой suite и полный framework suite НЕ перепрогонялись на итоговом `bb5d53330`: последние полные прогоны были на `173897d22` (ветка) и `5db2a4d51` (main), после них влито T1.4 robot_comm (15 файлов `Services/robot_comm`, `robot/v2`) и документы. С моими файлами пересечение — только документы (`ORDER.md`, `OPEN_QUESTIONS.md`, `DECISIONS.md`), после слияния прогнаны validate и `recipe/tests`.
- Список 10 красных точечного прогона не разобран по причинам (сверка «ветка = main» сделана, причина не выяснена; Mac).
- Не прогнано: `sentrux check .` на итоговом дереве (Opus-ревью ветки: 43 правила зелёные на `f5fa8c237`); `ruff`; `test_yaml_patch.py`; POSIX-лок и `test_file_lock.py` вне Windows; `backend_ctl` live-тест хаба.
- Тест-сторож «app.py вызывает capture_foundation» не добавлялся (оставлено на усмотрение лида, в этой ветке не нужен для приёмки).
- Подпись merge-коммитов: хук предупреждает «trailers git does not see» из-за пустой строки перед `Co-Authored-By` в формате сообщения — предупреждение, не отказ.
- Нерешённое у владельца (не трогал): права на кнопку «Сохранить» Камеры, M4, брать ли `_4`, int-ключ `0:`, `sentrux gate --save`, судьба `origin/fix/recipe-save-noise` (`-48`).
