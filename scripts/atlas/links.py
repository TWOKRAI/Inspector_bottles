"""Индекс связей над фактами v2: кто использует символ, кто его вызывает, кто наследует, кто тестирует (Task 4.1).

Purpose: из `dict[str, FileFacts]` (ровно то, что отдаёт `scan(...).facts`: ключ — posix-путь файла от корня
    репозитория, значение — факты файла, включая поля v2 `defs`, `calls`, `test_defs`) строит индекс, который
    отвечает на вопрос «что известно о символе `путь::qualname`». Индекс считается заново при каждом вызове
    `build_links`, кэша нет (кэш `links` вне Task 4.1). Паспорт (Task 4.2a) читает только `Links.of`.
Public API: Links, build_links.
Stability: lite

Pre: `facts` — отображение путь -> `FileFacts`; файлы с `error` или `v2_error` вкладывают пустые списки и не мешают
    остальным. Пустой `facts` допустим. Модуль не читает диск и git, не импортирует `multiprocess_framework`,
    `Services`, `Plugins` (сторож R1) и не бросает на пустых или неполных фактах.
Post: `build_links(facts)` детерминирован: тот же `facts` -> тот же ответ `of`, порядок записей в разделах —
    по `(where, line)`. `Links.of(ident)` не меняет индекс.

Идентификатор `ident` = `"<путь>::<qualname>"`: `scripts/x.py::Cls.method`, `scripts/x.py::func`.
Символ без записи в `defs` файла -> `of(...) is None`.

Ответ `of(ident)` — словарь; ключи-разделы (пустой раздел — `[]`, не отсутствующий ключ, кроме `structural`):

  - `used_by` — импорты символа: файлы, чей `from <модуль> import <имя>` (или `import <модуль>` при
    обращении `m.<имя>`) указывает на файл символа. Запись: `{"where": "путь:строка", "how": "import",
    "scope": .., "enclosing": ..}`; `where` — файл-импортёр и строка импорта (`ImportRec.line`); `enclosing` у импорта —
    `"<module>"`.
  - `call_sites` — разрешённые вызовы (name-call) из `CallFact`: голое имя в своём файле; голое имя по
    from-импорту символа; `m.f()` по импорту модуля `m`; `self.m()` внутри класса символа. Запись:
    `{"where": "путь:строка", "how": "name-call", "scope": .., "enclosing": qualname, "same_file": bool}`;
    `same_file` — вызов в файле самого символа (F2). `enclosing` — ближайший def/class вызова.
  - `call_sites_unresolved` — число (int) вызовов с совпавшим именем, которые не отнесены ни к одному символу
    (`x.m()` по произвольному получателю): счётчик «не видно», а не список.
  - `subclasses` — наследники: классы, чей `DefFact.bases` называет символ-класс. `how: "import"` — файл
    наследника импортирует основу; `how: "same-file"` — основа и наследник в одном файле (иерархии исключений и
    интерфейсов: без импорта; основа — класс верхнего уровня файла, имя без точки). Запись как у `used_by`, но
    `where` — `"путь:строка"` строки `class` наследника (`DefFact.line`), `enclosing` = qualname наследника.
  - `structural` — структурные двойники протокола/ABC: `{"required": [имена], "twins": [qualname с путём]}`
    или `None`. Обязательные имена — все неприватные (без `_` в начале) не-dunder методы класса-основы;
    меньше двух таких -> `None` (в ответе строка «слишком общий протокол» в ключе `note`). Двойник — класс
    с неприватным именем, имеющий все обязательные методы и НЕ наследующий основу. Раздел только у классов.
  - `tests` — тесты символа (`how: "test-body"`): функции из `test_defs`, в чьём теле символ назван
    (`CallFact.name` == имя символа) и чей файл импортирует файл символа. Запись:
    `{"where": "путь:строка", "how": "test-body", "scope": "test", "enclosing": qualname_теста}`; счёт тестов —
    `len(...)`.

Поле `scope` у каждой записи (кроме счётчика): `"test"`, если путь `where` совпал с `(^|/)tests/` или имя файла
`test_*.py`, `*_test.py`, `conftest.py` (шире `_TEST_FILE` A1: помощники внутри `tests/` тоже тест); иначе
`"prod"` (каталог `testing/` — поставляемые двойники, не тесты).

Что НЕ разрешается (граница «не видно» паспорта): символы, видимые только через реэкспорт `__init__.py`;
динамические вызовы (`getattr`, строки); вызовы по алиасу. В `call_sites` такие вызовы не попадают; считаются ли
они в `call_sites_unresolved`, зависит от формы алиаса:
  - `import m as x; x.f()` — вызов с получателем `x`, не разрешённый в символ: СЧИТАЕТСЯ в `call_sites_unresolved`
    (как любой `x.m()` по произвольному получателю);
  - `from a import f as g; g()` — голое имя `g` без определения и без from-импорта под этим именем: нигде НЕ
    считается ни в `call_sites`, ни в `call_sites_unresolved`; сам импорт при этом попадает в `used_by` символа `f`.

Известные ложные разрешения (имя -> символ по первому from-импорту; частота на HEAD не измерена):
  - `from a import f as g` + `from b import f`: имя `f` в таблице from-импортов достаётся первому импорту, у
    алиаса отдельной записи нет — вызов `f()` может отнестись к символу `a::f`, а не `b::f`;
  - вложенный `def f` или параметр `f` затеняет импортированное имя, но разбор вызовов этого не видит: вызов
    локального `f()` относится к импортированному `f`.
Полное решение — отдельное поле алиаса в фактах (v2 сканера); в Task 4.1b не заводится.

  - `bases` (Task 4.1b) — основы класса в порядке `DefFact.bases`, по одной записи на основу (разрешённую или нет):
    `{"name": .., "where": "путь:строка", "how": .., "scope": ..}`. `name` — сырой текст основы (`m.Base`, `Base[T]`),
    не лист; `where` — строка `class` ОСНОВЫ (не строка импорта); `how` — `"same-file"` (основа из своего файла) или
    `"import"`; `scope` — по файлу основы (не наследника). Разрешение то же, что у `subclasses`: имя класса своего
    файла; from-импорт; `m.Base` по импорту модуля `m`; у `Base[T]` — имя до `[`. Основа без адреса (`abc.ABC`,
    `object`, `Protocol`, реэкспорт `__init__`, алиас `as`, вызов `Base(1)`) — запись есть, `where`, `how`, `scope`
    равны None: `where: None` значит «адрес не разрешён», а не «не искали». Счётчика неразрешённых нет. У класса без
    основ — `[]`; у функции и метода — `None`. Глубина — один уровень: цепочки основ нет.

Не входит: `inherited_members` и цепочка основ глубже одного уровня; `command_specs` (Task 4.2a).
"""

