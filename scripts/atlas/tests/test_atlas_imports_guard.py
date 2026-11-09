"""Сторож R1 (Task 4.1): код `scripts/atlas` вместе с тестами не импортирует слои приложения.

Purpose: atlas читает репозиторий как текст (AST, git), а не как пакеты: импорт `multiprocess_framework`,
    `Services` или `Plugins` тянет PySide6/железо и связывает инструмент с кодом, который он описывает.
    Сторож разбирает AST каждого `scripts/atlas/**/*.py` и ищет `import X`, `from X import ...`,
    `importlib.import_module("X...")`, `import_module("X...")`, `__import__("X...")` (литерал первым аргументом или
    `name=`; алиас из `from importlib import import_module as im` тоже) с корнем из `FORBIDDEN`.
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
    tree = ast.parse(source)
    aliases = {  # `from importlib import import_module as im` -> {"im": "import_module"}
        a.asname: a.name
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
        for a in n.names
        if a.asname and a.name in _DYNAMIC
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(_root(a.name) in FORBIDDEN for a in node.names):
                lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and _root(node.module) in FORBIDDEN:
                lines.append(node.lineno)
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            name = aliases.get(name, name)
            arg = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "name"), None)
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


def test_guard_catches_aliased_import_module():
    """`from importlib import import_module as im; im("Plugins.x")` — алиас из ImportFrom тоже динамический импорт."""
    assert forbidden_imports("from importlib import import_module as im\nim('Plugins.x')\n") == [2]
    assert forbidden_imports("from importlib import import_module as im\n\n\ndef f():\n    im('Services')\n") == [5]
    assert forbidden_imports("from builtins import __import__ as imp\nimp('multiprocess_framework.x')\n") == [2]
    # соседние безвредные формы: алиас чужой функции, алиас без запрещённого корня, имя без алиаса
    assert forbidden_imports("from os import path as im\nim('Plugins.x')\n") == []
    assert forbidden_imports("from importlib import import_module as im\nim('os.path')\n") == []
    assert forbidden_imports("im('Plugins.x')\n") == []


def test_guard_catches_import_module_name_keyword():
    """`import_module(name="Plugins.x")` / `__import__(name=...)` — литерал в keyword, не в args[0]."""
    assert forbidden_imports("import importlib\nimportlib.import_module(name='Plugins.x')\n") == [2]
    assert forbidden_imports("from importlib import import_module\nimport_module(name='Services')\n") == [2]
    assert forbidden_imports("__import__(name='multiprocess_framework')\n") == [1]
    assert forbidden_imports("from importlib import import_module as im\nim(name='Plugins.x')\n") == [2]
    # другой keyword или чужая функция с `name=` — не динамический импорт
    assert forbidden_imports("import importlib\nimportlib.import_module(name='os')\n") == []
    assert forbidden_imports("make(name='Plugins.x')\n") == []
    assert forbidden_imports("import importlib\nimportlib.import_module(package='Plugins.x')\n") == []
