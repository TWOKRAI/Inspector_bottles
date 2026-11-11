"""Паспорт символа Д1 (Task 4.2a): один объект про класс, функцию, метод или привязку имени (Task 4.6a) — для `ref
--format`, бенча и агента.
Тот же конверт и шесть разделов у юнита и файла (`build_map`, Task 4.2b-2) — для `atlas map`.

Purpose: по ревизии git (`ref`) и идентификатору символа собирает паспорт: конверт и шесть разделов с постоянными
    ключами (JSON-совместимый `dict`), печатает его текстом по бюджету строк. Читает факты v2 (`scan`), связи
    (`build_links`), слой (`modules_for` + `modules.resolve`). Не меняет репозиторий (кроме stat-кэша `.git/index`,
    который обновляет `git diff` из `status.stale`) и не меняет рабочее дерево; рабочее дерево читает только
    `status.stale`; пишет только кэш фактов `data/atlas.sqlite` через `scan()`.
Public API: build_passport, build_map, resolve_ident, render_text, passports_for.
Stability: lite

Pre: `root` — корень git-репозитория (каталог с `.git`), `ref` — ревизия git (как у `ref` Task 4.1: `HEAD`, ветка,
    sha). Пути в паспорте — posix, от `root`. `exclude` — префиксы путей от `root` (posix): файлы под префиксом не
    читаются и в паспорт не попадают (ни как символ, ни как связь).
Post: паспорт детерминирован: та же ревизия -> тот же `dict` (кроме `status.stale`: он зависит от рабочего дерева).
    Модуль не меняет репозиторий (кроме stat-кэша `.git/index`) и рабочее дерево.

Правило пустого. `null` раздела или ключа = «не искали» (источника нет, значение — другая задача); `[]` и `0` =
«искали, не нашли». `where: null` у ЗАПИСИ внутри раздела = «адрес не разрешён» — это не `null` раздела. `line`
отдельно от пути в разделах не пишется: адрес — одна строка `where: "путь:строка"`. Исключение — конверт (`path`,
`line` самого символа).

Конверт (все ключи всегда):

  ключ       тип   значение
  passport   int   `1`
  kind       str   `class` | `function` | `method` (`DefFact.kind`) | `binding` (4.6a); у `build_map` — `unit` | `file`
  id         str   `путь::qualname`; у `build_map` — id юнита реестра (`unit`) или путь файла (`file`)
  path       str   путь файла символа; у `build_map` — `paths[0]` юнита как в реестре (`unit`) или путь файла (`file`)
  line       int | null   строка `def`/`class` (`DefFact.line`); `null` у `build_map` (юнит и файл без строки)
  sha        str   полный sha ревизии `ref` (40 символов), не имя ветки
  scanner    str   `scan.SCANNER` (версия сканера фактов)

Шесть разделов, порядок ключей верхнего уровня: `purpose`, `interface`, `links`, `runtime`, `checks`, `status`.
Ключи разделов есть у всех видов (класс, функция, метод, привязка); не относящееся к виду — `null`.
Идентификатора `io` среди разделов нет: ввод-вывод — ключ `runtime.io` (Д1).

`purpose` — зачем символ:

  ключ              тип                     null / пусто
  text              str                     `""` — докстринга нет (искали, нет); иначе первый абзац (`DefFact.doc`)
  called_from       list[dict] (0 или 1)    `[]` — вызывающих из продукта нет. Запись `{"qualname": str, "text": str}`:
                                            `qualname` — `enclosing` вызова из продукта (`scope: prod`) с высшим `rank`
                                            (DESIGN 3), без `<module>`; `text` — первый абзац его докстринга, `""` — нет
  called_from_more  int                     число прочих вызывающих (по другим `enclosing`) из продукта; `0` — нет
  declared_at       null                    всегда `null` (источника в 4.1 нет)

`interface` — как символ встроен в код:

  ключ       тип                      null / пусто
  layer      str                      id юнита слоя (`modules_for(Tree(root, ref))` + `modules.resolve(path, rows)`);
                                      `"other"` — путь ни в одном юните. Не `null`. НЕ `load_modules()`: ревизия
  all        list[str] | null         `null` — литерального `__all__` нет ни у файла символа, ни у одного `__init__.py`
                                      цепочки (от ближайшего пакета до юнита). Иначе пути звеньев, где имя в `__all__`:
                                      сначала файл символа, если его `__all__` с именем (Task 4.5c, В14), затем
                                      `__init__.py` от ближайшего пакета до юнита — и когда у файла `__all__` нет;
                                      `[]` — `__all__` есть хотя бы у одного звена, имени нигде нет
  signature  str                      у функции и метода — хвост строки `reference._sig` после имени (без `self`/`cls`,
                                      `-> T` после скобок): `(key: str) -> None`; у `async def` — `async (x: int) -> T`
                                      (как `reference._sig`); у `property` — `-> T` или `""`; у класса `""`
  members    list[dict] | null        у класса: члены из `defs` 4.1, отбор как `reference._methods` (неприватные +
                                      `codemap.DUNDERS`), порядок исходника; `[]` — членов нет. У функции, метода
                                      `null`. В тексте режется (Task 4.5c): минимум 3, хвост `ещё N; --full`.
                                      Класс без публичных методов (Task 4.6b): члены — его поля, прямые привязки
                                      тела (`_body_bindings`, по строке; имя метода или вложенного класса — нет),
                                      `signature` формы привязки 4.6a; текст — `публичных методов нет; полей N:` и
                                      `<имя><signature>  :строка`; у класса с любым членом `_methods` (публичный
                                      метод или dunder) поля не входят; `where` поля — строка оператора, не `def`
                                      Запись `{"name": str, "signature": str, "where": "путь:строка"}`; `signature` — по
                                      правилу `signature` выше; `where` — строка `def` члена (не `null`)

`links` — связи (источник — `Links.of`, записи как в докстринге `links.py`; порядок записей — по `(where, line)`):

  ключ                    тип                     null / пусто
  used_by                 list[dict]              `[]` — импортов нет. Запись `{where, how: "import", scope,
                                                  enclosing: "<module>"}`
  uses                    null                    всегда `null` (источника в 4.1 нет)
  subclasses              list[dict]              `[]` — наследников нет. Запись `{where, how: "import" |
                                                  "same-file", scope, enclosing, rank}`
  call_sites              list[dict]              `[]` — разрешённых вызовов нет. Запись `{where, how:
                                                  "name-call", scope, enclosing, same_file, rank}`
  call_sites_unresolved   int                     `0` — неотнесённых вызовов нет. Счётчик «не видно», не список
  bases                   list[dict] | null       у класса: основы в порядке `DefFact.bases`, запись
                                                  `{name, where, how, scope}`;
                                                  у неразрешённой основы `where`, `how`, `scope` = `null` («адрес не
                                                  разрешён»); `[]` — класс без основ. У функции и метода `null`
  structural              dict | null             у класса: `{"required": list[str], "twins": list[str],
                                                  "note": str | null}`;
                                                  `twins` — `путь::qualname`; протокол с менее чем двумя обязательными
                                                  методами: `required: []`, `twins: []`, `note` = `links.TOO_GENERIC`;
                                                  иначе
                                                  `note: null`. У функции и метода `null`
  call_sites_by_name      dict | null             (Task 4.5b) у метода: `{"count": N, "items": list[dict] | null}` —
                                                  вызовы `x.<имя>(...)` из продукта, `x` не `self`, не отнесённые ни
                                                  к одному символу (`Links.of`, тип `x` не проверен); `items` — записи
                                                  `{where, how: "by-name", scope, enclosing, same_file, rank}` при
                                                  N <= 10, `null` при N > 10 (имя частое); `{"count": 0, "items": []}`
                                                  — таких нет. У класса и функции `null`; у `build_map` ключа нет

`rank` (int) записи `links.call_sites`, `links.subclasses`, `checks.tests` — число вызовов из продукта
(`scope: prod`, `call_sites`) у её `enclosing` (`<module>` — 0); у `used_by` ключа нет (ранг импорта всегда 0).
Сужение DESIGN 3 (там к рангу прибавлялись prod `used_by`) принято лидом. Ключ нужен `render_text` для порядка среза.

`where` записи — `"путь:строка"` или `null`; у `used_by`, `subclasses`, `call_sites` он всегда строка (из `Links`).
`scope` — `"prod"` | `"test"` (по пути записи).

`runtime` — рантайм-следы, найденные статикой:

  ключ        тип                  null / пусто
  processes   null                 всегда `null` (источника в 4.1 нет)
  threads     list[dict]           `[]` — пусков нет. Запись `{"pattern": str, "daemon": bool | null,
                                   "where": "путь:строка"}`:
                                   `ThreadSite` с `enclosing` = qualname символа или вложенный в него; `where` — строка
                                   КОНСТРУКТОРА; `daemon: null` — не задан или не литерал
  commands    list[dict] | null    `null` — в области символа нет `def command_specs` (текст «форма command_specs() не
                                   объявлена»). Иначе записи `{"name": str, "where": "путь:строка", "how": "declared"}`
                                   по литералам кортежа или `CommandSpec(...)`; запись без `where` не рождается (R2);
                                   `[]` — объявлена, литералов нет. Область — символ-класс или функция, чьё тело
                                   (с вложенными) содержит `def command_specs`. У самого объявляющего
                                   `command_specs` символа (метода или вложенной функции) `commands` = `null`: форма
                                   относится к вмещающему символу
  io          list[dict]           `[]` — побочных эффектов нет. Запись `{"op": "watch" | "replaces", "path": str,
                                   "where": "путь:строка"}`:
                                   `IoFact` с `enclosing` = qualname символа или вложенный; `path` — ВЫРАЖЕНИЕ пути
                                   (`str(self._path.parent)`), не адрес

`checks`:

  ключ      тип                 null / пусто
  findings  list[dict] | null   `null` — не искали или нет совпадения по `node` (в v1 практически всегда: `node` — узел
                                реестра, не `путь::qualname`). Иначе находки готовой сборки `sha` (`main_ref=sha`) по
                                `node` символа; `build()` не вызывается
  tests     list[dict]          `[]` — тестов нет. Записи `Links.of(...)["tests"]`: `{where, how: "test-body",
                                scope: "test", enclosing, rank}`

`status`:

  ключ         тип           null / пусто
  tier         str | null    `FileFacts.tier` файла символа; `null` — шапки `Tier:` нет
  doc_missing  bool          `True` — у символа нет докстринга (`purpose.text == ""`)
  dynamic      int           `links.call_sites_unresolved` + число динамических `command_specs` (`command_specs_dynamic`
                             в `scan.py`, 4.2a GREEN; `0`, если `runtime.commands` — `null`)
  stale        list[str] | null   пути паспорта (`path`, путь из каждого `where`, из `structural.twins`), чьё
                             содержимое в рабочем дереве отличается от `sha`: один `git --no-optional-locks
                             --literal-pathspecs diff -z --name-only --no-renames <sha> -- <пути>` (при > 100 путях —
                             тот же `git diff` без `-- <пути>`, пересечение в Python; Task 4.2b-2); порядок — как пути
                             в паспорте, без повторов. `[]` — искали, чисто. `null` — не искали: `sha` != HEAD корня,
                             HEAD не разрешается или `git diff` упал (bare-клон). `where: null` пропускается;
                             неотслеженные файлы не ищутся
  frozen       list[dict]    шапки `FREEZE YYYY-MM-DD: текст` — сначала докстринг файла символа, затем `__init__.py`
                             цепочки (обход каталогов общий с `interface.all`). Запись `{"date": str, "text": str,
                             "where": "путь:строка"}`; `text` — после `FREEZE YYYY-MM-DD: `; `where` — строка шапки.
                             Без повторов. Звено цепочки с `error` пропускается. `[]` — искали, нет. `null` у
                             `frozen` в v1 не бывает

Паспорт привязки (Task 4.6a). Привязка — имя из прямого оператора тела модуля или класса (`Cls`, `Outer.Inner`,
`f.Cls`, у которого есть `DefFact` `kind == "class"`): `Assign` — каждая цель `ast.Name` (`A = B = 1` — две;
`a, b = ...` — нет), `AnnAssign` с целью `Name` (со значением и без), `ast.TypeAlias`. Не привязка: операторы внутри
`if`/`try`/`with`/`for`/`while`, `self.x`, локальные имена функций, `+=`. Побеждает первый оператор (его `lineno` —
`line`). id — `путь::ИМЯ`, `путь::Cls.ИМЯ`, `путь::Outer.Inner.ИМЯ`; ищется только при промахе `find` (имя из `defs`
даёт прежний паспорт). Голое имя (`ref ИМЯ` без пути) привязку не находит: `not found`.
Те же конверт и шесть разделов, `kind: "binding"`; значения:

  ключ                    значение
  purpose                 `text`, `called_from`, `declared_at`: `null`; `called_from_more`: `0`
  interface.layer, .all   как у метода: слой файла; `all` — звенья `__all__` по первому сегменту qualname
  interface.signature     `AnnAssign` — `: <ann>` [+ ` = <value>`]; `Assign` — `= <value>`; `TypeAlias` — `type` [+
                          `[<params>]`] + ` = <value>`; части — `ast.unparse`; `<value>` длиннее 120 символов — первые
                          120 и `…` (ровно 120 — без среза); аннотация не режется
  interface.members       `null`
  links.used_by           у привязки модуля — `Links.imports_of(path, qualname)` (from-импорт любого имени); у привязки
                          класса `[]` (`Schema.KIND` не наследует импорт модульного `KIND`)
  links.*  (прочие)       `null` (`uses`, `subclasses`, `call_sites`, `call_sites_unresolved`, `bases`, `structural`,
                          `call_sites_by_name`)
  runtime.*, checks.*     `null` (`processes`, `threads`, `commands`, `io`, `findings`, `tests`)
  status                  `tier`, `stale`, `frozen` как у символа; `doc_missing`, `dynamic`: `null`

Текст — `_render_binding`: строки «не искали» — литералы; значения только у `signature`, `all`, `used_by`, `tier`,
`stale`, `frozen`. Срез `used_by` — `SHOW_ALL_SECTIONS`.

Паспорт юнита и файла (`build_map`, Task 4.2b-2). Конверт и шесть разделов — те же, ключи постоянны; `kind` — `unit`
| `file`, `line` — `null`. Цель: id строки реестра (`modules_for(Tree(root, sha))`, не `load_modules()`) -> `unit`;
иначе путь `.py` ревизии вне `exclude` -> `file`; обратная косая черта в цели читается как `/`. Члены юнита — файлы
`.py` вне `exclude` с `modules.resolve(path, rows) == id` (вложенный юнит не входит). Значения ключей (источник —
`plans/2026-11-06_atlas-passport/map-form.md` п. 1–2; здесь — отличия от паспорта символа):

  ключ                     unit                                          file
  purpose.text             `purpose` строки реестра                      `FileFacts.doc` (первая строка докстринга)
  purpose.declared_at,
    .called_from           `null`                                        `null` (`called_from_more` — `0`)
  interface.layer          id юнита                                      `modules.resolve(path)` (`other` -> `"other"`)
  interface.all            `FileFacts.all` у `__init__.py` юнита         `null` (не искали, сознательно)
                           (`paths[0]+"__init__.py"` у каталога, сам
                           `paths[0]`, если это `__init__.py`); `null` —
                           кандидата нет (текст `не искали`) или у него
                           нет фактов/`__all__` (текст `—`)
  interface.signature      `null`                                        `null`
  interface.members        форма A — по ПРОД-ФАЙЛАМ: `{name: путь,       форма B — по символам: `{name: qualname,
                           signature: null, where: "путь:1",             signature, where}`, верхний уровень,
                           top: [имена без `_`], doc: FileFacts.doc}`,    имена на `_` тоже; классы и функции,
                           порядок `(-операторов импорта с целью в       методы не входят; с Task 4.6b — и
                           файле, путь)`                                 привязки модуля (`_body_bindings`, имя не
                                                                         из `defs`; `signature` формы 4.6a), всё по
                                                                         строке; срез текста — class/def первыми
  links.used_by            `{name: id юнита-импортёра, where, how:       то же, цель — файл (реэкспорт через
                           "import", count}`, `where` — min по (путь,    `__init__` у файла не виден); импортёры —
                           строка); `count` — операторов импорта, включая кроме самого файла и `__init__.py` его
                           импорт через реэкспорт; порядок `(-count,     цепочки пакетов; свой юнит — группой
                           name)`; импортёры — вне юнита                 с id своего юнита
  links.call_sites,
    subclasses, bases,
    structural, uses,
    call_sites_unresolved  `null`                                        `null`
  runtime.threads/io/      записи продуктовых файлов по `(путь, строка)` записи файла; `commands` — `[]`, если нет
    commands
  runtime.processes,
    checks.findings        `null`                                        `null`
  checks.tests             `{name: путь тест-файла, where: "путь:1",     `null`
                           count: число test-функций}`, `count > 0`
  status.tier              `tier` строки реестра                         шапка `Tier:` файла
  status.doc_missing       нет `README.md` среди `docs` строки           `purpose.text == ""`
  status.dynamic           сумма `command_specs_dynamic` по prod-файлам  `command_specs_dynamic` файла
                           (без `call_sites_unresolved`: он по имени)
  status.stale             правило 4.2b-1 по путям цели и `where`        правило 4.2b-1 по пути файла и `where`
  status.frozen            шапки `__init__.py` юнита (тот же кандидат,   цепочка файла (4.2b-1)
                           что у `interface.all`; иначе `[]`)

Продуктовый файл — `links._scope(path) == "prod"`; тест-файлы входят только в `checks.tests`. Две формы
`interface.members`: у `unit` запись — файл (форма A), у `file` — символ (форма B).

Не входит: `recipes`; `kind` выше unit/file (package, layer); `uses`; `interface.all` у файла; методы в `members`; кэш
`links` (`build_links` пересчитывается при каждом вызове).

Текст (`render_text`). Порядок: `== <id> ==`; строки конверта (`path:line`, `sha`, `scanner`); затем шесть разделов в
порядке `purpose`, `interface`, `links`, `runtime`, `checks`, `status` — у каждого строка-заголовок `<раздел>:`.
Искали и нет (`[]`, `0`) — `<раздел>: —`; `null` — `<раздел>: не искали`. Образцы (литералы из DESIGN 2):

  - связи: `найдено 3 (формы: import, name-call); не видно: динамика, аннотации, упоминания`; формы — значения `how`
    записей раздела в порядке `links.py` (`import`, `name-call`, `same-file`, `test-body`); счёт по областям: `из
    продукта A, из тестов B` (A, B — число записей `scope: prod` и `scope: test`, отдельно, не суммой);
  - срез: `показано K из N; все: --all <раздел>`;
  - пустые `runtime` символа (Task 4.5b; у `map` — прежний `—`): `threads: — (ищет: Thread, Timer, Observer)`
    (`scan.THREAD_PATTERNS`), `io: — (ищет: ...)` (`scan.IO_PATTERNS`), `commands: — (ищет только def
    command_specs(); register_command(...) не читает)`; у `commands: null` — `_NO_SPECS`, пробел, та же оговорка;
  - вызовы по имени метода (Task 4.5b): N <= 10 — `по имени метода, тип не проверен (N):` и записи `_link_row`
    (срез — список `call_sites_by_name` в `_alloc`, снимает его `--all call_sites`); N > 10 — одна строка
    `по имени метода (prod, без self): N вызовов .<имя>(...) - имя частое, адреса не печатаются` (ASCII ` - `,
    в остальном тексте — «—»); N = 0, класс и функция — строки нет;
  - член класса: `  имя(сигнатура)  :строка`, например
    `  __call__(key: str, old_value: Any, new_value: Any) -> None  :17`;
  - связь с адресом: `<имя> — <путь:строка> (<how>)`, `<имя>` — `name` у основы, `enclosing` у прочих связей;
  - связь с `where: null`: `<имя> — строка не указана`;
  - срез и имена среза: у class/function/method/binding — `SHOW_ALL_SECTIONS`; у `kind` unit/file (Task 4.2b-2) —
    `MAP_SHOW_ALL`; `render_text` выбирает набор по `kind` паспорта. Метка среза входит в бюджет. Текст `map`
    — образец `map-form.md` п. 3 (`== unit u ==`, вторая строка `<path>; sha <sha>; scanner <scanner>` без `:line`);
  - статус (Task 4.2b-1): строка `status:` несёт `tier`, `doc_missing`, `dynamic`; затем строки с отступом в 2
    пробела: `  stale: —` (`[]`), `  stale: не искали` (`null`), `  stale: a.py, b.py` (без среза); `  frozen: —`
    (`[]`), иначе по строке на шапку `  frozen: <date> <text> (<путь:строка>)`. Строки входят в служебный минимум
    (не режутся).
Расположение образцов внутри раздела `links` (подзаголовки `used_by`, `call_sites`, ...) тестом RED не утверждается,
кроме самих образцов выше.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from scripts.atlas import store
from scripts.atlas.adapters.modules import modules_for
from scripts.atlas.links import TOO_GENERIC, Links, _scope, build_links
from scripts.atlas.modules import norm_path
from scripts.atlas.modules import resolve as module_of
from scripts.atlas.reference import _methods, _sig, _tag
from scripts.atlas.scan import IO_PATTERNS, SCANNER, THREAD_PATTERNS, DefFact, FileFacts, ImportIndex, scan
from scripts.atlas.tree import AtlasError, Tree, git_z, resolve


__all__ = ["build_map", "build_passport", "passports_for", "render_text", "resolve_ident"]

SECTIONS = ("purpose", "interface", "links", "runtime", "checks", "status")  # порядок ключей и заголовков
SHOW_ALL_SECTIONS = ("used_by", "call_sites", "subclasses", "structural", "tests")  # допустимые значения `show_all`
MAP_SHOW_ALL = ("members", "used_by", "tests", "threads", "io")  # то же у `kind` unit/file (`atlas map --all`)
# имена среза текста символа (`_alloc`): `members` класса (Task 4.5c; флага `--all` нет, только `--full`:
# `_FULL_ONLY`) + `SHOW_ALL_SECTIONS` + адреса по имени метода (Task 4.5b; флага `--all` своего нет: его снимает
# `--all call_sites`, `_ALL_FLAG`)
_SYMBOL_CUT = ("members", *SHOW_ALL_SECTIONS, "call_sites_by_name")
_ALL_FLAG = {"call_sites_by_name": "call_sites"}  # список среза -> значение `--all`, что его снимает

_SIDE_DIRS = ("docs/", "plans/", ".claude/")  # продукт внутри них — после основного продукта (`_order`, группа 1)
_MEMBERS_MIN = 3  # `members` класса в тексте: меньше 3 строк не режется; остаток — `ещё N; --full`
_FULL_ONLY = {"members": _MEMBERS_MIN}  # списки без своего `--all`: снимает только `--full`; значение — минимум строк
_FORMS = ("import", "name-call", "same-file", "test-body")  # порядок форм — порядок упоминания в `links.py`
_UNSEEN = "не видно: динамика, аннотации, упоминания"
_NOT_SEARCHED = "не искали"
_EMPTY = "—"
_NO_SPECS = "форма command_specs() не объявлена"
_COMMANDS_NOTE = "(ищет только def command_specs(); register_command(...) не читает)"  # Ф9.7: register_command
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
_PATHSPEC_MAX = 100  # `status.stale`: больше путей — `git diff` без pathspec (предел argv), пересечение в Python
_TOP_SHOWN = 6  # `top` члена юнита в тексте: до 6 имён, остаток `, +N`
_STALE_SHOWN = 5  # `stale` в тексте `map`: первые 5 путей, остаток `; ещё N`
_VALUE_MAX = 120  # `signature` привязки (4.6a): значение длиннее — первые 120 символов и `…`


def _norm_exclude(exclude: tuple[str, ...], root: Path) -> tuple[str, ...]:
    """`--exclude`: `./pkg`, `pkg\\` -> `pkg`; пустой, выше корня, вне корня -> AtlasError; префикс, равный корню
    (`.`, `./`, `a/..`), — AtlasError: он скрыл бы весь репозиторий (код 2, значение пути в тексте не печатается)."""
    out = []
    for prefix in exclude:
        norm = norm_path(prefix, root)
        if norm == ".":
            raise AtlasError("atlas: --exclude: путь совпадает с корнем репозитория")
        out.append(norm)
    return tuple(out)


def _excluded(path: str, exclude: tuple[str, ...]) -> bool:
    """Путь под префиксом: равен ему или начинается с `префикс/` (DESIGN 6)."""
    for prefix in exclude:
        head = prefix.rstrip("/")
        if head and (path == head or path.startswith(head + "/")):
            return True
    return False


def _split(where: str) -> tuple[str, int]:
    path, _, line = where.rpartition(":")
    return path, int(line)


def _passport_paths(passport: dict) -> list[str]:
    """Пути паспорта для `status.stale` в порядке паспорта, без повторов: `path`, затем обход разделов до `status`
    в порядке ключей — путь каждого `where` (кроме `null`) и путь каждого `structural.twins` (часть до `::`).
    У `kind: unit` `path` — каталог (`paths[0]`), он не входит: файлы юнита приходят из `where` членов и тестов."""
    out = [] if passport["kind"] == "unit" else [passport["path"]]

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "where":
                    if isinstance(item, str):
                        out.append(_split(item)[0])
                elif key == "twins" and isinstance(item, list):
                    out.extend(twin.partition("::")[0] for twin in item)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for section in SECTIONS[:-1]:  # `status` строится после: его `frozen.where` в `stale` не входит
        walk(passport[section])
    return list(dict.fromkeys(out))


def _find_node(tree: ast.AST, qualname: str, line: int) -> ast.AST | None:
    """Узел `def`/`class` по qualname (правило `_V2Collector`: имя растёт только на def/class) и строке."""

    def walk(node: ast.AST, prefix: str) -> ast.AST | None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (*_FUNCS, ast.ClassDef)):
                name = prefix + child.name
                if name == qualname and child.lineno == line:
                    return child
                hit = walk(child, name + ".")
            else:
                hit = walk(child, prefix)
            if hit is not None:
                return hit
        return None

    return walk(tree, "")


def _tail(fn: ast.FunctionDef | ast.AsyncFunctionDef, drop_first: bool) -> str:
    """Строка `reference._sig` без имени: `(x: int) -> str`, `async (x: int) -> str`; у property — `-> T` или `""`."""
    full = _sig(fn, drop_first)
    prefix = "async " if full.startswith("async ") else ""
    return prefix + full.removeprefix(prefix).removeprefix(fn.name).strip()


def _drop_first(fn: ast.FunctionDef | ast.AsyncFunctionDef, is_method: bool) -> bool:
    return is_method and "staticmethod" not in {_tag(d) for d in fn.decorator_list}


@dataclass(frozen=True)
class _Binding:
    """Привязка имени (Task 4.6a): `qualname` — `ИМЯ` модуля или `Cls.ИМЯ`; `line` — строка первого оператора."""

    qualname: str
    line: int
    signature: str


def _cut_value(node: ast.expr) -> str:
    """`ast.unparse` значения; длиннее `_VALUE_MAX` символов — первые `_VALUE_MAX` и `…` (ровно столько — без среза)."""
    text = ast.unparse(node)
    return text[:_VALUE_MAX] + "…" if len(text) > _VALUE_MAX else text


def _binding_sig(stmt: ast.stmt) -> str:
    """`signature` привязки по оператору: `AnnAssign` — `: <ann>` [+ ` = <value>`]; `Assign` — `= <value>`;
    `TypeAlias` — `type` [+ `[<params>]`] + ` = <value>`. Части — `ast.unparse`; аннотация не режется."""
    if isinstance(stmt, ast.AnnAssign):
        value = f" = {_cut_value(stmt.value)}" if stmt.value is not None else ""
        return f": {ast.unparse(stmt.annotation)}{value}"
    if isinstance(stmt, ast.TypeAlias):
        params = f"[{', '.join(ast.unparse(p) for p in stmt.type_params)}]" if stmt.type_params else ""
        return f"type{params} = {_cut_value(stmt.value)}"
    assert isinstance(stmt, ast.Assign)
    return f"= {_cut_value(stmt.value)}"


def _body_bindings(body: list[ast.stmt]) -> dict[str, tuple[int, str]]:
    """Привязки прямых операторов тела модуля или класса: `имя -> (строка оператора, signature)`.

    Привязка — каждая цель-`Name` у `Assign` (`A = B = 1` — две; `a, b = ...` и `self.x = ...` — нет), цель-`Name` у
    `AnnAssign` (со значением и без), имя `TypeAlias`. Операторы внутри `if`/`try`/`with`/`for`/`while`, вложенных
    `def`/`class` и `+=` не входят. Побеждает первый оператор имени. Не бросает."""
    out: dict[str, tuple[int, str]] = {}
    for stmt in body:
        if isinstance(stmt, ast.Assign):
            names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            names = [stmt.target.id]
        elif isinstance(stmt, ast.TypeAlias):
            names = [stmt.name.id]
        else:
            continue
        if names:
            sig = _binding_sig(stmt)
            for name in names:
                out.setdefault(name, (stmt.lineno, sig))
    return out


@dataclass
class _Ctx:
    """Факты, связи и слой одной ревизии; строится один раз на вызов `passports_for`."""

    root: Path
    sha: str
    tree: Tree
    facts: dict[str, FileFacts]
    links: Links
    _rows: list[dict] | None = None
    _ranks: dict[tuple[str, str], int] = field(default_factory=dict)
    _asts: dict[str, ast.Module | None] = field(default_factory=dict)  # разбор файла один раз на `_Ctx` (4.6a)

    @classmethod
    def open(cls, root: Path, ref: str, exclude: tuple[str, ...], *, with_links: bool = True) -> _Ctx:
        """`with_links=False` — без `build_links` (пустой `Links`): `map` связей символов не читает (~0,5-1 с)."""
        root = Path(root)
        exclude = _norm_exclude(exclude, root)
        sha = resolve(root, ref)
        tree = Tree(root, sha)
        paths = sorted(p for p in tree.oids() if p.endswith(".py") and not _excluded(p, exclude))
        con = store.connect(root / "data" / "atlas.sqlite")  # кэш фактов `scan_cache`: тёплый вызов не разбирает
        try:
            facts = scan(tree, paths, cache=con).facts
        finally:
            con.close()
        return cls(root, sha, tree, facts, build_links(facts) if with_links else Links())

    def rows(self) -> list[dict]:
        if self._rows is None:
            self._rows = modules_for(self.tree)
        return self._rows

    def defs(self, path: str) -> list[DefFact]:
        facts = self.facts.get(path)
        return list(facts.defs) if facts is not None else []

    def find(self, path: str, qualname: str) -> DefFact | None:
        return next((d for d in self.defs(path) if d.qualname == qualname), None)

    def resolve(self, ident: str) -> list[str]:
        """Полные id по `ident`; часть до `::` (или голое имя) идёт через `norm_path` (AtlasError — код 2 в CLI)."""
        path, sep, qualname = ident.partition("::")
        path = norm_path(path, self.root)
        if sep:
            found = qualname and (self.find(path, qualname) is not None or self.binding(path, qualname) is not None)
            return [f"{path}::{qualname}"] if found else []
        return [f"{p}::{path}" for p in sorted(self.facts) if self.find(p, path) is not None]

    def _module_ast(self, path: str) -> ast.Module | None:
        """Разбор файла ревизии один раз на `_Ctx` (как `_node`: `decode`, `removeprefix` BOM); ошибка — None."""
        if path not in self._asts:
            try:
                self._asts[path] = ast.parse(self.tree.read(path).decode("utf-8").removeprefix("﻿"))
            except Exception:  # noqa: BLE001 — привязку не найти; паспорт def/class от этого не зависит
                self._asts[path] = None
        return self._asts[path]

    def binding(self, path: str, qualname: str) -> _Binding | None:
        """Привязка `qualname` в файле `path` (запасной поиск при промахе `find`; правила — `_body_bindings`).

        Pre: `path` — путь файла ревизии; `qualname` — `ИМЯ` (тело модуля) или `Cls.ИМЯ`/`Outer.Inner.ИМЯ`, где
            владелец — `DefFact` `kind == "class"` (тело модуля и тело этого класса — прямые операторы).
        Post: `None`, если файла нет в фактах или он с `error`/`v2_error` (символы таких файлов не находятся), владелец
            не класс (функция, метод, нет), файл не разбирается или имени в прямых операторах нет. Не бросает."""
        facts = self.facts.get(path)
        if facts is None or facts.error is not None or facts.v2_error is not None:
            return None
        module = self._module_ast(path)
        if module is None:
            return None
        if "" in qualname.split("."):  # пустой сегмент (`.X`, `X.`, `A..b`) — не привязка
            return None
        owner, _, name = qualname.rpartition(".")
        body = module.body
        if owner:
            d = self.find(path, owner)
            node = _find_node(module, owner, d.line) if d is not None and d.kind == "class" else None
            if not isinstance(node, ast.ClassDef):
                return None
            body = node.body
        hit = _body_bindings(body).get(name)
        return None if hit is None else _Binding(qualname, *hit)

    def rank(self, path: str, enclosing: str) -> int:
        """Число вызовов из продукта у `путь::enclosing`; `<module>` — 0."""
        if enclosing == "<module>":
            return 0
        key = (path, enclosing)
        if key not in self._ranks:
            got = self.links.of(f"{path}::{enclosing}")
            calls = got["call_sites"] if got is not None else []
            self._ranks[key] = sum(1 for e in calls if e["scope"] == "prod")
        return self._ranks[key]

    def ranked(self, entries: list[dict]) -> list[dict]:
        out = []
        for entry in entries:
            path, _ = _split(entry["where"])
            out.append({**entry, "rank": self.rank(path, entry.get("enclosing", "<module>"))})
        return out

    # ------------------------------------------------------------------ разделы

    def passport(self, ident: str) -> dict:
        path, _, qualname = ident.partition("::")
        d = self.find(path, qualname)
        if d is None:
            bound = self.binding(path, qualname)
            if bound is None:
                raise AtlasError(f"atlas: symbol not found: {ident}")
            return self._binding_passport(ident, path, bound)
        facts = self.facts[path]
        got = self.links.of(ident) or {}
        node = self._node(path, d)
        text = d.doc or ""
        p = {
            "passport": 1,
            "kind": d.kind,
            "id": ident,
            "path": path,
            "line": d.line,
            "sha": self.sha,
            "scanner": SCANNER,
            "purpose": {"text": text, **self._called_from(got), "declared_at": None},
            "interface": self._interface(path, d, node, facts),
            "links": self._links(d, got),
            "runtime": self._runtime(path, d, facts),
            "checks": {"findings": None, "tests": self.ranked(got.get("tests", []))},  # v1: node реестра ≠ id
            "status": {
                "tier": facts.tier,
                "doc_missing": text == "",
                "dynamic": got.get("call_sites_unresolved", 0) + self._dynamic(path, d, facts),
                "stale": None,  # ниже: `_stale` читает уже собранные разделы
                "frozen": self._frozen(path, facts, self.rows()),
            },
        }
        p["status"]["stale"] = self._stale(p)
        return p

    def _binding_passport(self, ident: str, path: str, bound: _Binding) -> dict:
        """Паспорт привязки (Task 4.6a, `kind: "binding"`): ключи и порядок — как у символа, значения без источника —
        `null` (таблица «Паспорт привязки» модуля). `used_by` — из индекса `Links` у привязки модуля, `[]` у привязки
        класса (имя члена не наследует импорт одноимённого модульного)."""
        facts = self.facts[path]
        rows = self.rows()
        qualname = bound.qualname
        used_by = [] if "." in qualname else self.links.imports_of(path, qualname)
        p = {
            "passport": 1,
            "kind": "binding",
            "id": ident,
            "path": path,
            "line": bound.line,
            "sha": self.sha,
            "scanner": SCANNER,
            "purpose": {"text": None, "called_from": None, "called_from_more": 0, "declared_at": None},
            "interface": {
                "layer": module_of(path, rows),
                "all": self._all_chain(path, qualname, facts, rows),
                "signature": bound.signature,
                "members": None,
            },
            "links": {
                "used_by": used_by,
                "uses": None,
                "subclasses": None,
                "call_sites": None,
                "call_sites_unresolved": None,
                "bases": None,
                "structural": None,
                "call_sites_by_name": None,
            },
            "runtime": {"processes": None, "threads": None, "commands": None, "io": None},
            "checks": {"findings": None, "tests": None},
            "status": {
                "tier": facts.tier,
                "doc_missing": None,
                "dynamic": None,
                "stale": None,  # ниже: `_stale` читает уже собранные разделы
                "frozen": self._frozen(path, facts, rows),
            },
        }
        p["status"]["stale"] = self._stale(p)
        return p

    def _node(self, path: str, d: DefFact) -> ast.AST | None:
        try:
            return _find_node(ast.parse(self.tree.read(path).decode("utf-8").removeprefix("﻿")), d.qualname, d.line)
        except Exception:  # noqa: BLE001 — факты уже есть, без узла сигнатура берётся из DefFact
            return None

    def _called_from(self, got: dict) -> dict:
        best: dict[tuple[str, str], tuple[int, str, int]] = {}
        for entry in got.get("call_sites", []):
            if entry["scope"] != "prod" or entry["enclosing"] == "<module>":
                continue
            path, line = _split(entry["where"])
            key = (path, entry["enclosing"])
            order = (-self.rank(*key), path, line)
            best[key] = min(best.get(key, order), order)
        if not best:
            return {"called_from": [], "called_from_more": 0}
        (path, enclosing), _ = min(best.items(), key=lambda kv: kv[1])
        caller = self.find(path, enclosing)
        text = (caller.doc if caller is not None else None) or ""
        return {"called_from": [{"qualname": enclosing, "text": text}], "called_from_more": len(best) - 1}

    def _interface(self, path: str, d: DefFact, node: ast.AST | None, facts: FileFacts) -> dict:
        rows = self.rows()
        signature, members = "", None
        if d.kind != "class":
            signature = _tail(node, _drop_first(node, d.kind == "method")) if isinstance(node, _FUNCS) else d.signature
        else:
            members = []
            if isinstance(node, ast.ClassDef):
                for m in _methods(node):
                    sig = _tail(m, _drop_first(m, True))
                    members.append({"name": m.name, "signature": sig, "where": f"{path}:{m.lineno}"})
                # Task 4.6b: публичных методов нет — члены класса его поля (порядок `_body_bindings` — порядок
                # операторов); имя метода или вложенного класса (`DefFact`) полем не считается
                if not members:
                    members = [
                        {"name": name, "signature": sig, "where": f"{path}:{line}"}
                        for name, (line, sig) in _body_bindings(node.body).items()
                        if self.find(path, f"{d.qualname}.{name}") is None
                    ]
        return {
            "layer": module_of(path, rows),
            "all": self._all_chain(path, d.qualname, facts, rows),
            "signature": signature,
            "members": members,
        }

    def _all_chain(self, path: str, qualname: str, facts: FileFacts, rows: list[dict]) -> list[str] | None:
        links = self._init_chain(path, rows)
        # `__all__` у файла символа или у звена цепочки; звено с `error` даёт `all=None` и идёт дальше, как до 4.2b-1
        seen_all = facts.all is not None or any(pkg.all is not None for _, pkg in links)
        name = qualname.split(".")[0]
        chain = [init for init, pkg in links if pkg.all is not None and name in pkg.all]
        if facts.all is not None and name in facts.all and path not in chain:  # В14: файл символа — первое звено
            chain.insert(0, path)  # (`path` в `chain` — символ в самом `__init__.py`, он уже звено)
        return chain if seen_all else None

    def _init_chain(self, path: str, rows: list[dict]) -> list[tuple[str, FileFacts]]:
        """Звенья-пакеты от каталога файла `path` вверх: `(путь __init__.py, его факты)`, от ближайшего к юниту.

        Общий обход для `interface.all` и `status.frozen` (выносится из `_all_chain`, Task 4.2b-1).
        Pre: `path` — путь файла ревизии (posix, от корня); `rows` — `self.rows()` (границы юнитов).
        Post: граница юнита — совпавший элемент `paths` с наибольшей длиной (как `modules.resolve`); юнит с `paths`
            без `/` (файл целиком) — `stop=""`, обход идёт до корня. Обход останавливается на первой дыре (каталог без
            `__init__.py` в фактах), после звена на границе юнита и при выходе из юнита. Звено с `error`/`v2_error`
            входит в результат как есть (пропуск — решение вызывающего). Результат — список, пустой, если ближайшего
            `__init__.py` нет. Не читает рабочее дерево, не бросает.
        """
        stop = ""
        best = 0
        # граница юнита — совпавший элемент `paths`: копия цикла `modules.resolve` (modules.py:113-118);
        # правка resolve -> править здесь
        for row in rows:
            for element in row["paths"]:
                hit = path.startswith(element) if element.endswith("/") else path == element
                if hit and len(element) > best:
                    best, stop = len(element), element.rstrip("/") if element.endswith("/") else ""
        links: list[tuple[str, FileFacts]] = []
        folder = path.rpartition("/")[0]
        while True:
            init = f"{folder}/__init__.py" if folder else "__init__.py"
            pkg = self.facts.get(init)
            if pkg is None:
                break
            links.append((init, pkg))
            if not folder or (stop and folder == stop):
                break
            folder = folder.rpartition("/")[0]
            if stop and not (folder == stop or folder.startswith(stop + "/")):
                break
        return links

    def _stale(self, passport: dict) -> list[str] | None:
        """`status.stale` собранного паспорта (раздел `status` в нём ещё не нужен).

        Pre: `passport` — `dict` с конвертом и пятью разделами до `status` (`path`, `links`, `runtime`, `checks`
            уже построены); `self.sha` — полный sha ревизии.
        Post: `None`, если `self.sha` != `resolve(self.root, "HEAD")`, HEAD не разрешается или `git diff` упал
            (`AtlasError`/`OSError` ловятся только вокруг `resolve(root, "HEAD")` и `git_z`); иначе список путей
            паспорта, изменённых в рабочем дереве относительно `self.sha`, в порядке путей паспорта, без повторов;
            `[]` — чисто. Вызов `git`: при <= 100 путях — `git --no-optional-locks --literal-pathspecs diff -z
            --name-only --no-renames <sha> -- <пути>` (pathspec); при > 100 путях — тот же `git diff` БЕЗ pathspec и
            пересечение со списком путей в Python (`map process_module`: 359 путей, ~29 КБ argv). Пути:
            `path` (у `kind: unit` — нет: это каталог `paths[0]`), путь из каждого `where` (`links.*`, `checks.tests`,
            `runtime.*`, `interface.members`, `links.bases`), путь из `links.structural.twins` (часть до `::`).
            `where: null` пропускается.
            Один вызов `git` на паспорт в обоих случаях; репозиторий не меняется (кроме stat-кэша `.git/index`:
            `--no-optional-locks` на `git diff` не действует, `index.lock` держится до ~0,5 с при устаревшем
            stat-кэше, ~15 мс иначе).
            Правка режима файла без правки текста тоже попадает в `stale` (поведение git).
        """
        try:
            head = resolve(self.root, "HEAD")
        except AtlasError:  # HEAD не разрешается (пустой репозиторий, битый HEAD): не искали
            return None
        if head != self.sha:  # `--ref` на чужой ревизии: рабочее дерево к ней не относится
            return None
        paths = _passport_paths(passport)
        args = ("--no-optional-locks", "--literal-pathspecs", "diff", "-z", "--name-only", "--no-renames", self.sha)
        spec = ("--", *paths) if len(paths) <= _PATHSPEC_MAX else ()  # иначе весь diff и пересечение ниже
        try:
            changed = set(git_z(self.root, *args, *spec))
        except (AtlasError, OSError):  # `git diff` упал (bare-клон) или argv слишком длинный: не искали
            return None
        return [p for p in paths if p in changed]

    def _frozen(self, path: str, facts: FileFacts, rows: list[dict]) -> list[dict]:
        """`status.frozen`: шапки `FREEZE` файла символа, затем `__init__.py` цепочки.

        Pre: `path`, `facts` — файл символа; `rows` — `self.rows()`.
        Post: список `{"date": str, "text": str, "where": "путь:строка"}`: сначала шапки `facts.freeze` (порядок
            строк файла), затем шапки каждого звена `_init_chain(path, rows)` без `error`, от ближайшего к юниту.
            Без повторов (символ в самом `__init__.py` — шапки файла не дублируются звеном). `[]` — искали, нет.
            `v2_error` звена не влияет. Класс и метод получают цепочку своего файла. Не бросает.
        """
        heads = [{"date": date, "text": text, "where": f"{path}:{line}"} for date, text, line in facts.freeze]
        for init, pkg in self._init_chain(path, rows):
            if init == path or pkg.error is not None:  # символ в самом `__init__.py`; звено не разобрано
                continue
            heads += [{"date": date, "text": text, "where": f"{init}:{line}"} for date, text, line in pkg.freeze]
        return heads

    def _links(self, d: DefFact, got: dict) -> dict:
        structural = None
        if d.kind == "class":
            raw = got.get("structural")
            structural = {"required": [], "twins": [], "note": TOO_GENERIC} if raw is None else {**raw, "note": None}
        return {
            "used_by": got.get("used_by", []),  # rank у импорта всегда 0 (DESIGN 3): ключа нет
            "uses": None,
            "subclasses": self.ranked(got.get("subclasses", [])),
            "call_sites": self.ranked(got.get("call_sites", [])),
            "call_sites_unresolved": got.get("call_sites_unresolved", 0),
            "bases": got.get("bases") if d.kind == "class" else None,
            "structural": structural,
            "call_sites_by_name": self._by_name(d, got),
        }

    def _by_name(self, d: DefFact, got: dict) -> dict | None:
        """`links.call_sites_by_name`: у метода `{count, items}` (`items` с `rank`, None при N > 10), иначе None."""
        raw = got.get("call_sites_by_name")
        if d.kind != "method" or raw is None:
            return None
        items = raw["items"]
        return {"count": raw["count"], "items": None if items is None else self.ranked(items)}

    @staticmethod
    def _inside(enclosing: str, qualname: str) -> bool:
        return enclosing == qualname or enclosing.startswith(qualname + ".")

    def _scopes(self, path: str, d: DefFact) -> set[str]:
        """qualname объявлений `def command_specs` в теле символа (с вложенными)."""
        prefix = d.qualname + "."
        return {
            x.qualname
            for x in self.defs(path)
            if x.qualname.startswith(prefix) and x.qualname.rsplit(".", 1)[-1] == "command_specs"
        }

    def _dynamic(self, path: str, d: DefFact, facts: FileFacts) -> int:
        scopes = self._scopes(path, d)
        return sum(1 for _, _, form, sc in facts.command_specs or () if form == "dynamic" and sc in scopes)

    def _runtime(self, path: str, d: DefFact, facts: FileFacts) -> dict:
        scopes = self._scopes(path, d)
        commands = None
        if scopes:
            commands = [
                {"name": name, "where": f"{path}:{line}", "how": "declared"}
                for name, line, form, sc in facts.command_specs or ()
                if sc in scopes and form != "dynamic"  # dynamic адреса имени нет: только счёт в `status.dynamic`
            ]
        q = d.qualname
        return {
            "processes": None,
            "threads": [
                {"pattern": t.pattern, "daemon": t.daemon, "where": f"{path}:{t.line}"}
                for t in facts.thread_sites
                if self._inside(t.enclosing, q)
            ],
            "commands": commands,
            "io": [
                {"op": i.op, "path": i.path, "where": f"{path}:{i.line}"}
                for i in facts.io
                if self._inside(i.enclosing, q)
            ],
        }

    # ------------------------------------------------------------------ map: юнит и файл (Task 4.2b-2)

    def map(self, target: str) -> dict:
        """Паспорт цели `build_map` (правила — в его докстринге). Raises: `AtlasError("not found")`."""
        if target.replace("\\", "/").endswith("/"):  # каталог (`u/`) — не цель, `normpath` слэш бы снял (пин 4.2b-2)
            raise AtlasError("not found")
        t = norm_path(target, self.root)
        rows = self.rows()
        row = next((r for r in rows if r["id"] == t), None)
        if row is not None:
            return self._map_unit(row, rows)
        if t.endswith(".py") and t in self.facts:  # `facts` — уже без `exclude`
            return self._map_file(t, rows)
        raise AtlasError("not found")

    def _imports_into(self, targets: set[str], skip) -> list[tuple[str, int, tuple[str, ...]]]:
        """Операторы импорта prod-файлов с хотя бы одной целью в `targets`: `(путь, строка, цели из targets)`.

        Оператор — запись `ImportRec` (`from u.a import A, B` — одна запись; `import a, b` — две, по имени),
        `ImportIndex.resolve(...).status == "internal"`; цель через `__init__.py` — сам `__init__.py` (реэкспорт
        дальше не разворачивается). Импортёр с `skip(путь)` пропускается (проверка — только у файлов с попаданием).
        """
        index = ImportIndex(self.facts)
        out: list[tuple[str, int, tuple[str, ...]]] = []
        for path, facts in self.facts.items():
            if _scope(path) != "prod":
                continue
            found = []
            for rec in facts.imports:
                resolved = index.resolve(path, rec)
                if resolved.status != "internal":
                    continue
                hit = tuple(dict.fromkeys(p for p, _ in resolved.targets if p in targets))
                if hit:
                    found.append((path, rec.line, hit))
            if found and not skip(path):
                out += found
        return out

    @staticmethod
    def _used_by(stmts: list[tuple[str, int, tuple[str, ...]]], unit_of) -> list[dict]:
        """Группы по юниту импортёра: `count` — операторов, `where` — min по (путь, строка); порядок `(-count, name)`.
        Pre: `unit_of(путь)` — id юнита импортёра (`modules.resolve`)."""
        groups: dict[str, list[tuple[str, int]]] = {}
        for path, line, _ in stmts:
            groups.setdefault(unit_of(path), []).append((path, line))
        out = [
            {"name": name, "where": "{}:{}".format(*min(places)), "how": "import", "count": len(places)}
            for name, places in groups.items()
        ]
        return sorted(out, key=lambda e: (-e["count"], e["name"]))

    @staticmethod
    def _top(facts: FileFacts) -> list[str] | None:
        """`top` члена юнита: верхний уровень class/def без `_`, порядок исходника; `None` — файл не разобран."""
        if facts.error is not None or facts.v2_error is not None:
            return None
        names = (d.qualname for d in facts.defs if d.kind != "method" and "." not in d.qualname)
        return list(dict.fromkeys(n for n in names if not n.startswith("_")))

    def _map_runtime(self, paths: list[str]) -> tuple[dict, int]:
        """`runtime` по файлам `paths` (записи по `(путь, строка)`) и сумма `command_specs_dynamic`.

        Файлы с `error`/`v2_error` записей не дают (у них полей v2 нет)."""
        threads: list[tuple[str, int, dict]] = []
        io: list[tuple[str, int, dict]] = []
        commands: list[tuple[str, int, dict]] = []
        dynamic = 0
        for path in paths:
            facts = self.facts[path]
            for t in facts.thread_sites:
                threads.append((path, t.line, {"pattern": t.pattern, "daemon": t.daemon, "where": f"{path}:{t.line}"}))
            for i in facts.io:
                io.append((path, i.line, {"op": i.op, "path": i.path, "where": f"{path}:{i.line}"}))
            for name, line, form, _ in facts.command_specs or ():
                if form != "dynamic":  # dynamic адреса имени нет: только счёт в `status.dynamic`
                    commands.append((path, line, {"name": name, "where": f"{path}:{line}", "how": "declared"}))
            dynamic += facts.command_specs_dynamic
        ordered = lambda xs: [e for _, _, e in sorted(xs, key=lambda x: (x[0], x[1]))]  # noqa: E731
        runtime = {"processes": None, "threads": ordered(threads), "commands": ordered(commands), "io": ordered(io)}
        return runtime, dynamic

    def _map_unit(self, row: dict, rows: list[dict]) -> dict:
        uid = row["id"]
        heads = tuple(row["paths"])

        def under(path: str) -> bool:  # префильтр до `resolve`: тот же матч элемента `paths`, что в `modules.resolve`
            return any(path.startswith(e) if e.endswith("/") else path == e for e in heads)

        files = sorted(p for p in self.facts if under(p) and module_of(p, rows) == uid)
        own = set(files)
        stmts = self._imports_into(own, own.__contains__)
        ops: dict[str, int] = {}
        for _, _, hit in stmts:
            for target in hit:
                ops[target] = ops.get(target, 0) + 1
        prod = sorted((p for p in files if _scope(p) == "prod"), key=lambda p: (-ops.get(p, 0), p))
        members = [
            {
                "name": p,
                "signature": None,
                "where": f"{p}:1",
                "top": self._top(self.facts[p]),
                "doc": None if self.facts[p].error is not None else self.facts[p].doc or "",
            }
            for p in prod
        ]
        tests = [
            {"name": p, "where": f"{p}:1", "count": len(self.facts[p].test_defs)}
            for p in files
            if _scope(p) == "test" and self.facts[p].test_defs
        ]
        tests.sort(key=lambda e: (-e["count"], e["name"]))
        init = _unit_init(heads[0]) if heads else None
        pkg = self.facts.get(init) if init is not None else None
        runtime, dynamic = self._map_runtime(prod)
        docs = row.get("docs") or []
        p = {
            "passport": 1,
            "kind": "unit",
            "id": uid,
            "path": heads[0] if heads else "",
            "line": None,
            "sha": self.sha,
            "scanner": SCANNER,
            "purpose": {
                "text": row.get("purpose") or "",
                "called_from": None,
                "called_from_more": 0,
                "declared_at": None,
            },
            "interface": {
                "layer": uid,
                "all": list(pkg.all) if pkg is not None and pkg.all is not None else None,
                "signature": None,
                "members": members,
            },
            "links": self._map_links(self._used_by(stmts, lambda path: module_of(path, rows))),
            "runtime": runtime,
            "checks": {"findings": None, "tests": tests},
            "status": {
                "tier": row.get("tier"),
                "doc_missing": not any(str(d).rsplit("/", 1)[-1] == "README.md" for d in docs),
                "dynamic": dynamic,
                "stale": None,
                "frozen": (
                    [{"date": date, "text": text, "where": f"{init}:{line}"} for date, text, line in pkg.freeze]
                    if pkg is not None and pkg.error is None
                    else []
                ),
            },
        }
        p["status"]["stale"] = self._stale(p)
        return p

    @staticmethod
    def _map_links(used_by: list[dict]) -> dict:
        return {
            "used_by": used_by,
            "uses": None,
            "subclasses": None,
            "call_sites": None,
            "call_sites_unresolved": None,
            "bases": None,
            "structural": None,
        }

    def _file_members(self, path: str, facts: FileFacts) -> list[dict]:
        """Форма B: верхний уровень class/def (имена на `_` тоже), сигнатура — `reference._sig` без имени.

        Task 4.6b: плюс привязки модуля (имена не из `defs` верхнего уровня), всё по строке.
        """
        try:
            tree: ast.AST | None = ast.parse(self.tree.read(path).decode("utf-8").removeprefix("﻿"))
        except Exception:  # noqa: BLE001 — факты уже есть; без дерева сигнатура берётся из DefFact
            tree = None
        out = []
        for d in facts.defs:
            if d.kind == "method" or "." in d.qualname:
                continue
            node = _find_node(tree, d.qualname, d.line) if tree is not None else None
            sig = "" if d.kind == "class" else _tail(node, False) if isinstance(node, _FUNCS) else d.signature
            out.append({"name": d.qualname, "signature": sig, "where": f"{path}:{d.line}"})
        if isinstance(tree, ast.Module):  # Task 4.6b: привязки модуля; имя из `defs` верхнего уровня — не привязка
            top = {d.qualname for d in facts.defs if "." not in d.qualname}
            bound = [
                {"name": name, "signature": sig, "where": f"{path}:{line}"}
                for name, (line, sig) in _body_bindings(tree.body).items()
                if name not in top
            ]
            if bound:  # без привязок порядок и байты прежние
                out = sorted([*out, *bound], key=lambda m: _split(m["where"])[1])  # устойчиво: форма B — по строке
        return out

    def _map_file(self, path: str, rows: list[dict]) -> dict:
        facts = self.facts[path]
        layer = module_of(path, rows)
        broken = facts.error is not None  # A1 не разобран: ни докстринга, ни шапок, ни v2
        no_v2 = broken or facts.v2_error is not None
        units: dict[str, str] = {}

        def unit_of(importer: str) -> str:
            if importer not in units:
                units[importer] = module_of(importer, rows)
            return units[importer]

        # исключены сам файл и `__init__.py` его цепочки пакетов (реэкспорт); импортёры своего юнита — группой юнита
        hidden = {path, *(init for init, _ in self._init_chain(path, rows))}
        skip = hidden.__contains__
        stmts = self._imports_into({path}, skip)
        text = None if broken else facts.doc or ""
        if no_v2:
            runtime, dynamic = {"processes": None, "threads": None, "commands": None, "io": None}, None
        else:
            runtime, dynamic = self._map_runtime([path])
        p = {
            "passport": 1,
            "kind": "file",
            "id": path,
            "path": path,
            "line": None,
            "sha": self.sha,
            "scanner": SCANNER,
            "purpose": {"text": text, "called_from": None, "called_from_more": 0, "declared_at": None},
            "interface": {
                "layer": layer,
                "all": None,  # у файла не искали (OUT OF SCOPE 4.2b-2)
                "signature": None,
                "members": None if no_v2 else self._file_members(path, facts),
            },
            "links": self._map_links(self._used_by(stmts, unit_of)),
            "runtime": runtime,
            "checks": {"findings": None, "tests": None},
            "status": {
                "tier": facts.tier,
                "doc_missing": None if text is None else text == "",
                "dynamic": dynamic,
                "stale": None,
                "frozen": self._frozen(path, facts, rows),
            },
        }
        p["status"]["stale"] = self._stale(p)
        return p


# --------------------------------------------------------------------------- текст


def _order(entry: dict) -> tuple[int, int, str, int]:
    """Ключ порядка записей текста: `(группа, -rank, path, line)`; группа 0 — продукт вне `_SIDE_DIRS`, 1 — продукт в
    них, 2 — тесты. JSON порядок `links.py` (`(where, line)`) не меняет."""
    where = entry.get("where")
    path, line = _split(where) if where else ("", 0)
    group = 2 if entry.get("scope") == "test" else 1 if path.startswith(_SIDE_DIRS) else 0
    return group, -entry.get("rank", 0), path, line


def _link_row(entry: dict) -> str:
    name = entry.get("name", entry.get("enclosing", ""))
    if entry.get("where") is None:
        return f"{name} — строка не указана"
    return f"{name} — {entry['where']} ({entry['how']})"


def _member_row(m: dict) -> str:
    """`  имя(сигнатура)  :строка` члена класса (без отступа): `name(x: int) -> int  :7`, `async run() -> None  :9`."""
    sig = m["signature"]
    prefix, sig = ("async ", sig.removeprefix("async ")) if sig.startswith("async ") else ("", sig)
    return f"{prefix}{m['name']}{' ' + sig if sig.startswith('->') else sig}  :{_split(m['where'])[1]}"


def _is_binding_sig(sig: str) -> bool:
    """`signature` привязки (форма `_binding_sig`), не функции (`(`/`async `/`->`) и не класса (`""`)."""
    return sig.startswith((": ", "= ", "type = ", "type["))


def _field_row(m: dict) -> str:
    """Поле класса или привязка модуля (без отступа): `l1: float = 325.0  :101`, `READY = 'ready'  :25`,
    `Alias type = int | str  :4` (`signature` с `:` клеится к имени, прочие — через пробел)."""
    sig = m["signature"]
    return f"{m['name']}{sig if sig.startswith(':') else ' ' + sig}  :{_split(m['where'])[1]}"


def _value(value: object) -> str:
    if value is None:
        return _NOT_SEARCHED
    if value == [] or value == 0 or value == "":
        return _EMPTY
    return str(value)


def _alloc(
    sizes: dict[str, int],
    avail: int,
    names: tuple[str, ...] = SHOW_ALL_SECTIONS,
    floors: dict[str, int] | None = None,
) -> dict[str, int]:
    """Строк записей на раздел: поровну, излишек короткого — прочим; срезанный раздел платит строку пометки.

    `names` — имена среза своего `kind` (`SHOW_ALL_SECTIONS` у символа, `MAP_SHOW_ALL` у unit/file): порядок раздачи
    остатка. `floors` — минимум записей у срезанного списка (по умолчанию 1; `members` символа — `_MEMBERS_MIN`)."""
    floors = floors or {}
    give: dict[str, int] = {}
    pending = dict(sizes)
    while pending:
        share = avail // len(pending)
        small = {k: n for k, n in pending.items() if n <= share}
        if not small:
            break
        for k, n in small.items():
            give[k] = n
            avail -= n
            del pending[k]
    if pending:
        cut = [k for k in names if k in pending]
        share = max(avail // len(cut) - 1, 1)  # минус строка «показано K из N»
        extra = max(avail - (share + 1) * len(cut), 0)
        for k in cut:
            # не меньше одной записи (минимум); список из одной записи не режется — иначе «показано 0 из 1»
            give[k] = max(min(pending[k] - 1, share + (1 if extra > 0 else 0)), floors.get(k, 1))
            extra -= 1
    return give


def _render(passport: dict, budget: int, show_all: frozenset[str], full: bool) -> str:
    p = passport
    pur, itf, lnk, rt, chk, st = (p[s] for s in SECTIONS)
    fixed: list[tuple[str, object]] = []  # ("line", text) | ("list", (имя, отступ, записи, строка-функция))

    def add(text: str) -> None:
        fixed.append(("line", text))

    def add_list(name: str, indent: str, entries: list, row, keep_order: bool = False) -> None:
        ordered = (
            entries if keep_order or not (entries and isinstance(entries[0], dict)) else sorted(entries, key=_order)
        )
        fixed.append(("list", (name, indent, ordered, row)))

    add(f"== {p['id']} ==")
    add(f"{p['path']}:{p['line']}; sha {p['sha']}; scanner {p['scanner']}")
    add(f"purpose: {pur['text'] or _EMPTY}")
    if pur["called_from"]:
        caller = pur["called_from"][0]
        row = f"  зовут из: {caller['qualname']}" + (f" — {caller['text']}" if caller["text"] else "")
        add(row + (f"; ещё {pur['called_from_more']}" if pur["called_from_more"] else ""))
    else:
        add(f"  зовут из: {_EMPTY}")
    add(f"  declared_at: {_value(pur['declared_at'])}")
    add(f"interface: layer {itf['layer']}; signature {itf['signature'] or _EMPTY}")
    add(f"  all: {', '.join(itf['all']) if itf['all'] else _value(itf['all'])}")
    members = itf["members"]
    if members and _is_binding_sig(members[0]["signature"]):  # Task 4.6b: у класса без публичных методов — поля
        add(f"  members: публичных методов нет; полей {len(members)}:")
        add_list("members", "    ", members, _field_row, keep_order=True)
    elif members:
        add("  members:")
        add_list("members", "    ", members, _member_row, keep_order=True)  # порядок исходника, срез — `ещё N; --full`
    else:
        add(f"  members: {_value(members)}")
    entries = [*lnk["used_by"], *lnk["call_sites"], *lnk["subclasses"]]
    forms = [f for f in _FORMS if any(e["how"] == f for e in entries)]
    head = f"links: найдено {len(entries)}" + (f" (формы: {', '.join(forms)})" if forms else "")
    add(f"{head}; {_UNSEEN}")
    prod = sum(1 for e in entries if e["scope"] == "prod")
    add(f"  из продукта {prod}, из тестов {len(entries) - prod}")
    for name in ("used_by", "call_sites", "subclasses"):
        if lnk[name]:
            add(f"  {name}: {len(lnk[name])}")
            add_list(name, "    ", lnk[name], _link_row)
        else:
            add(f"  {name}: {_value(lnk[name])}")
    add(f"  call_sites_unresolved: {_value(lnk['call_sites_unresolved'])}")
    by_name = lnk.get("call_sites_by_name")  # Task 4.5b: только у метода; N = 0 — строки нет
    if by_name and by_name["count"]:
        method = p["id"].partition("::")[2].rsplit(".", 1)[-1]
        if by_name["items"] is None:
            add(
                f"  по имени метода (prod, без self): {by_name['count']} вызовов .{method}(...)"
                " - имя частое, адреса не печатаются"
            )
        else:
            add(f"  по имени метода, тип не проверен ({by_name['count']}):")
            add_list("call_sites_by_name", "    ", by_name["items"], _link_row)
    add(f"  uses: {_value(lnk['uses'])}")
    if lnk["bases"]:
        add("  bases:")
        for b in lnk["bases"]:
            add(f"    {_link_row(b)}")
    else:
        add(f"  bases: {_value(lnk['bases'])}")
    sx = lnk["structural"]
    if sx is None:
        add(f"  structural: {_NOT_SEARCHED}")
    else:
        add(
            f"  structural: обязательные {', '.join(sx['required']) or _EMPTY}"
            + (f"; {sx['note']}" if sx["note"] else "")
        )
        if sx["twins"]:
            add_list("structural", "    ", sx["twins"], str)
    add(f"runtime: processes {_value(rt['processes'])}")
    if rt["threads"]:
        add("  threads:")
        for t in rt["threads"]:
            daemon = "не задан" if t["daemon"] is None else str(t["daemon"])
            add(f"    {t['pattern']} (daemon: {daemon}) — {t['where']}")
    else:
        add(f"  threads: {_EMPTY} (ищет: {', '.join(THREAD_PATTERNS)})")  # Task 4.5b: «—» — не «нет потоков»
    if rt["commands"] is None:
        add(f"  commands: {_NO_SPECS} {_COMMANDS_NOTE}")
    elif rt["commands"]:
        add("  commands:")
        for c in rt["commands"]:
            add(f"    {c['name']} — {c['where']} ({c['how']})")
    else:
        add(f"  commands: {_EMPTY} {_COMMANDS_NOTE}")
    if rt["io"]:
        add("  io:")
        for i in rt["io"]:
            add(f"    {i['op']} {i['path']} — {i['where']}")
    else:
        add(f"  io: {_EMPTY} (ищет: {', '.join(IO_PATTERNS)})")
    add(f"checks: findings {_value(chk['findings'])}")
    if chk["tests"]:
        add(f"  tests: {len(chk['tests'])}")
        add_list("tests", "    ", chk["tests"], _link_row)
    else:
        add(f"  tests: {_EMPTY}")
    doc = "да" if st["doc_missing"] else "нет"
    add(f"status: tier {st['tier'] or 'нет шапки'}; doc_missing {doc}; dynamic {_value(st['dynamic'])}")
    add(f"  stale: {', '.join(st['stale']) if st['stale'] else _value(st['stale'])}")  # служебные: не режутся
    if st["frozen"]:
        for head in st["frozen"]:
            add(f"  frozen: {head['date']} {head['text']} ({head['where']})")
    else:
        add(f"  frozen: {_value(st['frozen'])}")

    show = show_all | {"call_sites_by_name"} if "call_sites" in show_all else show_all  # `--all call_sites` — оба
    return _emit(fixed, budget, show, full, _SYMBOL_CUT, _FULL_ONLY)


def _render_binding(passport: dict, budget: int, show_all: frozenset[str], full: bool) -> str:
    """Текст `kind: "binding"` (Task 4.6a; образцы — `4.6a-fixtures.md` §4). Значения печатаются только у `signature`,
    `all`, `used_by`, `tier`, `stale`, `frozen`; остальное — литерал `не искали` в коде, а не `_value(раздел)`: тест
    закрепляет текст, а `null` в JSON — отдельно. `used_by` режется как у символа (`_emit`, `--all used_by`)."""
    p = passport
    itf, lnk, st = p["interface"], p["links"], p["status"]
    fixed: list[tuple[str, object]] = []

    def add(text: str) -> None:
        fixed.append(("line", text))

    add(f"== {p['id']} ==")
    add(f"{p['path']}:{p['line']}; sha {p['sha']}; scanner {p['scanner']}")
    add(f"purpose: {_NOT_SEARCHED}")
    add(f"  зовут из: {_NOT_SEARCHED}")
    add(f"  declared_at: {_NOT_SEARCHED}")
    add(f"interface: layer {itf['layer']}; signature {itf['signature'] or _EMPTY}")
    add(f"  all: {', '.join(itf['all']) if itf['all'] else _value(itf['all'])}")
    add(f"  members: {_NOT_SEARCHED}")
    used = lnk["used_by"]
    forms = [f for f in _FORMS if any(e["how"] == f for e in used)]
    add(f"links: найдено {len(used)}" + (f" (формы: {', '.join(forms)})" if forms else "") + f"; {_UNSEEN}")
    prod = sum(1 for e in used if e["scope"] == "prod")
    add(f"  из продукта {prod}, из тестов {len(used) - prod}")
    if used:
        add(f"  used_by: {len(used)}")
        fixed.append(("list", ("used_by", "    ", sorted(used, key=_order), _link_row)))
    else:
        add(f"  used_by: {_EMPTY}")
    for name in ("call_sites", "subclasses", "call_sites_unresolved", "uses", "bases", "structural"):
        add(f"  {name}: {_NOT_SEARCHED}")
    add(f"runtime: processes {_NOT_SEARCHED}")
    for name in ("threads", "commands", "io"):
        add(f"  {name}: {_NOT_SEARCHED}")
    add(f"checks: findings {_NOT_SEARCHED}")
    add(f"  tests: {_NOT_SEARCHED}")
    add(f"status: tier {st['tier'] or 'нет шапки'}; doc_missing {_NOT_SEARCHED}; dynamic {_NOT_SEARCHED}")
    add(f"  stale: {', '.join(st['stale']) if st['stale'] else _value(st['stale'])}")
    if st["frozen"]:
        for head in st["frozen"]:
            add(f"  frozen: {head['date']} {head['text']} ({head['where']})")
    else:
        add(f"  frozen: {_value(st['frozen'])}")
    return _emit(fixed, budget, show_all, full, _SYMBOL_CUT, _FULL_ONLY)


def _emit(
    fixed: list[tuple[str, object]],
    budget: int,
    show_all: frozenset[str],
    full: bool,
    names: tuple,
    full_only: dict[str, int] | None = None,
) -> str:
    """Строки и списки (`_render`, `_render_map`) -> текст по бюджету: раздел из `show_all` не режется, но его записи
    входят в расход бюджета; `full` — без среза; остаток делит `_alloc` (имена среза — `names`). `full_only` — списки
    без своего `--all` (`_FULL_ONLY`): минимум записей и пометка `ещё N; --full` вместо `показано K из N`."""
    full_only = full_only or {}
    lists = {v[0]: v for k, v in fixed if k == "list"}
    free = {n: len(v[2]) for n, v in lists.items() if not full and n not in show_all}
    used = sum(1 for k, _ in fixed if k == "line") + sum(len(v[2]) for n, v in lists.items() if n not in free)
    give = _alloc(free, budget - used, names, full_only)
    out: list[str] = []
    for kind, item in fixed:
        if kind == "line":
            out.append(item)  # type: ignore[arg-type]
            continue
        name, indent, rows, row, *prio = item  # type: ignore[misc]
        keep = give.get(name, len(rows))
        if prio and keep < len(rows):  # Task 4.6b: остаются `keep` записей с меньшим `prio`, печать — по порядку
            kept = sorted(sorted(range(len(rows)), key=lambda i: (prio[0][i], i))[:keep])
            out += [f"{indent}{row(rows[i])}" for i in kept]
        else:
            out += [f"{indent}{row(r)}" for r in rows[:keep]]
        if keep < len(rows):
            mark = (
                f"ещё {len(rows) - keep}; --full"
                if name in full_only
                else f"показано {keep} из {len(rows)}; все: --all {_ALL_FLAG.get(name, name)}"
            )
            out.append(f"{indent}{mark}")
    return "\n".join(out)


def _unit_init(head: str) -> str | None:
    """`__init__.py` юнита по `paths[0]`: каталог (`a/`) -> `a/__init__.py`; сам `__init__.py` -> он же; иначе (другой
    файл: `.py`, `.md`) — `None`, искать негде. Источник `interface.all` и `status.frozen` юнита."""
    if head.endswith("/"):
        return head + "__init__.py"
    if head == "__init__.py" or head.endswith("/__init__.py"):
        return head
    return None


def _unit_member_row(m: dict) -> str:
    """`u/a.py — Модуль a.  (A, B)`: `doc` или `—`; `top` до 6 имён, остаток `, +N`; пустой `top` — без скобок."""
    row = f"{m['name']} — {m.get('doc') or _EMPTY}"
    top = m["top"]
    if top is None:
        return f"{row}  ({_NOT_SEARCHED})"
    if not top:
        return row
    rest = len(top) - _TOP_SHOWN
    return f"{row}  ({', '.join(top[:_TOP_SHOWN])}{f', +{rest}' if rest > 0 else ''})"


def _file_member_row(m: dict) -> str:
    """`class A  :4`, `def f(x: int) -> int  :7`, `async def g() -> None  :9` (вид — по `signature`: `""` у класса)."""
    sig, line = m["signature"], _split(m["where"])[1]
    if _is_binding_sig(sig):  # Task 4.6b: привязка модуля
        return _field_row(m)
    if not sig:
        return f"class {m['name']}  :{line}"
    if sig.startswith("async "):
        return f"async def {m['name']}{sig.removeprefix('async ')}  :{line}"
    return f"def {m['name']}{sig}  :{line}"


def _render_map(passport: dict, budget: int, show_all: frozenset[str], full: bool) -> str:
    """Текст `kind` unit/file (образец — `map-form.md` п. 3): печатаются только ключи, у которых у `map` есть
    источник; ключи, всегда `null` у `map`, — только в JSON. Срез — `_emit` с именами `MAP_SHOW_ALL`.
    Post: строк <= max(`budget`, минимум); минимум включает все записи разделов из `show_all` (как у `render_text`)."""
    p = passport
    pur, itf, lnk, rt, chk, st = (p[s] for s in SECTIONS)
    unit = p["kind"] == "unit"
    fixed: list[tuple[str, object]] = []

    def add(text: str) -> None:
        fixed.append(("line", text))

    def add_list(name: str, entries: list, row, prio: list[int] | None = None) -> None:
        # порядок записей — как в паспорте; `prio` (Task 4.6b) — приоритет при срезе, меньше — держится первым
        fixed.append(("list", (name, "    ", entries, row, *([prio] if prio else []))))

    add(f"== {p['kind']} {p['id']} ==")
    add(f"{p['path']}; sha {p['sha']}; scanner {p['scanner']}")
    add(f"purpose: {_value(pur['text'])}")
    add(f"interface: layer {itf['layer']}")
    all_ = itf["all"]
    # у юнита `null` — `__init__.py` или его `__all__` нет (искали); у файла `null` — не искали (сознательно)
    # `null`: у юнита с `__init__.py`-кандидатом (каталог или сам `__init__.py`) — искали, нет (`—`); у юнита без
    # кандидата (`paths[0]` — другой файл) и у файла — не искали
    searched = unit and _unit_init(p["path"]) is not None
    add(f"  all: {', '.join(all_) if all_ else (_EMPTY if searched or all_ == [] else _NOT_SEARCHED)}")
    if itf["members"]:
        add("  members:")
        if unit:
            add_list("members", itf["members"], _unit_member_row)
        else:  # class/def файла держатся первыми, привязки модуля заполняют остаток
            add_list(
                "members",
                itf["members"],
                _file_member_row,
                [int(_is_binding_sig(m["signature"])) for m in itf["members"]],
            )
    else:
        add(f"  members: {_value(itf['members'])}")
    used = lnk["used_by"]
    found = sum(e["count"] for e in used)
    add(f"links: найдено {found}" + (" (формы: import)" if used else "") + f"; {_UNSEEN}")
    if used:
        add(f"  used_by: {len(used)}")
        add_list("used_by", used, lambda e: f"{e['name']} — {e['where']} ({e['how']}) ×{e['count']}")
    else:
        add(f"  used_by: {_EMPTY}")
    add("runtime:")
    rows = {
        "threads": lambda t: (
            f"{t['pattern']} (daemon: {'не задан' if t['daemon'] is None else t['daemon']}) — {t['where']}"
        ),
        "commands": lambda c: f"{c['name']} — {c['where']} ({c['how']})",
        "io": lambda i: f"{i['op']} {i['path']} — {i['where']}",
    }
    for name, row in rows.items():
        entries = rt[name]
        if not entries:
            add(f"  {name}: {_value(entries)}")
            continue
        add(f"  {name}: {len(entries)}")
        if name == "commands":  # не режется (map-form п. 4)
            for entry in entries:
                add(f"    {row(entry)}")
        else:
            add_list(name, entries, row)
    add("checks:")
    if chk["tests"]:
        add(f"  tests: {len(chk['tests'])}")
        add_list("tests", chk["tests"], lambda e: f"{e['name']} — {e['where']} ×{e['count']}")
    else:
        add(f"  tests: {_value(chk['tests'])}")
    missing = st["doc_missing"]
    doc = _NOT_SEARCHED if missing is None else "да" if missing else "нет"
    if unit:
        tier = st["tier"] or _EMPTY
    else:  # файл с `error`: шапки не прочитаны — не искали
        tier = st["tier"] or (_NOT_SEARCHED if pur["text"] is None else "нет шапки")
    add(f"status: tier {tier}; doc_missing {doc}; dynamic {_value(st['dynamic'])}")
    stale = st["stale"]
    if stale:
        rest = len(stale) - _STALE_SHOWN
        add(f"  stale: {', '.join(stale[:_STALE_SHOWN])}" + (f"; ещё {rest}" if rest > 0 else ""))
    else:
        add(f"  stale: {_value(stale)}")
    if st["frozen"]:
        for head in st["frozen"]:
            add(f"  frozen: {head['date']} {head['text']} ({head['where']})")
    else:
        add(f"  frozen: {_value(st['frozen'])}")
    return _emit(fixed, budget, show_all, full, MAP_SHOW_ALL)


def build_passport(root: Path, ref: str, ident: str, *, exclude: tuple[str, ...] = ()) -> dict:
    """Паспорт одного символа (структура — в докстринге модуля).

    Pre: `ident` — полный идентификатор `путь::qualname` символа, определённого в ревизии `ref`, либо привязки имени
        (`путь::ИМЯ`, `путь::Cls.ИМЯ`; Task 4.6a, правила — «Паспорт привязки» модуля); голое имя разбирает
        `resolve_ident` и привязку не находит; `root` и `ref` — см. модуль.
    Post: JSON-совместимый `dict`: конверт (`passport`, `kind`, `id`, `path`, `line`, `sha`, `scanner`) и шесть
        разделов (`purpose`, `interface`, `links`, `runtime`, `checks`, `status`) — все ключи всегда, `null` против
        `[]`/`0` по таблицам модуля. `json.dumps(result)` проходит без `default=`. Не меняет репозиторий (кроме
        stat-кэша `.git/index` от `git diff` ключа `status.stale`).
    Raises: `tree.AtlasError`, если `ident` не найден в ревизии или файл символа в `exclude`; `ref` не разрешается в
        ревизию. Паспорт не бросает на файлах с `error`/`v2_error` — их символы не находятся.
    """
    return _Ctx.open(root, ref, exclude).passport(ident)


def build_map(root: Path, ref: str, target: str, *, exclude: tuple[str, ...] = ()) -> dict:
    """Паспорт юнита или файла (`atlas map`; структура — в докстринге модуля, образцы — `map-form.md`).

    Pre: `target` — id строки реестра ревизии `ref` (`modules_for(Tree(root, sha))`) либо путь `.py` из
        `tree.oids()` вне `exclude`; обратная косая черта читается как `/`. Пустая строка и каталог — не цель.
        `root` и `ref` — см. модуль.
    Post: JSON-совместимый `dict`: конверт (`passport: 1`, `kind` = `unit` | `file`, `id`, `path`, `line: null`,
        `sha`, `scanner`) и шесть разделов с теми же постоянными ключами, что у символа (значения unit | file — таблица
        `Паспорт юнита и файла` модуля). Приоритет цели: id юнита реестра -> `unit`; иначе путь файла -> `file`.
        Не меняет репозиторий (кроме stat-кэша `.git/index` от `git diff` ключа `status.stale`); паспорт
        детерминирован (кроме `status.stale`). Кэш фактов `data/atlas.sqlite` пишет только промах `scan` (как
        `ref`); `build_links` не вызывается.
        Решения GREEN (закреплены `test_passport_map_hazards.py`):
        - `used_by`: оператор — запись `ImportRec` с `status == "internal"` и хотя бы одной целью в файлах цели:
          `from u.a import A, B` — один оператор (одна запись), `import u.a, u.b` — два (запись на имя). У юнита
          импортёр — prod-файл вне юнита; у файла — prod-файл, кроме самого файла и `__init__.py` его цепочки
          пакетов (`_init_chain`: реэкспорт); импортёры своего юнита идут группой с id своего юнита (ревью стадии 5
          р.2, вариант (а)). Импортёр с `error` операторов не даёт (его импорты не разобраны).
        - Запись члена юнита: `{name, signature: null, where: "путь:1", top, doc}`; `doc` — `FileFacts.doc`, `""` —
          докстринга нет.
        - Файл с `error` (A1 не разобран): цель-файл находится (`kind: file`); ключи из разбора самого файла — `null`
          («не искали»): `purpose.text`, `status.doc_missing`, `interface.members`, `runtime.threads/commands/io`,
          `status.dynamic`; `used_by`, `stale`, `frozen` (цепочка `__init__.py`) считаются как обычно. Член юнита с
          `error`: `top: null`, `doc: null`; записей в `runtime` и `dynamic` не даёт.
        - Файл с `v2_error` (A1 цел): `purpose.text`, `doc_missing`, `tier`, `frozen` — как обычно; `members`,
          `runtime.threads/commands/io`, `dynamic` — `null`. Член юнита с `v2_error`: `top: null`, `doc` — как обычно.
          Тест-файл с `error`/`v2_error` даёт `test_defs = ()` и в `checks.tests` не входит (`count > 0`).
        - Цель-файл под `exclude` — `not found`. Юнит, все файлы которого под `exclude`, находится: строка реестра
          есть, `members`, `tests`, `used_by` — `[]`.
        - `__init__.py` юнита (`_unit_init`): `paths[0]` — каталог -> `paths[0] + "__init__.py"`; `paths[0]` сам
          `__init__.py` -> он же (`framework_meta`). Источник `interface.all` и `status.frozen`. Иначе (`paths[0]` —
          другой файл: `.py`, `.md`) искать негде: `all` — `null`, в тексте `all: не искали`; `frozen` — `[]`. У
          кандидата без фактов или без `__all__` — `all: null`, в тексте `—` (искали, нет). `path` — `paths[0]` как в
          реестре.
    Raises: `tree.AtlasError("not found")` — цель не id юнита и не путь `.py` ревизии вне `exclude`: текст ровно
        `not found`, значение цели в него не входит; CLI печатает `atlas map: not found` и выходит с кодом 2. Тот же
        класс — `ref` не разрешается в ревизию (текст `resolve`). Исключение, не запись `{"error": ...}`: цель одна,
        частичного результата нет (в отличие от `passports_for`).
    """
    return _Ctx.open(root, ref, exclude, with_links=False).map(target)


def resolve_ident(root: Path, ref: str, ident: str, *, exclude: tuple[str, ...] = ()) -> list[str]:
    """Полные `путь::qualname` по `ident`.

    Pre: `ident` — `путь::qualname` либо голый `qualname` (`Cls.method`, `func`) без `::`.
    Post: с `::` — `[ident]`, если символ есть в `defs` файла ревизии или это привязка имени (Task 4.6a; файл с
        `error`/`v2_error` привязок не даёт, как и символов), иначе `[]`. Без `::` — все файлы ревизии
        (кроме `exclude`) с символом, чей `qualname` ТОЧНО равен `ident` (не подстрока, не регистр), список отсортирован
        по пути. `[]` — не найден (`not found`), больше одного — `ambiguous`; решение о тексте ошибки принимает
        вызывающий (`passports_for`). Не бросает на отсутствии символа.
    """
    return _Ctx.open(root, ref, exclude).resolve(ident)


def render_text(passport: dict, *, budget: int = 40, show_all: frozenset[str] = frozenset(), full: bool = False) -> str:
    """Текст паспорта (образцы строк — в докстринге модуля). Без завершающего перевода строки.

    Pre: `passport` — результат `build_passport` (в том числе `kind: binding`, Task 4.6a: текст `_render_binding`) или
        `build_map`; `show_all` ⊆ `SHOW_ALL_SECTIONS` (у `kind` unit/file
        — ⊆ `MAP_SHOW_ALL`: имена среза берутся по `kind` паспорта, текст unit/file — `_render_map`); `budget` — число
        строк на ЭТОТ паспорт (у каждого id независимо). Записи раздела из `show_all` входят в расход бюджета.
    Post: `full=True` — без среза (сильнее `budget` и `show_all`). Иначе строк <= max(`budget`, минимум); минимум —
        конверт, заголовки разделов, `purpose` и служебные строки, все записи разделов из `show_all`; остаток
        делится поровну между разделами-списками (без приоритета), излишек короткого уходит прочим. Порядок
        записей среза — `(группа, -rank, path, line)` (Task 4.5c: группа 0 — продукт вне `docs/`, `plans/`, `.claude/`,
        1 — продукт в них, 2 — тесты); `rank` = число вызовов из продукта (`scope: prod`) у `enclosing`
        записи (у `used_by` `enclosing` = `<module>`, `rank` = 0: порядок по `path`). Раздел из `show_all` не
        режется. Строк может быть больше `budget`: в минимум входят по одной записи на каждый срезанный список и его
        пометка; `members` класса режутся до минимума в 3 члена и пометки `ещё N; --full` (снимает только `full`:
        `--all members` у символа — `ValueError`); «<= 40 строк на экран» верно для небольших классов.
        Срезанный раздел содержит `показано K из N; все: --all <раздел>`. Паспорт не меняется.
    Raises: `ValueError`, если в `show_all` есть имя вне набора среза своего `kind` (`SHOW_ALL_SECTIONS` либо, у
        unit/file, `MAP_SHOW_ALL`).
    """
    is_map = passport.get("kind") in ("unit", "file")
    unknown = set(show_all) - set(MAP_SHOW_ALL if is_map else SHOW_ALL_SECTIONS)
    if unknown:
        raise ValueError(f"show_all: неизвестные разделы {sorted(unknown)}")
    kind = passport.get("kind")
    render = _render_map if is_map else _render_binding if kind == "binding" else _render
    return render(passport, budget, frozenset(show_all), full)


def passports_for(root: Path, ref: str, idents: list[str], *, exclude: tuple[str, ...] = ()) -> list[dict]:
    """Паспорта по списку идентификаторов, в порядке `idents`.

    Pre: `idents` — не пусто; каждый — `путь::qualname` или голое имя.
    Post: список той же длины и порядка. Разрешённый id -> результат `build_passport` (символы class/function/method и
        привязки имени `путь::ИМЯ` — Task 4.6a, `kind: binding`; цели unit/file — `build_map`; имена среза
        `render_text` берутся по `kind` паспорта). Ошибочный id ->
        запись `{"id": <как дан>, "error": "not found"}` (0 совпадений) либо `{"id": <как дан>, "error": "ambiguous",
        "candidates": [<путь::qualname>, ...]}` (больше одного; `candidates` отсортированы по пути; ключа нет у
        `not found`). Ошибка одного id не отменяет остальные: их паспорта полные. Дубли `idents` дают дубли записей.
    """
    ctx = _Ctx.open(root, ref, exclude)
    out: list[dict] = []
    for ident in idents:
        found = ctx.resolve(ident)
        if not found:
            out.append({"id": ident, "error": "not found"})
        elif len(found) > 1:
            out.append({"id": ident, "error": "ambiguous", "candidates": found})
        else:
            out.append(ctx.passport(found[0]))
    return out
