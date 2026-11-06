# Ревью стадии 0: atlas-map A1 «ядро сканера и кэш по блобам»

Ревьюер (Opus, только чтение), `main` = `1dc6c71b7`, 2026-11-06. Текст задачи: `docs/reports/2026-11-06_atlas-map-merge-design.md` §4 A1, опора — §2, §3.
Карта (`scripts/arch_map/build.py`) правится другим агентом: за время ревью в неё добавились `read_doc_headers`, `DOC_HEADER`, `TIERS`,
`names_outside_all`, номера строк сдвинулись. Имена проверены по `grep -n -E '^(class|def) '`, не номера.

VERDICT: CHANGES REQUESTED (итерация 1 из 2)

Слепой тестер по текущему тексту может записать литералом только красный 5 (и то лишь через resolve_relative), остальные 9 — нет; после правок ниже — все 10 плюс 3 добавленных.

Имена функций карты проверены по выводу `grep -n -E` по `class`/`def`, номера строк не использовались.

## a. Ссылки на символы и строки

Совпали: `tree.py:67` (`Tree.read`, процесс git на файл, `:69`); `adapters/code.py:38` (`_read`), `:61` (`_interface_names`); `reference.py:21`,
`rules.py:20` (импорт `_read`); `store.py:49` (`_SCHEMA`), `:50` (`_TABLES`); все девять переносимых функций карты есть по имени
(`collect_imports`, `is_type_checking`, `catches_import_error`, `leaf_name`, `class_style`, `literal_names`, `collect_derived`,
`resolve_relative`, `resolve_import`).

Расхождения:
1. Список переноса неполон. `test_all_plus_equals` требует `read_all`; `collect_derived` вызывает `literal_str`; `test_header_tier_contour_parsed`
   требует `read_doc_headers` (+ `DOC_HEADER`, `TIERS`), `resolve_import` — `import_text`; `collect_imports` — `IMPORT_GUARDS`. Ни одного нет в тексте.
2. `Source` в §3.2 — `files()`, `read_many(paths)`; но кэш по oid (§3.2: «факты кэшируются по oid блоба») без `oids()` у источника не работает.
   В тексте `oids()` есть только у `Tree`; у `DictSource` его нет, `scan(source, …)` не знает, откуда брать oid.
3. `_read` — функция `(root: Path, ref: str, paths, strict=True)` (`code.py:38`), не метод. Текст не говорит ни как она называется в `tree.py`, ни чем
   `Tree.read_many(paths)` отличается от неё (strict или нет).
4. `ImportRec` карты имеет `is_from` (используется в `resolve_import` и `import_text`); в тексте A1 поля `ImportRec(kind, line, level, module, names, guarded)` — без него.
5. `calls` в карте нет вовсе (`ParsedFile`: loc, classes, styles, functions, imports, all_names, doc_line, doc_tier, doc_contour, commands, threads);
   в тексте A1 поле есть, определения нет, ни одно из 10 красных его не трогает.
6. «1867 файлов» — не стабильное число. Набор — не-тестовые `.py` в пяти корнях слоёв; на HEAD проба даёт 1858 (в модели карты 1859 узлов `file`).

## b. Дыры контракта и точный текст для вставки

### R1. Форма фактов (frozen dataclass, контейнеры — tuple, равенство по значению)

Вставить в «Дизайн»:

    ImportRec(kind: "hard"|"lazy"|"tc", line: int, level: int, module: str|None, names: tuple[str,...], is_from: bool, guarded: bool)
    ClassFact(name, bases: tuple[str,...], line: int, methods: tuple[str,...], style: "Protocol"|"ABC"|"class")
    FileFacts(loc: int, doc: str|None, all: tuple[str,...]|None, classes: tuple[ClassFact,...], functions: tuple[str,...],
              imports: tuple[ImportRec,...], commands: tuple[str,...], threads: tuple[tuple[str,int],...],
              tier: str|None, contour: tuple[str,...]|None, error: str|None)

Смысл полей — как в `ParsedFile` карты: `loc` — непустые строки; `doc` — первая непустая строка докстринга модуля; `all` — литеральный `__all__`
(с `+=`), иначе None; `classes[*].methods` — публичные методы без повторов; `functions` — публичные функции верхнего уровня; `commands` — отсортированы;
`threads` — `(имя, строка)` по возрастанию строки, нелитеральное имя — `ast.unparse`. `FileFacts.to_json() -> str` и `FileFacts.from_json(str)`;
`from_json(to_json(f)) == f` для любого `f`. Поле `calls` и сигнатуры/докстринги функций в A1 НЕ заводятся: их потребители — A2/A3 (`scan.py` у A3 в FILES),
смена формы — это смена `SCANNER` (R6), цена ноль. Если лид хочет сигнатуры в A1 — нужна форма `FuncFact(name, sig: str, doc: str|None, line)` и красный на неё.

