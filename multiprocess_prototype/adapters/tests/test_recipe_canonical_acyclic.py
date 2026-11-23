"""Слепая приёмка: recipe_canonical.py не зависит от stores/recipe_store.py (AC2-AC7).

Поведение-сохраняющий рефакторинг: чистая dict-функция ``RecipeStoreFromManager._denormalize``
переезжает в ``recipe_canonical.denormalize_recipe_dict``; файловый цикл между
``recipe_canonical.py`` и ``stores/recipe_store.py`` исчезает.

Ожидаемые значения — литералы, написанные руками, не выводятся из проверяемого кода.
Один тест на критерий; новое имя импортируется ВНУТРИ теста, чтобы каждый падал отдельно.
AC1 («после import recipe_canonical в sys.modules нет recipe_store») снят решением лида: пакет
``adapters/__init__`` сам жадно импортирует ``stores``, так что recipe_store грузится при любом импорте
пакета. Свойство «canonical не зависит от store» проверяют AC2 (AST) и AC3 (файловый граф).
"""

from __future__ import annotations

import ast
import copy
from pathlib import Path

# <корень репо> / multiprocess_prototype / adapters / tests / <этот файл>
ROOT = Path(__file__).resolve().parents[3]
ADAPTERS = ROOT / "multiprocess_prototype" / "adapters"
ADAPTERS_PKG = "multiprocess_prototype.adapters"
CANONICAL = ADAPTERS / "recipe_canonical.py"

# Литерал из AC4 (blueprint лежит на верхнем уровне, формат v3 — предикат detect его принимает).
AC4_INPUT = {
    "meta": {"name": "r1", "version": "2", "description": "d", "created_at": "t", "zzz": 7},
    "displays": [{"id": "d1"}],
    "blueprint": {"processes": [], "wires": []},
    "active_services": ["s"],
}
AC4_KEYS = ["name", "version", "description", "created_at", "zzz", "displays", "blueprint", "active_services"]


# --------------------------------------------------------------------------------------
# Помощники (вынесены на уровень модуля, чтобы break-injection мог гонять их на мутантах)
# --------------------------------------------------------------------------------------


def non_test_files() -> list[Path]:
    """Все не-тестовые ``*.py`` под adapters/ (без каталогов tests, test_*.py, conftest.py)."""
    result = []
    for p in sorted(ADAPTERS.rglob("*.py")):
        rel = p.relative_to(ADAPTERS)
        if "tests" in rel.parts or p.name.startswith("test_") or p.name == "conftest.py":
            continue
        result.append(p)
    return result


