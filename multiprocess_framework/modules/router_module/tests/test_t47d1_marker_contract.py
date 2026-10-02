# -*- coding: utf-8 -*-
"""Task 4.7d-1 — слепые приёмочные тесты контракта маркера ``not_inspected``.

Источник: plans/transport-single-policy/task-4.7.md, блок «Контракт маркера» и acceptance 4.7d-1.
Модуль ``router_module/middleware/not_inspected_marker.py`` на момент написания не существует;
импорт — внутри каждого теста, чтобы каждый падал сам по себе (не одна ошибка сбора на файл).
Ожидаемые значения — литералы, не пересчитываются из кода под тестом.
"""

from __future__ import annotations

import numpy as np
import pytest

_MOD = "multiprocess_framework.modules.router_module.middleware.not_inspected_marker"


def _marker_mod():
    import importlib

    return importlib.import_module(_MOD)


def _full_meta() -> dict:
    return {
        "trace_id": "t1",
        "capture_ts": 12.5,
        "frame_id": 7,
        "camera_id": "cam0",
        "frame": np.zeros((2, 2, 3), dtype=np.uint8),
        "_shm_views": ["view0"],
        "_shm_refs": ["ref0"],
        "_shm_dropped": True,
        "target": "somewhere",
    }


def test_not_inspected_constant_literal():
    assert _marker_mod().NOT_INSPECTED == "not_inspected"


def test_marker_reasons_literal_tuple():
    assert _marker_mod().MARKER_REASONS == ("lag", "stale_restore", "stale_exec", "door")


def test_build_marker_exact_dict_for_full_meta():
    marker = _marker_mod().build_marker(_full_meta(), reason="lag", source="processor_0")
    assert marker == {
        "inspection_status": "not_inspected",
        "overflow_marker": True,
        "reason": "lag",
        "source": "processor_0",
        "trace_id": "t1",
        "capture_ts": 12.5,
        "frame_id": 7,
        "camera_id": "cam0",
        "count": 1,  # Task 5.3 (намеренно): маркер = потеря одного кадра
    }


@pytest.mark.parametrize("forbidden", ["frame", "_shm_refs", "_shm_views", "_shm_dropped", "target"])
def test_build_marker_never_carries_forbidden_key(forbidden):
    marker = _marker_mod().build_marker(_full_meta(), reason="lag", source="processor_0")
    # якорь существования: маркер построен и непуст — иначе «ключа нет» верно для чего угодно
    assert marker["inspection_status"] == "not_inspected"
    assert forbidden not in marker


@pytest.mark.parametrize("reason", ["lag", "stale_restore", "stale_exec", "door"])
def test_build_marker_accepts_each_listed_reason(reason):
    marker = _marker_mod().build_marker({}, reason=reason, source="p")
    assert marker["reason"] == reason


def test_build_marker_empty_meta_trace_id_is_empty_string():
    marker = _marker_mod().build_marker({}, reason="door", source="p")
    assert marker["trace_id"] == ""


def test_build_marker_empty_meta_capture_ts_is_none():
    marker = _marker_mod().build_marker({}, reason="door", source="p")
    assert marker["capture_ts"] is None


def test_build_marker_empty_meta_has_no_frame_id_and_camera_id_keys():
    marker = _marker_mod().build_marker({}, reason="door", source="p")
    # якорь: маркер существует и несёт обязательные ключи
    assert marker["source"] == "p"
    assert "frame_id" not in marker
    assert "camera_id" not in marker


def test_build_marker_unknown_reason_raises_value_error():
    with pytest.raises(ValueError):
        _marker_mod().build_marker({}, reason="foo", source="p")


def test_is_marker_true_for_built_marker():
    mod = _marker_mod()
    assert mod.is_marker(mod.build_marker({}, reason="lag", source="p")) is True


def test_is_marker_false_for_plugin_failure_tag_with_frame():
    """Тег от сбоя плагина (кадр с картинкой течёт по цепочке) маркером не считается."""
    item = {"inspection_status": "not_inspected", "frame": np.zeros((2, 2, 3), dtype=np.uint8)}
    assert _marker_mod().is_marker(item) is False


def test_is_marker_false_for_empty_dict():
    assert _marker_mod().is_marker({}) is False


def test_is_marker_false_when_overflow_marker_true_but_status_differs():
    assert _marker_mod().is_marker({"overflow_marker": True, "inspection_status": "pass"}) is False


def test_is_marker_false_when_overflow_marker_is_truthy_but_not_true():
    """Контракт: ``overflow_marker is True`` — истинное не-``True`` значение не годится."""
    assert _marker_mod().is_marker({"overflow_marker": 1, "inspection_status": "not_inspected"}) is False
