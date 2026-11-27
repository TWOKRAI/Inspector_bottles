# -*- coding: utf-8 -*-
"""W2-c2: тёмная плашка с названием и адресом камеры вместо замершего кадра (тесты автора).

Purpose: дисплей в режиме ``silence``, у которого ВСЕ его отправители молчат ``plate_after_s``,
показывает плашку «<шаблон>\\nнет кадров, N с» и сам возвращается к кадру; ``hold`` и ``trigger``
плашку по тишине не ставят. Настоящие ``_setup_bridge_callbacks``,
``DataReceiverBridge``, ``FramePump`` и ``ImagePanelWidget``; рецепт — словарь.

Ожидаемые значения — литералы. Ожидание — цикл событий Qt с дедлайном.

Запуск (из корня worktree, PYTHONPATH=корень, PYTHONUTF8=1, Qt offscreen), класс ``light``.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEventLoop, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402

__all__: list[str] = []

_QUIET_S = 2.5  # сколько молчим: дольше порога 1 с и умолчания 2 с
_SILENT = {"plate_mode": "silence", "plate_after_s": 1}  # экран, где ждут плашку


# ---------------------------------------------------------------------------
# Помощники
# ---------------------------------------------------------------------------


def _spin_until(cond: Callable[[], bool], timeout_s: float) -> bool:
    """Крутить цикл событий Qt, пока cond() не станет True или не истечёт timeout_s."""
    loop = QEventLoop()
    deadline = time.perf_counter() + timeout_s
    state = {"ok": False}
    poll = QTimer()
    poll.setInterval(5)

    def _check() -> None:
        if cond():
            state["ok"] = True
            loop.quit()
        elif time.perf_counter() >= deadline:
            loop.quit()

    poll.timeout.connect(_check)
    poll.start()
    _check()
    if not state["ok"] and time.perf_counter() < deadline:
        loop.exec()
    poll.stop()
    return state["ok"]


def _spin(seconds: float) -> None:
    _spin_until(lambda: False, seconds)


def _msg(sender: str) -> dict:
    return {"sender": sender, "frame": np.full((48, 64, 3), 200, dtype=np.uint8), "data": {}}


def _display(display_id: str, name: str, x: int = 0, **plate: Any) -> dict:
    position = {"x": x, "y": 0}
    return {"id": display_id, "name": name, "enabled": True, "position": position, "fps_limit": 30.0, **plate}


class _Producer:
    """Поток, шлющий кадры одного sender каждые 50 мс (идёт и во время заминки цикла Qt)."""

    def __init__(self, bridge: Any, sender: str) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(bridge, sender), name=f"{sender}-producer", daemon=True)
        self._thread.start()

    def _run(self, bridge: Any, sender: str) -> None:
        while not self._stop.is_set():
            bridge.dispatch(_msg(sender))
            self._stop.wait(0.05)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(2.0)


@pytest.fixture()
def wire(qtbot):
    """Фабрика проводки: настоящие мост, насос и панель; режим и порог плашки берутся из рецепта."""
    from multiprocess_prototype.frontend import app as app_module
    from multiprocess_prototype.frontend.bridge import DataReceiverBridge
    from multiprocess_prototype.frontend.frame_intake import FrameIntake
    from multiprocess_prototype.frontend.widgets.image_panel.widget import ImagePanelWidget

    pumps: list = []

    def _make(recipe: dict) -> SimpleNamespace:
        class _Recipes:
            def get_active(self) -> str:
                return "plate"

            def read_recipe(self, _slug: str) -> dict:
                return recipe

        subscribers: list = []
        bus = SimpleNamespace(subscribe=lambda _event, callback: subscribers.append(callback))
        bridge = DataReceiverBridge()
        panel = ImagePanelWidget()
        qtbot.addWidget(panel)
        intake = FrameIntake(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
        process = SimpleNamespace(_bridge=bridge, _frame_intake=intake, _log_info=MagicMock(), _log_warning=MagicMock())
        app_module._setup_bridge_callbacks(
            process, panel, MagicMock(name="window"), recipe_manager=_Recipes(), event_bus=bus
        )
        pumps.append(process._frame_pump)

        def fire() -> None:
            assert subscribers, "подписка на пересборку дисплеев не сделана"
            subscribers[0](None)  # RecipeActivated

        return SimpleNamespace(bridge=bridge, panel=panel, pump=process._frame_pump, fire=fire)

    yield _make
    for pump in pumps:
        pump.stop()
    QCoreApplication.removePostedEvents(None)


def _spy_plate(panel: Any, slot_id: str) -> list[str]:
    """Обернуть ``show_no_signal`` объекта слота: список текстов всех вызовов."""
    slot = panel._slots[slot_id]  # noqa: SLF001
    original = slot.show_no_signal
    calls: list[str] = []

    def spy(text: str) -> None:
        calls.append(text)
        original(text)

    slot.show_no_signal = spy
    return calls


def _label(panel: Any, slot_id: str) -> Any:
    return panel._slots[slot_id]._label  # noqa: SLF001


def _shown(panel: Any, slot_id: str) -> int:
    return panel.presenter.frame_stats(slot_id)["shown"]


# ---------------------------------------------------------------------------
# recipe_displays: шаблон, статус, поля из рецепта
# ---------------------------------------------------------------------------


def test_plate_text_default_template() -> None:
    from multiprocess_prototype.frontend.widgets.image_panel.recipe_displays import plate_status, plate_text

    fields = {"title": "Камера 1", "number": 0, "address": None}

    assert plate_text("", fields) == "Камера 1 · № 0 · —"
    assert plate_status("lost", 3.9) == "нет связи, 3 с"
    assert plate_status(None, 3.9) == "нет кадров, 3 с"


def test_plate_text_unknown_and_unsafe_fields_stay_literal(caplog) -> None:
    from multiprocess_prototype.frontend.widgets.image_panel.recipe_displays import plate_text

    assert plate_text("{title} {x} {title.__class__} {title:>9}", {"title": "К"}) == (
        "К {x} {title.__class__} {title:>9}"
    )

    fields = {"title": "К", "number": 1, "address": "10.0.0.1"}
    with caplog.at_level(logging.WARNING):
        assert plate_text("{title", fields) == "К · № 1 · 10.0.0.1"
        assert plate_text("{title", fields) == "К · № 1 · 10.0.0.1"
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING and "{title" in r.getMessage()]
    assert len(warnings) == 1, f"ожидали одно WARNING на текст шаблона: {warnings}"


def test_build_plate_sources_flat_nested_and_override() -> None:
    from multiprocess_prototype.frontend.widgets.image_panel.recipe_displays import build_plate_sources

    recipe = {
        "displays": [
            {"id": "d0", "name": "0"},
            {"id": "d1", "name": "1", "plate_text": "{title}"},
            {"id": "r1", "name": "R", "plate_source": "reader_1.code_reader_sdk"},
            {"id": "free", "name": "F"},
        ],
        "blueprint": {
            "displays": [
                {"node_id": "cam_0.camera_device.frame", "display_id": "d0"},
                {"node_id": "other.plugin.frame", "display_id": "d0"},
                {"node_id": "cam_1.hikvision.frame", "display_id": "d1"},
                {"node_id": "draw_1.overlay_draw.frame", "display_id": "r1"},
            ],
            "processes": [
                {
                    "process_name": "cam_0",
                    "plugins": [{"plugin_name": "camera_device", "camera_id": 0, "device_serial": "S1"}],
                },
                {
                    "process_name": "cam_1",
                    "plugins": [
                        {
                            "plugin_name": "hikvision",
                            "camera_id": 9,
                            "config": {"camera_id": 1, "device_serial": "DA1"},
                        }
                    ],
                },
                {
                    "process_name": "reader_1",
                    "plugins": [{"plugin_name": "code_reader_sdk", "device_ip": "192.168.1.10", "reader_id": 1}],
                },
            ],
        },
    }

    sources = build_plate_sources(recipe)

    assert sources["d0"] == {
        "source": "cam_0.camera_device",
        "process": "cam_0",
        "number": 0,
        "address": None,
        "serial": "S1",
        "template": "",
        "mode": "hold",
        "after_s": 2,
        "run_view": "always",
    }
    assert sources["d1"] == {
        "source": "cam_1.hikvision",
        "process": "cam_1",
        "number": 1,
        "address": None,
        "serial": "DA1",
        "template": "{title}",
        "mode": "hold",
        "after_s": 2,
        "run_view": "always",
    }
    assert sources["r1"] == {
        "source": "reader_1.code_reader_sdk",
        "process": "reader_1",
        "number": 1,
        "address": "192.168.1.10",
        "serial": None,
        "template": "",
        "mode": "hold",
        "after_s": 2,
        "run_view": "always",
    }
    assert sources["free"] == {
        "source": "",
        "process": "",
        "number": None,
        "address": None,
        "serial": None,
        "template": "",
        "mode": "hold",
        "after_s": 2,
        "run_view": "always",
    }
    assert build_plate_sources({"displays": "x", "blueprint": {"processes": None}}) == {}
    assert build_plate_sources(None) == {}
    broken = {
        "displays": [None, {"id": "d"}],
        "blueprint": {
            "displays": [7, {"node_id": "p.q.frame", "display_id": "d"}],
            "processes": [3, {"process_name": "p", "plugins": [5, {"plugin_name": "q", "config": "x"}]}],
        },
    }
    assert build_plate_sources(broken)["d"]["process"] == "p"


# ---------------------------------------------------------------------------
# DisplaySlot
# ---------------------------------------------------------------------------


def _pixmap() -> QPixmap:
    pixmap = QPixmap(64, 48)
    pixmap.fill(QColor("red"))
    return pixmap


@pytest.fixture()
def slot(qtbot):
    from multiprocess_prototype.frontend.widgets.image_panel.display_slot import DisplaySlot

    widget = DisplaySlot(slot_id="s", label="Камера 0")
    qtbot.addWidget(widget)
    widget.show()
    QCoreApplication.processEvents()
    return widget


def test_slot_plate_and_resize_keeps_plate(slot) -> None:
    slot.update_pixmap(_pixmap())
    slot.show_no_signal("X\nнет кадров, 3 с")

    slot.resize(slot.width() + 200, slot.height() + 150)
    QCoreApplication.processEvents()

    label = slot._label  # noqa: SLF001
    assert label.pixmap().isNull()
    assert label.text() == "X\nнет кадров, 3 с"
    assert "#202020" in label.styleSheet()


def test_frame_then_leave_restores_image(slot) -> None:
    slot.show_no_signal("X\nнет кадров, 3 с")
    slot.update_pixmap(_pixmap())

    label = slot._label  # noqa: SLF001
    assert label.styleSheet() == ""
    assert not label.pixmap().isNull()
    before = (label.styleSheet(), label.text(), label.pixmap().cacheKey())

    for _ in range(3):
        slot.leave_no_signal()

    assert (label.styleSheet(), label.text(), label.pixmap().cacheKey()) == before
    assert not label.pixmap().isNull()


def test_leave_without_frame_removes_plate_text(slot) -> None:
    slot.show_no_signal("X\nнет кадров, 3 с")

    slot.leave_no_signal()

    label = slot._label  # noqa: SLF001
    assert label.text() == "Камера 0"
    assert label.styleSheet() == ""


# ---------------------------------------------------------------------------
# Проводка app: sink насоса, тишина, сбор отправителей
# ---------------------------------------------------------------------------


def test_unshown_frame_returns_false(wire) -> None:
    w = wire({})
    w.pump.stop()  # sink зовём сами
    sink = w.pump._sink  # noqa: SLF001

    assert sink("cam", _msg("cam")) is True
    assert sink("cam", {"sender": "cam", "data": {}}) is False

    w.bridge.restore_for_show = lambda _item: None  # ссылка SHM порвана
    assert sink("cam", _msg("cam")) is False


def test_two_senders_one_display_no_plate_while_one_alive(wire) -> None:
    recipe = {
        "displays": [_display("d", "D", **_SILENT)],
        "blueprint": {
            "displays": [
                {"node_id": "a.src.frame", "display_id": "d"},
                {"node_id": "b.src.frame", "display_id": "d"},
            ]
        },
    }
    w = wire(recipe)
    calls = _spy_plate(w.panel, "d")
    original = w.pump._on_silence  # noqa: SLF001
    silences: list[tuple[str, float | None]] = []

    def spy_silence(key: str, age_s: float | None) -> None:
        silences.append((key, age_s))
        original(key, age_s)

    w.pump._on_silence = spy_silence  # noqa: SLF001
    producer = _Producer(w.bridge, "b")
    try:
        assert _spin_until(lambda: _shown(w.panel, "d") >= 1, 1.0), "кадры b не показаны"
        shown = _shown(w.panel, "d")
        _spin(_QUIET_S)
        assert _shown(w.panel, "d") > shown, "кадры b перестали показываться"
        assert any(key == "a" and age is not None for key, age in silences), "тишина a не сообщена"
        assert calls == [], f"плашка при живом b: {calls}"
    finally:
        producer.stop()

    _spin(_QUIET_S)
    assert len(calls) >= 1, "оба молчат, плашки нет"


def test_two_unbound_senders_on_main_no_plate_while_one_alive(wire) -> None:
    w = wire({"displays": [_display("main", "main", **_SILENT)], "blueprint": {"displays": []}})
    calls = _spy_plate(w.panel, "main")
    w.bridge.dispatch(_msg("u1"))
    assert _spin_until(lambda: _shown(w.panel, "main") >= 1, 1.0), "кадр u1 не показан"
    w.bridge.dispatch(_msg("u2"))
    assert _spin_until(lambda: _shown(w.panel, "main") >= 2, 1.0), "кадр u2 не показан"
    producer = _Producer(w.bridge, "u2")
    try:
        assert _spin_until(lambda: _shown(w.panel, "main") >= 4, 1.0), "кадры u2 не идут"
        calls.clear()
        shown = _shown(w.panel, "main")
        _spin(_QUIET_S)
        assert _shown(w.panel, "main") > shown, "кадры u2 перестали показываться"
        assert calls == [], f"плашка при живом u2: {calls}"
    finally:
        producer.stop()

    _spin(_QUIET_S)
    assert len(calls) >= 1, "оба молчат, плашки нет"


def test_scan_found_sender_survives_rebuild(wire) -> None:
    w = wire({"displays": [_display("main", "main", **_SILENT)], "blueprint": {"displays": []}})
    w.bridge.dispatch(_msg("u"))
    assert _spin_until(lambda: w.bridge.frame_mailbox.stats()["pending"] == 0 and _shown(w.panel, "main") >= 1, 1.0), (
        "кадр не показан до пересборки"
    )

    w.fire()
    _spin(_QUIET_S)

    assert _label(w.panel, "main").text().startswith("main · № — · —\nнет кадров, ")


def test_app_wiring_silent_sender_draws_plate_on_its_display(wire) -> None:
    recipe = {
        "displays": [_display("display_2", "Камера 0", **_SILENT), _display("display_x", "Пустой", 10, **_SILENT)],
        "blueprint": {
            "displays": [{"node_id": "camera_0.camera_device.frame", "display_id": "display_2"}],
            "processes": [{"process_name": "camera_0", "plugins": [{"plugin_name": "camera_device", "camera_id": 0}]}],
        },
    }
    w = wire(recipe)
    w.bridge.dispatch(_msg("camera_0"))
    assert _spin_until(lambda: _shown(w.panel, "display_2") >= 1, 1.0), "кадр не показан"

    _spin(_QUIET_S)

    assert _label(w.panel, "display_2").text().startswith("Камера 0 · № 0 · —\nнет кадров, ")
    assert "нет кадров" not in _label(w.panel, "display_x").text()
    assert _label(w.panel, "display_x").styleSheet() == ""

    w.bridge.dispatch(_msg("camera_0"))
    assert _spin_until(lambda: not _label(w.panel, "display_2").pixmap().isNull(), 1.0), "картинка не вернулась"
    assert _label(w.panel, "display_2").styleSheet() == ""


# ---------------------------------------------------------------------------
# Пересборка дисплеев и отправители из привязок
# ---------------------------------------------------------------------------


def _two_bound_to_d() -> dict:
    """Дисплей ``d`` с отправителями ``a`` и ``b``; ``e`` держит набор дисплеев непустым при выключенном ``d``."""
    return {
        "displays": [_display("d", "D", **_SILENT), _display("e", "E", 10, **_SILENT)],
        "blueprint": {
            "displays": [
                {"node_id": "a.src.frame", "display_id": "d"},
                {"node_id": "b.src.frame", "display_id": "d"},
            ]
        },
    }


def test_rebuild_forgets_silence_of_dropped_keys(wire) -> None:
    """Выключили и включили дисплей: прежняя тишина ``a`` не должна давать плашку поверх живой камеры."""
    recipe = _two_bound_to_d()
    w = wire(recipe)
    assert _spin_until(lambda: "нет кадров" in _label(w.panel, "d").text(), 3.0), "оба молчат, плашки нет"

    recipe["displays"][0]["enabled"] = False
    w.fire()
    recipe["displays"][0]["enabled"] = True
    w.fire()
    calls = _spy_plate(w.panel, "d")  # слот пересоздан, шпион ставится на новый объект
    producer = _Producer(w.bridge, "a")
    try:
        assert _spin_until(lambda: _shown(w.panel, "d") >= 1, 1.0), "кадры a не показаны"
        calls.clear()
        shown = _shown(w.panel, "d")
        _spin(2.5)  # b молчит
        assert _shown(w.panel, "d") > shown, "кадры a перестали показываться"
        assert calls == [], f"плашка поверх живой камеры a: {calls}"
    finally:
        producer.stop()


def test_rebuild_removes_plate_of_unbound_display(wire) -> None:
    """Новый рецепт без привязки к ``d``: старая плашка снята, на слоте обычный placeholder."""
    recipe = {
        "displays": [_display("d", "D", **_SILENT)],
        "blueprint": {"displays": [{"node_id": "a.src.frame", "display_id": "d"}]},
    }
    w = wire(recipe)
    assert _spin_until(lambda: "нет кадров" in _label(w.panel, "d").text(), 3.0), "плашки нет"

    recipe["blueprint"] = {"displays": []}
    w.fire()
    _spin(_QUIET_S)

    assert _label(w.panel, "d").text() == "D"
    assert _label(w.panel, "d").styleSheet() == ""


def test_bound_sender_without_frames_holds_the_plate(wire) -> None:
    """Привязанный отправитель, ещё не объявленный молчащим, не даёт поставить плашку по молчанию соседа."""
    w = wire(_two_bound_to_d())
    w.pump.stop()  # тишину сообщаем сами, в заданном порядке
    calls = _spy_plate(w.panel, "d")

    w.pump._on_silence("b", 1.0)  # noqa: SLF001
    assert calls == [], f"плашка по молчанию одного b: {calls}"

    w.pump._on_silence("a", 1.0)  # noqa: SLF001
    assert calls == ["D · № — · —\nнет кадров, 1 с"]


# ---------------------------------------------------------------------------
# Режим плашки на каждом экране, порог, перенос строки (W2-c2b)
# ---------------------------------------------------------------------------


def _spy_silence(pump: Any) -> list[tuple[str, float | None]]:
    """Что насос сообщил приложению: список (ключ, возраст тишины)."""
    original = pump._on_silence  # noqa: SLF001
    seen: list[tuple[str, float | None]] = []

    def spy(key: str, age_s: float | None) -> None:
        seen.append((key, age_s))
        original(key, age_s)

    pump._on_silence = spy  # noqa: SLF001
    return seen


def _quiet_calls(wire, plate: dict) -> tuple[list[str], list[str]]:
    """Экран ``d`` с настройками ``plate`` и контроль ``c`` (silence/1), оба молчат: вызовы плашки."""
    w = wire(
        {
            "displays": [_display("d", "Экран", **plate), _display("c", "Контроль", 10, **_SILENT)],
            "blueprint": {
                "displays": [
                    {"node_id": "sd.src.frame", "display_id": "d"},
                    {"node_id": "sc.src.frame", "display_id": "c"},
                ]
            },
        }
    )
    calls = _spy_plate(w.panel, "d")
    control = _spy_plate(w.panel, "c")
    _spin(_QUIET_S)
    return calls, control


def test_hold_mode_by_default_no_plate(wire) -> None:
    calls, control = _quiet_calls(wire, {})

    assert control and control[0] == "Контроль · № — · —\nнет кадров, 1 с"
    assert calls == []


def test_trigger_mode_no_plate_on_silence(wire) -> None:
    calls, control = _quiet_calls(wire, {"plate_mode": "trigger", "plate_after_s": 1})

    assert control and control[0] == "Контроль · № — · —\nнет кадров, 1 с"
    assert calls == []


def test_no_displays_section_no_plate(wire) -> None:
    w = wire({"displays": [], "blueprint": {"displays": []}})
    calls = _spy_plate(w.panel, "main")
    silences = _spy_silence(w.pump)
    w.bridge.dispatch(_msg("lonely"))
    assert _spin_until(lambda: _shown(w.panel, "main") >= 1, 1.0), "кадр не показан"

    _spin(_QUIET_S)

    assert any(key == "lonely" and age is not None and age >= 2.0 for key, age in silences), silences
    assert calls == []


def test_silence_threshold_per_display(wire) -> None:
    w = wire(
        {
            "displays": [
                _display("d1", "Один", plate_mode="silence", plate_after_s=1),
                _display("d2", "Три", 10, plate_mode="silence", plate_after_s=3),
            ],
            "blueprint": {
                "displays": [
                    {"node_id": "s1.src.frame", "display_id": "d1"},
                    {"node_id": "s2.src.frame", "display_id": "d2"},
                ]
            },
        }
    )
    started = time.perf_counter()
    first = _spy_plate(w.panel, "d1")
    second = _spy_plate(w.panel, "d2")

    _spin(2.2 - (time.perf_counter() - started))
    assert first, "к 2,2 с плашки на d1 нет"
    assert second == [], f"плашка на d2 раньше 3 с: {second}"

    _spin(3.3 - (time.perf_counter() - started))
    assert second and second[0] == "Три · № — · —\nнет кадров, 3 с"
    assert "нет кадров" in _label(w.panel, "d1").text()


def _plate_entry(**keys: Any) -> dict:
    from multiprocess_prototype.frontend.widgets.image_panel.recipe_displays import build_plate_sources

    return build_plate_sources({"displays": [{"id": "fallback_d", **keys}]})["fallback_d"]


def test_bad_mode_and_after_fall_back() -> None:
    assert _plate_entry(plate_mode="silence")["mode"] == "silence"
    assert _plate_entry(plate_mode="trigger")["mode"] == "trigger"
    assert _plate_entry(plate_mode="blink")["mode"] == "hold"
    assert _plate_entry(plate_after_s=1)["after_s"] == 1
    assert _plate_entry(plate_after_s=600)["after_s"] == 600
    for bad in (0, 601, True, "5", 5.0):
        result = _plate_entry(plate_after_s=bad)["after_s"]
        assert result == 2 and type(result) is int, (bad, result)
    assert _plate_entry()["mode"] == "hold"
    assert _plate_entry()["after_s"] == 2


def test_bad_values_warn_once_without_value(caplog) -> None:
    from multiprocess_prototype.frontend.widgets.image_panel.recipe_displays import build_plate_sources

    recipe = {"displays": [{"id": "warn_d", "plate_mode": "blink_once"}]}
    with caplog.at_level(logging.WARNING):
        build_plate_sources(recipe)
        build_plate_sources(recipe)

    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(messages) == 1, messages
    assert "warn_d" in messages[0] and "plate_mode" in messages[0]
    assert "blink_once" not in messages[0]


def test_plate_wraps_and_unwraps(slot) -> None:
    long_text = "длинная строка плашки " * 5 + "конец наяву"
    label = slot._label  # noqa: SLF001
    exits = (slot.leave_no_signal, lambda: slot.update_pixmap(_pixmap()), lambda: slot.set_placeholder("Ошибка кадра"))
    for leave in exits:
        slot.show_no_signal(long_text)
        assert label.wordWrap() is True

        leave()

        assert label.wordWrap() is False


def test_plate_is_plain_text(slot) -> None:
    """Разметка в шаблоне не интерпретируется: перенос перед статусом остаётся, после плашки — как раньше."""
    label = slot._label  # noqa: SLF001
    label.setMinimumSize(0, 0)  # иначе heightForWidth зажат снизу высотой 240
    slot.show_no_signal("<b>Камера</b>\nнет кадров, 3 с")

    # на широкой метке две строки; при разметке перенос схлопнулся бы в одну
    assert label.heightForWidth(2000) >= 2 * label.fontMetrics().height()

    slot.leave_no_signal()
    assert label.textFormat() == Qt.TextFormat.AutoText


def test_rebuild_renames_existing_slot(wire) -> None:
    """Тот же id, новое название, режим hold: старое название не остаётся на слоте."""
    recipe = {
        "displays": [_display("d", "Камера А", **_SILENT)],
        "blueprint": {"displays": [{"node_id": "a.src.frame", "display_id": "d"}]},
    }
    w = wire(recipe)
    assert _spin_until(lambda: "нет кадров" in _label(w.panel, "d").text(), 3.0), "плашки нет"

    recipe["displays"] = [_display("d", "Камера Б")]
    w.fire()
    assert _label(w.panel, "d").text() == "Камера Б"
    assert _label(w.panel, "d").styleSheet() == ""

    recipe["displays"] = [_display("d", "Камера В")]  # плашки не было: меняется сам placeholder
    w.fire()
    assert _label(w.panel, "d").text() == "Камера В"
