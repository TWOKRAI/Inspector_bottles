> Расположение файла предварительное: план и фаза для задач слияния карты с атласом решаются позже (файл переедет без правки текста).

### Task map-A1 — ядро сканера и кэш по блобам

- **Статус:** [PENDING]. Стадия 0: раунд 2 CHANGES REQUESTED (только текст), правки внесены лидом без третьего раунда, 2026-11-06.
- **Level:** Senior+ · **Assignee:** `teamlead` (либо `developer` по этому DESIGN дословно) · **Layer:** tooling (`scripts/atlas`, ядро framework не трогается)
- **CHAIN:** `reviewer` (стадия 0 закрыта лидом после раунда 2) → `tester` (слепой, RED из раздела «Красные») → `teamlead` (GREEN + тесты автора) → лид (замер времени, инъекции) → `reviewer`
- **Источники:** проект слияния `docs/reports/2026-11-06_atlas-map-merge-design.md` §3, §4 A1; отчёт стадии 0 `docs/reviews/2026-11-06_task-atlas-map-A1-stage0.md` (R1–R9, §c–§g), раунд 2 — `docs/reviews/2026-11-06_task-atlas-map-A1-stage0-r2.md`. Решения лида D1–D5 ниже окончательны.
- **Зависит от:** ничего. **Даёт:** A2 (код в памяти), A3 (справка), B1 (адаптер `imports`).

## Цель

Один сканер `scripts/atlas/scan.py` читает код ревизии git и фикстуру в памяти одним кодом, отдаёт неизменяемые факты о файлах, а факты кэшируются в sqlite по oid блоба, так что новый SHA разбирает только изменённые файлы.

## Дизайн

### Что переносится из карты

Источник порта — `scripts/arch_map/build.py` в ГЛАВНОМ дереве (`D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles`). Файл не закоммичен (untracked) и правится другим агентом: имена проверены по `grep -n -E '^(class|def) '`, номера строк нестабильны, брать по имени. В `scan.py` переносятся:

- функции: `collect_imports`, `is_type_checking`, `catches_import_error`, `leaf_name`, `class_style`, `literal_names`, `collect_derived`, `resolve_relative`, `resolve_import`, `read_all`, `literal_str`, `read_doc_headers`;
- константы: `IMPORT_GUARDS`, `DOC_HEADER`, `TIERS`.

Не переносятся: `LAYER_ORDER`, `Graph`, `g.unresolved_abs`, `import_text` (вернётся в B1 вместе с `IMPORT_UNRESOLVED`; его единственный потребитель — `g.unresolved_abs`), `calls`, сигнатуры и докстринги функций. Поведение `class_style`, `collect_derived`, `read_all` сохраняется; отступления только те, что названы ниже (R1 `methods` по D5, R7 `roots`, R9).

### D1–D5, решения лида

- **D1. Предел размера блоба.** Константа `MAX_BLOB_BYTES = 1_048_576` в `scan.py` (1 МиБ, около 3 раз больше крупнейшего `.py` на HEAD, 322 КБ). Блоб длиннее предела не декодируется и не разбирается: `FileFacts(loc=0, error="BlobTooLarge")`, остальные поля пусты; факты кэшируются как любые другие. Проверка идёт по длине байт ДО декодирования, в той функции `scan`, что превращает байты в факты (имя на усмотрение разработчика; тестер идёт через `scan(DictSource, …)`).
- **D2. Каталог без `__init__.py`.** Поведение карты сохраняется: модулем не считается, `from ns import x` даёт `unresolved`. Разовый подсчёт на HEAD — см. «Разовые сверки». Шум это или нет, решается в B1.
- **D3. `roots` из индекса вместо `LAYER_ORDER`.** Принято: атлас должен работать на любом репозитории, `LAYER_ORDER` — константа проекта. Разовые проверки — см. «Разовые сверки».
- **D4. Сигнатуры, докстринги, `calls` — не в A1** (R1 как написано). Приходят в A3 вместе со сменой `SCANNER`.
- **D5. Дефект K0: карта теряет dunder-члены** (у Protocol `IConfigObserver.__call__` вышло `methods: []`). В A1 `ClassFact.methods` — имена `def`/`async def`, стоящих прямо в теле класса, без имён с `_` в начале, кроме dunder (`__x__`); порядок исходника, первое вхождение, без повторов. Вид, которому dunder не нужны, отфильтрует их сам (A2).

### R1. Форма фактов

Frozen dataclass, контейнеры — tuple, равенство по значению.

    ImportRec(kind: "hard"|"lazy"|"tc", line: int, level: int, module: str|None, names: tuple[str,...], is_from: bool, guarded: bool)
    ClassFact(name, bases: tuple[str,...], line: int, methods: tuple[str,...], style: "Protocol"|"ABC"|"class")
    FileFacts(loc: int, doc: str|None, all: tuple[str,...]|None, classes: tuple[ClassFact,...], functions: tuple[str,...],
              imports: tuple[ImportRec,...], commands: tuple[str,...], threads: tuple[tuple[str,int],...],
              tier: str|None, contour: tuple[str,...]|None, error: str|None)

Значения по умолчанию у `FileFacts` (решение лида): `loc=0`, `doc=None`, `all=None`, `tier=None`, `contour=None`, `error=None`, остальные поля — пустой tuple `()`. «Прочие поля пусты» в R4 и D1 означает именно их; `FileFacts(loc=1, error="SyntaxError")` строится без остальных аргументов.

Смысл полей — как в `ParsedFile` карты: `loc` — непустые строки; `doc` — первая непустая строка докстринга модуля; `all` — литеральный `__all__` (с `+=`), иначе None; `classes[*].methods` — по D5: имена `def`/`async def` прямо в теле класса, без имён с `_` в начале, кроме dunder (`__x__`), без повторов; `functions` — публичные функции верхнего уровня; `commands` — отсортированы; `threads` — `(имя, строка)` по возрастанию строки, нелитеральное имя — `ast.unparse`. `error` — имя исключения (R4) или `"BlobTooLarge"` (D1). `FileFacts.to_json() -> str` и `FileFacts.from_json(str)`; `from_json(to_json(f)) == f` для любого `f` (вложенные `ImportRec` и `ClassFact` восстанавливаются, кортежи остаются кортежами).

