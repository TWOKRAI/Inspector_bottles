"""Тесты автора контракта владения (Task 0.1, ADR-BM-008).

Опасности, которые видит автор `interfaces.py`, а не приёмка:

- `to_dict` при пустых и непустых `errors` даёт одну форму (список словарей);
- `from_dict(to_dict(r)) == r` на отчёте со всеми полями, в том числе после
  настоящего JSON-хопа (кортежи → списки → кортежи);
- `from_dict` со строкой на месте `errors` не режет её на символы, а бросает
  `TypeError` из `__post_init__` (ветка `isinstance(errors, str)` в `from_dict`);
- `ok` не зависит от `emits_after_close`;
- `Stoppable` проверяется через `getattr_static`: прокси с `__getattr__` и
  `Mock()` — не `Stoppable` (причина отказа от `hasattr` прототипа);
- `interfaces.py` импортирует только stdlib из литерального списка.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from multiprocess_framework.modules.base_manager.interfaces import CloseReport, Stoppable

_INTERFACES_PY = Path(__file__).resolve().parent.parent / "interfaces.py"

# Литеральный список из task-0.1.md, раздел «Ограничения файла».
_ALLOWED_IMPORTS = {"__future__", "abc", "collections.abc", "dataclasses", "threading", "typing"}


def _full_report() -> CloseReport:
    return CloseReport(
        path="proc/camera_0",
        elapsed_s=1.25,
        survivors=("proc/camera_0/work/grabber", "proc/camera_0/work (self)"),
        killed=("proc/camera_0/children/worker_1",),
        errors=(("proc/camera_0/planes/sink", "OSError: pipe closed"),),
        emits_after_close=3,
        complete=False,
    )


# ---------------------------------------------------------------------------
# to_dict: форма errors
# ---------------------------------------------------------------------------


def test_to_dict_empty_errors_is_empty_list():
    r = CloseReport(path="p", elapsed_s=0.0, survivors=(), killed=(), errors=())
    d = r.to_dict()
    assert d["errors"] == []
    assert type(d["errors"]) is list
    assert d["survivors"] == [] and d["killed"] == []
    assert d["ok"] is True


def test_to_dict_non_empty_errors_is_list_of_path_error_dicts():
    d = _full_report().to_dict()
    assert d["errors"] == [{"path": "proc/camera_0/planes/sink", "error": "OSError: pipe closed"}]
    assert d["survivors"] == ["proc/camera_0/work/grabber", "proc/camera_0/work (self)"]
    assert d["killed"] == ["proc/camera_0/children/worker_1"]
    assert d["emits_after_close"] == 3
    assert d["complete"] is False
    assert d["ok"] is False


# ---------------------------------------------------------------------------
# from_dict: обратимость
# ---------------------------------------------------------------------------


def test_from_dict_roundtrip_all_fields():
    r = _full_report()
    assert CloseReport.from_dict(r.to_dict()) == r


def test_from_dict_roundtrip_through_real_json_hop():
    r = _full_report()
    wire = json.loads(json.dumps(r.to_dict()))
    back = CloseReport.from_dict(wire)
    assert back == r
    assert hash(back) == hash(r)
    assert type(back.errors[0]) is tuple


def test_from_dict_does_not_mutate_input():
    d = _full_report().to_dict()
    snapshot = json.dumps(d, sort_keys=True)
    CloseReport.from_dict(d)
    assert json.dumps(d, sort_keys=True) == snapshot


def test_from_dict_string_in_place_of_errors_raises_type_error_not_char_split():
    d = _full_report().to_dict()
    d["errors"] = "proc/x"
    with pytest.raises(TypeError, match="errors"):
        CloseReport.from_dict(d)


def test_from_dict_string_in_place_of_survivors_raises_type_error():
    d = _full_report().to_dict()
    d["survivors"] = "proc/x"
    with pytest.raises(TypeError, match="survivors"):
        CloseReport.from_dict(d)


# ---------------------------------------------------------------------------
# ok и emits_after_close
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("emits", [0, 1, 5, 10_000])
def test_ok_does_not_depend_on_emits_after_close(emits):
    r = CloseReport(path="p", elapsed_s=0.1, survivors=(), killed=(), errors=(), emits_after_close=emits)
    assert r.ok is True


@pytest.mark.parametrize("emits", [0, 5])
def test_ok_false_with_survivor_regardless_of_emits(emits):
    r = CloseReport(path="p", elapsed_s=0.1, survivors=("p/a",), killed=(), errors=(), emits_after_close=emits)
    assert r.ok is False


# ---------------------------------------------------------------------------
# Stoppable: getattr_static, не hasattr
# ---------------------------------------------------------------------------


class _Proxy:
    """Прокси, отдающий любой атрибут через __getattr__ (hasattr → True)."""

    def __getattr__(self, name):
        return lambda *a, **k: None


def test_getattr_proxy_is_not_stoppable():
    proxy = _Proxy()
    assert hasattr(proxy, "request_stop") and hasattr(proxy, "join_until")
    assert isinstance(proxy, Stoppable) is False


def test_plain_mock_is_not_stoppable():
    assert isinstance(Mock(), Stoppable) is False


def test_real_class_with_both_methods_is_stoppable():
    """Контроль к двум тестам выше: настоящий класс с обоими методами проходит."""

    class _Real:
        def request_stop(self) -> None: ...

        def join_until(self, deadline: float) -> bool:
            return True

    assert isinstance(_Real(), Stoppable) is True


# ---------------------------------------------------------------------------
# interfaces.py — только stdlib из литерального списка
# ---------------------------------------------------------------------------


def _imported_modules(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # level > 0 — относительный импорт: всегда вне списка.
            names.add("." * node.level + (node.module or ""))
    return names


def test_interfaces_imports_only_allowed_stdlib():
    tree = ast.parse(_INTERFACES_PY.read_text(encoding="utf-8"))
    imported = _imported_modules(tree)
    assert imported, "AST не нашёл ни одного импорта — сторож пуст"
    assert imported - _ALLOWED_IMPORTS == set()


def test_import_guard_catches_a_forbidden_import():
    """Сторож выше не вакуумен: на тексте с запрещённым импортом он видит его."""
    tree = ast.parse("from typing import Protocol\nimport logging\nfrom . import base_manager\n")
    assert _imported_modules(tree) - _ALLOWED_IMPORTS == {"logging", "."}
