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
    from-импорту символа, в том числе через реэкспорт `__init__.py` (до 5 звеньев, Task 4.5a); `m.f()` по импорту
    модуля `m`; `self.m()` внутри класса символа. Запись:
    `{"where": "путь:строка", "how": "name-call", "scope": .., "enclosing": qualname, "same_file": bool}`;
    `same_file` — вызов в файле самого символа (F2). `enclosing` — ближайший def/class вызова.
  - `call_sites_unresolved` — число (int) вызовов с совпавшим именем, которые не отнесены ни к одному символу:
    `x.m()` по произвольному получателю; голый вызов или `m.f()`, где имя (у `m.f()` — первый сегмент
    получателя) затенено; голый вызов двусмысленного from-импорта; голый вызов через фасад `__init__.py`, не
    давший адреса. Счётчик «не видно», а не список; ключ — имя, общий для всех одноимённых символов.
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

Реэкспорт (Task 4.5a). Голое имя по `from pkg import X`, где `pkg/__init__.py` имя не определяет, идёт по записям
`ImportRec` фасада с этим именем (любой `kind`: `lazy` внутри `def __getattr__` по PEP 562 и во вспомогательной
функции — тоже) до файла определения; звено — один `__init__.py`, звеньев не больше 5. Нет записи, цели записей
различны, цикл, 6-е звено -> вызов в `call_sites_unresolved`. `used_by` определения остаётся по записи импорта
в самом `__init__.py`: импортёры фасада в нём не видны. `m.X()` по `import pkg` через фасад не разрешается.

Затенение (Task 4.5a). Голый вызов `f()` (и `m.f()` по первому сегменту получателя) не относится к символу, если
имя — параметр `def` цепочки охватывающих вызова или `def`/`class`, вложенный в функцию или метод этой цепочки;
одноимённый метод охватывающего класса не затеняет. Сигнатура, которая не разбирается, затеняет любое имя. Без
анализа потока: порядок объявлений, ветки `if`, присваивания, `lambda` и переменные включений не учитываются.

Двусмысленность (Task 4.5a). Различных определений `(путь, имя)` у from-импортов имени в файле (после реэкспорта)
>= 2 -> голые вызовы имени в файле не относятся никому. `from pkg import X` + `from pkg.core import X` к одному
определению — не двусмысленны. Своё определение файла побеждает from-импорт без проверки двусмысленности.

Что НЕ разрешается (граница «не видно» паспорта): реэкспорт сверх 5 звеньев, через `*` или `importlib`;
динамические вызовы (`getattr`, строки); вызовы по алиасу. В `call_sites` такие вызовы не попадают; считаются ли
они в `call_sites_unresolved`, зависит от формы алиаса:
  - `import m as x; x.f()` — вызов с получателем `x`, не разрешённый в символ: СЧИТАЕТСЯ в `call_sites_unresolved`
    (как любой `x.m()` по произвольному получателю);
  - `from a import f as g; g()` — голое имя `g` без определения и без from-импорта под этим именем: нигде НЕ
    считается ни в `call_sites`, ни в `call_sites_unresolved`; сам импорт при этом попадает в `used_by` символа `f`.