### R2. Источник, oids, DictSource, результат scan

    class Source(Protocol): files() -> list[str]; oids() -> dict[str, str]; read_many(paths: Sequence[str]) -> dict[str, bytes | None]
    DictSource(files: dict[str, str | bytes])   # oid = git blob sha1: sha1(b"blob %d" % len(data) + b"\0" + data).hexdigest(); str кодируется utf-8
    scan(source, paths: Sequence[str], cache: sqlite3.Connection | None = None) -> ScanResult
    ScanResult(facts: dict[str, FileFacts], missing: tuple[str,...], parsed: int, hits: int)

`facts` — только прочитанные пути, порядок как в `paths`; `missing` — запрошены, но нет в `source.oids()` (в том числе символьные ссылки и gitlink);
`parsed` — число вызовов разбора (различных oid-промахов; два пути с одним oid разбираются один раз); `hits` — различных oid из кэша.
`cache=None` — без кэша, `hits == 0`. Пути — posix, от корня репозитория, без `./`; `DictSource` хранит ключи как есть.
`DictSource.oids()` совпадает с `Tree.oids()` для того же содержимого — это отдельное утверждение в `test_tree_and_dict_source_give_equal_facts`.

### R3. Чтение блобов

    tree.read_blobs(root, ref, paths, strict=True) -> dict[str, bytes|None]   # тело — бывший adapters/code.py:_read, поведение и сигнатура те же
    Tree.read_many(paths) = read_blobs(self.root, self.ref, list(paths), strict=False)   # нет файла -> None, не исключение
    read_blobs([]) и read_many([]) -> {} без запуска git (0 процессов)
    путь с переводом строки -> AtlasError (протокол cat-file построчный: перенос в пути сдвигает все следующие ответы; code.py:40)
    adapters/code.py: from scripts.atlas.tree import read_blobs as _read   # имя _read остаётся: reference.py:21, rules.py:20; вызовы code.py :170/:172/:188 не меняются

Если разработчик перепишет вызовы в `code.py` на `read_blobs`, ruff F401 снесёт импорт `_read`, и `reference.py`/`rules.py` упадут при импорте — запретить:
«в `code.py` вызовы остаются через `_read`». `read_blobs` добавить в `__all__` и `Public API` у `tree.py` (импорт `run_git` в `code.py` станет лишним — ruff уберёт, это нормально).

### R4. Непарсящийся исходник — политика

`scan_text(text: str) -> FileFacts` не бросает никогда. Декодирование байтов — `utf-8` строго; перед `ast.parse` снимается `﻿` в начале.
`UnicodeDecodeError`, `SyntaxError`, `ValueError`, `RecursionError`, `MemoryError` -> `FileFacts(loc=<непустые строки или 0>, error="<ИмяИсключения>")`, прочие поля пусты.
Текст сообщения в `error` не кладётся (там имя файла и строка, ключ находки должен быть стабилен). Такие факты кэшируются как обычные.
Доказательства (пробы): `ast.parse("﻿import os")` -> SyntaxError «invalid non-printable character U+FEFF»; atlas везде снимает BOM (`code.py:128, :175`);
цепочка `x = 1 + 1 + …` из 600 членов: `collect_imports` -> RecursionError, а карта ловит только `(SyntaxError, ValueError, UnicodeDecodeError, OSError)`
(`build_nodes`) — один такой файл убил бы весь скан; `ast.parse` падает с RecursionError уже на 3000 членах. На HEAD: 0 файлов с BOM, CRLF, не-UTF-8.

### R5. Факты зависят только от содержимого блоба (кэш по oid)

`scan_text(text)` без аргументов пути и `is_init`; `all`, `doc`, `tier`, `contour` считаются для каждого файла; `is_init` и имя модуля нужны
только `ImportIndex`. Доказательство: карта вычисляет `all_names`, `doc_line`, `doc_tier/doc_contour` только при `is_init` (`parse_source`); на HEAD
26 групп побайтово одинаковых непустых `.py` по разным путям (проба), пустой блоб `e69de29…` общий у всех пустых файлов. Иначе `__init__.py`,
скопированный в `m.py`, вернёт из кэша факты чужого пути. Добавить красный `test_facts_depend_only_on_content` (см. ниже).

