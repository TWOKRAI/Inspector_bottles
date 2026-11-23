# Run-state, полоса Ф — П3 остаток (P3r), ложные «разрыв revision» (R3c), S4b2, шапки по git, подготовка коммита B 2.1 (2026-11-21)

Автор: лид полосы Ф (сессия inspector-bottles-9a). План: `plans/2026-10-27_system-run-state/plan.md`. Основа веток — `main` `dc56f14df` (позже main ушёл на `e836b2db5`, `merge-tree` без конфликтов). Ничего не влито в main и не запушено. Задачи по порядку брифа:

## 1. Что готово (ветка → HEAD → что внутри)

| Ветка | HEAD | Содержимое | Ревью |
|---|---|---|---|
| `fix/run-state-p3-node-read` | `4a8403bf9` | задача 1 (P3r) + задача 4 (шапки `plan.md`, спеки P3r/R3c/S4b2) | стадия 0 Sonnet ×2 раунда; слепой tester; Sonnet APPROVED; Opus MERGE WITH CONDITIONS (условия закрыты текстом) |
| `test/run-state-s4b2` | `50b016570` | задача 3 (S4b2): тест на настоящем `RobotDriverV2`, допуск `run_stop_timeout_s` | Sonnet CHANGES REQUESTED → правки → сверка лида; Opus MERGE |
| `feat/state-proxy-gap-classification` | `43ceeb801` | задача 2 (R3c): вариант (в) ADR-SS-015 | стадия 0 ×2 раунда; слепой tester; Sonnet APPROVED (M1, M2 закрыты); Opus MERGE WITH CONDITIONS (число 51 % приложено) |
| `docs/run-state-oq3` | см. `git rev-parse docs/run-state-oq3` (этот файл + заявка + `OPEN_QUESTIONS` поверх `c56a6dbbd`) | записи `OPEN_QUESTIONS`, этот отчёт, заявка на слияние | Opus MERGE WITH CONDITIONS (числа исправлены) |
| `feat/run-state-2-1-commit-b` | `1fbefc6d8` | задача 5 (коммит B 2.1) — ПОДГОТОВЛЕН, не к слиянию | Opus: DO NOT MERGE сейчас |
| задача 6 (файл PM, C-36/A) | — | НЕ тронута (по брифу: после п.1–5 и дня №1, слово координатора) | — |

## 2. Числа

**Задача 1 (P3r).** После П3 read-model хранит листья; `await_condition(state_path/metric_threshold)` и `ReplayPlayer.state_get` не видели узла, `metric_threshold` давал ложный `unknown_metric`. Новый приватный `backend_ctl/_node_read.py` (`read_node(drv, path)`, 66 строк) + замена чтения в `conditions.py` (+9/−4) и `recorder.py` (+6/−4), включая `_unknown_metric_diagnosis`. Тесты: слепые 36 (30 красных на базе: 10 по поведению, 20 `ModuleNotFoundError`; 6 контролей) + 8 тестов реплей-await; 44 passed. Радиус `backend_ctl/tests`: 873 → 917 passed, 72 skipped (Opus, класс `medium`). Инъекции: 10 мутантов, 8 точно по предсказанию, 2 с объяснённым отличием (`v-slice` без RED 7 — тест гонки не проверял содержимое, усилен; `g` без лока: {7, 10}). Дифференциал Opus на 400 случайных деревьях: листья 2824/2824, несуществующие 2275/2275 совпали с базой; узлы: база 0/3026, `read_node` 3026/3026. Реальная гонка без лока красна 5 из 5 прогонов (macOS, 0,7 с).

**Задача 2 (R3c).** Строка обнаружения разрыва — DEBUG; счётчики `gap_detected/clean/diverged/unclassified_count` и метрики `state_proxy.gap_*`; `_apply_resync_snapshot` возвращает изменённые пути; WARNING `diverged` ≤ 1 раза в 30 с. `state_proxy.py` +198/−12 (+ правки M1/M2), DECISIONS/README/STATUS модуля. Тесты: слепые 52 (46 красных на базе: 17 по поведению, 29 `AttributeError`; 6 контролей) + 5 тестов автора; каталог `state_store_module/tests` 739 → 796 passed (`medium`). Инъекции: 13 мутантов, все убиты; 8 точно, 5 с большим числом красных, один неточный прогноз лида (e: REDS 6 вакуумен на fallback). Дифференциал Sonnet с базой на 17 сценариях: поведение ресинка идентично. Opus на настоящем `StateStoreManager`+`StateProxy` (модель транспорта, не стенд), 20 с: чужие записи 4 Гц — 78 разрывов, 78 `clean`, 0 WARNING (на базе 78); + свои записи 2 Гц (`exclude_self`) — `diverged` 51 %, 1 WARNING; запись в подписку 60 Гц — `diverged` 16–22 %.

**Задача 3 (S4b2).** Тест `Plugins/hub/device_hub/tests/test_tick_fails_limit_real_driver_v2.py` (11 тестов, 313 строк+): настоящий `RobotDriverV2` на `FakeRobotTransport(RobotSimCoreV2())`, настоящий воркер hub, подмена `_dispatch`/`_park.step` на бросающую. 62 passed вместе с двумя соседними файлами; `Plugins/hub/device_hub/tests` 577 passed (290 с). Инъекции: 11, все убиты, включая «успех очищает `last_error`» (добавлена по ревью). Допуск в `tasks/2.7.md:120`: «≥ 2,0 и ≤ 2,7 с (n = 8: 2,046…2,532; причина разброса не установлена)»; гипотеза «квант PM 0,5 с» опровергнута кодом (`_STOP_POLL_S = 0.05`).

