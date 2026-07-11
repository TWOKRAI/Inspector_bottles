"""Contract-тесты detect.is_v3_recipe — распознавание формата рецепта."""

from __future__ import annotations

from multiprocess_framework.modules.recipe.detect import (
    has_top_level_blueprint,
    is_v3_recipe,
    nested_blueprint_data,
)


def test_blueprint_key_marks_v3() -> None:
    # given рецепт с top-level blueprint
    # then это v3
    assert is_v3_recipe({"name": "x", "blueprint": {"processes": []}}) is True


def test_version_ge_3_marks_v3() -> None:
    # given рецепт с version >= 3 без blueprint
    assert is_v3_recipe({"name": "x", "version": 3}) is True
    assert is_v3_recipe({"name": "x", "version": 5}) is True


def test_config_snapshot_is_not_v3() -> None:
    # given config-snapshot (envelope meta/data, version 2)
    assert is_v3_recipe({"meta": {"version": 2}, "data": {"cameras": {}}}) is False


def test_non_dict_is_not_v3() -> None:
    # given не-dict / None
    assert is_v3_recipe(None) is False
    assert is_v3_recipe("string") is False
    assert is_v3_recipe([1, 2]) is False
    assert is_v3_recipe(42) is False


def test_corrupted_v3_still_detected_by_blueprint() -> None:
    # given битый файл (blueprint + остаточные data/meta от прошлой порчи)
    # then распознаётся как v3 по blueprint — повторной порчи не будет
    corrupted = {"blueprint": {"processes": []}, "data": {}, "meta": {"migrated_from_v1": True}}
    assert is_v3_recipe(corrupted) is True


def test_has_top_level_blueprint_true_for_dict_with_key() -> None:
    # given dict с ключом blueprint на верхнем уровне
    assert has_top_level_blueprint({"blueprint": {}}) is True


def test_has_top_level_blueprint_false_without_key_or_non_dict() -> None:
    # given dict без blueprint / не-dict
    assert has_top_level_blueprint({"meta": {}, "data": {}}) is False
    assert has_top_level_blueprint(None) is False
    assert has_top_level_blueprint("string") is False
    assert has_top_level_blueprint([1, 2]) is False


def test_nested_blueprint_data_returns_data_when_nested() -> None:
    # given legacy v2: blueprint вложен в data
    raw = {"data": {"blueprint": {"processes": []}}}
    assert nested_blueprint_data(raw) is raw["data"]


def test_nested_blueprint_data_none_without_nested_blueprint() -> None:
    # given data без blueprint / data отсутствует / не-dict
    assert nested_blueprint_data({"data": {"cameras": {}}}) is None
    assert nested_blueprint_data({"meta": {}}) is None
    assert nested_blueprint_data(None) is None
    assert nested_blueprint_data({"data": "not-a-dict"}) is None