Поле `calls`, сигнатуры и докстринги функций в A1 НЕ заводятся (D4): смена формы — это смена `SCANNER` (R6), цена ноль. Поле `header` одним значением тоже нет: шапка — `tier` + `contour` (R8).

### R2. Источник, oids, DictSource, результат scan

    class Source(Protocol): files() -> list[str]; oids() -> dict[str, str]; read_many(paths: Sequence[str]) -> dict[str, bytes | None]
    DictSource(files: dict[str, str | bytes])   # oid = git blob sha1: sha1(b"blob %d" % len(data) + b"\0" + data).hexdigest(); str кодируется utf-8
    scan(source, paths: Sequence[str], cache: sqlite3.Connection | None = None) -> ScanResult
    ScanResult(facts: dict[str, FileFacts], missing: tuple[str,...], parsed: int, hits: int)

`facts` — только прочитанные пути, порядок как в `paths`; `missing` — запрошены, но нет в `source.oids()` (в том числе символьные ссылки и gitlink); `parsed` — число вызовов разбора (различных oid-промахов; два пути с одним oid разбираются один раз; факты с `error`, включая `BlobTooLarge`, считаются как обычные); `hits` — различных oid из кэша. `cache=None` — без кэша, `hits == 0`. Пути — posix, от корня репозитория, без `./`; `DictSource` хранит ключи как есть. `DictSource.oids()` совпадает с `Tree.oids()` для того же содержимого. Пути, содержащие `\n`, `scan` кладёт в `missing` и не передаёт в `read_many`; `read_blobs`/`read_many` по-прежнему бросают `AtlasError` (R3). `scan` читает модульную константу `SCANNER` в момент вызова (не копию в аргументе по умолчанию): красный 12 подменяет её через `monkeypatch.setattr`.

### R3. Чтение блобов

    tree.read_blobs(root, ref, paths, strict=True) -> dict[str, bytes|None]   # тело — бывший adapters/code.py:_read, поведение и сигнатура те же, кроме двух добавлений: перевод строки в пути -> `AtlasError`; несовпадение `len(blob) == size` -> `AtlasError` (strict и не-strict; тест автора 7)
    Tree.read_many(paths) = read_blobs(self.root, self.ref, list(paths), strict=False)   # нет файла -> None, не исключение
    Tree.oids() -> dict[str, str]            # из того же `ls-tree -r -z`, что и files(); только blob с режимом 100644/100755
    read_blobs([]) и read_many([]) -> {} без запуска git (0 процессов)
    путь с переводом строки -> AtlasError (протокол cat-file построчный: перенос в пути сдвигает все следующие ответы; code.py:40)
    adapters/code.py: from scripts.atlas.tree import read_blobs as _read   # имя _read остаётся: reference.py:21, rules.py:20; вызовы code.py :170/:172/:188 не меняются

Запрет: «в `code.py` вызовы остаются через `_read`». Если переписать вызовы на `read_blobs`, ruff F401 снесёт импорт `_read`, и `reference.py`/`rules.py` упадут при импорте. `read_blobs` — в `__all__` и `Public API` у `tree.py`; импорт `run_git` в `code.py` станет лишним, ruff его уберёт, это нормально. `files()` и `oids()` одного `Tree` делят один `ls-tree -r -z`; вывод `files()` прежний: все записи, включая символьные ссылки и gitlink.

### R4. Непарсящийся исходник — политика

`scan_text(text: str) -> FileFacts` не бросает никогда. Декодирование байтов — `utf-8` строго; перед `ast.parse` снимается `"\ufeff"` в начале. Перед декодированием длина байт сверяется с `MAX_BLOB_BYTES` (D1): длиннее — `FileFacts(loc=0, error="BlobTooLarge")`, декодирования и разбора нет. `UnicodeDecodeError`, `SyntaxError`, `ValueError`, `RecursionError`, `MemoryError` -> `FileFacts(loc=<непустые строки или 0>, error="<ИмяИсключения>")`, прочие поля пусты. На Python 3.12 NUL-байт в исходнике даёт `SyntaxError`; имя ошибки в красных не утверждается. Текст сообщения в `error` не кладётся (там имя файла и строка, ключ находки должен быть стабилен). Такие факты кэшируются как обычные.

Доказательства (пробы): `ast.parse("\ufeffimport os")` -> SyntaxError «invalid non-printable character U+FEFF»; atlas везде снимает BOM (`code.py:128, :175`); цепочка `x = 1 + 1 + …` из 600 членов: `collect_imports` -> RecursionError, а карта ловит только `(SyntaxError, ValueError, UnicodeDecodeError, OSError)` (`build_nodes`) — один такой файл убил бы весь скан; `ast.parse` падает с RecursionError уже на 3000 членах (проверено при составлении задачи на Python 3.12.12). На HEAD: 0 файлов с BOM, CRLF, не-UTF-8.

### R5. Факты зависят только от содержимого блоба (кэш по oid)

`scan_text(text)` без аргументов пути и `is_init`; `all`, `doc`, `tier`, `contour` считаются для каждого файла; `is_init` и имя модуля нужны только `ImportIndex`. Доказательство: карта вычисляет `all_names`, `doc_line`, `doc_tier/doc_contour` только при `is_init` (`parse_source`); на HEAD 26 групп побайтово одинаковых непустых `.py` по разным путям (проба), пустой блоб `e69de29…` общий у всех пустых файлов. Иначе `__init__.py`, скопированный в `m.py`, вернёт из кэша факты чужого пути.

### R6. Ключ кэша scanner, инвалидация, схема таблицы

    SCANNER = "1-" + sha256(Path(__file__).read_bytes()).hexdigest()[:12]   # модульная константа scan.py, считается при импорте
    scan_cache(oid TEXT NOT NULL, scanner TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (oid, scanner))   # body = FileFacts.to_json()

Правка `scan.py` меняет `SCANNER` -> строки старого сканера не читаются. Строки старых сканеров в A1 не удаляются (рост — тела изменённых блобов; чистка — вместе со сменой `_SCHEMA`). Почему не `code_fingerprint()`: он хеширует весь пакет (`build.py:42-48`), любая правка atlas сбросила бы кэш фактов. `scan.py` не импортирует `adapters.plans.adapter_version` (ядро не зависит от адаптеров).