from __future__ import annotations

import re
from collections import defaultdict

from scripts.atlas.scan import DefFact, FileFacts, ImportIndex, resolve_relative

__all__ = ["Links", "build_links"]

TOO_GENERIC = "слишком общий протокол: меньше двух обязательных методов"
_TEST_PATH = re.compile(r"(^|/)tests/|(^|/)(test_[^/]*|[^/]*_test|conftest)\.py$")

type _Sym = tuple[str, str]  # (путь, qualname)


def _scope(path: str) -> str:
    return "test" if _TEST_PATH.search(path) else "prod"


def _is_init(path: str) -> bool:
    return path == "__init__.py" or path.endswith("/__init__.py")


def _module_name(path: str) -> str:
    """Имя модуля по пути — та же формула, что в `ImportIndex`."""
    name = path[: -len(".py")].replace("/", ".") if path.endswith(".py") else path
    return name[: -len("__init__")].rstrip(".") if _is_init(path) else name


def _base_leaf(base: str) -> str:
    """`pkg.mod.Base[T]` -> `Base`: листовое имя основы без параметров."""
    return base.split("[", 1)[0].rsplit(".", 1)[-1].strip()


def _entry(path: str, line: int, how: str, enclosing: str) -> dict:
    return {"where": f"{path}:{line}", "how": how, "scope": _scope(path), "enclosing": enclosing}


