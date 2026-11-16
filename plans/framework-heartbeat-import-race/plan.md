# Plan: гонка ленивых импортов `heartbeat.cpu_clock` на старте ребёнка (C-92)

- **Slug:** framework-heartbeat-import-race
- **Дата:** 2026-11-16
- **Статус:** DRAFT (стадия 0, раунд 1: CHANGES REQUESTED 13 пунктов — внесены 2026-11-16; слепой tester дальше)
- **Ветка:** `fix/framework-heartbeat-import-race`
- **Полоса:** Д (дефекты). Дефект: `plans/queue/defects.md` C-92 (номер предварительный: на 2026-11-16 в `main` записи нет, сверить перед слиянием).
- **Разбор:** [`docs/reviews/2026-11-16_stand-1.10-findings.investigation.md`](../../docs/reviews/2026-11-16_stand-1.10-findings.investigation.md) находка 1
  (скрипт воспроизведения — [`repro_import_deadlock.py`](repro_import_deadlock.py), копия из расследования).
- **Стадия 0:** [`docs/reviews/2026-11-16_task-c92-1.1-stage0.md`](../../docs/reviews/2026-11-16_task-c92-1.1-stage0.md).

## Контекст

Ребёнок на старте падает `_DeadlockError on heartbeat.cpu_clock` (стенд 1.10: 1 из ~30 рестартов; в окне 60 с ведёт к `gave_up` → `fault`).
Два потока ребёнка лениво импортируют один пакет в одно окно:

| поток | импорт | цепочка замков |
|---|---|---|
| `message_processor` (поднят в `initialize()`, `process_module.py:307-308`), обработчик `introspect.status` | `builtin_commands.py:822` `from ..heartbeat.cpu_clock import process_clock` | `heartbeat.cpu_clock` → `heartbeat` → ждёт `heartbeat.process_heartbeat` |
| основной, `ProcessModule.run()` | `process_module.py:1518` `from ..heartbeat.process_heartbeat import ProcessHeartbeat` | `heartbeat.process_heartbeat` → ждёт `heartbeat.cpu_clock` |

CPython 3.12 берёт замок подмодуля раньше импорта родителя; `heartbeat/__init__.py:3` сразу тянет `.process_heartbeat`, а `process_heartbeat.py:12` — `.cpu_clock`.
Цикл `cpu_clock → process_heartbeat → cpu_clock`. Окно ≈ 0,3 мс; без перехватчиков 40 из 70 (сдвиг 0,55 мс), с предзагрузкой 0 из 40.
Не регресс Ф1: `6601abd2b` (2026-09-30), `7a5b5209d` (2026-05-08).

## Цель

Цикл замков в пакете `heartbeat` снят при любом первом импортёре (П3), а сам пакет загружен в основном потоке до старта потоков ребёнка (П1).
Ленивый `heartbeat.telemetry` из потоков остаётся, но безопасен: цикла замков нет, пакет уже загружен.

## Принципы владельца

- Правка framework, а не обход (принципы 1, 2): `process_module` общий для всех приложений.
- Публичный путь `from ...heartbeat import ProcessHeartbeat` остаётся (принцип 3).
- Слои не добавляются, лишний пункт снят (принцип 4): ленивый импорт в `builtin_commands.py` не трогаем — он безопасен при П1+П3
  (стадия 0, вопрос 4: п. «импорт в шапку `builtin_commands.py`» избыточен).

## Задачи

| Task | Суть | Уровень |
|---|---|---|
| 1.1 | Импорт `ProcessHeartbeat` в шапку `core/process_module.py` (П1) + PEP 562 в `heartbeat/__init__.py` (П3) + тесты в чистом подпроцессе | Middle (≈ 15 строк кода, ≈ 150 строк тестов) |

Цена фазы (оценка стадии 0): 5 участников × ~56k ≈ 280k + работа ≈ 220k, итого ≈ 500k токенов.

## Task 1.1 — загрузка `heartbeat` до потоков и снятие ребра цикла в пакете

