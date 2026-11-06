# arch-map 1 — генератор модели архитектуры (developer)

STATUS: DONE_WITH_CONCERNS

Дата 2026-11-06, ветка main, HEAD 1dc6c71b7. Контракт — `docs/arch-map/README.md`. Коммита нет (по брифу).

## Результат

`python scripts/arch_map/build.py` собирает `docs/arch-map/{model.json, model.js, units.md, findings.md}` за ~4 с;
`python scripts/arch_map/build.py --check` -> «модель = код», exit 0. Два прогона подряд: `units.md` и `findings.md`
байт-в-байт равны, `model.json` равен без `meta.generated` (тест + проверка `cmp`).

### Числа (команда `python scripts/arch_map/build.py`)

```
узлы: file 1867, group 13, layer 5, package 316, unit 128 (всего 2329)
рёбра: hard 3831, lazy 795, tc 261 (всего 4887)
находки (всего 1143):
  unit-cycle / warn: 2
  deep-import / warn: 1042
  private-import / warn: 26
  unit-hygiene / info: 67
  unresolved-relative / error: 6
абсолютных импортов внутри корней без файла-цели: 1; файлов не разобрано: 0
```

layer-reverse: 0, card-orphan: 0 (карточка `backend_ctl` сопоставлена, см. ниже). Юнитов 128, из них синтетических
`__root__` — 17; framework-юнитов под слоем — 28 (27 модулей + `multiprocess_framework.__root__`); юнитов без карточки — 16 из 128.

### Тесты

`bash scripts/machine_gate.sh light arch-map .venv/Scripts/python.exe -m pytest scripts/arch_map/tests -q --tb=short`
-> collected 9, `9 passed` (шлюз переклассифицировал light -> medium, окно не потребовалось, exit не 75).
RED до кода: тот же вызов — `ERROR scripts/arch_map/tests/test_build.py` (collection error, нет build.py).
Инъекции (код временно ломался, затем восстановлен, `cmp` с копией — идентично):

| инъекция | упали |
|---|---|
| `drop = level` (не различать `__init__`/файл) | test_relative_import_from_init_and_from_file |
| `inner = kind` (убрать TYPE_CHECKING) | test_edge_kinds_hard_lazy_tc, test_layer_reverse_and_deep_and_private_findings |
| deep-import и на `__root__`-цель | test_layer_reverse_and_deep_and_private_findings |
| `from pkg import sub` не ищет подмодуль | test_relative_import..., test_from_pkg_import_submodule..., test_layer_reverse... |
| unit-cycle всегда error | test_unit_cycle_hard_is_error_lazy_is_warn |

`ruff check` и `ruff format --check` на `scripts/arch_map` — чисто.

## Сверка с scripts/arch_graph/ast_graph.py (framework, модуль -> модуль, по видам)

Команда: `ast_graph.py <scratchpad>/report.txt` -> `ast_graph.json`; мои файловые рёбра свёрнуты в `modules/<X>` (файлы
`_fallback`, `observability_declarations` у них тоже «модули»). Их `lazy_only = lazy - hard`, `tc_only = tc - hard - lazy`
(так отдаёт их json), у меня то же.

| вид | в обоих | только у них | только у меня |
|---|---:|---:|---:|
| hard | 100 | 0 | 0 |
| lazy (без hard) | 18 | 0 | 0 |
| tc (без hard/lazy) | 5 | 0 | 0 |

Расхождений нет. Классы различий, которые есть в КОДЕ, но на этой выборке дают 0 пар (проверено сверкой, а не рассуждением):
1. `def` внутри `if` — у них hard (в `walk_stmt` потомки `def` обходятся без смены вида на lazy), у меня lazy. Пример
   только в фикстуре теста (`Services/svc_a/impl.py:11`); на реальном framework пар с этим отличием нет.
2. У них импорты `multiprocess_framework`, `multiprocess_framework.modules`, `multiprocess_framework.version` не имеют
   владельца (ребро теряется), у меня они — рёбра в `multiprocess_framework.__root__`. В сверку framework-модулей не входит;
   именно эти рёбра дают «цикл через фасад» (см. unit-cycle).

