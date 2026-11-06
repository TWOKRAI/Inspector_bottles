# Слияние карты архитектуры с атласом — проект

Дата: 2026-11-06, `main` = `1dc6c71b7`. Основание — слова владельца: «один универсальный механизм и не было дубля»,
«максимально автономно… по коду, чтоб агенты легко считывали что делает модуль или класс или функция и как связывать и
использовать», «лишние можно отложить». Проект составил агент-архитектор (Opus, только чтение) по решениям лида;
замеры времени — его пробы, не повторены. Это проект, не план: задач в `plans/` ещё нет, код не тронут.

## 1. Что сливаем

| | Атлас (`scripts/atlas/`, 4,6 тыс. строк) | Карта (`scripts/arch_map/`, новая, не закоммичена) |
|---|---|---|
| список юнитов | `modules.yaml`, 88 строк | правила «юнит = каталог», 111 юнитов |
| чтение кода | ревизия git, выгрузка на диск (`codemap.checkout`) | рабочее дерево, `os.walk` |
| факты | узлы, рёбра, находки в sqlite; правила П1–П4 (ADR-175) | импорты файл → файл `hard/lazy/tc`, циклы, витрины, команды, потоки, рецепты |
| гейт | `atlas check`: блокирует только новая blocking-находка | свой `--check` «модель = код» |
| виды | `card`, `ref`, `pack`, `index` — текст | сворачиваемая схема `index.html` |

Вердикт архитектора: слить можно. Замер K0 от 2026-10-07 (контекст ADR-175): `atlas ref`/`card` не закрыли ни одного
из 10 вопросов разведки, агент 10 раз читал исходник. Приёмка слияния — тот же замер.

## 2. Почему атлас сейчас медленный (и как это чинится)

- `codemap._unpack` (`codemap.py:78-89`) выгружает ревизию на диск: 4138 файлов. На этой машине запись идёт 65–130 мс
  на файл — 270–540 с. Ключ выгрузки — SHA коммита (`:193`), каждый коммит — холодная выгрузка. 2026-10-11 то же
  занимало ~1,8 с (ADR-ATL-003). Причина замедления записи не выяснена (догадка: антивирус или индексатор).
- `tar failed (rc=3840)` — аварийное завершение MSYS tar, не воспроизводилось; после него `tarfile` распаковывает заново.
- `Tree.read` (`tree.py:67`) — один процесс git на файл, 18,5 мс: 1867 файлов ≈ 35 с. Тоже не годится.
- Путь чтения для слияния — один `git cat-file --batch` (уже есть как `_read`, `adapters/code.py:38`): 1867 файлов за
  0,61 с, разбор `ast` — 1,94 с. Ожидание: справка ≤ 5 с на новом SHA, ≤ 1 с на том же.

## 3. Решения

1. **Один список юнитов** — строки `modules.yaml` (`module:<id>`, `layer`, `parent`). Файл, не попавший ни в одну
   строку, — находка `MODULE_UNMAPPED` (сегодня 4 файла, все в `Services/camera_device`).
2. **Один сканер** — `scripts/atlas/scan.py` поверх протокола `Source` (`files()`, `read_many(paths)`): тот же код
   читает ревизию git и фикстуру в памяти. Факты кэшируются по oid блоба.
3. **Один реестр, две глубины**: адаптер `imports` кладёт в реестр связи модуль → модуль (`depends_on`, вид уже
   зарезервирован в ADR-ATL-001 §2) и находки; детали до файла считает вид `atlas map` тем же сканером.
4. **Один гейт** — `atlas check`. Все новые коды — `warning` или `info`, блокирующих нет (ADR-ATL-002). Ключ находки
   без номеров строк. `--check` карты и закоммиченные сгенерированные файлы удаляются.
5. **Одна карточка** — функция `spec.py::module_spec` кормит и `atlas card`, и панель схемы.
6. **Нового типа файла нет** (поправка лида после чтения ADR-175): оболочка модуля — то, что ADR-175 уже требует.
   Назначение — первая строка докстринга `__init__.py`. Публичная витрина выводится: пакет, чей `__init__.py`
   объявляет `__all__`. Руками — только две строки шапки докстринга: `Tier: core`, `Contour: ipc, lifecycle`.
   «Где исполняется» не объявляется: потоки — из кода, процессы — из листа рантайма.
