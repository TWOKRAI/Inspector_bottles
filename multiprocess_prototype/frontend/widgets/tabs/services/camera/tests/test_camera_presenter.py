"""Тесты CameraSettingsPresenter (Phase 4): live-команды + persist в рецепт."""

from __future__ import annotations

from multiprocess_prototype.domain.commands import SetPluginConfig
from multiprocess_prototype.frontend.widgets.tabs.services.camera.presenter import (
    CameraSettingsPresenter,
    _merge_camera_params,
)


class _FakeBridge:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def on_action_command(self, plugin, command, args):
        self.calls.append((plugin, command, args))
        return True


class _FakeTopology:
    def __init__(self, topo: dict) -> None:
        self._topo = topo

    def load(self):
        return self

    def to_dict(self) -> dict:
        return self._topo


class _FakeRecipes:
    def __init__(self, active: str | None) -> None:
        self._active = active

    def get_active(self):
        return self._active


class _FakeCommands:
    def __init__(self) -> None:
        self.dispatched: list = []

    def dispatch(self, command):
        self.dispatched.append(command)


class _FakeSave:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        return self.result


_TOPO = {
    "processes": [
        {"process_name": "camera_0", "plugins": [{"plugin_name": "camera_service"}]},
        {"process_name": "disp", "plugins": [{"plugin_name": "display"}]},
    ]
}


class TestCameraProcessLookup:
    def test_finds_camera_process(self):
        p = CameraSettingsPresenter(topology=_FakeTopology(_TOPO))
        assert p.camera_process_name() == "camera_0"

    def test_none_when_no_camera(self):
        p = CameraSettingsPresenter(topology=_FakeTopology({"processes": []}))
        assert p.camera_process_name() is None

    def test_is_live(self):
        p = CameraSettingsPresenter(bridge=_FakeBridge(), topology=_FakeTopology(_TOPO))
        assert p.is_live is True


class TestLiveCommands:
    def test_apply_param_sends_set_param(self):
        b = _FakeBridge()
        p = CameraSettingsPresenter(bridge=b, topology=_FakeTopology(_TOPO))
        assert p.apply_param("gain", 100) is True
        assert b.calls[-1] == ("camera_service", "set_param", {"name": "gain", "value": 100})

    def test_apply_mjpg(self):
        b = _FakeBridge()
        p = CameraSettingsPresenter(bridge=b)
        p.apply_mjpg(True)
        assert b.calls[-1] == ("camera_service", "set_mjpg", {"on": True})

    def test_apply_fps_and_resolution(self):
        b = _FakeBridge()
        p = CameraSettingsPresenter(bridge=b)
        p.apply_fps(30)
        p.apply_resolution(1280, 720)
        assert ("camera_service", "set_fps", {"fps": 30}) in b.calls
        assert ("camera_service", "set_resolution", {"width": 1280, "height": 720}) in b.calls

    def test_no_bridge_is_noop(self):
        p = CameraSettingsPresenter(bridge=None)
        assert p.apply_param("gain", 1) is False


class TestPersist:
    def test_save_dispatches_set_plugin_config_then_save_active(self):
        commands, save = _FakeCommands(), _FakeSave(True)
        p = CameraSettingsPresenter(
            topology=_FakeTopology(_TOPO), recipes=_FakeRecipes("recipe_a"), commands=commands, save_active=save
        )
        p._pending = {"gain": 100, "fps": 30, "mjpg": True}
        assert p.save() is True
        assert commands.dispatched == [
            SetPluginConfig("camera_0", 0, "fps", 30),
            SetPluginConfig("camera_0", 0, "mjpg", True),
            SetPluginConfig("camera_0", 0, "params", {"gain": 100}),
        ]
        assert save.calls == 1
        assert p._pending == {}

    def test_save_no_active_recipe(self):
        commands, save = _FakeCommands(), _FakeSave(True)
        p = CameraSettingsPresenter(
            topology=_FakeTopology(_TOPO), recipes=_FakeRecipes(None), commands=commands, save_active=save
        )
        p._pending = {"gain": 1}
        assert p.save() is False
        assert commands.dispatched == []
        assert save.calls == 0

    def test_save_nothing_pending(self):
        commands, save = _FakeCommands(), _FakeSave(True)
        p = CameraSettingsPresenter(
            topology=_FakeTopology(_TOPO), recipes=_FakeRecipes("r"), commands=commands, save_active=save
        )
        assert p.save() is False
        assert commands.dispatched == []
        assert save.calls == 0

    def test_save_without_save_active_is_false(self):
        commands = _FakeCommands()
        p = CameraSettingsPresenter(topology=_FakeTopology(_TOPO), recipes=_FakeRecipes("r"), commands=commands)
        p._pending = {"gain": 1}
        assert p.save() is False
        assert commands.dispatched == []

    def test_save_active_returns_false_keeps_pending(self):
        """save_active вернул False без исключения (напр. активный рецепт пропал): False, pending цел."""
        commands, save = _FakeCommands(), _FakeSave(False)
        p = CameraSettingsPresenter(
            topology=_FakeTopology(_TOPO), recipes=_FakeRecipes("r"), commands=commands, save_active=save
        )
        p._pending = {"fps": 30}
        assert p.save() is False
        assert save.calls == 1
        assert p._pending == {"fps": 30}
        assert p.last_error == ""
        save.result = True  # повтор после «исправления» причины: pending не потерян, запись идёт
        assert p.save() is True
        assert p._pending == {}


class TestMergeHelper:
    def test_merge_recursive_finds_block(self):
        raw = {"x": [{"plugin_name": "camera_service"}]}
        assert _merge_camera_params(raw, {"gain": 5, "fps": 10}) is True
        assert raw["x"][0]["params"]["gain"] == 5
        assert raw["x"][0]["fps"] == 10

    def test_merge_not_found(self):
        raw = {"x": [{"plugin_name": "other"}]}
        assert _merge_camera_params(raw, {"gain": 5}) is False