Неожиданного: у меня 100/18/5 — полное равенство; независимая проверка layer-reverse: `rg` по `^\s*(from|import)\s+(Services|Plugins|multiprocess_prototype|backend_ctl)` в `multiprocess_framework`, Services -> Plugins/prototype/backend_ctl, Plugins -> prototype/backend_ctl без тестов — 0 строк.

## unit-cycle (2, обе warn: только lazy)

1. 6 вершин: `multiprocess_framework.modules._fallback` (файл из `__root__`), `base_manager`, `channel_routing_module`,
   `data_schema_module`, `error_module`, `logger_module`.
2. 3 юнита: `process_manager_module`, `process_module`, `statistics_module`.

hard-циклов между вершинами нет.

## layer-reverse

Нет ни одной находки. Prototype -> backend_ctl и backend_ctl -> всё по контракту не находки; backend_ctl сейчас
импортирует framework (hard 9, lazy 10, tc 1), Services (lazy 1), prototype (lazy 11); его не импортирует никто.

## Топ-10 пар юнитов по deep-import

| число | откуда | куда |
|---:|---|---|
| 108 | multiprocess_prototype.frontend | multiprocess_framework.modules.frontend_module |
| 59 | multiprocess_prototype.frontend | multiprocess_prototype.domain |
| 42 | Services.device_hub | Services.robot_comm |
| 35 | multiprocess_prototype.adapters | multiprocess_prototype.domain |
| 21 | multiprocess_framework.modules.process_manager_module | multiprocess_framework.modules.process_module |
| 21 | multiprocess_framework.modules.process_module | multiprocess_framework.modules.logger_module |
| 14 | multiprocess_prototype.frontend | multiprocess_framework.modules.registers_module |
| 13 | Services.dataset_gen | Services.layer_render |
| 13 | multiprocess_prototype.frontend | multiprocess_framework.modules.actions_module |
| 13 | multiprocess_prototype.frontend | multiprocess_prototype.backend |

## unresolved-relative (6, error)

Пять — в `multiprocess_framework/modules/data_schema_module/docs/examples/*.py` (примеры не обновлены под пакет, строки 02_conversion.py:13,
03_registers_and_data_packages.py:9/13/14, 03_validation.py:12) и одна живая: `data_schema_module/storage/storage_manager.py:17`
(`from ...process_module.process_data import ProcessData`; файла `process_module/process_data*` нет — реально битый импорт, проверено `ls`).
Это найденные дефекты кода, не ошибка генератора; я их не правил (вне FILES).

## Файлы

Созданы: `scripts/arch_map/build.py` (960 строк после `ruff format`), `scripts/arch_map/__init__.py` (пустой),
`scripts/arch_map/tests/test_build.py` (9 тестов), `docs/arch-map/{model.json,model.js,units.md,findings.md}`, этот отчёт.
Не тронуты: ast_graph.py, README.md, index.html, cards/.

## Что я трактовал, а не следовал (отклонения от контракта)

1. **Id единственного юнита backend_ctl = `backend_ctl.__root__`**, юнит НЕ помечен `synthetic` (он настоящий). Id слоя уже
   `backend_ctl`, совпасть они не могли. Карточки ключуют его как `backend_ctl` (`cards/services.yaml:333`) — я принимаю ключ
   карточки и по id юнита, и по имени каталога (только для не синтетических юнитов). Решение по id — за лидом.
2. **Файлы в каталоге группы плагинов** (`Plugins/<g>/__init__.py`, 13 файлов) и в корне `Plugins/` собраны в синтетические
   юниты `Plugins.<g>.__root__` / `Plugins.__root__` (в контракте этот случай не описан). Родитель — группа.
3. **Доп. поле `synthetic: true`** на узле синтетического юнита и **`members`** (список вершин) у находки unit-cycle;
   у unit-cycle `src_unit` = первый настоящий юнит компоненты, `dst_unit`/`src`/`dst`/`where` = null.
