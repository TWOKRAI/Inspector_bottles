# Запрос на слияние: полоса Н (observability-signal-contracts) — фаза 0, срез 0.1–0.11 (2026-11-22)

Автор: лид полосы Н (сессия inspector-bottles-19). Ветка `refactor/observability-signal-contracts` (worktree `Inspector_bottles--lane-N`), HEAD — `git rev-parse refactor/observability-signal-contracts` на момент слияния; `main` влит в ветку (`915af7280`), `git rev-list HEAD..main` = 0. Слияние — одним срезом, тема коммита `feat(...)` (хук режет `merge(...)`), `merge-begin`/`merge-end` через `machine_gate.sh`. Решение владельца: «доводи и сливай».

Заменяет прежнюю заявку (срез 0.1–0.3, 11 красных контракт-тестов): все 11 контракт-тестов теперь зелёные.

## Что вошло
61 коммит, 147 файлов (+12574 / −615): задачи 0.1–0.11 плана `plans/2026-11-21_observability-signal-contracts/` (Task 0.11b, 0.12, 0.12b, 0.13 — после слияния).
- **I1 «исход» (0.1, 0.4–0.7):** `outcome_of`, `count_outcome`, `LOSS_KEY_BY_HOP` (`channel_routing_module`); часовой `REFUSED` и `LoggerCore.is_closed` (ADR-CRM-019, ADR-CRM-020); суд над ответом в tap/форвардере/мосту (0.5a–0.5c, ADR-RTR-016); OSError файла (0.4), остановленный логгер (0.6), traceback (0.7).
- **I2 «свежесть» (0.2, 0.8–0.10b):** `state_store_module/core/freshness.py` (ADR-SS-025); пара fps/latency самой медленной стадии, остановленные воркеры исключены (0.8, ADR-PM-063); метка `processes.<p>._fresh` в heartbeat (0.9); `TelemetryReadModel.read` и кольцо истории по времени источника (0.10); `telemetry_snapshot` с `class`/`age_s`/`gap_count`/`last_gap_at` (0.10b).
- **I3 / проверенная запись (0.3, 0.11):** `set_register_verified`, `telemetry_set`, `register_restore` отдают `verdict` (confirmed/vacuous/failed/unverifiable).
- Документы: три ADR (PM-063, CRM-020, RTR-016), поправка к ADR-SS-025 (цена метки), правка устаревших текстов.

## Проверки на ветке в сборе
- **Полный прогон** (`pytest -q --tb=line -p no:cacheprovider -rf --continue-on-collection-errors`, корень репозитория, замороженные деревья, 2026-11-21): main `8383b7a62` — 483 failed / 20673 passed / 3 errors сбора; ветка `998ffb81c` — 485 failed / 20815 passed / 3 errors. Множество красных: в ветке на 2 больше (`multiprocess_prototype/frontend/widgets/tabs/observability/tests/test_tail_activator.py`: фейк router имел только `send_async`, а форвардер после 0.5c судит ответ `router.send()`) — **исправлено** коммитом `08b6c619e` (каталог 75 passed). Сверх этого новых красных 0, исчезнувших 0. Общие красные окружения Mac одинаковы до и после: `layer_render`, `machine_gate_tests`, `Plugins/io/otel_export` (нет модуля `opentelemetry`), `dataset_gen`, `lifecycle_guards`, `code_reader`, `scene_source`, `device_hub`, `test_std_logger_guard` (C-106).
- 11 контракт-тестов: `test_contract_outcome.py` + `test_contract_freshness.py` 12 passed; `test_contract_freshness_reader.py` + `test_contract_verified.py` 13 passed.
- Каталоги по задачам (ревью стадии 5, по 2 раунда): `backend_ctl/tests` 963 passed, `process_module/tests` 3782 passed (+бенч 616), `statistics_module` 355, read-model + frontend state 232, `telemetry_sink` 35, вкладка processes 211.
- `scripts/validate.py` — ошибок нет; `python -m scripts.sync` — чисто; `sentrux check .` — 1 нарушение вне диффа (`test_recipe_1_0.py`, fan-out 20, C-107).
- Ревью ветки Opus: `plans/2026-11-21_observability-signal-contracts/reports/phase0.branch-review-opus.md` (MERGE AFTER FIXES; блокеры закрыты: заявка, запись о цене метки).
- Короткий стенд (до слияния): `docs/reviews/2026-11-22_stand-phase0.md`; итог — раздел «Стенд» ниже.

## Известные красные и особенности (в `defects.md` / `OPEN_QUESTIONS.md`)
- Дефекты полосы Н **перенумерованы** при влитии main: C-106 (`test_std_logger_guard`, Services/hikvision_camera и др., красный и на main), C-107 (`sentrux`, `no_god_files`); номера 102–105 заняты другими полосами в main.
- `Plugins/io/otel_export/tests`: 46 красных и на main (нет `opentelemetry`).
- `contract.lock` плана не переподписан: `plans_ledger.py amend` отказывает по `PLAN_TOO_BIG`/`TASK_TOO_BIG` (как у других слитых планов); дрейф записан поправкой 8 в `amendments.md`. Решение по бюджету размера — за координатором.
- Хвосты фазы 0 — блок «хвосты фазы 0» в `OPEN_QUESTIONS.md`.
- Чистого прогона `process_manager_module/tests` без ENOSPC не получено: исчерпание POSIX-семафоров macOS (`sysctl kern.posix.sem.max` = 10000), не диск; полный прогон выше его включает.

