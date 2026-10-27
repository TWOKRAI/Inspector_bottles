"""C-53: ленивые публичные имена process_module разрешаются и указывают на канонические классы.

Слепая приёмка (plans/word-layout/tasks/C-53.md, «Цель» и «Приёмка»). Контракт: каждое имя из
``process_module.__all__`` берётся обычным обращением к атрибуту; ``SystemBlueprint``, ``ProcessConfig``,
``Wire`` -- те же объекты (``is``), что в ``process_manager_module.topology.blueprint``.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

import multiprocess_framework.modules.process_module as pm

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BLUEPRINT = "multiprocess_framework.modules.process_manager_module.topology.blueprint"
_LAZY_BLUEPRINT_NAMES = ("SystemBlueprint", "ProcessConfig", "Wire")


def _fresh_interpreter(code: str) -> subprocess.CompletedProcess:
    """Новый интерпретатор: холодный порядок импорта, без кэша ``__getattr__`` в globals."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("name", list(pm.__all__))
def test_every_public_name_resolves(name):
    resolved = getattr(pm, name)
    assert resolved is not None


@pytest.mark.parametrize("name", _LAZY_BLUEPRINT_NAMES)
def test_blueprint_names_are_canonical_classes(name):
    import importlib

    canonical = getattr(importlib.import_module(_BLUEPRINT), name)
    assert getattr(pm, name) is canonical


def test_blueprint_names_are_canonical_in_fresh_interpreter():
    code = (
        "import multiprocess_framework.modules.process_module as pm\n"
        f"import {_BLUEPRINT} as bp\n"
        "for n in ('SystemBlueprint', 'ProcessConfig', 'Wire'):\n"
        "    print(n, getattr(pm, n) is getattr(bp, n))\n"
    )
    result = _fresh_interpreter(code)
    assert result.returncode == 0, result.stderr[-1500:]
    assert result.stdout.split("\n")[:3] == [
        "SystemBlueprint True",
        "ProcessConfig True",
        "Wire True",
    ]


def test_star_import_in_fresh_interpreter():
    result = _fresh_interpreter("from multiprocess_framework.modules.process_module import *")
    assert result.returncode == 0, result.stderr[-1500:]


def test_all_has_no_duplicates():
    assert len(pm.__all__) == len(set(pm.__all__))


def _lazy_names(source: str) -> set[str]:
    """Строковые литералы, с которыми ``name`` сравнивается внутри модульного ``__getattr__``."""
    tree = ast.parse(source)
    found: set[str] = set()
    for func in tree.body:
        if not (isinstance(func, ast.FunctionDef) and func.name == "__getattr__"):
            continue
        for node in ast.walk(func):
            if not (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "name"):
                continue
            for comparator in node.comparators:
                items = comparator.elts if isinstance(comparator, (ast.Tuple, ast.List, ast.Set)) else [comparator]
                found.update(i.value for i in items if isinstance(i, ast.Constant) and isinstance(i.value, str))
    return found


def test_lazy_names_are_listed_in_all():
    source = Path(pm.__file__).read_text(encoding="utf-8")
    lazy = _lazy_names(source)
    assert lazy, "в __getattr__ не найдено ни одного ленивого имени: разбор ast ничего не видит"
    missing = sorted(lazy - set(pm.__all__))
    assert not missing, f"ленивые имена вне __all__: {missing}"


def test_lazy_names_scan_detects_name_missing_from_all():
    source = "\n".join(
        [
            "def __getattr__(name):",
            "    if name == 'Alpha':",
            "        return 1",
            "    if name in ('Beta', 'Gamma'):",
            "        return 2",
            "    raise AttributeError(name)",
        ]
    )
    fake_all = ["Alpha", "Gamma"]
    assert _lazy_names(source) == {"Alpha", "Beta", "Gamma"}
    assert sorted(_lazy_names(source) - set(fake_all)) == ["Beta"]


def test_unknown_name_raises_attribute_error():
    with pytest.raises(AttributeError):
        getattr(pm, "NoSuchName_c53")
