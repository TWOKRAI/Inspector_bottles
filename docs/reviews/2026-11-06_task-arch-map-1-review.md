# arch-map 1 — ревью генератора модели (reviewer, раунд 1)

VERDICT: CHANGES REQUESTED

Дата 2026-11-06, HEAD 1dc6c71b7, ветка main. Репозиторий не менялся, коммитов и `git add` нет. Единственный созданный файл — этот отчёт.
Стадия слепого тестера не проводилась; 14 тестов — авторские. Принято и не разбиралось: шум `deep-import`, `commands` только литералы, динамические импорты вне охвата.

Итог: рёбра модели совпали с независимой сверкой (0 расхождений на 4882 рёбрах), но охранные тесты и `--check` не ловят класс поломок, который бьёт именно в свойство «модель не лжёт и не пропускает молча», а часть пропусков модель делает без следа.

## A. Полнота рёбер (независимо от генератора)

- Вручную прочитано 14 файлов (framework 4, Services 3, Plugins 2, prototype 3, backend_ctl 2), около 300 операторов import, сверка с рёбрами `model.json` по (src, dst, kind, names, line): 0 расхождений.
  Файлы: `multiprocess_framework/modules/_fallback.py` (уровень 3 в докстринге, lazy в теле), `app_module/builder.py` (tc + 13 lazy), `config_module/tools/__init__.py` (`__init__` + `try/except ImportError`), `chain_module/worker_pool/dispatcher.py` (`from ...base_manager`, уровень 3), `Services/robot_comm/__init__.py` (`__init__` + TYPE_CHECKING, alias `as`), `Services/dataset_gen/export.py`, `Services/vfd_comm/core/client.py`, `Plugins/hub/device_hub/plugin.py`, `Plugins/sim/scene_source/plugin.py`, `multiprocess_prototype/frontend/bridge/command_catalog.py` (`from ...registers`, уровень 3), `multiprocess_prototype/main.py`, `multiprocess_prototype/frontend/app.py` (около 90 импортов), `backend_ctl/harness.py`, `backend_ctl/mcp_server_sdk.py`.
- Полная независимая сверка (мой скрипт, не код репозитория: `ast.walk` с указателями на родителя + разрешение по файловой системе с учётом регистра): 4883 моих ребра против 4882 в модели по ключу (src, line, dst, kind): 0 расхождений, кроме одного ребра в тест-файл, исключённый из графа по замыслу (`Services/code_reader/tools/thread_split_probe.py:410 -> Services/code_reader/tests/test_sdk_trigger.py`). Набор файлов графа совпал: 1859 = 1859.
- Оговорка: первый прогон показал 71 «пропуск» — артефакт моей проверки (Windows сравнивает имена без учёта регистра: `Port` -> `port.py`); исправлено точным листингом каталога, генератор здесь прав.

## B. Негативное пространство (динамические импорты)

`rg -n "importlib|__import__\(" <слой> -g "*.py" -g "!*test*" -g "!**/tests/**" -g "!**/docs/**"`: строк/файлов — framework 45/15, Services 16/7, Plugins 5/2, prototype 3/1, backend_ctl 1/1 (всего 70 строк в 26 файлах; сюда входят `import importlib` и `find_spec` как проверка доступности).
Живые вызовы (`import_module(`, `spec_from_file_location(`, `__import__(`, `reload(`): framework 17, Services 3, Plugins 2, prototype 1, backend_ctl 1 (ложное: строка в генераторе зонда `probes/break_inject_g3_seams.py:68`) — итого 23 места, которые модель не видит.
Примеры: `Services/robot_comm/__init__.py:83` (ленивый фасад `getattr(importlib.import_module(target[0]), ...)`), `multiprocess_framework/modules/process_module/plugins/manager.py:221` и `:376` (загрузка плагинов по строке `module_path`), `Plugins/runtime/chain_executor/plugin.py:146`.
Декларативная слепота (тяжелее по весу): 205 строк `plugin_class: Plugins.… | Services.…` в 37 yaml-рецептах `multiprocess_prototype/recipes` называют 54 юнита. У 47 из этих 54 `fan_in == 0` в модели; у 55 из 59 юнитов `Plugins` `fan_in == 0`. `units.md` не предупреждает, что fan-in не видит загрузку по конфигу.