4. **Вершина графа циклов — настоящий юнит или отдельный ФАЙЛ из `__root__`.** По буквальному контракту (юнит-граф с `__root__`)
   получался один error-цикл из 22 юнитов, целиком из-за склейки фасада `multiprocess_framework/__init__.py` (импортирует всё hard)
   с `modules/_fallback.py`/`version.py` в одну вершину; без склейки hard-циклов нет, остаются 2 lazy-цикла. Для метрик
   fan-in/fan-out `__root__` остаётся единым юнитом, как в контракте.
5. **Серьёзность unit-cycle:** error, если внутри компоненты есть ЛЮБОЙ hard-цикл (не обязательно на всей компоненте).
6. **`--check` игнорирует `meta.generated` И `meta.commit`** (контракт — только generated): иначе проверка краснеет от
   любого чужого коммита в общем дереве при неизменном коде.
7. **Правила про backend_ctl:** все рёбра, где хоть один конец в слое backend_ctl, дают только layer-reverse (framework/
   Services/Plugins -> backend_ctl); deep/private/cycle для них не ведутся, цикл-граф без backend_ctl.
8. **`tests` в спеке юнита** = число файлов `test_*.py` (conftest.py и `tests/__init__.py` не считаются).
9. Добавил правило `card-orphan` (info) в findings (оно в брифе, но не в таблице README).
10. Классификатор импортов не копия ast_graph: `def` внутри `if` — lazy (баг-класс описан выше).
11. Для `ast.Import` (`import a.b.c`) ребро — только в целевой модуль, без неявных рёбер в `a/__init__`, `a/b/__init__`.
    `names` у таких рёбер пуст `[]`.
12. Размер build.py 960 строк против «500–700»: автоформатирование проекта (ruff format) разворачивает длинные вызовы.

## Что оставлено открытым / ненадёжно

- Id `backend_ctl.__root__` и `members` у unit-cycle — не согласованы с вьюером (`archmap-viewer`); если вьюер ждёт
  `src_unit`/`dst_unit` у цикла, увидит null у `dst_unit`.
- Карточки пишутся другими агентами прямо сейчас: числа «без карточки 16 из 128» и `card-orphan 0` — снимок на момент прогона;
  `--check` краснеет, когда карточки меняются (они часть модели).
- `deep-import` в 1042 случая — это сырой счёт «импорт мимо `__init__`/`interfaces`». Витриной считается только эти два узла;
  юниты с другим публичным модулем (`api.py`, `contracts`) дают шум. Это правило контракта, не проверка смысла.
- Абсолютный импорт внутри корней без файла-цели молча пропускается (счётчик в выводе CLI): сейчас 1, и он ведёт в тест
  (`Services/code_reader/tools/thread_split_probe.py:410 -> Services.code_reader.tests.test_sdk_trigger`), тесты в граф не входят.
- Динамические импорты (`importlib`, `__import__`), строки-пути плагинов и реестры в граф не попадают — рёбра только из `import`.
- Файлы в `docs/examples/` внутри юнитов считаются обычными исходниками (в LOC, в рёбрах, в находках): отдельного правила
  «не код» в контракте нет.
- Сверка с ast_graph покрывает только framework; Services/Plugins/prototype независимого эталона не имеют (проверены
  только `rg`-пересчётом layer-reverse = 0).
- Тест `test_real_repo_structural_invariants` строит реальный репозиторий (~4 с) — зависит от текущего дерева; порог «>= 27
  framework-юнитов» привязан к нынешним 28.
- Строки `where` берутся по `lineno` оператора import; у многострочного `from x import (…)` это строка начала оператора.

## Поправка 1 (карточка собирается из юнита, 2026-11-06)

STATUS: DONE_WITH_CONCERNS. Коммита нет. `_card_drafts/` не читался.

