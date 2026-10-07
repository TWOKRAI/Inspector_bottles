"""Виды справочника: `ref <module>` и `index`, файл docs/atlas/INDEX.md (Task 1.6b, ADR-ATL-001 §1-3).

Purpose: `ref` — интерфейсы модуля с сигнатурами, фразами docstring и тестами (AST корневого interfaces.py
    ревизии сборки + SQLite по build_id); `index` — весь проект: «id — purpose» и главные интерфейсы;
    `index_file` пишет и сверяет docs/atlas/INDEX.md. Вид возвращает список строк; соединение приходит от
    вызывающего, `store.connect` здесь не зовётся.
Public API: INDEX_PATH, index, index_file, ref.
Stability: lite
"""

from __future__ import annotations

import ast
import re
import sqlite3
import sys
from functools import reduce
from pathlib import Path

from scripts.atlas.adapters.code import _read
from scripts.atlas.adapters.modules import modules_for
from scripts.atlas.build import build
from scripts.atlas.tree import AtlasError, Tree, resolve
from scripts.atlas.views import purpose

__all__ = ["INDEX_PATH", "index", "index_file", "ref"]

INDEX_PATH = "docs/atlas/INDEX.md"
_HEADER = "# Индекс проекта — собран командой `python -m scripts.atlas index --write`, руками не править"
_NO_DOC = "нет описания"
_SENTENCE = re.compile(r"\.(?:\s|$)")
_MARKDOWN = (
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),
)
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _flat(node: ast.expr) -> list[ast.expr]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _flat(node.left) + _flat(node.right)
    return [node]


def _chain(parts: list[ast.expr]) -> ast.expr:
    return reduce(lambda a, b: ast.BinOp(a, ast.BitOr(), b), parts)


def _tag(node: ast.expr) -> str | None:
    if isinstance(node, ast.Subscript):
        node = node.value
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None


class _Simplify(ast.NodeTransformer):
    """Типы для чтения: Union/Optional -> `A | B`, кавычки форвард-ссылок сняты."""

    def _union(self, node: ast.expr) -> list[ast.expr]:
        if isinstance(node, ast.Subscript) and _tag(node) == "Union":
            elts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            return [m for e in elts for m in self._union(e)]
        if isinstance(node, ast.Subscript) and _tag(node) == "Optional":
            return [*self._union(node.slice), ast.Constant(None)]
        return _flat(self.visit(node))

    def visit_Subscript(self, node: ast.Subscript) -> ast.expr:
        if _tag(node) in ("Union", "Optional"):
            return _chain(self._union(node))
        return node if _tag(node) == "Literal" else self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> ast.expr:
        node = self.generic_visit(node)
        return _chain(_flat(node)) if isinstance(node.op, ast.BitOr) else node

    def visit_Constant(self, node: ast.Constant) -> ast.expr:
        if not isinstance(node.value, str):
            return node
        try:
            return self.visit(ast.parse(node.value.strip(), mode="eval").body)
        except SyntaxError:
            return ast.Name(id=node.value)


def _ann(node: ast.expr) -> str:
    return ast.unparse(_Simplify().visit(node))


def _param(arg: ast.arg, default: ast.expr | None) -> str:
    text = arg.arg if arg.annotation is None else f"{arg.arg}: {_ann(arg.annotation)}"
    if default is None:
        return text
    return f"{text}{'=' if arg.annotation is None else ' = '}{ast.unparse(default)}"


def _sig(fn: ast.FunctionDef | ast.AsyncFunctionDef, drop_first: bool) -> str:
    a = fn.args
    pos = [*a.posonlyargs, *a.args]
    items = list(zip(pos, [None] * (len(pos) - len(a.defaults)) + list(a.defaults)))
    fixed = len(a.posonlyargs)
    if drop_first and items:
        items, fixed = items[1:], max(fixed - 1, 0)
    parts = [_param(x, d) for x, d in items]
    if fixed:
        parts.insert(fixed, "/")
    if a.vararg:
        parts.append("*" + _param(a.vararg, None))
    elif a.kwonlyargs:
        parts.append("*")
    parts += [_param(x, d) for x, d in zip(a.kwonlyargs, a.kw_defaults)]
    if a.kwarg:
        parts.append("**" + _param(a.kwarg, None))
    marks = {_tag(d) for d in fn.decorator_list}
    ret = f" -> {_ann(fn.returns)}" if fn.returns is not None else ""
    if "property" in marks:
        return f"{fn.name}{ret}"
    return f"{'async ' if isinstance(fn, ast.AsyncFunctionDef) else ''}{fn.name}({', '.join(parts)}){ret}"


