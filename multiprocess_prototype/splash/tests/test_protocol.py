"""Слепая приёмка задачи 2.6: шкала заставки и посылка (``splash.protocol``).

Написано до реализации по ``plans/2026-10-27_system-run-state/tasks/2.6.md`` (REDS, «Публичные имена»).
Ожидаемые значения — литералы из задачи. Импорт кода под тестом — внутри тестов: пока модуля нет,
каждый тест краснеет сам, а не одной ошибкой сбора на файл.
"""

from __future__ import annotations

import socket

from multiprocess_framework.modules.process_module.progress import ProgressTracker

#: (id листа, percent листа, done)
_SEQUENCE = [
    ("launch", 50, False),
    ("launch", 100, True),
    ("boot", 50, False),
    ("boot", 20, False),
    ("recipe_load", 90, False),
    ("gui", 40, False),
    ("boot", 100, True),
    ("gui", 100, True),
]


def test_scale_literals_monotone_and_tracker():
    from multiprocess_prototype.splash.protocol import SPLASH_WEIGHTS, SplashScale

    scale = SplashScale()
    returned = []
    seen_by_property = []
    for progress_id, percent, done in _SEQUENCE:
        returned.append(scale.feed({"id": progress_id, "percent": percent, "label": "", "done": done}))
        seen_by_property.append(scale.percent)

    assert returned == [5, 10, 35, 35, 35, 51, 76, 100]
    assert seen_by_property == [5, 10, 35, 35, 35, 51, 76, 100]

    # То же правило, что у ProgressTracker (неизвестный трекеру ``recipe_load`` из ряда убран).
    tracker = ProgressTracker(list(SPLASH_WEIGHTS.items()))
    by_tracker = [
        tracker.advance(progress_id, percent / 100)["percent"]
        for progress_id, percent, _done in _SEQUENCE
        if progress_id != "recipe_load"
    ]
    assert by_tracker == [5, 10, 35, 35, 51, 76, 100]


def test_encode_decode_send_edges():
    from multiprocess_prototype.splash.protocol import (
        decode,
        encode,
        is_close_signal,
        send_leaf,
        splash_enabled,
    )

    full = {"id": "boot", "percent": 5, "label": "", "done": False}
    assert decode(encode("boot", {"percent": 5})) == full
    # Якорь: ``label``/``done`` на входе необязательны — отказы ниже вызваны названным полем, а не их отсутствием.
    assert decode(b'{"id": "boot", "percent": 5}') == full
    assert decode(b'{"id": "boot", "percent": 100}') == {"id": "boot", "percent": 100, "label": "", "done": False}

    assert decode(b"x") is None
    assert decode(b"[]") is None
    assert decode(b'{"id": "boot", "percent": 101}') is None
    assert decode(b'{"id": "boot", "percent": true}') is None
    assert decode(b'{"id": "boot", "percent": "5"}') is None
    assert decode(b'{"id": "", "percent": 5}') is None

    leaf = {"percent": 5}
    assert send_leaf("boot", leaf, environ={}) is False
    assert send_leaf("boot", leaf, environ={"INSPECTOR_SPLASH_PORT": "abc"}) is False
    # Якорь существования: на живом порту тот же вызов даёт True и датаграмму.
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(5.0)
        port = str(receiver.getsockname()[1])
        assert send_leaf("boot", leaf, environ={"INSPECTOR_SPLASH_PORT": port}) is True
        assert decode(receiver.recv(65535)) == full
    finally:
        receiver.close()

    assert is_close_signal({"id": "gui", "percent": 100, "label": "", "done": True}) is True
    assert is_close_signal({"id": "gui", "percent": 100, "label": "", "done": False}) is False
    assert is_close_signal({"id": "boot", "percent": 100, "label": "", "done": True}) is False
    assert is_close_signal({"id": "launch", "percent": 100, "label": "", "done": True}) is False

    assert splash_enabled({"INSPECTOR_SPLASH": " 0 "}) is False
    assert splash_enabled({"INSPECTOR_SPLASH": "0"}) is False
    assert splash_enabled({}) is True
    assert splash_enabled({"INSPECTOR_SPLASH": "1"}) is True
    assert splash_enabled({"INSPECTOR_SPLASH": ""}) is True
