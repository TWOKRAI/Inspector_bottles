"""Адаптер `code`: узлы interface и test, рёбра exposes и tests, находки качества по коду (Task 1.5a).

Purpose: интерфейс модуля (корневой interfaces.py) и его тесты; INTERFACE_WITHOUT_TEST — имя без теста;
    PRE_POST_MISSING — изменённый против `base` публичный метод без Pre:/Post: (разбор — scripts.s2_gate).
    Тесты и импорты разбираются регулярными выражениями, файлы читаются пакетно (`git cat-file --batch`).
Public API: CodeAdapter, S2_GATE.
Stability: lite
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from scripts.atlas.adapters.modules import modules_for
from scripts.atlas.adapters.plans import adapter_version
from scripts.atlas.modules import OTHER, resolve
from scripts.atlas.schema import AdapterOutput, BuildContext, Edge, Finding, Node
from scripts.atlas.tree import AtlasError, run_git
from scripts.s2_gate import contract_gaps

__all__ = ["S2_GATE", "CodeAdapter"]

S2_GATE = Path(__file__).resolve().parents[2] / "s2_gate.py"  # читается при вызове: смена парсера контракта -> версия
_TEST_FILE = re.compile(r"(?:^|/)(?:test_[^/]*|[^/]*_test)\.py$")
_DEFS = re.compile(
    r"^(?:(?:async[ \t]+)?def[ \t]+(\w+)|class[ \t]+(\w+)|[ ]{4}(?:async[ \t]+)?def[ \t]+(\w+))", re.MULTILINE
)
_AS = r"(?:[ \t]+as[ \t]+\w+)?"
_IMPORT = re.compile(
    rf"^[ \t]*(?:from[ \t]+(\.*[\w.]*)[ \t]+import\b|import[ \t]+(\w[\w.]*{_AS}(?:[ \t]*,[ \t]*\w[\w.]*{_AS})*))",
    re.MULTILINE,
)
_NEWLINE = re.compile(r"\r\n|\r|\n")


def _read(root: Path, ref: str, paths: list[str], strict: bool = True) -> dict[str, bytes | None]:
    """Содержимое `<ref>:<path>` одним `git cat-file --batch`; нет файла -> None (strict: AtlasError)."""
    proc = run_git(root, "cat-file", "--batch", input="".join(f"{ref}:{p}\n" for p in paths).encode("utf-8"))
    out: dict[str, bytes | None] = {}
    pos = 0
    try:
        if proc.returncode != 0 and paths:
            raise ValueError
        for path in paths:
            end = proc.stdout.index(b"\n", pos)
            header, pos = proc.stdout[pos:end], end + 1
            out[path] = None
            if not header.endswith(b" missing"):  # путь с пробелом даёт заголовок из 3+ частей
                _, kind, size = header.split(b" ")
                out[path] = proc.stdout[pos : pos + int(size)] if kind == b"blob" else None
                pos += int(size) + 1
            if strict and out[path] is None:
                raise ValueError
    except ValueError:
        raise AtlasError("atlas: git cat-file failed") from None
    return out


def _interface_names(module: ast.Module) -> list[str]:
    """Имена интерфейса: `__all__` (литералы) без дублей, иначе class/def верхнего уровня без `_`."""
    for node in module.body:
        targets = (
            node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets) and isinstance(
            node.value, ast.List | ast.Tuple
        ):
            return list(
                dict.fromkeys(
                    e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
                )
            )
    defs = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    return list(dict.fromkeys(n.name for n in module.body if isinstance(n, defs) and not n.name.startswith("_")))


def _test_ids(path: str, text: str) -> list[str]:
    """nodeid тестов файла: `def test…` без отступа и в `class Test…` (отступ 4); повтор — по первому вхождению."""
    ids: dict[str, None] = {}
    owner: str | None = None
    for top, klass, method in (m.groups() for m in _DEFS.finditer(text)):
        if klass is not None:
            owner = klass if klass.startswith("Test") else None
        elif top is not None:
            owner = None
            if top.startswith("test"):
                ids[f"{path}::{top}"] = None
        elif owner is not None and method.startswith("test"):
            ids[f"{path}::{owner}::{method}"] = None
    return list(ids)


def _imported_paths(text: str) -> set[str]:
    """Строки импортов файла: `a.b` и относительные (`..m`) как есть."""
    found: set[str] = set()
    for m in _IMPORT.finditer(text):
        found.update([m.group(1)] if m.group(1) is not None else (p.split()[0] for p in m.group(2).split(",")))
    return found


def _import_module(spec: str, folder: str, modules: list[dict], present: set[str]) -> str:
    """id модуля по строке импорта (`other` — нет); `<путь>/__init__.py` раньше `<путь>.py` (первый из `present`)."""
    if spec.startswith("."):
        rest = spec.lstrip(".")
        parts = folder.split("/") if folder else []
        up = len(spec) - len(rest) - 1
        if up > len(parts):
            return OTHER
        path = "/".join([*parts[: len(parts) - up], *([rest.replace(".", "/")] if rest else [])])
    else:
        path = spec.replace(".", "/")
    candidates = (f"{path}/__init__.py", f"{path}.py") if path else ()
    first = next((c for c in candidates if c in present), None)  # как Python: пакет раньше модуля, если он есть
    for candidate in [first] if first else candidates:
        found = resolve(candidate, modules)
        if found != OTHER:
            return found
    return OTHER


def _pre_post(mid: str, path: str, text: str, names: set[str], base_raw: bytes | None) -> list[Finding]:
    """PRE_POST_MISSING: публичные функции без маркеров, изменённые против base (нет файла/разбора -> все)."""
    gaps = contract_gaps(text)
    old: dict[str, set[str]] | None = None
    if gaps and base_raw is not None:
        base_text = base_raw.decode("utf-8", "replace").removeprefix("\ufeff")
        base_lines = _NEWLINE.split(base_text)
        try:
            old = {}
            for qualname, first, last, _ in contract_gaps(base_text):
                old.setdefault(qualname, set()).add("\n".join(base_lines[first - 1 : last]))
        except (SyntaxError, ValueError):
            old = None
    lines = _NEWLINE.split(text)
    found: dict[tuple[str, str], Finding] = {}
    for qualname, first, last, missing in gaps:
        node = f"interface:{mid}:{qualname.split('.')[0]}"
        if qualname.split(".")[0] not in names or (node, qualname) in found:
            continue
        if old is not None and "\n".join(lines[first - 1 : last]) in old.get(qualname, ()):
            continue
        msg = f"У изменённого {qualname} в docstring нет {' и '.join(missing)}"
        found[(node, qualname)] = Finding("PRE_POST_MISSING", "blocking", node, qualname, msg, f"{path}:{first}")
    return list(found.values())


class CodeAdapter:
    name = "code"
    _BASE = 2

    @property
    def version(self) -> int:
        return adapter_version(self._BASE, S2_GATE)

    def collect(self, ctx: BuildContext) -> AdapterOutput:
        tree, root = ctx.tree, ctx.tree.root
        modules = modules_for(tree)
        files = tree.files()
        present = set(files)
        out = AdapterOutput()
        iface: dict[str, str] = {}  # id модуля -> корневой interfaces.py (по одному на модуль)
        for row in modules:
            for element in row["paths"]:
                candidate = f"{element}interfaces.py"
                if element.endswith("/") and candidate in present and resolve(candidate, modules) == row["id"]:
                    iface[row["id"]] = candidate
                    break
        blobs = _read(root, tree.ref, list(iface.values()))
        # base читается по содержимому; нет файла на base — штатно (все функции «новые»)
        base_blobs = _read(root, ctx.base.ref, list(iface.values()), strict=False) if ctx.base is not None else {}
        names_of: dict[str, list[str]] = {}
        for mid, path in iface.items():
            text = (blobs[path] or b"").decode("utf-8", "replace").removeprefix("\ufeff")
            try:
                names = names_of[mid] = _interface_names(ast.parse(text))
            except (SyntaxError, ValueError):
                raise AtlasError("atlas: interfaces.py is not valid Python") from None
            for name in names:
                out.nodes.append(Node("interface", f"{mid}:{name}", path))
                out.edges.append(Edge("exposes", f"module:{mid}", f"interface:{mid}:{name}", "path"))
            if ctx.base is not None:
                out.findings += _pre_post(mid, path, text, set(names), base_blobs[path])

        test_paths = [p for p in files if _TEST_FILE.search(p)]
        linked: dict[str, list[str]] = {}  # id модуля -> тексты связанных тестовых файлов (с узлами test)
        for path, raw in _read(root, tree.ref, test_paths).items():
            text = (raw or b"").decode("utf-8", "replace")
            ids = _test_ids(path, text)
            if not ids:
                continue
            via: dict[str, str] = {}
            here = resolve(path, modules)
            if here != OTHER:
                via[here] = "path"
            folder = path.rpartition("/")[0]
            for spec in _imported_paths(text):
                found = _import_module(spec, folder, modules, present)
                if found != OTHER:
                    via.setdefault(found, "ast-import")
            for test_id in ids:
                out.nodes.append(Node("test", test_id, path))
                out.edges += [Edge("tests", f"test:{test_id}", f"module:{m}", v) for m, v in via.items()]
            for mid in via:
                linked.setdefault(mid, []).append(text)

        for mid, names in names_of.items():
            left = set(names)
            pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, names)) + r")\b") if names else None
            for text in linked.get(mid, ()):
                if not left:
                    break
                left.difference_update(pattern.findall(text))  # type: ignore[union-attr]
            for name in names:
                if name in left:
                    msg = f"У имени {name} нет теста: слово не найдено в тестах модуля {mid}"
                    out.findings.append(
                        Finding("INTERFACE_WITHOUT_TEST", "info", f"interface:{mid}:{name}", "", msg, iface[mid])
                    )
        return out
