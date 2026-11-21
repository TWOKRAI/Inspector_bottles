# Запрос на слияние: патч «--autostart + run_gate в bootstrap()» и коммит B 2.1 — полоса Ф (2026-11-21)

Автор: лид полосы Ф (сессия inspector-bottles-b8). Заменяет заявку `…merge-request-b.md` (там B без патча). Слово координатора 2026-11-21 — вариант (а): патч отдельным коммитом ПЕРЕД B. Слияние делает координатор; в main я не коммитил. `git merge-tree` B с main `2136e0c59`: конфликтов нет.

## Порядок и состав

| # | Ветка | HEAD | Layer | Что |
|---|---|---|---|---|
| 1 | `fix/prototype-headless-start-before-run-gate` | `123d0b47f` (3 коммита: `624b3c240`, `d7e60dee4`, `123d0b47f`; основа `96fb1ea59`) | `prototype` | `--autostart` в `frontend/run.py`; `SystemBuilder.from_topology_path(..., run_gate=None)`; `main.bootstrap(run_gate=False)`; 13 тестов `test_bootstrap_run_gate.py`; докстринги, `frontend/README.md`, `STATUS.md` |
| 2 | `feat/run-state-2-1-commit-b` | `0e099d2f0` (поверх ветки 1) | `prototype` | `run_gate: true` в `system.yaml`, golden (только `run_gate`), литералы в `test_run_gate_manifest.py` (4 файла, +8/−8) |

Сливать 1 → 2 (ветка 2 содержит ветку 1: можно слить одну ветку 2, тогда войдут оба). Тема — `feat(prototype): merge …` + `Why:`/`Layer:`/`Refs: plans/2026-10-27_system-run-state/plan.md`; сообщение из файла.

## Числа
- Конвейер патча (solo, 3 файла кода, ≈ 25 строк): инъекции 8 из 8 по предсказанию (числа и имена красных; предсказания записаны до запуска); ревью Sonnet — APPROVED, 4 minor применены; ревьюер воспроизвёл инъекции (7 из 7) и цепочку `argv → orchestrator_config` на стеке с B.
- Offline: `backend/tests` на патче 358 passed / 18 skipped; на ветке B (до правок ревью) backend 357+, state 102, recipes 214/5, settings 32, frontend 412, stand_gate+capacity_bench+harness_run_gate 206 — красных 0. Один сбой пойман и исправлен: утечка `INSPECTOR_PRESENTATION` из теста `launch()` краснила `test_build_characterization` (3 теста).
- Живой стенд (macOS, сим-линия, дерево B `0e099d2f0`, окно `stand.lock`, снято):

| Путь | Результат |
|---|---|
| `frontend/run.py --headless --autostart letter_robot_sim` | running за 5,2 с; fps camera_0/vision/line 25,0 стабильно ~45 с |
| то же без `--autostart` (контроль) | ready, кадров 0 за 26 с |
| `bootstrap()` (по умолчанию `run_gate=False`), `letter_robot_sim` + сим | state ready, gate False, camera_0/vision/line 25,0 с ~3-й секунды |
| `bootstrap(run_gate=None)` (гейт из yaml = true), контроль | ready, кадров 0 (fps только у pult) |
| `smoke_proof`, `telemetry_probe` (дефолтная топология) | rc 0, ready, кадров 0 — на mac нет веб-камеры, проба кадров не ждёт |
| `tools/otel_stand/task21_proof` | rc 1, 3/3/1 — как на контроле (нет OTel SDK), к гейту не относится |

Ранее (дерево main + `run_gate: true`): `test_recipe_service_live`, `…_restart_live`, `test_frame_bridge_live` — по 1 passed; `start_run` до apply — PASS (отчёт `docs/reports/2026-11-21_system-run-state_lane-f-stand.md`).

## Что НЕ покрыто (не блокер по слову координатора; записано в `OPEN_QUESTIONS`)
`alpha_sim/run_alpha.py` без `--autostart` (оператор сам поднимает прототип; без флага rc 3 через ~120 с); блок `__main__` в `main.py` (там `--autostart` стал бы именем рецепта); `backend_ctl/AGENTS.md:85`, `scripts/run_sim_all.ps1:21`; GUI-зонды `probe_*_live` — по решению владельца START шлёт сам зонд через `run_start`; `bootstrap()` молча перебивает `run_gate` и из yaml, и из `user_overrides.yaml`.

## Что нужно от координатора
1. Слияние 1 → 2; после — `backend/tests`, `recipes/tests` на слитом дереве (main ушёл вперёд на C-99: тесты изоляции env в `backend/tests`; golden сверен — дифф к main только `run_gate`).
2. Стенд свободен: `stand.lock` снят мной в 13:00, порты 8765/8766/5021/8091/8092/8770/8771 свободны; следующее окно — Д2 (heavy-прогон C-99).
