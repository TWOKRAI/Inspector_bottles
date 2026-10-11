"""G6: запреты жизненного цикла (правила R1..R8), AST, режим fail.

Храповик по ``(правило, путь)``: найдено больше ``count`` записи — «новое нарушение»,
меньше — «запись устарела, уменьши count», путь исчез — «запись гнилая»;
``reason`` пуста или короче 10 знаков — finding.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

from scripts.lifecycle_guards.tables import ALLOWLIST, AllowEntry, Finding, production_files

LIFETIME_PATH = "multiprocess_framework/modules/base_manager/core/lifetime.py"
BASE_MANAGER_DIR = "multiprocess_framework/modules/base_manager/"
_LIFETIME_TAIL = "base_manager.core.lifetime"
MIN_REASON_LEN = 10

# R8: литеральный список task-0.2; относительный ``..interfaces`` разрешён отдельно.
LIFETIME_ALLOWED_IMPORTS = frozenset(
    {
        "__future__",
        "collections",
        "collections.abc",
        "dataclasses",
        "itertools",
        "logging",
        "math",
        "threading",
        "time",
        "typing",
        "weakref",
    }
)

_THREAD_CTORS = frozenset({"Thread", "Timer"})
_NUMBER_TYPES = (int, float)


def _call_name(call: ast.Call) -> tuple[str | None, str | None]:
    """(имя вызываемого, имя объекта слева) — ``threading.Thread`` -> (``Thread``, ``threading``)."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id, None
    if isinstance(func, ast.Attribute):
        owner = func.value.id if isinstance(func.value, ast.Name) else None
        return func.attr, owner
    return None, None


def _is_number(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, _NUMBER_TYPES) and not isinstance(node.value, bool)


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _resolve_from(rel: str, node: ast.ImportFrom) -> str:
    """Полное точечное имя модуля ``from ... import`` с разрешением относительного уровня."""
    module = node.module or ""
    if node.level == 0:
        return module
    package = rel.split("/")[:-1]
    base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
    return ".".join([*base, module] if module else base)


def _is_lifetime(dotted: str) -> bool:
    return dotted == _LIFETIME_TAIL or dotted.endswith("." + _LIFETIME_TAIL)


def _scan_calls(rel: str, node: ast.Call, in_layers: bool, hits: list[tuple[str, int, str]]) -> None:
    name, owner = _call_name(node)
    is_attr = isinstance(node.func, ast.Attribute)
    line = node.lineno
    if in_layers and (
        (name in _THREAD_CTORS and (isinstance(node.func, ast.Name) or owner == "threading"))
        or name == "ThreadPoolExecutor"
    ):
        hits.append(("R1", line, f"{name}(...) в слое Plugins/Services — жизнью потока владеет область, не код"))
    if name == "QTimer":
        has_parent_kw = any(k.arg == "parent" for k in node.keywords)
        if (not node.args and not has_parent_kw) or (node.args and _is_none(node.args[0])):
            hits.append(("R2", line, "QTimer без родителя"))
    if name == "join" and is_attr:
        if any(_is_number(a) for a in node.args) or any(
            k.arg == "timeout" and _is_number(k.value) for k in node.keywords
        ):
            hits.append(("R3", line, "join с числовым литералом срока — срок берётся из stop_budget"))
    if (
        is_attr
        and name in ("terminate", "kill")
        and not node.args
        and not node.keywords
        and rel.rsplit("/", 1)[-1] != "child_process_stop.py"
    ):
        hits.append(("R4", line, f".{name}() вне child_process_stop.py"))
    if is_attr and name == "deleteLater" and rel.rsplit("/", 1)[-1] != "qt_lifetime.py":
        hits.append(("R6", line, ".deleteLater() вне qt_lifetime.py"))


def scan_file(rel: str, text: str) -> list[tuple[str, int, str]]:
    """Нарушения файла: (правило, строка, сообщение), без учёта таблицы."""
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [("R0", exc.lineno or 1, f"файл не разбирается: {exc.msg}")]
    hits: list[tuple[str, int, str]] = []
    in_layers = rel.startswith(("Plugins/", "Services/"))
    in_base_manager = rel.startswith(BASE_MANAGER_DIR)
    is_lifetime = rel == LIFETIME_PATH
    is_stop_budget = rel.rsplit("/", 1)[-1] == "stop_budget.py"

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            _scan_calls(rel, node, in_layers, hits)
        elif isinstance(node, ast.Constant) and node.value == "shutdown_timeout" and not is_stop_budget:
            hits.append(("R5", node.lineno, 'строка "shutdown_timeout" вне stop_budget.py'))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if not in_base_manager and _is_lifetime(alias.name):
                    hits.append(("R7", node.lineno, "импорт base_manager.core.lifetime снаружи base_manager/"))
                if is_lifetime and alias.name not in LIFETIME_ALLOWED_IMPORTS:
                    hits.append(("R8", node.lineno, f"lifetime.py импортирует {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_from(rel, node)
            if not in_base_manager and (
                _is_lifetime(module) or any(_is_lifetime(f"{module}.{a.name}") for a in node.names)
            ):
                hits.append(("R7", node.lineno, "импорт base_manager.core.lifetime снаружи base_manager/"))
            if is_lifetime:
                allowed = (node.level == 0 and module in LIFETIME_ALLOWED_IMPORTS) or (
                    node.level == 2 and node.module == "interfaces"
                )
                if not allowed:
                    shown = "." * node.level + (node.module or "")
                    hits.append(("R8", node.lineno, f"lifetime.py импортирует из {shown}"))
    return sorted(hits, key=lambda h: (h[1], h[0]))


def check_g6(root: Path, allowlist: dict[tuple[str, str], AllowEntry] = ALLOWLIST) -> list[Finding]:
    findings: list[Finding] = []
    found: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    for rel, text in production_files(root):
        for rule, line, message in scan_file(rel, text):
            found[(rule, rel)].append((line, message))

    for (rule, rel), hits in sorted(found.items()):
        allowed = allowlist[(rule, rel)].count if (rule, rel) in allowlist else 0
        for line, message in hits[allowed:]:
            findings.append(Finding("G6", rule, rel, line, f"новое нарушение: {message}"))

    for (rule, rel), entry in sorted(allowlist.items()):
        n = len(found.get((rule, rel), []))
        if not (root / rel).is_file():
            findings.append(Finding("G6", rule, rel, 0, "запись гнилая: пути нет в дереве"))
        elif n < entry.count:
            findings.append(
                Finding("G6", rule, rel, 0, f"запись устарела, уменьши count: в таблице {entry.count}, найдено {n}")
            )
        if len(entry.reason.strip()) < MIN_REASON_LEN:
            findings.append(Finding("G6", rule, rel, 0, f"reason пуста или короче {MIN_REASON_LEN} знаков"))

    return sorted(findings, key=lambda f: (f.path, f.line, f.rule))