def _plain(text: str) -> str:
    for pattern, sub in _MARKDOWN:
        text = pattern.sub(sub, text)
    return text


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _phrase(node: ast.AST) -> str:
    """Первая фраза docstring (DESIGN п. 4)."""
    doc = ast.get_docstring(node)  # type: ignore[arg-type]
    if not doc:
        return _NO_DOC
    lines = [x.strip() for x in doc.split("\n")]
    para = " ".join(lines[: lines.index("")] if "" in lines else lines)
    cut = _SENTENCE.search(para)
    text = _plain(para[: cut.start()] if cut else para).strip()
    return _cut(text, 120) if text else _NO_DOC


def _pre_post(fn: ast.AST) -> str | None:
    """Строка `Pre: … / Post: …` по маркерам docstring (DESIGN п. 5); None — маркеров нет."""
    lines = [x.strip() for x in (ast.get_docstring(fn) or "").split("\n")]  # type: ignore[arg-type]
    found: list[str] = []
    for marker in ("Pre:", "Post:"):
        for i, line in enumerate(lines):
            if line.startswith(marker):
                text = line[len(marker) :].strip()
                nxt = next((x for x in lines[i + 1 :] if x), "")
                text = text or ("" if nxt.startswith(("Pre:", "Post:")) else nxt)
                text = _cut(_plain(re.sub(r"^[-*]\s+", "", text)).strip(), 100)
                if text:
                    found.append(f"{marker} {text}")
                break
    return " / ".join(found) or None


def _scan(raw: bytes | None) -> tuple[dict[str, tuple[str, ast.AST]], dict[str, int]]:
    """Имя верхнего уровня interfaces.py -> (вид, оператор); строка элемента `__all__` у имени."""
    text = (raw or b"").decode("utf-8", "replace").removeprefix("\ufeff")
    try:
        body = ast.parse(text).body
    except (SyntaxError, ValueError):
        raise AtlasError("atlas: interfaces.py is not valid Python") from None
    defs: dict[str, tuple[str, ast.AST]] = {}
    listed: dict[str, int] = {}
    for node in body:
        if isinstance(node, ast.ClassDef):
            defs[node.name] = ("class", node)
        elif isinstance(node, _FUNCS):
            defs[node.name] = ("func", node)
        elif isinstance(node, ast.ImportFrom):
            defs.update({a.asname or a.name: ("from", node) for a in node.names})
        elif isinstance(node, ast.Import):
            defs.update({a.asname or a.name.partition(".")[0]: ("other", node) for a in node.names})
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id == "__all__" and isinstance(node.value, ast.List | ast.Tuple):
                    listed = {e.value: e.lineno for e in reversed(node.value.elts) if isinstance(e, ast.Constant)}
                elif isinstance(t, ast.Name):
                    defs[t.id] = ("other", node)
    return defs, listed


def _methods(cls: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [m for m in cls.body if isinstance(m, _FUNCS) and not m.name.startswith("_")]  # type: ignore[attr-defined]


def _tests(
    con: sqlite3.Connection, root: Path, sha: str, bid: int, module: str, names: list[str]
) -> dict[str, tuple[int, str | None]]:
    """Имя -> (число узлов test в файлах, где есть слово имени; наименьший путь). Одно выражение на файл."""
    files = con.execute(
        "SELECT n.path, COUNT(DISTINCT n.id) FROM edges e JOIN nodes n ON n.build_id = e.build_id AND n.kind = 'test' "
        "AND n.id = substr(e.src, 6) WHERE e.build_id = ? AND e.kind = 'tests' AND e.dst = ? "
        "GROUP BY n.path ORDER BY n.path",
        (bid, f"module:{module}"),
    ).fetchall()
    pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, names)) + r")\b")
    count: dict[str, int] = {}
    first: dict[str, str] = {}
    for (path, nodes), raw in zip(files, _read(root, sha, [p for p, _ in files]).values()):
        for name in set(pattern.findall((raw or b"").decode("utf-8", "replace"))):
            count[name] = count.get(name, 0) + nodes
            first.setdefault(name, path)  # файлы идут по возрастанию пути
    return {n: (count.get(n, 0), first.get(n)) for n in names}


