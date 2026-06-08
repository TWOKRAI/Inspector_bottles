"""Тесты JoinInspectorManager — корреляция N входов по seq_id+data_type.

Семантика: непришедший/неактивный второстепенный вход НЕ ожидается (auto-passthrough),
поэтому в merge-тестах сначала регистрируем активность overlay (присылаем его),
после чего frame того же seq_id ждёт парный overlay. Несколько overlay-источников —
РАЗНЫЕ data_type (overlay1/overlay2), merge конкатенирует общий list-ключ `overlay`.
"""

import time

from multiprocess_framework.modules.process_module.generic.join_inspector_manager import (
    JoinInspectorManager,
)


def _mgr(results, **kw):
    kw.setdefault("required_inputs", {"frame", "overlay"})
    kw.setdefault("primary", "frame")
    kw.setdefault("timeout_sec", 0.05)
    kw.setdefault("inactive_sec", 0.2)
    return JoinInspectorManager(on_ready=results.append, **kw)


class TestPassThrough:
    def test_no_data_type(self):
        results = []
        m = _mgr(results)
        item = {"frame": "f", "seq_id": 1}
        m.on_item(item)
        assert results == [[item]]

    def test_no_seq_id(self):
        results = []
        m = _mgr(results)
        item = {"frame": "f", "data_type": "frame"}
        m.on_item(item)
        assert results == [[item]]


class TestMerge:
    def test_full_set_emits_merged(self):
        """Активный overlay → frame ждёт парный overlay → один слитый item."""
        results = []
        m = _mgr(results)
        # overlay приходит первым: регистрирует активность + буферизуется
        m.on_item({"data_type": "overlay", "seq_id": 7, "overlay": [{"type": "line"}]})
        assert results == []  # ждём frame
        m.on_item({"data_type": "frame", "seq_id": 7, "frame": "F"})
        assert len(results) == 1
        merged = results[0][0]
        assert merged["frame"] == "F"
        assert merged["overlay"] == [{"type": "line"}]
        assert merged["seq_id"] == 7

    def test_two_overlay_sources_concatenated(self):
        """Два overlay-источника (разные data_type) → конкатенация фигур."""
        results = []
        m = JoinInspectorManager(
            required_inputs={"frame", "overlay1", "overlay2"},
            primary="frame",
            timeout_sec=0.05,
            inactive_sec=0.2,
            on_ready=results.append,
        )
        m.on_item({"data_type": "overlay1", "seq_id": 1, "overlay": [{"x": 1}]})
        m.on_item({"data_type": "overlay2", "seq_id": 1, "overlay": [{"x": 2}]})
        assert results == []  # ждём frame
        m.on_item({"data_type": "frame", "seq_id": 1, "frame": "F"})
        assert len(results) == 1
        assert results[0][0]["overlay"] == [{"x": 1}, {"x": 2}]

    def test_primary_scalar_priority(self):
        """Скаляр primary не перезатирается второстепенным при merge."""
        results = []
        m = _mgr(results)
        m.on_item({"data_type": "overlay", "seq_id": 1, "overlay": [], "owner": "filter"})
        m.on_item({"data_type": "frame", "seq_id": 1, "frame": "F", "owner": "cam"})
        assert results[0][0]["owner"] == "cam"


class TestLeftJoin:
    def test_timeout_emits_primary_only(self):
        """overlay активен, но для нового seq не пришёл, окно истекло → кадр без overlay."""
        results = []
        m = _mgr(results)
        m.on_item({"data_type": "overlay", "seq_id": 99, "overlay": []})  # активируем overlay
        results.clear()
        m.on_item({"data_type": "frame", "seq_id": 100, "frame": "F"})
        assert results == []  # ждёт overlay (он недавно активен)
        time.sleep(0.07)
        m.check_timeouts()
        assert len(results) == 1
        assert results[0][0]["frame"] == "F"
        assert "overlay" not in results[0][0]

    def test_no_primary_dropped(self):
        """overlay без frame, окно истекло → дроп (рисовать не на чем)."""
        results = []
        m = _mgr(results)
        m.on_item({"data_type": "overlay", "seq_id": 5, "overlay": [{"a": 1}]})
        time.sleep(0.07)
        m.check_timeouts()
        assert results == []
        assert m.drop_count == 1


class TestAutoPassthrough:
    def test_inactive_secondary_not_awaited(self):
        """overlay никогда не приходил → неактивен → frame эмитится сразу."""
        results = []
        m = JoinInspectorManager(
            required_inputs={"frame", "overlay"},
            primary="frame",
            timeout_sec=0.05,
            inactive_sec=0.05,
            on_ready=results.append,
        )
        m.on_item({"data_type": "frame", "seq_id": 1, "frame": "F"})
        assert len(results) == 1
        assert results[0][0]["frame"] == "F"


class TestTTL:
    def test_pending_count(self):
        results = []
        m = _mgr(results)
        m.on_item({"data_type": "overlay", "seq_id": 1, "overlay": []})
        assert m.pending_count == 1
        time.sleep(0.07)
        m.check_timeouts()
        assert m.pending_count == 0
