# -*- coding: utf-8 -*-
"""W2-c2b: режим плашки на каждом экране, порог N с, перенос строки (слепые приёмочные тесты).

Purpose: контракт ``plans/2026-11-25_multicam-observability/tasks/W2-c2b.md`` и ``plate-modes.md``,
написан ДО реализации. Настоящие ``_setup_bridge_callbacks``, ``DataReceiverBridge``, ``FramePump``
и ``ImagePanelWidget``; рецепт — словарь; порог приложения не подменяется.

Ожидаемые значения — литералы. Ожидание — цикл событий Qt с дедлайном. У каждого теста свои
``display_id``: множество уже сказанных WARNING живёт на процесс (исключение — запасной ``main``).

Запуск (из корня worktree, PYTHONPATH=корень, PYTHONUTF8=1, Qt offscreen), класс ``light``.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402

__all__: list[str] = []

_QUIET_S = 2.5  # молчим дольше умолчания 2 с
_HANG_DEADLINE_S = 60.0  # pytest-timeout в venv нет: зависший тест снимает faulthandler


@pytest.fixture(autouse=True)
def _hang_deadline():
    faulthandler.dump_traceback_later(_HANG_DEADLINE_S, exit=True)
    yield
    faulthandler.cancel_dump_traceback_later()


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
    return {
        "id": display_id,
        "name": name,
        "enabled": True,
        "position": {"x": x, "y": 0},
        "fps_limit": 30.0,
        **plate,
    }


def _bind(sender: str, display_id: str) -> dict:
    return {"node_id": f"{sender}.src.frame", "display_id": display_id}


@pytest.fixture()
def wire(qtbot):
    """Фабрика проводки: настоящие мост, насос и панель; пороги берутся только из рецепта."""
    from multiprocess_prototype.frontend import app as app_module
    from multiprocess_prototype.frontend.bridge import DataReceiverBridge
    from multiprocess_prototype.frontend.frame_intake import FrameIntake
    from multiprocess_prototype.frontend.widgets.image_panel.widget import ImagePanelWidget

    pumps: list = []

    def _make(recipe: dict) -> SimpleNamespace:
        class _Recipes:
            def get_active(self) -> str:
                return "plate_blind"

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


def _spy_silence(pump: Any) -> list[tuple[str, float | None]]:
    """Что насос сообщил приложению: список (ключ, возраст тишины)."""
    original = pump._on_silence  # noqa: SLF001
    seen: list[tuple[str, float | None]] = []

    def spy(key: str, age_s: float | None) -> None:
        seen.append((key, age_s))
        original(key, age_s)

    pump._on_silence = spy  # noqa: SLF001
    return seen


def _label(panel: Any, slot_id: str) -> Any:
    return panel._slots[slot_id]._label  # noqa: SLF001


def _shown(panel: Any, slot_id: str) -> int:
    return panel.presenter.frame_stats(slot_id)["shown"]


# ---------------------------------------------------------------------------
# Режимы экрана через настоящий насос
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "plate"),
    [
        ("absent", {}),
        ("hold", {"plate_mode": "hold", "plate_after_s": 1}),
        ("trigger", {"plate_mode": "trigger", "plate_after_s": 1}),
        ("unknown", {"plate_mode": "blink", "plate_after_s": 1}),
    ],
)
def test_non_silence_mode_keeps_last_frame(wire, case: str, plate: dict) -> None:
    """Всё, кроме ``silence``: плашки нет, на экране последний кадр. Контроль ``c`` — ``silence``/1."""
    d, c = f"blind_mode_{case}_d", f"blind_mode_{case}_c"
    w = wire(
        {
            "displays": [
                _display(d, "Экран D", **plate),
                _display(c, "Контроль", 10, plate_mode="silence", plate_after_s=1),
            ],
            "blueprint": {"displays": [_bind("sd", d), _bind("sc", c)]},
        }
    )
    calls = _spy_plate(w.panel, d)
    control = _spy_plate(w.panel, c)
    silences = _spy_silence(w.pump)
    w.bridge.dispatch(_msg("sd"))
    assert _spin_until(lambda: _shown(w.panel, d) >= 1, 1.0), "кадр не показан"

    _spin(_QUIET_S)

    assert any(key == "sd" and age is not None and age >= 2.0 for key, age in silences), (
        f"тишина sd не дошла до 2 с: {silences}"
    )
    assert calls == [], f"плашка в режиме {case}: {calls}"
    assert control, "контроль silence/1 без плашки"
    assert control[0] == "Контроль · № — · —\nнет кадров, 1 с"
    assert not _label(w.panel, d).pixmap().isNull(), "последний кадр пропал с экрана"


def test_no_displays_section_no_plate(wire) -> None:
    """Запасной ``main`` без записи в рецепте — ``hold``."""
    w = wire({"displays": [], "blueprint": {"displays": []}})
    calls = _spy_plate(w.panel, "main")
    silences = _spy_silence(w.pump)
    w.bridge.dispatch(_msg("blind_lonely"))
    assert _spin_until(lambda: _shown(w.panel, "main") >= 1, 1.0), "кадр не показан"

    _spin(_QUIET_S)

    assert any(key == "blind_lonely" and age is not None and age >= 2.0 for key, age in silences), (
        f"тишина не дошла до 2 с: {silences}"
    )
    assert calls == [], f"плашка на экране без записи: {calls}"
    assert not _label(w.panel, "main").pixmap().isNull()


def test_silence_threshold_per_display(wire) -> None:
    """Кадров нет вовсе: ``d1`` с порогом 1 с, ``d2`` — 3 с."""
    d1, d2 = "blind_thr_d1", "blind_thr_d2"
    w = wire(
        {
            "displays": [
                _display(d1, "Один", plate_mode="silence", plate_after_s=1),
                _display(d2, "Три", 10, plate_mode="silence", plate_after_s=3),
            ],
            "blueprint": {"displays": [_bind("s1", d1), _bind("s2", d2)]},
        }
    )
    started = time.perf_counter()
    first = _spy_plate(w.panel, d1)
    second = _spy_plate(w.panel, d2)

    _spin(2.2 - (time.perf_counter() - started))

    assert first, "к 2,2 с плашки на d1 нет"
    assert first[0] == "Один · № — · —\nнет кадров, 1 с"
    assert second == [], f"плашка на d2 раньше 3 с: {second}"

    _spin(3.3 - (time.perf_counter() - started))

    assert second, "к 3,3 с плашки на d2 нет"
    assert second[0] == "Три · № — · —\nнет кадров, 3 с"
    assert "нет кадров" in _label(w.panel, d1).text()
    assert "нет кадров" in _label(w.panel, d2).text()


def test_silence_without_after_s_waits_two_seconds(wire) -> None:
    """``silence`` без ``plate_after_s``: порог 2 с, граница с обеих сторон (возраст подаёт тест)."""
    d = "blind_default_after_d"
    w = wire(
        {
            "displays": [_display(d, "Умолч", plate_mode="silence")],
            "blueprint": {"displays": [_bind("a", d)]},
        }
    )
    w.pump.stop()  # тишину сообщаем сами
    calls = _spy_plate(w.panel, d)

    w.pump._on_silence("a", 1.0)  # noqa: SLF001
    w.pump._on_silence("a", 1.99)  # noqa: SLF001
    assert calls == [], f"плашка раньше 2 с: {calls}"

    w.pump._on_silence("a", 2.0)  # noqa: SLF001
    assert calls == ["Умолч · № — · —\nнет кадров, 2 с"]


def test_threshold_applies_to_youngest_sender(wire) -> None:
    """Два отправителя на экране: порог считается по тому, кто молчит меньше всех."""
    d = "blind_youngest_d"
    w = wire(
        {
            "displays": [_display(d, "Двое", plate_mode="silence", plate_after_s=3)],
            "blueprint": {"displays": [_bind("a", d), _bind("b", d)]},
        }
    )
    w.pump.stop()
    calls = _spy_plate(w.panel, d)

    w.pump._on_silence("b", 10.0)  # noqa: SLF001
    w.pump._on_silence("a", 2.99)  # noqa: SLF001
    assert calls == [], f"плашка раньше, чем a домолчал до 3 с: {calls}"

    w.pump._on_silence("a", 3.0)  # noqa: SLF001
    assert calls == ["Двое · № — · —\nнет кадров, 3 с"]


def test_next_frame_removes_silence_plate(wire) -> None:
    d = "blind_return_d"
    w = wire(
        {
            "displays": [_display(d, "Возврат", plate_mode="silence", plate_after_s=1)],
            "blueprint": {"displays": [_bind("a", d)]},
        }
    )
    assert _spin_until(lambda: "нет кадров" in _label(w.panel, d).text(), 3.0), "плашки нет"

    w.bridge.dispatch(_msg("a"))

    assert _spin_until(lambda: not _label(w.panel, d).pixmap().isNull(), 1.0), "картинка не вернулась"
    assert _label(w.panel, d).styleSheet() == ""


def test_mode_change_to_hold_on_rebuild(wire) -> None:
    """Правка режима ``silence`` -> ``hold``: плашка снята и не возвращается; у контроля возвращается."""
    d, c = "blind_switch_d", "blind_switch_c"
    recipe = {
        "displays": [
            _display(d, "Смена", plate_mode="silence", plate_after_s=1),
            _display(c, "Контроль", 10, plate_mode="silence", plate_after_s=1),
        ],
        "blueprint": {"displays": [_bind("sd", d), _bind("sc", c)]},
    }
    w = wire(recipe)
    assert _spin_until(
        lambda: "нет кадров" in _label(w.panel, d).text() and "нет кадров" in _label(w.panel, c).text(), 3.0
    ), "плашек до правки нет"

    recipe["displays"][0]["plate_mode"] = "hold"
    w.fire()
    calls = _spy_plate(w.panel, d)
    control = _spy_plate(w.panel, c)
    _spin(_QUIET_S)

    assert control, "контроль после пересборки без плашки"
    assert calls == [], f"плашка после перевода в hold: {calls}"
    assert _label(w.panel, d).text() == "Смена"
    assert _label(w.panel, d).styleSheet() == ""


# ---------------------------------------------------------------------------
# build_plate_sources: mode / after_s и WARNING
# ---------------------------------------------------------------------------

_ABSENT = object()


def _entry(display_id: str, **keys: Any) -> dict:
    from multiprocess_prototype.frontend.widgets.image_panel.recipe_displays import build_plate_sources

    defn = {"id": display_id, **{k: v for k, v in keys.items() if v is not _ABSENT}}
    return build_plate_sources({"displays": [defn]})[display_id]


@pytest.mark.parametrize(
    ("case", "value", "expected"),
    [
        ("absent", _ABSENT, "hold"),
        ("hold", "hold", "hold"),
        ("silence", "silence", "silence"),
        ("trigger", "trigger", "trigger"),
        ("unknown", "blink", "hold"),
        ("upper", "SILENCE", "hold"),
        ("empty", "", "hold"),
        ("int", 1, "hold"),
        ("none", None, "hold"),
        ("list", ["silence"], "hold"),
        ("dict", {"silence": 1}, "hold"),
    ],
)
def test_plate_mode_parsing(case: str, value: Any, expected: str) -> None:
    assert _entry(f"blind_parse_mode_{case}", plate_mode=value)["mode"] == expected


@pytest.mark.parametrize(
    ("case", "value", "expected"),
    [
        ("absent", _ABSENT, 2),
        ("min", 1, 1),
        ("five", 5, 5),
        ("max", 600, 600),
        ("zero", 0, 2),
        ("negative", -1, 2),
        ("over", 601, 2),
        ("true", True, 2),
        ("false", False, 2),
        ("string", "5", 2),
        ("float", 5.0, 2),
        ("none", None, 2),
        ("list", [5], 2),
    ],
)
def test_plate_after_s_parsing(case: str, value: Any, expected: int) -> None:
    result = _entry(f"blind_parse_after_{case}", plate_after_s=value)["after_s"]

    assert result == expected
    assert type(result) is int


def _warnings(caplog: Any, display_id: str) -> list[str]:
    return [
        r.getMessage() for r in caplog.records if r.levelno == logging.WARNING and f"'{display_id}'" in r.getMessage()
    ]


@pytest.mark.parametrize(
    ("display_id", "key", "value", "leak"),
    [
        ("blind_warn_mode", "plate_mode", "blink_once", "blink_once"),
        ("blind_warn_after", "plate_after_s", 987654, "987654"),
    ],
)
def test_bad_value_warns_once_without_value(caplog, display_id: str, key: str, value: Any, leak: str) -> None:
    with caplog.at_level(logging.WARNING):
        _entry(display_id, **{key: value})
        _entry(display_id, **{key: value})

    messages = _warnings(caplog, display_id)
    assert len(messages) == 1, f"ожидали ровно одно WARNING: {messages}"
    assert key in messages[0]
    assert all(leak not in r.getMessage() for r in caplog.records), "значение из рецепта попало в лог"


def test_both_bad_keys_each_get_a_warning(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        _entry("blind_warn_both", plate_mode="blink_both", plate_after_s=0)

    messages = _warnings(caplog, "blind_warn_both")
    assert len(messages) == 2, f"по одному WARNING на ключ: {messages}"
    assert sum("plate_mode" in m for m in messages) == 1
    assert sum("plate_after_s" in m for m in messages) == 1


def test_warning_dedup_is_per_display_and_per_value(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        _entry("blind_dedup_one", plate_mode="bad_x")
        _entry("blind_dedup_two", plate_mode="bad_x")
        _entry("blind_dedup_one", plate_mode="bad_y")
        _entry("blind_dedup_one", plate_mode="bad_x")

    assert len(_warnings(caplog, "blind_dedup_one")) == 2
    assert len(_warnings(caplog, "blind_dedup_two")) == 1


def test_valid_and_absent_values_do_not_warn(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        _entry("blind_quiet_absent")
        _entry("blind_quiet_silence", plate_mode="silence", plate_after_s=1)
        _entry("blind_quiet_trigger", plate_mode="trigger", plate_after_s=600)
        _entry("blind_quiet_hold", plate_mode="hold")

    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []


# ---------------------------------------------------------------------------
# DisplaySlot: перенос строки
# ---------------------------------------------------------------------------

_LONG_TEXT = "camera line seven " * 6 + "end of plate"  # 120 символов с пробелами


def _pixmap() -> QPixmap:
    pixmap = QPixmap(64, 48)
    pixmap.fill(QColor("red"))
    return pixmap


@pytest.mark.parametrize("exit_name", ["leave_no_signal", "update_pixmap", "set_placeholder"])
def test_plate_wraps_and_every_exit_unwraps(qtbot, exit_name: str) -> None:
    from multiprocess_prototype.frontend.widgets.image_panel.display_slot import DisplaySlot

    slot = DisplaySlot(slot_id=f"blind_wrap_{exit_name}", label="Камера")
    qtbot.addWidget(slot)
    slot.show()
    QCoreApplication.processEvents()
    label = slot._label  # noqa: SLF001
    assert len(_LONG_TEXT) == 120

    slot.show_no_signal(_LONG_TEXT)

    assert label.wordWrap() is True
    # перенос виден по раскладке: на ширине 320 текст занимает не меньше двух строк;
    # минимум слота 320x240 маскирует высоту, поэтому перед замером он снимается
    label.setMinimumSize(0, 0)
    assert label.heightForWidth(320) >= 2 * label.fontMetrics().height()

    if exit_name == "leave_no_signal":
        slot.leave_no_signal()
        assert label.text() == "Камера"
    elif exit_name == "update_pixmap":
        slot.update_pixmap(_pixmap())
        assert not label.pixmap().isNull()
    else:
        slot.set_placeholder("Ошибка кадра")
        assert label.text() == "Ошибка кадра"

    assert label.wordWrap() is False
