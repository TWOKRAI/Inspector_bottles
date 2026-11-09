"""Сканер исходников: неизменяемые факты о `.py`-файлах ревизии git или фикстуры в памяти, кэш по oid блоба (map-A1).

Purpose: один код читает дерево git (`Tree`) и словарь в памяти (`DictSource`) и отдаёт `FileFacts`: импорты
    (hard / lazy / tc), классы, функции, `__all__`, шапку `Tier:`/`Contour:`, команды и потоки. Факты зависят только от
    содержимого блоба, поэтому хранятся в `scan_cache` по `(oid, SCANNER)`: новый SHA разбирает лишь изменённые файлы.
    `ImportIndex` разрешает импорты в пути файлов индекса. Модуль не импортирует `scripts.arch_map` (карта удаляется)
    и адаптеры atlas; разбор перенесён копией из `scripts/arch_map/build.py`.
Public API: Source, DictSource, ImportRec, ClassFact, FileFacts, ScanResult, Resolved, ImportIndex, scan, scan_text,
    resolve_relative, SCANNER, MAX_BLOB_BYTES.
    Правило ошибок: `scan_text` и разбор блоба не бросают; непарсящийся файл — `FileFacts(error=<имя исключения>)`.
Stability: lite

Правка этого файла меняет `SCANNER` и тем самым сбрасывает кэш фактов (цена — один холодный скан).

Шапка модуля (R8): в очищенном докстринге модуля строки `Tier: core|optional|frozen` (значение без учёта регистра;
другое значение — None; побеждает первая допустимая строка) и `Contour: a, b` (элементы через запятую, пустые
отброшены; первая подходящая строка побеждает).
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from scripts.atlas.store import get_scans, put_scans

__all__ = [
    "MAX_BLOB_BYTES",
    "SCANNER",
    "ClassFact",
    "DictSource",
    "FileFacts",
    "ImportIndex",
    "ImportRec",
    "Resolved",
    "ScanResult",
    "Source",
    "resolve_relative",
    "scan",
    "scan_text",
]

SCANNER = "1-" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
MAX_BLOB_BYTES = 1_048_576  # блоб длиннее не декодируется и не разбирается (D1)

IMPORT_GUARDS = frozenset({"ImportError", "ModuleNotFoundError", "Exception", "BaseException"})
TIERS = ("core", "optional", "frozen")
DOC_HEADER = re.compile(r"^(Tier|Contour):[ \t]*(.+)$", re.MULTILINE)


# --------------------------------------------------------------------------- факты


@dataclass(frozen=True)
class ImportRec:
    kind: Literal["hard", "lazy", "tc"]
    line: int
    level: int
    module: str | None
    names: tuple[str, ...]
    is_from: bool
    guarded: bool  # внутри try, чьи обработчики ловят ImportError/Exception


@dataclass(frozen=True)
class ClassFact:
    name: str
    bases: tuple[str, ...]
    line: int
    methods: tuple[str, ...]  # def/async def прямо в теле, без `_private` (dunder остаются), без повторов
    style: Literal["Protocol", "ABC", "class"]


@dataclass(frozen=True)
class FileFacts:
    loc: int = 0  # непустые строки
    doc: str | None = None  # первая непустая строка докстринга модуля
    all: tuple[str, ...] | None = None  # литеральный __all__, иначе None
    classes: tuple[ClassFact, ...] = ()
    functions: tuple[str, ...] = ()  # публичные функции верхнего уровня
    imports: tuple[ImportRec, ...] = ()
    commands: tuple[str, ...] = ()
    threads: tuple[tuple[str, int], ...] = ()  # (имя, строка) вызовов Thread(name=...)
    tier: str | None = None
    contour: tuple[str, ...] | None = None
    error: str | None = None  # имя исключения разбора или "BlobTooLarge"

    def to_json(self) -> str:
        data = {
            "loc": self.loc,
            "doc": self.doc,
            "all": self.all,
            "classes": [[c.name, c.bases, c.line, c.methods, c.style] for c in self.classes],
            "functions": self.functions,
            "imports": [[i.kind, i.line, i.level, i.module, i.names, i.is_from, i.guarded] for i in self.imports],
            "commands": self.commands,
            "threads": self.threads,
            "tier": self.tier,
            "contour": self.contour,
            "error": self.error,
        }
        return json.dumps(data, separators=(",", ":"))  # ASCII: одиночный суррогат не ломает запись в sqlite

    @classmethod
    def from_json(cls, text: str) -> FileFacts:
        """Обратное к `to_json`; тело неверной формы -> исключение (для `scan` это промах кэша)."""
        d = json.loads(text)
        return cls(
            loc=d["loc"],
            doc=d["doc"],
            all=None if d["all"] is None else tuple(d["all"]),
            classes=tuple(ClassFact(n, tuple(b), ln, tuple(m), s) for n, b, ln, m, s in d["classes"]),
            functions=tuple(d["functions"]),
            imports=tuple(
                ImportRec(k, ln, lv, mod, tuple(names), frm, grd) for k, ln, lv, mod, names, frm, grd in d["imports"]
            ),
            commands=tuple(d["commands"]),
            threads=tuple((n, ln) for n, ln in d["threads"]),
            tier=d["tier"],
            contour=None if d["contour"] is None else tuple(d["contour"]),
            error=d["error"],
        )


# --------------------------------------------------------------------------- разбор одного файла (порт из карты)


def is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def catches_import_error(handler: ast.ExceptHandler) -> bool:
    """Обработчик ловит ImportError / ModuleNotFoundError / Exception (или голый except)."""
    if handler.type is None:
        return True
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(leaf_name(x) in IMPORT_GUARDS for x in types)


def collect_imports(tree: ast.Module) -> tuple[ImportRec, ...]:
    """Все импорты модуля с классом hard / lazy / tc (обход с пометкой контекста).

    `tc` побеждает на любой глубине, в том числе во вложенном `def` (отступление от карты, R9).
    """
    found: list[ImportRec] = []

    def handle(stmt: ast.AST, kind: str, guarded: bool) -> None:
        if isinstance(stmt, ast.Import):
            found.extend(ImportRec(kind, stmt.lineno, 0, a.name, (), False, guarded) for a in stmt.names)  # type: ignore[arg-type]
        elif isinstance(stmt, ast.ImportFrom):
            names = tuple(a.name for a in stmt.names)
            found.append(ImportRec(kind, stmt.lineno, stmt.level, stmt.module, names, True, guarded))  # type: ignore[arg-type]
        elif isinstance(stmt, ast.If):
            inner = "tc" if is_type_checking(stmt.test) else kind
            for sub in stmt.body:
                handle(sub, inner, guarded)
            for sub in stmt.orelse:
                handle(sub, kind, guarded)
        elif isinstance(stmt, (ast.Try, ast.TryStar)):
            protected = guarded or any(catches_import_error(h) for h in stmt.handlers)
            for sub in stmt.body:
                handle(sub, kind, protected)
            for sub in [*stmt.handlers, *stmt.orelse, *stmt.finalbody]:
                handle(sub, kind, guarded)
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            # тело def выполняется позже: try вокруг него импорт не защищает;
            # под `if TYPE_CHECKING` функции в рантайме нет -> tc
            visit(stmt, "tc" if kind == "tc" else "lazy", False)
        else:
            visit(stmt, kind, guarded)

    def visit(node: ast.AST, kind: str, guarded: bool) -> None:
        for child in ast.iter_child_nodes(node):
            handle(child, kind, guarded)

    visit(tree, "hard", False)
    return tuple(found)


def leaf_name(expr: ast.expr) -> str:
    while isinstance(expr, ast.Subscript):
        expr = expr.value
    if isinstance(expr, ast.Name):
        return expr.id
    return expr.attr if isinstance(expr, ast.Attribute) else ""


def class_style(node: ast.ClassDef, known: dict[str, str]) -> str:
    """Protocol / ABC / class; наследование от интерфейса того же файла передаёт его стиль."""
    leaves = [leaf_name(b) for b in node.bases]
    if "Protocol" in leaves:
        return "Protocol"
    metas = [leaf_name(k.value) for k in node.keywords if k.arg == "metaclass"]
    if "ABC" in leaves or "ABCMeta" in metas:
        return "ABC"
    for leaf in leaves:
        if known.get(leaf, "class") != "class":
            return known[leaf]
    return "class"


def read_all(tree: ast.Module) -> tuple[str, ...] | None:
    """Литеральный `__all__` (в т. ч. с `+=`); нет или не литерал — None."""
    value: tuple[str, ...] | None = None
    for stmt in tree.body:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
                value = literal_names(stmt.value)
        elif isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == "__all__":
            extra = literal_names(stmt.value) if isinstance(stmt.op, ast.Add) else None
            value = None if value is None or extra is None else value + extra
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            func = stmt.value.func  # __all__.extend(...) и т. п. — не разбираем, считаем не литералом
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "__all__":
                return None
    return value


def literal_names(expr: ast.expr | None) -> tuple[str, ...] | None:
    if not isinstance(expr, (ast.List, ast.Tuple)):
        return None
    if all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in expr.elts):
        return tuple(e.value for e in expr.elts)  # type: ignore[union-attr]
    return None


def literal_str(expr: ast.expr | None) -> str | None:
    return expr.value if isinstance(expr, ast.Constant) and isinstance(expr.value, str) else None


def collect_derived(tree: ast.Module) -> tuple[tuple[str, ...], tuple[tuple[str, int], ...]]:
    """Команды (commands = {...} в классах, register_command("...")) и потоки Thread(name=...)."""
    commands: set[str] = set()
    threads: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    targets, value = stmt.targets, stmt.value
                elif isinstance(stmt, ast.AnnAssign):
                    targets, value = [stmt.target], stmt.value
                else:
                    continue
                if isinstance(value, ast.Dict) and any(isinstance(x, ast.Name) and x.id == "commands" for x in targets):
                    commands.update(k for k in map(literal_str, value.keys) if k)
        elif isinstance(node, ast.Call):
            func = node.func
            if leaf_name(func) == "register_command" and node.args:
                name = literal_str(node.args[0])
                if name:
                    commands.add(name)
            is_thread = (isinstance(func, ast.Name) and func.id == "Thread") or (
                isinstance(func, ast.Attribute)
                and func.attr == "Thread"
                and isinstance(func.value, ast.Name)
                and func.value.id == "threading"
            )
            if is_thread:
                for kw in node.keywords:
                    if kw.arg == "name":
                        threads.append((literal_str(kw.value) or ast.unparse(kw.value), node.lineno))
    threads.sort(key=lambda x: x[1])  # sort устойчив: порядок обхода внутри строки сохраняется
    return tuple(sorted(commands)), tuple(threads)


def read_doc_headers(doc: str) -> tuple[str | None, tuple[str, ...] | None]:
    """Строки `Tier: core|optional|frozen` и `Contour: a, b` из докстринга; первая подходящая побеждает."""
    tier: str | None = None
    contour: tuple[str, ...] | None = None
    for match in DOC_HEADER.finditer(doc):
        value = match.group(2).strip()
        if match.group(1) == "Tier":
            if tier is None and value.lower() in TIERS:
                tier = value.lower()
        elif contour is None:
            contour = tuple(x.strip() for x in value.split(",") if x.strip()) or None
    return tier, contour


def _is_dunder(name: str) -> bool:
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _class_fact(node: ast.ClassDef, styles: dict[str, str]) -> ClassFact:
    names = (m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)))
    methods = tuple(dict.fromkeys(n for n in names if not n.startswith("_") or _is_dunder(n)))
    styles[node.name] = style = class_style(node, styles)
    return ClassFact(node.name, tuple(ast.unparse(b) for b in node.bases), node.lineno, methods, style)  # type: ignore[arg-type]


def _loc(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def scan_text(text: str) -> FileFacts:
    """Факты исходника; не бросает никогда. Зависят только от текста (R5): ни пути, ни `is_init`."""
    text = text.removeprefix("﻿")
    try:
        loc = _loc(text)
    except Exception:  # noqa: BLE001 — контракт «не бросает»
        loc = 0
    try:
        tree = ast.parse(text)
        styles: dict[str, str] = {}
        classes: list[ClassFact] = []
        functions: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                classes.append(_class_fact(node, styles))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                functions.append(node.name)
        imports = collect_imports(tree)
        commands, threads = collect_derived(tree)
        doc = ast.get_docstring(tree) or ""
        tier, contour = read_doc_headers(doc)
        return FileFacts(
            loc=loc,
            doc=next((x.strip() for x in doc.splitlines() if x.strip()), None),
            all=read_all(tree),
            classes=tuple(classes),
            functions=tuple(functions),
            imports=imports,
            commands=commands,
            threads=threads,
            tier=tier,
            contour=contour,
        )
    except Exception as exc:  # noqa: BLE001 — SyntaxError, ValueError, RecursionError, MemoryError, ...
        return FileFacts(loc=loc, error=type(exc).__name__)


def _facts_of_bytes(data: bytes) -> FileFacts:
    """Байты блоба -> факты: предел размера ДО декодирования, потом utf-8 строго."""
    if len(data) > MAX_BLOB_BYTES:
        return FileFacts(error="BlobTooLarge")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return FileFacts(error="UnicodeDecodeError")
    return scan_text(text)


# --------------------------------------------------------------------------- источники и scan


class Source(Protocol):
    def files(self) -> list[str]: ...

    def oids(self) -> dict[str, str]: ...

    def read_many(self, paths: Sequence[str]) -> dict[str, bytes | None]: ...


def _blob_oid(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class DictSource:
    """Файлы в памяти; oid — sha1 блоба git, так что `oids()` совпадает с `Tree.oids()` для того же содержимого."""

    def __init__(self, files: dict[str, str | bytes]) -> None:
        self._data = {p: v.encode("utf-8") if isinstance(v, str) else bytes(v) for p, v in files.items()}
        self._oids = {p: _blob_oid(v) for p, v in self._data.items()}

    def files(self) -> list[str]:
        return list(self._data)

    def oids(self) -> dict[str, str]:
        return dict(self._oids)

    def read_many(self, paths: Sequence[str]) -> dict[str, bytes | None]:
        return {p: self._data.get(p) for p in paths}


@dataclass(frozen=True)
class ScanResult:
    facts: dict[str, FileFacts]  # только прочитанные пути, порядок как в `paths`
    missing: tuple[str, ...]  # запрошены, но не прочитаны (нет в oids: ссылка, gitlink, путь с переводом строки)
    parsed: int  # различных oid, разобранных заново
    hits: int  # различных oid из кэша


def scan(source: Source, paths: Sequence[str], cache: sqlite3.Connection | None = None) -> ScanResult:
    """Факты файлов `paths`; разбор — по одному разу на oid, кэш `scan_cache` — по `(oid, SCANNER)`."""
    scanner = SCANNER  # читается при вызове: тест подменяет константу модуля
    wanted = list(dict.fromkeys(paths))
    oids = source.oids()
    missing = [p for p in wanted if "\n" in p or p not in oids]  # перенос в пути сдвинул бы ответы cat-file
    skip = set(missing)
    present = [p for p in wanted if p not in skip]

    by_oid: dict[str, FileFacts] = {}
    first_path: dict[str, str] = {}  # oid -> первый путь с этим блобом: два пути с одним oid разбираются один раз
    for p in present:
        first_path.setdefault(oids[p], p)
    cached = get_scans(cache, scanner, list(first_path)) if cache is not None and first_path else {}
    for oid, body in cached.items():
        try:
            by_oid[oid] = FileFacts.from_json(body)
        except Exception:  # noqa: BLE001 — битое тело кэша: промах, строку перезапишет put_scans
            continue
    hits = len(by_oid)

    todo = {oid: p for oid, p in first_path.items() if oid not in by_oid}
    fresh: list[tuple[str, str]] = []
    if todo:
        blobs = source.read_many(list(todo.values()))
        for oid, path in todo.items():
            data = blobs.get(path)
            if data is None:  # файл исчез между oids() и чтением
                continue
            facts = by_oid[oid] = _facts_of_bytes(data)
            fresh.append((oid, facts.to_json()))
    if fresh and cache is not None:
        put_scans(cache, scanner, fresh)

    gone = [p for p in present if oids[p] not in by_oid]
    gone_set = set(gone)
    facts_by_path = {p: by_oid[oids[p]] for p in present if p not in gone_set}
    missing += gone
    return ScanResult(facts_by_path, tuple(missing), len(fresh), hits)


# --------------------------------------------------------------------------- разрешение импортов


def resolve_relative(level: int, module: str | None, current: str, is_init: bool) -> str | None:
    """Абсолютное имя цели относительного импорта.

    У `__init__.py` одна точка — сам пакет, у обычного файла — его каталог.
    """
    base = current.split(".")
    drop = level - 1 if is_init else level
    if drop > len(base):
        return None
    trimmed = base[: len(base) - drop] if drop else base
    if not trimmed:
        return None
    return ".".join(trimmed + ([module] if module else []))


@dataclass(frozen=True)
class Resolved:
    status: Literal["internal", "external", "unresolved"]
    targets: tuple[tuple[str, tuple[str, ...]], ...] = ()  # ((путь-цель, имена), ...)


class ImportIndex:
    """Индекс модулей по путям `*.py`; каталог без `__init__.py` модулем не считается (D2)."""

    def __init__(self, paths: Iterable[str]) -> None:
        self._module_of: dict[str, str] = {}  # путь -> имя модуля
        self._path_of: dict[str, str] = {}  # имя модуля -> путь
        for path in paths:
            if not path.endswith(".py"):
                continue
            name = path[: -len(".py")].replace("/", ".")
            if path == "__init__.py" or path.endswith("/__init__.py"):
                name = name[: -len("__init__")].rstrip(".")
            if not name:
                continue
            self._module_of[path] = name
            self._path_of[name] = path
        self.roots: frozenset[str] = frozenset(name.split(".")[0] for name in self._module_of.values())

    @staticmethod
    def _is_init(path: str) -> bool:
        return path == "__init__.py" or path.endswith("/__init__.py")

    def resolve(self, path: str, rec: ImportRec) -> Resolved:
        if rec.level:
            current = self._module_of.get(path)
            if current is None:
                return Resolved("unresolved")
            base = resolve_relative(rec.level, rec.module, current, self._is_init(path))
        else:
            base = rec.module
            if not base or base.split(".")[0] not in self.roots:
                return Resolved("external")
        target = self._path_of.get(base) if base else None
        if target is None:
            return Resolved("unresolved")
        if not rec.is_from:
            return Resolved("internal", ((target, ()),))
        hits: dict[str, list[str]] = {}
        for name in rec.names:
            sub = self._path_of.get(f"{base}.{name}") if self._is_init(target) else None
            hits.setdefault(sub or target, []).append(name)  # `from pkg import sub` -> файл sub
        return Resolved("internal", tuple((p, tuple(names)) for p, names in hits.items()))
