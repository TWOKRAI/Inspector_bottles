"""Тесты TextVectorPlugin — генерация draw_points, merge/override, passthrough."""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.text_vector.plugin import TextVectorPlugin


def _make_plugin(config: dict | None = None) -> TextVectorPlugin:
    services = MockProcessServices(name="text_vector", config=config or {})
    ctx = PluginContext(services=services, config=config or {})
    plugin = TextVectorPlugin()
    plugin.configure(ctx)
    return plugin


def test_registered() -> None:
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
    import Plugins.processing.text_vector.plugin  # noqa: F401

    entry = PluginRegistry.get("text_vector")
    assert entry is not None
    assert entry.category == "processing"


def test_emits_draw_points_for_text() -> None:
    p = _make_plugin({"element": "text", "text": "AB", "size_px": 60.0})
    out = p.process([{}])[0]
    pts = out["draw_points"]
    assert pts and all({"x_mm", "y_mm", "pen"} <= set(q) for q in pts)
    assert pts[0]["pen"] == 0  # первая точка — подвод
    assert p._reg.points_last == len(pts)


def test_disabled_passthrough() -> None:
    p = _make_plugin({"enabled": False, "text": "AB"})
    item = {"draw_points": [{"x_mm": 1.0, "y_mm": 2.0, "pen": 1}]}
    out = p.process([item])[0]
    assert out["draw_points"] == item["draw_points"]  # без изменений


def test_merge_appends_to_incoming() -> None:
    p = _make_plugin({"element": "text", "text": "A", "size_px": 50.0, "merge": True})
    incoming = [{"x_mm": 9.0, "y_mm": 9.0, "pen": 1}]
    out = p.process([{"draw_points": list(incoming)}])[0]["draw_points"]
    assert out[0] == incoming[0]  # вход сохранён в начале
    assert len(out) > 1  # элемент дописан


def test_override_replaces_incoming() -> None:
    p = _make_plugin({"element": "text", "text": "A", "size_px": 50.0, "merge": False})
    incoming = [{"x_mm": 9.0, "y_mm": 9.0, "pen": 1}]
    out = p.process([{"draw_points": list(incoming)}])[0]["draw_points"]
    assert incoming[0] not in out  # вход заменён только элементом


def test_heart_element() -> None:
    p = _make_plugin({"element": "heart", "size_px": 80.0})
    out = p.process([{}])[0]["draw_points"]
    assert out and out[0]["pen"] == 0
    assert p._reg.points_last == len(out)


def test_skipped_chars_recorded() -> None:
    p = _make_plugin({"element": "text", "text": "A☺", "size_px": 40.0})
    p.process([{}])
    assert "☺" in p._reg.skipped_last


def test_frame_passthrough() -> None:
    p = _make_plugin({"element": "text", "text": "A"})
    out = p.process([{"frame": "F"}])[0]
    assert out["frame"] == "F"  # кадр проброшен
