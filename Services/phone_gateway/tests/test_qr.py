"""Тесты генерации QR (segno опционален)."""

from __future__ import annotations

from Services.phone_gateway import qr


def test_wifi_payload_format():
    out = qr.wifi_payload("MyNet", "pass123", security="WPA")
    assert out == "WIFI:T:WPA;S:MyNet;P:pass123;H:false;;"


def test_wifi_payload_escapes_special_chars():
    out = qr.wifi_payload("Net;1", "p:a;ss")
    assert "\\;" in out and "\\:" in out


def test_make_qr_svg():
    svg = qr.make_qr_svg("http://192.168.1.42:8080")
    if qr.have_qr():
        assert svg is not None and svg.lstrip().startswith("<?xml") or "<svg" in (svg or "")
    else:
        assert svg is None


def test_make_qr_svg_empty_is_none():
    assert qr.make_qr_svg("") is None
