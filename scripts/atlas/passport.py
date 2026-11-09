"""Паспорт символа Д1 (Task 4.2a): один объект про класс, функцию или метод — для `ref --format`, бенча и агента.

Purpose: по ревизии git (`ref`) и идентификатору символа собирает паспорт: конверт и шесть разделов с постоянными
    ключами (JSON-совместимый `dict`), печатает его текстом по бюджету строк. Читает факты v2 (`scan`), связи
    (`build_links`), слой (`modules_for` + `modules.resolve`); ничего не пишет и не хранит. Это стадия INTERFACE:
    тела функций — `NotImplementedError`, контракт задают докстринги; тесты и реализация идут следом.
Public API: build_passport, resolve_ident, render_text, passports_for.
Stability: lite

Pre: `root` — корень git-репозитория (каталог с `.git`), `ref` — ревизия git (как у `ref` Task 4.1: `HEAD`, ветка,
    sha). Пути в паспорте — posix, от `root`. `exclude` — префиксы путей от `root` (posix): файлы под префиксом не
    читаются и в паспорт не попадают (ни как символ, ни как связь).
Post: паспорт детерминирован: та же ревизия -> тот же `dict`. Модуль не меняет репозиторий и рабочее дерево.

Правило пустого. `null` раздела или ключа = «не искали» (источника нет, значение — другая задача); `[]` и `0` =
«искали, не нашли». `where: null` у ЗАПИСИ внутри раздела = «адрес не разрешён» — это не `null` раздела. `line`
отдельно от пути в разделах не пишется: адрес — одна строка `where: "путь:строка"`. Исключение — конверт (`path`,
`line` самого символа).

Конверт (все ключи всегда):

  ключ       тип   значение
  passport   int   `1`
  kind       str   `class` | `function` | `method` (`DefFact.kind`)
  id         str   `путь::qualname`
  path       str   путь файла символа
  line       int   строка `def`/`class` (`DefFact.line`)
  sha        str   полный sha ревизии `ref` (40 символов), не имя ветки
  scanner    str   `scan.SCANNER` (версия сканера фактов)

Шесть разделов, порядок ключей верхнего уровня: `purpose`, `interface`, `links`, `runtime`, `checks`, `status`.
Ключи разделов есть у всех видов (класс, функция, метод); не относящееся к виду — `null`.
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
  all        list[str] | null         `null` — у файла символа нет литерального `__all__`. Иначе пути `__init__.py` от
                                      ближайшего пакета до юнита, где имя в `__all__` (с него и до самого юнита); `[]` —
                                      `__all__` есть, имени в цепочке нет
  signature  str                      у функции и метода — хвост строки `reference._sig` после имени (без `self`/`cls`,
                                      `-> T` после скобок): `(key: str) -> None`; у `property` — `-> T` или `""`; у
                                      класса `""`
  members    list[dict] | null        у класса: члены из `defs` 4.1, отбор как `reference._methods` (неприватные +
                                      `codemap.DUNDERS`), порядок исходника; `[]` — членов нет. У функции, метода `null`
                                      Запись `{"name": str, "signature": str, "where": "путь:строка"}`; `signature` — по
                                      правилу `signature` выше; `where` — строка `def` члена (не `null`)

`links` — связи (источник — `Links.of`, записи как в докстринге `links.py`; порядок записей — по `(where, line)`):

  ключ                    тип                     null / пусто
  used_by                 list[dict]              `[]` — импортов нет. Запись `{where, how: "import", scope,
                                                  enclosing: "<module>"}`
  uses                    null                    всегда `null` (источника в 4.1 нет)
  subclasses              list[dict]              `[]` — наследников нет. Запись `{where, how: "import" |
                                                  "same-file", scope, enclosing}`
  call_sites              list[dict]              `[]` — разрешённых вызовов нет. Запись `{where, how:
                                                  "name-call", scope, enclosing, same_file}`
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
                                   (с вложенными) содержит `def command_specs`
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
                                scope: "test", enclosing}`

`status`:

  ключ         тип           null / пусто
  tier         str | null    `FileFacts.tier` файла символа; `null` — шапки `Tier:` нет
  doc_missing  bool          `True` — у символа нет докстринга (`purpose.text == ""`)
  dynamic      int           `links.call_sites_unresolved` + число динамических `command_specs` (`command_specs_dynamic`
                             в `scan.py`, 4.2a GREEN; `0`, если `runtime.commands` — `null`)
  stale        null          ключ есть; значение — Task 4.2b
  frozen       null          ключ есть; значение — Task 4.2b

Не входит: `recipes`; `kind` выше class/function/method (unit, package, file, layer); `map`; `stale`/`frozen`
значения; кэш `links` (`build_links` пересчитывается при каждом вызове).

Текст (`render_text`). Порядок: `== <id> ==`; строки конверта (`path:line`, `sha`, `scanner`); затем шесть разделов в
порядке `purpose`, `interface`, `links`, `runtime`, `checks`, `status` — у каждого строка-заголовок `<раздел>:`.
Искали и нет (`[]`, `0`) — `<раздел>: —`; `null` — `<раздел>: не искали`. Образцы (литералы из DESIGN 2):

  - связи: `найдено 3 (формы: import, name-call); не видно: динамика, аннотации, упоминания`; формы — значения `how`
    записей раздела в порядке `links.py` (`import`, `name-call`, `same-file`, `test-body`); счёт по областям: `из
    продукта A, из тестов B` (A, B — число записей `scope: prod` и `scope: test`, отдельно, не суммой);
  - срез: `показано K из N; все: --all <раздел>`;
  - член класса: `  имя(сигнатура)  :строка`, например
    `  __call__(key: str, old_value: Any, new_value: Any) -> None  :17`;
  - связь с адресом: `<имя> — <путь:строка> (<how>)`, `<имя>` — `name` у основы, `enclosing` у прочих связей;
  - связь с `where: null`: `<имя> — строка не указана`.
Расположение образцов внутри раздела `links` (подзаголовки `used_by`, `call_sites`, ...) тестом RED не утверждается,
кроме самих образцов выше.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["build_passport", "passports_for", "render_text", "resolve_ident"]

SECTIONS = ("purpose", "interface", "links", "runtime", "checks", "status")  # порядок ключей и заголовков
SHOW_ALL_SECTIONS = ("used_by", "call_sites", "subclasses", "structural", "tests")  # допустимые значения `show_all`


def build_passport(root: Path, ref: str, ident: str, *, exclude: tuple[str, ...] = ()) -> dict:
    """Паспорт одного символа (структура — в докстринге модуля).

    Pre: `ident` — полный идентификатор `путь::qualname` символа, определённого в ревизии `ref` (голое имя разбирает
        `resolve_ident`); `root` и `ref` — см. модуль.
    Post: JSON-совместимый `dict`: конверт (`passport`, `kind`, `id`, `path`, `line`, `sha`, `scanner`) и шесть
        разделов (`purpose`, `interface`, `links`, `runtime`, `checks`, `status`) — все ключи всегда, `null` против
        `[]`/`0` по таблицам модуля. `json.dumps(result)` проходит без `default=`. Не меняет репозиторий.
    Raises: `tree.AtlasError`, если `ident` не найден в ревизии или файл символа в `exclude`; `ref` не разрешается в
        ревизию. Паспорт не бросает на файлах с `error`/`v2_error` — их символы не находятся.
    """
    raise NotImplementedError


def resolve_ident(root: Path, ref: str, ident: str, *, exclude: tuple[str, ...] = ()) -> list[str]:
    """Полные `путь::qualname` по `ident`.

    Pre: `ident` — `путь::qualname` либо голый `qualname` (`Cls.method`, `func`) без `::`.
    Post: с `::` — `[ident]`, если символ есть в `defs` файла ревизии, иначе `[]`. Без `::` — все файлы ревизии
        (кроме `exclude`) с символом, чей `qualname` ТОЧНО равен `ident` (не подстрока, не регистр), список отсортирован
        по пути. `[]` — не найден (`not found`), больше одного — `ambiguous`; решение о тексте ошибки принимает
        вызывающий (`passports_for`). Не бросает на отсутствии символа.
    """
    raise NotImplementedError


def render_text(passport: dict, *, budget: int = 40, show_all: frozenset[str] = frozenset(), full: bool = False) -> str:
    """Текст паспорта (образцы строк — в докстринге модуля). Без завершающего перевода строки.

    Pre: `passport` — результат `build_passport`; `show_all` ⊆ `SHOW_ALL_SECTIONS`; `budget` — число строк на ЭТОТ
        паспорт (у каждого id независимо).
    Post: `full=True` — без среза (сильнее `budget` и `show_all`). Иначе строк <= max(`budget`, минимум); минимум —
        конверт, заголовки разделов, `purpose` и служебные строки; остаток делится поровну между разделами-списками
        (без приоритета), излишек короткого уходит прочим. Порядок записей среза — `(-rank, path, line)`; `rank` =
        число вызовов из продукта (`scope: prod`) у `enclosing` записи (у `used_by` `enclosing` = `<module>`,
        `rank` = 0: порядок по `path`). Раздел из `show_all` не режется.
        Срезанный раздел содержит `показано K из N; все: --all <раздел>`. Паспорт не меняется.
    Raises: `ValueError`, если в `show_all` есть имя вне `SHOW_ALL_SECTIONS`.
    """
    raise NotImplementedError


def passports_for(root: Path, ref: str, idents: list[str], *, exclude: tuple[str, ...] = ()) -> list[dict]:
    """Паспорта по списку идентификаторов, в порядке `idents`.

    Pre: `idents` — не пусто; каждый — `путь::qualname` или голое имя.
    Post: список той же длины и порядка. Разрешённый id -> результат `build_passport`. Ошибочный id -> запись
        `{"id": <как дан>, "error": "not found"}` (0 совпадений) либо `{"id": <как дан>, "error": "ambiguous",
        "candidates": [<путь::qualname>, ...]}` (больше одного; `candidates` отсортированы по пути; ключа нет у
        `not found`). Ошибка одного id не отменяет остальные: их паспорта полные. Дубли `idents` дают дубли записей.
    """
    raise NotImplementedError
