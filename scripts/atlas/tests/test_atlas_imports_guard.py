"""Сторож R1 (Task 4.1): код `scripts/atlas` вместе с тестами не импортирует слои приложения.

Purpose: atlas читает репозиторий как текст (AST, git), а не как пакеты: импорт `multiprocess_framework`,
    `Services` или `Plugins` тянет PySide6/железо и связывает инструмент с кодом, который он описывает.
    Сторож разбирает AST каждого `scripts/atlas/**/*.py` и ищет `import X`, `from X import ...`,
    `importlib.import_module("X...")`, `import_module("X...")`, `__import__("X...")` с корнем из `FORBIDDEN`.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Ошибка сторожа — список `путь:строка` (ввода не требует). Детектор проверен на образцах каждой формы:
без этого зелёный сторож ничего не доказывает.
"""

from __future__ import annotations

import ast
from pathlib import Path

__all__: list[str] = []

ATLAS = Path(__file__).resolve().parents[1]
FORBIDDEN = frozenset({"multiprocess_framework", "Services", "Plugins"})
_DYNAMIC = frozenset({"import_module", "__import__"})


def _root(name: str | None) -> str:
    return (name or "").split(".", 1)[0]


def forbidden_imports(source: str) -> list[int]:
    """Строки запрещённых импортов в исходнике (статических и через `import_module`/`__import__` с литералом)."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(_root(a.name) in FORBIDDEN for a in node.names):
                lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and _root(node.module) in FORBIDDEN:
                lines.append(node.lineno)
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            arg = node.args[0]
            if name in _DYNAMIC and isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if _root(arg.value) in FORBIDDEN:
                    lines.append(node.lineno)
    return sorted(lines)


def test_atlas_code_imports_no_application_layer():
    files = sorted(ATLAS.rglob("*.py"))
    assert len(files) > 20, f"сторож не нашёл файлов atlas в {ATLAS}"
    found = [
        f"{path.relative_to(ATLAS.parents[1]).as_posix()}:{line}"
        for path in files
        for line in forbidden_imports(path.read_text(encoding="utf-8"))
    ]
    assert found == [], "scripts/atlas импортирует слой приложения (R1): " + ", ".join(found)


def test_detector_sees_every_form():
    """Каждая форма из ACCEPTANCE ловится; соседние безвредные формы — нет."""
    bad = {
        "import multiprocess_framework\n": [1],
        "import os, Services.x\n": [1],
        "from Plugins import x\n": [1],
        "from multiprocess_framework.modules import y\n": [1],
        "import importlib\nimportlib.import_module('Services.x')\n": [2],
        "from importlib import import_module\nimport_module('Plugins.a')\n": [2],
        "def f():\n    __import__('Plugins')\n": [2],
        "if True:\n    import Services\n": [2],
    }
    for source, lines in bad.items():
        assert forbidden_imports(source) == lines, source
    good = [
        "import scripts.atlas.scan\n",
        "from . import Plugins\n",  # относительный импорт — свой пакет, не слой приложения
        "x = 'multiprocess_framework'\n",  # строка, не импорт
        "importlib.import_module(name)\n",  # не литерал: не видно, не ловится
        "import ServicesX\n",
    ]
    for source in good:
        assert forbidden_imports(source) == [], source