Что сделано: убраны чтение `cards/*.yaml` и правило `card-orphan`; `spec.card` собирает `build_card()` из `module.yaml` юнита
(иначе `purpose`/`tier` из корневого `modules.yaml` через `scripts.atlas.modules.load_modules/resolve`), докстринга `__init__.py`
(`summary`), заголовков `ADR-` в `DECISIONS.md` (`adr_count`), литеральных `commands = {...}` и `register_command("...")` (`commands`),
`threading.Thread(name=...)` / `Thread(name=...)` (`threads`); `card.sources` = {поле: путь}. Новые правила `unit-undeclared` (info) и
`registry-drift` (warn); `unresolved-relative` — info внутри `try` с обработчиком ImportError/ModuleNotFoundError/Exception;
каталоги `docs` пропускаются при сканировании; `units.md`: колонка «команд» и раздел «Юниты без объявленных полей».
Переписанных тестов нет: тестов на cards/card-orphan раньше не было (их проверял только прогон на реальном репозитории).
Добавлены 5 тестов из REDS (до кода все 5 красные, после — зелёные); всего collected 14, passed 14.

Числа после поправки (`python scripts/arch_map/build.py`; `--check` -> exit 0):

- узлы: file 1859, group 13, layer 5, package 310, unit 128 (всего 2315); рёбра: hard 3827, lazy 794, tc 261 (всего 4882)
- находки (1250): unit-cycle warn 2; deep-import warn 1042; private-import warn 26; unit-hygiene info 67; unit-undeclared info 111;
  registry-drift warn 1; unresolved-relative info 1 (storage_manager.py:17; пять error из `docs/examples` ушли вместе с каталогом docs)
- покрытие объявленных полей на 111 настоящих юнитах: purpose 110, tier 27, contour 0, runs_in 0 (summary 109, adr_count 41)
- registry-drift полностью: (a) юнит -> other: `Services.camera_device`; (b) путь из modules.yaml не на диске: нет
- команд найдено 175, потоков с name= 31; топ-5 по командам: Plugins.sources.camera_service 18, Plugins.hub.device_hub 17,
  Services.hikvision_camera 13, Plugins.sim.robot_host 12, multiprocess_framework.modules.process_module 10

Трактовка, а не следование:
1. Для синтетических `__root__` карточка тоже строится (declared = null, `summary`/`commands`/`threads` из их файлов, `adr_count` = null);
   `unit-undeclared`/`registry-drift` по ним не ведутся.
2. `card.sources` для `commands` и `threads` указывает каталог юнита (источник — много файлов); у `threads` точное место в `where`.
3. Голый `except:` и `BaseException` считаются защитой так же, как Exception; защита не распространяется на импорты в `def` внутри `try`
   и в самих обработчиках.
4. Поле шильдика `module.yaml` приоритетнее реестра по каждому полю отдельно; `contour`/`runs_in` есть только в шильдике.
5. Пропускается любой каталог с именем `docs` на любой глубине (не только внутри юнитов).
6. `thread name`: литерал — как есть, иначе `ast.unparse` выражения (f-строка даёт `f'w-{i}'`).
7. Правило `registry-drift` (b): путь проверяется только если первый компонент — один из пяти корней.

Что оставлено открытым / ненадёжно:
- `contour` и `runs_in` пусты у всех 111 юнитов, пока нет ни одного `module.yaml`; `tier` объявлен лишь у 27 (в modules.yaml у 61 строки `tier: null`).
- `commands` — только литералы; команды, собранные динамически или объявленные в другом юните, не видны; счёт 175 не проверялся вручную по каждому юниту.
- `adr_count` считает заголовки с `ADR-` и не отличает действующие ADR от отменённых.
- Резолв по `modules.yaml` берёт самый длинный префикс: один модуль реестра может покрывать несколько юнитов (одна и та же `purpose` у всех).
- Тесты на `load_registry` с битым `modules.yaml` нет (ветка с предупреждением не покрыта).

## Поправка 2 (ответ на ревью раунда 1, 2026-11-06)

STATUS: DONE_WITH_CONCERNS. Коммита нет. Актуальные числа основной части отчёта: тестов 23 (не 9), build.py 1209 строк (не 960),
находок 1251, юнитов без `card-orphan` (правило снято в Поправке 1).