7. **Справка для агента** (`atlas ref`) на трёх глубинах — модуль, класс, метод: первый абзац докстринга, сигнатура,
   до трёх настоящих мест вызова, тесты как nodeid, для плагина — схема настроек и команды, зависимости в обе стороны;
   `--format json`.

Правило витрин на сегодняшней модели: из 1042 находок «импорт мимо витрины» уходят 404 (309 — в
`process_module.plugins`, 30 — в `frontend_module.widgets.tabs`); оставшиеся 638 сворачиваются в 363 ключа.

## 4. Задачи «сейчас» (решение владельца 2026-11-06: лишнее отложить)

Порядок: A1 → A2 → A3, затем B1 → B2. После A3 — остановка и замер K0. Все задачи — в `scripts/atlas`, ядро
framework не трогают.

### A1 — ядро сканера и кэш по блобам (Senior+)

> **Стадия 0 (2026-11-06): раунд 1 CHANGES REQUESTED, правки внесены в отдельный файл задачи** —
> `plans/2026-10-04_atlas/tasks/map-A1.md` (расположение предварительное); отчёт — `docs/reviews/2026-11-06_task-atlas-map-A1-stage0.md`. Решения лида:
> - D1: предел блоба `MAX_BLOB_BYTES = 1_048_576`, больше — `FileFacts(loc=0, error="BlobTooLarge")`.
> - D2: каталог без `__init__.py` не модуль (как в карте); число случаев на HEAD — разовая сверка, шум решает B1.
> - D3: `roots` берутся из индекса, не из `LAYER_ORDER`; сверка с дистрибутивами и с `resolve_import` карты — разовая.
> - D4: сигнатуры, докстринги, `calls` не в A1 — приходят в A3 вместе со сменой `SCANNER`.
> - D5: `ClassFact.methods` сохраняет dunder-члены (дефект K0 с `IConfigObserver.__call__`); красный 14.

- **Дизайн.** Новый `scripts/atlas/scan.py`: `Source(Protocol)` + `DictSource`; `FileFacts` (loc, doc, all, classes,
  functions с сигнатурой и докстрингом, imports как `ImportRec(kind, line, level, module, names, guarded)`, calls,
  commands, threads, header); `scan_text`, `scan(source, paths, cache)`, `ImportIndex.resolve`. Из карты переносятся
  `collect_imports`, `is_type_checking`, `catches_import_error`, `leaf_name`, `class_style`, `literal_names`,
  `collect_derived`, `resolve_relative`, `resolve_import`. `Tree` получает `oids()` (`ls-tree -r -z`) и `read_many()`;
  `_read` переезжает туда, старое имя остаётся псевдонимом для `reference.py:21` и `rules.py:20`. Новая таблица
  `scan_cache(oid, scanner, body)`, `_SCHEMA` 4 → 5 (`store.py:49-50`).
- **Файлы:** `scan.py` (новый), `tree.py`, `store.py`, `adapters/code.py`, `tests/test_scan.py` (новый).
- **Красные (`test_scan.py::`):** `test_tree_and_dict_source_give_equal_facts`, `test_import_kinds_hard_lazy_tc`,
  `test_guarded_relative_import_marked_guarded`, `test_from_pkg_import_submodule_targets_submodule`,
  `test_init_level_one_is_package`, `test_commands_and_threads_literals`, `test_all_plus_equals`,
  `test_header_tier_contour_parsed`, `test_one_git_process_per_scan`, `test_blob_cache_reparses_only_changed_oids`.
- ~~**Приёмка:** 1867 файлов ≤ 2,6 с холодно, ≤ 1 с после коммита; один процесс git на чтение.~~ Заменено, см. задачу `map-A1.md`.
- **Вне задачи:** адаптеры, виды, удаление карты.

### A2 — код в памяти, без выгрузки на диск (Senior+, после A1)

- **Дизайн.** `codemap.Code` (`:290`) строится поверх `Source` и фактов: `info()` (`:372`) — из фактов; `graph()` и
  `_importers()` (`:325`, `:361`) — обратный индекс из `ImportIndex`, grimp удаляется; `_class` оставляет
  `griffe.visit(code=…)` (`:490`) с виртуальным путём. Удаляются `checkout`, `_unpack`, `_cache_dir`, `_prune`,
  `_move_into_place`, `_discard` (`:78-231`). `code_of` сохраняет сигнатуру (вызовы `views.py:137`, `reference.py:320`).
