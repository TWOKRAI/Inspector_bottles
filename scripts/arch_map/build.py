"""Генератор модели архитектуры: узлы, рёбра-импорты, интерфейсы, находки — из кода, без импорта кода.

Контракт — docs/arch-map/README.md (schema = 1). Запуск из любого места:

    python scripts/arch_map/build.py [--root <repo>] [--out docs/arch-map] [--check]

Конвейер из чистых функций:
    collect_files -> build_nodes -> build_edges -> unit_specs -> findings -> write_outputs.
Классификация импортов (hard / lazy / tc) и разбор относительных импортов — как в
scripts/arch_graph/ast_graph.py; отличие одно: `def` внутри `if` считается lazy (там — hard).
Зависимости: stdlib + PyYAML.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:  # запуск как скрипта: пакета `scripts` в sys.path ещё нет
    sys.path.insert(0, str(_REPO))
from scripts.atlas.modules import OTHER, load_modules, resolve  # noqa: E402

SCHEMA = 1
# Слои и их порядок: первые четыре — цепочка (импорт разрешён справа налево), backend_ctl — вне цепочки.
LAYERS = ("multiprocess_framework", "Services", "Plugins", "multiprocess_prototype", "backend_ctl")
LAYER_ORDER = {name: i for i, name in enumerate(LAYERS)}
EXTERNAL = "backend_ctl"
# Кто из цепочки не должен знать о backend_ctl (prototype его импортировать вправе).
NO_EXTERNAL_IMPORT = frozenset(LAYERS[:3])
KINDS = ("hard", "lazy", "tc")
SKIP_DIRS = frozenset({"__pycache__", "docs"})  # docs — примеры, не прод-код
IMPORT_GUARDS = frozenset({"ImportError", "ModuleNotFoundError", "Exception", "BaseException"})
DECLARED = ("purpose", "tier", "contour")  # поля карточки, которые объявляет человек (в докстринге юнита)
TIERS = ("core", "optional", "frozen")
DOC_HEADER = re.compile(r"^(Tier|Contour):[ \t]*(.+)$", re.MULTILINE)
RECIPE_SKIP_DIRS = frozenset({"__pycache__", "node_modules", "graphify-out"})
INACTIVE_PARTS = frozenset({"tests", "fixtures", "archive"})  # рецепты в таких каталогах — не живые
TEST_DIRS = frozenset({"tests", "test"})
RECIPE_LINE = re.compile(r"""^\s*(?:-\s+)?plugin_class:\s*["']?([A-Za-z_][\w.]*)["']?\s*(?:#.*)?$""")
SYNTHETIC = "__root__"

# Правила находок: порядок = порядок в отчётах; текст — для findings.md.
RULES = {
    "layer-reverse": "импорт против цепочки слоёв framework < Services < Plugins < prototype (tc — warn); "
    "framework/Services/Plugins не должны импортировать backend_ctl",
    "unit-cycle": "сильно связная компонента из 2+ юнитов; error, если внутри есть цикл по hard-рёбрам, иначе warn",
    "deep-import": "импорт из другого юнита мимо его витрины: цель — не `__init__` юнита, не его `interfaces` "
    "и не `__init__` пакета с литеральным `__all__`, в котором есть все импортируемые имена",
    "private-import": "из другого юнита импортируется имя или модуль с `_` в начале",
    "unit-hygiene": "у юнита нет interfaces.py, README.md, STATUS.md или тестов",
    "unit-undeclared": "у юнита не объявлено поле карточки (purpose, tier, contour)",
    "registry-drift": "юнит графа не найден в modules.yaml либо путь из modules.yaml не существует на диске",
    "unresolved-relative": "относительный импорт не разрешается в файл графа (info внутри try/except ImportError)",
    "parse-error": "файл не разобран ast.parse (синтаксис, кодировка): в графе он без рёбер и классов",
    "unresolved-absolute": "абсолютный импорт внутри корней не разрешается в файл графа (info — цель тестовый файл)",
    "recipe-unknown-plugin": "plugin_class в рецепте не соответствует ни одному юниту графа",
}
SEVERITY_ORDER = ("error", "warn", "info")


# --------------------------------------------------------------------------- модели данных


@dataclass(frozen=True)
class UnitRef:
    """Юнит, которому принадлежит файл."""

    id: str
    path: str  # каталог юнита от корня репозитория (posix)
    parent: str  # id слоя или группы плагинов
    synthetic: bool  # <слой>.__root__ / <группа>.__root__


@dataclass
class SourceFile:
    rel: str
    parts: tuple[str, ...]
    file_id: str
    module: str  # имя для импортов: у `__init__` — имя пакета
    is_init: bool
    unit: UnitRef


@dataclass
class ImportRec:
    kind: str  # hard | lazy | tc
    line: int
    level: int
    module: str | None
    names: list[str]
    is_from: bool
    guarded: bool = False  # внутри try, чьи обработчики ловят ImportError/Exception


@dataclass
class ParsedFile:
    loc: int = 0
    classes: list[dict] = field(default_factory=list)  # name, bases, line, methods
    styles: dict[str, str] = field(default_factory=dict)  # имя класса -> Protocol | ABC | class
    functions: list[str] = field(default_factory=list)
    imports: list[ImportRec] = field(default_factory=list)
    all_names: list[str] | None = None  # литеральный __all__, иначе None
    doc_line: str | None = None  # первая непустая строка докстринга модуля
    doc_tier: str | None = None  # строка `Tier: …` докстринга (core|optional|frozen)
    doc_contour: list[str] | None = None  # строка `Contour: a, b` докстринга
    commands: list[str] = field(default_factory=list)  # литеральные имена команд
    threads: list[dict] = field(default_factory=list)  # {name, line} вызовов Thread(name=...)


@dataclass
class Graph:
    nodes: dict[str, dict] = field(default_factory=dict)
    parsed: dict[str, ParsedFile] = field(default_factory=dict)
    file_unit: dict[str, str] = field(default_factory=dict)
    file_path: dict[str, str] = field(default_factory=dict)
    file_module: dict[str, str] = field(default_factory=dict)
    file_is_init: dict[str, bool] = field(default_factory=dict)
    module_index: dict[str, str] = field(default_factory=dict)  # имя модуля -> id файла
    units: dict[str, UnitRef] = field(default_factory=dict)
    unit_files: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    unit_tests: Counter = field(default_factory=Counter)
    unresolved: list[tuple[str, int, str, bool]] = field(default_factory=list)  # (файл, строка, текст, guarded)
    pairs: dict[tuple[str, str], Counter] = field(default_factory=dict)  # (юнит-src, юнит-dst) -> счётчик kind
    parse_errors: list[tuple[str, int | None, str]] = field(default_factory=list)  # (файл, строка, ошибка)
    unresolved_abs: list[tuple[str, int, str, bool]] = field(default_factory=list)  # (файл, строка, текст, тест)
    test_modules: set[str] = field(default_factory=set)  # имена модулей, исключённых как тесты
    recipe_refs: list[tuple[str, int, str, str | None, bool]] = field(default_factory=list)
    # recipe_refs: (yaml, строка, значение, юнит, неживой)


def layer_of(node_id: str) -> str:
    return node_id.split(".", 1)[0]


# --------------------------------------------------------------------------- 1. сбор файлов


def is_test_path(parts: tuple[str, ...]) -> bool:
    name = parts[-1]
    return any(p in TEST_DIRS for p in parts[:-1]) or name.startswith("test_") or name == "conftest.py"


def locate_unit(parts: tuple[str, ...]) -> UnitRef:
    """Юнит файла по его пути (parts = компоненты пути от корня, включая имя файла)."""
    layer = parts[0]
    n = len(parts)
    if layer == "multiprocess_framework" and n >= 4 and parts[1] == "modules":
        return UnitRef(f"{layer}.modules.{parts[2]}", "/".join(parts[:3]), layer, False)
    if layer == "Services" and n >= 3:
        return UnitRef(f"{layer}.{parts[1]}", "/".join(parts[:2]), layer, False)
    if layer == "Plugins" and n >= 3:
        group = f"{layer}.{parts[1]}"
        if n >= 4:
            return UnitRef(f"{group}.{parts[2]}", "/".join(parts[:3]), group, False)
        return UnitRef(f"{group}.{SYNTHETIC}", "/".join(parts[:2]), group, True)  # файл прямо в каталоге группы
    if layer == "multiprocess_prototype" and n >= 3:
        return UnitRef(f"{layer}.{parts[1]}", "/".join(parts[:2]), layer, False)
    if layer == EXTERNAL:
        return UnitRef(f"{layer}.{SYNTHETIC}", layer, layer, False)  # backend_ctl — один настоящий юнит
    return UnitRef(f"{layer}.{SYNTHETIC}", layer, layer, True)  # файлы прямо в корне слоя


def collect_files(root: Path) -> tuple[list[SourceFile], list[str], set[str]]:
    """Исходные файлы графа и id юнитов-владельцев для каждого тестового файла test_*.py."""
    sources: list[SourceFile] = []
    test_units: list[str] = []
    test_modules: set[str] = set()
    for layer in LAYERS:
        top = root / layer
        if not top.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
            for name in sorted(filenames):
                if not name.endswith(".py"):
                    continue
                rel = (Path(dirpath) / name).relative_to(root).as_posix()
                parts = tuple(rel.split("/"))
                if is_test_path(parts):
                    test_modules.add(".".join(parts)[: -len(".py")].removesuffix(".__init__"))
                    if name.startswith("test_"):
                        test_units.append(locate_unit(parts).id)
                    continue
                file_id = ".".join(parts)[: -len(".py")]
                is_init = name == "__init__.py"
                module = file_id[: -len(".__init__")] if is_init else file_id
                sources.append(SourceFile(rel, parts, file_id, module, is_init, locate_unit(parts)))
    return sources, test_units, test_modules


# --------------------------------------------------------------------------- 2. узлы и разбор файлов


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


def collect_imports(tree: ast.Module) -> list[ImportRec]:
    """Все импорты модуля с классом hard / lazy / tc (обход с пометкой контекста)."""
    found: list[ImportRec] = []

    def handle(stmt: ast.AST, kind: str, guarded: bool) -> None:
        if isinstance(stmt, ast.Import):
            found.extend(ImportRec(kind, stmt.lineno, 0, a.name, [], False, guarded) for a in stmt.names)
        elif isinstance(stmt, ast.ImportFrom):
            names = [a.name for a in stmt.names]
            found.append(ImportRec(kind, stmt.lineno, stmt.level, stmt.module, names, True, guarded))
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
            visit(stmt, "lazy", False)  # тело def выполняется позже: try вокруг него импорт не защищает
        else:
            visit(stmt, kind, guarded)

    def visit(node: ast.AST, kind: str, guarded: bool) -> None:
        for child in ast.iter_child_nodes(node):
            handle(child, kind, guarded)

    visit(tree, "hard", False)
    return found


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


def read_all(tree: ast.Module) -> list[str] | None:
    """Литеральный `__all__` (в т. ч. с `+=`); нет или не литерал — None."""
    value: list[str] | None = None
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


def literal_names(expr: ast.expr | None) -> list[str] | None:
    if not isinstance(expr, (ast.List, ast.Tuple)):
        return None
    if all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in expr.elts):
        return [e.value for e in expr.elts]  # type: ignore[union-attr]
    return None