Тесты: `collected 23, 23 passed` (gate, exit не 75). Новые (по пунктам 1–5): test_imports_in_method_class_body_async_and_loop,
test_type_checking_in_function_is_tc_and_guarded_flag, test_tc_edges_do_not_count_in_fan_or_cycles,
test_tests_dirs_and_conftest_excluded_but_counted, test_check_detects_edge_only_and_finding_only_diffs,
test_check_covers_all_four_outputs, test_parse_error_finding_and_counts,
test_unresolved_absolute_finding_and_test_target_info, test_recipes_plugin_class_mapped_to_units.

Инъекции ревьюера на КОПИИ build.py (каталог в scratchpad, свой `pytest.ini` с `pythonpath = .`; контроль C0: 22 passed без
`real_repo`, путь импорта доказан — внутри копии; файл репозитория не менялся). Тесты нового кода писались до правок, но красный
прогон ДО правок я не гонял (на старом коде они упали бы на отсутствии функций); сила охранных тестов доказана инъекциями:

| инъекция | красный тест |
|---|---|
| I1 пропуск тел class | test_imports_in_method_class_body_async_and_loop |
| I2 async def не lazy | test_imports_in_method_class_body_async_and_loop |
| I3 tests/test считаются кодом | test_tests_dirs_and_conftest_excluded_but_counted |
| I4 tc-рёбра в графе циклов | test_tc_edges_do_not_count_in_fan_or_cycles |
| I5 fan-in/out считает tc | test_tc_edges_do_not_count_in_fan_or_cycles |
| I6 `--check` не сравнивает рёбра | test_check_detects_edge_only_and_finding_only_diffs |
| I7 `--check` не сравнивает находки | test_check_detects_edge_only_and_finding_only_diffs |
| I10 conftest считается кодом | test_tests_dirs_and_conftest_excluded_but_counted |

Что сделано: `--check` сверяет все четыре файла (model.json и model.js — без generated/commit; md — без SHA в шапке), в stderr имена
расходящихся файлов; битый/отсутствующий файл = расхождение. Новые находки `parse-error` (error), `unresolved-absolute` (warn / info
для тестовой цели), `recipe-unknown-plugin` (warn); `meta.counts.parse_errors` и `unresolved_absolute`. `TYPE_CHECKING` внутри функции
= tc. Ребро получает `"guarded": true` под try/except. `spec.recipes` и колонка «в рецептах» + предупреждение в разделе Plugins.
README синхронизирован с генератором.

Числа (`python scripts/arch_map/build.py`, `--check` exit 0): узлы file 1859, group 13, layer 5, package 310, unit 128; рёбра hard 3827,
lazy 794, tc 261 (4882; `guarded` у 111); находки 1251: unit-cycle warn 2, deep-import warn 1042, private-import warn 26,
unit-hygiene info 67, unit-undeclared info 111, registry-drift warn 1, unresolved-relative info 1, unresolved-absolute info 1;
parse-error 0, recipe-unknown-plugin 0. meta.counts: parse_errors 0, unresolved_absolute 1 (тот же импорт в тест).
Рецепты: 217 строк `plugin_class:` (ревьюер насчитал 205 — у меня все `*.yaml` под multiprocess_prototype, включая не-рецепты), их называют 55 юнитов;
Plugins-юнитов 59, с непустыми `spec.recipes` 50, ни импортов (fan_in 0), ни рецептов — 8 (кандидаты на «не используется»).

Трактовка: (а) тело класса — hard, как у ast_graph (в задании стояло «lazy»; тест фиксирует hard); (б) `from Services.svc_a.ns import inner`
для каталога без `__init__.py` по-прежнему не разрешается, но теперь видно как unresolved-absolute (разрешение namespace-каталогов не делал —
в списке правок его нет); (в) `guarded` ставится и для голого except и BaseException; (г) строка рецепта без `-` и с `-` оба считаются.