### R6. Ключ кэша scanner, инвалидация, схема таблицы

    SCANNER = "1-" + sha256(Path(__file__).read_bytes()).hexdigest()[:12]   # модульная константа scan.py, считается при импорте
    scan_cache(oid TEXT NOT NULL, scanner TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (oid, scanner))   # body = FileFacts.to_json()

Правка `scan.py` меняет `SCANNER` -> строки старого сканера не читаются. Строки старых сканеров в A1 не удаляются (рост — тела изменённых блобов;
чистка — вместе со сменой `_SCHEMA`). Почему не `code_fingerprint()`: он хеширует весь пакет (`build.py:42-48`), любая правка atlas сбросила бы кэш фактов.
`scan.py` не импортирует `adapters.plans.adapter_version` (ядро не зависит от адаптеров).
API хранилища (`store.py`, рядом с `get_view`/`put_view`): `get_scans(con, scanner, oids) -> dict[str, str]` — запрос порциями по ≤ 500 oid в `IN (...)`;
`put_scans(con, scanner, rows)` — одна транзакция `executemany`, `INSERT OR REPLACE`; `sqlite3.OperationalError` -> строка в stderr и работа продолжается
(как `put_view`, `store.py:181`); тело не разбирается как JSON или форма не та -> промах, строка перезаписывается (как `get_view`, `store.py:164-168`).
Одна транзакция обязательна: на Windows каждый коммит — fsync, 1858 однострочных коммитов съели бы весь бюджет.

### R7. Разрешение импортов (ImportIndex)

    ImportIndex(paths: Iterable[str])                  # индексирует ВСЕ переданные пути *.py; фильтр tests/docs — дело вызывающего
      имя модуля: путь без ".py", "/" -> ".", у __init__.py — имя пакета; каталог без __init__.py модулем не считается (как в карте)
      roots = первые сегменты имён всех модулей индекса    # вместо константы LAYER_ORDER карты (resolve_import: base.split(".")[0] not in LAYER_ORDER)
    ImportIndex.resolve(path: str, rec: ImportRec) -> Resolved
    Resolved(status: "internal"|"external"|"unresolved", targets: tuple[tuple[str, tuple[str,...]], ...])   # ((путь-цель, имена), ...)

Правила (порт `resolve_import` без изменения поведения, но без побочного списка `g.unresolved_abs`; обе ветки `[]` карты — внешняя библиотека и неразрешённый
абсолютный импорт — различаются, B1 нужен `IMPORT_UNRESOLVED`):
- `level > 0`: `base = resolve_relative(level, module, <имя модуля path>, <path — __init__.py>)`; `base` None или нет в индексе -> `unresolved`, `targets == ()`.
- `level == 0`: первый сегмент `module` не в `roots` -> `external`; в `roots`, но модуля нет -> `unresolved`.
- `import a.b.c` (`is_from == False`) -> `((<путь a.b.c>, ()),)`.
- `from pkg import n1, n2`: если `pkg` — пакет (в индексе его `__init__.py`) и есть модуль `pkg.n` — цель это файл `pkg/n.py` (или `pkg/n/__init__.py`) с именем `n`;
  иначе цель — файл `pkg` с именем `n`. Цели сгруппированы по первому появлению, порядок имён сохранён. `from pkg import *` -> имена `("*",)`.
- Самоссылка (цель равна `path`) возвращается как есть; отсев — дело вызывающего (в карте он в `build_edges`).

`resolve_relative(level, module, current, is_init)` переносится с той же сигнатурой. Литералы: `(1, None, "pkg", True) == "pkg"`, `(1, "m", "pkg", True) == "pkg.m"`,
`(1, "m", "pkg.mod", False) == "pkg.m"`, `(1, None, "pkg.mod", False) == "pkg"`, `(2, None, "pkg", True) is None`, `(2, "x", "a.b.c", False) == "a.x"`, `(3, None, "a.b.c", False) is None`.

### R8. Грамматика шапки (header) — в текст, а не ссылкой на docs/arch-map/README.md (он не закоммичен и в B2 удаляется)