def ref(con: sqlite3.Connection, root: Path, ref: str, main_ref: str, module: str) -> list[str]:
    """Справочник модуля: интерфейсы по имени, у класса — публичные методы в порядке файла."""
    sha = resolve(root, ref)
    if all(r["id"] != module for r in modules_for(Tree(root, sha))):
        raise AtlasError("atlas: module not found")
    bid = build(con, root, ref, main_ref)
    prefix = f"{module}:"
    rows = con.execute(
        "SELECT id, path FROM nodes WHERE build_id = ? AND kind = 'interface' AND substr(id, 1, ?) = ?",
        (bid, len(prefix), prefix),
    ).fetchall()
    if not rows:
        return [f"Справочник модуля {module} — интерфейсов нет"]
    path = min(p for _, p in rows)
    names = sorted(i[len(prefix) :] for i, _ in rows)
    defs, listed = _scan(_read(root, sha, [path])[path])
    tests = _tests(con, root, sha, bid, module, names)
    lines = [f"Справочник модуля {module} — {path}, интерфейсов {len(names)}"]
    for name in names:
        kind, node = defs.get(name, ("none", None))
        label, text, line = name, _NO_DOC, listed.get(name, 1)
        if node is not None:
            line = node.lineno  # type: ignore[attr-defined]
        if kind == "func":
            label, text = _sig(node, False), _phrase(node)  # type: ignore[arg-type]
        elif kind == "class":
            text = _phrase(node)  # type: ignore[arg-type]
        elif kind == "from":
            text = f"реэкспорт из {'.' * node.level}{node.module or ''}"  # type: ignore[attr-defined]
        total, example = tests[name]
        lines.append(f"{label} — {text} — {path}:{line} — тестов {total}" + (f", пример {example}" if total else ""))
        for m in _methods(node) if kind == "class" else []:
            static = "staticmethod" in {_tag(d) for d in m.decorator_list}
            lines += [f"  {_sig(m, not static)}  :{m.lineno}", f"    {_phrase(m)}"]
            if (extra := _pre_post(m)) is not None:
                lines.append(f"    {extra}")
    return lines


def index(con: sqlite3.Connection, root: Path, ref: str, main_ref: str) -> list[str]:
    """Весь проект: «id — purpose» в порядке modules.yaml и до 5 главных интерфейсов модуля."""
    sha = resolve(root, ref)
    modules = modules_for(Tree(root, sha))
    bid = build(con, root, ref, main_ref)
    found: dict[str, list[str]] = {}
    paths: dict[str, str] = {}
    for node_id, path in con.execute("SELECT id, path FROM nodes WHERE build_id = ? AND kind = 'interface'", (bid,)):
        module, _, name = node_id.rpartition(":")
        found.setdefault(module, []).append(name)
        paths[module] = path
    blobs = _read(root, sha, sorted(set(paths.values())))
    scanned = {p: _scan(raw)[0] for p, raw in blobs.items()}
    lines = [_HEADER]
    for row in modules:
        lines.append(f"{row['id']} — {purpose(row)}")
        names = found.get(row["id"])
        if not names:
            continue
        defs = scanned[paths[row["id"]]]
        sized = sorted(
            ((len(_methods(defs[n][1])) if defs.get(n, ("",))[0] == "class" else 0, n) for n in names),
            key=lambda t: (-t[0], t[1]),
        )
        shown = [f"{n} ({k})" if defs.get(n, ("",))[0] == "class" else n for k, n in sized[:5]]
        more = f", … ещё {len(sized) - 5}" if len(sized) > 5 else ""
        lines.append("  " + ", ".join(shown) + more)
    return lines


def index_file(root: Path, lines: list[str], write: bool) -> int:
    """`index --write` пишет файл от корня репозитория; `--check` сверяет байты, файл не трогает. Код выхода."""
    data = ("\n".join(lines) + "\n").encode("utf-8")
    file = root / INDEX_PATH
    if write:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
        print(f"atlas index: {INDEX_PATH}, {len(lines)} строк")
        return 0
    try:
        fresh = file.read_bytes() == data
    except OSError:
        fresh = False
    if not fresh:
        print("atlas index: INDEX.md отстал — запусти atlas index --write", file=sys.stderr)
        return 1
    print(f"atlas index: {INDEX_PATH} свежий, {len(lines)} строк")
    return 0