def collect_imports(path: Path) -> list[tuple[int, str, str | None, int, list[str]]]:
    """(lineno, kind, module, level, имена) для каждого Import/ImportFrom на ЛЮБОЙ вложенности."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found.append((node.lineno, "import", a.name, 0, []))
        elif isinstance(node, ast.ImportFrom):
            found.append((node.lineno, "from", node.module, node.level, [a.name for a in node.names]))
    return found


def module_name_of(path: Path) -> str:
    """Имя модуля файла: adapters/x/__init__.py -> пакет x; adapters/x/y.py -> x.y."""
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def build_file_graph() -> dict[Path, set[Path]]:
    """Файловый граф импортов внутри adapters (узлы — не-тестовые файлы; внешние цели игнорируются)."""
    files = non_test_files()
    by_module: dict[str, Path] = {module_name_of(p): p for p in files}
    graph: dict[Path, set[Path]] = {p: set() for p in files}
    for p in files:
        is_pkg = p.name == "__init__.py"
        cur_pkg = module_name_of(p) if is_pkg else module_name_of(p).rpartition(".")[0]
        for _lineno, kind, module, level, names in collect_imports(p):
            targets: list[str] = []
            if kind == "import":
                assert module is not None
                targets.append(module)
            else:
                if level:
                    base_parts = cur_pkg.split(".")
                    base_parts = base_parts[: len(base_parts) - (level - 1)]
                    base = ".".join(base_parts)
                    full = f"{base}.{module}" if module else base
                else:
                    assert module is not None
                    full = module
                targets.append(full)
                targets.extend(f"{full}.{n}" for n in names)
            for t in targets:
                if t in by_module and by_module[t] != p:
                    graph[p].add(by_module[t])
    return graph


def strongly_connected_components(graph: dict[Path, set[Path]]) -> list[list[Path]]:
    """Тарьян, итеративно (граф маленький, но рекурсию не рискуем)."""
    index_of: dict[Path, int] = {}
    low: dict[Path, int] = {}
    on_stack: set[Path] = set()
    stack: list[Path] = []
    comps: list[list[Path]] = []
    counter = 0
    for root in graph:
        if root in index_of:
            continue
        work = [(root, iter(sorted(graph[root])))]
        index_of[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in index_of:
                    index_of[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(sorted(graph[nxt]))))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index_of[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index_of[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                comps.append(comp)
    return comps


def get_pure_fn(ac: str):
    """Импорт нового имени внутри теста; нет имени -> AssertionError, называющий критерий."""
    from multiprocess_prototype.adapters import recipe_canonical as rc

    fn = getattr(rc, "denormalize_recipe_dict", None)
    assert fn is not None, f"{ac}: нет recipe_canonical.denormalize_recipe_dict"
    return fn


def ac5_violations(fn) -> list[str]:
    """Нарушения AC5 для реализации ``fn(data) -> dict`` (пустой список = всё держится)."""
    bad = []
    src = {"a": 1, "b": [2]}
    out = fn(src)
    if out != {"a": 1, "b": [2]}:
        bad.append(f"без meta: ожидали {{'a': 1, 'b': [2]}}, получили {out!r}")
    if out is src:
        bad.append("без meta: вернулся тот же объект, ждали новый dict")
    out2 = fn({"meta": 5, "a": 1})
    if out2 != {"a": 1}:
        bad.append(f"meta не dict: ожидали {{'a': 1}}, получили {out2!r}")
    return bad


# --------------------------------------------------------------------------------------
# Тесты: один на критерий
# --------------------------------------------------------------------------------------


def test_ac2_recipe_canonical_has_no_recipe_store_import_at_any_nesting():
    """AC2: ни один Import/ImportFrom в recipe_canonical.py (любая вложенность) не ведёт в recipe_store."""
    assert CANONICAL in non_test_files(), "AC2: recipe_canonical.py не найден среди не-тестовых файлов adapters"
    offenders = []
    for lineno, kind, module, level, names in collect_imports(CANONICAL):
        paths = [module or ""] + [f"{module or ''}.{n}" for n in names]
        if any("recipe_store" in p for p in paths) or "RecipeStoreFromManager" in names:
            offenders.append(f"строка {lineno}: {kind} {'.' * level}{module} {names}")
    assert not offenders, "AC2: recipe_canonical.py импортирует recipe_store: " + "; ".join(offenders)


def test_ac3_no_file_level_cycle_through_recipe_canonical():
    """AC3: ни одна SCC размера >1 в файловом графе adapters не содержит recipe_canonical.py."""
    graph = build_file_graph()
    assert CANONICAL in graph, "AC3: recipe_canonical.py не попал в граф"
    bad = [c for c in strongly_connected_components(graph) if len(c) > 1 and CANONICAL in c]
    desc = [sorted(str(p.relative_to(ADAPTERS)) for p in c) for c in bad]
    assert not bad, f"AC3: recipe_canonical.py в цикле импортов файлов: {desc}"


def test_ac4_denormalize_recipe_dict_flattens_meta_in_order():
    """AC4: функция есть, в __all__, meta разворачивается в верхний уровень, порядок ключей фиксирован."""
    from multiprocess_prototype.adapters import recipe_canonical as rc

    assert hasattr(rc, "denormalize_recipe_dict"), "AC4: нет recipe_canonical.denormalize_recipe_dict"
    assert "denormalize_recipe_dict" in rc.__all__, "AC4: denormalize_recipe_dict нет в recipe_canonical.__all__"
    out = rc.denormalize_recipe_dict(copy.deepcopy(AC4_INPUT))
    assert isinstance(out, dict), f"AC4: результат не dict: {type(out)!r}"
    assert "meta" not in out, "AC4: ключ meta остался в результате"
    assert list(out) == AC4_KEYS, f"AC4: порядок ключей {list(out)!r}"
    assert out == {
        "name": "r1",
        "version": "2",
        "description": "d",
        "created_at": "t",
        "zzz": 7,
        "displays": [{"id": "d1"}],
        "blueprint": {"processes": [], "wires": []},
        "active_services": ["s"],
    }, f"AC4: значения не совпали: {out!r}"


def test_ac5_without_meta_equals_input_and_non_dict_meta_dropped():
    """AC5: нет meta -> копия входа; meta не dict ({'meta': 5, 'a': 1}) -> {'a': 1}."""
    denormalize_recipe_dict = get_pure_fn("AC5")

    bad = ac5_violations(denormalize_recipe_dict)
    assert not bad, "AC5: " + "; ".join(bad)


def test_ac6_denormalize_recipe_dict_does_not_mutate_argument():
    """AC6: аргумент не мутируется (deepcopy до, сравнение после) — на AC4-литерале и на входе без meta."""
    denormalize_recipe_dict = get_pure_fn("AC6")

    for label, data in (("с meta", AC4_INPUT), ("без meta", {"a": 1, "b": [2]}), ("meta=5", {"meta": 5, "a": 1})):
        arg = copy.deepcopy(data)
        snapshot = copy.deepcopy(arg)
        denormalize_recipe_dict(arg)
        assert arg == snapshot, f"AC6: аргумент ({label}) изменён: {arg!r} != {snapshot!r}"


def test_ac7_store_static_denormalize_agrees_with_pure_function():
    """AC7: RecipeStoreFromManager._denormalize(x) == denormalize_recipe_dict(x), порядок ключей тот же."""
    denormalize_recipe_dict = get_pure_fn("AC7")
    from multiprocess_prototype.adapters.stores.recipe_store import RecipeStoreFromManager

    via_store = RecipeStoreFromManager._denormalize(copy.deepcopy(AC4_INPUT))
    via_func = denormalize_recipe_dict(copy.deepcopy(AC4_INPUT))
    assert via_store == via_func, f"AC7: значения разошлись: {via_store!r} vs {via_func!r}"
    keys = (list(via_store), list(via_func))
    assert keys[0] == keys[1] == AC4_KEYS, f"AC7: порядок ключей {keys[0]!r} vs {keys[1]!r}"