def literal_str(expr: ast.expr | None) -> str | None:
    return expr.value if isinstance(expr, ast.Constant) and isinstance(expr.value, str) else None


def collect_derived(tree: ast.Module, parsed: ParsedFile) -> None:
    """Команды (commands = {...} в классах, register_command("...")) и потоки Thread(name=...)."""
    commands: set[str] = set()
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
                        text = literal_str(kw.value) or ast.unparse(kw.value)
                        parsed.threads.append({"name": text, "line": node.lineno})
    parsed.commands = sorted(commands)
    parsed.threads.sort(key=lambda x: x["line"])


def read_doc_headers(doc: str) -> tuple[str | None, list[str] | None]:
    """Строки `Tier: core|optional|frozen` и `Contour: a, b` из докстринга юнита; первая подходящая побеждает."""
    tier: str | None = None
    contour: list[str] | None = None
    for match in DOC_HEADER.finditer(doc):
        value = match.group(2).strip()
        if match.group(1) == "Tier":
            if tier is None and value.lower() in TIERS:
                tier = value.lower()
        elif contour is None:
            contour = [x.strip() for x in value.split(",") if x.strip()] or None
    return tier, contour


def parse_source(text: str, is_init: bool) -> ParsedFile:
    """Разбор одного файла: LOC (непустые строки), классы, публичные функции, импорты."""
    parsed = ParsedFile(loc=sum(1 for line in text.splitlines() if line.strip()))
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = [m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
            public = [m for i, m in enumerate(methods) if not m.startswith("_") and m not in methods[:i]]
            parsed.styles[node.name] = class_style(node, parsed.styles)
            parsed.classes.append(
                {
                    "name": node.name,
                    "bases": [ast.unparse(b) for b in node.bases],
                    "line": node.lineno,
                    "methods": public,
                }
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            parsed.functions.append(node.name)
    parsed.imports = collect_imports(tree)
    collect_derived(tree, parsed)
    if is_init:
        parsed.all_names = read_all(tree)
        doc = ast.get_docstring(tree) or ""
        parsed.doc_line = next((x.strip() for x in doc.splitlines() if x.strip()), None)
        parsed.doc_tier, parsed.doc_contour = read_doc_headers(doc)
    return parsed


def build_nodes(root: Path, sources: list[SourceFile], test_units: list[str], test_modules: set[str]) -> Graph:
    """Дерево узлов: слой -> (группа) -> юнит -> пакет -> файл, плюс разобранные файлы."""
    g = Graph(test_modules=test_modules)
    for order, layer in enumerate(LAYERS):
        g.nodes[layer] = {"id": layer, "kind": "layer", "parent": None, "name": layer, "order": order}
    for src in sorted(sources, key=lambda s: s.file_id):
        ref = src.unit
        if ref.parent not in g.nodes:  # группа плагинов
            g.nodes[ref.parent] = {
                "id": ref.parent, "kind": "group", "parent": layer_of(ref.parent),
                "name": ref.parent.split(".")[-1], "path": ref.parent.replace(".", "/"),
            }  # fmt: skip
        if ref.id not in g.nodes:
            g.units[ref.id] = ref
            name = SYNTHETIC if ref.synthetic else ref.path.split("/")[-1]
            g.nodes[ref.id] = {
                "id": ref.id, "kind": "unit", "parent": ref.parent, "name": name, "path": ref.path, "spec": None,
            }  # fmt: skip
            if ref.synthetic:
                g.nodes[ref.id]["synthetic"] = True
        parent = ref.id
        if not ref.synthetic:  # у синтетических юнитов каталоги ниже — это чужие юниты, пакетов не заводим
            unit_parts = ref.path.split("/")
            dirs = src.parts[len(unit_parts) : -1]
            for depth in range(1, len(dirs) + 1):
                pkg_id = ".".join(unit_parts + list(dirs[:depth]))
                if pkg_id not in g.nodes:
                    g.nodes[pkg_id] = {
                        "id": pkg_id, "kind": "package", "parent": parent, "name": dirs[depth - 1],
                        "path": "/".join(src.parts[: len(unit_parts) + depth]),
                    }  # fmt: skip
                parent = pkg_id
        try:
            parsed = parse_source((root / src.rel).read_text(encoding="utf-8"), src.is_init)
        except (SyntaxError, ValueError, UnicodeDecodeError, OSError) as exc:
            g.parse_errors.append((src.file_id, getattr(exc, "lineno", None), f"{type(exc).__name__}: {exc}"))
            parsed = ParsedFile()
        g.parsed[src.file_id] = parsed
        g.nodes[src.file_id] = {
            "id": src.file_id, "kind": "file", "parent": parent, "name": src.parts[-1][: -len(".py")], "path": src.rel,
            "loc": parsed.loc, "classes": parsed.classes, "functions": parsed.functions,
        }  # fmt: skip
        g.file_unit[src.file_id] = ref.id
        g.file_path[src.file_id] = src.rel
        g.file_module[src.file_id] = src.module
        g.file_is_init[src.file_id] = src.is_init
        g.module_index[src.module] = src.file_id
        g.unit_files[ref.id].append(src.file_id)
    for unit_id in test_units:
        g.unit_tests[unit_id] += 1
    return g


# --------------------------------------------------------------------------- 3. рёбра


def resolve_relative(level: int, module: str | None, current: str, is_init: bool) -> str | None:
    """Абсолютное имя цели относительного импорта.

    У `__init__.py` одна точка — сам пакет, у обычного файла — его каталог (см. ast_graph.resolve).
    """
    base = current.split(".")
    drop = level - 1 if is_init else level
    if drop > len(base):
        return None
    trimmed = base[: len(base) - drop] if drop else base
    if not trimmed:
        return None
    return ".".join(trimmed + ([module] if module else []))


def import_text(rec: ImportRec) -> str:
    if not rec.is_from:
        return f"import {rec.module}"
    return f"from {'.' * rec.level}{rec.module or ''} import {', '.join(rec.names)}"


def resolve_import(g: Graph, file_id: str, rec: ImportRec) -> list[tuple[str, list[str]]] | None:
    """[(файл-цель, имена)] для импорта; [] — вне графа; None — относительный импорт не разрешился."""
    if rec.level:
        base = resolve_relative(rec.level, rec.module, g.file_module[file_id], g.file_is_init[file_id])
    else:
        base = rec.module
        if not base or base.split(".")[0] not in LAYER_ORDER:
            return []  # внешняя библиотека
    target = g.module_index.get(base) if base else None
    if target is None:
        if rec.level:
            return None
        under_test = base in g.test_modules or any(f"{base}.{n}" in g.test_modules for n in rec.names)
        g.unresolved_abs.append((file_id, rec.line, import_text(rec), under_test))
        return []
    if not rec.is_from:
        return [(target, [])]
    hits: dict[str, list[str]] = {}
    for name in rec.names:
        sub = g.module_index.get(f"{base}.{name}") if g.file_is_init[target] else None
        hits.setdefault(sub or target, []).append(name)  # `from pkg import sub` -> файл sub
    return list(hits.items())


def build_edges(g: Graph) -> list[dict]:
    """Одно ребро на оператор import между двумя файлами графа; находит и считает пары юнитов."""
    acc: dict[tuple[str, str, str, int], dict] = {}
    for file_id in sorted(g.parsed):
        for rec in g.parsed[file_id].imports:
            result = resolve_import(g, file_id, rec)
            if result is None:
                g.unresolved.append((file_id, rec.line, import_text(rec), rec.guarded))
                continue
            for dst, names in result:
                if dst != file_id:
                    item = acc.setdefault((file_id, dst, rec.kind, rec.line), {"names": [], "guarded": rec.guarded})
                    item["names"].extend(n for n in names if n not in item["names"])
                    item["guarded"] = item["guarded"] and rec.guarded
    edges = []
    for (s, d, k, ln), item in acc.items():
        edge = {"src": s, "dst": d, "kind": k, "names": item["names"], "line": ln}
        if item["guarded"]:  # импорт под try/except ImportError: необязательная зависимость
            edge["guarded"] = True
        edges.append(edge)
    edges.sort(key=lambda e: (e["src"], e["line"], e["dst"], e["kind"]))
    pairs: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for e in edges:
        su, du = g.file_unit[e["src"]], g.file_unit[e["dst"]]
        if su != du:
            pairs[(su, du)][e["kind"]] += 1
    g.pairs = dict(pairs)
    return edges


# --------------------------------------------------------------------------- 4. спецификации юнитов


def json_safe(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def load_registry(root: Path) -> list[dict] | None:
    """Корневой modules.yaml через резолвер атласа; нет файла или не разобрался — None."""
    path = root / "modules.yaml"
    if not path.is_file():
        return None
    try:
        return load_modules(path)
    except (ValueError, OSError, yaml.YAMLError, AttributeError) as exc:
        print(f"ПРЕДУПРЕЖДЕНИЕ: modules.yaml не прочитан: {exc}", file=sys.stderr)
        return None


def count_adr(path: Path) -> int | None:
    """Число заголовков markdown с `ADR-` в DECISIONS.md; нет файла — None."""
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    return sum(1 for line in lines if re.match(r"#{1,6}\s", line) and "ADR-" in line)


def build_card(root: Path, g: Graph, ref: UnitRef, registry: list[dict] | None) -> dict:
    """Карточка юнита из него самого: объявленное (докстринг `__init__.py`, иначе modules.yaml) + выведенное из кода."""
    sources: dict[str, str] = {}
    prefix = ref.path.replace("/", ".")
    folder = root / ref.path
    init_id = f"{prefix}.__init__"
    init = None if ref.synthetic else g.parsed.get(init_id)
    declared = {
        "purpose": init.doc_line if init else None,
        "tier": init.doc_tier if init else None,
        "contour": init.doc_contour if init else None,
    }
    row = None
    if registry is not None and not ref.synthetic:
        row_id = resolve(ref.path + "/", registry)
        row = next((r for r in registry if r["id"] == row_id), None) if row_id != OTHER else None
    card: dict = {}
    for key in DECLARED:
        if declared.get(key):
            card[key], sources[key] = declared[key], g.file_path[init_id]
        elif row is not None and key in ("purpose", "tier") and row.get(key) is not None:
            card[key], sources[key] = json_safe(row[key]), "modules.yaml"
        else:
            card[key] = None
    card["adr_count"] = None if ref.synthetic else count_adr(folder / "DECISIONS.md")
    if card["adr_count"] is not None:
        sources["adr_count"] = f"{ref.path}/DECISIONS.md"
    files = sorted(g.unit_files[ref.id])
    card["commands"] = sorted({c for f in files for c in g.parsed[f].commands})
    card["threads"] = [
        {"name": th["name"], "where": f"{g.file_path[f]}:{th['line']}"} for f in files for th in g.parsed[f].threads
    ]
    for key in ("commands", "threads"):
        if card[key]:
            sources[key] = ref.path
    card["sources"] = sources
    return card


def iface_entries(g: Graph, file_id: str, only: set[str] | None = None) -> list[dict]:
    parsed = g.parsed[file_id]
    return [
        {
            "name": c["name"],
            "style": parsed.styles[c["name"]],
            "file": g.file_path[file_id],
            "line": c["line"],
            "methods": c["methods"],
        }
        for c in parsed.classes
        if only is None or c["name"] in only
    ]


def unit_interfaces(g: Graph, unit_id: str, edges_by_src: dict[str, list[dict]]) -> list[dict]:
    """Классы из interfaces.py / пакета interfaces; если там только реэкспорт — один шаг внутри юнита."""
    base = unit_id
    files = [f for f in g.unit_files[unit_id] if f == f"{base}.interfaces" or f.startswith(f"{base}.interfaces.")]
    found = [entry for f in files for entry in iface_entries(g, f)]
    if not found:
        for f in files:
            for e in edges_by_src[f]:
                if e["kind"] != "tc" and g.file_unit[e["dst"]] == unit_id and e["dst"] not in files:
                    found.extend(iface_entries(g, e["dst"], set(e["names"])))
    unique = {(i["file"], i["name"]): i for i in found}
    return sorted(unique.values(), key=lambda i: (i["file"], i["line"]))


def unit_classes_top(
    g: Graph, unit_id: str, prefix: str, all_names: list[str] | None, edges_by_src: dict
) -> list[dict]:
    """Классы юнита, чьи имена входят в __all__ (определение ищется в файлах юнита)."""
    if not all_names:
        return []
    defs: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for f in sorted(g.unit_files[unit_id]):
        for c in g.parsed[f].classes:
            defs[c["name"]].append((f, c))
    via_init = {n: e["dst"] for e in edges_by_src[f"{prefix}.__init__"] for n in e["names"]}
    top = []
    for name in all_names:
        options = defs.get(name)
        if options:
            pick = next((o for o in options if o[0] == via_init.get(name)), options[0])
            top.append({"name": name, "bases": pick[1]["bases"], "file": g.file_path[pick[0]], "line": pick[1]["line"]})
    return top


def skip_recipe_dir(rel: str, name: str) -> bool:
    """Каталоги, где `plugin_class:` не ищем: точечные, кэши, логи, выгрузки."""
    return (
        name.startswith(".")
        or name.startswith("logs")
        or name in RECIPE_SKIP_DIRS
        or rel == "data/atlas"
        or rel.startswith("data/atlas/")
    )


def scan_recipes(root: Path, g: Graph) -> None:
    """Строки `plugin_class: <dotted>` в *.yaml / *.yml всего дерева -> юнит по самому длинному префиксу."""
    prefixes = sorted(
        ((ref.path.replace("/", "."), uid) for uid, ref in g.units.items() if not ref.synthetic),
        key=lambda pair: -len(pair[0]),
    )
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if not skip_recipe_dir((here / d).relative_to(root).as_posix(), d))
        for name in sorted(filenames):
            if not name.endswith((".yaml", ".yml")):
                continue
            path = here / name
            rel = path.relative_to(root).as_posix()
            inactive = any(part in INACTIVE_PARTS for part in rel.split("/")[:-1])
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(lines, 1):
                match = RECIPE_LINE.match(line)
                if match:
                    value = match.group(1)
                    unit = next((uid for pre, uid in prefixes if value == pre or value.startswith(pre + ".")), None)
                    g.recipe_refs.append((rel, number, value, unit, inactive))


def unit_specs(root: Path, g: Graph, edges: list[dict], registry: list[dict] | None) -> None:
    """Заполняет node['spec'] у всех юнитов."""
    fan_out: dict[str, set[str]] = defaultdict(set)
    fan_in: dict[str, set[str]] = defaultdict(set)
    for (su, du), counter in g.pairs.items():
        if counter["hard"] or counter["lazy"]:  # tc в метрики не входит
            fan_out[su].add(du)
            fan_in[du].add(su)
    edges_by_src: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        edges_by_src[e["src"]].append(e)
    recipes: dict[str, set[str]] = defaultdict(set)
    recipes_off: dict[str, set[str]] = defaultdict(set)
    for recipe_path, _line, _value, recipe_unit, inactive in g.recipe_refs:
        if recipe_unit:
            (recipes_off if inactive else recipes)[recipe_unit].add(recipe_path)
    for unit_id, ref in g.units.items():
        files = sorted(g.unit_files[unit_id])
        prefix = ref.path.replace("/", ".")
        folder = root / ref.path
        if ref.synthetic:
            docs = dict.fromkeys(("readme", "status", "decisions", "interfaces"), False)
            interfaces: list[dict] = []
        else:
            docs = {
                "readme": (folder / "README.md").is_file(),
                "status": (folder / "STATUS.md").is_file(),
                "decisions": (folder / "DECISIONS.md").is_file(),
                "interfaces": (folder / "interfaces.py").is_file() or (folder / "interfaces").is_dir(),
            }
            interfaces = unit_interfaces(g, unit_id, edges_by_src)
        init = g.parsed.get(f"{prefix}.__init__")
        all_names = init.all_names if init else None
        n_in, n_out = len(fan_in[unit_id]), len(fan_out[unit_id])
        card = build_card(root, g, ref, registry)
        g.nodes[unit_id]["spec"] = {
            "loc": sum(g.parsed[f].loc for f in files),
            "files": len(files),
            "tests": g.unit_tests[unit_id],
            "docs": docs,
            "all": all_names,
            "interfaces": interfaces,
            "classes_top": unit_classes_top(g, unit_id, prefix, all_names, edges_by_src),
            "fan_in": n_in,
            "fan_out": n_out,
            "instability": round(n_out / (n_in + n_out), 2) if n_in + n_out else 0.0,
            "tier": card["tier"],
            "card": card,
            "recipes": sorted(recipes[unit_id]),
            "recipes_inactive": sorted(recipes_off[unit_id]),
        }


# --------------------------------------------------------------------------- 5. находки


def tarjan(adj: dict[str, set[str]]) -> list[list[str]]:
    """Сильно связные компоненты (рекурсивно: в графе юнитов сотни вершин)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    out: list[list[str]] = []

    def strong(v: str) -> None:
        index[v] = low[v] = len(index)
        stack.append(v)
        on_stack.add(v)
        for w in sorted(adj.get(v, ())):
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            out.append(sorted(comp))

    for v in sorted(adj):
        if v not in index:
            strong(v)
    return out


def is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def private_parts(g: Graph, edge: dict) -> list[str]:
    """Приватные имена и модули (с `_` в начале), через которые ребро заходит в чужой юнит."""
    bad = [n for n in edge["names"] if n.startswith("_") and not is_dunder(n)]
    ref = g.units[g.file_unit[edge["dst"]]]
    inner = g.file_path[edge["dst"]][len(ref.path) + 1 :].removesuffix(".py").split("/")
    bad += [p for p in inner if p.startswith("_") and not is_dunder(p)]
    return list(dict.fromkeys(bad))


def names_outside_all(g: Graph, edge: dict) -> list[str] | None:
    """Витрина по `__all__`: None — цель не `__init__` с литеральным `__all__`; [] — все имена в нём; иначе вне него."""
    dst = edge["dst"]
    all_names = g.parsed[dst].all_names if g.file_is_init[dst] else None
    if all_names is None:
        return None
    return [n for n in edge["names"] if n != "*" and n not in all_names]


def is_layer_reverse(src_layer: str, dst_layer: str) -> bool:
    if src_layer == dst_layer or src_layer == EXTERNAL:
        return False
    if dst_layer == EXTERNAL:
        return src_layer in NO_EXTERNAL_IMPORT
    return LAYER_ORDER[src_layer] < LAYER_ORDER[dst_layer]


def findings(root: Path, g: Graph, edges: list[dict], registry: list[dict] | None) -> list[dict]:
    """Все правила таблицы README; порядок детерминирован."""
    out: list[dict] = []

    def add(rule, severity, src_unit, dst_unit, src, dst, where, detail, sort_line=0, **extra):  # noqa: ANN001
        item = {
            "rule": rule, "severity": severity, "src_unit": src_unit, "dst_unit": dst_unit,
            "src": src, "dst": dst, "where": where, "detail": detail, **extra,
        }  # fmt: skip
        item["_key"] = (list(RULES).index(rule), src_unit or "", dst_unit or "", where or "", sort_line, dst or "")
        out.append(item)

    for e in edges:
        su, du = g.file_unit[e["src"]], g.file_unit[e["dst"]]
        if su == du:
            continue
        sl, dl = layer_of(su), layer_of(du)
        where = f"{g.file_path[e['src']]}:{e['line']}"
        kind, names = e["kind"], ", ".join(e["names"]) or "-"
        if is_layer_reverse(sl, dl):
            add("layer-reverse", "warn" if kind == "tc" else "error", su, du, e["src"], e["dst"], where,
                f"слой {sl} импортирует слой {dl} ({kind}): {e['src']} -> {e['dst']} [{names}]", e["line"])  # fmt: skip
        if EXTERNAL in (sl, dl):
            continue  # v1: прочие находки про backend_ctl не ведём
        du_ref = g.units[du]
        showcase = (
            e["dst"] == f"{du}.__init__" or e["dst"] == f"{du}.interfaces" or e["dst"].startswith(f"{du}.interfaces.")
        )
        gap = names_outside_all(g, e)
        if not showcase and not du_ref.synthetic and gap != []:
            detail = f"импорт мимо витрины юнита {du} ({kind}): {e['dst']} [{names}]"
            if gap:
                detail += f"; вне __all__: {', '.join(gap)}"
            add("deep-import", "warn", su, du, e["src"], e["dst"], where, detail, e["line"])
        bad = private_parts(g, e)
        if bad:
            add("private-import", "warn", su, du, e["src"], e["dst"], where,
                f"приватное из чужого юнита {du} ({kind}): {', '.join(bad)}", e["line"])  # fmt: skip

    for file_id, line, text, guarded in g.unresolved:
        severity = "info" if guarded else "error"
        where = f"{g.file_path[file_id]}:{line}"
        detail = f"относительный импорт не разрешился в файл графа: {text}"
        add("unresolved-relative", severity, g.file_unit[file_id], None, file_id, None, where, detail, line)

    for file_id, lineno, message in g.parse_errors:
        where = g.file_path[file_id] + (f":{lineno}" if lineno else "")
        detail = f"файл не разобран: {message}"
        add("parse-error", "error", g.file_unit[file_id], None, file_id, None, where, detail, lineno or 0)
    for file_id, line, text, under_test in g.unresolved_abs:
        where = f"{g.file_path[file_id]}:{line}"
        detail = (
            "цель — тестовый файл, он вне графа: " if under_test else "цель не найдена среди файлов графа: "
        ) + text
        severity = "info" if under_test else "warn"
        add("unresolved-absolute", severity, g.file_unit[file_id], None, file_id, None, where, detail, line)
    for recipe_path, line, value, recipe_unit, inactive in g.recipe_refs:
        if recipe_unit is None and not inactive:
            detail = f"plugin_class `{value}` не соответствует ни одному юниту"
            add("recipe-unknown-plugin", "warn", None, None, None, None, f"{recipe_path}:{line}", detail, line)

    # Вершина графа циклов: настоящий юнит или отдельный файл из синтетического `__root__`
    # (иначе фасад `multiprocess_framework/__init__.py` склеивает полсотни юнитов в одну «петлю»).
    def vertex(file_id: str) -> str:
        unit_id = g.file_unit[file_id]
        return file_id if g.units[unit_id].synthetic else unit_id

    runtime: dict[str, set[str]] = defaultdict(set)
    hard: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        if e["kind"] == "tc" or EXTERNAL in (layer_of(e["src"]), layer_of(e["dst"])):
            continue
        a, b = vertex(e["src"]), vertex(e["dst"])
        if a != b:
            runtime[a].add(b)
            runtime.setdefault(b, set())
            if e["kind"] == "hard":
                hard[a].add(b)
    for comp in tarjan(runtime):
        if len(comp) < 2:
            continue
        members = set(comp)
        inner = {u: hard[u] & members for u in comp}
        hard_cycles = [c for c in tarjan(inner) if len(c) > 1]
        if not hard_cycles:
            how = "только с lazy-рёбрами"
        elif any(len(c) == len(comp) for c in hard_cycles):
            how = "по hard-рёбрам цикл охватывает всех участников"
        else:
            how = "по hard-рёбрам: " + " | ".join(", ".join(c) for c in hard_cycles)
        detail = f"цикл из {len(comp)} вершин: {', '.join(comp)}; {how}"
        first = next((c for c in comp if c in g.units), comp[0])
        add("unit-cycle", "error" if hard_cycles else "warn", first, None, None, None, None, detail, members=comp)

    for unit_id in sorted(g.units):
        spec = g.nodes[unit_id]["spec"]
        if g.units[unit_id].synthetic:
            continue
        docs = spec["docs"]
        checks = (
            ("interfaces.py", docs["interfaces"]),
            ("README.md", docs["readme"]),
            ("STATUS.md", docs["status"]),
            ("тесты", spec["tests"] > 0),
        )
        missing = [name for name, ok in checks if not ok]
        if missing:
            add("unit-hygiene", "info", unit_id, None, None, None, None, f"нет: {', '.join(missing)}")
        card = spec["card"]
        absent = [key for key in DECLARED if card[key] is None]
        if absent:
            add("unit-undeclared", "info", unit_id, None, None, None, None, f"не объявлено: {', '.join(absent)}")
        if registry is not None and resolve(g.units[unit_id].path + "/", registry) == OTHER:
            add("registry-drift", "warn", unit_id, None, None, None, None, "юнит не найден в modules.yaml (other)")
    for row in registry or []:
        for element in row["paths"]:
            if element.split("/")[0] in LAYER_ORDER and not (root / element.rstrip("/")).exists():
                add("registry-drift", "warn", None, None, None, None, None,
                    f"modules.yaml: у модуля `{row['id']}` путь `{element}` не существует на диске")  # fmt: skip

    out.sort(key=lambda f: (f["_key"], f["detail"]))
    for item in out:
        del item["_key"]
    return out


# --------------------------------------------------------------------------- 6. выходные файлы


def git_commit(root: Path) -> str | None:
    try:
        run = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return run.stdout.strip() or None if run.returncode == 0 else None


def build_model(root: Path, out_dir: Path) -> tuple[dict, Graph]:
    """Вся модель в памяти (без записи на диск)."""
    sources, test_units, test_modules = collect_files(root)
    g = build_nodes(root, sources, test_units, test_modules)
    edges = build_edges(g)
    scan_recipes(root, g)
    registry = load_registry(root)
    unit_specs(root, g, edges, registry)
    finds = findings(root, g, edges, registry)
    nodes = sorted(g.nodes.values(), key=lambda n: (LAYER_ORDER[layer_of(n["id"])], n["id"]))
    counts = Counter(n["kind"] for n in nodes)
    meta = {
        "schema": SCHEMA,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "commit": git_commit(root),
        "layers": list(LAYERS),
        "counts": {
            "nodes": len(nodes),
            "units": counts["unit"],
            "files": counts["file"],
            "edges": len(edges),
            "findings": len(finds),
            "parse_errors": len(g.parse_errors),
            "unresolved_absolute": len(g.unresolved_abs),
        },
    }
    return {"meta": meta, "nodes": nodes, "edges": edges, "findings": finds}, g


def dumps(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False)


def render_model_json(model: dict) -> str:
    """Один узел / ребро / находка на строку — диффы в git читаются."""
    parts = [f'  "meta": {dumps(model["meta"])}']
    for key in ("nodes", "edges", "findings"):
        rows = ",\n".join("    " + dumps(item) for item in model[key])
        parts.append(f'  "{key}": [\n{rows}\n  ]')
    return "{\n" + ",\n".join(parts) + "\n}\n"


def esc(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def fmt_kinds(counter: Counter) -> str:
    return ", ".join(f"{k} {counter[k]}" for k in KINDS if counter[k])


def finding_counts(finds: list[dict]) -> dict[str, Counter]:
    """unit -> счётчик правил (цикл засчитывается каждому участнику)."""
    per_unit: dict[str, Counter] = defaultdict(Counter)
    for f in finds:
        for unit in f.get("members") or [f["src_unit"]]:
            per_unit[unit][f["rule"]] += 1
    return per_unit


def render_units_md(model: dict, g: Graph) -> str:
    meta = model["meta"]
    units = [n for n in model["nodes"] if n["kind"] == "unit"]
    per_unit = finding_counts(model["findings"])
    out_map: dict[str, list] = defaultdict(list)
    in_map: dict[str, list] = defaultdict(list)
    for (su, du), counter in sorted(g.pairs.items()):
        out_map[su].append((du, counter))
        in_map[du].append((su, counter))
    L = [
        "# Спецификация юнитов",
        "",
        f"Сгенерировано `scripts/arch_map/build.py` (commit `{meta['commit']}`, schema {meta['schema']}). "
        "Не править руками.",
        "fan-in / fan-out — число других юнитов по рёбрам hard+lazy (tc не считается); "
        "I = fan-out / (fan-in + fan-out).",
        "Тесты — число файлов `test_*.py` юнита; в LOC и files они не входят.",
        "",
    ]
    for layer in LAYERS:
        rows = [u for u in units if layer_of(u["id"]) == layer]
        if not rows:
            continue
        L += [f"## Слой `{layer}` — юнитов: {len(rows)}", ""]
        if layer == "Plugins":
            L += [
                "> Внимание: fan-in и fan-out считают только импорты. Плагины подключаются конфигом, строками "
                "`plugin_class:` в рецептах (`*.yaml`/`*.yml` по всему репозиторию), "
                "поэтому fan-in 0 не значит «не используется». "
                "Колонка «в рецептах» считает только живые рецепты (без путей с `tests`, `fixtures`, `archive`; "
                "они лежат в `spec.recipes_inactive`).",
                "",
            ]
        L += [
            "| unit | tier | contour | purpose | команд | в рецептах | LOC | files | tests | fan-in | fan-out | I "
            "| interfaces | findings |"
        ]
        L += ["|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"]
        for u in rows:
            s, card = u["spec"], u["spec"]["card"]
            contour = card.get("contour")
            contour = ", ".join(contour) if isinstance(contour, list) else (contour or "—")
            names = [i["name"] for i in s["interfaces"]]
            ifaces = ", ".join(names[:4]) + (f" +{len(names) - 4}" if len(names) > 4 else "") if names else "—"
            counts = per_unit.get(u["id"]) or {}
            found = ", ".join(f"{r} {counts[r]}" for r in RULES if counts.get(r)) or "—"
            L.append(
                f"| `{u['id']}` | {esc(s['tier'] or '—')} | {esc(contour)} | {esc(card.get('purpose') or '—')} | "
                f"{len(card['commands'])} | {len(s['recipes'])} | "
                f"{s['loc']} | {s['files']} | {s['tests']} | {s['fan_in']} | {s['fan_out']} | {s['instability']} | "
                f"{esc(ifaces)} | {esc(found)} |"
            )
        L.append("")
    L += ["## Зависимости юнитов", ""]
    for layer in LAYERS:
        rows = [u for u in units if layer_of(u["id"]) == layer and (out_map.get(u["id"]) or in_map.get(u["id"]))]
        if not rows:
            continue
        L += [f"### Слой `{layer}`", ""]
        for u in rows:
            L.append(f"- `{u['id']}`")
            if out_map.get(u["id"]):
                L.append("  - зависит от: " + "; ".join(f"`{d}` ({fmt_kinds(c)})" for d, c in out_map[u["id"]]))
            if in_map.get(u["id"]):
                L.append("  - используют: " + "; ".join(f"`{s}` ({fmt_kinds(c)})" for s, c in in_map[u["id"]]))
        L.append("")
    real = [u for u in units if not u.get("synthetic")]
    absent = [(u["id"], [k for k in DECLARED if u["spec"]["card"][k] is None]) for u in real]
    absent = [(uid, miss) for uid, miss in absent if miss]
    L += [f"## Юниты без объявленных полей — {len(absent)} из {len(real)}", ""]
    L += [f"- `{uid}`: {', '.join(miss)}" for uid, miss in absent] or ["нет"]
    L += ["", f"## Внешний инструмент `{EXTERNAL}`", ""]
    imports_layers: dict[str, Counter] = defaultdict(Counter)
    imported_by: dict[str, Counter] = defaultdict(Counter)
    for (su, du), counter in g.pairs.items():
        if layer_of(su) == EXTERNAL and layer_of(du) != EXTERNAL:
            imports_layers[layer_of(du)].update(counter)
        if layer_of(du) == EXTERNAL and layer_of(su) != EXTERNAL:
            imported_by[su].update(counter)
    L.append(
        "Импортирует слои: "
        + (
            "; ".join(
                f"`{ly}` ({fmt_kinds(c)})"
                for ly, c in sorted(imports_layers.items(), key=lambda kv: LAYER_ORDER[kv[0]])
            )
            or "нет"
        )
    )
    L.append(
        "Его импортируют: " + ("; ".join(f"`{s}` ({fmt_kinds(c)})" for s, c in sorted(imported_by.items())) or "никто")
    )
    return "\n".join(L) + "\n"


def render_findings_md(model: dict) -> str:
    finds, meta = model["findings"], model["meta"]
    L = [
        "# Находки правил",
        "",
        f"Сгенерировано `scripts/arch_map/build.py` (commit `{meta['commit']}`). Не править руками. "
        f"Всего: {len(finds)}.",
        "",
        "| правило | error | warn | info | всего |",
        "|---|---:|---:|---:|---:|",
    ]
    by_rule: dict[str, list[dict]] = {r: [f for f in finds if f["rule"] == r] for r in RULES}
    for rule, items in by_rule.items():
        sev = Counter(f["severity"] for f in items)
        L.append(f"| {rule} | {sev['error']} | {sev['warn']} | {sev['info']} | {len(items)} |")
    for rule, items in by_rule.items():
        if not items:
            continue
        L += ["", f"## {rule} — {len(items)}", "", RULES[rule], ""]
        pairs: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for f in items:
            if f["rule"] == "unit-cycle":
                L.append(f"- [{f['severity']}] {f['detail']}")
            elif f["dst_unit"] is None and not f["where"]:
                L.append(f"- [{f['severity']}] `{f['src_unit'] or '—'}` — {f['detail']}")
            else:
                pairs[(f["src_unit"] or "—", f["dst_unit"] or "—")].append(f)
        for (src, dst), group in sorted(pairs.items()):
            sev = Counter(f["severity"] for f in group)
            split = ", ".join(f"{s} {sev[s]}" for s in SEVERITY_ORDER if sev[s])
            L += ["", f"### `{src}` -> `{dst}` — {len(group)} ({split})"]
            L += [f"- `{f['where']}`" for f in group[:5]]
            if len(group) > 5:
                L.append(f"- … и ещё {len(group) - 5}")
    return "\n".join(L) + "\n"


OUTPUT_NAMES = ("model.json", "model.js", "units.md", "findings.md")
JS_PREFIX = "window.ARCH_MODEL = "


def render_outputs(model: dict, g: Graph) -> dict[str, str]:
    return {
        "model.json": render_model_json(model),
        "model.js": JS_PREFIX + json.dumps(model, ensure_ascii=False, separators=(",", ":")) + ";\n",
        "units.md": render_units_md(model, g),
        "findings.md": render_findings_md(model),
    }


def write_outputs(out_dir: Path, model: dict, g: Graph) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in render_outputs(model, g).items():
        (out_dir / name).write_bytes(text.encode("utf-8"))  # байты: на Windows не плодим CRLF


# --------------------------------------------------------------------------- 7. CLI


def summary_lines(model: dict) -> list[str]:
    nodes = Counter(n["kind"] for n in model["nodes"])
    edges = Counter(e["kind"] for e in model["edges"])
    finds = Counter((f["rule"], f["severity"]) for f in model["findings"])
    lines = [
        "узлы: " + ", ".join(f"{k} {v}" for k, v in sorted(nodes.items())) + f" (всего {len(model['nodes'])})",
        "рёбра: " + ", ".join(f"{k} {edges[k]}" for k in KINDS) + f" (всего {len(model['edges'])})",
        f"находки (всего {len(model['findings'])}):",
    ]
    lines += [
        f"  {rule} / {sev}: {n}"
        for (rule, sev), n in sorted(finds.items(), key=lambda kv: (list(RULES).index(kv[0][0]), kv[0][1]))
    ]
    return lines


def comparable(model: dict) -> dict:
    """Модель без полей, которые меняются при неизменном коде (время, SHA)."""
    meta = {k: v for k, v in model["meta"].items() if k not in ("generated", "commit")}
    return {"meta": meta, "nodes": model["nodes"], "edges": model["edges"], "findings": model["findings"]}


def parse_model_text(name: str, raw: str) -> dict:
    if name == "model.js":
        if not raw.startswith(JS_PREFIX):
            raise ValueError("нет префикса window.ARCH_MODEL")
        raw = raw[len(JS_PREFIX) :].rstrip().removesuffix(";")
    return json.loads(raw)


def normalize_md(text: str) -> str:
    """В шапке md есть SHA снимка; как и в model.json, он не считается расхождением."""
    return re.sub(r"commit `[^`]*`", "commit `-`", text.replace("\r\n", "\n"))


def print_model_diff(label: str, disk: dict, now: dict) -> None:
    if disk["meta"] != now["meta"]:
        print(f"  {label} meta: на диске {disk['meta']} / из кода {now['meta']}", file=sys.stderr)
    for key in ("nodes", "edges", "findings"):
        old = {dumps(x) for x in disk[key]}
        new = {dumps(x) for x in now[key]}
        if old != new:
            print(f"  {label} {key}: только на диске {len(old - new)}, только в коде {len(new - old)}", file=sys.stderr)
            for side, items in (("диск", sorted(old - new)), ("код", sorted(new - old))):
                for row in items[:3]:
                    print(f"    {side}: {row[:200]}", file=sys.stderr)


def check(fresh: dict, g: Graph, out_dir: Path) -> int:
    """Все четыре файла на диске против свежей сборки; SHA и время не в счёт."""
    texts = render_outputs(fresh, g)
    now = comparable(fresh)
    bad: list[str] = []
    for name in OUTPUT_NAMES:
        path = out_dir / name
        if not path.is_file():
            bad.append(name)
            print(f"  {name}: файла нет", file=sys.stderr)
            continue
        raw = path.read_bytes().decode("utf-8", errors="replace")
        if name.startswith("model."):
            try:
                disk = comparable(parse_model_text(name, raw))
            except (ValueError, KeyError, TypeError) as exc:
                bad.append(name)
                print(f"  {name}: не разобрался ({exc})", file=sys.stderr)
                continue
            if disk != now:
                bad.append(name)
                print_model_diff(name, disk, now)
        elif normalize_md(raw) != normalize_md(texts[name]):
            bad.append(name)
            print(f"  {name}: текст отличается от свежей сборки", file=sys.stderr)
    if bad:
        print(f"МОДЕЛЬ УСТАРЕЛА: расходятся файлы: {', '.join(bad)}", file=sys.stderr)
        return 1
    print("модель = код")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Генератор модели архитектуры (docs/arch-map)")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]), help="корень репозитория")
    parser.add_argument("--out", default="docs/arch-map", help="каталог результата (относительно --root)")
    parser.add_argument("--check", action="store_true", help="сверить четыре файла на диске с кодом, ничего не писать")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    out_dir = Path(args.out)
    out_dir = out_dir if out_dir.is_absolute() else root / out_dir
    model, g = build_model(root, out_dir)
    for file_id, lineno, message in g.parse_errors:
        print(f"ПРЕДУПРЕЖДЕНИЕ: файл не разобран: {g.file_path[file_id]}:{lineno}: {message}", file=sys.stderr)
    if args.check:
        return check(model, g, out_dir)
    write_outputs(out_dir, model, g)
    print(f"записано в {out_dir}")
    print("\n".join(summary_lines(model)))
    print(
        f"абсолютных импортов без файла-цели: {len(g.unresolved_abs)}; файлов не разобрано: {len(g.parse_errors)}; "
        f"plugin_class в рецептах: {len(g.recipe_refs)}"
    )
    errors = sum(1 for f in model["findings"] if f["severity"] == "error")
    if errors:
        print(f"ОШИБКИ: находок с серьёзностью error — {errors}; код выхода 1", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
