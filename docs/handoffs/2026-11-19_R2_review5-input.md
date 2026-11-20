# Вход для REVIEW-5 (приёмка Ф5 `robot-protocol-v2`) — подготовка, не запуск (полоса Р2, 2026-11-19)

Сверено по `main` `767d61329`. REVIEW-5 не запускался; запуск `cto` — только по слову владельца (`docs/handoffs/2026-11-19_R2_owner-decisions.md`, строка 3д).

## 1. Что ревьюируется

- **Ф5** — «приложение против sim v2 без GUI: параметры, программа, калибровка ленты» (`plans/robot-protocol-v2/plan.md:58`; задачи — `plan.md:122-143`).
- **REVIEW-5** → `cto`: «приёмка Ф5 = приложение против sim v2 без GUI (параметры, программа, калибровка ленты, стоп) через `backend_ctl`» (`tasks-2.md:130-131`; повтор в `tasks/T5.4.md:75`, `T5.5.md:161`).
- Условие «после слияния T5.4» (решение В7, `T5.4.md:133`) выполнено: T5.4 влита `9afe828be` 2026-11-09. Остаётся оговорка `T5.4.md:160` и `plan.md:138`: `executors.device_io` не проверен живьём — «на REVIEW-5 (`backend_ctl capabilities`)».

## 2. Задачи Ф5, статусы, слияния (`plan.md`, `git log --merges`)

| Задача | Статус | Слияние |
|---|---|---|
| T5.1 `RobotDriverV2` | DONE 2026-10-14 | `337047255` |
| T5.2 `RobotDataStore` | DONE 2026-10-14 | `a7b7c3c56` |
| T5.3 a+b / c+d | DONE 2026-10-19 / -20 | `0a4b07af0` / `b4a008445` |
| T5.3f / g / h | DONE 2026-10-21 | `13a0afba0` (`60b99f210`) / `53b1e1564` (`cf5855f9c`) / `6652ef88a` |
| C-29 | DONE 2026-10-25 | `26534c136` |
| SPI хаба | DONE 2026-10-26 | `4d9cf4c4b` |
| T5.3e.1–3 / .4 | DONE 2026-10-27 / -28 | `695b9eec7` / `2a557de4f` |
| T5.3e.5 / .6 | DONE 2026-11-07 / -15 | `9eb384633` / `7c4ddccdc` |
| T5.4 калибровка | DONE 2026-11-09 | `9afe828be` |
| T5.5 плагины | DONE 2026-11-08 | `009e35f86`, страж `7ccb4d716` |
| T5.6 журнал обмена | DONE 2026-10-19 | `6b16c17fb` |
| C-33, C-39 | PENDING (`plan.md`) | — |

Расхождение в плане: заголовок T5.3e — `[IN PROGRESS…]` при DONE у всех подзадач; C-33 «= T5.3e» ещё `[PENDING]`. Какое слово считать итоговым — вопрос лиду плана (не правил).

## 3. Где отчёты

- Ф5 по задачам: `docs/reports/2026-10-19_…T5.3.md`, `…T5.3cd`, `…T5.3f/g/h`, `2026-10-26_…SPI`, `2026-10-28_…T5.3e.4`, `2026-11-07_…T5.3e.5`, `2026-11-08_…T5.5`, `2026-11-11_…T5.3e.6` (все `robot-protocol-v2_`).
- Ревью стадии 5: `plans/robot-protocol-v2/reports/T5.3e.5a|5b.review-stage5.md`, `T5.3e.1.review*.md`; прочие — рядом.
- Инъекции: `tasks/T5.4.injections-result.md` (J1–J19, базовая линия 344 passed), `tasks/T5.5.injections-result.md` (J1–J12), `tasks/T5.3e.6.injections-result.md` (J1–J14, 14/14), `reports/T5.3e.4.injections-*.md`.

## 4. Числа тестов (из отчётов, не пересчитаны сегодня)

T5.4: 344 passed, 73 с (инъекции). T5.5: 1488 passed / 8 skipped (11 мин, 2026-11-08); на `main` 2026-11-15 — 98 passed (4 файла, sim v2). T5.3e.5: `Services/device_hub/tests` 1027 passed / 6 skipped, `Plugins/hub/device_hub/tests` 395 passed; полный suite на Mac тогда не зелёный (92 failed — `OSError(28)`, 72 из них в `shared_resources_module`). T5.3e.6: 155 + слепой 15 passed.

## 5. Что ревьюер воспроизводит запуском (команды — не запускал; через `machine_gate.sh`, окно по §8 `project-rules`)

1. `pytest -q --tb=short Services/device_hub/tests Plugins/hub/device_hub/tests Services/robot_comm/tests` (heavy).
2. Приёмка T5.5: `Plugins/hub/device_hub/tests/test_t55_plugins_v2_acceptance.py`, `Services/device_hub/tests/test_robot_v2_draw.py`, `test_spi_contract.py`, `Plugins/hub/device_hub/tests/test_robot_v2_commands_acceptance.py` (было 98 passed).
3. Вкладка: `pytest -q robot/tests` (было 155 passed).
4. Живьём по `tasks-2.md:130`: бэкенд с `BACKEND_CTL=1`, рецепт с sim v2, `capabilities` → параметры, `robot_program_run`, калибровка ленты, `robot_stop`; `executors.device_io` (`T5.4.md:160`).
5. `python scripts/validate.py` (на `main` был красен 2 ошибками памяти — не от Ф5).

## 6. Известные остатки (`docs/reports/2026-11-15_R2_lane.md`, `T5.5.md`, `T5.4.md`)

Второй рисунок на v2 теряется; нет `robot_draw_abort` на v2; нет контракта наблюдаемости `status` в `OPEN_QUESTIONS.md`; L1b/L4 шага `pre_stop` без стенда v2; тесты сроков T5.3e.6 идут по реальным часам (запас 0,5–0,6 с); живой GUI-стенд T5.3e.6 не гонялся; утечка замыканий `owner.destroyed` (`bindings.py:320`); `P_BELT_FACTOR` до 65535 при знаковом слове (вопрос В8 GATE-0).

## 7. Что НЕ входит

Ф4 (прошивка, T4.x — ждёт T0.3), Ф6 (пакет `robot.*`, пульт), Ф7 (bring-up на железе), GATE-1, настоящий контроллер; единая очередь движения и C-39 (режим ручной/авто) — кандидаты вне Ф5.

## 8. Вопросы к плану (определение нечёткое — не додумывал)

1. Пределы «Ф5» в `plan.md` — задачи T5.1–T5.6 плюс C-29/SPI/C-33/C-39 в одном списке; входят ли C-33/C-39 (PENDING) в приёмку?
2. Жив ли вариант (б) из `T5.5.md:55` («REVIEW-5 без ленты») — T5.4 влита, значит вариант (а) исполнен?
3. Нужен ли стенд с живым `backend_ctl` (Mac, sim v2) — `tasks-2.md:130` велит «через `backend_ctl`»; в `machine.lock` окно на Mac не берётся.