Известная неточность: `ImportRec` алиас не хранит, поэтому `from a import f as g` + `from b import f` дают имени `f`
два определения — вызов `f()` (на деле `b::f`) не относится никому и считается в `call_sites_unresolved`.
Полное решение — отдельное поле алиаса в фактах (v2 сканера); в Task 4.5a не заводится.
Ещё неточности затенения (Task 4.5a, ревью stage 5):
  - `" -> "` внутри значения по умолчанию ломает разбор сигнатуры: затенено любое имя (на дереве 0 из 57 669 def);
  - не учитываются присваивание, `lambda`, переменные включений и тело класса (`class A: def helper(): ...;
    x = helper()` — вызов в теле класса относится к верхнему `helper`, если такой есть);
  - у `@property` + `@x.setter` берётся первый `DefFact` qualname: параметры сеттера не видны (на дереве 0 вызовов).

  - `bases` (Task 4.1b) — основы класса в порядке `DefFact.bases`, по одной записи на основу (разрешённую или нет):
    `{"name": .., "where": "путь:строка", "how": .., "scope": ..}`. `name` — сырой текст основы (`m.Base`, `Base[T]`),
    не лист; `where` — строка `class` ОСНОВЫ (не строка импорта); `how` — `"same-file"` (основа из своего файла) или
    `"import"`; `scope` — по файлу основы (не наследника). Разрешение то же, что у `subclasses`: имя класса своего
    файла; from-импорт; `m.Base` по импорту модуля `m`; у `Base[T]` — имя до `[`; импорт из `__init__.py` — по
    реэкспорту до файла определения (Task 4.5a, те же 5 звеньев). Основа без адреса (`abc.ABC`, `object`,
    `Protocol`, реэкспорт сверх 5 звеньев, алиас `as`, вызов `Base(1)`) — запись есть, `where`, `how`, `scope`
    равны None: `where: None` значит «адрес не разрешён», а не «не искали». Счётчика неразрешённых нет. У класса без
    основ — `[]`; у функции и метода — `None`. Глубина — один уровень: цепочки основ нет.