- **Level:** Middle · **Assignee:** developer
- **Goal:** см. «Цель»
- **Files:** блок FILES ниже
- **Acceptance criteria:** блок ACCEPTANCE ниже
- **Handoff:** tester (слепой, один раз, до кода) -> developer -> лид (инъекции) -> reviewer (стадия 5)
- **Gate:** light — `multiprocess_framework/modules/process_module/tests/test_heartbeat_import_race.py`; medium — каталоги из ACCEPTANCE п. 1
- **Module contract:** N/A — публичный API (`ProcessHeartbeat`, `__all__`) не меняется
- **Dependencies:** нет

```
TASK: 1.1 — C-92: гонка импорта heartbeat.cpu_clock          PLAN: plans/framework-heartbeat-import-race/plan.md
ROLE: developer (эскалация — teamlead)
CHAIN: tester (слепой, один раз, до кода) -> developer -> лид (инъекции) -> reviewer (стадия 5)
```

### DESIGN

(decided by the lead — you type it, you do not derive it)

1. **П1.** `multiprocess_framework/modules/process_module/core/process_module.py`: в шапку файла, к прочим относительным импортам, добавить
   `from ..heartbeat.process_heartbeat import ProcessHeartbeat`; в `run()` (около строки 1518) удалить ленивый `from ..heartbeat.process_heartbeat import ProcessHeartbeat`.
   Комментарий у шапочного импорта: «heartbeat грузится при импорте класса процесса, до потоков ребёнка: ленивый импорт пакета из `message_processor` и `run()` давал
   `_DeadlockError` (C-92)». Причина стадии 0 п. 6: этот слой даёт гарантию «ошибка импорта всплывает до потоков» и не зависит от детали замков CPython 3.12.
2. **П3.** `multiprocess_framework/modules/process_module/heartbeat/__init__.py`: `ProcessHeartbeat` отдаётся лениво через PEP 562:
   ```python
   def __getattr__(name: str) -> object:
       if name == "ProcessHeartbeat":
           from .process_heartbeat import ProcessHeartbeat
           return ProcessHeartbeat
       raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
   ```
   Исключение — строго `AttributeError` (его ловит `hasattr` в `_handle_fromlist`: форма `from ...heartbeat import telemetry` — `configs/telemetry_publish_config.py:69`,
   `statistics_module/observation/observation_manager.py:135` — иначе ломается). `__all__ = ["ProcessHeartbeat"]` остаётся; под `TYPE_CHECKING` — обычный импорт для анализаторов.
   Назначение: родитель не тянет `.process_heartbeat` при собственной загрузке, значит первый импорт `heartbeat.cpu_clock` из любого потока не берёт замок `process_heartbeat`.
3. `builtin_commands.py` НЕ трогать (ленивый импорт `cpu_clock` в `_cmd_introspect_status` остаётся: безопасен при П1+П3).
4. Циклов импорта нет: расследование проверило без правки файлов четыре входа (`multiprocess_framework`, `...process_module`, `...core.process_module`,
   `multiprocess_prototype.backend.launch`). Автор правки повторяет проверку после правки (те же четыре входа, чистый интерпретатор) и пишет результат в отчёт.
5. Не трогать: `heartbeat/process_heartbeat.py`, `cpu_clock.py`, `telemetry.py`, `builtin_commands.py`, прочие ленивые импорты `heartbeat.telemetry`
   (`plugins/base.py:928`, `observability_wiring.py:451`, `observation_manager.py:135`, `ensure_framework_producers`, методы `process_heartbeat.py`): безопасны, потому что цикл замков снят (П3)
   и пакет загружен (П1).
6. Побочный эффект П1 (записать в ADR): `declare_metric("shm" | "cpu" | "plugin_ms")` из `process_heartbeat.py` теперь исполняется на импорте `core.process_module`, а не при первом `run()`.

### FILES

