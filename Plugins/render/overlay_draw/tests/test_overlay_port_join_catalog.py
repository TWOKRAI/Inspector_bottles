"""A11 (plans/topology-port-join.md, C16.1): ``catalog.plugins`` несёт ``join`` у портов ``overlay_draw``.

Слепой приёмочный тест. Реальный ``OverlayDrawPlugin`` регистрируется в реестре, дергается
реальный ``BuiltinCommands._cmd_catalog_plugins()`` (как в ``registers_module/tests/
test_field_info_codec_hazards.py::_build_real_payload``). Реестр — снимок/восстановление.

Ожидаемые порты — литералы: ключи ``name``, ``dtype``, ``optional``, ``shape`` как на main,
плюс ``join`` (``overlay`` -> ``True``, остальные -> ``None``).
"""

from __future__ import annotations

import pytest

from Plugins.render.overlay_draw.plugin import OverlayDrawPlugin


@pytest.fixture
def catalog_entry() -> dict:
    from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
    from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

    snapshot = PluginRegistry.snapshot()
    PluginRegistry.clear()
    try:
        PluginRegistry.register("overlay_draw", OverlayDrawPlugin, category="rendering")
        payload = BuiltinCommands(MockProcessServices(name="a11_catalog_test"))._cmd_catalog_plugins()
    finally:
        PluginRegistry.clear()
        PluginRegistry.restore(snapshot)

    assert payload["success"] is True
    assert payload["failed_catalog"] == {}  # достижимость: запись overlay_draw собрана, не провалена
    entries = [p for p in payload["plugins"] if p["name"] == "overlay_draw"]
    assert len(entries) == 1
    return entries[0]


def test_catalog_overlay_input_is_join_true(catalog_entry: dict) -> None:
    overlay = next(p for p in catalog_entry["inputs"] if p["name"] == "overlay")
    assert overlay == {"name": "overlay", "dtype": "dict", "optional": True, "shape": "-", "join": True}


def test_catalog_frame_input_has_join_none(catalog_entry: dict) -> None:
    frame = next(p for p in catalog_entry["inputs"] if p["name"] == "frame")
    assert frame == {"name": "frame", "dtype": "image/*", "optional": False, "shape": "", "join": None}


def test_catalog_frame_output_has_join_none(catalog_entry: dict) -> None:
    frame = next(p for p in catalog_entry["outputs"] if p["name"] == "frame")
    assert frame == {"name": "frame", "dtype": "image/bgr", "optional": False, "shape": "(H, W, 3)", "join": None}


def test_catalog_lists_exactly_two_inputs_and_one_output(catalog_entry: dict) -> None:
    assert [p["name"] for p in catalog_entry["inputs"]] == ["frame", "overlay"]
    assert [p["name"] for p in catalog_entry["outputs"]] == ["frame"]