## C. Границы юнитов

- Services: 18 настоящих юнитов на диске = 18 в модели (`Services/tests` — только тесты, узла нет).
- multiprocess_prototype: 6 = 6 (adapters, backend, domain, frontend, recipes, registers); `data`, `docs`, `plans` без `.py`.
- Plugins: все 13 групп, 59 юнитов на диске = 59 в модели (в том числе `_shared`, `utility`, `sinks`, `hub`, `filter`, `io`, `processing`).
- framework: 27 модулей = 27 (+`__root__` = 28); `modules/tests` — только тесты.
- Учёт всех `.py` под пятью корнями: 3849 = 1859 в графе + 1804 тестовых (`tests/`, `test_*`) + 177 файлов внутри `tests/` не `test_*` (в основном `__init__.py`, состав не разбирал) + 8 в `docs/` (`data_schema_module/docs/examples`) + 1 `modules/conftest.py`. Категория «production-код выпал из графа» = 0.
- Каталог без `__init__.py` с файлом в графе: 1 (`multiprocess_framework/modules/data_schema_module/tools/examples`); импортов в него нет, потерь сейчас нет, но см. находку 3.

## D. Правила

- layer-reverse, независимый `rg` по строкам import, без тестов: framework -> Services|Plugins|prototype|backend_ctl 0; Services -> Plugins|prototype 0; Services -> backend_ctl 0; Plugins -> prototype|backend_ctl 0; строковые ссылки `"Services.…"|"Plugins.…"|"multiprocess_prototype.…"` в framework 0 (единственное упоминание — комментарий `multiprocess_framework/__init__.py:112`). Модель: 0. Совпало.
- unit-cycle подтверждён цепочкой (цикл из 3 юнитов, warn «только lazy»):
  `multiprocess_framework/modules/process_module/__init__.py:119` (lazy, в `__getattr__`: `from ..process_manager_module.topology.blueprint import SystemBlueprint`) -> `process_manager_module/topology/blueprint.py:37` (hard: `from ...process_module.plugins.port import Port, …`) -> обратно в `process_module`.
  Второе замыкание: `process_module/configs/managers_config.py:25` (hard: `from ...statistics_module.configs.stats_config import StatsManagerConfig`) -> `statistics_module/observation/observation_manager.py:135` (lazy: `from ...process_module.heartbeat import telemetry`) -> `process_module`.
  Строки проверены `sed` по исходникам.

## E. Детерминизм и сторож

- `python scripts/arch_map/build.py --check` на репозитории: «модель = код», exit 0 (3,7 с).
- Копия `model.json` во временном каталоге (`--out`), удалена одна строка-ребро (`frontend_module.debug.__init__ -> debug.intent_taps`): exit 1, «edges: только на диске 0, только в коде 1». Правка `meta.counts.nodes` 2315 -> 2316: exit 1.
- Тесты через шлюз `bash scripts/machine_gate.sh light arch-map .venv/Scripts/python.exe -m pytest scripts/arch_map/tests -q --tb=short`: 14 passed, 2 warnings in 6.16s, exit 0 (не 75).
- Но `--check` сверяет только `model.json` (находка 2).

## F. Качество тестов

- Ожидаемые значения — литералы (id файлов, номера строк, имена); результат тестируемого кода как ожидание нигде не используется. Тестов, проходящих без проверки, не найдено.
- Break-injection на копии `build.py` во временном каталоге (репозиторий не тронут; `test_real_repo_structural_invariants` отключён: он строит корень от места теста). Контроль без правки: 13 passed. Результат по 12 правкам:

| правка | упали |
|---|---|
| I1 пропуск тел `class` (в том числе методов) | НИКТО |
| I2 `async def` перестал быть lazy | НИКТО |
| I3 каталоги `tests`/`test` считаются прод-кодом | НИКТО |
| I4 tc-рёбра входят в граф циклов | НИКТО |
| I5 fan-in/out считает tc | НИКТО |
| I6 `--check` не сравнивает рёбра | НИКТО |
| I7 `--check` не сравнивает находки | НИКТО |
| I10 `conftest.py` считается прод-кодом | НИКТО |
| I8 убрано распознавание TYPE_CHECKING | test_edge_kinds_hard_lazy_tc, test_layer_reverse_and_deep_and_private_findings |
| I9 уровень относительного импорта у обычного файла смещён | test_relative_import_from_init_and_from_file, test_unresolved_relative_finding, test_all_and_interface_reexport_one_hop |
| I11 правило private-import выключено | test_layer_reverse_and_deep_and_private_findings |
| I12 каталоги `docs` не пропускаются | test_docs_dirs_inside_units_are_skipped |

Три свойства, которые никто не страхует: (1) «импорт внутри метода или тела класса попадает в граф»; (2) «`--check` краснеет, когда разошлись только рёбра»; (3) «тестовые каталоги не попадают в граф». На реальном репозитории правка I1 даёт lazy 794 -> 348 (потеряно 446 рёбер, 56%); `--check` против зафиксированной модели краснеет, но ни один тест репозитория не краснеет.

## Находки

### major

1. [tests] Охранные тесты не покрывают самую частую lazy-форму. Вход: правка «пропускать `ClassDef`» (теряются методы с локальным импортом) -> наблюдаемо: 13/13 тестов зелёные; на реальном репозитории lazy-рёбер 348 вместо 794. То же для async def (I2), tests-каталогов (I3), tc в циклах (I4), tc в fan-метриках (I5), conftest (I10). Исправление: в `test_build.py` фикстуры с импортом в методе класса, в теле класса, в `async def`, в `with`/`for`; каталог `tests/` и `conftest.py` в дереве фикстуры (ожидание: в графе их нет); tc-ребро не создаёт цикла; `fan_in`/`fan_out`/`instability` с литералами.
2. [spec] `--check` не страхует то, что читает вьюер. Вход: в копии `docs/arch-map` `model.js` и `units.md` заменены на `garbage`, `model.json` без правок -> `--check` печатает «модель = код», exit 0. README называет `model.js` источником страницы. Правки только рёбер и только находок тест тоже не ловит (I6, I7). Исправление: `--check` сверяет все четыре файла (`units.md`/`findings.md` побайтно, `model.js` через сравнение с тем текстом, который получился бы без `generated`/`commit`); тесты с правкой одного ребра, одной находки, `model.js`.
3. [spec] Модель молча пропускает класс импортов и файлов; в `meta` и в находках следа нет. Вход (фикстура `scratchpad\fx2`): `Services/svc_a/broken.py` с синтаксической ошибкой -> exit 0, узел с `loc: 0`, рёбер 0, находки нет, только предупреждение в stderr. Вход: `from Services.svc_zzz import X`, `import multiprocess_framework.modules.nope`, `from Services.svc_a.ns import inner` (каталог `ns/` без `__init__.py`, `inner.py` есть в графе), `import Services.svc_a.ns` -> рёбер 0, находок 0, счётчик «4» только в stdout CLI. Правило README «не разрешается в файл графа» заведено только для относительных. Сегодня в репозитории: не разобрано 0, абсолютных без цели 1 (в тест) — ущерба сейчас нет, но свойство «не пропускает молча» не держится. Исправление: находки `unparsed-file` и `unresolved-absolute` (info/warn) либо поля `meta.skipped` и `meta.unresolved_absolute`; разрешать `from pkg.ns import mod` для каталога без `__init__.py`, если `ns/mod.py` в графе.

### minor

