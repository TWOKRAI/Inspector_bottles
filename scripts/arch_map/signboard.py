"""signboard — «вывески» кода на каждом уровне зума, считаются из кода, без импорта кода.

Аналогия — карта: слой (материк) → юнит (страна) → пакет (город) → файл (район) → класс/функция (дом).
У каждого уровня своя вывеска-спецификация; наведение на объект показывает её одной карточкой.

    python scripts/arch_map/signboard.py show <путь>[::<квалифицированное имя>] [--format json|text]
    python scripts/arch_map/signboard.py bench --targets docs/arch-map/_bench/k0_targets.json \
        --out docs/arch-map/_bench/k0_reference.json
    python scripts/arch_map/signboard.py cards --out docs/arch-map/cards.html

Дом и район считаются обходом `ast` по всему репозиторию (индекс строится один раз на запуск).
Слой, юнит и пакет читают `docs/arch-map/model.json` (контракт — docs/arch-map/README.md).
Зависимости: stdlib; помощники берутся импортом из scripts/arch_map/build.py (он тянет PyYAML).
Правило карточки: строка 1 — что это; строка 2 — «использует меня N / использую M»;
красным только нарушенное правило; остальное — под сгибом.
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:  # запуск как скрипта: пакета `scripts` в sys.path ещё нет
    sys.path.insert(0, str(_REPO))
from scripts.arch_map.build import (  # noqa: E402
    EXTERNAL,
    NO_EXTERNAL_IMPORT,
    SKIP_DIRS,
    class_style,
    is_test_path,
    layer_of,
    leaf_name,
    resolve_relative,
)

# --------------------------------------------------------------------------- умолчания проекта (единственное место)

DEFAULT_MODEL = "docs/arch-map/model.json"
DEFAULT_TARGETS = "docs/arch-map/_bench/k0_targets.json"
DEFAULT_BENCH_OUT = "docs/arch-map/_bench/k0_reference.json"
DEFAULT_CARDS_OUT = "docs/arch-map/cards.html"
FEATURED = {  # три карточки наверху страницы: слой, юнит, класс
    "layer": "multiprocess_framework",
    "unit": "multiprocess_framework.modules.config_module",
    "house": "multiprocess_framework/modules/config_module/interfaces.py::IConfigManager",
}
DRILL_UNIT = FEATURED["unit"]  # юнит, раскрытый до домов
# каталоги данных и планов: .py там не код проекта (в data — 12 тыс. файлов)
EXTRA_SKIP_DIRS = frozenset({"data", "plans"})

# --------------------------------------------------------------------------- общие константы

SCAN_SKIP = SKIP_DIRS | EXTRA_SKIP_DIRS | {"node_modules", "site-packages", "venv", "build", "dist", "graphify-out"}
SEVERITIES = ("error", "warn", "info")
KIND_SUFFIXES = (("plugin", "Plugin"), ("manager", "Manager"))  # имя класса или базы кончается на суффикс
ABSTRACT_DECOS = frozenset({"abstractmethod", "abstractproperty", "abstractclassmethod", "abstractstaticmethod"})
MEMBER_DECOS = ("property", "staticmethod", "classmethod")
STRUCTURAL_SKIP = frozenset({"__init__", "__new__", "__subclasshook__", "__init_subclass__"})
CALL_SITES_CAP = 3
TESTS_CAP = 5
STRUCTURAL_CAP = 5
SUBCLASSES_CAP = 20
INHERIT_DEPTH = 4
DOC_CUT = 160  # символов абзаца докстринга в странице
CALL_SITES_NOTE = "вызовы по имени (импорт + вызов); 0 не значит «не используется»"
WRITE_MODES = frozenset("wax+")
DUMP_FUNCS = frozenset({"json.dump", "yaml.safe_dump", "yaml.dump"})
READ_ATTRS = frozenset({"read_text", "read_bytes"})
WRITE_ATTRS = frozenset({"write_text", "write_bytes"})


class SignboardError(Exception):
    """Понятная пользователю ошибка: нет файла, символа или модели."""


# --------------------------------------------------------------------------- разбор файлов и индекс репозитория

type FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def iter_defs(body: list[ast.stmt], prefix: str):
    """(квалифицированное имя, узел) для классов и функций; в классы заходит, в функции — нет."""
    for stmt in body:
        if isinstance(stmt, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            qualname = f"{prefix}{stmt.name}"
            yield qualname, stmt
            if isinstance(stmt, ast.ClassDef):
                yield from iter_defs(stmt.body, qualname + ".")
        elif isinstance(stmt, ast.If):
            yield from iter_defs(stmt.body, prefix)
            yield from iter_defs(stmt.orelse, prefix)
        elif isinstance(stmt, (ast.Try, ast.TryStar)):
            for part in (stmt.body, *(h.body for h in stmt.handlers), stmt.orelse, stmt.finalbody):
                yield from iter_defs(part, prefix)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            yield from iter_defs(stmt.body, prefix)


def module_name(rel: str) -> tuple[str, bool]:
    """(имя модуля для импортов, это `__init__.py`) по пути от корня."""
    parts = rel[: -len(".py")].split("/")
    is_init = parts[-1] == "__init__"
    return ".".join(parts[:-1] if is_init else parts), is_init


def parse_file(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8-sig"))
    except (SyntaxError, ValueError, UnicodeDecodeError, OSError):
        return None


def safe_unparse(node: ast.AST | None) -> str:
    return "" if node is None else ast.unparse(node)


def is_private(name: str) -> bool:
    """`_x` и `__x` — приватные; `__x__` (дандеры) — нет."""
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def ancestors(module: str) -> list[str]:
    """`a.b.c` -> [`a.b.c`, `a.b`, `a`]."""
    parts = module.split(".")
    return [".".join(parts[:i]) for i in range(len(parts), 0, -1)]


@dataclass
class ClassFact:
    name: str
    qualname: str
    file: str
    module: str
    line: int
    bases: list[str]  # листовые имена баз
    own: frozenset[str]  # имена, определённые в теле класса
    is_test: bool


@dataclass
class FileFact:
    rel: str
    module: str
    is_init: bool
    is_test: bool
    names: dict[str, tuple[str, str]] = field(default_factory=dict)  # локальное имя -> (модуль, исходное имя)
    module_aliases: dict[str, str] = field(default_factory=dict)  # ключ (`m` или `a.b.c`) -> модуль


@dataclass
class Ref:
    """Как файл ссылается на символ: локальные имена из `from M import N [as L]` и ключи модуля-псевдонима."""

    locals: set[str] = field(default_factory=set)
    mod_keys: set[str] = field(default_factory=set)


@dataclass
class Index:
    root: Path
    modules: set[str] = field(default_factory=set)
    top_levels: set[str] = field(default_factory=set)
    files: dict[str, FileFact] = field(default_factory=dict)
    classes_by_name: dict[str, list[ClassFact]] = field(default_factory=dict)
    subclasses_by_base: dict[str, list[ClassFact]] = field(default_factory=dict)
    by_name: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)  # исх. имя -> (файл, local, модуль)
    by_module: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # модуль -> (файл, ключ)
    parse_errors: list[str] = field(default_factory=list)
    trees: dict[str, ast.Module] = field(default_factory=dict)  # кэш деревьев файлов карточек
    calls: dict[str, list[tuple[str, str, str, int]]] = field(default_factory=dict)  # кэш вызовов файла
    test_funcs: dict[str, list[tuple[str, frozenset[str]]]] = field(default_factory=dict)


def iter_py_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SCAN_SKIP and not d.startswith("."))
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield (Path(dirpath) / name).relative_to(root).as_posix()


def class_own_names(node: ast.ClassDef) -> frozenset[str]:
    names: set[str] = set()
    for stmt in node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(stmt.name)
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            names.add(stmt.target.id)
        elif isinstance(stmt, ast.Assign):
            names.update(t.id for t in stmt.targets if isinstance(t, ast.Name))
    return frozenset(names)


def scan_file(idx: Index, rel: str, tree: ast.Module) -> FileFact:
    """Факты одного файла: импорты и классы; регистрирует их в индексе."""
    module, is_init = module_name(rel)
    fact = FileFact(rel, module, is_init, is_test_path(tuple(rel.split("/"))))
    idx.files[rel] = fact
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                fact.module_aliases[alias.asname or alias.name] = alias.name
                idx.by_module.setdefault(alias.name, []).append((rel, alias.asname or alias.name))
        elif isinstance(node, ast.ImportFrom):
            base = resolve_relative(node.level, node.module, module, is_init) if node.level else node.module
            if base is None:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                full = f"{base}.{alias.name}"
                if full in idx.modules:  # `from pkg import submodule`
                    fact.module_aliases[local] = full
                    idx.by_module.setdefault(full, []).append((rel, local))
                else:
                    fact.names[local] = (base, alias.name)
                    idx.by_name.setdefault(alias.name, []).append((rel, local, base))
    for qualname, node in iter_defs(tree.body, ""):
        if isinstance(node, ast.ClassDef):
            cf = ClassFact(
                node.name, qualname, rel, module, node.lineno,
                [leaf_name(b) for b in node.bases if leaf_name(b)], class_own_names(node), fact.is_test,
            )  # fmt: skip
            idx.classes_by_name.setdefault(cf.name, []).append(cf)
            for base in cf.bases:
                idx.subclasses_by_base.setdefault(base, []).append(cf)
    return fact


_INDEX_CACHE: dict[str, Index] = {}


def get_index(root: Path) -> Index:
    """Индекс репозитория; строится один раз на корень за запуск."""
    key = str(root.resolve())
    if key in _INDEX_CACHE:
        return _INDEX_CACHE[key]
    rels = list(iter_py_files(root))
    idx = Index(root=root, modules={module_name(r)[0] for r in rels})
    idx.top_levels = {m.split(".")[0] for m in idx.modules if m}
    for rel in rels:
        tree = parse_file(root / rel)
        if tree is None:
            idx.parse_errors.append(rel)
            continue
        scan_file(idx, rel, tree)
    _INDEX_CACHE[key] = idx
    return idx


def tree_of(idx: Index, rel: str) -> ast.Module:
    if rel not in idx.trees:
        tree = parse_file(idx.root / rel)
        if tree is None:
            raise SignboardError(f"файл не читается или не разбирается: {rel}")
        idx.trees[rel] = tree
        if rel not in idx.files:  # файл вне обхода (например, под docs/): регистрируем для разбора имён
            scan_file(idx, rel, tree)
    return idx.trees[rel]


def file_calls(idx: Index, rel: str) -> list[tuple[str, str, str, int]]:
    """Вызовы файла: (`name`|`attr`, идентификатор, текст базы атрибута, строка)."""
    if rel not in idx.calls:
        tree = parse_file(idx.root / rel)
        found: list[tuple[str, str, str, int]] = []
        for node in ast.walk(tree) if tree else ():
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                found.append(("name", func.id, "", node.lineno))
            elif isinstance(func, ast.Attribute):
                found.append(("attr", func.attr, safe_unparse(func.value), node.lineno))
        idx.calls[rel] = found
    return idx.calls[rel]


def identifiers(node: ast.AST) -> frozenset[str]:
    """Имена и атрибуты, упомянутые внутри узла."""
    found: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            found.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            found.add(sub.attr)
    return frozenset(found)


def test_functions(idx: Index, rel: str) -> list[tuple[str, frozenset[str]]]:
    """(nodeid, упомянутые идентификаторы) для test-функций файла и методов классов `Test*`."""
    if rel not in idx.test_funcs:
        tree = parse_file(idx.root / rel)
        found: list[tuple[str, frozenset[str]]] = []
        for qualname, node in iter_defs(tree.body, "") if tree else ():
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test"):
                continue
            parts = qualname.split(".")
            if len(parts) == 1 or (len(parts) == 2 and parts[0].startswith("Test")):
                found.append((f"{rel}::" + "::".join(parts), identifiers(node)))
        idx.test_funcs[rel] = found
    return idx.test_funcs[rel]


def importing_files(idx: Index, def_module: str, name: str) -> dict[str, Ref]:
    """Файлы, импортирующие `name` из модуля определения или из пакета над ним (витрина), и псевдонимы модуля."""
    found: dict[str, Ref] = {}
    for rel, local, base in idx.by_name.get(name, ()):
        if base == def_module or def_module.startswith(base + "."):
            found.setdefault(rel, Ref()).locals.add(local)
    for anc in ancestors(def_module):
        for rel, key in idx.by_module.get(anc, ()):
            found.setdefault(rel, Ref()).mod_keys.add(key)
    return found


def short_first(paths: list[str]) -> list[str]:
    """Кратчайший путь первым, дальше по алфавиту."""
    return sorted(paths, key=lambda p: (len(p.split(":")[0].split("::")[0]), p))


# --------------------------------------------------------------------------- дом: класс, функция, метод


def first_paragraph(doc: str | None) -> str:
    if not doc:
        return ""
    return " ".join(doc.strip().split("\n\n")[0].split())


def one_sentence(text: str, limit: int = 140) -> str:
    """Первое предложение, не длиннее `limit` символов."""
    head = text.split(". ")[0].rstrip(".")
    return head if len(head) <= limit else head[: limit - 1].rstrip() + "…"


def func_signature(node: FunctionNode, strip_self: bool = False) -> str:
    args = node.args
    if strip_self:
        args = copy.deepcopy(args)
        if args.posonlyargs:
            args.posonlyargs = args.posonlyargs[1:]
        else:
            args.args = args.args[1:]
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    return f"{prefix}{node.name}({ast.unparse(args)}){ret}"


def deco_leaf(deco: ast.expr) -> str:
    return leaf_name(deco.func if isinstance(deco, ast.Call) else deco)


def is_abstract(node: FunctionNode) -> bool:
    return any(deco_leaf(d) in ABSTRACT_DECOS for d in node.decorator_list)


def class_members(node: ast.ClassDef) -> list[dict]:
    """Члены класса: методы и аннотированные атрибуты; дандеры остаются, `_приватные` отброшены."""
    members: list[dict] = []
    for stmt in node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and not is_private(stmt.name):
            decos = [deco_leaf(d) for d in stmt.decorator_list]
            kind = next((d for d in decos if d in MEMBER_DECOS), "method")
            members.append(
                {"name": stmt.name, "signature": func_signature(stmt), "abstract": is_abstract(stmt), "kind": kind}
            )
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and not is_private(stmt.target.id):
            members.append(
                {"name": stmt.target.id, "signature": f"{stmt.target.id}: {ast.unparse(stmt.annotation)}",
                 "abstract": False, "kind": "attr"}
            )  # fmt: skip
    return members


def house_kind(node: ast.AST, owner: ast.ClassDef | None) -> str:
    """Protocol / ABC / plugin / manager / class / function / method.

    Правило: Protocol и ABC — по базам (`class_style` из build.py); иначе `plugin`, если имя класса или листовое имя
    любой базы кончается на `Plugin`; `manager` — на `Manager`; иначе `class`.
    """
    if not isinstance(node, ast.ClassDef):
        return "method" if owner is not None else "function"
    style = class_style(node, {})
    if style != "class":
        return style
    names = [node.name, *(leaf_name(b) for b in node.bases)]
    for kind, suffix in KIND_SUFFIXES:
        if any(n.endswith(suffix) for n in names):
            return kind
    return "class"


def resolve_class(idx: Index, from_rel: str, leaf: str) -> ClassFact | None:
    """Класс-база по листовому имени: единственный по имени, иначе тот же файл, иначе по импорту; иначе None."""
    fact = idx.files.get(from_rel)
    imported = fact.names.get(leaf) if fact else None
    name = imported[1] if imported else leaf
    cands = idx.classes_by_name.get(name, [])
    if len(cands) <= 1:
        return cands[0] if cands else None
    same = [c for c in cands if c.file == from_rel]
    if same:
        return same[0]
    if imported:
        hit = [c for c in cands if c.module == imported[0] or c.module.startswith(imported[0] + ".")]
        if hit:
            return hit[0]
    return None


def class_node(idx: Index, fact: ClassFact) -> ast.ClassDef | None:
    for qualname, node in iter_defs(tree_of(idx, fact.file).body, ""):
        if qualname == fact.qualname and isinstance(node, ast.ClassDef):
            return node
    return None


def is_dataclass(node: ast.ClassDef) -> bool:
    return any(deco_leaf(d) == "dataclass" for d in node.decorator_list)


def class_signature(idx: Index, rel: str, node: ast.ClassDef, depth: int = 0) -> tuple[str, str]:
    """(сигнатура по `__init__`, откуда взят `__init__`: own | имя базы | dataclass | none)."""
    for stmt in node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == "__init__":
            sig = func_signature(stmt, strip_self=True)
            return f"{node.name}{sig[len('__init__') :].split(' -> ')[0]}", "own"  # -> None конструктора не нужен
    if is_dataclass(node):
        fields = [
            ast.unparse(s).replace("\n", " ")
            for s in node.body
            if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name) and "ClassVar" not in ast.unparse(s)
        ]
        return f"{node.name}({', '.join(fields)})", "dataclass"
    if depth < INHERIT_DEPTH:
        for base in node.bases:
            fact = resolve_class(idx, rel, leaf_name(base))
            base_node = class_node(idx, fact) if fact else None
            if base_node is not None:
                sig, source = class_signature(idx, fact.file, base_node, depth + 1)
                if source != "none":
                    return f"{node.name}{sig[len(base_node.name) :]}", fact.name if source == "own" else source
    return f"{node.name}()", "none"


def inherited_members(idx: Index, rel: str, node: ast.ClassDef, seen_names: set[str], depth: int = 0) -> list[dict]:
    """Члены известных баз (рекурсивно), не перекрытые потомком; у каждого `from` — имя базы."""
    out: list[dict] = []
    if depth >= INHERIT_DEPTH:
        return out
    for base in node.bases:
        fact = resolve_class(idx, rel, leaf_name(base))
        base_node = class_node(idx, fact) if fact else None
        if base_node is None or fact is None:
            continue
        for member in class_members(base_node):
            if member["name"] not in seen_names:
                seen_names.add(member["name"])
                out.append({"from": fact.name, **member})
        out.extend(inherited_members(idx, fact.file, base_node, seen_names, depth + 1))
    return out


def refers_to(idx: Index, rel: str, def_file: str, def_module: str, name: str) -> bool:
    """Файл определяет символ или импортирует его из модуля определения либо из пакета над ним."""
    return rel == def_file or rel in importing_files(idx, def_module, name)


def subclass_closure(idx: Index, name: str) -> set[str]:
    """Имена всех потомков по базовому имени (транзитивно)."""
    seen: set[str] = set()
    todo = [name]
    while todo:
        for cf in idx.subclasses_by_base.get(todo.pop(), ()):
            if cf.name not in seen:
                seen.add(cf.name)
                todo.append(cf.name)
    return seen


def abstract_names(node: ast.ClassDef, kind: str) -> set[str]:
    """Что обязан иметь структурный двойник: у ABC — `abstractmethod`-имена, у Protocol — все члены."""
    members = class_members(node)
    if kind == "Protocol":
        return {m["name"] for m in members} - STRUCTURAL_SKIP
    return {m["name"] for m in members if m["abstract"]}


def io_of(node: ast.AST) -> list[dict]:
    """Ввод-вывод внутри символа: open / read_text / write_text / json.dump / yaml.safe_dump / .schedule(."""
    aliases: dict[str, str] = {}  # `with open(P) as f` -> f: P
    for sub in ast.walk(node):
        if isinstance(sub, (ast.With, ast.AsyncWith)):
            for item in sub.items:
                call = item.context_expr
                if (
                    isinstance(item.optional_vars, ast.Name)
                    and isinstance(call, ast.Call)
                    and is_open_call(call)
                    and open_target(call)
                ):
                    aliases[item.optional_vars.id] = open_target(call)
    found: list[dict] = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        op, path_expr = "", ""
        if is_open_call(sub):
            op, path_expr = ("writes" if set(open_mode(sub)) & WRITE_MODES else "reads"), open_target(sub)
        elif isinstance(func, ast.Attribute) and func.attr in WRITE_ATTRS:
            op, path_expr = "writes", ast.unparse(func.value)
        elif isinstance(func, ast.Attribute) and func.attr in READ_ATTRS:
            op, path_expr = "reads", ast.unparse(func.value)
        elif isinstance(func, ast.Attribute) and func.attr == "schedule":
            op, path_expr = "watches", ast.unparse(sub.args[0]) if sub.args else ""
        elif safe_unparse(func) in DUMP_FUNCS:
            stream = (
                sub.args[1]
                if len(sub.args) > 1
                else next((k.value for k in sub.keywords if k.arg in ("fp", "stream")), None)
            )
            if stream is not None:
                text = ast.unparse(stream)
                op, path_expr = "writes", aliases.get(text, text)
        if op:
            found.append({"op": op, "path_expr": path_expr, "line": sub.lineno})
    found.sort(key=lambda d: d["line"])
    seen: set[tuple[str, str]] = set()
    unique = []
    for item in found:  # open + json.dump в одном with — одна запись
        key = (item["op"], item["path_expr"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def is_open_call(call: ast.Call) -> bool:
    func = call.func
    return (isinstance(func, ast.Name) and func.id == "open") or (
        isinstance(func, ast.Attribute) and func.attr == "open"
    )


def open_target(call: ast.Call) -> str:
    """Выражение пути: первый аргумент `open(...)` или приёмник `path.open(...)`."""
    func = call.func
    if isinstance(func, ast.Attribute):
        return ast.unparse(func.value)
    return ast.unparse(call.args[0]) if call.args else ""


def open_mode(call: ast.Call) -> str:
    mode: ast.expr | None = None
    index = 1 if isinstance(call.func, ast.Name) else 0
    if len(call.args) > index:
        mode = call.args[index]
    mode = next((k.value for k in call.keywords if k.arg == "mode"), mode)
    return mode.value if isinstance(mode, ast.Constant) and isinstance(mode.value, str) else "r"


def uses_count(idx: Index, rel: str, node: ast.AST) -> int:
    """Сколько разных внутренних имён (импортов из пакетов репозитория) символ упоминает."""
    fact = idx.files.get(rel)
    if fact is None:
        return 0
    used = {sub.id for sub in ast.walk(node) if isinstance(sub, ast.Name)}
    names = {(m, n) for local, (m, n) in fact.names.items() if local in used and m.split(".")[0] in idx.top_levels}
    mods = {m for key, m in fact.module_aliases.items() if key in used and m.split(".")[0] in idx.top_levels}
    return len(names) + len(mods)


def call_site_hits(
    idx: Index, rel: str, module: str, owner: ast.ClassDef | None, node: ast.AST
) -> tuple[list[str], int]:
    """(`путь:строка` вызовов по имени из других файлов, число вызовов внутри своего файла)."""
    name = node.name  # type: ignore[attr-defined]
    owner_name = owner.name if owner is not None else None
    refs = importing_files(idx, module, owner_name or name)
    hits: list[str] = []
    for ref_rel, ref in refs.items():
        if ref_rel == rel or idx.files[ref_rel].is_test:
            continue
        for kind, ident, base, line in file_calls(idx, ref_rel):
            if owner_name is not None:
                match = kind == "attr" and ident == name
            else:
                match = (kind == "name" and ident in ref.locals) or (
                    kind == "attr" and ident == name and base in ref.mod_keys
                )
            if match:
                hits.append(f"{ref_rel}:{line}")
    same = sum(
        1 for kind, ident, _b, _l in file_calls(idx, rel)
        if ident == name and kind == ("attr" if owner_name is not None else "name")
    )  # fmt: skip
    return hits, same


def test_hits(idx: Index, rel: str, module: str, owner: ast.ClassDef | None, node: ast.AST) -> list[str]:
    """nodeid тестов, упоминающих символ в теле, из файлов-тестов, которые его импортируют."""
    name = node.name  # type: ignore[attr-defined]
    owner_name = owner.name if owner is not None else None
    found: list[str] = []
    for ref_rel, ref in importing_files(idx, module, owner_name or name).items():
        if not idx.files[ref_rel].is_test:
            continue
        local_hits = []
        for nodeid, names in test_functions(idx, ref_rel):
            if owner_name is not None:
                match = name in names
            else:
                match = bool(ref.locals & names) or (bool(ref.mod_keys) and name in names)
            if match:
                local_hits.append(nodeid)
        if local_hits:
            found.extend(local_hits)
        elif owner_name is None and ref.locals:  # только `import пакет` — не повод называть файл
            found.append(ref_rel)  # импорт есть, прямого упоминания в test-функциях нет — файл целиком
    return found


def find_symbol(tree: ast.Module, qualname: str) -> tuple[ast.AST, ast.ClassDef | None]:
    defs = dict(iter_defs(tree.body, ""))
    if qualname not in defs:
        raise SignboardError(f"символ не найден: {qualname}")
    owner = defs.get(qualname.rsplit(".", 1)[0]) if "." in qualname else None
    return defs[qualname], owner if isinstance(owner, ast.ClassDef) else None


def norm_path(root: Path, path: str) -> str:
    """Путь от корня репозитория в posix-виде; абсолютный путь внутри корня сокращается."""
    p = Path(path)
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise SignboardError(f"путь вне корня {root}: {path}") from exc
    return p.as_posix().strip("/")


def house_spec(root: str | Path, path: str, qualname: str) -> dict:
    """Вывеска дома: класс, функция или метод `Класс.метод`."""
    root = Path(root)
    rel = norm_path(root, path)
    idx = get_index(root)
    tree = tree_of(idx, rel)
    node, owner = find_symbol(tree, qualname)
    module = idx.files[rel].module
    name = node.name  # type: ignore[attr-defined]
    kind = house_kind(node, owner)
    doc = first_paragraph(ast.get_docstring(node, clean=True))  # type: ignore[arg-type]
    spec: dict = {
        "level": "house", "id": f"{rel}::{qualname}", "path": rel, "qualname": qualname, "name": name,
        "kind": kind, "line": node.lineno, "doc_first_paragraph": doc, "doc_missing": not doc,
    }  # fmt: skip
    if isinstance(node, ast.ClassDef):
        spec["signature"], spec["init_from"] = class_signature(idx, rel, node)
        if spec["init_from"] == "none" and kind in ("Protocol", "ABC"):
            spec["signature"] = name  # у интерфейса нет конструктора: пустые скобки обманули бы
        members = class_members(node)
        spec["bases"] = [ast.unparse(b) for b in node.bases]
        spec["members"] = members
        spec["inherited_members"] = inherited_members(idx, rel, node, {m["name"] for m in members})
        collide = len(idx.classes_by_name.get(name, []))
        subs = [
            c for c in idx.subclasses_by_base.get(name, [])
            if not c.is_test and (collide <= 1 or refers_to(idx, c.file, rel, module, name))
        ]  # fmt: skip
        spec["subclasses"] = [{"name": c.qualname, "where": f"{c.file}:{c.line}"} for c in subs[:SUBCLASSES_CAP]]
        spec["subclasses_total"] = len(subs)
        spec["name_collisions"] = collide - 1
        required = abstract_names(node, kind) if kind in ("Protocol", "ABC") else set()
        spec["structural_matches"], spec["structural_total"] = structural_matches(idx, name, required)
    else:
        spec["signature"] = func_signature(node)  # type: ignore[arg-type]
    hits, same = call_site_hits(idx, rel, module, owner, node)
    spec["call_sites"] = short_first(hits)[:CALL_SITES_CAP]
    spec["call_sites_total"] = len(hits)
    spec["same_file_calls"] = same
    spec["call_sites_note"] = CALL_SITES_NOTE
    tests = test_hits(idx, rel, module, owner, node)
    spec["tests"] = short_first(tests)[:TESTS_CAP]
    spec["tests_total"] = len(tests)
    spec["io"] = io_of(node)
    spec["uses_count"] = uses_count(idx, rel, node)
    spec["line1"] = f"{kind} — {one_sentence(doc)}" if doc else f"{kind} — докстринга нет"
    spec["line2"] = f"использует меня {len(hits)} (вызовы по имени) / использую {spec['uses_count']}"
    spec["line3"] = None
    spec["red"] = False
    return spec


def structural_matches(idx: Index, name: str, required: set[str]) -> tuple[list[dict], int]:
    """Классы, не наследующие `name`, но имеющие все обязательные имена интерфейса (в своём теле)."""
    if not required:
        return [], 0
    skip = subclass_closure(idx, name) | {name}
    found = [
        f"{c.file}:{c.line}::{c.qualname}"
        for classes in idx.classes_by_name.values()
        for c in classes
        if not c.is_test and c.name not in skip and not {"Protocol", "ABC"} & set(c.bases) and required <= c.own
    ]
    ordered = short_first(found)
    out = []
    for item in ordered[:STRUCTURAL_CAP]:
        where, qual = item.split("::", 1)
        out.append({"name": qual, "where": where})
    return out, len(found)


# --------------------------------------------------------------------------- район: файл


def district_spec(root: str | Path, path: str) -> dict:
    """Вывеска района (файла): первая строка докстринга и список домов верхнего уровня."""
    root = Path(root)
    rel = norm_path(root, path)
    idx = get_index(root)
    tree = tree_of(idx, rel)
    module = idx.files[rel].module
    doc = (ast.get_docstring(tree, clean=True) or "").strip().split("\n")[0].strip()
    houses = []
    for qualname, node in iter_defs(tree.body, ""):
        if "." in qualname:
            continue
        hits, _same = call_site_hits(idx, rel, module, None, node)
        node_doc = (ast.get_docstring(node, clean=True) or "").strip().split("\n")[0].strip()
        houses.append(
            {"name": qualname, "kind": house_kind(node, None), "one_line": node_doc, "public": not is_private(qualname),
             "call_sites": len(hits)}
        )  # fmt: skip
    spec: dict = {
        "level": "district", "id": rel, "path": rel, "name": Path(rel).name, "doc_line": doc, "houses": houses,
    }  # fmt: skip
    file_in = file_out = None
    view = try_model_view(root)
    if view is not None:
        file_id = module + ".__init__" if idx.files[rel].is_init else module
        if file_id in view.nodes:
            file_in = len({e["src"] for e in view.edges if e["dst"] == file_id and e["src"] != file_id})
            file_out = len({e["dst"] for e in view.edges if e["src"] == file_id and e["dst"] != file_id})
    public = sum(1 for h in houses if h["public"])
    spec["files_in"], spec["files_out"] = file_in, file_out
    spec["line1"] = doc or "докстринга модуля нет"
    inout = "" if file_in is None else f"использует меня {file_in} файлов / использую {file_out} · "
    spec["line2"] = f"{inout}домов {len(houses)} (публичных {public})"
    spec["line3"] = None
    spec["red"] = False
    return spec


# --------------------------------------------------------------------------- модель: слой, юнит, пакет


class ModelView:
    """model.json с индексами: узлы, потомки, рёбра hard+lazy, находки."""

    def __init__(self, model: dict) -> None:
        self.model = model
        self.nodes: dict[str, dict] = {n["id"]: n for n in model["nodes"]}
        self.by_path: dict[str, dict] = {n["path"]: n for n in model["nodes"] if n.get("path")}
        self.layers: list[str] = model["meta"]["layers"]
        self.children: dict[str, list[str]] = {}
        for n in model["nodes"]:
            if n.get("parent"):
                self.children.setdefault(n["parent"], []).append(n["id"])
        self.edges = [e for e in model["edges"] if e["kind"] in ("hard", "lazy")]
        self.findings: list[dict] = model["findings"]

    def descendants(self, node_id: str) -> list[dict]:
        out: list[dict] = []
        todo = list(self.children.get(node_id, ()))
        while todo:
            node = self.nodes[todo.pop()]
            out.append(node)
            todo.extend(self.children.get(node["id"], ()))
        return out


_MODEL_CACHE: dict[str, ModelView] = {}


def load_model_view(root: Path, model_path: str = DEFAULT_MODEL) -> ModelView:
    path = (root / model_path).resolve()
    key = f"{path}:{path.stat().st_mtime_ns}" if path.is_file() else str(path)
    if key not in _MODEL_CACHE:
        if not path.is_file():
            raise SignboardError(f"нет модели {path}: сначала python scripts/arch_map/build.py")
        _MODEL_CACHE[key] = ModelView(json.loads(path.read_text(encoding="utf-8")))
    return _MODEL_CACHE[key]


def try_model_view(root: Path) -> ModelView | None:
    try:
        return load_model_view(root)
    except SignboardError:
        return None


def layer_rule(layers: list[str], layer: str) -> tuple[list[str], list[str]]:
    """(можно импортировать из, нельзя импортировать из) — по правилам build.py (RULES, README: «Слои»)."""
    chain = [name for name in layers if name != EXTERNAL]
    if layer == EXTERNAL or layer not in chain:
        return chain, []
    pos = chain.index(layer)
    allowed, forbidden = chain[:pos], chain[pos + 1 :]
    if EXTERNAL in layers:
        (forbidden if layer in NO_EXTERNAL_IMPORT else allowed).append(EXTERNAL)
    return allowed, forbidden


def rule_text(layers: list[str], layer: str) -> str:
    allowed, forbidden = layer_rule(layers, layer)
    return f"можно → {', '.join(allowed) or 'никого'}; нельзя ← {', '.join(forbidden) or 'нет запретов'}"


def severity_counts(findings: list[dict]) -> dict[str, int]:
    return {sev: sum(1 for f in findings if f["severity"] == sev) for sev in SEVERITIES}


def direction_line(count: int) -> str:
    return f"нарушений направления: {count}"


def doc_first_line(root: Path, rel_init: str) -> str | None:
    tree = parse_file(root / rel_init)
    doc = ast.get_docstring(tree, clean=True) if tree else None
    return doc.strip().split("\n")[0].strip() if doc and doc.strip() else None


def aggregate(view: ModelView, node_id: str) -> dict:
    below = view.descendants(node_id)
    files = [n for n in below if n["kind"] == "file"]
    return {
        "units": sum(1 for n in below if n["kind"] == "unit" and not n.get("synthetic")),
        "packages": sum(1 for n in below if n["kind"] == "package"),
        "files": len(files),
        "loc": sum(n.get("loc", 0) for n in files),
        "classes": sum(len(n.get("classes", [])) for n in files),
        "functions": sum(len(n.get("functions", [])) for n in files),
    }


def finish_model_spec(spec: dict, findings: list[dict], line1: str, fan_in: int, fan_out: int, fan_what: str) -> dict:
    direction = sum(1 for f in findings if f["rule"] == "layer-reverse")
    spec.update(
        direction_violations=direction,
        findings_by_severity=severity_counts(findings),
        fan_in=fan_in,
        fan_out=fan_out,
        line1=line1,
        line2=f"использует меня {fan_in} / использую {fan_out} ({fan_what})",
        line3=direction_line(direction),
        red=direction > 0,
    )
    return spec


def layer_spec(root: str | Path, layer_id: str, view: ModelView | None = None) -> dict:
    """Вывеска слоя (материка): назначение, правило направления, счётчики, находки, нарушения направления."""
    root = Path(root)
    view = view or load_model_view(root)
    node = view.nodes.get(layer_id)
    if node is None or node["kind"] != "layer":
        raise SignboardError(f"нет слоя {layer_id} в model.json")
    purpose = doc_first_line(root, f"{layer_id}/__init__.py")
    findings = [f for f in view.findings if layer_of(f.get("src_unit") or f.get("src") or "") == layer_id]
    fan_in = sum(1 for e in view.edges if layer_of(e["dst"]) == layer_id and layer_of(e["src"]) != layer_id)
    fan_out = sum(1 for e in view.edges if layer_of(e["src"]) == layer_id and layer_of(e["dst"]) != layer_id)
    spec = {
        "level": "layer", "id": layer_id, "name": layer_id, "purpose": purpose,
        "import_rule": rule_text(view.layers, layer_id), "counts": aggregate(view, layer_id),
    }  # fmt: skip
    line1 = purpose or "назначение не задано: у слоя нет докстринга __init__.py"
    return finish_model_spec(spec, findings, line1, fan_in, fan_out, "импортов между слоями, hard+lazy")


def unit_spec(root: str | Path, unit_id: str, view: ModelView | None = None) -> dict:
    """Вывеска юнита (страны) или группы плагинов."""
    root = Path(root)
    view = view or load_model_view(root)
    node = view.nodes.get(unit_id)
    if node is None or node["kind"] not in ("unit", "group"):
        raise SignboardError(f"нет юнита {unit_id} в model.json")
    layer = layer_of(unit_id)
    spec_in = node.get("spec", {})
    card = spec_in.get("card", {})
    findings = [f for f in view.findings if f.get("src_unit") == unit_id]
    interfaces = [f"{i['name']} ({i['style']})" for i in spec_in.get("interfaces", [])]
    spec = {
        "level": "unit", "id": unit_id, "name": node["name"], "path": node.get("path"), "kind": node["kind"],
        "purpose": card.get("purpose"), "tier": card.get("tier") or spec_in.get("tier"),
        "import_rule": rule_text(view.layers, layer) + "; в чужой юнит — через его витрину (__init__, interfaces)",
        "counts": {
            **{k: v for k, v in aggregate(view, unit_id).items() if k != "units"},
            "loc_unit": spec_in.get("loc"),
            "tests": spec_in.get("tests"),
        },
        "interfaces": interfaces, "all": spec_in.get("all") or [], "commands": card.get("commands") or [],
        "recipes": spec_in.get("recipes") or [], "instability": spec_in.get("instability"),
    }  # fmt: skip
    if "fan_in" in spec_in:
        fan_in, fan_out, fan_what = spec_in["fan_in"], spec_in["fan_out"], "юнитов, hard+lazy"
    else:  # группа и юниты без spec: импорты файлов через границу узла
        inside = {n["id"] for n in view.descendants(unit_id)}
        fan_in = sum(1 for e in view.edges if e["dst"] in inside and e["src"] not in inside)
        fan_out = sum(1 for e in view.edges if e["src"] in inside and e["dst"] not in inside)
        fan_what = "импортов через границу, hard+lazy"
    line1 = card.get("purpose") or "назначение не задано (докстринг __init__.py и modules.yaml пусты)"
    return finish_model_spec(spec, findings, line1, fan_in, fan_out, fan_what)


def package_spec(root: str | Path, package_id: str, view: ModelView | None = None) -> dict:
    """Вывеска пакета (города): назначение из `__init__.py`, счётчики, импорты через границу пакета."""
    root = Path(root)
    view = view or load_model_view(root)
    node = view.nodes.get(package_id)
    if node is None or node["kind"] != "package":
        raise SignboardError(f"нет пакета {package_id} в model.json")
    inside = {n["id"] for n in view.descendants(package_id)}
    purpose = doc_first_line(root, f"{node['path']}/__init__.py")
    findings = [f for f in view.findings if f.get("src") in inside]
    fan_in = sum(1 for e in view.edges if e["dst"] in inside and e["src"] not in inside)
    fan_out = sum(1 for e in view.edges if e["src"] in inside and e["dst"] not in inside)
    layer = layer_of(package_id)
    spec = {
        "level": "package", "id": package_id, "name": node["name"], "path": node["path"], "purpose": purpose,
        "import_rule": "правило слоя " + layer + ": " + rule_text(view.layers, layer),
        "counts": aggregate(view, package_id),
    }  # fmt: skip
    line1 = purpose or "назначение не задано: у пакета нет докстринга __init__.py"
    return finish_model_spec(spec, findings, line1, fan_in, fan_out, "импортов через границу пакета, hard+lazy")


def spec_for(root: str | Path, target: str) -> dict:
    """Вывеска по адресу: `путь::имя` — дом; `файл.py` — район; каталог или id — слой, юнит или пакет."""
    root = Path(root)
    path, _, qualname = target.partition("::")
    rel = norm_path(root, path)
    if qualname:
        return house_spec(root, rel, qualname)
    if rel.endswith(".py") and (root / rel).is_file():
        return district_spec(root, rel)
    view = load_model_view(root)
    node = view.nodes.get(rel) or view.by_path.get(rel)
    if node is None:
        raise SignboardError(f"{rel}: не файл .py, не слой/юнит/пакет из model.json")
    if node["kind"] == "layer":
        return layer_spec(root, node["id"], view)
    if node["kind"] in ("unit", "group"):
        return unit_spec(root, node["id"], view)
    if node["kind"] == "package":
        return package_spec(root, node["id"], view)
    raise SignboardError(f"{rel}: узел вида {node['kind']} — используйте `путь.py`")


# --------------------------------------------------------------------------- человеческий вид карточки


def cut(text: str, limit: int | None) -> str:
    return text if limit is None or len(text) <= limit else text[: limit - 1].rstrip() + "…"


def member_line(m: dict) -> str:
    return ("[abstract] " if m["abstract"] else "") + m["signature"]


def house_sections(spec: dict, cap: int | None, doc_limit: int | None) -> list[tuple[str, list[str]]]:
    def head(items: list, n: int | None = cap) -> list:
        return items if n is None else items[:n]

    secs: list[tuple[str, list[str]]] = [
        (
            "Сигнатура",
            [spec["signature"]]
            if "init_from" not in spec
            else [f"{spec['signature']}   (__init__: {spec['init_from']})"],
        )
    ]
    if spec["doc_first_paragraph"]:
        secs.append(("Докстринг", [cut(spec["doc_first_paragraph"], doc_limit)]))
    if spec.get("bases"):
        secs.append(("Базы", [", ".join(spec["bases"])]))
    if spec.get("members"):
        lines = [member_line(m) for m in head(spec["members"])]
        if cap is not None and len(spec["members"]) > cap:
            lines.append(f"… ещё {len(spec['members']) - cap}")
        secs.append((f"Члены ({len(spec['members'])})", lines))
    if spec.get("inherited_members"):
        lines = [f"{m['from']}: {member_line(m)}" for m in head(spec["inherited_members"])]
        if cap is not None and len(spec["inherited_members"]) > cap:
            lines.append(f"… ещё {len(spec['inherited_members']) - cap}")
        secs.append((f"Унаследовано ({len(spec['inherited_members'])})", lines))
    if "subclasses" in spec:
        title = f"Наследники по имени базы ({spec['subclasses_total']})"
        if spec["name_collisions"]:
            title += f"; имя занято ещё {spec['name_collisions']} раз — отфильтровано по импорту"
        lines = [f"{s['name']}  {s['where']}" for s in head(spec["subclasses"], 8 if cap else None)]
        secs.append((title, lines or ["нет"]))
        if spec["kind"] in ("Protocol", "ABC"):
            lines = [f"{s['name']}  {s['where']}" for s in spec["structural_matches"]]
            secs.append((f"Структурно подходят, не наследуют ({spec['structural_total']})", lines or ["нет"]))
    secs.append(
        (f"Вызовы по имени: {spec['call_sites_total']} (+{spec['same_file_calls']} в файле); 0 — не «не используется»",
         spec["call_sites"] or ["не найдено по имени"])
    )  # fmt: skip
    secs.append((f"Тесты ({spec['tests_total']})", spec["tests"] or ["не найдено по имени"]))
    if spec["io"]:
        secs.append(("Ввод-вывод", [f"{i['op']}  {i['path_expr']}  :{i['line']}" for i in spec["io"]]))
    return secs


def district_sections(spec: dict, cap: int | None) -> list[tuple[str, list[str]]]:
    lines = [
        f"{'' if h['public'] else '_'}{h['name'].lstrip('_')} — {h['kind']}"
        + (f" — {cut(h['one_line'], 80 if cap else None)}" if h["one_line"] else "")
        + f" — вызовов по имени {h['call_sites']}"
        for h in spec["houses"]
    ]
    return [(f"Дома ({len(spec['houses'])})", lines or ["нет"])]


def model_sections(spec: dict) -> list[tuple[str, list[str]]]:
    counts = spec["counts"]
    count_text = ", ".join(f"{k} {v}" for k, v in counts.items() if v is not None)
    sev = spec["findings_by_severity"]
    secs = [
        ("Правило направления импортов", [spec["import_rule"]]),
        ("Счётчики", [count_text]),
        ("Находки по серьёзности", [", ".join(f"{k} {v}" for k, v in sev.items())]),
    ]
    if spec["level"] == "unit":
        extra = [
            ("Интерфейсы", spec["interfaces"] or ["нет"]),
            ("Витрина __all__", [", ".join(spec["all"]) or "нет"]),
            ("Рецепты, где назван", [str(len(spec["recipes"]))]),
        ]
        if spec["tier"]:
            secs.append(("Ярус", [spec["tier"]]))
        secs.extend(extra)
    return secs


def card_view(spec: dict, cap: int | None = None, doc_limit: int | None = None) -> dict:
    """Карточка для человека: строки 1–3 и разделы под сгибом. cap/doc_limit — урезание для страницы."""
    level = spec["level"]
    if level == "house":
        sections = house_sections(spec, cap, doc_limit)
    elif level == "district":
        sections = district_sections(spec, cap)
    else:
        sections = model_sections(spec)
    return {
        "level": level, "title": spec.get("qualname") or spec["name"], "line1": cut(spec["line1"], doc_limit),
        "line2": spec["line2"], "line3": spec["line3"], "red": spec["red"], "sections": sections,
    }  # fmt: skip


def render_text(spec: dict) -> str:
    view = card_view(spec)
    out = [f"[{view['level']}] {view['title']}", view["line1"], view["line2"]]
    if view["line3"]:
        out.append(("!! " if view["red"] else "") + view["line3"])
    for heading, lines in view["sections"]:
        out.append("")
        out.append(f"{heading}:")
        out.extend(f"  {line}" for line in lines)
    return "\n".join(out)


# --------------------------------------------------------------------------- bench: эталон K0


def git_commit(root: Path) -> str | None:
    try:
        run = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return run.stdout.strip() or None if run.returncode == 0 else None


def run_bench(root: Path, targets_file: Path, out_file: Path) -> dict:
    """Эталон по списку целей: [{id, path, qualname?}]. Пишется только скриптом, руками не правится."""
    targets = json.loads(targets_file.read_text(encoding="utf-8"))
    if isinstance(targets, dict):
        targets = targets["targets"]
    result = []
    for target in targets:
        address = target["path"] + (f"::{target['qualname']}" if target.get("qualname") else "")
        spec = spec_for(root, address)
        result.append({"id": target["id"], "address": address, "level": spec["level"], "spec": spec})
    doc = {
        "meta": {"tool": "scripts/arch_map/signboard.py bench", "commit": git_commit(root), "targets": len(result),
                 "note": "сгенерировано скриптом из кода; не править руками"},
        "targets": result,
    }  # fmt: skip
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return doc


# --------------------------------------------------------------------------- cards.html


def build_cards_data(root: Path) -> dict:
    """Данные страницы: карточки слоёв и юнитов, дерево спуска в DRILL_UNIT с карточками до домов."""
    view = load_model_view(root)
    cards: dict[str, dict] = {}
    layers = []
    for layer in view.layers:
        cards[f"layer:{layer}"] = card_view(layer_spec(root, layer, view), cap=12, doc_limit=DOC_CUT)
        units = sorted(
            (n for n in view.descendants(layer) if n["kind"] in ("unit", "group")),
            key=lambda n: n["id"],
        )
        unit_items = []
        for n in units:
            cards[f"unit:{n['id']}"] = card_view(unit_spec(root, n["id"], view), cap=12, doc_limit=DOC_CUT)
            unit_items.append({"key": f"unit:{n['id']}", "label": unit_label(view, n)})
        layers.append({"key": f"layer:{layer}", "label": layer, "units": unit_items})
    tree = drill_tree(root, view, DRILL_UNIT, cards)
    featured = {}
    for kind, key in (("layer", f"layer:{FEATURED['layer']}"), ("unit", f"unit:{FEATURED['unit']}")):
        featured[kind] = key
    house_path, _, house_qual = FEATURED["house"].partition("::")
    house_key = f"house:{FEATURED['house']}"
    if house_key not in cards:
        cards[house_key] = card_view(house_spec(root, house_path, house_qual), cap=12, doc_limit=DOC_CUT)
    featured["house"] = house_key
    return {
        "meta": {"commit": git_commit(root), "drill": DRILL_UNIT, "cards": len(cards)},
        "layers": layers, "cards": cards, "tree": tree, "featured": featured,
    }  # fmt: skip


def unit_label(view: ModelView, node: dict) -> str:
    """Имя юнита для чипа; у корневых `__root__` — с именем родителя, иначе «(корень)» не различить."""
    if node["name"] != "__root__":
        return node["name"]
    parent = view.nodes.get(node.get("parent") or "")
    return f"{parent['name'] if parent else '?'}/(корень)"


def drill_tree(root: Path, view: ModelView, unit_id: str, cards: dict[str, dict]) -> dict:
    """Юнит → пакеты → файлы → дома; карточки каждого уровня кладёт в `cards`."""
    open_file = FEATURED["house"].partition("::")[0]

    def node_for(node_id: str) -> dict:
        node = view.nodes[node_id]
        kind = node["kind"]
        if kind == "unit":
            key = f"unit:{node_id}"
        elif kind == "package":
            key = f"pkg:{node_id}"
            cards[key] = card_view(package_spec(root, node_id, view), cap=12, doc_limit=DOC_CUT)
        else:
            key = f"file:{node['path']}"
            district = district_spec(root, node["path"])
            cards[key] = card_view(district, cap=12, doc_limit=DOC_CUT)
        item = {"key": key, "label": node["name"] + (".py" if kind == "file" else ""), "kind": kind, "children": []}
        kids = sorted(
            view.children.get(node_id, ()), key=lambda i: (view.nodes[i]["kind"] == "file", view.nodes[i]["name"])
        )
        item["children"] = [node_for(k) for k in kids]
        if kind == "file":
            item["open"] = node["path"] == open_file
            for house in district["houses"]:
                hkey = f"house:{node['path']}::{house['name']}"
                cards[hkey] = card_view(house_spec(root, node["path"], house["name"]), cap=12, doc_limit=DOC_CUT)
                item["children"].append({"key": hkey, "label": f"{house['kind']} {house['name']}", "kind": "house"})
        else:
            item["open"] = True
        return item

    return node_for(unit_id)


def render_page(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return PAGE_TEMPLATE.replace("__DATA__", payload)


PAGE_TEMPLATE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Вывески кода</title>
<style>
:root {
  --bg: #f6f7f9; --panel: #ffffff; --ink: #1b1f24; --muted: #5c6670; --line: #d5dae0;
  --accent: #1f6feb; --ok: #1a7f37; --red: #c62828; --red-bg: #fdecea; --chip: #eef1f5; --chip-hover: #dde6f5;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #12161b; --panel: #1b2128; --ink: #e6eaee; --muted: #9aa5b1; --line: #323b45;
    --accent: #5ea1ff; --ok: #56d364; --red: #ff6b63; --red-bg: #3a1f1e; --chip: #232b34; --chip-hover: #2c3947;
  }
}
:root[data-theme="dark"] {
  --bg: #12161b; --panel: #1b2128; --ink: #e6eaee; --muted: #9aa5b1; --line: #323b45;
  --accent: #5ea1ff; --ok: #56d364; --red: #ff6b63; --red-bg: #3a1f1e; --chip: #232b34; --chip-hover: #2c3947;
}
* { box-sizing: border-box; }
.card, .region { min-width: 0; overflow-wrap: anywhere; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.45 system-ui, "Segoe UI", sans-serif; }
header, main { max-width: 1280px; margin: 0 auto; padding: 0 16px; }
header { padding-top: 20px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 28px 0 10px; }
.sub { color: var(--muted); margin: 0; font-size: 13px; }
.feat { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }
.layers { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }
.region { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; }
.region > .head { margin-bottom: 8px; }
.units { display: flex; flex-wrap: wrap; gap: 4px; max-height: 260px; overflow: auto; }
button.item, summary.item {
  font: inherit; color: var(--ink); background: var(--chip); border: 1px solid transparent; border-radius: 6px;
  padding: 2px 8px; cursor: pointer; text-align: left;
}
button.item:hover, button.item:focus-visible, summary.item:hover, summary.item:focus-visible {
  background: var(--chip-hover); border-color: var(--accent); outline: none;
}
button.layer { font-weight: 600; font-size: 15px; }
button.unit { font-size: 12.5px; }
.tree details { margin: 2px 0 2px 14px; }
.tree summary { list-style-position: outside; }
.tree summary.item { display: list-item; width: fit-content; }
.tree ul { list-style: none; margin: 2px 0 2px 14px; padding: 0; }
.tree li { margin: 2px 0; }
.tree button.item { font-size: 13px; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; }
.card.red { border-color: var(--red); }
.card .lvl { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
.card .l1 { font-weight: 600; margin-top: 2px; }
.card .l2 { color: var(--muted); }
.card .l3 { font-size: 13px; color: var(--ok); }
.card .l3.red { color: var(--red); background: var(--red-bg); border-radius: 4px; padding: 0 6px;
  display: inline-block; }
.card .fold { border-top: 1px dashed var(--line); margin-top: 8px; padding-top: 6px; font-size: 13px; }
.card h4 { margin: 8px 0 2px; font-size: 12px; color: var(--muted); font-weight: 600; }
.card pre { margin: 0; white-space: pre-wrap; word-break: break-word;
  font: 12px/1.4 ui-monospace, Consolas, monospace; }
#pop { position: fixed; z-index: 10; width: 420px; max-width: calc(100vw - 16px); max-height: 60vh; overflow: auto;
  box-shadow: 0 6px 24px rgba(0, 0, 0, .25); border-radius: 10px; }
#pop[hidden] { display: none; }
@media (max-width: 640px) {
  #pop { left: 8px !important; right: 8px; bottom: 8px; top: auto !important; width: auto; max-height: 50vh; }
  body { font-size: 14px; }
}
</style>
</head>
<body>
<header>
  <h1>Вывески кода</h1>
  <p class="sub">Карточки считаются скриптом scripts/arch_map/signboard.py из кода и model.json. Наведите, сфокусируйте
  (Tab) или коснитесь объекта — появится карточка; клик закрепляет, Esc снимает. <span id="meta"></span></p>
</header>
<main>
  <h2>Три карточки: слой, юнит, класс</h2>
  <div class="feat" id="feat"></div>
  <h2>Материки: слои и их юниты</h2>
  <div class="layers" id="layers"></div>
  <h2 id="drill-h">Спуск</h2>
  <div class="tree" id="drill"></div>
</main>
<div id="pop" role="tooltip" hidden></div>
<script>
const DATA = __DATA__;
const CARDS = DATA.cards;
const pop = document.getElementById('pop');
let pinned = null;

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function cardNode(c) {
  const root = el('div', 'card' + (c.red ? ' red' : ''));
  root.append(el('div', 'lvl', c.level + ' · ' + c.title));
  root.append(el('div', 'l1', c.line1));
  root.append(el('div', 'l2', c.line2));
  if (c.line3) root.append(el('div', 'l3' + (c.red ? ' red' : ''), c.line3));
  const fold = el('div', 'fold');
  for (const [head, lines] of c.sections) {
    fold.append(el('h4', '', head));
    fold.append(el('pre', '', lines.join('\n')));
  }
  if (c.sections.length) root.append(fold);
  return root;
}

function place(target) {
  if (window.innerWidth <= 640) { pop.style.left = ''; pop.style.top = ''; return; }
  const r = target.getBoundingClientRect();
  const w = pop.offsetWidth, h = pop.offsetHeight;
  let left = Math.min(Math.max(8, r.left), window.innerWidth - w - 8);
  let top = r.bottom + 6;
  if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 6);
  pop.style.left = left + 'px';
  pop.style.top = top + 'px';
}

function show(key, target) {
  const c = CARDS[key];
  if (!c) return;
  pop.replaceChildren(cardNode(c));
  pop.hidden = false;
  place(target);
}
function hide() { if (pinned === null) pop.hidden = true; }
function unpin() { pinned = null; pop.hidden = true; }

function bind(node, key) {
  node.addEventListener('mouseenter', () => { if (pinned === null) show(key, node); });
  node.addEventListener('mouseleave', hide);
  node.addEventListener('focus', () => { if (pinned === null) show(key, node); });
  node.addEventListener('blur', hide);
  node.addEventListener('click', (ev) => { ev.stopPropagation(); pinned = key; show(key, node); });
}
document.addEventListener('click', unpin);
document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') unpin(); });
pop.addEventListener('click', (ev) => ev.stopPropagation());

function chip(key, label, cls) {
  const b = el('button', 'item ' + cls, label);
  b.type = 'button';
  bind(b, key);
  return b;
}

function renderLayers() {
  const host = document.getElementById('layers');
  for (const layer of DATA.layers) {
    const box = el('div', 'region');
    const head = el('div', 'head');
    head.append(chip(layer.key, layer.label, 'layer'));
    head.append(el('span', 'sub', ' · юнитов ' + layer.units.length));
    box.append(head);
    const units = el('div', 'units');
    for (const u of layer.units) units.append(chip(u.key, u.label, 'unit'));
    box.append(units);
    host.append(box);
  }
}

function renderTree(node) {
  if (node.kind === 'house') {
    const li = el('li');
    li.append(chip(node.key, node.label, 'house'));
    return li;
  }
  const d = el('details');
  d.open = !!node.open;
  const s = el('summary', 'item', node.label);
  bind(s, node.key);
  d.append(s);
  const ul = el('ul');
  for (const child of node.children) {
    if (child.kind === 'house') ul.append(renderTree(child));
    else d.append(renderTree(child));
  }
  if (ul.children.length) d.append(ul);
  return d;
}

function renderFeatured() {
  const host = document.getElementById('feat');
  for (const kind of ['layer', 'unit', 'house']) host.append(cardNode(CARDS[DATA.featured[kind]]));
}

document.getElementById('meta').textContent =
  'Снимок ' + (DATA.meta.commit || '?') + ', карточек ' + DATA.meta.cards + '.';
document.getElementById('drill-h').textContent = 'Спуск: ' + DATA.meta.drill + ' → пакеты → файлы → дома';
renderFeatured();
renderLayers();
document.getElementById('drill').append(renderTree(DATA.tree));
const m = /card=([^&]+)/.exec(decodeURIComponent(location.hash));
if (m && CARDS[m[1]]) { pinned = m[1]; show(m[1], document.getElementById('feat')); }
</script>
</body>
</html>
"""


def write_cards(root: Path, out_file: Path) -> int:
    html = render_page(build_cards_data(root))
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(html, encoding="utf-8")
    return len(html.encode("utf-8"))


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Вывески кода: дом, район, пакет, юнит, слой.")
    parser.add_argument("--root", default=".", help="корень репозитория (по умолчанию текущий каталог)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    show = sub.add_parser("show", help="вывеска по адресу путь[::имя]")
    show.add_argument("target")
    show.add_argument("--format", choices=("json", "text"), default="text")
    bench = sub.add_parser("bench", help="эталон по списку целей")
    bench.add_argument("--targets", default=DEFAULT_TARGETS)
    bench.add_argument("--out", default=DEFAULT_BENCH_OUT)
    cards = sub.add_parser("cards", help="страница cards.html")
    cards.add_argument("--out", default=DEFAULT_CARDS_OUT)
    return parser


def resolve_out(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if args.cmd == "show":
            spec = spec_for(root, args.target)
            print(json.dumps(spec, ensure_ascii=False, indent=2) if args.format == "json" else render_text(spec))
        elif args.cmd == "bench":
            doc = run_bench(root, resolve_out(root, args.targets), resolve_out(root, args.out))
            print(f"bench: {doc['meta']['targets']} целей -> {resolve_out(root, args.out)}")
        else:
            size = write_cards(root, resolve_out(root, args.out))
            print(f"cards: {size} байт -> {resolve_out(root, args.out)}")
    except SignboardError as exc:
        print(f"signboard: {exc}", file=sys.stderr)
        return 2
    idx = _INDEX_CACHE.get(str(root))
    if idx is not None and idx.parse_errors:
        print(
            f"signboard: не разобрано файлов: {len(idx.parse_errors)} (первый: {idx.parse_errors[0]})", file=sys.stderr
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
