"""Smoke-тесты CameraSettingsWidget + _CameraSection (Qt-сборка + сигналы)."""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.tabs.services.camera.widget import (
    CameraSettingsWidget,
)
from multiprocess_prototype.frontend.widgets.tabs.services.camera.section import (
    _CameraSection,
    build_camera_section,
)


class _FakeBindings:
    def __init__(self) -> None:
        self.bound: list[str] = []
        self.unbound = 0

    def bind(self, path, widget, prop="value", *, formatter=None):
        self.bound.append(path)
        return ("h", path)

    def unbind(self, handle):
        self.unbound += 1


class _FakeTopology:
    def load(self):
        return self

    def to_dict(self):
        return {"processes": [{"process_name": "camera_0", "plugins": [{"plugin_name": "camera_service"}]}]}


class _Runtime:
    topology_bridge = None
    bindings = None


class TestWidget:
    def test_widget_builds(self, qtbot):
        w = CameraSettingsWidget()
        qtbot.addWidget(w)
        # actual-метки созданы
        assert set(w.actual_labels) >= {"fps", "resolution", "exposure", "gain", "fourcc"}

    def test_param_signal_emits(self, qtbot):
        w = CameraSettingsWidget()
        qtbot.addWidget(w)
        captured = []
        w.param_changed.connect(lambda n, v: captured.append((n, v)))
        w.mjpg_changed.connect(lambda on: captured.append(("mjpg", on)))
        w._mjpg_check.setChecked(True)
        assert ("mjpg", True) in captured


class TestSection:
    def test_section_binds_actual_when_live(self, qtbot):
        runtime = _Runtime()
        runtime.bindings = _FakeBindings()
        services = type("S", (), {"topology": _FakeTopology(), "recipes": None})()
        section = _CameraSection(services, runtime)
        w = section.widget()
        qtbot.addWidget(w)
        # camera_0 в топологии → actual привязан
        assert any("camera_0.state.cam.actual" in p for p in runtime.bindings.bound)

    def test_build_camera_section_spec(self):
        spec = build_camera_section(object(), object())
        assert spec.key == "__camera__"
        assert spec.title == "Камера"