**Задача 4 (шапки).** Сверка по git: влито целиком 20 из 32 (с 0.1; 19 из 31 без неё — так считает `plans_progress`; прибор показывал 1 из 30), частично 3 (2.1, 1.10, 1.11), не влито 9. «21 из 31» из отчёта CTO не воспроизведено.

**Задача 5 (коммит B 2.1).** 4 файла, +8/−8: `system.yaml` true, golden `hikvision_letter_robot` и `phone_sketch` (только `run_gate`), литералы в `test_run_gate_manifest.py`. Offline: `backend/tests` 345 passed, `recipes/tests` 214, `stand_gate/tests` 105, `capacity_bench/tests` 79, `test_harness_run_gate.py` 22. Живые условия слияния не проверены (см. §4).

## 3. Находки (подробности — `docs/claude/OPEN_QUESTIONS.md`, записи 2026-11-21)

1. `RobotDriverV2.tick` может бросить наружу: сбой публикатора в `except`-ветках `_run_next_job` (`driver.py:639` `_publish_error` вне `try`) — воспроизведено на уровне драйвера; файлы Р2.
2. Потребители read-model по пути узла вне `backend_ctl`: `io_debug_section.py:250`, `telemetry_view_model.py:258` — баг после П3; Opus: чтение узла должно жить в framework, а не в приватном модуле `backend_ctl` (третья сборка узла из листьев).
3. R3c: клиент не отличает потерю пакета от дельты в полёте и собственной записи; `diverged` у процессов со своими записями ≥ 51 %.
4. Коммит B: пути, берущие yaml напрямую (`run_alpha.py` без `--autostart`, пробы `backend_ctl/probes/*`, `tools/otel_stand/*`, `test_recipe_service_*_live.py`), встанут в `ready` без кадров.

## 4. Что осталось открытым / ненадёжно

- **Живой стенд не выполнен ни для одной задачи.** Стендовый замер R3c (WARNING за 25 с против базы 106–111), живой путь S4b на боевом публикаторе, `heavy`-условия коммита B (`recipe_service` ×2, `test_frame_bridge_live`, `start_run` до `apply`) — нет окна, стенд у координатора (`stand.lock`/слово).
- **Свои числа R3c — модель, не стенд:** один транспорт-FIFO 3 мс, 2 зерна; число ресинков в `busy` (39–41 база, 44–45 HEAD) объяснено чтением кода, не доказано.
- **Инъекции R3c** прогнаны на коде до правок M1/M2; для 5 новых тестов — «красные до, зелёные после», но 13 мутантов на финальном коде не повторены (мутант `n` на новой строке shutdown не применится без правки скрипта).
- **Golden коммита B** перегенерированы на `dc56f14df`; на новом main (Пульт 6.2/6.3, рецепты) нужна перегенерация при слиянии.
- **Решения владельца/CTO, не мои:** уровень WARNING `diverged` и защита собственных записей клиента в окне ресинка; Р1 (подпись пульта при `run_gate: false`), Р2 (`stop_allowed` для `None`, `""`, `0`, `[]`), В10, 2.2c (блокировать START в `stopping` с `auto_start`: CTO вариант (б), ключ `readiness` в узле камеры при R4); задача на общий помощник чтения узла в framework и починку frontend-потребителей до 1.0.
- **Мои решения, оставленные без слова владельца:** троттлинг `diverged` 30 с (в рамках варианта CTO «ограничить частоту»); допуск `run_stop_timeout_s` ≤ 2,7 с (запас над максимумом 0,168 с при n = 8); нумерация задач P3r/R3c/S4b2 в `tasks/`.
- **`plan.md` 35 КБ при бюджете 32 КБ** (было 34 КБ до правки) — разбить отдельной задачей.
- Не запущены `sentrux check .`, `make gate`, `heavy`-каталоги (`frontend_module/bridge`, `frontend_module/state`) — окно.
- Слепой tester получил в брифе неточный счётчик «58» (на деле 52) — моя ошибка, исправлена в коммите.

## 5. Таблица agentId (эта часть сессии)

| Роль / задача | agentId |
|---|---|
| reviewer Sonnet стадия 0: P3r / R3c / S4b2 | a06b87ba520ae45bd / a659f477a49b9ccba / a6d790a4d060ccf30 |
| tester слепой: P3r / R3c | a1db33d6e2b69cdd5 / a5d2cbb8f8eb18f08 |
| developer: P3r / R3c / S4b2 / коммит B 2.1 | a6c4ed79fcd45e834 / aa0ca9dd3ec89c913 / a91aa8ebcc5d3540f / a974f0e55e8b88279 |
| reviewer Sonnet стадия 5: P3r / R3c / S4b2 | acaf1cf4a4c348192 / a2448df1f26787cad / a0c8ab48a84f23a59 |
| reviewer Opus перед main (все ветки) | ace0da86b5bc05f10 |
| test-runner (инъекции): P3r / R3c | a3cdf801ce580e734 / ad8186bc44ff6ef00 |
| Explore (инвентарь шапок) / docs-writer (шапки plan.md) | a81bba9358e16a746 / aedbcb9665c6db56a |

Скрипты инъекций и пробы ревьюеров — scratchpad сессии 9a (`inj_p3r/`, `inj_r3c/`, `rev/`, `scripts/`); /private/tmp может быть очищен.
