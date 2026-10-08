"""Правила ADR-175 П1-П4 и реализации интерфейсов: чистый разбор AST, адаптер `rules` (Task 1.6c).

Purpose: один путь кода для адаптера (находки `warning`, слой framework), `ref` (реализации интерфейса: явно,
    структурно, структурно (Qt)) и `card` (доли соответствия framework/services/plugins). П1 — структурная реализация
    без наследования; П2 — docstring Google у публичного API; П3 — `__all__` у interfaces.py и __init__.py;
    П4 — запись файла без замены в той же функции (форма записи, не назначение файла). Код проекта не правится.
Public API: RulesAdapter, Scan, all_of.
Stability: lite
"""

from __future__ import annotations

import ast
import gc
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator

from scripts.atlas.adapters.code import _interface_names, _read
from scripts.atlas.adapters.modules import modules_for
from scripts.atlas.adapters.plans import adapter_version
from scripts.atlas.codemap import DUNDERS, dotted, is_test
from scripts.atlas.modules import resolve as module_of
from scripts.atlas.schema import AdapterOutput, BuildContext, Finding

__all__ = ["RulesAdapter", "Scan", "all_of"]

_QT = ("PySide6.", "PyQt5.", "PyQt6.")
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
_DEFS = (ast.ClassDef, *_FUNCS)
_API = ("interfaces.py", "__init__.py")
_STYLE = re.compile(r"^\s*:(param|returns?|raises?|type|rtype)\b|^\s*(Parameters|Returns|Raises)\s*\n\s*-{3,}", re.M)
_MODE = re.compile(r"[wx]b?\+?|[wx]\+?b?")
_ATOMIC = {"replace", "rename", "move"}
_CLASS = re.compile(r"\bclass\s")
_WRITE = re.compile(r"write_text|write_bytes")
_OPEN = re.compile(r"open\(")
_MODE_LITERAL = re.compile(r"""["'][wx]b?\+?["']|mode\s*=""")  # запись через open() требует литерал режима
Key = tuple[str, str]  # (путь, имя класса)


def _dot(expr: ast.expr) -> str | None:
    """`a.b.C` из Name/Attribute (подписка отбрасывается)."""
    expr = expr.value if isinstance(expr, ast.Subscript) else expr
    if isinstance(expr, ast.Attribute) and (head := _dot(expr.value)):
        return f"{head}.{expr.attr}"
    return expr.id if isinstance(expr, ast.Name) else None


def _last(expr: ast.expr) -> str:
    return (_dot(expr) or "").rpartition(".")[2]


def _blocks(node: ast.stmt) -> list[list[ast.stmt]]:
    return [
        node.body,
        getattr(node, "orelse", []),
        getattr(node, "finalbody", []),
        *(h.body for h in getattr(node, "handlers", [])),
    ]  # type: ignore[attr-defined]


def _top(tree: ast.Module) -> Iterator[ast.stmt]:
    """Узлы верхнего уровня, включая тела try/if (условный экспорт)."""
    for node in tree.body:
        yield node
        if isinstance(node, ast.Try | ast.If):
            yield from (n for block in _blocks(node) for n in block)


def _targets(node: ast.stmt) -> list[ast.expr]:
    return node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []


