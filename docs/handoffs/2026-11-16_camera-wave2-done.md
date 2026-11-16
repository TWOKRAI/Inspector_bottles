# Handoff полосы К — W2 влита, дальше W3 (2026-11-16)

Сессия: `inspector-bottles-9e`, координатор `inspector-bottles-cd`. Отчёт: `docs/reports/2026-11-15_camera-device-service_W2.md`.

## Сделано
- W2 (1.6, 1.8, 2.1, 2.2) влита в локальный `main` слиянием `fdd2b6381` (ветка `feat/camera-device-w2-core`); в `origin` не отправлено. Статусы в `plan.md` — по git: 1.6, 1.8, 2.1, 2.2 `[DONE]`, 0.5 `[PARTIAL]`.
- Поток-владелец и сторож сеанса — воркеры `ctx.worker_manager` (G6 R1 снят без записи в ALLOWLIST).
- «День №1: камера» подготовлен: `docs/handoffs/2026-11-15_day1-camera-checklist.md`, `scripts/day1_capture_check.py`. Вопросы владельцу (числа набора, угол, разрешение, имена каталогов, рецепт capture в git) — у координатора, ответа нет.

## Что осталось открытым / ненадёжно
- Набор реальных кадров дисков (0.5) — только с камерой (≈ 2026-11-22); рецепт capture с `frame_saver` и `set_register`/`save_now` не прогонялся ни на sim, ни на железе (репетиция на синтетике предложена, не поручена).
- Стенд 1.8 на живом процессе подтвердил рост `frames` и штатный останов, но закрытие порта строкой лога не видно (логгер сеанса вне файлов framework — в `tasks/2.3b.md`).
- Плагин ещё не строит `run`/`rest` (пробел плана, пункт в `tasks/2.3a.md`): на стенде профили не пишутся.
- Очереди команд владельца нет: 2.4 строит почтовый ящик (`tasks/2.4.md`, TRAPS).
- Гонка `WorkerManager.start_worker` при живом старом потоке — кандидат fix-forward framework, в `OPEN_QUESTIONS` не внесена.
- `contract.lock` не пересчитан (`TASK_TOO_BIG`/`RESULT_TOO_BIG` у `plans_ledger.py amend`, было до W2).
- Две красные «память» в `validate.py` и три `test_qr_reader_sdk*` в общем прогоне воспроизводятся на чистом `main`.

## Дальше — W3 (по плану, `wave-protocol.md`)
{2.3a, 4.1, 3.1}, затем 2.3b → 2.4 → 3.2. 2.3a теперь включает передачу `run`/`rest` плагином (ACCEPTANCE +1). Стадия 0 у 2.3a и 2.4 (reviewer sonnet), слепой tester до кода у 2.3a и 2.4; перед стадией 0 — решить по драйверу `mvcr` (3.1; зависимость 4.2a → 3.2) с числами (вопрос владельцу из задания полосы). W3 только если успеем — не гнать ради срока.
Для W3: свежий developer (прежний `a738f094c08d4160f` на 405k; брифовать отчётом `docs/reviews/2026-11-15_task-2.1-workers-developer.md`, `…2.2-step2-developer.md` и diff), слепые файлы 2.1/2.2 не править без решения лида.

## agentId (на момент handoff)
developer `a738f094c08d4160f`; reviewer opus `ab2dbf5f15a3c731a` (2.1, 2.2, волна, перенос); investigator opus `ac4065aa94ebc440d`; reviewer стадии 0: 2.1 `af6272af91f5cd418`, 2.2 `ad356db403fd2eef1`; tester 2.1 `a433fc35f149ec601`, 2.2 `a60ec57c220a8e471`; tech-writer `ad06a505bd1734c29` (день №1), `a2aeb5150711a5531` (документы); стенд `ada8bec8efe093249`; test-runner `a6f57ffa7bdffbc14`. Для W3 — свежие, кроме reviewer opus (сессия по W2).

## Рабочие деревья
`.claude/worktrees/{cam-w2, cam-2-1-tester, cam-2-2-tester, cam-2-1-review, cam-main-clean, cam-main-base}` — временные, можно удалить (`git worktree remove`), ветка `feat/camera-device-w2-core` влита.
Перед любым стендом: `INSPECTOR_PID_FILE=/tmp/inspector-bottles-9e_pids.jsonl` и свой `BACKEND_CTL_PORT` (реестр PID общий для соседних полос — предупреждение координатора).
