"""G2: сигнатуры издателей (подписка/регистрация обратного вызова).

Три проверки по таблице ``PUBLISHERS``:
(а) строка ``migrated``: параметр ``owner`` ключевой (после ``*``), без умолчания,
    текст аннотации ровно ``IScope`` (сравнивается текст, не имя в пространстве имён);
(б) любая строка: метод ``путь::Класс.метод`` существует в файле, иначе «гнилая строка таблицы»;
(в) перепись: в производственном файле определение с именем из ``CENSUS_NAMES``,
    которого нет в таблице, — ``unlisted publisher``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from scripts.lifecycle_guards.tables import PUBLISHERS, Finding, Publisher, production_files

CENSUS_NAMES = frozenset(
    {
        "subscribe",
        "add_callback",
        "add_change_callback",
        "add_post_execute_callback",
        "add_push_listener",
        "add_tap",
        "register_message_handler",
        "register_handler",
    }
)

type FuncDef = ast.FunctionDef | ast.AsyncFunctionDef


def iter_defs(tree: ast.AST) -> Iterator[tuple[str, FuncDef]]:
    """Все определения функций с квалифицированным именем (как ``__qualname__``)."""

    def walk(node: ast.AST, prefix: str) -> Iterator[tuple[str, FuncDef]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                yield from walk(child, f"{prefix}{child.name}.")
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                yield f"{prefix}{child.name}", child
                yield from walk(child, f"{prefix}{child.name}.<locals>.")
            else:
                yield from walk(child, prefix)

    yield from walk(tree, "")


def _owner_problem(func: FuncDef) -> str | None:
    """Почему сигнатура не годится для ``migrated``; None — годится."""
    args = func.args
    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        if arg.arg != "owner":
            continue
        if default is not None:
            return "у owner есть значение по умолчанию"
        text = ast.unparse(arg.annotation) if arg.annotation is not None else "<нет>"
        if text != "IScope":
            return f"аннотация owner — {text}, нужно ровно IScope"
        return None
    return "owner не ключевой параметр (после *)"


def _parse(text: str) -> ast.Module | None:
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


def check_g2(root: Path, publishers: list[Publisher] = PUBLISHERS) -> list[Finding]:
    findings: list[Finding] = []
    listed = {(p.path, p.qualname) for p in publishers}

    for pub in publishers:
        file = root / pub.path
        tree = _parse(file.read_text(encoding="utf-8", errors="replace")) if file.is_file() else None
        matches = [f for q, f in iter_defs(tree) if q == pub.qualname] if tree is not None else []
        if not matches:
            findings.append(
                Finding("G2", "table-row", pub.path, 1, f"гнилая строка таблицы: {pub.qualname} не найден в файле")
            )
            continue
        if pub.status != "migrated":
            continue
        for func in matches:
            problem = _owner_problem(func)
            if problem is not None:
                findings.append(
                    Finding("G2", "signature", pub.path, func.lineno, f"{pub.qualname} (migrated): {problem}")
                )

    for rel, text in production_files(root):
        if not any(name in text for name in CENSUS_NAMES):
            continue
        tree = _parse(text)
        if tree is None:
            continue
        for qualname, func in iter_defs(tree):
            if func.name in CENSUS_NAMES and (rel, qualname) not in listed:
                findings.append(
                    Finding(
                        "G2", "census", rel, func.lineno, f"unlisted publisher: {qualname} нет в таблице PUBLISHERS"
                    )
                )

    return sorted(findings, key=lambda f: (f.path, f.line, f.rule))