API хранилища (`store.py`, рядом с `get_view`/`put_view`): `get_scans(con, scanner, oids) -> dict[str, str]` — запрос порциями по ≤ 500 oid в `IN (...)`; `put_scans(con, scanner, rows)` — `rows: Iterable[tuple[str, str]]` — пары `(oid, body)`; одна транзакция `executemany`, `INSERT OR REPLACE` (обработка `OperationalError` — как `put_view`, `store.py:181`). `get_scans` возвращает тела как есть и форму не проверяет: красный 10 кладёт тела `"[1]"`, `"{}"`, `"new"` и ждёт их обратно. Проверка формы — в `scan`: тело, которое `FileFacts.from_json` не разобрал (любое исключение), — промах: блоб разбирается заново, строка перезаписывается `put_scans`. `get_scans` при `sqlite3.OperationalError` пишет строку в stderr и возвращает `{}` (все промахи), `scan` продолжает без кэша. `put_scans` при `OperationalError` — строка в stderr, работа продолжается. Одна транзакция обязательна: на Windows каждый коммит — fsync, 1858 однострочных коммитов съели бы весь бюджет.

### R7. Разрешение импортов (ImportIndex)

    ImportIndex(paths: Iterable[str])                  # индексирует ВСЕ переданные пути *.py; фильтр tests/docs — дело вызывающего
      имя модуля: путь без ".py", "/" -> ".", у __init__.py — имя пакета; каталог без __init__.py модулем не считается (как в карте; D2)
      roots = первые сегменты имён всех модулей индекса    # вместо константы LAYER_ORDER карты (D3)
    ImportIndex.resolve(path: str, rec: ImportRec) -> Resolved
    Resolved(status: "internal"|"external"|"unresolved", targets: tuple[tuple[str, tuple[str,...]], ...])   # ((путь-цель, имена), ...)

Правила (порт `resolve_import` без изменения поведения, но без побочного списка `g.unresolved_abs`; обе ветки `[]` карты — внешняя библиотека и неразрешённый абсолютный импорт — различаются, B1 нужен `IMPORT_UNRESOLVED`):
- `level > 0`: `base = resolve_relative(level, module, <имя модуля path>, <path — __init__.py>)`; `base` None или нет в индексе -> `unresolved`, `targets == ()`.
- `level == 0`: первый сегмент `module` не в `roots` -> `external`; в `roots`, но модуля нет -> `unresolved`. У `external` и `unresolved` `targets == ()` (решение лида).
- `import a.b.c` (`is_from == False`) -> `((<путь a.b.c>, ()),)`.
- `from pkg import n1, n2`: если `pkg` — пакет (в индексе его `__init__.py`) и есть модуль `pkg.n` — цель это файл `pkg/n.py` (или `pkg/n/__init__.py`) с именем `n`; иначе цель — файл `pkg` с именем `n`. Цели сгруппированы по первому появлению, порядок имён сохранён. `from pkg import *` -> имена `("*",)`.
- Самоссылка (цель равна `path`) возвращается как есть; отсев — дело вызывающего (в карте он в `build_edges`).
- `path` вне индекса при `level > 0` -> `Resolved("unresolved", ())`, не `KeyError` (решение лида).
- `ImportIndex.roots` — публичный атрибут `frozenset[str]`; пути без суффикса `.py` индекс пропускает.

`resolve_relative(level, module, current, is_init)` переносится с той же сигнатурой. Литералы: `(1, None, "pkg", True) == "pkg"`, `(1, "m", "pkg", True) == "pkg.m"`, `(1, "m", "pkg.mod", False) == "pkg.m"`, `(1, None, "pkg.mod", False) == "pkg"`, `(2, None, "pkg", True) is None`, `(2, "x", "a.b.c", False) == "a.x"`, `(3, None, "a.b.c", False) is None`.

### R8. Грамматика шапки

В тексте, а не ссылкой на `docs/arch-map/README.md` (он не закоммичен и в B2 удаляется). Строки ищутся в докстринге модуля (`ast.get_docstring`, очищенном) регулярным выражением `^(Tier|Contour):[ \t]*(.+)$` (MULTILINE), у любого файла. `Tier` — значение в нижнем регистре, принимается только `core|optional|frozen`, иначе None; побеждает первая допустимая строка. `Contour` — список через запятую, элементы `strip()`, пустые отброшены, пустой список -> None; первая строка побеждает; словарь значений не проверяется. Литерал: докстринг "Цель.\n\nTier: Core\nContour: ipc, lifecycle" -> `tier == "core"`, `contour == ("ipc", "lifecycle")`; "Tier: huge" -> `tier is None`.

### R9. Классификация импортов

`kind`: `tc` — если среди охватывающих узлов есть тело `if TYPE_CHECKING:` / `if typing.TYPE_CHECKING:` (на любой глубине, в том числе внутри `def`); иначе `lazy` — внутри `def`/`async def` (в том числе внутри `if`); иначе `hard` — на уровне модуля, в теле класса, в `if/else/with/for/while/match`. Ветка `else` у `if TYPE_CHECKING` сохраняет внешний `kind`; `if not TYPE_CHECKING` не распознаётся. Первое уточнение (решение лида 2026-11-06): импорт под `if TYPE_CHECKING` внутри `def` — `tc`, не `lazy`, как в первоначальном тексте R9 (ветка не выполняется, это не зависимость времени исполнения). Карта уже даёт здесь `tc` (проверено: `("a","tc",4)`), отступления от карты нет. Единственное отступление от карты (решение лида 2026-11-06): импорт в `def`, стоящем в теле `if TYPE_CHECKING`, — `tc` (функции в рантайме нет; правило «на любой глубине» действует); карта даёт `lazy` (проверено: `("b","lazy",4)`), потому что `def` сбрасывает `kind`. `guarded` — импорт в теле `try`, чьи обработчики ловят `ImportError`/`ModuleNotFoundError`/`Exception`/`BaseException` или есть голый `except`; обработчики, `else`, `finally` и вложенный `def` — не guarded.

### §d. Переход `_SCHEMA` 4 -> 5