## Что меняет поведение для других полос
- **`state.fps`/`latency_ms` процесса** — пара самой медленной стадии живых воркеров, без округления; `None`, когда данных нет (раньше максимум по воркерам). Читатель `frontend_module/bridge/wire_monitor.py:123,125` (`float(None)`) без вызывающих.
- **Метка `processes.<p>._fresh`** (+2 дельты на процесс за такт, в том числе при закрытом гейте) — подузел под `processes.<P>`; код, перебирающий детей как секции, увидит новый dict. Решение лида (ADR-SS-025), владельцу — на подтверждение.
- **`set_register_verified`:** запись, отвергнутая хостом при уже равном значении, — `success=False`, `vacuous=True`. Пробы соседних полос, пишущие равные значения в процессы без хендлера `register_update`, станут красными (так задумано).
- **История кольца read-model** ставится на время источника (`src_ts` писателя), не приёма.
- **Литерал бенча** `ENABLED_INSTRUCTIONS` 607 → 616 (`test_f2_numbers_disabled_cost_bench.py`, привязан к CPython 3.12): правка соседа в этой дороге даст конфликт.
- **Логгер:** `logger_core.py` (`_closed`, `_refuse_closed`), `log_channel.py` (`_ErrorCapture*`) — зона пересечения с C-93 (`std_facade`).
- **Windows:** консоль без `sys.stderr` теперь отвечает `error` на каждую запись (`channel_refused_records` растёт); на Windows не проверено.

## Стенд
Отчёт: `docs/reviews/2026-11-22_stand-phase0.md` — **БЛОКЕРОВ 0**. Дерево `f098876da`, macOS, `BackendHarness`, рецепт `region_pipeline`, 10 процессов; камеры нет, конвейер без кадров, Windows и Qt не проверялись.
- **Такт монитора хаба (0.5 с)** при клиенте после SIGSTOP (RCVBUF 2 КБ): p50 0.494 с, max ≈ 0.62 с; при насыщении буфера хаб снял клиента один раз, один пик (интервал 0.750 с вместо 0.5), повторяющихся пиков нет. Слабость: насыщение поймано в 1 запуске из 3 (в двух клиент за 55 с буфер не насытил). Замера на Windows нет.
- **fps/latency при остановленных воркерах:** `None` через 5.5 и 30 с (не замёрзшие числа); у остановленного воркера публикуются `last_cycle_age_s`/`effective_hz`. Сценарий «пара живого воркера» **не измерен** (нет двух воркеров с измеренным циклом).
- **`forwarders`:** `sent` +73, клиент получил 73; `dropped = send_failed = 0`; после закрытия сокета запись исчезла за ≤ 1.5 с. Один прогон.
- **`telemetry_snapshot`:** живой — `fresh` (0.6–5.0 с); после SIGSTOP `stale` при возрасте > 10 с, при 9 с ещё `fresh`; после рестарта процесса монитором `fresh` вернулся за ≤ 1 с; `gap_count = 0` (ложные дыры ADR-SS-015 не проверены).
- **Цена метки:** ровно **2 дельты на процесс за такт** (разброс 0 по 8 процессам); при такте стенда 5 с это 2N/5 с = 3.2 дельты/с при N=8 (8/с при N=20), ≈ 10% потока `state.changed` (30.6/с). Условие пересмотра ADR-SS-025 («цена хаба») не сработало; «8 → 10» при открытом гейте на простаивающих процессах не воспроизведено (значения не менялись).
- **`set_register_verified`:** без обработчика (12 из 12) — `verdict=failed`, `success=False`, ложного успеха нет; принятая запись с равным значением — `verdict=vacuous`, `vacuous=True`, но **`success=True`** (по дизайну I3; цель 10 требует `success=False` только для отвергнутой). Читатель, смотрящий только `success`, увидит «успех» у записи, ничего не доказавшей — вопрос в OPEN_QUESTIONS. Сценарий «отвергнута хостом при равном значении» на стенде недостижим, закрыт контракт-тестом.
- **Журналы:** `REFUSED`, `forwarders`, `telemetry_publish_failed`, `Traceback`, `Logging error` — 0 вхождений; ERROR 5, все объяснены (камера не открывается; 4 × `delivery_failed` ушедшему клиенту).
- Не разобрано: рост числа листьев после рестарта (30 → 227), предупреждение `resource_tracker` про 5 утёкших семафоров при останове.

## Что нужно от координатора
1. Слот слияния (`merge-begin lane-N refactor/observability-signal-contracts`).
2. Решение по размеру Task (`contract.lock`, см. выше).
3. Файлы PM (`process_manager_process.py`), `launcher/spawner.py`, `state_proxy.py` и `logger_module/adapters/std_facade.py` не тронуты.
