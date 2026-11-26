"""Слепая приёмка задачи 2.6: признак «окно будет» (``backend.launch.presentation_window_expected``).

Написано до реализации по ``tasks/2.6.md`` (DESIGN п.1, REDS). Чистая функция над dict.
"""

from __future__ import annotations

_QT_GUI = "multiprocess_prototype.frontend.process.GuiProcess"
_HEADLESS_GUI = "multiprocess_prototype.frontend.headless_process.HeadlessGuiProcess"


def _topology(*processes):
    return {"processes": [{"process_name": name, "process_class": cls} for name, cls in processes]}


def test_predicate_literals():
    from multiprocess_prototype.backend.launch import presentation_window_expected

    assert presentation_window_expected(_topology(("gui", _QT_GUI))) is True
    assert presentation_window_expected(_topology(("camera_0", "x.Camera"), ("gui", _QT_GUI))) is True

    assert presentation_window_expected(_topology(("gui", _HEADLESS_GUI))) is False
    assert presentation_window_expected(_topology(("camera_0", "x.Camera"))) is False
    assert presentation_window_expected(_topology(("not_gui", _QT_GUI))) is False
    assert presentation_window_expected({}) is False
    assert presentation_window_expected({"processes": None}) is False