`store.connect` (`store.py:53-74`): `user_version != _SCHEMA` -> `BEGIN IMMEDIATE`, повторная проверка, `DROP TABLE IF EXISTS` по `_TABLES`, `CREATE ... IF NOT EXISTS` по `_DDL`, `PRAGMA user_version = 5`, `COMMIT`. Нужны три правки, а не две: `_SCHEMA = 5` (`:49`), `"scan_cache"` в `_TABLES` (`:50`) и `CREATE TABLE` в `_DDL` (`:30-48`). Без `_TABLES` будущий сброс оставит старый `scan_cache` (`:64-65` удаляет только перечисленное).

- Существующий `data/atlas.sqlite` (289 МБ): таблицы `builds`…`view_cache` сбрасываются, файл НЕ уменьшается (нет `VACUUM`; «сбрасывает 289 МБ» в §6 проекта — про содержимое). Время сброса на 289 МБ не измерялось (боевую базу трогать нельзя).
- Пир с открытой базой: путь `<toplevel>/data/atlas.sqlite` (`__main__.py:143`) свой у каждого worktree, поэтому между полосами в worktree гонки нет; она есть только между процессами одного checkout. Читатель держит SHARED, `COMMIT` сброса ждёт EXCLUSIVE, `sqlite3.connect` ждёт 5 с, затем `OperationalError: database is locked` вылетает из `connect` (`:70-72` закрывает и пробрасывает), CLI печатает `atlas: internal error`, код 2 (`__main__.py`, `except Exception`). Так же было при 3 -> 4; повтор запуска проходит.
- Процесс СО СТАРЫМ кодом (`_SCHEMA = 4`) против файла v5: `!= _SCHEMA` -> сбрасывает всё обратно в v4 (чужой `scan_cache` остаётся сиротой до ближайшего сброса новым кодом). Пинг-понг возможен, только пока на одном файле работают оба кода; каждый переброс — холодная сборка (около 13 с).
- Тесты, пинующие 4: нет (`test_core_build_key.py:133-150` — версии 0 и 999; `test_cache_1_6e_code.py:102` — 3). `test_cache_1_6e.py:196` суммирует строки всех таблиц: после A1 `scan_cache` пуст, пока `ref`/`card` не вызывают `scan` (это A2).
- `DECISIONS.md`, ADR-ATL-001 `:23`: «≤ 6 таблиц» -> 7.

### §e. Перенос `_read`

`git grep -n -E "\b_read\b" -- scripts/atlas`: определение `code.py:38`; вызовы `code.py:170, :172, :188`, `reference.py:219, :308, :390`, `rules.py:436`; импорты `reference.py:21`, `rules.py:20`. `metrics.py:53` — другая одноимённая приватная функция `_read(path)`, не затронута. Тесты `_read` не импортируют, `run_git` и `subprocess.run` в `scripts.atlas` не подменяют (`rg` по tests на setattr/monkeypatch — 0). Других импортёров нет.

## Файлы (FILES; другой файл — стоп и вопрос лиду)

- `scripts/atlas/scan.py` (новый): `Source`, `DictSource`, `FileFacts`, `ClassFact`, `ImportRec`, `ScanResult`, `Resolved`, `ImportIndex`, `scan_text`, `scan`, `resolve_relative`, `SCANNER`, `MAX_BLOB_BYTES`, перенесённое из карты. Module header по правилам проекта (`Purpose`, `Public API`, `Stability`) и `__all__`.
- `scripts/atlas/tree.py`: `read_blobs` (тело бывшего `_read`; добавить проверку `len(blob) == size`, см. тест автора 7), `Tree.oids()`, `Tree.read_many()`, общий `ls-tree -r -z` для `files()` и `oids()`; `Public API` и `__all__`.
- `scripts/atlas/store.py`: `_DDL` (таблица `scan_cache`), `_SCHEMA = 5`, `_TABLES`, `get_scans`/`put_scans`; `Public API` и `__all__`.
- `scripts/atlas/adapters/code.py`: только `from scripts.atlas.tree import read_blobs as _read`; вызовы остаются через `_read`; определение `_read` и лишний `run_git` уходят.
- `scripts/atlas/DECISIONS.md`: ADR-ATL-001 `:23` «≤ 6 таблиц» -> 7 с поправкой; абзац о `scan_cache` и `SCANNER`.
- `scripts/atlas/tests/test_scan.py` (новый): красные тестера и тесты автора.

НЕ правятся: `scripts/atlas/reference.py`, `scripts/atlas/rules.py`, `scripts/atlas/tests/conftest.py` (фикстуры `repo`, `repo_factory`, `GitRepo.write/commit/head`, `run_with_deadline` годятся, пример — `test_core_store_tree.py:36-60`). Побочное: `code_fingerprint()` (`build.py:42-48`) включит новый `scan.py` и один раз сбросит `view_cache` у каждой полосы (безвредно); `fingerprint()` адаптеров не меняется (`CodeAdapter.version` хеширует только `s2_gate.py`, `code.py:155`).

## Красные (`scripts/atlas/tests/test_scan.py::`, 14 штук, слепой тестер)

Общее. Git-фикстура — `repo` из `conftest.py`; файлы кладутся через `repo.write`, `Tree(repo.path, "HEAD")`. База кэша — `store.connect(tmp_path / "atlas.sqlite")`; число строк кэша — `con.execute("SELECT count(*) FROM scan_cache").fetchone()[0]`. `ImportRec` и `FileFacts` строятся по ключам. Все значения ниже — литералы.

Импорты теста: `import scripts.atlas.scan as scan_mod` (модуль: `scan_mod.SCANNER`, `MAX_BLOB_BYTES`, `__file__`; `monkeypatch.setattr(scan_mod, "SCANNER", "x")`) и `from scripts.atlas.scan import scan, scan_text, DictSource, FileFacts, ImportRec, ImportIndex, Resolved, resolve_relative`. В красных 12 и 13 запись `scan.X` — это `scan_mod.X`, `scan(...)` — функция. Файлы пишутся `repo.write` (как `test_core_store_tree.py:36-60`); литерал `96766802…` верен при `core.autocrlf=true` — проверено: рабочий файл CRLF, блоб LF.

