"""Тесты PhoneCameraPlugin — регистрация, конфиг, produce(), toggle сервера."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import cv2
import numpy as np


def _jpeg(w: int = 40, h: int = 30) -> bytes:
    img = np.full((h, w, 3), (7, 14, 21), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def test_plugin_registered():
    from multiprocess_framework.modules.process_module.plugins.registry import (
        PluginRegistry,
    )
    import Services.phone_gateway.plugin.plugin  # noqa: F401  (триггерит @register_plugin)

    entry = PluginRegistry.get("phone_camera")
    assert entry is not None
    assert entry.category == "source"


def test_config_defaults_and_memory():
    from Services.phone_gateway.plugin.config import PhoneCameraConfig

    cfg = PhoneCameraConfig()
    assert cfg.plugin_class.endswith("PhoneCameraPlugin")
    assert cfg.http_port == 8080
    mem = cfg.memory
    assert mem["camera_0_frame"] == (480, 640, 3)
    assert mem["coll"] == 3


def test_registers_default_hold():
    from Services.phone_gateway.plugin.registers import PhoneCameraRegisters

    assert PhoneCameraRegisters().hold_last is True


def _make_plugin(width=64, height=48, hold=True):
    """Сконструировать плагин в обход configure() (без процесса/контекста).

    Gateway на эфемерном порту (0) и НЕ запущен — тесты сами решают про сервер.
    """
    from Services.phone_gateway.gateway import PhoneGateway
    from Services.phone_gateway.plugin.plugin import PhoneCameraPlugin
    from Services.phone_gateway.plugin.registers import PhoneCameraRegisters

    p = PhoneCameraPlugin()
    p._ctx = SimpleNamespace(process_name="phone", log_info=lambda *a: None)
    p._reg = PhoneCameraRegisters(hold_last=hold)
    p._gateway = PhoneGateway(host="127.0.0.1", port=0)
    p._camera_id = 9
    p._width, p._height = width, height
    p._state_proxy = None
    p._placeholder = None
    p._frame_count = 0
    p._last_word_seq = -1
    p._last_photo_seq = -1
    p._auto_start = False
    p._show_hint = False
    p._url = ""
    p._wifi_ssid = ""
    p._wifi_password = ""
    p._pending_signals = []
    p._signal_lock = threading.Lock()
    return p


def test_produce_empty_when_server_off():
    p = _make_plugin()
    p._gateway.submit_frame(_jpeg())  # фото есть, но сервер выключен
    assert p.produce() == []


def test_produce_letterboxes_photo():
    p = _make_plugin(width=64, height=48)
    p._gateway.start()
    try:
        p._gateway.submit_frame(_jpeg(40, 30))
        out = p.produce()
        assert len(out) == 1
        assert out[0]["frame"].shape == (48, 64, 3)
        assert out[0]["camera_type"] == "phone"
    finally:
        p._gateway.stop()


def test_produce_hold_vs_consume():
    p = _make_plugin(hold=True)
    p._gateway.start()
    try:
        p._gateway.submit_frame(_jpeg())
        assert p.produce() and p.produce()  # hold — повторно
    finally:
        p._gateway.stop()

    p2 = _make_plugin(hold=False)
    p2._gateway.start()
    try:
        p2._gateway.submit_frame(_jpeg())
        assert p2.produce()
        assert p2.produce() == []  # consume — один раз
    finally:
        p2._gateway.stop()


def test_toggle_server():
    p = _make_plugin()
    assert p.cmd_server_status({})["running"] is False
    res = p.cmd_start_server({})
    try:
        assert res["running"] is True
        assert res["url"].startswith("http://")
        assert p.cmd_server_status({})["running"] is True
    finally:
        stop = p.cmd_stop_server({})
        assert stop["running"] is False


class _RecProxy:
    """state_proxy-заглушка: записывает merge-вызовы."""

    def __init__(self) -> None:
        self.merges: list[tuple[str, dict]] = []

    def merge(self, path: str, data: dict) -> None:
        self.merges.append((path, data))


def test_emit_signal_produces_item_once():
    p = _make_plugin()
    # сервер выключен → кадра нет; сигнал всё равно эмитится (триггер из GUI)
    res = p.cmd_emit_signal({"port": "signal_1", "value": {"x_mm": 10.0, "y_mm": 20.0}})
    assert res["status"] == "ok" and res["port"] == "signal_1"

    items = p.produce()
    sig = [it for it in items if "signal_1" in it]
    assert len(sig) == 1
    assert sig[0]["signal_1"] == {"x_mm": 10.0, "y_mm": 20.0}
    assert sig[0]["data_type"] == "signal"
    assert "frame" not in sig[0]  # сигнал-item без кадра

    # слит — повторно не эмитится
    assert not any("signal_1" in it for it in p.produce())


def test_signal_coexists_with_frame():
    p = _make_plugin(width=48, height=36)
    p._gateway.start()
    try:
        p._gateway.submit_frame(_jpeg())
        p.cmd_emit_signal({"port": "signal_2", "value": "РОБОТ"})
        items = p.produce()
        assert any(it.get("signal_2") == "РОБОТ" for it in items)  # сигнал
        assert any("frame" in it for it in items)  # и кадр
    finally:
        p._gateway.stop()


def test_publishes_photo_thumb_once_per_photo():
    p = _make_plugin()
    proxy = _RecProxy()
    p._state_proxy = proxy
    p._gateway.start()
    try:
        p._gateway.submit_frame(_jpeg())
        p.produce()
        thumbs = [d for _, d in proxy.merges if "photo_thumb" in d]
        assert len(thumbs) == 1
        assert thumbs[0]["photo_thumb"]  # непустой base64
        assert thumbs[0]["photo_seq"] == 1
        # Тот же кадр — повторно не публикуем (гейт по seq).
        p.produce()
        assert len([d for _, d in proxy.merges if "photo_thumb" in d]) == 1
        # Новое фото — новая публикация.
        p._gateway.submit_frame(_jpeg())
        p.produce()
        assert len([d for _, d in proxy.merges if "photo_thumb" in d]) == 2
    finally:
        p._gateway.stop()
