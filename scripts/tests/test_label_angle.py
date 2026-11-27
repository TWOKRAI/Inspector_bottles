"""Тесты автора на опасные места ``scripts/label_angle.py`` (то, чего нет в слепой приёмке)."""

from __future__ import annotations

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import unicodedata
from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from scripts import label_angle as la


def _frame(path: Path, value: int = 90) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", np.full((48, 64, 3), value, dtype=np.uint8))
    assert ok
    buf.tofile(str(path))
    return path.read_bytes()


def _names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def _view(window):
    """Картинка, что сейчас на экране."""
    shown = [w.pixmap() for w in window.findChildren(QLabel) if not w.pixmap().isNull()]
    assert len(shown) == 1
    return shown[0].toImage()


def test_old_copy_cannot_be_removed(qtbot, tmp_path, monkeypatch):
    """Новая копия уже записана, а прежняя не удаляется: громко, ничего не потеряно, повтор доводит до конца."""
    raw, out = tmp_path / "raw", tmp_path / "out"
    data = _frame(raw / "П" / "a000_000001.png")
    (out / "П").mkdir(parents=True)
    (out / "П" / "a010_000001.png").write_bytes(data)
    window = la.LabelWindow(raw, out)
    qtbot.addWidget(window)
    QTest.keyClick(window, Qt.Key.Key_Backspace)

    real_unlink = Path.unlink

    def locked(self, *args, **kwargs):
        if self.name == "a010_000001.png":
            raise PermissionError("файл занят")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked)
    window.set_turn(-45)
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert window.current.index == "000001"
    assert any("НЕ ЗАПИСАНО" in w.text() for w in window.findChildren(QLabel))
    assert _names(out / "П") == ["a010_000001.png", "a045_000001.png"]
    with pytest.raises(ValueError, match="две копии"):  # следующий запуск не угадывает, какая верная
        la.scan(raw, out)

    monkeypatch.setattr(Path, "unlink", real_unlink)
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert _names(out / "П") == ["a045_000001.png"]


def test_own_copy_differing_only_by_case_is_not_deleted(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    data = _frame(raw / "П" / "a000_000001.png")
    (out / "П").mkdir(parents=True)
    (out / "П" / "a045_000001.PNG").write_bytes(data)  # на Windows это тот же файл, что и a045_000001.png
    la.save_label(la.scan(raw, out)[0], out, 45)
    left = list((out / "П").iterdir())
    assert len(left) == 1 and left[0].read_bytes() == data


def test_guide_lines_are_on_screen_only(qtbot, tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    data = _frame(raw / "П" / "a000_000001.png")
    window = la.LabelWindow(raw, out)
    qtbot.addWidget(window)
    window.set_turn(30)  # прямые не поворачиваются вместе с картинкой
    image = _view(window)
    middle = la.VIEW_SIZE // 2
    for x, y in ((middle, 5), (5, middle)):
        assert image.pixelColor(x, y).getRgb()[:3] == (230, 30, 30)
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert (out / "П" / "a330_000001.png").read_bytes() == data
    assert (raw / "П" / "a000_000001.png").read_bytes() == data


def test_crop_failure_does_not_leave_previous_picture(qtbot, tmp_path, monkeypatch):
    """Плагин упал на кадре: на экране должен быть ЭТОТ кадр целиком, а не картинка предыдущего."""
    raw, out = tmp_path / "raw", tmp_path / "out"
    _frame(raw / "П" / "a000_000001.png", value=40)
    _frame(raw / "П" / "a000_000002.png", value=200)

    def crop(self, frame):
        if frame[0, 0, 0] == 200:
            raise RuntimeError("плагин упал")
        return np.full((128, 128, 3), 40, dtype=np.uint8)

    monkeypatch.setattr(la.RecipePipeline, "crop", crop)
    window = la.LabelWindow(raw, out, la.DEFAULT_RECIPE)
    qtbot.addWidget(window)
    QTest.keyClick(window, Qt.Key.Key_S)
    assert window.current.index == "000002"
    assert _view(window).pixelColor(la.VIEW_SIZE // 2 + 20, la.VIEW_SIZE // 2 + 20).red() == 200
    assert any("плагин упал" in w.text() for w in window.findChildren(QLabel))


@pytest.mark.parametrize("case", ["two-letter-folder", "nfd-folder-in-out", "out-is-a-file", "swapped-folders"])
def test_scan_refuses_odd_inputs(tmp_path, case):
    raw, out = tmp_path / "raw", tmp_path / "out"
    data = _frame(raw / "Й" / "a000_000001.png")
    _frame(raw / "Й" / "a000_000002.png", value=120)
    if case == "two-letter-folder":
        _frame(raw / "ЙЙ" / "a000_000001.png")
    elif case == "nfd-folder-in-out":  # save_label такую папку не увидел бы и сделал вторую копию
        folder = out / unicodedata.normalize("NFD", "Й")
        folder.mkdir(parents=True)
        (folder / "a045_000001.png").write_bytes(data)
    elif case == "out-is-a-file":
        out.write_bytes(b"x")
    else:  # размечен один кадр из двух, папки в команде перепутаны местами
        (out / "Й").mkdir(parents=True)
        (out / "Й" / "a045_000001.png").write_bytes(data)
        raw, out = out, raw
    with pytest.raises(ValueError):
        la.scan(raw, out)