**1. `test_tree_and_dict_source_give_equal_facts`.** Три файла и в git (один коммит), и в `DictSource`:
- `pkg/__init__.py` = `'"""Pkg doc."""\n__all__ = ["run"]\n'`
- `pkg/m.py` = `"import os\nfrom . import n\n\n\ndef run():\n    pass\n"`
- `pkg/n.py` = `"X = 1\n"`

Ожидается для `paths = ["pkg/n.py", "pkg/__init__.py", "pkg/m.py"]`: `scan(tree, paths).facts == scan(dict_source, paths).facts`; `list(facts) == paths`. Литеральные якоря:
- `pkg/__init__.py`: `loc == 2`, `doc == "Pkg doc."`, `all == ("run",)`, `imports == ()`, `classes == ()`, `error is None`.
- `pkg/m.py`: `loc == 4`, `functions == ("run",)`, `doc is None`, `all is None`, `imports == (ImportRec(kind="hard", line=1, level=0, module="os", names=(), is_from=False, guarded=False), ImportRec(kind="hard", line=2, level=1, module=None, names=("n",), is_from=True, guarded=False))`.
- `pkg/n.py`: `loc == 1`.
- `DictSource({...}).oids() == Tree(repo.path, "HEAD").oids()` (те же три ключа); `DictSource({"n.py": "X = 1\n"}).oids()["n.py"] == "96766802bd555f14ace322a7f376c4551f1bf5b7"`; `DictSource({"e.py": ""}).oids()["e.py"] == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"`.
- `scan(tree, ["pkg/n.py", "ghost.py"])`: `missing == ("ghost.py",)`, `list(facts) == ["pkg/n.py"]`.
- `FileFacts.from_json(f.to_json()) == f` для всех трёх фактов.

**2. `test_import_kinds_hard_lazy_tc`.** Источник A, `scan_text`:

    import a
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        import b
    else:
        import c
    class K:
        import d
    def f():
        import e
        if True:
            import g
    async def h():
        import i
    if True:
        import j

Ожидается `[(module, kind, line)]`: `("a","hard",1)`, `("typing","hard",2)`, `("b","tc",4)`, `("c","hard",6)`, `("d","hard",8)`, `("e","lazy",10)`, `("g","lazy",12)`, `("i","lazy",14)`, `("j","hard",16)`. У записи `typing`: `names == ("TYPE_CHECKING",)`, `is_from is True`, `level == 0`; у записи `a`: `names == ()`, `is_from is False`.
Дополнительные источники: `"from typing import TYPE_CHECKING\ndef f():\n    if TYPE_CHECKING:\n        import a\n"` -> две записи `[("typing","hard",1), ("a","tc",4)]` (решение лида, R9; правка лида 2026-11-06: строка 1 — тоже импорт); `"from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    def g():\n        import b\n"` -> две записи `[("typing","hard",1), ("b","tc",4)]` (решение лида, R9); `"import typing\nif typing.TYPE_CHECKING:\n    import k\n"` -> `[("typing","hard",1), ("k","tc",3)]`; `"from typing import TYPE_CHECKING\nif not TYPE_CHECKING:\n    import m\n"` -> запись `m`: `kind == "hard"`, `line == 3`; `"import q\nimport r.s as t, u\n"` -> три записи: `("q",1)`, `("r.s",2)`, `("u",2)`, все `hard`, `names == ()`.

**3. `test_guarded_relative_import_marked_guarded`.** Источники, `scan_text`, всегда одна запись, если не сказано иное:
- `"try:\n    from . import x\nexcept ImportError:\n    x = None\n"` -> `guarded is True`, `level == 1`, `module is None`, `names == ("x",)`, `kind == "hard"`, `line == 2`.
- то же с `except ValueError:` -> `guarded is False`.
- `"try:\n    def f():\n        from . import x\nexcept ImportError:\n    pass\n"` -> `kind == "lazy"`, `guarded is False`.
- `"try:\n    import q\nexcept (KeyError, ModuleNotFoundError):\n    pass\n"` -> `guarded is True`; то же с `except:` (голый) -> `True`; с `except Exception:` -> `True`; с `except BaseException:` -> `True`.
- `"try:\n    pass\nexcept ImportError:\n    import y\nelse:\n    import z\nfinally:\n    import w\n"` -> три записи (`y` строка 4, `z` строка 6, `w` строка 8), у всех `guarded is False`, `kind == "hard"`.

**4. `test_from_pkg_import_submodule_targets_submodule`.** `idx = ImportIndex(["pkg/__init__.py", "pkg/sub.py", "pkg/mod.py", "pkg/inner/__init__.py", "other.py"])` (`idx.roots == frozenset({"pkg", "other"})`); `resolve("other.py", rec)`, `rec` — `ImportRec(kind="hard", line=1, level=0, ..., is_from=...)`:
- `from pkg import sub, helper` (`module="pkg"`, `names=("sub","helper")`) -> `Resolved(status="internal", targets=(("pkg/sub.py", ("sub",)), ("pkg/__init__.py", ("helper",))))`.
- `from pkg import helper, sub` -> `targets == (("pkg/__init__.py", ("helper",)), ("pkg/sub.py", ("sub",)))`.
- `from pkg import helper, missing` -> `targets == (("pkg/__init__.py", ("helper", "missing")),)`.
- `from pkg import inner` -> `targets == (("pkg/inner/__init__.py", ("inner",)),)`.
- `from pkg import *` (`names=("*",)`) -> `targets == (("pkg/__init__.py", ("*",)),)`.
- `import pkg.sub` (`module="pkg.sub"`, `names=()`, `is_from=False`) -> `status == "internal"`, `targets == (("pkg/sub.py", ()),)`; `import other` -> `targets == (("other.py", ()),)`.
- `import os` -> `status == "external"`, `targets == ()`; `from os import path` -> `external`.
- `import pkg.nope` -> `status == "unresolved"`, `targets == ()`; `from pkg.nope import x` -> `unresolved`.
- D2: `idx2 = ImportIndex(["ns/a.py", "other.py"])` (каталог `ns` без `__init__.py`): `resolve("other.py", from ns import a)` (`module="ns"`, `names=("a",)`) -> `Resolved("unresolved", ())`; `import ns.a` -> `Resolved("internal", (("ns/a.py", ()),))`; `idx2.roots == frozenset({"ns","other"})`.

