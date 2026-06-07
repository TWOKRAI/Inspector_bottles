"""Тесты CameraSettingsPresenter (Phase 4): live-команды + persist в рецепт."""

from __future__ import annotations

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
    def __init__(self, active: str | None, raw: dict | None) -> None:
        self._active = active
        self._raw = raw
        self.saved: tuple | None = None

    def get_active(self):
        return self._active

    def read_raw(self, slug):
        return self._raw

    def save_raw(self, slug, data):
        self.saved = (slug, data)


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
    def test_save_merges_into_recipe(self):
        raw = {
            "data": {
                "blueprint": {
                    "processes": [
                        {"process_name": "camera_0", "plugins": [{"plugin_name": "camera_service"}]},
                    ]
                }
            }
        }
        recipes = _FakeRecipes("recipe_a", raw)
        p = CameraSettingsPresenter(recipes=recipes)
        p._pending = {"gain": 100, "fps": 30, "mjpg": True}
        assert p.save() is True
        slug, data = recipes.saved
        assert slug == "recipe_a"
        plugin = data["data"]["blueprint"]["processes"][0]["plugins"][0]
        assert plugin["params"]["gain"] == 100
        assert plugin["fps"] == 30
        assert plugin["mjpg"] is True

    def test_save_no_active_recipe(self):
        recipes = _FakeRecipes(None, None)
        p = CameraSettingsPresenter(recipes=recipes)
        p._pending = {"gain": 1}
        assert p.save() is False

    def test_save_nothing_pending(self):
        recipes = _FakeRecipes("r", {})
        p = CameraSettingsPresenter(recipes=recipes)
        assert p.save() is False


class TestMergeHelper:
    def test_merge_recursive_finds_block(self):
        raw = {"x": [{"plugin_name": "camera_service"}]}
        assert _merge_camera_params(raw, {"gain": 5, "fps": 10}) is True
        assert raw["x"][0]["params"]["gain"] == 5
        assert raw["x"][0]["fps"] == 10

    def test_merge_not_found(self):
        raw = {"x": [{"plugin_name": "other"}]}
        assert _merge_camera_params(raw, {"gain": 5}) is False
