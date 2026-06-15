"""Тесты ControlPanelPlugin — регистрация, конфиг, команды, эмит в produce()."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from Services.control_panel.controls import parse_controls


def test_plugin_registered():
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
    import Services.control_panel.plugin.plugin  # noqa: F401  (триггерит @register_plugin)

    entry = PluginRegistry.get("control_panel")
    assert entry is not None
    assert entry.category == "source"
    # Пул выходных портов out_1..out_8
    out_names = {p.name for p in entry.outputs}
    assert "out_1" in out_names and "out_8" in out_names


def test_config_defaults():
    from Services.control_panel.plugin.config import ControlPanelConfig

    cfg = ControlPanelConfig()
    assert cfg.plugin_class.endswith("ControlPanelPlugin")
    assert cfg.port_count == 8
    assert cfg.controls == []
    assert cfg.memory is None  # источник без SHM


class _RecProxy:
    """state_proxy-заглушка: записывает merge-вызовы."""

    def __init__(self) -> None:
        self.merges: list[tuple[str, dict]] = []

    def merge(self, path: str, data: dict) -> None:
        self.merges.append((path, data))


def _make_plugin(controls=None, proxy=None):
    """Сконструировать плагин в обход configure() (без процесса/контекста)."""
    from Services.control_panel.plugin.plugin import ControlPanelPlugin

    p = ControlPanelPlugin()
    p._ctx = SimpleNamespace(process_name="pult", log_info=lambda *a: None)
    p._panel_id = "pult"
    p._controls = parse_controls(controls or [])
    p._state_proxy = proxy
    p._pending = []
    p._lock = threading.Lock()
    return p


def test_set_control_emits_once():
    p = _make_plugin([{"id": "x", "type": "number", "port": "out_1", "min": 0, "max": 100}])
    res = p.cmd_set_control({"id": "x", "value": 250})
    assert res["status"] == "ok"
    assert res["value"] == 100.0  # clamp

    items = p.produce()
    out = [it for it in items if "out_1" in it]
    assert len(out) == 1
    assert out[0]["out_1"] == 100.0
    assert out[0]["data_type"] == "signal"
    # слит — повторно не эмитится
    assert p.produce() == []


def test_button_emit_trigger():
    p = _make_plugin([{"id": "go", "type": "button", "port": "out_2", "trigger_value": "START"}])
    p.cmd_emit_control({"id": "go"})
    items = p.produce()
    assert any(it.get("out_2") == "START" for it in items)


def test_toggle_set_emits_bool():
    p = _make_plugin([{"id": "t", "type": "toggle", "port": "out_3"}])
    p.cmd_set_control({"id": "t", "value": 1})
    items = p.produce()
    assert any(it.get("out_3") is True for it in items)


def test_add_remove_control_publishes():
    proxy = _RecProxy()
    p = _make_plugin([], proxy=proxy)
    assert p.cmd_add_control({"spec": {"id": "a", "type": "button", "port": "out_1"}})["status"] == "ok"
    # дубль — ошибка
    assert p.cmd_add_control({"spec": {"id": "a", "type": "toggle"}})["status"] == "error"
    assert any("control_panel" in path for path, _ in proxy.merges)

    assert p.cmd_remove_control({"id": "a"})["status"] == "ok"
    assert p.cmd_remove_control({"id": "a"})["status"] == "error"  # уже нет


def test_unknown_control_is_error():
    p = _make_plugin([])
    assert p.cmd_set_control({"id": "nope", "value": 1})["status"] == "error"
    assert p.cmd_emit_control({"id": "nope"})["status"] == "error"


def test_get_controls_returns_specs():
    p = _make_plugin([{"id": "a", "type": "slider", "port": "out_1", "min": 1, "max": 9}])
    res = p.cmd_get_controls({})
    assert res["status"] == "ok"
    assert res["controls"][0]["id"] == "a"
    assert res["controls"][0]["value"] == 1.0  # default = min