Строки ищутся в докстринге модуля (`ast.get_docstring`, очищенном) регулярным выражением `^(Tier|Contour):[ \t]*(.+)$` (MULTILINE), у любого файла.
`Tier` — значение в нижнем регистре, принимается только `core|optional|frozen`, иначе None; побеждает первая допустимая строка.
`Contour` — список через запятую, элементы `strip()`, пустые отброшены, пустой список -> None; первая строка побеждает; словарь значений не проверяется.
Литерал: докстринг "Цель.\n\nTier: Core\nContour: ipc, lifecycle" -> `tier == "core"`, `contour == ("ipc", "lifecycle")`; "Tier: huge" -> `tier is None`.

### R9. Классификация импортов — зафиксировать для красных 2 и 3

`kind`: `hard` — на уровне модуля, в теле класса, в `if/else/with/for/while/match`; `lazy` — внутри `def`/`async def` (в том числе внутри `if` и внутри `if TYPE_CHECKING`);
`tc` — тело `if TYPE_CHECKING:` / `if typing.TYPE_CHECKING:` (ветка `else` сохраняет внешний `kind`; `if not TYPE_CHECKING` не распознаётся). `guarded` — импорт в теле `try`,
чьи обработчики ловят `ImportError`/`ModuleNotFoundError`/`Exception`/`BaseException` или есть голый `except`; обработчики, `else`, `finally` и вложенный `def` — не guarded.

## c. Время: проверяемо ли в сьюте

Нет. Проба (один прогон, нагруженная общая машина, 1858 файлов): `ls-tree` 0,034 с; пакетное чтение `_read` 0,723 с; `ast.parse` 2,141 с (ошибок 0);
`collect_imports` + `collect_derived` 1,56 с. Итого ~4,4 с холодно ДО сигнатур и докстрингов, т.е. граница «≤ 2,6 с» (0,61 + 1,94 = 2,55, только чтение и `ast`)
арифметически недостижима одним процессом и расходится с A2 («справка ≤ 5 с на новом SHA»). Повторов нет, разброс неизвестен.
Прецедент проекта: `test_speed_1_6g.py` («Время не проверяется (его меряет лид на живом дереве)»); метка `slow` в conftest скрывает тесты дольше 60 с.

Заменить строку «Приёмка» на:

«Приёмка. Сьют (литералы, без времени): холодный `scan` дерева из N≥3 файлов запускает ровно 2 процесса git (`ls-tree -r -z`, `cat-file --batch`);
повторный `scan` без изменений — ровно 1 (только `ls-tree`; `cat-file` не запускается, `parsed == 0`); после коммита одного изменённого файла — 2 процесса и `parsed == 1`.
`files()` и `oids()` одного `Tree` делят один `ls-tree -r -z` (вывод `files()` прежний: все записи, включая символьные ссылки и gitlink; `oids()` — только blob с режимом 100644/100755).
Процессы считаются подменой `subprocess.run` в `scripts.atlas.tree` после подготовки фикстуры (фикстура `GitRepo.git` тоже зовёт `subprocess.run`). Скрипт лида (числа в отчёт, не в сьют):
набор — `.py` вне `tests/`, `docs/`, `test_*`, `conftest.py` в пяти корнях слоёв (на HEAD 1858): холодно ≤ 5 с, после коммита одного файла ≤ 1 с.»

Если лид настаивает на 2,6 с — нужен параллельный разбор (`multiprocessing`), в тексте его нет.

## d. Переход _SCHEMA 4 -> 5

Код `store.connect` (`store.py:53-74`): `user_version != _SCHEMA` -> `BEGIN IMMEDIATE`, повторная проверка, `DROP TABLE IF EXISTS` по `_TABLES`, `CREATE ... IF NOT EXISTS` по `_DDL`,
`PRAGMA user_version = 5`, `COMMIT`. Для A1 нужны три правки, а не две: `_SCHEMA = 5` (`:49`), `"scan_cache"` в `_TABLES` (`:50`) и `CREATE TABLE` в `_DDL` (`:30-48`).
Без `_TABLES` будущий сброс оставит старый `scan_cache` (`:64-65` удаляет только перечисленное).
- Существующий `data/atlas.sqlite` (289 МБ): таблицы `builds`...`view_cache` сбрасываются, файл НЕ уменьшается (нет `VACUUM`; в §6 дизайна «сбрасывает 289 МБ» — про содержимое). Время сброса на 289 МБ не измерял (трогать боевую базу нельзя).
- Пир с открытой базой: путь `<toplevel>/data/atlas.sqlite` (`__main__.py:143`) — свой у каждого worktree, поэтому между полосами в worktree гонки нет; она есть только между процессами одного checkout.
  Читатель держит SHARED -> `COMMIT` сброса ждёт EXCLUSIVE, `sqlite3.connect` ждёт 5 с, затем `OperationalError: database is locked` вылетает из `connect` (`:70-72` закрывает и пробрасывает), CLI печатает
  `atlas: internal error`, код 2 (`__main__.py`, `except Exception`). Так же было при 3 -> 4; повтор запуска проходит.
