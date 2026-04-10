"""Тесты bundle_contract (build_bundle / validate_bundle)."""

from ..core.bundle_contract import BUNDLE_KEYS, build_bundle, validate_bundle


def test_validate_bundle_requires_queues_and_config() -> None:
    assert not validate_bundle({})
    assert not validate_bundle({"queues": {}})
    assert validate_bundle({"queues": {}, "config": {}})


def test_build_bundle_shape() -> None:
    b = build_bundle(queues={"q": 1}, config={"a": 1}, custom={"x": 2})
    assert all(k in b for k in BUNDLE_KEYS)
    assert b["queues"] == {"q": 1}
    assert b["config"] == {"a": 1}
    assert b["custom"] == {"x": 2}
    assert b["routing_map"] == {}
