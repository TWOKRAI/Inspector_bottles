# -*- coding: utf-8 -*-
"""Гейт M-race-1: прод-код device_hub-плагина не лезет в приватки менеджера.

Acceptance Ф3.4: обращений `_manager._entries` / `_manager._drivers` из
прод-кода `Plugins/hub/device_hub/` = 0. Реестр/драйверы читаются ТОЛЬКО
через публичный потокобезопасный snapshot-API DeviceManager
(`snapshot_registry` / `get_driver` / `connected_ids` / `device_count` /
`connected_count`) — иначе tick/supervisor-потоки гоняются с upsert/remove
командного потока (`RuntimeError: dictionary changed size during iteration`).

AST-скан всех `*.py` зоны (кроме tests): ловит узел вида
``<expr>._manager._entries`` / ``<expr>._manager._drivers``. Зелёный тест =
запрет enforced навсегда: новый прямой доступ к приваткам валит CI.

По прецеденту `Plugins/tests/test_no_silent_swallows.py`, но проще — одна зона.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Корень зоны (этот файл: Plugins/hub/device_hub/tests/test_no_private_access.py)
_ZONE_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _ZONE_ROOT.parents[2]

#: Приватные атрибуты менеджера, читать которые извне запрещено.
_PRIVATE_ATTRS = frozenset({"_entries", "_drivers"})


def _iter_zone_files() -> list[Path]:
    """Все .py зоны device_hub-плагина, кроме тестов."""
    return sorted(
        p
        for p in _ZONE_ROOT.rglob("*.py")
        if "tests" not in p.relative_to(_ZONE_ROOT).parts
    )


def _is_manager_private(node: ast.Attribute) -> bool:
    """Узел вида ``<expr>._manager._entries`` / ``<expr>._manager._drivers``."""
    if node.attr not in _PRIVATE_ATTRS:
        return False
    inner = node.value
    return isinstance(inner, ast.Attribute) and inner.attr == "_manager"


def _scan_file(path: Path) -> list[str]:
    """Список нарушений файла (пусто = файл чист)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rel = path.relative_to(_REPO_ROOT)
    return [
        f"{rel}:{node.lineno} — прямой доступ `_manager.{node.attr}` "
        f"(используй публичный snapshot-API)"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and _is_manager_private(node)
    ]


def test_no_manager_private_access() -> None:
    """В прод-коде device_hub-плагина нет `_manager._entries/._drivers`."""
    violations: list[str] = []
    for path in _iter_zone_files():
        violations.extend(_scan_file(path))

    assert not violations, (
        "Найден прямой доступ к приваткам DeviceManager (M-race-1):\n"
        + "\n".join(violations)
        + "\nЧитай реестр/драйверы через snapshot_registry() / get_driver() / "
        "connected_ids() / device_count() / connected_count()."
    )