- Процесс СО СТАРЫМ кодом (`_SCHEMA = 4`) против файла v5: `!= _SCHEMA` -> сбрасывает всё обратно в v4 (чужой `scan_cache` остаётся сиротой до ближайшего сброса новым кодом). Пинг-понг возможен, только пока на одном файле работают оба кода; каждый переброс — холодная сборка (~13 с).
- Тесты, пинующие 4: нет (`rg` по `tests`: `test_core_build_key.py:133-150` — версии 0 и 999; `test_cache_1_6e_code.py:102` — 3). `test_cache_1_6e.py:196` суммирует строки всех таблиц — после A1 `scan_cache` пуст, пока `ref`/`card` не вызывают `scan` (это A2).
- `DECISIONS.md`, ADR-ATL-001 `:23`: «≤ 6 таблиц»; станет 7 — нужна строка поправки (см. f).

## e. Перенос _read

`git grep -n -E "\b_read\b" -- scripts/atlas`: определение `code.py:38`; вызовы `code.py:170, :172, :188`, `reference.py:219, :308, :390`, `rules.py:436`; импорты `reference.py:21`, `rules.py:20`.
`metrics.py:53` — другая одноимённая приватная функция `_read(path)`, не затронута. Тесты `_read` не импортируют, `run_git` и `subprocess.run` в `scripts.atlas` не подменяют (`rg` по tests на setattr/monkeypatch — 0). Других импортёров нет.

## f. Список FILES

Добавить: `scripts/atlas/DECISIONS.md` (поправка ADR-ATL-001 `:23` «≤ 6 таблиц» -> 7 и абзац о `scan_cache`/`SCANNER`).
`reference.py` и `rules.py` не правятся, если алиас остаётся в `code.py` (R3) — написать это в тексте. `store.py`: три правки (`_DDL`, `_SCHEMA`, `_TABLES`) + `get_scans`/`put_scans` + `Public API` и `__all__`.
`tree.py`: `Public API`/`__all__` с `read_blobs`. `code_fingerprint()` (`build.py:42-48`) включит новый `scan.py` -> один раз сбросит `view_cache` у каждой полосы (безвредно); `fingerprint()` адаптеров не меняется
(`CodeAdapter.version` хеширует только `s2_gate.py`, `code.py:155`). `tests/conftest.py` менять не надо: `repo`, `repo_factory`, `GitRepo.write/commit/head`, `run_with_deadline` годятся (пример — `test_core_store_tree.py:36-60`).

## g. Конкуренция и повторный вход — тесты автора (не красные тестера)

1. Две нити/два процесса `scan` одного дерева в одну базу: оба успешны, `SELECT count(*) FROM scan_cache` равно числу различных блобов (PK).
2. База занята писателем (`BEGIN EXCLUSIVE` в другом соединении): `scan` возвращает факты, в stderr предупреждение, исключения нет.
3. Битое тело в `scan_cache` (обрезанный JSON, `[1]`): промах, разбор, строка перезаписана.
4. `from_json(to_json(f)) == f` на фактах с пустыми и непустыми кортежами (список против кортежа — тихое расхождение «свежий не равен из кэша»).
5. Путь с пробелом, с кириллицей (на HEAD 15 путей не-ASCII, 1 с пробелом), с переводом строки (R3): пакетное чтение не сдвигает ответы.
6. Цепочка из 600 слагаемых, `﻿`, NUL-байт, не-UTF-8 (R4): `error` заполнен, остальные файлы скана целы.
7. Усечённый вывод `cat-file`: `returncode != 0` -> AtlasError (`code.py:44-45`); усечение при коде 0 `_read` не проверяет (срез `proc.stdout[pos:pos+size]` молча короче) — добавить проверку `len(blob) == size`.
8. Огромный блоб: самый большой `.py` на HEAD — 322 КБ; предела размера нет ни в тексте, ни в карте — решение лида (см. «открыто»).

