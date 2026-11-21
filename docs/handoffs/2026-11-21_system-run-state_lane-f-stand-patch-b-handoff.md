# Handoff полосы Ф (run-state): стенд R3c, патч headless-старта, коммит B 2.1 — 2026-11-21

Автор: лид полосы Ф, сессия inspector-bottles-b8. Закрывается `/clear`. Отчёт: `docs/reports/2026-11-21_system-run-state_lane-f-stand.md`; заявка: `docs/handoffs/2026-11-21_system-run-state_lane-f-merge-request-patch-b.md`.

## Влито в main (на 2026-11-21)
`1ec54a423` (отчёт, OPEN_QUESTIONS, брифы RN1/PS1); `1b67cc73d` (заявка); `4f8776c3d` (патч `--autostart` + `run_gate` в `bootstrap()`); `f32812114` (коммит B: `run_gate: true`). Проверки координатора на слитом дереве: validate.py чисто, sync --check rc=0, backend/tests 370 passed / 18 skipped, recipes 214/5, stand_gate 105, run_gate-тесты 56; красных нет. Стенд свободен, `stand.lock` снят.

## Что осталось (ничего не запущено)
| Что | Состояние | Кто/когда |
|---|---|---|
| RN1 (общий `read_node` в `telemetry_readmodel_module`, починка `io_debug_section.py:250`, `telemetry_view_model.py:258`) | бриф `plans/2026-10-27_system-run-state/tasks/RN1.md`, стадия 0 не прогонялась | стартовым промтом, когда освободится писатель (координатор) |
| PS1 (разбить `plan.md` 35 928 байт → ≤ 32 000) | бриф `tasks/PS1.md` | то же |
| Файл PM (`process_manager_process.py`, C-36/A) | не тронут | слово владельца по Р1–Р5 и порогам CTO |
| `alpha_sim`, `AGENTS.md:85`, `run_sim_all.ps1:21`, `main.py __main__` без `--autostart` | `OPEN_QUESTIONS` 2026-11-21 («входы без `--autostart`») | решение владельца: кто добавляет `--autostart`/`run_start` |
| Уровень WARNING `diverged` (R3c) и защита собственных записей клиента | `OPEN_QUESTIONS`; на стенде `diverged` 24–34 % | владелец/CTO |
| Метрики `state_proxy.gap_*` не доезжают до стора | `OPEN_QUESTIONS` (стенд) | задача в framework, после решения по уровню |
| Р1, Р2, В10, 2.2c; `RobotDriverV2.tick` (`driver.py:639`) | `OPEN_QUESTIONS` | владелец / Р2 |

## Уроки (в память не писал — решает лид-преемник)
- Тест, вызывающий `frontend/run.py launch()`, оставляет `INSPECTOR_PRESENTATION` в окружении процесса и краснит соседние `test_build_characterization` (порядок файлов); `monkeypatch.setenv`+`delenv` в автоюз-фикстуре.
- Классификатор прав отклонил агентный `git rebase`/`--amend` истории ветки до PASS; rebase делал лид сам после PASS п.2.
- Живой стенд на Mac: порты 8765/8766/5021/8091/8092 зашиты; перед запуском `lsof`, окно — строка в `../stand.lock`.

## agentId
Стенд R3c `a1d99a3c7c046f3da`; инвентарь путей `afc2cae18cbda3df4`; heavy-условия B `a3be23e9e077a77bb`; offline B `a93b84c20c8ea127b`; радиус патча `a6cfffde2db54224a`; ревью патча (reviewer Sonnet) `ac8745894fbb7e052`; живая проверка патча `ad6c52b2ed7aed659`.
