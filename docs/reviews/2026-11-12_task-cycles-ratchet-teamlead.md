# 2026-11-12 — cycles-ratchet-and-logger-seam (teamlead): полный отчёт

Ветка `fix/framework-acyclicity`, основное дерево, без коммита.

## Предсказания break-injection (записаны ДО прогонов)

Все инъекции — скриптом (замена строки), откат — из копий в scratchpad, не `git checkout`.
Прогон каждой: `pytest data_schema_module/tests/test_logger_seam_no_direct_logger_import.py
tests/test_import_cycles_ratchet.py data_schema_module/tests/test_metrics_freeze_hazards.py`.

| id | инъекция | предсказано красным | предсказано зелёным |
|---|---|---|---|
| a | `field_meta.py`, сайт «неизвестные правила»: вернуть `from ...logger_module import get_std_logger` + `get_std_logger(__name__).warning(...)` (код HEAD) | AST `test_field_meta_has_no_direct_logger_module_import`; строгий `largest` (>41) и `files` (>62); по швам `largest` (>19) и `files` (>40); оба теста эффекта (имя станет `mpf.`-префиксным) | оба `count`, AST metrics, охрана швов, все hazard-тесты metrics |
| b | `metrics.py::_std_logger`: убрать резолв под `try` — вернуть НЕрезолвнутый `FallbackLogger` | ровно один: `test_std_logger_returns_none_instead_of_raising_on_a_circular_import` (ожидает `None` при кольце) | `test_the_voice_never_kills_the_package_when_the_logger_is_unreachable` — ЗЕЛЁНЫЙ: он подменяет `_std_logger` целиком и обёртку не видит; всё остальное зелёное (рёбра графа не меняются) |
| c1 | `metrics.py`: новая функция с ленивым `from ...logger_module import get_std_logger` (обход двери) | AST `test_metrics_has_no_direct_logger_module_import`; строгий `largest`/`files`; по швам `largest`/`files` | оба `count`, AST field_meta, эффект, hazard-тесты |
| c2 | `data_schema_module/serialization/converter.py` (вне FILES, временно): ленивый `from ...config_module.tools import loader` — замыкает новую пару с `config_module/tools/loader.py -> converter.py` | строгий `count` (7>6) и `files`; по швам `count` и `files`; сообщение называет `config_module/tools/loader.py` и `converter.py` | оба `largest` (новая компонента мала), AST, эффект, hazard-тесты |
| c3 | (добавлена после c2) `base_manager/interfaces.py` (вне FILES, временно): ленивый `import ...channel_routing_module.interfaces` — новая изолированная пара | оба `count` (7>6), оба `files`; сообщение называет эту пару | оба `largest`, охрана швов |

## Получено

| id | предсказано | получено | совпало |
|---|---|---|---|
| a | AST field_meta; строгий largest/files; по швам largest/files; 2 теста эффекта | ровно эти 7: строгий 43>41, 64>62; по швам 35>19, 56>40; эффект: имя `mpf.multiprocess_framework...field_meta` | да |
| b | только `test_std_logger_returns_none_instead_of_raising_on_a_circular_import`; `..._voice_never_kills_the_package...` зелёный | `1 failed, 21 passed` — ровно он | да |
| c1 | AST metrics; строгий/по швам largest+files | ровно эти 5: 43>41, 64>62, 33>19, 54>40 | да |
| c2 | count и files красные; largest зелёные | **промах**: count зелёный (6), красные largest/files: строгий 47>41, 68>62, по швам 32>19, 53>40 — `config_module/tools/loader.py` достаёт до большой SCC, новая пара слилась с ней | частично: храповик красный, но не теми тестами |
| c3 | оба count, оба files; сообщение называет пару | `4 failed, 4 passed`: count 7>6 (оба), files 64>62 и 42>40. Первая версия сообщения назвала ЧУЖУЮ пару (`recipe/service.py`) — сравнение по одним размерам; исправлено на сравнение по (первый файл, размер), повтор назвал `base_manager/interfaces.py, channel_routing_module/interfaces.py` | да, после правки сообщения |

Все откаты — `shutil.copy2` из копии + сверка md5 (`restored ... md5 ok` на каждой). `git status` после серии — только 4 файла задачи + этот отчёт.

## Числа храповика (`python multiprocess_framework/modules/tests/test_import_cycles_ratchet.py`)

| состояние | строгий: SCC / наибольшая / файлов | по швам: SCC / наибольшая / файлов |
|---|---|---|
| HEAD, до правок (файлы HEAD подставлены из копий) | 6 / 43 / 64, размеры (43,11,4,2,2,2) | 6 / 38 / 59, (38,11,4,2,2,2) |
| после правок | 6 / 41 / 62, (41,11,4,2,2,2) | 6 / 19 / 40, (19,11,4,2,2,2) |

