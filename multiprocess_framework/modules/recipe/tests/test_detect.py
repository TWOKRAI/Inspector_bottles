"""Contract-тесты detect.is_v3_recipe — распознавание формата рецепта."""

from __future__ import annotations

from multiprocess_framework.modules.recipe.detect import is_v3_recipe


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
