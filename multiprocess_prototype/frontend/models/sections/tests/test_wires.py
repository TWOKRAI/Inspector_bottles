"""Тесты для WiresSectionView и WireEditorModel.

Проверяет CRUD wires, валидацию адресов, dirty tracking,
round-trip через blueprint, port resolution (graceful degradation).
"""

import pytest

from multiprocess_prototype.frontend.models.system_topology_editor import (
    SystemTopologyEditor,
)
from multiprocess_prototype.frontend.models.sections.wires_section import (
    WiresSectionView,
)
from multiprocess_prototype.frontend.models.wire_model import (
    PortAddress,
    WireEditorModel,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def editor() -> SystemTopologyEditor:
    """Свежий редактор с двумя процессами и плагинами."""
    ed = SystemTopologyEditor()
    ed.update_item("processes", "cam_0", {
        "name": "camera_0",
        "class_path": "app.CameraProcess",
        "priority": "normal",
        "auto_start": True,
        "sort_order": 0,
        "plugins": [
            {"plugin_class": "app.Capture", "plugin_name": "capture"},
            {"plugin_class": "app.Grayscale", "plugin_name": "grayscale"},
        ],
    })
    ed.update_item("processes", "proc_1", {
        "name": "processor_1",
        "class_path": "app.ProcessorProcess",
        "priority": "normal",
        "auto_start": True,
        "sort_order": 1,
        "plugins": [
            {"plugin_class": "app.ColorMask", "plugin_name": "color_mask"},
        ],
    })
    ed.mark_clean()
    return ed


@pytest.fixture
def wires(editor: SystemTopologyEditor) -> WiresSectionView:
    return editor.wires_section


@pytest.fixture
def model(wires: WiresSectionView) -> WireEditorModel:
    return WireEditorModel(wires)


# ---------------------------------------------------------------------------
# WiresSectionView: CRUD
# ---------------------------------------------------------------------------


class TestWiresSectionCRUD:
    def test_empty_initially(self, wires: WiresSectionView) -> None:
        assert wires.wires == {}
        assert not wires.dirty

    def test_add_wire(self, wires: WiresSectionView) -> None:
        key = wires.add_wire("cam_0.capture.frame", "proc_1.color_mask.frame")
        assert key.startswith("wire_")
        assert key in wires.wires
        assert wires.wires[key]["source"] == "cam_0.capture.frame"
        assert wires.wires[key]["target"] == "proc_1.color_mask.frame"
        assert wires.dirty

    def test_remove_wire(self, wires: WiresSectionView) -> None:
        key = wires.add_wire("cam_0.capture.frame", "proc_1.color_mask.frame")
        wires.remove_wire(key)
        assert key not in wires.wires

    def test_remove_nonexistent_raises(self, wires: WiresSectionView) -> None:
        with pytest.raises(KeyError):
            wires.remove_wire("nonexistent")

    def test_modify_wire(self, wires: WiresSectionView) -> None:
        key = wires.add_wire("cam_0.capture.frame", "proc_1.color_mask.frame")
        wires.modify_wire(key, {"description": "frame data"})
        assert wires.wires[key]["description"] == "frame data"

    def test_modify_nonexistent_raises(self, wires: WiresSectionView) -> None:
        with pytest.raises(KeyError):
            wires.modify_wire("nonexistent", {"description": "x"})

    def test_wires_for_process(self, wires: WiresSectionView) -> None:
        wires.add_wire("cam_0.capture.frame", "proc_1.color_mask.frame")
        wires.add_wire("cam_0.grayscale.out", "proc_1.color_mask.mask")

        cam_wires = wires.wires_for_process("cam_0")
        assert len(cam_wires) == 2

        proc_wires = wires.wires_for_process("proc_1")
        assert len(proc_wires) == 2

        # Процесс без wires
        none_wires = wires.wires_for_process("other")
        assert len(none_wires) == 0


# ---------------------------------------------------------------------------
# WiresSectionView: Snapshot / Round-trip
# ---------------------------------------------------------------------------


class TestWiresSnapshot:
    def test_full_snapshot(self, wires: WiresSectionView) -> None:
        key = wires.add_wire("cam_0.capture.frame", "proc_1.color_mask.frame")
        snap = wires.full_snapshot()
        assert key in snap
        # Snapshot — копия, изменения не отражаются
        snap[key]["description"] = "modified"
        assert wires.wires[key]["description"] == ""

    def test_load_from_snapshot(self, wires: WiresSectionView) -> None:
        snap = {
            "w1": {
                "source": "cam_0.capture.frame",
                "target": "proc_1.color_mask.frame",
                "description": "loaded",
                "transport": "router",
                "shm_config": {},
            }
        }
        wires.load_from_snapshot(snap)
        assert "w1" in wires.wires
        assert wires.wires["w1"]["description"] == "loaded"

    def test_editor_round_trip(self, editor: SystemTopologyEditor) -> None:
        """Полный round-trip: add wire → export → load → wire сохранён."""
        ws = editor.wires_section
        ws.add_wire("cam_0.capture.frame", "proc_1.color_mask.frame", description="rt")

        exported = editor.to_dict()
        assert len(exported["wires"]) == 1

        editor2 = SystemTopologyEditor()
        editor2.load(exported)
        assert len(editor2.wires_section.wires) == 1
        first_wire = next(iter(editor2.wires_section.wires.values()))
        assert first_wire["description"] == "rt"


# ---------------------------------------------------------------------------
# Валидация
# ---------------------------------------------------------------------------


class TestWiresValidation:
    def test_valid_wire_no_errors(self, editor: SystemTopologyEditor) -> None:
        ws = editor.wires_section
        ws.add_wire("cam_0.capture.frame", "proc_1.color_mask.frame")
        errors = editor.validate("wires")
        assert errors == []

    def test_invalid_process_ref(self, editor: SystemTopologyEditor) -> None:
        ws = editor.wires_section
        ws.add_wire("nonexistent.capture.frame", "proc_1.color_mask.frame")
        errors = editor.validate("wires")
        assert any("nonexistent" in e for e in errors)

    def test_invalid_plugin_ref(self, editor: SystemTopologyEditor) -> None:
        ws = editor.wires_section
        ws.add_wire("cam_0.no_such_plugin.frame", "proc_1.color_mask.frame")
        errors = editor.validate("wires")
        assert any("no_such_plugin" in e for e in errors)

    def test_invalid_format(self, editor: SystemTopologyEditor) -> None:
        ws = editor.wires_section
        ws.add_wire("bad_format", "also_bad")
        errors = editor.validate("wires")
        assert len(errors) >= 2  # Оба адреса невалидны

    def test_empty_source(self, editor: SystemTopologyEditor) -> None:
        ws = editor.wires_section
        ws.add_wire("", "proc_1.color_mask.frame")
        errors = editor.validate("wires")
        assert any("пустой" in e or "empty" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# PortAddress
# ---------------------------------------------------------------------------


class TestPortAddress:
    def test_parse_valid(self) -> None:
        pa = PortAddress.parse("cam_0.capture.frame", "output")
        assert pa is not None
        assert pa.process == "cam_0"
        assert pa.plugin == "capture"
        assert pa.port == "frame"
        assert pa.direction == "output"
        assert pa.address == "cam_0.capture.frame"

    def test_parse_invalid(self) -> None:
        assert PortAddress.parse("bad_format") is None
        assert PortAddress.parse("a.b") is None
        assert PortAddress.parse("a.b.c.d") is None


# ---------------------------------------------------------------------------
# WireEditorModel
# ---------------------------------------------------------------------------


class TestWireEditorModel:
    def test_add_wire_valid(self, model: WireEditorModel) -> None:
        """Добавление валидного wire (registry недоступен — graceful)."""
        key = model.add_wire("cam_0.capture.frame", "proc_1.color_mask.frame")
        assert key != ""
        assert key in model.wires

    def test_add_wire_same_process_rejected(self, model: WireEditorModel) -> None:
        """Wire внутри одного процесса отклоняется."""
        key = model.add_wire("cam_0.capture.frame", "cam_0.grayscale.in")
        assert key == ""

    def test_add_wire_invalid_format_rejected(self, model: WireEditorModel) -> None:
        key = model.add_wire("bad", "also_bad")
        assert key == ""

    def test_validate_wire_cross_process(self, model: WireEditorModel) -> None:
        errors = model.validate_wire("cam_0.capture.frame", "proc_1.color_mask.frame")
        assert errors == []

    def test_validate_wire_same_process(self, model: WireEditorModel) -> None:
        errors = model.validate_wire("cam_0.capture.frame", "cam_0.grayscale.in")
        assert len(errors) == 1
        assert "одного процесса" in errors[0]

    def test_validate_all(self, model: WireEditorModel) -> None:
        model._section.add_wire("cam_0.capture.frame", "proc_1.color_mask.frame")
        errors = model.validate_all()
        assert errors == []

    def test_remove_wire(self, model: WireEditorModel) -> None:
        key = model.add_wire("cam_0.capture.frame", "proc_1.color_mask.frame")
        model.remove_wire(key)
        assert key not in model.wires

    def test_wires_for_process(self, model: WireEditorModel) -> None:
        model.add_wire("cam_0.capture.frame", "proc_1.color_mask.frame")
        result = model.wires_for_process("cam_0")
        assert len(result) == 1

    def test_available_ports_graceful(self, model: WireEditorModel) -> None:
        """Без PluginRegistry — пустой список (graceful degradation)."""
        ports = model.available_ports("cam_0")
        # Может быть пустой если registry не загружен — это нормально
        assert isinstance(ports, list)