- **Нельзя менять:** текст вывода `ref` и `card`. Оракул — `test_usage.py`, `test_reference_pinned.py`,
  `test_views_pinned.py`, `test_card_pack_1_6c.py`, остаются зелёными без правок.
- **Удаляются тесты:** `test_checkout_1_6g.py`, `test_checkout_rename_retry.py`, tar-тесты `test_speed_1_6g.py:108, :124`.
  ADR-ATL-003 получает поправку.
- **Файлы:** `codemap.py`, `reference.py`, `views.py`, `rules.py` (`Scan.of_module` `:180`), `DECISIONS.md`,
  `tests/test_codemap_memory.py` (новый).
- **Красные (`test_codemap_memory.py::`):** `test_no_checkout_dir_created`, `test_usage_matches_previous_on_f1`,
  `test_describe_protocol_abc_in_memory`, `test_module_users_from_scan_index`, `test_ref_cold_after_commit_under_5s`,
  `test_unparsable_file_still_usage_unknown`.
- **Приёмка:** `atlas ref router_module` ≤ 5 с на новом SHA, ≤ 1 с на том же; каталог `data/atlas/checkout` не создаётся.

### A3 — справка для агента (Senior+, после A2)

- **Дизайн.** В `reference.ref` (`:281`): `--symbol` принимает `Class.method`; новый `--format json` (dest `fmt`; флаг
  `--json` на подкоманде столкнулся бы с верхним `--json`, `__main__.py:46`, `:105-116`); `ref` перестаёт звать `build`
  (`:300`), имена интерфейсов — из `_interface_names` (`adapters/code.py:61`) по фактам. Новые строки: первый абзац
  докстринга (`_paragraph` рядом с `_phrase` `:140`); конструктор и до трёх мест вызова, короткий путь первым,
  `файл:строка`; тесты как nodeid; у плагина — подкласс `SchemaBase` и словарь `commands`; у менеджера — команды и
  потоки; зависимости в обе стороны. Символ без докстринга печатает `нет описания` (`_NO_DOC` `:35`) и id находки П2.
- **Файлы:** `reference.py`, `__main__.py` (`:54-56`), `scan.py`, `tests/test_lookup_d9.py`, `tests/test_k0_questions.py`,
  `tests/k0_questions.json` (новые).
- **Красные (`test_lookup_d9.py::`):** `test_method_lookup`, `test_docstring_first_paragraph`,
  `test_call_sites_shortest_first_max3`, `test_tests_as_nodeids`, `test_format_json_keys`,
  `test_missing_docstring_marker`, `test_plugin_config_schema_and_commands`, `test_ref_does_not_call_build`;
  плюс `test_k0_questions.py::test_k0_answered_without_source`.
- **Приёмка — замер K0:** «N из 10 вопросов закрыто справкой без чтения исходника», порог 8 (оценка архитектора по
  чтению брифов — 7–8; порог уточняет лид после первого прогона). Вопросы — 10 случаев, когда агент читал исходник:
  бриф 1.1 (`plans/2026-10-07_k0-framework-quality/tasks/1.1.md:204`): вид интерфейса и кто реализует; реализация без
  наследования (`RouterManager`, `Config`); члены `IConfigObserver`; унаследованные абстрактные члены `IConfigManager`.
  Бриф 1.2 (`tasks/1.2.md:207`): сам объект `tools/watcher.py`; что уже закрепляет `tests/test_watcher.py`; кто зовёт
  watcher (`observability_reload.py`); кто зовёт и за чем он следит (`orchestrator.py`); кто пишет наблюдаемый файл
  (`observability_companion.py`); как пишет `save_to_file` (`converter.py`). Процедура: `k0_questions.json` — вопрос,
  закреплённая ревизия, аргументы atlas, ожидаемые литералы; прогон через `replay.run` (`replay.py:30`, в список
  разрешённого добавить `--format`); вопрос закрыт, если все литералы есть в выводе. Вопрос «кто пишет файл» скорее
  всего не закроется: нужен поток данных по литералам путей.