- `multiprocess_framework/modules/process_module/core/process_module.py`
- `multiprocess_framework/modules/process_module/heartbeat/__init__.py`
- `multiprocess_framework/modules/process_module/tests/test_heartbeat_import_race.py` (новый)
- `multiprocess_framework/modules/process_module/DECISIONS.md` — ADR **`### ADR-PM-060 — …`** (форма `###`, как соседний ADR-PM-059: индекс sync строится только по `## ADR-…`);
  номер сверить `git grep -n '^### ADR-PM-06' main` перед слиянием; проверка `python -m scripts.sync --check` → пустой diff, `multiprocess_framework/DECISIONS.md` не трогать.
- Не в FILES, делает лид: `docs/claude/OPEN_QUESTIONS.md` (две строки: правило «модуль, лениво импортируемый обработчиком или воркером, грузится до старта потоков»;
  родственная гонка `run():1488` — ленивый `builtin_commands` после `start_all_workers()` у не-`GenericProcess` процессов), `plans/queue/defects.md` (C-92), `STATUS.md` модуля.

Запрещено: `process_manager_process.py`, `launcher/spawner.py`, `Services/**`, `multiprocess_prototype/**`, `commands/builtin_commands.py`.

### REDS

Инфраструктура тестов (стадия 0 п. 2, 3): каждый тест — `subprocess.run([sys.executable, "-c", script], cwd=_REPO_ROOT, env={..., "PYTHONPATH": _REPO_ROOT}, timeout=…)`
(как `tests/test_metric_catalog_order_gate.py`); НЕ `-I` (он игнорирует `PYTHONPATH` и не кладёт cwd в `sys.path`). В скрипте первым действием:
`assert multiprocess_framework.__file__` лежит под `_REPO_ROOT`. Любой поток — с дедлайном `join`. Предусловие каждого теста (иначе тест пустой):
до действия `heartbeat`, `heartbeat.process_heartbeat`, `heartbeat.cpu_clock` НЕ в `sys.modules` (для R3 ещё и `core.process_module`). `import cv2` в тестовой копии — под `try/except ImportError`.
Время: `det` на зелёном пути ждёт 5-секундные таймауты — бюджет R3, R4 по ~5–10 с.

| # | Свойство | Красное сейчас | Зелёное после |
|---|---|---|---|
| R1 | `import ...core.process_module` → в `sys.modules` есть `...heartbeat.process_heartbeat` и `...heartbeat.cpu_clock` | да | П1 |
| R2 | гонка по сценарию `repro_import_deadlock.py det` (поток `msgproc` = настоящий `BuiltinCommands._cmd_introspect_status`, основной = `from ...heartbeat.process_heartbeat import ProcessHeartbeat`; исходы A и B = `ok`; флаги «перехватчик сработал» вернуть и проверить). Шапка скрипта грузит `core.process_module` и `builtin_commands` до потоков, как ребёнок | да (`_DeadlockError`) | П1 или П3 (любого одного достаточно) |
| R3 | гонка только на пакете (`core.process_module` НЕ импортирован): поток B `import ...heartbeat.cpu_clock`, поток A `from ...heartbeat.process_heartbeat import ProcessHeartbeat`, перехватчики как в `det`, флаги сработавших проверить; оба `ok` | да | П3 |
| R4 | без таймингов: в чистом интерпретаторе `import ...heartbeat` → `process_heartbeat` НЕ в `sys.modules`; после обращения `heartbeat.ProcessHeartbeat` → в `sys.modules` | да | П3 |
| R5 | охрана публичного пути (зелёный и сейчас, и после — не RED): `from ...heartbeat import ProcessHeartbeat` отдаёт класс, `heartbeat.ProcessHeartbeat is heartbeat.process_heartbeat.ProcessHeartbeat`; `from ...heartbeat import telemetry` и `from ...heartbeat import cpu_clock` работают (подмодуль через `fromlist`); `heartbeat.нет_такого` → именно `AttributeError`; `hasattr(heartbeat, "нет_такого")` → `False` | нет (зелёный) | П3 держит |

R2 — канарейка симптома, не охрана слоя: краснеет только при откате и П1, и П3 (исходный код). R1 и R3/R4 — охрана слоёв по отдельности.