def _sorted(entries: list[tuple[str, int, dict]]) -> list[dict]:
    return [dict(e) for _, _, e in sorted(entries, key=lambda x: (x[0], x[1]))]


class Links:
    """Индекс связей; создаётся `build_links`. Ответы `of` — свежие словари: правка ответа индекс не меняет."""

    def __init__(self, facts: dict[str, FileFacts] | None = None) -> None:
        self._facts: dict[str, FileFacts] = dict(facts or {})
        self._defs: dict[str, dict[str, DefFact]] = {}  # путь -> qualname -> первый DefFact
        self._used_by: dict[_Sym, list[tuple[str, int, dict]]] = defaultdict(list)
        self._calls: dict[_Sym, list[tuple[str, int, dict]]] = defaultdict(list)
        self._unresolved: dict[str, int] = defaultdict(int)  # имя -> число неотнесённых `x.m()`
        self._subclasses: dict[_Sym, list[tuple[str, int, dict]]] = defaultdict(list)
        self._bases: dict[_Sym, list[dict]] = {}  # класс -> основы в порядке `DefFact.bases`, с адресом или None
        self._importers: dict[str, set[str]] = defaultdict(set)  # путь -> файлы, чьи импорты указывают на него
        self._tests_by_name: dict[str, dict[str, list[tuple[str, int]]]] = {}  # файл -> имя -> тесты, его вызвавшие
        self._methods_of: dict[_Sym, list[str]] = {}  # класс -> имена прямых методов в порядке определения
        self._classes_with: dict[str, set[_Sym]] = defaultdict(set)  # неприватный метод -> классы с ним
        self._build()

    # ------------------------------------------------------------------ построение

    def _build(self) -> None:
        index = ImportIndex(self._facts)
        for path, facts in self._facts.items():
            table: dict[str, DefFact] = {}
            for d in facts.defs:
                table.setdefault(d.qualname, d)
            self._defs[path] = table
            for d in table.values():
                if d.kind != "class":
                    continue
                sym = (path, d.qualname)
                prefix = d.qualname + "."
                names = [q[len(prefix) :] for q, x in table.items() if x.kind == "method" and q.startswith(prefix)]
                self._methods_of[sym] = [n for n in names if "." not in n]
                for name in self._methods_of[sym]:
                    if not name.startswith("_"):
                        self._classes_with[name].add(sym)
        for path, facts in self._facts.items():
            from_names, modules = self._imports(index, path, facts)
            self._index_calls(path, facts, from_names, modules)
            self._index_subclasses(path, facts, from_names, modules)
            self._index_tests(path, facts)

    def _imports(
        self, index: ImportIndex, path: str, facts: FileFacts
    ) -> tuple[dict[str, tuple[str, int]], dict[str, tuple[str, int]]]:
        """Импорты файла: имена `from m import f` и модули (`import m`, `from pkg import mod`) -> (цель, строка)."""
        from_names: dict[str, tuple[str, int]] = {}
        modules: dict[str, tuple[str, int]] = {}
        for rec in facts.imports:
            resolved = index.resolve(path, rec)
            if resolved.status != "internal":
                continue
            if rec.level:
                base = resolve_relative(rec.level, rec.module, _module_name(path), _is_init(path))
            else:
                base = rec.module
            for target, names in resolved.targets:
                if target != path:
                    self._importers[target].add(path)
                if not rec.is_from:
                    modules.setdefault(rec.module or "", (target, rec.line))
                    continue
                for name in names:
                    if name == "*":
                        continue
                    if _module_name(target) == f"{base}.{name}":  # `from pkg import mod`: имя — модуль
                        modules.setdefault(name, (target, rec.line))
                    else:
                        from_names.setdefault(name, (target, rec.line))
                        if target != path:
                            self._used_by[(target, name)].append(
                                (path, rec.line, _entry(path, rec.line, "import", "<module>"))
                            )
        return from_names, modules

    def _top(self, path: str, name: str) -> bool:
        d = self._defs.get(path, {}).get(name)
        return d is not None and d.kind != "method"

    def _top_class(self, path: str, name: str) -> bool:
        d = self._defs.get(path, {}).get(name)
        return d is not None and d.kind == "class"

    def _class_of(self, path: str, enclosing: str) -> str | None:
        parts = enclosing.split(".")
        table = self._defs.get(path, {})
        for i in range(len(parts), 0, -1):
            d = table.get(".".join(parts[:i]))
            if d is not None and d.kind == "class":
                return d.qualname
        return None

    def _index_calls(
        self, path: str, facts: FileFacts, from_names: dict[str, tuple[str, int]], modules: dict[str, tuple[str, int]]
    ) -> None:
        seen_module_use: set[tuple[str, str, int]] = set()
        for call in facts.calls:
            target: _Sym | None = None
            if call.receiver is None:
                if self._top(path, call.name):
                    target = (path, call.name)
                elif call.name in from_names and self._top(from_names[call.name][0], call.name):
                    target = (from_names[call.name][0], call.name)
                else:
                    continue  # голое имя без определения и from-импорта: не видно, не считается
            elif call.receiver == "self":
                cls = self._class_of(path, call.enclosing)
                if cls is not None and f"{cls}.{call.name}" in self._defs[path]:
                    target = (path, f"{cls}.{call.name}")
            elif call.receiver in modules:
                where, line = modules[call.receiver]
                if self._top(where, call.name):
                    target = (where, call.name)
                    if where != path and (where, call.name, line) not in seen_module_use:
                        seen_module_use.add((where, call.name, line))
                        self._used_by[target].append((path, line, _entry(path, line, "import", "<module>")))
            if target is None:
                self._unresolved[call.name] += 1
                continue
            entry = _entry(path, call.line, "name-call", call.enclosing)
            entry["same_file"] = target[0] == path
            self._calls[target].append((path, call.line, entry))

    def _resolve_base(
        self, path: str, base: str, from_names: dict[str, tuple[str, int]], modules: dict[str, tuple[str, int]]
    ) -> tuple[str, str, str] | None:
        """Основа `base` класса из файла `path` -> `(файл основы, имя в нём, how)` или None, если адрес не разрешён.

        `Base[T]` берётся по имени до `[`; `m.Base` — по импорту модуля `m`; голое имя — по from-импорту либо как класс
        своего файла (`how: "same-file"`, импорта нет). Имя должно быть объявлено в файле основы."""
        core = base.split("[", 1)[0].strip()
        head, _, leaf = core.rpartition(".")
        hit = modules.get(head) if head else from_names.get(leaf)
        if hit is not None and hit[0] != path:
            target, how = hit[0], "import"
        elif not head and self._top_class(path, leaf):
            target, how = path, "same-file"  # основа из своего файла: импорта нет
        else:
            return None
        if self._defs.get(target, {}).get(leaf) is None:
            return None
        return target, leaf, how

    def _index_subclasses(
        self, path: str, facts: FileFacts, from_names: dict[str, tuple[str, int]], modules: dict[str, tuple[str, int]]
    ) -> None:
        for d in self._defs[path].values():
            if d.kind != "class":
                continue
            bases: list[dict] = []
            for base in d.bases:
                resolved = self._resolve_base(path, base, from_names, modules)
                entry = {"name": base, "where": None, "how": None, "scope": None}  # None: адрес не разрешён
                if resolved is not None:
                    target, leaf, how = resolved
                    self._subclasses[(target, leaf)].append((path, d.line, _entry(path, d.line, how, d.qualname)))
                    base_def = self._defs[target][leaf]
                    if base_def.kind == "class":  # `where` — строка `class` основы; функция-«основа» адреса не даёт
                        entry.update(where=f"{target}:{base_def.line}", how=how, scope=_scope(target))
                bases.append(entry)
            self._bases[(path, d.qualname)] = bases

    def _index_tests(self, path: str, facts: FileFacts) -> None:
        if not facts.test_defs:
            return
        lines = dict(facts.test_defs)
        by_name: dict[str, list[tuple[str, int]]] = defaultdict(list)
        named: set[tuple[str, str]] = set()
        for call in facts.calls:
            parts = call.enclosing.split(".")
            for i in range(len(parts), 0, -1):  # тест — объемлющая функция или её предок (вложенный def в тесте)
                owner = ".".join(parts[:i])
                if owner in lines:
                    if (owner, call.name) not in named:
                        named.add((owner, call.name))
                        by_name[call.name].append((owner, lines[owner]))
                    break
        self._tests_by_name[path] = dict(by_name)

    # ------------------------------------------------------------------ запрос

    def _structural(self, sym: _Sym) -> dict | None:
        required = [n for n in self._methods_of.get(sym, []) if not n.startswith("_")]
        if len(required) < 2:
            return None
        name = sym[1].rsplit(".", 1)[-1]
        found = set.intersection(*(self._classes_with.get(n, set()) for n in required))
        twins = []
        for path, qualname in found:
            if (path, qualname) == sym or qualname.rsplit(".", 1)[-1].startswith("_"):
                continue
            if any(_base_leaf(b) == name for b in self._defs[path][qualname].bases):
                continue  # наследник основы — не двойник
            twins.append(f"{path}::{qualname}")
        return {"required": required, "twins": sorted(twins)}

    def of(self, ident: str) -> dict | None:
        """Связи символа `"путь::qualname"` (разделы — в докстринге модуля).

        Pre: `ident` — строка вида `путь::qualname`.
        Post: символ найден в `defs` файла -> словарь разделов; не найден, или `ident` неверной формы -> None.
        Не бросает.
        """
        if not isinstance(ident, str):
            return None
        path, sep, qualname = ident.partition("::")
        d = self._defs.get(path, {}).get(qualname) if sep and qualname else None
        if d is None:
            return None
        sym = (path, qualname)
        name = qualname.rsplit(".", 1)[-1]
        tests = []
        for importer in self._importers.get(path, ()):
            for owner, line in self._tests_by_name.get(importer, {}).get(name, ()):
                entry = {"where": f"{importer}:{line}", "how": "test-body", "scope": "test", "enclosing": owner}
                tests.append((importer, line, entry))
        result: dict = {
            "used_by": _sorted(self._used_by.get(sym, [])),
            "call_sites": _sorted(self._calls.get(sym, [])),
            "call_sites_unresolved": self._unresolved.get(name, 0),
            "subclasses": _sorted(self._subclasses.get(sym, [])),
            "tests": _sorted(tests),
        }
        result["bases"] = [dict(b) for b in self._bases[sym]] if d.kind == "class" else None
        if d.kind == "class":
            result["structural"] = self._structural(sym)
            if result["structural"] is None:
                result["note"] = TOO_GENERIC
        return result


def build_links(facts: dict[str, FileFacts]) -> Links:
    """Строит индекс связей по фактам файлов (`scan(...).facts`); без кэша, без чтения диска.

    Pre: `facts` — `{путь: FileFacts}`; пустой словарь допустим.
    Post: возвращает `Links`; на любых входных фактах не бросает.
    """
    return Links(facts)
