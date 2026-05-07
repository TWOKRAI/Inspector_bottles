"""test_glob_walker.py — Тесты единого обхода дерева по glob-паттерну.

Покрывает поведение `iter_matches`:
- точные ключи
- '*' (один сегмент)
- '**' (0+ сегментов)
- комбинации
- non-dict узлы
- пустое дерево
"""
from __future__ import annotations

from multiprocess_framework.modules.state_store_module.core import iter_matches


def _as_dict(root: dict, pattern: str) -> dict:
    return dict(iter_matches(root, pattern))


def test_exact_key_match() -> None:
    root = {"cameras": {"0": {"fps": 30}}}
    assert _as_dict(root, "cameras.0.fps") == {"cameras.0.fps": 30}


def test_single_star_one_segment() -> None:
    root = {
        "cameras": {
            "0": {"fps": 30},
            "1": {"fps": 24},
        }
    }
    matched = _as_dict(root, "cameras.*.fps")
    assert matched == {"cameras.0.fps": 30, "cameras.1.fps": 24}


def test_double_star_zero_segments() -> None:
    """'**' может поглотить 0 сегментов и матчить точно cameras.fps."""
    root = {"cameras": {"fps": 30, "0": {"fps": 24}}}
    matched = _as_dict(root, "cameras.**.fps")
    # cameras.fps (через 0 сегментов) и cameras.0.fps (через 1 сегмент)
    assert matched == {"cameras.fps": 30, "cameras.0.fps": 24}


def test_double_star_returns_subtrees_when_last() -> None:
    """'**' в конце паттерна выдаёт ВСЕ узлы под cameras."""
    root = {"cameras": {"0": {"fps": 30}, "1": {"fps": 24}}}
    matched = _as_dict(root, "cameras.**")
    # 0 сегментов: cameras (всё поддерево)
    assert "cameras" in matched
    assert matched["cameras"] == {"0": {"fps": 30}, "1": {"fps": 24}}
    # +1 сегмент: cameras.0 / cameras.1 (поддеревья)
    assert matched["cameras.0"] == {"fps": 30}
    # +2 сегмента: cameras.0.fps / cameras.1.fps
    assert matched["cameras.0.fps"] == 30
    assert matched["cameras.1.fps"] == 24


def test_concrete_after_star() -> None:
    root = {"a": {"b": {"x": 1, "y": 2}, "c": {"x": 3}}}
    matched = _as_dict(root, "a.*.x")
    assert matched == {"a.b.x": 1, "a.c.x": 3}


def test_no_match_returns_empty() -> None:
    root = {"cameras": {"0": {"fps": 30}}}
    assert _as_dict(root, "renderer.*") == {}


def test_non_dict_branch_terminates() -> None:
    root = {"a": 5}
    assert _as_dict(root, "a.b") == {}


def test_non_dict_root_returns_empty() -> None:
    # iter_matches защищён от не-dict root
    assert dict(iter_matches([1, 2, 3], "a.b")) == {}  # type: ignore[arg-type]
    assert dict(iter_matches(None, "a")) == {}  # type: ignore[arg-type]


def test_empty_tree() -> None:
    assert _as_dict({}, "a.*") == {}
    assert _as_dict({}, "**") == {"": {}}  # ** с 0 сегментов — корень


def test_yields_node_reference_not_copy() -> None:
    """iter_matches не делает deep_copy — клиент сам решает."""
    inner = {"x": 1}
    root = {"a": inner}
    [(_path, value)] = list(iter_matches(root, "a"))
    assert value is inner