Заявленные гарантии и инъекции (каждую откатываем отдельно; предсказания — ДО прогона, повторены после последнего теста):
- откат П1 (вернуть ленивый импорт в `run()`, убрать шапочный) — красный: R1 (R2 зелёный: цикл ломает П3; R3, R4, R5 зелёные);
- откат П3 (вернуть `from .process_heartbeat import ProcessHeartbeat` в `__init__`) — красные: R3, R4 (R1 и R2 зелёные: П1 грузит пакет до потоков; R5 зелёный);
- откат П1 + П3 вместе — красные: R1, R2, R3, R4 (R5 зелёный);
- мутант R5: удалить `__getattr__` → R5 красный; `__getattr__` бросает `ImportError` вместо `AttributeError` → R5 красный; на неизвестное имя отдаёт `None` → R5 красный;
- мутанты гонки: перехватчик R2/R3 не срабатывает (подменить имя модуля в `Finder`) → тест краснеет по флагу, а не остаётся зелёным.

### ACCEPTANCE

1. R1–R5 зелёные. Радиус без новых красных против `main` (базу `main` брать тем же набором в основном checkout, `medium`): `multiprocess_framework/modules/process_module/tests`,
   `multiprocess_framework/modules/process_manager_module/tests` (`test_alerting*`, `test_telemetry_addressed_delta_*`, `test_observation_port_migration_acceptance*`),
   `Plugins/sources/capture/tests/test_plugin.py`, `multiprocess_framework/modules/statistics_module/tests`. Все через `machine_gate.sh medium D <cmd>`.
2. `python plans/framework-heartbeat-import-race/repro_import_deadlock.py natural_delayA:550 <repo>` ×40: на `main` > 0 `_DeadlockError` из 40, на ветке — 0. Осмысленна только парой:
   шапка скрипта на исправленной ветке сама предзагружает пакет. Режим `det` на ветке — оба исхода `ok`.
3. `sentrux check .` не краснее `main`; `scripts/validate.py` rc 0 — зависит от слияния `fix/validate-red-memory-tags`; запасной вариант: сравнение набора ошибок с `main` (на `main` их ровно две, обе «память»).
4. Стенд (дымовая проверка, не статистика): рестарт ребёнка 30 раз подряд (расписание S2/S3 стенда 1.10) без `_DeadlockError` в логах; при частоте 1/30 вероятность ложного зелёного
   ≈ 0,36, для статистики нужно ≈ 90 рестартов (≈ 0,05). Выполняет лид, числами.

### OUT OF SCOPE

- Дефект C-36 (мёртвая линия camera_0 → consumer_0 после `kill -9`): другая находка.
- Правило «модуль, лениво импортируемый обработчиком или воркером, грузится до старта потоков» и родственная гонка `run():1488` — две строки в OPEN_QUESTIONS (делает лид), не в этой задаче.
- Любые другие рёбра циклов внутри пакета `heartbeat`: R4 ловит только возврат ребра `__init__`.

### TRAPS

- Файл `process_module.py` огромный; ленивый импорт ищем по точной строке, не по номеру.
- `git grep -n "heartbeat import\|heartbeat.process_heartbeat"` — единственный живой потребитель `from ...heartbeat import ProcessHeartbeat` — `process_module/tests/test_rt2_config_flip_acceptance.py:40`; охрана должна быть настоящей (принцип 3).
- Spawn-ребёнок не наследует `sys.modules` родителя; pytest-раннер предзагружает пакет: поэтому тесты только в подпроцессе и с предусловием «пакет не загружен».
- Если R2 построить импортом внутри потока, а не в шапке теста, он станет красным и при П1+П3 — строить как `repro_import_deadlock.py` (импорт `builtin_commands` в шапке до потоков).

## Журнал

- 2026-11-16 — план и Task написаны лидом полосы Д; стадия 0 раунд 1 (reviewer, sonnet): CHANGES REQUESTED 13 пунктов; внесены; решение по вопросу 4 — п. «импорт в шапку `builtin_commands.py`» снят (избыточен, принцип 4), П1 и П3 оставлены.