- **Опыт 2026-11-06 (сырая карта против чтения кода, один прогон, Haiku).** По `model.json` полностью закрыт 1 вопрос
  из 10 (кто импортирует watcher), 54 вызова, ~105k токенов; по исходникам — 6 из 10, 40 вызовов, ~85k. Чего не
  хватило карте — это обязательные поля справки A3: (1) сигнатуры, включая `__init__`; (2) признак `abstractmethod`
  у члена интерфейса; (3) обратный индекс «кто наследует», плюс пометка «совпадает по именам методов, не наследует»;
  (4) dunder-члены Protocol — сейчас `IConfigObserver.__call__` в модель не попадает, `methods: []`; (5) первый абзац
  докстринга; (6) тесты как nodeid; (7) места вызова, а не только импорта (`observability_reload.py:2341` карта не
  видит). Вопросы 8 и 9 (за каким файлом следит, кто его пишет) без потока данных не закрываются — в порог не входят.
  Таблица по вопросам — `docs/handoffs/2026-11-06_arch-map-atlas-merge.md`.

### B1 — адаптер `imports` и одна карточка (Senior+, после A1)

- **Дизайн.** Новый `adapters/imports.py::ImportsAdapter`, `version = adapter_version(1, file, scan.py)` (`plans.py:42`):
  рёбра `depends_on` (одно на пару и вид) и находки. Входит в `ADAPTERS` (`build.py:28`) — меняется ключ кэша.
  Новый `spec.py::module_spec` (назначение, ярус, контур, команды, потоки, рецепты, число ADR, fan-in/out, размеры);
  `views.card` (`:162`) дописывает его строки после `:202`. `check.py` не трогается.
- **Коды находок** (`Finding(code, severity, "module:<id>", detail без строк, message, "путь:строка")`):

  | Правило карты | Код атласа | Серьёзность |
  |---|---|---|
  | импорт против слоёв | `LAYER_REVERSE` | warning; info для `tc` |
  | цикл юнитов | `MODULE_CYCLE` | warning по `hard`; info только `lazy` |
  | импорт мимо витрины (с правилом `__all__`) | `DEEP_IMPORT` | info |
  | импорт приватного имени | `PRIVATE_IMPORT` | warning |
  | неразрешённый импорт | `IMPORT_UNRESOLVED` | warning; info под `try/except ImportError` |
  | файл вне `modules.yaml` / путь из него не существует | `MODULE_UNMAPPED` / `MODULE_PATH_MISSING` | info / warning |
  | оболочка неполна, шапка не объявлена | `MODULE_SHELL` | info |
  | файл не разобран | `SOURCE_UNPARSED` | warning |

- **Файлы:** `adapters/imports.py`, `spec.py` (новые), `build.py`, `views.py`, `DECISIONS.md` (ADR-ATL-005, строки в
  таблицу ADR-ATL-002 §2), `tests/test_adapters_imports.py` (новый).
- **Красные (`test_adapters_imports.py::`):** `test_depends_on_one_edge_per_kind`, `test_layer_reverse_warning_tc_info`,
  `test_module_cycle_hard_warning_lazy_info`, `test_deep_import_skips_init_with_all`,
  `test_deep_import_name_outside_all_fires`, `test_private_import`, `test_unmapped_file`, `test_no_blocking_severity`,
  `test_check_stable_after_line_shift`, `test_card_spec_lines_appended`.
- **Приёмка:** адаптер ≤ 5 с холодно; `atlas check` на HEAD по новым кодам даёт только warning/info; байты
  `docs/atlas/INDEX.md` не меняются.

### B2 — вид `atlas map`, удаление отдельной карты (Middle, после B1)

- **Дизайн.** Новый `mapview.py::model()` — модель schema 1 по контракту `docs/arch-map/README.md` (слой → цепочка
  `parent` → модуль → пакет → файл; рёбра файл → файл с именами и строкой; находки из реестра; `spec` = `module_spec`);
  `write()` кладёт `data/atlas/map/{model.js, index.html}` (`data/` в `.gitignore:135`); кэш — `view_cache`, вид `map`.
  Просмотрщик переезжает в `scripts/atlas/assets/arch_map.html`. Удаляются `scripts/arch_map/` и сгенерированные файлы
  `docs/arch-map/`; тесты карты переносятся в `test_scan.py` и `test_adapters_imports.py`; README карты становится
  ADR-ATL-005. `scripts/arch_graph/ast_graph.py` (третий сканер, 277 строк) удаляется по слову владельца.
