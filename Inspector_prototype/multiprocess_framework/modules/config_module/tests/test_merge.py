"""
Unit-тесты для config_module.tools.merge — deep_merge и multi_merge.
"""
import pytest

from config_module.tools.merge import deep_merge, multi_merge


# ---------------------------------------------------------------------------
# deep_merge — базовые сценарии
# ---------------------------------------------------------------------------

def test_empty_overlay_returns_copy():
    base = {"a": 1}
    result = deep_merge(base, None)
    assert result == {"a": 1}
    assert result is not base  # deepcopy


def test_empty_base():
    result = deep_merge({}, {"a": 1})
    assert result == {"a": 1}


def test_flat_merge():
    base = {"a": 1, "b": 2}
    overlay = {"b": 3, "c": 4}
    result = deep_merge(base, overlay)
    assert result == {"a": 1, "b": 3, "c": 4}


def test_nested_merge():
    base = {"db": {"host": "localhost", "port": 5432}}
    overlay = {"db": {"port": 3306}, "debug": True}
    result = deep_merge(base, overlay)
    assert result == {"db": {"host": "localhost", "port": 3306}, "debug": True}


def test_deep_nested_merge():
    base = {"a": {"b": {"c": 1, "d": 2}}}
    overlay = {"a": {"b": {"d": 3, "e": 4}}}
    result = deep_merge(base, overlay)
    assert result == {"a": {"b": {"c": 1, "d": 3, "e": 4}}}


# ---------------------------------------------------------------------------
# deep_merge — изоляция (deepcopy)
# ---------------------------------------------------------------------------

def test_copy_base_true_no_mutation():
    base = {"a": {"nested": [1, 2]}}
    overlay = {"a": {"nested": [3]}}
    result = deep_merge(base, overlay, copy_base=True)
    assert base == {"a": {"nested": [1, 2]}}  # base не мутирован
    assert result == {"a": {"nested": [3]}}


def test_copy_base_false_mutates():
    base = {"a": 1}
    overlay = {"b": 2}
    result = deep_merge(base, overlay, copy_base=False)
    assert base == {"a": 1, "b": 2}  # base мутирован
    assert result is base


def test_overlay_values_are_deepcopied():
    """Overlay значения копируются — изменение overlay не влияет на result."""
    overlay_list = [1, 2, 3]
    overlay = {"items": overlay_list}
    result = deep_merge({}, overlay)
    overlay_list.append(4)
    assert result["items"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# deep_merge — list_strategy
# ---------------------------------------------------------------------------

def test_list_replace_default():
    base = {"tags": ["a", "b"]}
    overlay = {"tags": ["c"]}
    result = deep_merge(base, overlay)
    assert result == {"tags": ["c"]}


def test_list_append():
    base = {"tags": ["a", "b"]}
    overlay = {"tags": ["c"]}
    result = deep_merge(base, overlay, list_strategy="append")
    assert result == {"tags": ["a", "b", "c"]}


def test_list_append_nested():
    base = {"cfg": {"items": [1]}}
    overlay = {"cfg": {"items": [2, 3]}}
    result = deep_merge(base, overlay, list_strategy="append")
    assert result == {"cfg": {"items": [1, 2, 3]}}


# ---------------------------------------------------------------------------
# deep_merge — edge cases
# ---------------------------------------------------------------------------

def test_overlay_dict_over_scalar():
    """Overlay dict заменяет scalar в base."""
    base = {"a": "string"}
    overlay = {"a": {"nested": True}}
    result = deep_merge(base, overlay)
    assert result == {"a": {"nested": True}}


def test_overlay_scalar_over_dict():
    """Overlay scalar заменяет dict в base."""
    base = {"a": {"nested": True}}
    overlay = {"a": "string"}
    result = deep_merge(base, overlay)
    assert result == {"a": "string"}


def test_empty_dict_overlay():
    result = deep_merge({"a": 1}, {})
    assert result == {"a": 1}


def test_none_values_preserved():
    result = deep_merge({"a": 1}, {"a": None})
    assert result == {"a": None}


# ---------------------------------------------------------------------------
# multi_merge
# ---------------------------------------------------------------------------

def test_multi_merge_basic():
    defaults = {"a": 1, "b": 2}
    env = {"b": 3}
    user = {"c": 4}
    result = multi_merge(defaults, env, user)
    assert result == {"a": 1, "b": 3, "c": 4}


def test_multi_merge_skips_none():
    result = multi_merge({"a": 1}, None, {"b": 2}, None)
    assert result == {"a": 1, "b": 2}


def test_multi_merge_empty():
    result = multi_merge()
    assert result == {}


def test_multi_merge_single():
    result = multi_merge({"a": 1})
    assert result == {"a": 1}


def test_multi_merge_priority():
    """Последний слой побеждает."""
    result = multi_merge(
        {"port": 5432},
        {"port": 3306},
        {"port": 8080},
    )
    assert result == {"port": 8080}


def test_multi_merge_with_list_strategy():
    result = multi_merge(
        {"tags": ["a"]},
        {"tags": ["b"]},
        {"tags": ["c"]},
        list_strategy="append",
    )
    assert result == {"tags": ["a", "b", "c"]}
