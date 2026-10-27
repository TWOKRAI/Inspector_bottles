"""C-53/C-54: страж -- относительные импорты внутри ``modules/**`` не выходят за ``modules``.

Слепая приёмка (plans/word-layout/tasks/C-53.md). Обходятся ВСЕ ``.py`` под ``multiprocess_framework/modules``
(тесты и блоки ``TYPE_CHECKING`` включены, белого списка нет). Каждый ``ImportFrom`` с ``level > 0`` переводится
в абсолютное точечное имя собственным кодом; цель вне ``multiprocess_framework.modules`` -- нарушение.
Файл, который ``ast`` не разбирает, -- тоже нарушение.
"""

from __future__ import annotations

import ast
from pathlib import Path

_MODULES_DIR = Path(__file__).resolve().parents[1]
_MODULES_DOTTED = "multiprocess_framework.modules"


def _dotted_name_of_file(path: Path) -> tuple[list[str], bool]:
    """(части точечного имени модуля, это ли пакет ``__init__.py``) для файла под ``modules``."""
    rel = path.relative_to(_MODULES_DIR).with_suffix("")
    parts = _MODULES_DOTTED.split(".") + list(rel.parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return parts, is_package


def _resolve_target(module_parts: list[str], is_package: bool, level: int, module: str | None) -> list[str] | None:
    """Абсолютная цель ``from <level точек><module> import ...``; ``None`` -- вышли выше корня."""
    package = module_parts if is_package else module_parts[:-1]
    up = level - 1
    if up > len(package) - 1:
        return None
    base = package[: len(package) - up]
    return base + (module.split(".") if module else [])


def _is_inside_modules(target: list[str] | None) -> bool:
    prefix = _MODULES_DOTTED.split(".")
    return target is not None and target[: len(prefix)] == prefix


def _violations_in_source(source: bytes, module_parts: list[str], is_package: bool) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level > 0:
            target = _resolve_target(module_parts, is_package, node.level, node.module)
            if not _is_inside_modules(target):
                shown = ".".join(target) if target is not None else "<выше корня пакета>"
                found.append((node.lineno, f"{'.' * node.level}{node.module or ''} -> {shown}"))
    return sorted(found)


def _python_files() -> list[Path]:
    return sorted(p for p in _MODULES_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def test_relative_imports_stay_inside_modules():
    files = _python_files()
    problems: list[str] = []
    for path in files:
        shown = path.relative_to(_MODULES_DIR.parent.parent).as_posix()
        parts, is_package = _dotted_name_of_file(path)
        try:
            for lineno, text in _violations_in_source(path.read_bytes(), parts, is_package):
                problems.append(f"{shown}:{lineno}: {text}")
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            problems.append(f"{shown}:{getattr(exc, 'lineno', None) or 0}: файл не разобран ast: {exc!r}")
    assert len(files) > 1000, f"обход не охватил дерево: найдено {len(files)} файлов"
    assert not problems, "относительные импорты выходят за multiprocess_framework.modules:\n" + "\n".join(problems)


# --- Самопроверка резолвера на литералах (зелёные всегда) -------------------------------------------------------


def test_resolver_level_one_in_plain_module_stays_in_package():
    parts = ["multiprocess_framework", "modules", "a", "b"]
    assert _resolve_target(parts, False, 1, "c") == ["multiprocess_framework", "modules", "a", "c"]


def test_resolver_level_one_in_package_init_is_the_package_itself():
    parts = ["multiprocess_framework", "modules", "a"]
    assert _resolve_target(parts, True, 1, "c") == ["multiprocess_framework", "modules", "a", "c"]


def test_resolver_three_dots_from_init_leaves_modules():
    parts = ["multiprocess_framework", "modules", "process_module"]
    target = _resolve_target(parts, True, 3, "process_manager_module.topology.blueprint")
    assert target == ["multiprocess_framework", "process_manager_module", "topology", "blueprint"]
    assert not _is_inside_modules(target)


def test_resolver_four_dots_from_adapters_leaves_modules():
    parts = ["multiprocess_framework", "modules", "shared_resources_module", "adapters", "data_schema_adapter"]
    target = _resolve_target(parts, False, 4, "data_schema_module.storage.storage_manager")
    assert target == ["multiprocess_framework", "data_schema_module", "storage", "storage_manager"]
    assert not _is_inside_modules(target)


def test_resolver_three_dots_from_adapters_stays_inside_modules():
    parts = ["multiprocess_framework", "modules", "shared_resources_module", "adapters", "data_schema_adapter"]
    target = _resolve_target(parts, False, 3, "data_schema_module.storage.storage_manager")
    assert target == ["multiprocess_framework", "modules", "data_schema_module", "storage", "storage_manager"]
    assert _is_inside_modules(target)


def test_resolver_bare_dots_without_module_name():
    parts = ["multiprocess_framework", "modules", "a", "b"]
    assert _resolve_target(parts, False, 3, None) == ["multiprocess_framework"]
    assert not _is_inside_modules(["multiprocess_framework"])


def test_resolver_beyond_top_level_is_none():
    parts = ["multiprocess_framework", "modules", "a"]
    assert _resolve_target(parts, True, 5, "x") is None
    assert not _is_inside_modules(None)


def test_violation_scan_reports_line_inside_type_checking_block():
    source = (
        b"from __future__ import annotations\n"
        b"from typing import TYPE_CHECKING\n"
        b"if TYPE_CHECKING:\n"
        b"    from ...x import Y\n"
    )
    parts = ["multiprocess_framework", "modules", "a", "b"]
    found = _violations_in_source(source, parts, False)
    assert [line for line, _ in found] == [4]


def test_violation_scan_ignores_absolute_and_inside_relative():
    source = b"from multiprocess_framework.modules.a import X\nfrom . import y\nfrom ..c import z\n"
    parts = ["multiprocess_framework", "modules", "a", "b"]
    assert _violations_in_source(source, parts, False) == []
