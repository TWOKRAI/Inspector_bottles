"""Граф импортов фреймворка по AST — точная классификация каждого импорта.

Три класса рёбер:
  hard  — импорт на верхнем уровне модуля (исполняется при импорте пакета)
  lazy  — импорт внутри функции/метода/условия (не исполняется при импорте)
  tc    — импорт под `if TYPE_CHECKING:` (не исполняется никогда в рантайме)

Только AST, без импорта кода. Тесты исключены.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(os.getcwd())
MODULES_DIR = ROOT / "multiprocess_framework" / "modules"

if len(sys.argv) < 2:
    # путь отчёта обязателен намеренно: дефолт в cwd однажды уже насорил в корне репозитория
    print("usage: python scripts/arch_graph/ast_graph.py <путь-отчёта.txt>", file=sys.stderr)
    print("       рядом с отчётом кладётся ast_graph.json с теми же данными", file=sys.stderr)
    raise SystemExit(2)

REPORT = Path(sys.argv[1])

PKG_PREFIX = "multiprocess_framework.modules."


def is_test_path(p: Path) -> bool:
    parts = p.parts
    return "tests" in parts or p.name.startswith("test_") or p.name == "conftest.py"


def dotted(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def resolve(node: ast.ImportFrom, current: str, is_package: bool) -> str | None:
    """Абсолютное имя цели для `from ... import X`.

    Точка отсчёта разная: у `__init__.py` одна точка означает сам пакет,
    у обычного файла — его родителя. Смешение этих двух случаев теряет рёбра.
    """
    if node.level == 0:
        return node.module
    base = current.split(".")
    drop = node.level - 1 if is_package else node.level
    if drop > len(base):
        return None
    trimmed = base[: len(base) - drop] if drop else base
    if not trimmed:
        return None
    return ".".join(trimmed + ([node.module] if node.module else []))


def owner(name: str | None, roots: set[str]) -> str | None:
    if not name or not name.startswith(PKG_PREFIX):
        return None
    tail = name[len(PKG_PREFIX) :]
    head = tail.split(".")[0]
    return head if head in roots else None


def classify(tree: ast.Module) -> list[tuple[ast.stmt, str]]:
    """[(узел импорта, класс)] — обход с пометкой контекста."""
    found: list[tuple[ast.stmt, str]] = []

    def walk(node: ast.AST, kind: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                found.append((child, kind))
                continue
            if isinstance(child, ast.If):
                test = child.test
                is_tc = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
                    isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
                )
                inner = "tc" if (is_tc and kind == "hard") else kind
                for sub in child.body:
                    walk_stmt(sub, inner)
                for sub in child.orelse:
                    walk_stmt(sub, kind)
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, "lazy")
                continue
            if isinstance(child, ast.ClassDef):
                walk(child, kind)
                continue
            walk(child, kind)

    def walk_stmt(stmt: ast.stmt, kind: str) -> None:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            found.append((stmt, kind))
        else:
            walk(stmt, kind)

    walk(tree, "hard")
    return found


def tarjan(adj):
    index, low, on_stack, stack, out, counter = {}, {}, {}, [], [], [0]

    def strong(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack[v] = True
        for w in adj.get(v, ()):
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif on_stack.get(w):
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                comp.append(w)
                if w == v:
                    break
            out.append(sorted(comp))

    for v in adj:
        if v not in index:
            strong(v)
    return out


def tiers(adj, cyclic):
    level = {}

    def depth(v, seen):
        if v in level:
            return level[v]
        if v in seen:
            return 0
        deps = [d for d in adj.get(v, ()) if d != v and not (v in cyclic and d in cyclic)]
        level[v] = 0 if not deps else 1 + max(depth(d, seen | {v}) for d in deps)
        return level[v]

    for v in adj:
        depth(v, frozenset())
    return level


def main() -> int:
    roots = {
        p.name if p.is_dir() else p.stem
        for p in MODULES_DIR.iterdir()
        if (p.is_dir() and (p / "__init__.py").exists() and p.name not in {"tests", "__pycache__", "logs"})
        or (p.is_file() and p.suffix == ".py" and p.name not in {"__init__.py", "conftest.py"})
    }

    hard: dict[str, set[str]] = defaultdict(set)
    lazy: dict[str, set[str]] = defaultdict(set)
    tc: dict[str, set[str]] = defaultdict(set)
    evidence: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    files = 0

    for path in MODULES_DIR.rglob("*.py"):
        if is_test_path(path.relative_to(MODULES_DIR)):
            continue
        current = dotted(path)
        src = owner(current, roots)
        if src is None:
            continue
        files += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            print(f"SKIP {path}: {exc}")
            continue
        for node, kind in classify(tree):
            targets: list[str | None] = []
            if isinstance(node, ast.ImportFrom):
                targets.append(resolve(node, current, path.name == "__init__.py"))
            else:
                targets.extend(a.name for a in node.names)
            for target in targets:
                dst = owner(target, roots)
                if dst is None or dst == src:
                    continue
                {"hard": hard, "lazy": lazy, "tc": tc}[kind][src].add(dst)
                key = (src, dst, kind)
                if len(evidence[key]) < 3:
                    rel = path.relative_to(ROOT).as_posix()
                    evidence[key].append(f"{rel}:{node.lineno}")

    for d in (hard, lazy, tc):
        for r in roots:
            d.setdefault(r, set())

    scc_hard = [c for c in tarjan(hard) if len(c) > 1]
    runtime = {r: hard[r] | lazy[r] for r in roots}
    scc_runtime = [c for c in tarjan(runtime) if len(c) > 1]
    level = tiers(hard, {m for c in scc_hard for m in c})

    out: list[str] = []
    w = out.append
    w(f"ФАЙЛОВ разобрано: {files} · МОДУЛЕЙ: {len(roots)}")
    w("")
    w("=== ЦИКЛЫ по ЖЁСТКИМ рёбрам (import-time) ===")
    w("  нет" if not scc_hard else "")
    for comp in scc_hard:
        w("  цикл: " + " <-> ".join(comp))
        for a in comp:
            for b in hard[a]:
                if b in comp:
                    w(f"    {a} -> {b}: {'; '.join(evidence[(a, b, 'hard')])}")
    w("")
    w("=== ЦИКЛЫ с учётом отложенных (runtime, hard+lazy) ===")
    w("  нет" if not scc_runtime else "")
    for comp in scc_runtime:
        w("  цикл: " + " <-> ".join(comp))
        for a in comp:
            for b in comp:
                if b in lazy[a] and b not in hard[a]:
                    w(f"    ОТЛОЖЕННОЕ ребро {a} -> {b}: {'; '.join(evidence[(a, b, 'lazy')])}")
    w("")
    w("=== ТИРЫ (жёсткий граф) ===")
    by_level = defaultdict(list)
    for m, lv in level.items():
        by_level[lv].append(m)
    for lv in sorted(by_level):
        w(f"  тир {lv}: {', '.join(sorted(by_level[lv]))}")
    w("")
    w("=== МОДУЛЬ [тир] fan_in(жёсткий) ===")
    rows = []
    for r in sorted(roots):
        rows.append(
            {
                "module": r,
                "tier": level[r],
                "hard": sorted(hard[r]),
                "lazy_only": sorted(lazy[r] - hard[r]),
                "tc_only": sorted(tc[r] - hard[r] - lazy[r]),
                "fan_in_hard": sum(1 for o in roots if r in hard[o]),
                "fan_in_any": sum(1 for o in roots if r in hard[o] | lazy[o]),
            }
        )
    rows.sort(key=lambda x: (x["tier"], -x["fan_in_hard"], x["module"]))
    for r in rows:
        w(f"  [{r['tier']}] {r['module']:28} fan_in={r['fan_in_hard']:2} (с отлож. {r['fan_in_any']:2})")
        w(f"       -> {', '.join(r['hard']) or '(ничего)'}")
        if r["lazy_only"]:
            w(f"       отложенно -> {', '.join(r['lazy_only'])}")
        if r["tc_only"]:
            w(f"       TYPE_CHECKING -> {', '.join(r['tc_only'])}")

    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")
    (REPORT.parent / "ast_graph.json").write_text(
        json.dumps(
            {"cycles_hard": scc_hard, "cycles_runtime": scc_runtime, "rows": rows},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"report -> {REPORT}")
    return 0


if __name__ == "__main__":
    sys.setrecursionlimit(10000)
    raise SystemExit(main())