- **Файлы:** `mapview.py` (новый), `__main__.py`, `assets/arch_map.html`, `tests/test_map_view.py` (новый), удаления.
- **Красные (`test_map_view.py::`):** `test_schema1_top_keys`, `test_hierarchy_layer_parent_module_package_file`,
  `test_spec_is_module_spec`, `test_writes_only_data_atlas_map`, `test_cached_in_view_cache`, `test_viewer_loads_model_js`.
- **Приёмка:** схема открывается с диска из `data/atlas/map/index.html`; тёплый вызов ≤ 1 с.

## 5. Отложено (кандидаты без плана и писателя)

| Что | Зависит от | Заметка |
|---|---|---|
| `ref --find <Имя>` без указания модуля | A3 | Middle |
| храповик докстрингов для Services и Plugins | A3 | П2 сегодня покрывает только framework (`rules.py:425-430`), warning |
| `atlas diff` — что меняет ветка | B1 | переиспользует `check._renames`, `translate_node` |
| скрытые связи из истории git (`co_changes`) | B1 | в адаптере коммитов |
| шапки `Tier:`/`Contour:` в 36 `__init__.py` framework, генерируемая таблица `MODULE_TIERS.md` | B1 | правит докстринги ядра; заменяет `test_module_tiers.py:91-122` |
| `atlas new <слой> <id>` — модуль по шаблону | шапки | шаблон из `MODULE_README_TEMPLATE.md` и навыка `module-contract` |
| удаление дублей из `validate.py` (проверки 4, 5, 5а, 5б, `:162-232`) | находки оболочки | по слову владельца |
| команды из `@expose` / `CommandSpec` | A3, B1 | после 1.0, трогает ядро (`base_manager`, `command_module`) |
| лист рантайма с `backend_ctl` по рецепту | B2 | после 1.0, нужно окно стенда; отдельный снимок (рецепт, SHA), в ключ гейта не входит |
| записи атласа в qex с фильтром по модулю | A3 | идея владельца 2026-11-06 («нейросеть на модуль»): отдельная модель на модуль не нужна; вывод `ref`/`card` индексируется как документы qex с полем модуля, обновление только по изменённым файлам (oid). Нужен живой Ollama |

## 6. Влияние на другие полосы

- Локальные хуки атлас не зовут (`commit-msg` → `validate_commit.py`, `pre-push` → pre-commit; в `.claude/hooks` и
  `pre_report_gate.py` атласа нет). Вне `scripts/atlas` его никто не импортирует.
- CI: `ci.yml:195-204` (`atlas check`, две холодные сборки) — плюс ~6 с; `ci.yml:207-209` (`index --check`) — плюс ~3 с.
- Локально: `_SCHEMA` 4 → 5 один раз сбрасывает `data/atlas.sqlite` (289 МБ); первая сборка у каждой полосы холодная (~13 с).
- После A2 `card` и `ref` перестают стоить минуты после каждого коммита — для всех полос.

## 7. Вопросы владельцу

1. Удалить выгрузку на диск и grimp целиком (поправка к ADR-ATL-003)? Архитектор и лид: да.
2. Удалить `scripts/arch_graph/ast_graph.py` в задаче B2?
3. Убрать из `modules.yaml` колонки `purpose` и `tier`, когда они начнут выводиться из докстринга? (Отложенная задача.)

## 8. Что не проверено

- Замеры времени — пробы архитектора на этой машине, без повторов и разброса.
- Байтовое равенство вывода `ref`/`card` после замены grimp на индекс сканера — это оракул задачи A2, не проверено.
- Принимает ли ruff `D` (google) строки `Tier:`/`Contour:` в докстринге.
- Числа «404 из 1042» посчитаны по юнитам-каталогам карты; под юнитами `modules.yaml` не пересчитаны.
- Оценка «7–8 из 10» по K0 — по чтению брифов, не по прогону.
- Карта (`scripts/arch_map/`): ревью Sonnet, раунд 2 — APPROVED, остались minor
  (`docs/reviews/2026-11-06_task-arch-map-1-review.md`). Слепого тестера у карты не было; её тесты — авторские,
  проверены 12 инъекциями ревьюера. Рецепты вне `multiprocess_prototype` (`apps/line_sim/pipeline.yaml` и др.) карта
  на момент записи не видит.