**5. `test_init_level_one_is_package`.** Прямые вызовы `resolve_relative(level, module, current, is_init)`: `(1, None, "pkg", True) == "pkg"`, `(1, "m", "pkg", True) == "pkg.m"`, `(1, "m", "pkg.mod", False) == "pkg.m"`, `(1, None, "pkg.mod", False) == "pkg"`, `(2, None, "pkg", True) is None`, `(2, "x", "a.b.c", False) == "a.x"`, `(3, None, "a.b.c", False) is None`. Через индекс `idx = ImportIndex(["pkg/__init__.py", "pkg/m.py"])`:
- `resolve("pkg/__init__.py", from . import m)` (`level=1`, `module=None`, `names=("m",)`) -> `Resolved("internal", (("pkg/m.py", ("m",)),))`.
- `resolve("pkg/__init__.py", from .m import x)` (`level=1`, `module="m"`, `names=("x",)`) -> `(("pkg/m.py", ("x",)),)`.
- `resolve("pkg/__init__.py", from . import zzz)` (`names=("zzz",)`) -> `(("pkg/__init__.py", ("zzz",)),)` (самоссылка как есть).
- `resolve("pkg/m.py", from . import m)` -> `(("pkg/m.py", ("m",)),)` (у обычного файла точка — его каталог; цель — сам файл, отсев не делается).
- `resolve("pkg/__init__.py", from .. import x)` (`level=2`) -> `status == "unresolved"`, `targets == ()`.
- путь вне индекса: `idx.resolve("zz/q.py", ImportRec(kind="hard", line=1, level=1, module="m", names=("x",), is_from=True, guarded=False)) == Resolved("unresolved", ())` (не `KeyError`).

**6. `test_commands_and_threads_literals`.** Источник (нумерация строк с 1):

    import threading
    from threading import Thread


    class M:
        commands = {"zeta": 1, "alpha": 2}

        def setup(self):
            self.register_command("beta", self.h)
            self.register_command(name_var)
            t = threading.Thread(target=self.h, name="worker-1")
            u = Thread(target=self.h, name=self.label)
            v = Thread(target=self.h)

Ожидается `commands == ("alpha", "beta", "zeta")` (нелитеральный `register_command(name_var)` не попадает); `threads == (("worker-1", 11), ("self.label", 12))` (поток без `name` не попадает).

**7. `test_all_plus_equals`.** Поле `all`: `'__all__ = ["a"]\n__all__ += ["b"]\n'` -> `("a", "b")`; `'__all__ = ["a"]\n__all__ += other\n'` -> `None`; `'__all__ = ["a"]\n__all__.extend(["b"])\n'` -> `None`; `'__all__ = ("a", "b")\n'` -> `("a", "b")`; `'__all__ = ["a", name]\n'` -> `None`; `'__all__: list[str] = ["a"]\n'` -> `("a",)`; `"x = 1\n"` -> `None`.

**8. `test_header_tier_contour_parsed`.** Модуль с докстрингом, `scan_text`, файл — обычный (не `__init__`). Докстринг -> `(tier, contour)`:
- `"Цель.\n\nTier: Core\nContour: ipc, lifecycle"` -> `("core", ("ipc", "lifecycle"))`, `doc == "Цель."`;
- `"Цель.\n\nTier: huge"` -> `(None, None)`;
- `"Tier: huge\nTier: optional"` -> `("optional", None)`;
- `"Contour: a\nContour: b"` -> `(None, ("a",))`;
- `"Contour: , ,"` -> `(None, None)`;
- `"Contour: a, ,b "` -> `(None, ("a", "b"))`.
(Исходник — `'"""' + докстринг + '\n"""\n'`.)

**9. `test_one_git_process_per_scan`.** Репозиторий из трёх файлов `a.py` = `"A = 1\n"`, `b.py` = `"B = 2\n"`, `c.py` = `"C = 3\n"`, один коммит. Процессы считаются подменой `subprocess.run` в `scripts.atlas.tree` (`monkeypatch.setattr(tree_module.subprocess, "run", counting)`; обёртка записывает `argv` и зовёт настоящий `run`) ПОСЛЕ подготовки фикстуры; перед каждым `scan` список вызовов очищается (фикстура `GitRepo.git`/`commit` тоже зовёт `subprocess.run`). Каждый `scan` — на новом `Tree(repo.path, "HEAD")`, `paths = ["a.py", "b.py", "c.py"]`, общий `cache`:
- холодно: ровно 2 вызова; в первом `argv` есть `"ls-tree"`, `"-r"`, `"-z"`, во втором — `"cat-file"`, `"--batch"`; `parsed == 3`;
- повтор без изменений: ровно 1 вызов (`"ls-tree"`), `"cat-file"` нет; `parsed == 0`, `hits == 3`;
- правка `a.py` (`"A = 10\n"`) и коммит: 2 вызова, `parsed == 1`, `hits == 2`;
- К `a.py`, `b.py`, `c.py` добавить через `repo.git`: `update-index --add --cacheinfo 160000,<repo.head>,sub` (gitlink) и `update-index --add --cacheinfo 120000,<repo.git("rev-parse","HEAD:a.py")>,link` (символьная ссылка), затем `repo.git("commit","-q","-m","special")`. Не `repo.commit`: его `git add .` стирает эти записи (проверено). На новом `Tree`: `files() == ["a.py","b.py","c.py","link","sub"]`; `set(oids()) == {"a.py","b.py","c.py"}`; после обоих вызовов ровно 1 вызов `ls-tree`; `scan(tree, ["a.py","link","sub"]).missing == ("link","sub")`, `list(facts) == ["a.py"]`;
- `read_blobs(repo.path, "HEAD", [])` и `Tree.read_many([])` -> `{}` и 0 вызовов; `read_blobs(repo.path, "HEAD", ["x\ny.py"])` -> `AtlasError`; `Tree.read_many(["a.py", "x\ny.py"])` -> `AtlasError`. Второй вызов обязателен: на входе `HEAD:x\ny.py\n` git отвечает кодом 0 и строками `HEAD:x missing`, `y.py missing` (наблюдено), поэтому strict-вариант падает и без проверки перевода строки, а не-strict молча вернул бы `{"a.py": b"A = 10\n", "x\ny.py": None}` (выведено по алгоритму `_read`, не прогонялось). `Tree.read_many(["a.py", "nope.py"]) == {"a.py": b"A = 10\n", "nope.py": None}`;
- `scan` не прерывается на пути с переводом строки: `scan(DictSource({"a.py": "A = 1\n", "x\ny.py": "B = 2\n"}), ["a.py", "x\ny.py"])` -> `missing == ("x\ny.py",)`, `list(facts) == ["a.py"]`.

