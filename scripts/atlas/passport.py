"""Паспорт символа Д1 (Task 4.2a): один объект про класс, функцию или метод — для `ref --format`, бенча и агента.

Purpose: по ревизии git (`ref`) и идентификатору символа собирает паспорт: конверт и шесть разделов с постоянными
    ключами (JSON-совместимый `dict`), печатает его текстом по бюджету строк. Читает факты v2 (`scan`), связи
    (`build_links`), слой (`modules_for` + `modules.resolve`). Не меняет репозиторий (кроме stat-кэша `.git/index`,
    который обновляет `git diff` из `status.stale`) и не меняет рабочее дерево; рабочее дерево читает только
    `status.stale`; пишет только кэш фактов `data/atlas.sqlite` через `scan()`.
Public API: build_passport, resolve_ident, render_text, passports_for.
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
  all        list[str] | null         `null` — литерального `__all__` нет ни у файла символа, ни у одного `__init__.py`
                                      цепочки (от ближайшего пакета до юнита). Иначе пути `__init__.py` звеньев, где имя
                                      в `__all__`, от ближайшего пакета до юнита — и когда у самого файла `__all__` нет;
                                      `[]` — `__all__` есть хотя бы у одного звена, имени нигде нет
  signature  str                      у функции и метода — хвост строки `reference._sig` после имени (без `self`/`cls`,
                                      `-> T` после скобок): `(key: str) -> None`; у `async def` — `async (x: int) -> T`
                                      (как `reference._sig`); у `property` — `-> T` или `""`; у класса `""`
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
                             --literal-pathspecs diff -z --name-only --no-renames <sha> -- <пути>`; порядок — как пути
                             в паспорте, без повторов. `[]` — искали, чисто. `null` — не искали: `sha` != HEAD корня,
                             HEAD не разрешается или `git diff` упал (bare-клон). `where: null` пропускается;
                             неотслеженные файлы не ищутся
  frozen       list[dict]    шапки `FREEZE YYYY-MM-DD: текст` — сначала докстринг файла символа, затем `__init__.py`
                             цепочки (обход каталогов общий с `interface.all`). Запись `{"date": str, "text": str,
                             "where": "путь:строка"}`; `text` — после `FREEZE YYYY-MM-DD: `; `where` — строка шапки.
                             Без повторов. Звено цепочки с `error` пропускается. `[]` — искали, нет. `null` у
                             `frozen` в v1 не бывает

Не входит: `recipes`; `kind` выше class/function/method (unit, package, file, layer); `map`; кэш `links` (`build_links`
пересчитывается при каждом вызове).

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
  - связь с `where: null`: `<имя> — строка не указана`;
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
from scripts.atlas.links import TOO_GENERIC, Links, build_links
from scripts.atlas.modules import resolve as module_of
from scripts.atlas.reference import _methods, _sig, _tag
from scripts.atlas.scan import SCANNER, DefFact, FileFacts, scan
from scripts.atlas.tree import AtlasError, Tree, resolve


__all__ = ["build_passport", "passports_for", "render_text", "resolve_ident"]

SECTIONS = ("purpose", "interface", "links", "runtime", "checks", "status")  # порядок ключей и заголовков
SHOW_ALL_SECTIONS = ("used_by", "call_sites", "subclasses", "structural", "tests")  # допустимые значения `show_all`

_FORMS = ("import", "name-call", "same-file", "test-body")  # порядок форм — порядок упоминания в `links.py`
_UNSEEN = "не видно: динамика, аннотации, упоминания"
_NOT_SEARCHED = "не искали"
_EMPTY = "—"
_NO_SPECS = "форма command_specs() не объявлена"
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


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

    @classmethod
    def open(cls, root: Path, ref: str, exclude: tuple[str, ...]) -> _Ctx:
        root = Path(root)
        sha = resolve(root, ref)
        tree = Tree(root, sha)
        paths = sorted(p for p in tree.oids() if p.endswith(".py") and not _excluded(p, exclude))
        con = store.connect(root / "data" / "atlas.sqlite")  # кэш фактов `scan_cache`: тёплый вызов не разбирает
        try:
            facts = scan(tree, paths, cache=con).facts
        finally:
            con.close()
        return cls(root, sha, tree, facts, build_links(facts))

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
        path, sep, qualname = ident.partition("::")
        if sep:
            return [ident] if qualname and self.find(path, qualname) is not None else []
        return [f"{p}::{ident}" for p in sorted(self.facts) if self.find(p, ident) is not None]

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
            raise AtlasError(f"atlas: symbol not found: {ident}")
        facts = self.facts[path]
        got = self.links.of(ident) or {}
        node = self._node(path, d)
        text = d.doc or ""
        return {
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
                "stale": None,
                "frozen": None,
            },
        }

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
        return {
            "layer": module_of(path, rows),
            "all": self._all_chain(path, d, facts, rows),
            "signature": signature,
            "members": members,
        }

    def _all_chain(self, path: str, d: DefFact, facts: FileFacts, rows: list[dict]) -> list[str] | None:
        seen_all = facts.all is not None  # `__all__` у файла символа или у звена цепочки
        name = d.qualname.split(".")[0]
        stop = ""
        best = 0
        # граница юнита — совпавший элемент `paths`: копия цикла `modules.resolve` (modules.py:113-118);
        # правка resolve -> править здесь
        for row in rows:
            for element in row["paths"]:
                hit = path.startswith(element) if element.endswith("/") else path == element
                if hit and len(element) > best:
                    best, stop = len(element), element.rstrip("/") if element.endswith("/") else ""
        chain: list[str] = []
        folder = path.rpartition("/")[0]
        while True:
            init = f"{folder}/__init__.py" if folder else "__init__.py"
            pkg = self.facts.get(init)
            if pkg is None:
                break
            seen_all = seen_all or pkg.all is not None
            if pkg.all is not None and name in pkg.all:
                chain.append(init)
            if not folder or (stop and folder == stop):
                break
            folder = folder.rpartition("/")[0]
            if stop and not (folder == stop or folder.startswith(stop + "/")):
                break
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
        raise NotImplementedError

    def _stale(self, passport: dict) -> list[str] | None:
        """`status.stale` собранного паспорта (раздел `status` в нём ещё не нужен).

        Pre: `passport` — `dict` с конвертом и пятью разделами до `status` (`path`, `links`, `runtime`, `checks`
            уже построены); `self.sha` — полный sha ревизии.
        Post: `None`, если `self.sha` != `resolve(self.root, "HEAD")`, HEAD не разрешается или `git diff` упал
            (`AtlasError` ловится только вокруг `resolve(root, "HEAD")` и `git_z`); иначе список путей паспорта,
            изменённых в рабочем дереве относительно `self.sha` (`git --no-optional-locks --literal-pathspecs diff -z
            --name-only --no-renames <sha> -- <пути>`), в порядке путей паспорта, без повторов; `[]` — чисто. Пути:
            `path`, путь из каждого `where` (`links.*`, `checks.tests`, `runtime.*`, `interface.members`,
            `links.bases`), путь из `links.structural.twins` (часть до `::`). `where: null` пропускается.
            Один вызов `git` на паспорт; репозиторий не меняется (кроме stat-кэша `.git/index`).
        """
        raise NotImplementedError

    def _frozen(self, path: str, facts: FileFacts, rows: list[dict]) -> list[dict]:
        """`status.frozen`: шапки `FREEZE` файла символа, затем `__init__.py` цепочки.

        Pre: `path`, `facts` — файл символа; `rows` — `self.rows()`.
        Post: список `{"date": str, "text": str, "where": "путь:строка"}`: сначала шапки `facts.freeze` (порядок
            строк файла), затем шапки каждого звена `_init_chain(path, rows)` без `error`, от ближайшего к юниту.
            Без повторов (символ в самом `__init__.py` — шапки файла не дублируются звеном). `[]` — искали, нет.
            `v2_error` звена не влияет. Класс и метод получают цепочку своего файла. Не бросает.
        """
        raise NotImplementedError

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
        }

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


# --------------------------------------------------------------------------- текст


def _order(entry: dict) -> tuple[int, str, int]:
    where = entry.get("where")
    path, line = _split(where) if where else ("", 0)
    return -entry.get("rank", 0), path, line


def _link_row(entry: dict) -> str:
    name = entry.get("name", entry.get("enclosing", ""))
    if entry.get("where") is None:
        return f"{name} — строка не указана"
    return f"{name} — {entry['where']} ({entry['how']})"


def _value(value: object) -> str:
    if value is None:
        return _NOT_SEARCHED
    if value == [] or value == 0 or value == "":
        return _EMPTY
    return str(value)


def _alloc(sizes: dict[str, int], avail: int) -> dict[str, int]:
    """Строк записей на раздел: поровну, излишек короткого — прочим; срезанный раздел платит строку пометки."""
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
        names = [k for k in SHOW_ALL_SECTIONS if k in pending]
        share = max(avail // len(names) - 1, 1)  # минус строка «показано K из N»
        extra = max(avail - (share + 1) * len(names), 0)
        for k in names:
            give[k] = min(pending[k] - 1, share + (1 if extra > 0 else 0))
            extra -= 1
    return give


def _render(passport: dict, budget: int, show_all: frozenset[str], full: bool) -> str:
    p = passport
    pur, itf, lnk, rt, chk, st = (p[s] for s in SECTIONS)
    fixed: list[tuple[str, object]] = []  # ("line", text) | ("list", (имя, отступ, записи, строка-функция))

    def add(text: str) -> None:
        fixed.append(("line", text))

    def add_list(name: str, indent: str, entries: list, row) -> None:
        fixed.append(
            (
                "list",
                (
                    name,
                    indent,
                    sorted(entries, key=_order) if entries and isinstance(entries[0], dict) else entries,
                    row,
                ),
            )
        )

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
    if members:
        add("  members:")
        for m in members:
            sig = m["signature"]
            prefix, sig = ("async ", sig.removeprefix("async ")) if sig.startswith("async ") else ("", sig)
            add(f"    {prefix}{m['name']}{' ' + sig if sig.startswith('->') else sig}  :{_split(m['where'])[1]}")
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
        add(f"  threads: {_EMPTY}")
    if rt["commands"] is None:
        add(f"  commands: {_NO_SPECS}")
    elif rt["commands"]:
        add("  commands:")
        for c in rt["commands"]:
            add(f"    {c['name']} — {c['where']} ({c['how']})")
    else:
        add(f"  commands: {_EMPTY}")
    if rt["io"]:
        add("  io:")
        for i in rt["io"]:
            add(f"    {i['op']} {i['path']} — {i['where']}")
    else:
        add(f"  io: {_EMPTY}")
    add(f"checks: findings {_value(chk['findings'])}")
    if chk["tests"]:
        add(f"  tests: {len(chk['tests'])}")
        add_list("tests", "    ", chk["tests"], _link_row)
    else:
        add(f"  tests: {_EMPTY}")
    doc = "да" if st["doc_missing"] else "нет"
    add(
        f"status: tier {st['tier'] or 'нет шапки'}; doc_missing {doc}; dynamic {_value(st['dynamic'])}; "
        f"stale {_value(st['stale'])}; frozen {_value(st['frozen'])}"
    )

    lists = {v[0]: v for k, v in fixed if k == "list"}
    free = {n: len(v[2]) for n, v in lists.items() if not full and n not in show_all}
    used = sum(1 for k, _ in fixed if k == "line") + sum(len(v[2]) for n, v in lists.items() if n not in free)
    give = _alloc(free, budget - used)
    out: list[str] = []
    for kind, item in fixed:
        if kind == "line":
            out.append(item)  # type: ignore[arg-type]
            continue
        name, indent, rows, row = item  # type: ignore[misc]
        keep = give.get(name, len(rows))
        out += [f"{indent}{row(r)}" for r in rows[:keep]]
        if keep < len(rows):
            out.append(f"{indent}показано {keep} из {len(rows)}; все: --all {name}")
    return "\n".join(out)


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
    return _Ctx.open(root, ref, exclude).passport(ident)


def resolve_ident(root: Path, ref: str, ident: str, *, exclude: tuple[str, ...] = ()) -> list[str]:
    """Полные `путь::qualname` по `ident`.

    Pre: `ident` — `путь::qualname` либо голый `qualname` (`Cls.method`, `func`) без `::`.
    Post: с `::` — `[ident]`, если символ есть в `defs` файла ревизии, иначе `[]`. Без `::` — все файлы ревизии
        (кроме `exclude`) с символом, чей `qualname` ТОЧНО равен `ident` (не подстрока, не регистр), список отсортирован
        по пути. `[]` — не найден (`not found`), больше одного — `ambiguous`; решение о тексте ошибки принимает
        вызывающий (`passports_for`). Не бросает на отсутствии символа.
    """
    return _Ctx.open(root, ref, exclude).resolve(ident)


def render_text(passport: dict, *, budget: int = 40, show_all: frozenset[str] = frozenset(), full: bool = False) -> str:
    """Текст паспорта (образцы строк — в докстринге модуля). Без завершающего перевода строки.

    Pre: `passport` — результат `build_passport`; `show_all` ⊆ `SHOW_ALL_SECTIONS`; `budget` — число строк на ЭТОТ
        паспорт (у каждого id независимо).
    Post: `full=True` — без среза (сильнее `budget` и `show_all`). Иначе строк <= max(`budget`, минимум); минимум —
        конверт, заголовки разделов, `purpose` и служебные строки; остаток делится поровну между разделами-списками
        (без приоритета), излишек короткого уходит прочим. Порядок записей среза — `(-rank, path, line)`; `rank` =
        число вызовов из продукта (`scope: prod`) у `enclosing` записи (у `used_by` `enclosing` = `<module>`,
        `rank` = 0: порядок по `path`). Раздел из `show_all` не режется. Строк может быть больше `budget`: в минимум
        входят по одной записи на каждый срезанный список и его пометка, члены класса не режутся; «<= 40 строк на
        экран» верно для небольших классов.
        Срезанный раздел содержит `показано K из N; все: --all <раздел>`. Паспорт не меняется.
    Raises: `ValueError`, если в `show_all` есть имя вне `SHOW_ALL_SECTIONS`.
    """
    unknown = set(show_all) - set(SHOW_ALL_SECTIONS)
    if unknown:
        raise ValueError(f"show_all: неизвестные разделы {sorted(unknown)}")
    return _render(passport, budget, frozenset(show_all), full)


def passports_for(root: Path, ref: str, idents: list[str], *, exclude: tuple[str, ...] = ()) -> list[dict]:
    """Паспорта по списку идентификаторов, в порядке `idents`.

    Pre: `idents` — не пусто; каждый — `путь::qualname` или голое имя.
    Post: список той же длины и порядка. Разрешённый id -> результат `build_passport`. Ошибочный id -> запись
        `{"id": <как дан>, "error": "not found"}` (0 совпадений) либо `{"id": <как дан>, "error": "ambiguous",
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