Прогоны REDS на HEAD-коде: с литералами ПОСЛЕ — `8 failed, 4 passed` (2 AST, 2 эффекта, строгий largest/files, по швам largest/files); с литералами ДО (43/64, 38/59) — храповик `8 passed`.

Почему не 24: дверь `_fallback.FallbackLogger` ПЕРЕНОСИТ ребро, а не режет его. Её ленивое ребро
`_fallback.py -> logger_module/adapters/std_facade.py` строгий счёт видит, и data_schema остаётся в
SCC через `field_meta/metrics -> _fallback -> std_facade -> ... -> channel_routing -> data_schema`.
Из SCC ушли только `logger_module/__init__.py` и `logger_module/configs/__init__.py`. 24 — это
«data_schema без исходящего ребра вообще» (what-if скрипт). Решение лида: два храповика (строгий +
по `SANCTIONED_SEAMS`).

## Приёмка

- `pytest data_schema_module tests` (gate medium, cwd modules): `2 failed, 949 passed, 1 skipped in 468.46s`.
  Оба красных в `tests/`, не мои:
  - `test_module_tiers.py::test_no_test_dir_is_invisible_to_every_runner` — список невидимых каталогов:
    `.claude/_backups/...`, `_archive/...`, `data/atlas/checkout/<sha>/...`, `scripts/alpha_sim/tests`,
    `scripts/nav_bench/tests`; каталогов этой задачи в списке нет. Состояние диска/репо.
  - `test_declarations_leak_order_independence.py::test_statistics_then_process_module_order_matches_the_reverse_order` —
    вложенный прогон: 3 failed. Отдельно: `test_pacing_hazards::test_idle_cycle_duration_measured_with_fine_clock`
    зелёный (флак под нагрузкой); два `test_t45b_process_fields` (`TestPluginRunnerMs::..._first_sample_seeds`,
    `TestIntrospectQueuesCapacity::..._keeps_queue_sizes`) красные И на HEAD-коде этих двух файлов (`2 failed in 0.73s`).
- Чистый `python -I` (sys.path = корень репо), пакет первым: data_schema_module rc=0, logger_module rc=0,
  channel_routing_module rc=0, process_module rc=0.
- После чистого `import data_schema_module`: `metrics._logger` = `FallbackLogger`, вид `StdLoggerFacade`,
  `_voice_sounded == True`, `logger_module` в `sys.modules` — кольцо на импорте исполняется как раньше.
- `sentrux check .`: `Quality: 6898`, `✓ All rules pass`.
- Время храповика: setup 1.38 с (граф 832 файлов), весь файл < 2 с.
- ruff check / format --check по 4 файлам: чисто.

## Замечания

1. **Имя stdlib-логгера изменилось.** На HEAD записи шли в `mpf.multiprocess_framework.modules.data_schema_module.core.field_meta`
   (то же для `...core.metrics`) — `get_std_logger(__name__)` без `fallback_name`. Через дверь —
   `multiprocess_framework.modules.data_schema_module.core.field_meta` (без `mpf.`), как требует тест шва
   по брифу и шапка `_fallback.py`. Текст и уровень не менялись. Кто фильтрует по `mpf.`-префиксу без
   менеджера — увидит переезд. С живым менеджером имя не проверял.
2. `metrics._std_logger` зовёт приватный `FallbackLogger._resolve()` — иначе тест
   `test_std_logger_returns_none_instead_of_raising_on_a_circular_import` (ждёт `None` от `_std_logger()`)
   не выполним без правки `_fallback.py`. Отвергнуто: публичный `ensure()/resolve()` в `_fallback.py`
   (вне FILES); запись-проба (меняет журнал); `importlib` строкой (прячет ребро от храповика).
3. Тест `test_the_voice_never_kills_the_package_when_the_logger_is_unreachable` обёртку НЕ сторожит
   (подменяет `_std_logger` целиком) — инъекция b его не краснит. Сторож обёртки — только тест «returns None».
4. В `field_meta.py` ленивых импортов было три (стр. 480/488/495), не два; переведены все.
5. Модель графа не добавляет неявные `__init__.py` родителей и не видит `importlib.import_module`.

## Раунд 2 (правки по ревью Opus): предсказания ДО прогонов