**10. `test_blob_cache_reparses_only_changed_oids`.** Репозиторий: `x.py` = `"X = 1\n"`, `y.py` = `"Y = 2\n"`, `z.py` = `"Z = 3\n"`; кэш — свежая база. Блок схемы: `PRAGMA user_version` == 5; `[r[1] for r in con.execute("PRAGMA table_info(scan_cache)")] == ["oid", "scanner", "body"]`. Дальше `scan` на новом `Tree`:
- холодно по `["x.py","y.py","z.py"]`: `parsed == 3`, `hits == 0`, строк 3;
- `x.py` -> `"X = 10\n"` + коммит; по тем же путям: `parsed == 1`, `hits == 2`, строк 4;
- `git mv y.py w.py` без правки + коммит; по `["x.py","w.py","z.py"]`: `parsed == 0`, `hits == 3`, строк 4.

Блок хранилища, напрямую: `put_scans(con, "s1", [("o1", "[1]"), ("o2", "{}")])`; `get_scans(con, "s1", ["o1", "o2", "o3"]) == {"o1": "[1]", "o2": "{}"}`; `get_scans(con, "s2", ["o1"]) == {}`; `put_scans(con, "s1", [("o1", "new")])` -> `get_scans(con, "s1", ["o1"]) == {"o1": "new"}`.

**11. `test_facts_depend_only_on_content`.** Один текст `'"""Doc."""\n__all__ = ["a"]\nimport os\n'` в `DictSource` по путям `pkg/__init__.py` и `pkg/m.py`, общий кэш: `facts["pkg/__init__.py"] == facts["pkg/m.py"]`; у обоих `doc == "Doc."`, `all == ("a",)`; `parsed == 1`, `hits == 0`; строк в `scan_cache` — 1.

**12. `test_scanner_change_is_full_miss`.** `DictSource({"a.py": "A = 1\n", "b.py": "B = 2\n", "c.py": "C = 3\n"})`, общий кэш. Холодно: `parsed == 3`, `hits == 0`, строк 3; повтор: `parsed == 0`, `hits == 3`. После `monkeypatch.setattr(scan, "SCANNER", "x")` повторный скан: `parsed == 3`, `hits == 0`, строк 6 (2N). Формат ключа: `re.fullmatch(r"1-[0-9a-f]{12}", SCANNER)` и `SCANNER == "1-" + hashlib.sha256(Path(scan.__file__).read_bytes()).hexdigest()[:12]` (до подмены).

**13. `test_unparsable_source_gives_error_facts`.** Через `scan(DictSource(...), paths)` и `scan_text`:
- `scan_text("def (")` -> `FileFacts(loc=1, error="SyntaxError")` (прочие поля пусты);
- байты `b"\xff\xfe"` -> `FileFacts(loc=0, error="UnicodeDecodeError")`;
- `scan_text("\ufeffimport os")` -> `error is None`, ровно один `ImportRec(module="os", ...)`; то же байтами `b"\xef\xbb\xbfimport os"` через `scan(DictSource)`;
- контракт «`scan_text` не бросает никогда»: цепочка `"x = " + " + ".join(["1"] * 600) + "\n"` -> вызов не бросает исключения, `loc == 1`, на `error` утверждений нет (зависит от лимита рекурсии); цепочка из 3000 членов -> `error == "RecursionError"`, `loc == 1`;
- соседний файл скана цел (и рядом с цепочкой из 600 членов, и рядом с `b"\xff\xfe"`): `DictSource({"bad.py": b"\xff\xfe", "ok.py": "X = 1\n"})` -> `facts["ok.py"].error is None`, `facts["ok.py"].loc == 1`, `facts["bad.py"].error == "UnicodeDecodeError"`;
- D1: `DictSource({"big.py": b"#" * 1_048_577})` через `scan` (не `scan_text`) с общим кэшем: `facts["big.py"] == FileFacts(loc=0, error="BlobTooLarge")`, `parsed == 1`, `hits == 0`, строк в `scan_cache` 1; повторный `scan`: `parsed == 0`, `hits == 1`, строк 1. `DictSource({"edge.py": b"#" * 1_048_576})` -> `error is None`, `loc == 1`. Модуль: `MAX_BLOB_BYTES == 1_048_576`.

**14. `test_class_methods_keep_dunder_members`.** Источник (D5):

    from typing import Protocol
    class P(Protocol):
        def __call__(self, x): ...
    class C:
        def __init__(self): ...
        def _hidden(self): ...
        def run(self): ...
        def run(self): ...

Ожидается: `P.methods == ("__call__",)`, `P.style == "Protocol"`, `P.bases == ("Protocol",)`, `P.line == 2`; `C.methods == ("__init__", "run")`, `C.style == "class"`, `C.bases == ()`, `C.line == 4`.

Второй источник (`pass` на отдельных строках, иначе номера строк другие):

    from abc import ABC, ABCMeta
    from typing import Protocol, TypeVar
    T = TypeVar("T")
    class A(ABC):
        pass
    class B(A):
        pass
    class N(metaclass=ABCMeta):
        pass
    class G(Protocol[T]):
        pass
    class H(G):
        pass
    class Plain:
        pass

`style`: A «ABC», B «ABC», N «ABC», G «Protocol», H «Protocol», Plain «class». `bases`: A `("ABC",)`, B `("A",)`, N `()`, G `("Protocol[T]",)`, H `("G",)`, Plain `()`. `line`: 4, 6, 8, 10, 12, 14.

## Приёмка

