"""Тесты PhoneGateway — логика хранилища и HTTP-эндпоинты."""

from __future__ import annotations

import json
import urllib.request

import cv2
import numpy as np
import pytest

from Services.phone_gateway.gateway import PhoneGateway


def _jpeg(w: int = 32, h: int = 24) -> bytes:
    img = np.full((h, w, 3), (5, 10, 15), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


# --- Логика хранилища (без сервера) ---


def test_submit_and_take_frame():
    gw = PhoneGateway()
    res = gw.submit_frame(_jpeg(32, 24))
    assert res["ok"] is True
    assert (res["width"], res["height"]) == (32, 24)
    frame = gw.take_frame()
    assert frame is not None and frame.shape == (24, 32, 3)


def test_submit_bad_frame():
    gw = PhoneGateway()
    res = gw.submit_frame(b"garbage")
    assert res["ok"] is False
    assert gw.take_frame() is None


def test_hold_mode_returns_repeatedly():
    gw = PhoneGateway()
    gw.submit_frame(_jpeg())
    assert gw.take_frame(consume=False) is not None
    assert gw.take_frame(consume=False) is not None  # держим — отдаём снова


def test_consume_mode_returns_once_per_upload():
    gw = PhoneGateway()
    gw.submit_frame(_jpeg())
    assert gw.take_frame(consume=True) is not None
    assert gw.take_frame(consume=True) is None  # тот же кадр повторно не отдаём
    gw.submit_frame(_jpeg())  # новая загрузка
    assert gw.take_frame(consume=True) is not None


def test_submit_word():
    gw = PhoneGateway()
    res = gw.submit_word("  робот ")
    assert res["ok"] is True and res["word"] == "робот"
    snap = gw.word_snapshot()
    assert snap["word"] == "робот" and snap["seq"] == 1


def test_submit_empty_word():
    gw = PhoneGateway()
    assert gw.submit_word("   ")["ok"] is False
    assert gw.word_snapshot()["word"] == ""


def test_submit_phrase_keeps_inner_spaces():
    """Фраза из нескольких слов: внутренние пробелы сохраняются."""
    gw = PhoneGateway()
    res = gw.submit_word("  ГАЙКА   БОЛТ \n")
    assert res["ok"] is True
    assert res["word"] == "ГАЙКА БОЛТ"  # края/повторы схлопнуты, один пробел между слов
    assert gw.word_snapshot()["word"] == "ГАЙКА БОЛТ"


# --- HTTP-эндпоинты (реальный сервер на эфемерном порту) ---


@pytest.fixture()
def running_gateway():
    gw = PhoneGateway(host="127.0.0.1", port=0)
    gw.start()
    try:
        yield gw
    finally:
        gw.stop()


def _post(url: str, body: bytes, ctype: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def test_http_get_page(running_gateway):
    url = f"http://127.0.0.1:{running_gateway.port}/"
    with urllib.request.urlopen(url, timeout=5) as resp:
        assert resp.status == 200
        assert b"<html" in resp.read().lower()


def test_http_health(running_gateway):
    url = f"http://127.0.0.1:{running_gateway.port}/health"
    with urllib.request.urlopen(url, timeout=5) as resp:
        assert json.loads(resp.read())["ok"] is True


def test_http_disables_keepalive(running_gateway):
    """Ответ закрывает соединение (Connection: close) — телефон не держит
    мёртвый keep-alive сокет, переподключение всегда по свежему соединению."""
    url = f"http://127.0.0.1:{running_gateway.port}/health"
    with urllib.request.urlopen(url, timeout=5) as resp:
        assert resp.headers.get("Connection", "").lower() == "close"


def test_http_reconnect_sequential(running_gateway):
    """Несколько независимых соединений подряд проходят (имитация переподключения)."""
    url = f"http://127.0.0.1:{running_gateway.port}/health"
    for _ in range(5):
        with urllib.request.urlopen(url, timeout=5) as resp:
            assert json.loads(resp.read())["ok"] is True


def test_http_post_frame_and_word(running_gateway):
    base = f"http://127.0.0.1:{running_gateway.port}"
    status, body = _post(base + "/frame", _jpeg(48, 36), "image/jpeg")
    assert status == 200 and body["ok"] is True
    assert (body["width"], body["height"]) == (48, 36)
    assert running_gateway.take_frame() is not None

    status, body = _post(base + "/word", "ГАЙКА".encode("utf-8"), "text/plain")
    assert status == 200 and body["ok"] is True and body["word"] == "ГАЙКА"
    assert running_gateway.word_snapshot()["word"] == "ГАЙКА"