4. [quality] Fan-in/instability не видят загрузку по конфигу и не предупреждают об этом (47 из 54, 55 из 59 — раздел B). Известное ограничение, но `units.md` его не называет. Исправление: оговорка в шапке `units.md` и в README с числом (205 строк `plugin_class:`); лучше — ребро вида `cfg` из yaml-рецептов.
5. [quality] README и генератор расходятся: схема в README (строка 58) говорит `"card": {} // запись из cards/*.yaml`, а раздел «Карточка юнита» (строка 101) — «собирается»; в README нет полей `members` (unit-cycle), `synthetic` на узле, id `backend_ctl.__root__`, правила «error, если внутри компоненты есть любой hard-цикл» (README: «для цикла по hard»); строка 124 описывает `_card_drafts/`, которого генератор не читает. Исправление: синхронизировать README с `build.py`.
6. [quality] `if TYPE_CHECKING` внутри функции получает вид lazy. Вход: `def f(): if TYPE_CHECKING: from … import core` (фикстура `typing_in_def.py:4`) -> ребро `lazy`, хотя код не исполняется; завышает runtime-связь и может дать лишний lazy-цикл. Живых случаев в репозитории не подсчитано (см. «Что оставлено открытым»).
7. [quality] В ребре нет признака защиты `try/except ImportError`: необязательная зависимость выглядит как обычный `hard` (пример: `config_module/tools/__init__.py:17`, `from .watcher import ConfigFileWatcher`). Число таких рёбер не подсчитано. Исправление: поле `guarded` в ребре или учёт в `unit-cycle`.
8. [quality] Отчёт автора устарел: «9 тестов» и «960 строк» в основной части против 14 тестов и 1094 строк после Поправки 1.

### advisory (без полного воспроизведения)

- Ребро production -> тестовый файл исключено из графа и из находок (1 случай, `thread_split_probe.py:410`).
- `--check` игнорирует `meta.commit` (отклонение 6 автора) — обосновано, но вместе с находкой 2 значит, что подпись снимка не проверяется вообще.

## Слепые зоны модели в числах

- Динамические импорты: 23 живых вызова (framework 17, Services 3, Plugins 2, prototype 1).
- Загрузка по конфигу: 205 строк `plugin_class:` в 37 рецептах -> 54 юнита; 47 из них с `fan_in == 0`; 55 из 59 `Plugins`-юнитов с `fan_in == 0`.
- Абсолютные импорты в корнях без файла-цели: 1 (в тест), только в stdout CLI.
- Не разобранных файлов: 0 (только stderr).
- Не вошло в граф: 1804 тестовых файла, 177 вспомогательных в `tests/`, 8 примеров в `docs/`, 1 `conftest.py`.
- Неявные рёбра `import a.b.c` в `a/__init__` (отклонение 11 автора) — числом не оценивал.

## Что оставлено открытым / ненадёжно

- Подсчёт рёбер под `try/except ImportError` и импортов TYPE_CHECKING внутри функции по всему репозиторию: два прогона моего скрипта не уложились в лимит времени (причину не выяснял), результата нет; находки 6 и 7 доказаны только на фикстуре.
- 177 вспомогательных файлов в `tests/`: разбивку на `__init__.py` и настоящие модули не делал.
- Моя независимая сверка использует те же семантические допущения, что и генератор (`from pkg import name` ведёт в подмодуль, если он есть; `import a.b.c` — только в целевой файл). Совпадение доказывает отсутствие ошибок обхода и разрешения, не правильность допущений.
- Карточка (`purpose`, `tier`, `summary`, `adr_count`, `commands`, `threads`) проверена только тестами автора на фикстурах; по реальному репозиторию (175 команд, 31 поток) вручную не сверял.
- Break-injection шла на копии без `test_real_repo_structural_invariants`; для I1 его инварианты проверены рассуждением и прогоном на реальном репозитории (структура целая), не самим тестом.
- Раунд 1 из 2.

---

## Раунд 2

VERDICT: APPROVED (остались только minor; блокирующих и major нет)

Проверено запуском, а не чтением заявления автора (Поправка 2 в `2026-11-06_task-arch-map-1-developer.md`). Репозиторий не менялся, коммитов и `git add` нет; временные файлы — в scratchpad.

### 1. Инъекции на копии `build.py` (12 строк раунда 1), прогон через шлюз; контроль C0 без правок: 22 passed, 1 deselected

