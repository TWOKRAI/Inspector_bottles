# Run-state, полоса Ф — стенд R3c и heavy-условия коммита B 2.1 (2026-11-21)

Автор: лид полосы Ф (сессия inspector-bottles-b8). План: `plans/2026-10-27_system-run-state/plan.md`. Стенд — macOS, сим-линия `apps/line_sim`, machine.lock нет. Основа — `main` `96fb1ea59`. Заявка на слияние B: `docs/handoffs/2026-11-21_system-run-state_lane-f-merge-request-b.md`.

## 1. R3c: «до / после» (3 прогона на дерево, окно 25 с от готовности; `run_one.sh` + `count.py`)

| | BASE `c10c63eb9` (до R3c) | HEAD `96fb1ea59` |
|---|---|---|
| WARNING за окно | 104 / 106 / 103 (среднее 104,3); база 20.11 — 106–111 | 1 / 1 / 1 |
| окно 95 с | — | 4 строки на −0,1 / +29,9 / +60,2 / +90,4 с (троттлинг 30 с) |
| DEBUG HEAD (25 с ×3 / 95 с) | — | detected 105/105/104/398, diverged 25/31/35/133 (23,8–33,7 %), unclassified 0 |

Разрывы остались (≈ 4,2/с), убран шум WARNING. Только процесс `camera` (подписка `sim.belt.**`); все diverged — `sim.belt.encoder.{t,value}` (робот пишет ~50 мс). Метрики `state_proxy.gap_*` до стора не доезжают — счёт по DEBUG-строкам.

## 2. Коммит B 2.1: условия слияния (дерево main + `run_gate: true`; heavy)

| Условие | Команда / способ | Результат | |
|---|---|---|---|
| `test_recipe_service_live` | pytest `-m harness_smoke` | 1 passed, 7,7 с | PASS |
| `test_recipe_service_restart_live` | pytest | 1 passed, 10,8 с | PASS |
| `test_frame_bridge_live` (`start_run` до apply) | pytest | 1 passed, 7,0 с | PASS |
| `start_run` до apply, живьём (`bridge_synth`) | backend_ctl | ready 3,85 с; 0 кадров за 8 с; `run_start` → running 0,01 с, 152 кадра/5 с; apply/activate в running — `error: "running"`; `run_stop` → ready 0,19 с | PASS |
| offline на rebased B (`68b4a026d`) | `machine_gate medium` | backend 345 passed/18 skipped, recipes 214/5, stand_gate 105, capacity_bench 79, harness_run_gate 22; red 0 | PASS |
| golden после rebase | `UPDATE_BUILD_SNAPSHOTS=1` | перегенерация без изменений; `git diff main -- '*.build.json'` — только 4 строки `run_gate` | PASS |

Пути без START после B (живьём): `run.py letter_robot_sim --headless` — ready, кадров 0 (с `--autostart`: running, 25 fps); `frontend/run.py --headless` — ready, кадров 0 (флага нет); `alpha_sim/run_alpha.py` без автостарта — rc 3 (с автостартом P1–P3, B, D — 35 PASS, прерван таймаутом); `smoke_proof`, `telemetry_probe` — rc 0, остаются в ready; `task21_proof` — rc 1, на контроле то же (нет OTel SDK).
Чинить сейчас (малый патч, файлы вне зоны Ф): `--autostart` в `frontend/run.py`; `run_gate` kwarg в `bootstrap()`/`from_topology_path` (8 скриптов). Остальное — `OPEN_QUESTIONS` 2026-11-21 (стенд).

## 3. Брифы (код не писал)
`tasks/RN1.md` — общий `read_node` в `telemetry_readmodel_module`, починка `io_debug_section.py:250` и `telemetry_view_model.py:258` (до 1.0); `tasks/PS1.md` — разбить `plan.md` (35 928 байт, бюджет 32 000); `RobotDriverV2.tick` (`driver.py:639`) уже в `OPEN_QUESTIONS` (Р2). Файл PM не тронут.

## 4. Что осталось открытым / ненадёжно
- Выборка R3c: 3 прогона на дерево + 4 DEBUG; не доказано, что diverged ≠ реальная потеря (верхняя оценка 34 %); «дельты в полёте» — правдоподобно, не проверено; GUI-процесс не смотрели (сим headless).
- Шаг «start_run до apply» снят на синтетическом `bridge_synth` без камеры и пульта; кадры в шаге 3 — косвенно, по fps из дерева состояния; контроль `run_gate: false` снят только для `task21_proof`; `alpha_sim` с автостартом не доведён до конца (C, «домой», СТОП не измерены).
- Не снимались: GUI-зонды `probe_*_live`, `otel_stand` 2.2–2.4, `telemetry_sink_proof`, `test_harness_no_orphans_*`/`parent_death`; 18+5 skipped offline не разбирались; break-injection на B не гонялся; `sentrux check .`, `make gate`, `frontend_module/bridge|state` heavy — не запускались.
- B: ветка `feat/run-state-2-1-commit-b` перебазирована на main (`68b4a026d`, история ветки переписана, не запушена); коммит message прежний, `Why:`/`Layer:` сохранены.
- Решения владельца/CTO: уровень WARNING `diverged` и защита собственных записей клиента; Р1, Р2, В10, 2.2c; кто шлёт START для GUI-зондов (`tasks/2.7.md:59`); слово координатора на слияние B.
- Мои решения без слова владельца: исполнитель rebase — лид сам (агентный rebase отклонён классификатором прав); дерево «main + run_gate» без коммита как эквивалент B для живых условий; брифы RN1/PS1 — черновики без стадии 0.

## 5. agentId
| Роль | agentId |
|---|---|
| стенд R3c (general-purpose Sonnet) | a1d99a3c7c046f3da |
| инвентарь путей (Explore) | afc2cae18cbda3df4 |
| heavy-условия B (general-purpose Sonnet) | a3be23e9e077a77bb |
| offline-тесты B (test-runner) | a93b84c20c8ea127b |

Деревья: `.claude/worktrees/lane-b8-stand-{base,head,b}` (detached), `lane-b8-docs`; стенд свободен (порты 8765/8766/5021/8091/8092/8770/8771 свободны, процессов нет).
