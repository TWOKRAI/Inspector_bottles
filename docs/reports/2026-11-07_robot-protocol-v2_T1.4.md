# Отчёт: Р2 · T1.4 — диапазоны APARAM в `delta_v2.yaml` (2026-11-07)

Лид: inspector-bottles-eb. Ветка `feat/robot-v2-t14`. Бриф `plans/robot-protocol-v2/tasks/T1.4.md`.

## Что сделано
- `delta_v2.yaml` → `scenario.aparam` (6 действий, `ACCEL` — `{param: P_ACC_L}`); codegen выдаёт `ACT_RANGE` (`core/protocol_v2.py`) и `ARNG` (Lua, ключ — код действия); `programs/program.py` и `server/sim_core_v2.py` читают `ACT_RANGE` во время вызова; `SC_RUN` и `DO_SET` берут границы оттуда же; `main_v2.lua` пересобран.
- Коммиты: брифы `7068f0e1b`, правки stage 0 `a1610daa0`, слепые тесты `e234a04ec`, реализация `006365301`, инъекции `8b277af5b`, тест по review `b8541d2ab`, документы `cf16b3c43`.

## Стадии
| Стадия | Итог |
|---|---|
| 0 reviewer (Sonnet) | CHANGES REQUESTED: 1 major (grep по programs/ невыполним), 5 minor; правки внесены |
| 1 слепой tester (Sonnet) | 19 тестов, все красные по правильной причине |
| 2 developer (Sonnet) | слепая приёмка 19/19; 8 файлов `robot_comm` 542 passed, 1 skipped |
| 4 инъекции I1–I10 | предсказания сбылись; I8 — по тестам да, по grep ACCEPTANCE нет |
| 5 reviewer (Sonnet) | APPROVED; 725 входов sim старый против нового — 0 расхождений; minor (ветка `rng is None`) закрыт тестом |

После слияния main: 9 файлов 555 passed, 1 skipped; `codegen --check` rc 0.

## Открыто / ненадёжно
- Три файла с `hypothesis` (`test_programs_acceptance.py`, `test_generators_acceptance.py`, `test_client_v2_chunks_acceptance.py`) на Mac не собираются и не запускались; первые два ходят через `Action`.
- Lua `ARNG` не исполнялся (нет `lupa`, `luacheck`): только текст; прошивка читает `ARNG` и применяет сдвиг ACCUR на 1 в Ф4/T4.1.
- `_DO_CHANNELS = range(1, 17)` в `Services/device_hub/drivers/robot_driver_v2/texts.py:113` — третья копия «16» вне объёма.
- Края записи сценария (`DO` 16, `DELAY_MS` 65535, `ACCEL` 50000) тестами на реальном YAML не закреплены (так было и до T1.4).
- Инвариант T1.2 не проверяет тип границ (`100.5`, `True` проходят) — advisory.
- `validate.py` красный (2 ошибки памяти, как на main); `test_e2e_rig_v2.py::test_rig_restart_retries_until_port_free` красный и на main.
- Стенд/динамика хода сценария (accel/accur в движении) не сравнивалась — только прежние тесты.
- Документы T1.4d: express-ревью выполнил лид чтением диффа (19 строк), не отдельный reviewer.