| инъекция | красных тестов | пример |
|---|---:|---|
| I1 пропуск тел class | 1 | test_imports_in_method_class_body_async_and_loop |
| I2 async def не lazy | 1 | test_imports_in_method_class_body_async_and_loop |
| I3 tests/test считаются кодом | 1 | test_tests_dirs_and_conftest_excluded_but_counted |
| I4 tc-рёбра в графе циклов | 1 | test_tc_edges_do_not_count_in_fan_or_cycles |
| I5 fan-in/out считает tc | 1 | test_tc_edges_do_not_count_in_fan_or_cycles |
| I6 --check не сравнивает рёбра | 1 | test_check_detects_edge_only_and_finding_only_diffs |
| I7 --check не сравнивает находки | 1 | test_check_detects_edge_only_and_finding_only_diffs |
| I10 conftest считается кодом | 1 | test_tests_dirs_and_conftest_excluded_but_counted |
| I8 TYPE_CHECKING не распознан | 4 | test_edge_kinds_hard_lazy_tc |
| I9 уровень относительного импорта смещён | 3 | test_relative_import_from_init_and_from_file |
| I11 private-import выключен | 1 | test_layer_reverse_and_deep_and_private_findings |
| I12 каталоги docs не пропускаются | 1 | test_docs_dirs_inside_units_are_skipped |

Выживших нет. Дополнительно 8 правок по новому коду, все убиты: X1/X2/X3 (--check пропускает model.js / units.md / findings.md) -> test_check_covers_all_four_outputs; X4 (флаг guarded не ставится) -> test_type_checking_in_function_is_tc_and_guarded_flag; X5 (meta.counts.parse_errors = 0) и X6 (находка parse-error убрана) -> test_parse_error_finding_and_counts; X7 (unresolved-absolute убрана) -> test_unresolved_absolute_finding_and_test_target_info; X8 (юнит рецепта не ищется) -> test_recipes_plugin_class_mapped_to_units. Слабое место: одним тестом закрыты пары (I1+I2), (I4+I5), (I6+I7), (X1–X3): красный вызывает любая правка, но какая именно, по имени теста не видно.

### 2. Сторож --check (копии четырёх файлов в каталоге --out)

Репозиторий: «модель = код», exit 0. По одному повреждению: units.md (одна цифра) -> exit 1, «расходятся файлы: units.md»; model.js (kind hard -> lazy) -> exit 1, «model.js»; findings.md («Всего: 1251» -> 1252) -> exit 1, «findings.md»; model.json с удалённой строкой-ребром -> exit 1, «model.json»; model.json с номером строки ребра +1 -> exit 1, «model.json». Находка 2 раунда 1 закрыта.

### 3. Тихие пропуски (фикстура scratchpad\fx3)

Файл с синтаксической ошибкой: находка parse-error (error) на Services/svc_a/broken.py:2, meta.counts.parse_errors == 1. Абсолютные импорты без цели: unresolved-absolute (warn) на ghost.py:1, ghost.py:2 и на from Services.svc_a.ns import inner (useNS.py:1; каталог ns/ без __init__.py по-прежнему не разрешается, но теперь виден), meta.counts.unresolved_absolute == 3. Находка 3 раунда 1 закрыта по видимости; разрешение namespace-каталогов автор не делал и это назвал.

### 4. Рецепты