## Красные: можно ли ожидаемое записать литералом до кода

| № | Красный | Сейчас | После R1-R9 |
|---|---|---|---|
| 1 | `test_tree_and_dict_source_give_equal_facts` | нет: форма фактов и `DictSource` не определены; равенство «пусто = пусто» ничего не доказывает | да; обязательны литеральные якоря (`loc`, первый `ImportRec`) и `DictSource.oids() == Tree.oids()` |
| 2 | `test_import_kinds_hard_lazy_tc` | частично (нет `ImportRec`, правил `lazy`/`tc`) | да (R1, R9) |
| 3 | `test_guarded_relative_import_marked_guarded` | частично | да (R9): `try: from . import x` + `except ImportError` -> True; `except ValueError` -> False; в `def` внутри `try` -> False |
| 4 | `test_from_pkg_import_submodule_targets_submodule` | нет: ни конструктора, ни результата `resolve` | да (R7) |
| 5 | `test_init_level_one_is_package` | да по `resolve_relative` (сигнатура известна из карты); через индекс — нет | да (R7, литералы выше) |
| 6 | `test_commands_and_threads_literals` | нет: формы `commands`/`threads` не заданы | да (R1) |
| 7 | `test_all_plus_equals` | нет: `read_all` не в списке переноса, имя атрибута `all` не закреплено | да (R1): `__all__ = ["a"]` и `__all__ += ["b"]` -> `("a","b")`; `+= other` и `.extend(...)` -> None |
| 8 | `test_header_tier_contour_parsed` | нет: грамматики нет в тексте | да (R8) |
| 9 | `test_one_git_process_per_scan` | нет: «один процесс» противоречит двум (`ls-tree` + `cat-file`); способ подсчёта не задан | да (п. c) |
| 10 | `test_blob_cache_reparses_only_changed_oids` | нет: наблюдаемого счётчика разборов нет | да (R2, R6): 3 файла холодно `parsed == 3`, строк 3; правка одного + коммит -> `parsed == 1`, `hits == 2`, строк 4; `git mv` без правки -> `parsed == 0` |

## Добавить к красным (13 вместо 10)

11. `test_facts_depend_only_on_content` — один текст по путям `pkg/__init__.py` и `pkg/m.py`: равные факты, в `scan_cache` одна строка (R5).
12. `test_scanner_change_is_full_miss` — после `monkeypatch.setattr(scan, "SCANNER", "x")` повторный скан: `parsed == N`, `hits == 0`, строк 2N (R6).
13. `test_unparsable_source_gives_error_facts` — `def (` -> `error == "SyntaxError"`; байты `ff fe` -> `"UnicodeDecodeError"`; `"﻿import os"` -> `error is None`, один импорт; цепочка из 600 слагаемых -> `"RecursionError"`;
    соседний файл скана цел (R4). На него опираются A2 `test_unparsable_file_still_usage_unknown` и B1 `SOURCE_UNPARSED`.

## Что оставлено открытым / ненадёжно

- Время: все цифры — одна проба на нагруженной общей машине, без повторов. Время сброса базы 289 МБ не измерял. Разбор с сигнатурами и докстрингами не мерил (в пробе их нет) — реальный холодный скан может быть выше 4,4 с.
- Предел размера блоба (пропускать `.py` больше N байт?) — решение лида; без него гигантский сгенерированный файл съест память и время.
- Каталог без `__init__.py` не модуль (порт карты): `from ns import x` в пространстве имён Python даст `unresolved`. Сколько таких случаев в 1858 файлах — не считал; для B1 это возможный шум `IMPORT_UNRESOLVED`.
- `roots` из индекса вместо `LAYER_ORDER` меняет поведение против карты: каталог верхнего уровня, совпавший с именем сторонней библиотеки, станет `unresolved`, а не `external`. Решение лида; для A1 безопасно, для B1 — проверить.
- Равенство результатов `ImportIndex` и `resolve_import` карты на HEAD не проверял (карта правится прямо сейчас). Разработчику: разовая сверка рёбер на HEAD, число в отчёт; в сьют не идёт.
- `SCANNER` на хеше файла: правка комментария в `scan.py` сбрасывает кэш фактов. Принято (цена — один холодный скан), но рост `scan_cache` без очистки не оценён.
- Пробы лежат в scratchpad (`probe_perf.py`, `probe_haz.py`, `probe_bom.py`), не в репозитории; других файлов в дереве я не создавал.