Не входит: `inherited_members` и цепочка основ глубже одного уровня; `command_specs` (Task 4.2a).
"""

from __future__ import annotations

import ast
import functools
import re
from collections import defaultdict

from scripts.atlas.scan import DefFact, FileFacts, ImportIndex, resolve_relative

__all__ = ["Links", "build_links"]

TOO_GENERIC = "слишком общий протокол: меньше двух обязательных методов"
_TEST_PATH = re.compile(r"(^|/)tests/|(^|/)(test_[^/]*|[^/]*_test|conftest)\.py$")
_REEXPORT_HOPS = 5  # звено — один `__init__.py`, через который идёт реэкспорт (Task 4.5a, решение лида а)

type _Sym = tuple[str, str]  # (путь, qualname)


@functools.cache  # путь -> scope: ~108 тыс. записей на дереве, ~4,4 тыс. путей (Task 4.5a, бюджет Kill-2)
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
        self._params: dict[str, frozenset[str] | None] = {}  # сигнатура -> имена параметров; None — не разобрана
        self._reexports: dict[tuple[str, str], _Sym | None] = {}  # (`__init__.py`, имя) -> определение или None
        self._locals: dict[tuple[str, str], frozenset[str] | None] = {}  # (путь, enclosing) -> локальные имена
        self._children: dict[str, dict[str, set[str]]] = {}  # путь -> qualname -> имена вложенных def/class
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
            from_names, modules, from_targets = self._imports(index, path, facts)
            self._index_calls(path, facts, self._from_definitions(index, from_targets), modules)
            self._index_subclasses(index, path, facts, from_names, modules)
            self._index_tests(path, facts)

    def _imports(
        self, index: ImportIndex, path: str, facts: FileFacts
    ) -> tuple[dict[str, tuple[str, int]], dict[str, tuple[str, int]], dict[str, list[str]]]:
        """Импорты файла: имена `from m import f` и модули (`import m`, `from pkg import mod`) -> (цель, строка);
        третий словарь — все различные цели from-импортов имени в порядке записей (для двусмысленности)."""
        from_names: dict[str, tuple[str, int]] = {}
        modules: dict[str, tuple[str, int]] = {}
        from_targets: dict[str, list[str]] = {}
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
                        targets = from_targets.setdefault(name, [])
                        if target not in targets:
                            targets.append(target)
                        if target != path:
                            self._used_by[(target, name)].append(
                                (path, rec.line, _entry(path, rec.line, "import", "<module>"))
                            )
        return from_names, modules, from_targets

    def _reexport_targets(self, index: ImportIndex, path: str, name: str) -> list[str]:
        """Файлы, откуда `__init__.py` `path` берёт имя `name` (`from m import name`, любой `kind`), без повторов."""
        facts = self._facts.get(path)
        targets: list[str] = []
        if facts is None:
            return targets
        current = _module_name(path)
        for rec in facts.imports:
            if not rec.is_from or name not in rec.names:
                continue
            resolved = index.resolve(path, rec)
            if resolved.status != "internal":
                continue
            base = resolve_relative(rec.level, rec.module, current, True) if rec.level else rec.module
            for target, names in resolved.targets:
                if name not in names or _module_name(target) == f"{base}.{name}":  # `from . import mod` — не имя
                    continue
                if target not in targets:
                    targets.append(target)
        return targets

    def _follow_reexport(self, index: ImportIndex, init_path: str, name: str) -> tuple[str, str] | None:
        """Реэкспорт `name` фасадом `init_path` -> `(файл определения, name)` или None, если адреса нет.

        Звено — один `__init__.py`: в его фактах ищется `ImportRec` с этим именем любого `kind` (`lazy` в
        `def __getattr__` по PEP 562 и во вспомогательной функции — тоже). Определение — имя верхнего уровня цели.
        None: записи нет; цели записей различны; цель — не `__init__.py` и имя не определяет; звено сверх
        `_REEXPORT_HOPS` (так же кончается цикл фасадов). Ответ запоминается по `(init_path, name)`."""
        key = (init_path, name)
        if key in self._reexports:
            return self._reexports[key]
        found: _Sym | None = None
        path = init_path
        for _ in range(_REEXPORT_HOPS):  # цикл фасадов обрывает тот же предел
            if not _is_init(path):
                break  # тупик: не фасад и имя не определяет
            targets = self._reexport_targets(index, path, name)
            if len(targets) != 1:
                break  # записи нет или цели различны
            if self._top(targets[0], name):
                found = (targets[0], name)
                break
            path = targets[0]
        self._reexports[key] = found
        return found

    def _from_definitions(self, index: ImportIndex, from_targets: dict[str, list[str]]) -> dict[str, _Sym | None]:
        """Имя from-импорта файла -> определение `(путь, имя)` после реэкспорта `__init__.py`.

        None — голый вызов имени не относится никому и считается в `call_sites_unresolved`: различных определений
        >= 2 (двусмысленность) или фасад `__init__.py` адреса не дал. Имени нет в ответе — ни одна цель имя не
        определяет и не фасад: вызов не считается нигде (как до Task 4.5a)."""
        out: dict[str, _Sym | None] = {}
        for name, targets in from_targets.items():
            found: list[_Sym] = []
            lost = False
            for target in targets:
                if self._top(target, name):
                    sym: _Sym | None = (target, name)
                elif _is_init(target):
                    sym = self._follow_reexport(index, target, name)
                    lost = lost or sym is None
                else:
                    sym = None
                if sym is not None and sym not in found:
                    found.append(sym)
            if len(found) == 1:
                out[name] = found[0]
            elif found or lost:
                out[name] = None
        return out

    def _params_of(self, d: DefFact) -> frozenset[str] | None:
        """Имена всех параметров `def` по `DefFact.signature`; None — сигнатура не разбирается. Разбор — раз на
        сигнатуру."""
        sig = d.signature
        if sig not in self._params:
            names: frozenset[str] | None = None
            try:
                node = ast.parse(f"def _({sig.split(' -> ')[0]}): pass").body[0]
            except (SyntaxError, ValueError):  # ValueError: нулевой байт в тексте
                node = None
            if isinstance(node, ast.FunctionDef):
                a = node.args
                every = [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg]
                names = frozenset(x.arg for x in every if x is not None)
            self._params[sig] = names
        return self._params[sig]

    def _local_names(self, path: str, enclosing: str) -> frozenset[str] | None:
        """Локальные имена в `enclosing`: параметры `def` цепочки охватывающих и имена `def`/`class`, вложенных в
        функцию или метод цепочки (метод охватывающего класса — нет). None — у `def` цепочки сигнатура не
        разобрана: локальным считается любое имя. Ответ запоминается по `(path, enclosing)`."""
        key = (path, enclosing)
        if key in self._locals:
            return self._locals[key]
        table = self._defs.get(path, {})
        kids = self._children.get(path)
        if kids is None:
            kids = defaultdict(set)
            for q in table:
                parent, _, leaf = q.rpartition(".")
                if parent:
                    kids[parent].add(leaf)
            self._children[path] = kids
        names: set[str] | None = set()
        parts = enclosing.split(".")
        for i in range(len(parts), 0, -1):
            q = ".".join(parts[:i])
            d = table.get(q)
            if d is None or d.kind == "class":
                continue
            params = self._params_of(d)
            if params is None:
                names = None
                break
            names |= params
            names |= kids.get(q, set())
        self._locals[key] = None if names is None else frozenset(names)
        return self._locals[key]

    def _shadowed(self, path: str, enclosing: str, name: str) -> bool:
        """`name` внутри `enclosing` — локальное имя (`_local_names`). Без анализа потока: порядок объявления и
        ветки `if` не учитываются."""
        local = self._local_names(path, enclosing)
        return local is None or name in local

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
        self, path: str, facts: FileFacts, from_defs: dict[str, _Sym | None], modules: dict[str, tuple[str, int]]
    ) -> None:
        seen_module_use: set[tuple[str, str, int]] = set()
        for call in facts.calls:
            target: _Sym | None = None
            if call.receiver is None:
                if self._top(path, call.name):
                    target = (path, call.name)
                elif call.name in from_defs:
                    target = from_defs[call.name]  # None: двусмысленно или фасад без адреса -> unresolved
                else:
                    continue  # голое имя без определения и from-импорта: не видно, не считается
                if target is not None and self._shadowed(path, call.enclosing, call.name):
                    target = None  # параметр или вложенный def/class: вызов локального имени
            elif call.receiver == "self":
                cls = self._class_of(path, call.enclosing)
                if cls is not None and f"{cls}.{call.name}" in self._defs[path]:
                    target = (path, f"{cls}.{call.name}")
            elif call.receiver in modules:
                where, line = modules[call.receiver]
                if self._top(where, call.name) and not self._shadowed(
                    path, call.enclosing, call.receiver.split(".", 1)[0]
                ):
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
        self,
        index: ImportIndex,
        path: str,
        base: str,
        from_names: dict[str, tuple[str, int]],
        modules: dict[str, tuple[str, int]],
    ) -> tuple[str, str, str] | None:
        """Основа `base` класса из файла `path` -> `(файл основы, имя в нём, how)` или None, если адрес не разрешён.

        `Base[T]` берётся по имени до `[`; `m.Base` — по импорту модуля `m`; голое имя — по from-импорту либо как класс
        своего файла (`how: "same-file"`, импорта нет). Имя должно быть объявлено в файле основы; импорт из
        `__init__.py`, где имени нет, идёт по реэкспорту (`_follow_reexport`) — файл основы тогда файл определения."""
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
            followed = self._follow_reexport(index, target, leaf) if how == "import" else None
            if followed is None:
                return None
            target = followed[0]
        return target, leaf, how

    def _index_subclasses(
        self,
        index: ImportIndex,
        path: str,
        facts: FileFacts,
        from_names: dict[str, tuple[str, int]],
        modules: dict[str, tuple[str, int]],
    ) -> None:
        for d in self._defs[path].values():
            if d.kind != "class":
                continue
            bases: list[dict] = []
            for base in d.bases:
                resolved = self._resolve_base(index, path, base, from_names, modules)
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