- Пять юнитов (Plugins.processing.blur, io.robot_io, sources.camera_service, render.render_overlay, control.robot_control): множество yaml-файлов из rg --no-ignore по строке plugin_class для юнита равно spec.recipes из model.json по всем пяти (0 / 4 / 9 / 2 / 1 файл). У camera_service 10 строк в 9 файлах: модель считает файлы, не строки.
- 217 против 205: разница 12 строк в 6 файлах multiprocess_prototype/backend/topology/archive/*.yaml (например phase0_heartbeat.yaml). Мой обычный rg их не видел из-за корневого файла .ignore (правила qex); обход автора через os.walk берёт все 9 отслеживаемых git файлов каталога. rg --no-ignore --hidden даёт ровно 217. Моё число 205 было занижено, прав автор.
- 8 юнитов «ни импортов, ни рецептов»: blur, chain_executor, worker_pool, layer_preview, mjpeg_sink, pult_web, robot_host, scene_source. Три из них используются: Plugins.sim.scene_source.plugin.SceneSourcePlugin (apps/line_sim/pipeline.yaml:80), Plugins.sim.robot_host.plugin.SimRobotHostPlugin (там же :41), Plugins.sim.pult_web.plugin.PultWebPlugin (там же :176). Для chain_executor, blur, worker_pool вне тестов, graphify и копии data/atlas/checkout ссылок на класс нет: настоящие кандидаты. layer_preview и mjpeg_sink не проверял.

### 5. Тело класса: hard или lazy

Скрипт из 3 файлов: host.py с class K: import dep и def m(): import dep2; import host печатает «dep imported» раньше «host: class body done»; после импорта dep in sys.modules: True, dep2 in sys.modules: False. Генератор на том же файле: dep — hard (строка 3), dep2 — lazy (строка 6). Трактовка автора (hard) верна, инструкция лида «lazy» неверна.

### 6. README против model.json (5 точек)

members у unit-cycle: есть, длины 6 и 3 (README стр. 91). synthetic: 17 узлов с true, backend_ctl.__root__ без флага (README 36–38). guarded: 111 рёбер, ключ только со значением true (README 83). spec.recipes: ключ есть у юнитов (README 68). meta.counts: ключи nodes, units, files, edges, findings, parse_errors, unresolved_absolute, ровно как README 48–49. Расхождений нет.

### 7. Шлюз

bash scripts/machine_gate.sh light arch-map .venv/Scripts/python.exe -m pytest scripts/arch_map/tests -q --tb=short: переклассифицирован light -> medium, collected 23, 23 passed, 2 warnings, exit 0 (не 75).

### Остаточные находки

minor:
- R2-1 [quality] Корень поиска рецептов — только multiprocess_prototype. Вход: apps/line_sim/pipeline.yaml (5 строк plugin_class), scripts/capacity_bench/recipes/stand.yaml (6), data/mvs_stand/hikvision_capture.yaml (3) -> модель не видит 14 строк; scene_source, robot_host, pult_web получают «в рецептах» 0 и fan_in 0, хотя запускаются. Шапка раздела Plugins в units.md честно называет «рецептах multiprocess_prototype», но вывод автора «8 кандидатов на не используется» верен для 5 из 8. Исправление: расширить корни до apps/, scripts/**/recipes, data/ либо назвать колонку «в рецептах prototype».
- R2-2 [quality] spec.recipes смешивает живые рецепты с recipes/tests/fixtures/*.yaml (5 файлов) и backend/topology/archive/*.yaml (6 файлов): 11 из 43 различных файлов нежилые. Вход: Plugins.sources.heartbeat -> единственный рецепт archive/phase0_heartbeat.yaml, в колонке «в рецептах» стоит 1. Исправление: пропускать archive и tests либо помечать.

advisory:
- parse-error имеет severity error, но CLI возвращает exit 0 (проверено на fx3); красным становится только --check при расхождении с диском. Для сторожа в CI понадобится ненулевой код.
- 111 рёбер guarded по-прежнему считаются hard в unit-cycle (автор назвал это сам); живых hard-циклов нет, на результат сегодня не влияет.

### Что оставлено открытым / ненадёжно (раунд 2)

- layer_preview и mjpeg_sink из восьми кандидатов не проверял; для chain_executor, blur, worker_pool искал только имя класса, не строки пути в конфигах.
- Инъекции убиваются по одному тесту на правку; насколько узко тесты проверяют, глубже не оценивал.
- Корректность commands, threads и карточки на реальном репозитории вручную не сверял (как и в раунде 1).
- Мой счёт 205 не учитывал корневой .ignore: числа раздела B раунда 1, снятые обычным rg по multiprocess_prototype, занижены (205 -> 217 строк, 37 -> 43 файла, 54 -> 55 юнитов); на вывод о слепоте fan-in это не влияет.
- Раунд 2 из 2; дальше эскалация к teamlead.