| id | инъекция | предсказано красным | предсказано зелёным |
|---|---|---|---|
| S | убрать ленивый импорт, дающий обратное ребро одной из 2-файловых SCC (файл выбирает скрипт, строка -> `pass`) | 4 теста: оба `count` (6 -> 5) и оба `files` (62 -> 60, 40 -> 38), текст «цикл уменьшился (было 6, стало 5): подтяни литерал до 5, это нормальная победа» | оба `largest`, охрана швов |
| 4b | `metrics.py::_std_logger`: убрать `resolve()` под `try` (отдать нерезолвнутую дверь) | `test_logger_module_first_survives_the_voice_ring` (rc=1, `ImportError ... 'ChannelRoutingManager' ... partially initialized`); `test_std_logger_returns_none_instead_of_raising_on_a_circular_import`; с низкой уверенностью ещё `test_unknown_rule_warning_in_a_clean_process_with_the_package_first` (если кольцо ловит и порядок «data_schema первым») | AST, храповик, `test_fallback_handle.py` |

## Раунд 2: получено

| id | предсказано | получено | совпало |
|---|---|---|---|
| S | 4 красных (оба count 6->5, оба files 62->60 / 40->38), текст «цикл уменьшился» | скрипт убрал `from .manifest import load_manifest` (`app_module/store.py:203`); `4 failed, 4 passed`; ровно эти 4, тексты «[строгий] count: цикл уменьшился (было 6, стало 5): подтяни литерал до 5, это нормальная победа», «files ... (было 62, стало 60)», «[по швам] ... (было 40, стало 38)» | да |
| 4b | hazard «logger_module первым» + «returns None»; с низкой уверенностью — проба «data_schema первым» | `3 failed, 37 passed`: все три; оба подпроцесса rc=1 с `ImportError: cannot import name 'ChannelRoutingManager' from partially initialized module 'multiprocess_framework.modules.channel_routing_module'` | да (включая неуверенное) |

Откаты — из копий, md5 сверен (`restored ... md5 ok`).

## Раунд 2: приёмка

- `pytest data_schema_module logger_module/tests/test_fallback_handle.py tests/test_import_cycles_ratchet.py` (gate medium): `680 passed, 1 warning in 4.45s`, rc=0.
- Чистый `python -I`, пакет первым: data_schema_module / logger_module / channel_routing_module / process_module — rc=0, stderr 0 байт.
- `sentrux check .`: `Quality: 6898`, `✓ All rules pass`.
- `python -m scripts.sync`: rc=0, вывода нет, файлов не изменил (глобальный индекс уже актуален).
- `python scripts/validate.py`: rc=1, ровно два различных `[FAIL]` — «память: ошибки тегов…» и «память: индекс BY-MODULE*.md устарел…» (каждый печатается дважды: деталь + сводка). Новых нет.
- ruff check / format --check по всем изменённым .py: чисто.

## Раунд 2: что изменено

- `_fallback.py`: аддитивно `FallbackLogger.resolve() -> Any` (делегирует в `_resolve()`), +8 строк.
- `metrics.py`: `log._resolve()` -> `log.resolve()` (снят ставший ложным комментарий про приватный метод); докстринг `MetricsCollector` — «через дверь `_fallback.FallbackLogger`».
- `test_fallback_handle.py`: `test_resolve_returns_the_view_of_the_first_write_and_keeps_it`, `test_resolve_does_not_swallow_import_error`.
- Храповик: `==` вместо `<=` (рост — прежний текст с компонентой, сжатие — «подтяни литерал»), тесты `..._matches_baseline`, docstring — слепое пятно (родительские `__init__.py`, `importlib`; 87/52/33 у Opus) и оговорка «строгий 43 -> 41 — артефакт модели; измеренный выигрыш шва — по швам 38 -> 19»; текст охраны швов — ADR-DS-009. Литералы не менялись.
- Тест шва: подмена корня `multiprocess_framework` (`types.ModuleType` + `__path__`) в обеих пробах; новый hazard `test_logger_module_first_survives_the_voice_ring` (rc=0, пустой stderr).
- `DECISIONS.md` ADR-DS-009: п.4 и п.7 под дверь; новый блок «Шов ... через дверь» с (i) резолв до флага, (ii) имя без `mpf.`, (iii) единственный санкционированный шов и правило роста списка.

## Раунд 2: открыто

- «Трижды заходит рекурсивно под RLock» и «A/B побайтно при живом менеджере» в ADR — со слов ревью Opus, сам не воспроизводил.
- `DECISIONS.md` data_schema_module 44.5 КБ при бюджете 32 КБ (до правок было ~41.9 КБ), секция ADR-DS-009 9.3 КБ > 8 КБ — хук doc-size-guard; разбиение вне задачи.
- В рабочем дереве чужая правка `docs/claude/memory/feedback_lazy_import_for_layer0_data_schema_files.md` — не моя, не трогал.