def all_of(tree: ast.Module) -> list[str] | None:
    """Литералы `__all__` модуля; None — переменной нет."""
    for node in _top(tree):
        if any(isinstance(t, ast.Name) and t.id == "__all__" for t in _targets(node)):
            value = node.value  # type: ignore[attr-defined]
            elts = value.elts if isinstance(value, ast.List | ast.Tuple) else []
            return [e.value for e in elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return None


def _bad_doc(node: ast.AST) -> bool:
    doc = (ast.get_docstring(node) or "").strip()  # type: ignore[arg-type]
    return not doc or bool(_STYLE.search(doc))


def _is_write(call: ast.Call) -> bool:
    """`open(…, "w"|"wb"|"x"…)`, `.write_text`, `.write_bytes`."""
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in ("write_text", "write_bytes"):
        return True
    if not (
        isinstance(func, ast.Name) and func.id == "open" or isinstance(func, ast.Attribute) and func.attr == "open"
    ):
        return False
    # Name-вызов: режим — args[1]; метод `.open(...)`: Path.open("w") — args[0], io.open(path, "w") — args[1]
    slots = call.args[:2] if isinstance(func, ast.Attribute) else call.args[1:2]
    modes = [a.value for a in slots if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    modes += [k.value.value for k in call.keywords if k.arg == "mode" and isinstance(k.value, ast.Constant)]
    return any(isinstance(m, str) and _MODE.fullmatch(m) for m in modes)


class _File:
    """Разобранный файл: дерево, импорты (локальное имя -> абсолютное имя цели), классы по имени."""

    def __init__(self, path: str, text: str) -> None:
        self.path, self.tree, self.text = path, ast.parse(text), text
        self.names: dict[str, str] = {}
        self.classes: dict[str, ast.ClassDef] = {}
        self._lines: list[str] | None = None
        self._visit(self.tree.body, dotted(path) if path.endswith("__init__.py") else dotted(path).rpartition(".")[0])

    def _visit(self, stmts: list[ast.stmt], pkg: str) -> None:
        """Классы (в т.ч. вложенные) и импорты вне тел функций."""
        for node in stmts:
            if isinstance(node, ast.ClassDef):
                self.classes.setdefault(node.name, node)
                self._visit(node.body, pkg)
            elif isinstance(node, ast.Try | ast.If | ast.With):
                for block in _blocks(node):
                    self._visit(block, pkg)
            elif isinstance(node, ast.ImportFrom):
                head = pkg.split(".")[: len(pkg.split(".")) - node.level + 1] if node.level else []
                mod = ".".join([*[h for h in head if h], *([node.module] if node.module else [])])
                self.names.update({a.asname or a.name: f"{mod}.{a.name}" for a in node.names if a.name != "*"})
            elif isinstance(node, ast.Import):
                self.names.update(
                    {a.asname or a.name.split(".")[0]: a.name if a.asname else a.name.split(".")[0] for a in node.names}
                )

    def source(self, node: ast.ClassDef) -> str:
        self._lines = self._lines or self.text.split("\n")
        return "\n".join(self._lines[node.lineno - 1 : node.end_lineno])


class Scan:
    """Разбор набора исходников `{путь: текст|байты}`: реестр классов, реализации интерфейсов, находки и доли."""

    def __init__(
        self, sources: dict[str, Any], rows: list[dict], structural_only: bool = False, focus: set[str] | None = None
    ) -> None:
        """`structural_only` (сборка): классы разбираются сразу лишь у модулей с интерфейсом из >= 2 абстрактных членов
        (иначе структурных реализаций там нет), явные вне модуля не ищутся. `focus` (виды): классы сразу лишь
        в этих файлах (модуль и его импортёры); остальные исходники framework — предки по цепочке, по требованию."""
        self.rows, self.structural_only = rows, structural_only
        self.sources = {
            p: (r if isinstance(r, str) else (r or b"").decode("utf-8", "replace").removeprefix("﻿"))
            for p, r in sources.items()
            if not is_test(p)
        }
        self.path_of = {dotted(p): p for p in self.sources}
        self.mod = {p: module_of(p, rows) for p in self.sources}
        self.by_module: dict[str, list[str]] = defaultdict(list)
        for p in sorted(self.sources):
            self.by_module[self.mod[p]].append(p)
        self.files: dict[str, _File | None] = {}
        self._anc: dict[Key, tuple[set[Key], set[str]]] = {}
        self._abs: dict[Key, set[str]] = {}
        self._all: list[Key] | None = None
        self.ifaces: dict[Key, str] = {}  # (путь, имя) -> id модуля
        self.iface_names: dict[str, list[Key]] = defaultdict(list)  # id модуля -> [(имя, путь)]
        for row in rows:  # сначала файлы API: по ним видно, у каких модулей есть интерфейс
            path = self._api(row, "interfaces.py")
            if path and (f := self.file(path)):
                for name in (n for n in _interface_names(f.tree) if f.classes.get(n) in f.tree.body):
                    self.ifaces[(path, name)] = row["id"]
                    self.iface_names[row["id"]].append((name, path))
        wide = {m for key, m in self.ifaces.items() if len(self.abstract(key)) >= 2}
        for path, text in self.sources.items():
            if _CLASS.search(text) and (
                (self.mod[path] in wide) if structural_only else (focus is None or path in focus)
            ):
                self.file(path)

    @classmethod
    def of_module(cls, code: Any, module: str, users: list[tuple[str, int]] | None) -> Scan:
        """Scan для видов `ref`/`card`: исходники framework выгрузки (предки по цепочке — лениво) плюс модуль и его
        импортёры (разбираются сразу); множество реализаций то же, что у адаптера."""
        framework = tuple(e for r in code.rows if r["layer"] == "framework" for e in r["paths"])
        focus = {*code.own(module), *(u for u, _ in users or [])}
        paths = sorted({f for f in code.files if f.startswith(framework)} | focus)
        return cls({p: code.text(p) for p in paths}, code.rows, focus=focus)

    @staticmethod
    def _writes(text: str) -> bool:
        return bool(_WRITE.search(text) or (_OPEN.search(text) and _MODE_LITERAL.search(text)))

    def _api(self, row: dict, name: str) -> str | None:
        return next((f"{e}{name}" for e in row["paths"] if e.endswith("/") and f"{e}{name}" in self.sources), None)

    def file(self, path: str) -> _File | None:
        """Разбор файла по требованию; синтаксическая ошибка или нет файла -> None (файл пропускается)."""
        if path not in self.files:
            try:
                self.files[path] = _File(path, self.sources[path])
            except (KeyError, SyntaxError, ValueError):
                self.files[path] = None
        return self.files[path]

    def _node(self, key: Key) -> ast.ClassDef:
        return self.files[key[0]].classes[key[1]]  # type: ignore[union-attr]

    # ------------------------------------------------------------------ классы и предки

    def _find(self, full: str, depth: int = 0) -> Key | None:
        mod, _, name = full.rpartition(".")
        f = self.file(self.path_of[mod]) if mod in self.path_of and depth < 6 else None
        if f is None:
            return None
        if name in f.classes:
            return f.path, name
        return self._find(f.names[name], depth + 1) if name in f.names else None

    def _ancestors(self, key: Key) -> tuple[set[Key], set[str]]:
        """(ключи предков-классов, внешние точечные имена) — транзитивно; базы разрешаются по импортам файла."""
        if key not in self._anc:
            self._anc[key] = keys, ext = set(), set()  # пустая запись — защита от циклов
            f = self.file(key[0])
            for base in f.classes[key[1]].bases if f else []:
                head, _, rest = (_dot(base) or "?").partition(".")
                full = f"{f.names[head]}.{rest}" if rest and head in f.names else f.names.get(head, _dot(base) or "?")
                target = (key[0], head) if not rest and head in f.classes and head != key[1] else self._find(full)
                if target is None:
                    ext.add(full)
                    continue
                keys.add(target)
                for part, acc in zip(self._ancestors(target), (keys, ext)):
                    acc |= part
        return self._anc[key]

    def has_all(self, key: Key, need: set[str]) -> bool:
        """Есть ли у класса с разрешимыми предками все имена `need` (def, присваивания в теле, `self.x =` в методах)."""
        chain = [key, *self._ancestors(key)[0]]
        declared: set[str] = set()
        for item in (i for k in chain for i in self._node(k).body):
            declared |= (
                {item.name} if isinstance(item, _FUNCS) else {t.id for t in _targets(item) if isinstance(t, ast.Name)}
            )
        missing = need - declared
        # текстовый отсев: имя из `self.x =` обязано встретиться в исходнике класса; затем решает AST
        sources = [self.files[k[0]].source(self._node(k)) for k in chain]  # type: ignore[union-attr]
        if missing and any(not any(f"self.{n}" in src for src in sources) for n in missing):
            return False
        for node in (n for k in chain for n in ast.walk(self._node(k)) if missing):
            for t in _targets(node):
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                    missing.discard(t.attr)
        return not missing

    def abstract(self, key: Key) -> set[str]:
        """Абстрактные члены интерфейса: у Protocol — публичные и значимые dunder тела, у ABC — с abstractmethod."""
        if key not in self._abs:
            names: set[str] = set()
            for k in [key, *sorted(self._ancestors(key)[0])]:
                node = self._node(k)
                proto = any(_last(b) == "Protocol" for b in node.bases)
                for item in node.body:
                    if isinstance(item, _FUNCS):
                        name, hit = item.name, proto or any(_last(d) == "abstractmethod" for d in item.decorator_list)
                    elif proto and isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        name, hit = item.target.id, True
                    else:
                        continue
                    if hit and (not name.startswith("_") or name in DUNDERS):
                        names.add(name)
            self._abs[key] = names
        return self._abs[key]

    # ------------------------------------------------------------------ реализации

    def implementations(self, module: str) -> dict[str, list[tuple[str, str, int, str]]]:
        """Имя интерфейса модуля -> [(класс, путь, строка, 'явно'|'структурно'|'структурно (Qt)')] по (имя, путь)."""
        found: dict[str, list[tuple[str, str, int, str]]] = {n: [] for n, _ in self.iface_names.get(module, [])}
        if self._all is None:
            self._all = [(p, n) for p in sorted(self.files) if self.files[p] for n in self.files[p].classes]  # type: ignore[union-attr]
        classes = [k for k in self._all if self.mod[k[0]] == module] if self.structural_only else self._all
        for iname, ipath in self.iface_names.get(module, []):
            need = self.abstract((ipath, iname))
            for key in (k for k in classes if k not in self.ifaces):
                keys, ext = self._ancestors(key)
                kind = None
                if (ipath, iname) in keys:
                    kind = "явно"
                elif self.mod[key[0]] == module and len(need) >= 2 and self.has_all(key, need):
                    kind = "структурно (Qt)" if any(e.startswith(_QT) for e in ext) else "структурно"
                if kind:
                    found[iname].append((key[1], key[0], self._node(key).lineno, kind))
            found[iname].sort()
        return found

    # ------------------------------------------------------------------ П2-П4

    def _defn(self, path: str, name: str, depth: int = 0) -> tuple[str, ast.AST] | None:
        """Определение класса/функции `name`: в файле, затем по цепочке `from .x import name`."""
        f = self.file(path)
        if f is None or depth > 5:
            return None
        node = next((n for n in f.tree.body if isinstance(n, _DEFS) and n.name == name), None)
        if node is not None:
            return path, node
        target = f.names.get(name)
        return self._defn(self.path_of.get(target.rpartition(".")[0], ""), name, depth + 1) if target else None

    def _p2(self, module: str) -> list[tuple[str, str, int, bool]]:
        """(метка, путь, строка, нарушено) символов API: interfaces.py и `__all__` корневого __init__.py."""
        row = next(r for r in self.rows if r["id"] == module)
        ifile, init = self.file(self._api(row, "interfaces.py") or ""), self.file(self._api(row, "__init__.py") or "")
        items = (
            [(ifile.path, n) for n in ifile.tree.body if isinstance(n, _DEFS) and not n.name.startswith("_")]
            if ifile
            else []
        )
        for name in (all_of(init.tree) or []) if init else []:
            if name not in {n.name for _, n in items}:  # type: ignore[attr-defined]
                hit = self._defn(init.path, name) or next(
                    filter(None, (self._defn(p, name) for p in self.by_module[module])), None
                )
                items += [hit] if hit else []
        out = []
        for path, node in items:
            out.append((node.name, path, node.lineno, _bad_doc(node)))  # type: ignore[attr-defined]
            for m in node.body if isinstance(node, ast.ClassDef) else []:
                if isinstance(m, _FUNCS) and not m.name.startswith("_"):
                    out.append((f"{node.name}.{m.name}", path, m.lineno, _bad_doc(m)))  # type: ignore[attr-defined]
        return out

    def _p3(self, module: str) -> list[tuple[str, bool]]:
        """(путь, соответствует) для interfaces.py и __init__.py модуля с публичными именами."""
        out = []
        for path in (p for p in self.by_module[module] if p.rsplit("/", 1)[-1] in _API):
            if (f := self.file(path)) is None:
                continue
            have: set[str] = set()
            public: set[str] = set()
            for node in _top(f.tree):
                if isinstance(node, _DEFS):
                    names = pub = {node.name}
                elif isinstance(node, ast.ImportFrom | ast.Import):
                    names = {a.asname or a.name.split(".")[0] for a in node.names if a.name != "*"}
                    pub = names if isinstance(node, ast.ImportFrom) else set()
                else:
                    names, pub = {t.id for t in _targets(node) if isinstance(t, ast.Name)}, set()
                have |= names
                public |= pub
            if all(n.startswith("_") for n in public):
                continue
            listed = all_of(f.tree)
            out.append((path, listed is not None and ("__getattr__" in have or all(n in have for n in listed))))
        return out

    def _p4(self, module: str) -> list[tuple[str, str, int, bool]]:
        """(путь, функция, строка записи, атомарна ли функция) для записей файла модуля."""
        out = []
        for path in (p for p in self.by_module[module] if self._writes(self.sources[p])):
            if (f := self.file(path)) is None:
                continue
            units = [("<module>", [n for n in f.tree.body if not isinstance(n, _DEFS)])]
            for node in f.tree.body:
                units += [(node.name, [node])] if isinstance(node, _FUNCS) else []
                if isinstance(node, ast.ClassDef):
                    units += [(f"{node.name}.{m.name}", [m]) for m in node.body if isinstance(m, _FUNCS)]
            for label, roots in units:
                calls = [c for r in roots for c in ast.walk(r) if isinstance(c, ast.Call)]
                atomic = any(isinstance(c.func, ast.Attribute) and c.func.attr in _ATOMIC for c in calls)
                out += [(path, label, c.lineno, atomic) for c in calls if _is_write(c)]
        return sorted(set(out))

    def check(self, module: str) -> tuple[list[Finding], dict[str, tuple[int, int]]]:
        """Находки П1-П4 модуля (`warning`, узел `module:<id>`) и доли {'П1': (соответствует, всего), ...}."""
        found: list[Finding] = []

        def add(code: str, detail: str, message: str, source: str) -> None:
            found.append(Finding(code, "warning", f"module:{module}", detail, message, source))

        pairs = [(i, c) for i, items in self.implementations(module).items() for c in items]
        explicit = sum(c[3] == "явно" for _, c in pairs)
        plain = [(i, c) for i, c in pairs if c[3] == "структурно"]
        for iface, (cls, path, line, _) in plain:
            add(
                "P1_IMPL_NOT_INHERITING",
                f"{cls}>{iface}",
                f"Класс {cls} реализует {iface} без наследования (ADR-175 П1)",
                f"{path}:{line}",
            )
        p2, p3, p4 = self._p2(module), self._p3(module), self._p4(module)
        for label, path, line, bad in p2:
            if bad:
                add("P2_DOCSTRING", label, f"У {label} нет docstring Google (ADR-175 П2)", f"{path}:{line}")
        for path, ok in p3:
            if not ok:
                add("P3_NO_ALL", path, f"В {path} нет корректного __all__ (ADR-175 П3)", f"{path}:1")
        for path, label, line, atomic in p4:
            if not atomic:
                add(
                    "P4_DIRECT_WRITE",
                    f"{path}::{label}",
                    f"Запись файла без замены в {label} (ADR-175 П4)",
                    f"{path}:{line}",
                )
        shares = {
            "П1": (explicit, explicit + len(plain)),
            "П2": (sum(not b for *_, b in p2), len(p2)),
            "П3": (sum(ok for _, ok in p3), len(p3)),
            "П4": (sum(a for *_, a in p4), len(p4)),
        }
        return found, shares


class RulesAdapter:
    name = "rules"
    _BASE = 1

    @property
    def version(self) -> int:
        return adapter_version(self._BASE, Path(__file__))

    def collect(self, ctx: BuildContext) -> AdapterOutput:
        """Находки П1-П4 слоя framework: нетестовые .py его модулей читаются пакетно из ревизии сборки."""
        tree = ctx.tree
        rows = modules_for(tree)
        framework = sorted(r["id"] for r in rows if r["layer"] == "framework")
        paths = [p for p in tree.files() if p.endswith(".py") and not is_test(p) and module_of(p, rows) in framework]
        out = AdapterOutput()
        was_enabled = gc.isenabled()
        gc.disable()  # тысячи узлов AST без циклов: сборщик мусора только тормозит разбор
        try:
            scan = Scan(_read(tree.root, tree.ref, paths), rows, structural_only=True)
            for module in framework:
                out.findings += scan.check(module)[0]
        finally:
            if was_enabled:
                gc.enable()
        return out