Сьют (литералы, без времени): холодный `scan` дерева из N≥3 файлов запускает ровно 2 процесса git (`ls-tree -r -z`, `cat-file --batch`); повторный `scan` без изменений — ровно 1 (только `ls-tree`; `cat-file` не запускается, `parsed == 0`); после коммита одного изменённого файла — 2 процесса и `parsed == 1`. `files()` и `oids()` одного `Tree` делят один `ls-tree -r -z` (вывод `files()` прежний: все записи, включая символьные ссылки и gitlink; `oids()` — только blob с режимом 100644/100755). Процессы считаются подменой `subprocess.run` в `scripts.atlas.tree` после подготовки фикстуры (фикстура `GitRepo.git` тоже зовёт `subprocess.run`). Скрипт лида (числа в отчёт, не в сьют): набор — `.py` вне `tests/`, `docs/`, `test_*`, `conftest.py` в пяти корнях слоёв (на HEAD 1858): холодно ≤ 5 с, после коммита одного файла ≤ 1 с.

Прежняя строка «1867 файлов ≤ 2,6 с холодно» снята: набор из 1867 не стабилен (на HEAD 1858), а граница 2,6 с равна чтению (0,61 с) плюс `ast` (1,94 с) и недостижима одним процессом (проба ревьюера: холодно около 4,4 с ещё до сигнатур).

Остальное: `ruff check -q scripts/atlas` чисто; `pytest -q --tb=short scripts/atlas/tests` зелёный целиком (алиас `_read` держит `reference.py`/`rules.py`); `sentrux check .` без новых нарушений.

## Тесты автора (не тестера; в `test_scan.py` отдельным блоком)

1. Две нити (или два процесса) `scan` одного дерева в одну базу: оба успешны, `SELECT count(*) FROM scan_cache` равно числу различных блобов (PK).
2. База занята писателем (`BEGIN EXCLUSIVE` в другом соединении): `get_scans` и `put_scans` пишут в stderr предупреждение (R6), `get_scans` даёт `{}`; `scan` возвращает факты, исключения нет.
3. Битое тело в `scan_cache` (обрезанный JSON, `[1]`): `scan` считает промахом (`from_json` не разобрал), разбирает блоб заново, строка перезаписана.
4. `from_json(to_json(f)) == f` на фактах с пустыми и непустыми кортежами (список против кортежа — тихое расхождение «свежий не равен из кэша»).
5. Путь с пробелом, с кириллицей (на HEAD 15 путей не-ASCII, 1 с пробелом), с переводом строки (R3): пакетное чтение не сдвигает ответы.
6. Цепочка из 600 слагаемых (без исключения), `"\ufeff"`, NUL-байт, не-UTF-8 (R4): `error` заполнен там, где он обещан, остальные файлы скана целы.
7. Усечённый вывод `cat-file`: `returncode != 0` -> `AtlasError` (`code.py:44-45`); усечение при коде 0 `_read` не проверяет (срез `proc.stdout[pos:pos+size]` молча короче) — добавить проверку `len(blob) == size` и тест на неё.
8. Огромный блоб (D1) сквозь git: фикстура с блобом `b"\xff" * 1_048_577` через `Tree` -> `error == "BlobTooLarge"` (не `UnicodeDecodeError`: доказывает, что декодирования нет); блоб около 400 КБ из строк-комментариев разбирается (`error is None`).
9. (Из R6, красного нет.) `get_scans` на 1200 oid возвращает все 1200 строк (порции по ≤ 500).

## Разовые сверки разработчика (числа в отчёт разработчика, в сьют не идут)

- **D2.** На HEAD: число результатов `unresolved`, у которых путь модуля лежит в каталоге без `__init__.py`. Число — в отчёт; шум это или нет, решает B1.
- **D3 (а).** Список `roots` на HEAD и его пересечение с именами верхнего уровня установленных дистрибутивов (`importlib.metadata.packages_distributions()`).
- **D3 (б).** Число рёбер, где `ImportIndex.resolve` расходится с `resolve_import` карты на HEAD, и до 5 примеров. Карта правится параллельно: сверять по рабочему дереву главного репозитория и записать, на каком состоянии `build.py` (хеш файла) сверка сделана.

## Вне задачи

Адаптеры (`adapters/imports.py` — B1), виды и справка (A2, A3), удаление карты и `scripts/arch_graph/` (B2), сигнатуры, докстринги, `calls`, признак `abstractmethod` (A3, вместе со сменой `SCANNER`), `multiprocessing` (параллельный разбор в тексте не предусмотрен), очистка старых строк `scan_cache`, `VACUUM`, правка `reference.py`, `rules.py`, `conftest.py`.

## Что оставлено открытым / ненадёжно

1. **Реализации нет, литералы сверены только с функциями карты.** Совпадение `ImportIndex.resolve` с `resolve_import` карты проверено ревьюером на заглушке `Graph`, на входах красных 4–5 и случае D2, не на HEAD (на HEAD — разовая сверка D3 б). Литералы красных 1–8 и 14 для полей, общих с `ParsedFile`, сверены прогоном `parse_source` карты.
2. **Красный 13, цепочка из 3000 членов:** на Python 3.12.12 при лимите рекурсии 1000 `ast.parse` падает с `RecursionError` с n=2994, запас 6 членов. Надёжно, пока никто не поднимает `sys.setrecursionlimit` (в репозитории он только в `scripts/arch_graph/ast_graph.py:276` под `__main__`). На Python 3.13 и новее литерал может не совпасть.
3. **Цепочка из 600 членов:** `collect_imports` карты падает с `RecursionError` уже с около 500 членов, так что при простом порте `error == "RecursionError"`; красный на `error` не утверждает.
4. **Не проверено, нужна ли запись в `modules.yaml` или README для нового `scan.py`.**
5. **Время** — одна проба на нагруженной общей машине, без повторов, без сигнатур и докстрингов (их в A1 нет). Реальный холодный скан может быть выше 4,4 с; порог 5 с проверяет лид скриптом.
6. **Рост `scan_cache` без очистки** не оценён; время сброса базы в 289 МБ не измерялось.
7. **`SCANNER` на хеше файла:** правка комментария в `scan.py` сбрасывает кэш фактов. Принято (цена — один холодный скан).
8. **Карта правится параллельно:** порт снимается по именам; расхождение порта с картой после этой даты не отслеживается.
9. **`read_blobs(strict=True)` на отсутствующем пути** — поведение бывшего `_read`, красными не закрыто.