Что оставлено открытым / ненадёжно:
- 111 рёбер guarded в unit-cycle не учтены (цикл через необязательную зависимость остаётся hard-циклом).
- `plugin_class` читается регуляркой: значение на следующей строке, якоря YAML и значения не с точечным путём не видны.
- Динамические импорты (23 места по ревью) по-прежнему вне модели; fan-in плагинов остаётся заниженным, пока не заведено ребро-конфиг.
- Красный прогон новых тестов до правок кода не гонялся (см. выше).
- README: абзац про `_card_drafts/` оставлен как есть, каталог не проверялся.

## Поправка 3 (витрина по `__all__`, паспорт снят, рецепты по всему дереву, 2026-11-06)

STATUS: DONE_WITH_CONCERNS. Коммита нет. Тесты: collected 28, passed 28 (gate); до кода 8 из них были красными (REDS плюс три переписанных).

- deep-import: цель `__init__` с литеральным `__all__`, где есть все импортируемые имена (и `import pkg`, и `from pkg import *`) — не находка;
  `__init__` без `__all__` / с нелитеральным `__all__` и имя вне `__all__` (оно названо в detail) — находка. Было 1042, стало 638, снято 404,
  из них 309 с целью `process_module.plugins.__init__` (остальное: frontend_module.widgets.tabs 30, frontend_module.state 7, state_store_module.adapters 5 …).
- Паспорт `module.yaml` не читается. `purpose` = первая строка докстринга `__init__.py` (иначе modules.yaml), `tier` и `contour` — строки `Tier:` / `Contour:`
  докстринга (tier иначе из modules.yaml); `runs_in` и `summary` убраны из карточки и из `unit-undeclared`. Объявлено у 111 настоящих юнитов:
  purpose 111, tier 27, contour 0 (заголовков в докстрингах пока нет).
- Рецепты: `*.yaml`/`*.yml` по всему дереву минус точечные каталоги, `__pycache__`, `node_modules`, `graphify-out`, `logs*`, `data/atlas`; `spec.recipes_inactive` для путей
  с `tests`/`fixtures`/`archive`. Плагинов 59: с живыми рецептами 54; только с неживыми 1 (`Plugins.sources.heartbeat`); ни импортов, ни рецептов 3
  (`Plugins.processing.blur`, `Plugins.runtime.chain_executor`, `Plugins.runtime.worker_pool`). Строк `plugin_class:` 270.
- CLI: обычная сборка выходит с 1, если есть находка `error` (файлы записаны); `--check` не изменился. Сейчас error-находок нет, exit 0.
- Находки теперь: 849 (unit-cycle warn 2, deep-import warn 638, private-import warn 26, unit-hygiene info 67, unit-undeclared info 111, registry-drift warn 1,
  unresolved-relative info 1, unresolved-absolute info 1, recipe-unknown-plugin warn 2). `--check` exit 0.
- Переписаны тесты: test_card_from_local_module_yaml_wins_over_registry -> test_tier_contour_header_lines_and_purpose_from_docstring (проверяет и игнор module.yaml);
  test_card_from_registry_and_derived_fields (purpose теперь из докстринга, без summary/runs_in); test_unit_undeclared_and_registry_drift_findings (без runs_in);
  test_recipes_plugin_class_mapped_to_units (yaml вне prototype теперь сканируется).
- README: убраны module.yaml в таблице файлов, раздел шильдика и абзац про `_card_drafts/`; обновлены deep-import, unit-undeclared, рецепты, код выхода.

Что оставлено открытым / ненадёжно:
- recipe-unknown-plugin 2: `examples/minimal_app/pipeline.yaml:25,36` — пример вне слоёв графа; решение (исключить `examples/` или считать шумом) за лидом.
- Заголовки `Tier:`/`Contour:` читаются регуляркой по всему докстрингу; строка с комментарием после значения (`Tier: core  # …`) не распознаётся как tier.
- «Через витрину» значит только «имя есть в `__all__`»: не проверяется, что `__all__` честно реэкспортирует это имя.
- Для `import pkg` без имён и для `*` витрина принимается без проверки, что `__init__` вообще что-то отдаёт.
- Инъекции для новых тестов этого раунда не прогонялись (красный прогон до кода есть).
