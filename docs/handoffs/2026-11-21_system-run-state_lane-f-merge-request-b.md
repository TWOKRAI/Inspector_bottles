# Запрос на слияние: коммит B 2.1 (`run_gate: true`) — полоса Ф (2026-11-21)

Автор: лид полосы Ф (сессия inspector-bottles-b8). Отчёт: `docs/reports/2026-11-21_system-run-state_lane-f-stand.md`. Слияние делает координатор; в main я не коммитил.

| Ветка | HEAD | Основа | Layer слияния |
|---|---|---|---|
| `feat/run-state-2-1-commit-b` | `68b4a026d` (было `1fbefc6d8`; rebase на main `96fb1ea59`, конфликтов 0, не запушена) | main `96fb1ea59` | `prototype` |

Состав (`git diff main --stat`): 4 файла, +8/−8 — `system.yaml` (`run_gate: true`), golden `hikvision_letter_robot` и `phone_sketch` (только `run_gate`; перегенерация `UPDATE_BUILD_SNAPSHOTS=1` без изменений), литералы в `test_run_gate_manifest.py`. Тема слияния — `feat(prototype): merge …` + `Why:`/`Layer:`/`Refs: plans/2026-10-27_system-run-state/plan.md`; сообщение из файла (`git merge -F -` stdin не читает).

## Числа по условиям (tasks/2.1.md, «Условия слияния коммита B»)
- (1) heavy на дереве main + `run_gate: true`: `test_recipe_service_live` 1 passed (7,7 с), `…_restart_live` 1 passed (10,8 с), `test_frame_bridge_live` 1 passed (7,0 с).
- (2) `start_run` до apply: ready 3,85 с, 0 кадров за 8 с; `run_start` → running 0,01 с, 152 кадра за 5 с; apply/activate в running — `error: "running"`; `run_stop` → ready 0,19 с (рецепт `bridge_synth`, без камеры и пульта).
- Offline на `68b4a026d`: backend 345 passed/18 skipped, recipes 214/5, stand_gate 105, capacity_bench 79, harness_run_gate 22; красных 0.

## Что B ломает (подтверждено живьём; п.3 условий)
`frontend/run.py --headless` (нет `--autostart`), `alpha_sim/run_alpha.py` без `--autostart`, `bootstrap()`-вызывающие (`smoke_proof`, `telemetry_probe`, `telemetry_sink_proof`, `tools/otel_stand/*`), GUI-зонды — встают в `ready` без кадров. `run.py --headless` закрыт флагом.

## Что нужно от координатора
1. Слово на слияние B: ДО слияния — малый патч `--autostart` в `frontend/run.py` и `run_gate` kwarg в `bootstrap()`/`from_topology_path` (файлы прототипа вне зоны Ф, нужен писатель) ИЛИ слияние с записью «не покрыты» (`OPEN_QUESTIONS` 2026-11-21, стенд).
2. Перед слиянием: golden заново на актуальном main, если main уйдёт от `96fb1ea59` (рецепты/Пульт); `backend/tests`, `recipes/tests` на слитом дереве.
3. Решения владельца: кто шлёт START для GUI-зондов (`tasks/2.7.md:59`); уровень WARNING `diverged` (R3c).
4. Стенд R3c — отдельная строка, B не блокирует: WARNING за 25 с 104,3 (до) → 1 (после), diverged 24–34 %.
