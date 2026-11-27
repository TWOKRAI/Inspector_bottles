"""Слепая приёмка РУ-1 (plans/layer-render/task-label-angle.md): ``scripts/label_angle.py``.

Тесты написаны ДО реализации по разделам «Данные», «DESIGN» и «REDS» 1-9 задания. Автор реализации файл не правит.
Ожидаемые значения — литералы. Проверяется наблюдаемое: файлы и их байты, состояние окна, код выхода, stderr/stdout.
Импорт модуля — внутри помощника ``_la()``, чтобы каждый тест падал сам за себя.
Номер REDS указан в заголовке раздела.
"""

from __future__ import annotations

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import subprocess
import sys
import unicodedata
from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QImage, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSlider,
    QStatusBar,
    QTextEdit,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "label_angle.py"
RECIPE = REPO_ROOT / "multiprocess_prototype" / "recipes" / "hikvision_letter_robot.yaml"

MAGENTA_BGR = (255, 0, 255)


def _la():
    from scripts import label_angle

    return label_angle


# --------------------------------------------------------------------------- #
# Помощники: синтетические файлы                                              #
# --------------------------------------------------------------------------- #


def _write_image(path: Path, image: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(path.suffix.lower(), image)
    assert ok, f"cv2 не кодирует {path.suffix}"
    buf.tofile(str(path))
    return path


def _noise(seed: int, height: int = 48, width: int = 64) -> np.ndarray:
    """Уникальный по seed кадр: разные seed дают разные байты файла."""
    return np.random.default_rng(seed).integers(40, 220, size=(height, width, 3), dtype=np.uint8)


def _frame(raw: Path, letter: str, name: str, seed: int) -> Path:
    return _write_image(raw / letter / name, _noise(seed))


def _put(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _files(root: Path) -> dict[str, bytes]:
    """{относительный posix-путь: байты} всех файлов под root; нет root — пусто."""
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _disc_frame() -> np.ndarray:
    """Полный кадр 1440x1080: белый диск в ROI боевого рецепта, пурпурная метка у верхнего края диска."""
    img = np.full((1080, 1440, 3), 40, dtype=np.uint8)
    cv2.circle(img, (646, 537), 130, (235, 235, 235), thickness=-1)
    cv2.rectangle(img, (621, 447), (671, 487), MAGENTA_BGR, thickness=-1)
    return img


def _black_frame() -> np.ndarray:
    return np.full((1080, 1440, 3), 10, dtype=np.uint8)


def _marker_frame(x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    """Квадратный кадр 800x800 с пурпурным прямоугольником."""
    img = np.full((800, 800, 3), 70, dtype=np.uint8)
    cv2.rectangle(img, (x0, y0), (x1, y1), MAGENTA_BGR, thickness=-1)
    return img


# --------------------------------------------------------------------------- #
# Помощники: окно                                                             #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _no_hang_and_cleanup(qapp):
    """Модальный диалог не должен вешать прогон; после теста не остаётся видимых окон (иначе exec() не выйдет)."""

    def close_modal():
        modal = QApplication.activeModalWidget()
        if modal is not None:
            modal.close()

    timer = QTimer()
    timer.setInterval(200)
    timer.timeout.connect(close_modal)
    timer.start()
    yield
    timer.stop()
    for widget in QApplication.topLevelWidgets():
        widget.close()
    qapp.processEvents()


def _open(qtbot, raw: Path, out: Path, recipe: Path | None = None):
    window = _la().LabelWindow(raw, out, recipe)
    qtbot.addWidget(window)
    return window


def _press(window, key) -> None:
    QTest.keyClick(window, key)


def _send_key(window, key, text: str, autorep: bool = False) -> None:
    event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text, autorep)
    QApplication.sendEvent(window, event)


def _text(window) -> str:
    """Весь видимый текст окна, в нижнем регистре."""
    parts = [w.text() for w in window.findChildren(QLabel)]
    parts += [w.text() for w in window.findChildren(QLineEdit)]
    parts += [w.toPlainText() for w in window.findChildren(QPlainTextEdit)]
    parts += [w.toPlainText() for w in window.findChildren(QTextEdit)]
    parts += [w.currentMessage() for w in window.findChildren(QStatusBar)]
    return "\n".join(parts).lower()


def _index(window) -> str | None:
    current = window.current
    return None if current is None else current.index


def _magenta(window) -> tuple[int, float, float]:
    """(число пурпурных пикселей в снимке окна, центр x, центр y)."""
    QApplication.processEvents()
    image = window.grab().toImage().convertToFormat(QImage.Format.Format_RGB888)
    height, width, stride = image.height(), image.width(), image.bytesPerLine()
    flat = np.frombuffer(image.constBits(), dtype=np.uint8, count=height * stride)
    rgb = flat.reshape(height, stride)[:, : width * 3].reshape(height, width, 3)
    mask = (rgb[:, :, 0] > 180) & (rgb[:, :, 1] < 80) & (rgb[:, :, 2] > 180)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return 0, float("nan"), float("nan")
    return int(len(xs)), float(xs.mean()), float(ys.mean())


def _three_frames(tmp_path: Path) -> tuple[Path, Path]:
    raw, out = tmp_path / "raw", tmp_path / "out"
    for number in (1, 2, 3):
        _frame(raw, "П", f"a000_{number:06d}.png", seed=number)
    return raw, out


# --------------------------------------------------------------------------- #
# REDS 1: truth_angle                                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("turn", "angle"),
    [(0, 0), (90, 270), (-90, 90), (180, 180), (-180, 180), (1, 359), (360, 0), (450, 270)],
)
def test_truth_angle(turn, angle):
    assert _la().truth_angle(turn) == angle


# --------------------------------------------------------------------------- #
# REDS 2: rotate_view                                                         #
# --------------------------------------------------------------------------- #


def _top_marker() -> np.ndarray:
    img = np.zeros((101, 101, 3), dtype=np.uint8)
    img[5:16, 45:56] = 255  # середина верхнего края: центр (x=50, y=10)
    return img


def _bright_center(img: np.ndarray) -> tuple[float, float]:
    ys, xs = np.nonzero(img[:, :, 0] > 127)
    assert len(xs) > 50, "метка пропала после поворота"
    return float(xs.mean()), float(ys.mean())


@pytest.mark.parametrize(
    ("turn", "x", "y"),
    [
        (0, 50, 10),
        (90, 10, 50),  # против часовой: верх уходит влево
        (-90, 90, 50),
        (180, 50, 90),
        (45, 21.7, 21.7),  # 50 - 40*sin45
    ],
)
def test_rotate_view_moves_marker_counterclockwise(turn, x, y):
    rotated = _la().rotate_view(_top_marker(), turn)
    cx, cy = _bright_center(rotated)
    assert cx == pytest.approx(x, abs=2.0)
    assert cy == pytest.approx(y, abs=2.0)


@pytest.mark.parametrize("turn", [0, 37, 90, -90, 180])
def test_rotate_view_keeps_size_of_non_square_image(turn):
    image = np.zeros((80, 120, 3), dtype=np.uint8)
    assert _la().rotate_view(image, turn).shape == (80, 120, 3)


def test_letter_turned_90_ccw_is_labelled_90():
    """Сквозная конвенция знака: буква повёрнута на 90 против часовой -> доворот -90 ставит прямо -> угол 90."""
    la = _la()
    turned = np.zeros((101, 101, 3), dtype=np.uint8)
    turned[45:56, 5:16] = 255  # «верх» буквы смотрит влево
    cx, cy = _bright_center(la.rotate_view(turned, -90))
    assert (cx, cy) == (pytest.approx(50, abs=2.0), pytest.approx(10, abs=2.0))
    assert la.truth_angle(-90) == 90


# --------------------------------------------------------------------------- #
# REDS 3: scan                                                                #
# --------------------------------------------------------------------------- #


def test_scan_orders_by_letter_then_number_as_number(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    _frame(raw, "Р", "a000_1.png", seed=1)
    _frame(raw, "П", "a000_10.png", seed=2)
    _frame(raw, "П", "a000_2.png", seed=3)
    frames = _la().scan(raw, out)
    assert [(f.letter, f.index) for f in frames] == [("П", "2"), ("П", "10"), ("Р", "1")]


def test_scan_returns_raw_frame_fields(tmp_path):
    raw = tmp_path / "raw"
    path = _frame(raw, "П", "a123_000007.png", seed=1)  # цифры <ddd> во входе ничего не значат
    frames = _la().scan(raw, tmp_path / "out")
    assert len(frames) == 1
    assert isinstance(frames[0], _la().RawFrame)
    assert frames[0].path == path
    assert frames[0].letter == "П"
    assert frames[0].index == "000007"
    assert frames[0].angle is None


def test_raw_frame_is_frozen(tmp_path):
    raw = tmp_path / "raw"
    _frame(raw, "П", "a000_000001.png", seed=1)
    frame = _la().scan(raw, tmp_path / "out")[0]
    with pytest.raises(AttributeError):  # FrozenInstanceError — наследник AttributeError
        frame.angle = 5


def test_scan_accepts_every_listed_extension_and_ignores_non_images(tmp_path):
    raw = tmp_path / "raw"
    suffixes = ["png", "jpg", "jpeg", "bmp", "tif", "tiff", "webp"]
    for number, suffix in enumerate(suffixes, start=1):
        _frame(raw, "П", f"a000_{number}.{suffix}", seed=number)
    _put(raw / "П" / "notes.txt", b"not an image")
    frames = _la().scan(raw, tmp_path / "out")
    assert [f.path.suffix for f in frames] == [".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"]


def test_scan_letter_is_nfc(tmp_path):
    raw = tmp_path / "raw"
    _frame(raw, unicodedata.normalize("NFD", "Й"), "a000_000001.png", seed=1)
    assert _la().scan(raw, tmp_path / "out")[0].letter == "Й"


def test_scan_does_not_create_missing_out_dir(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    _frame(raw, "П", "a000_000001.png", seed=1)
    frames = _la().scan(raw, out)
    assert [f.angle for f in frames] == [None]
    assert not out.exists()


def test_scan_reads_angle_from_existing_copy(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    source = _frame(raw, "П", "a000_000001.png", seed=1)
    _frame(raw, "П", "a000_000002.png", seed=2)
    _put(out / "П" / "a045_000001.png", source.read_bytes())
    assert [(f.index, f.angle) for f in _la().scan(raw, out)] == [("000001", 45), ("000002", None)]


def test_scan_matches_copy_by_number_value(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    source = _frame(raw, "П", "a000_000007.png", seed=1)
    _put(out / "П" / "a045_7.png", source.read_bytes())
    assert [f.angle for f in _la().scan(raw, out)] == [45]


def test_scan_ignores_tmp_files_in_out(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    _frame(raw, "П", "a000_000001.png", seed=1)
    _put(out / "П" / "a045_000001.png.tmp", b"half written")
    assert [f.angle for f in _la().scan(raw, out)] == [None]


def test_scan_same_number_in_two_letters_is_allowed(tmp_path):
    raw = tmp_path / "raw"
    _frame(raw, "П", "a000_000001.png", seed=1)
    _frame(raw, "Р", "a000_000001.png", seed=2)
    assert len(_la().scan(raw, tmp_path / "out")) == 2


def test_scan_rejects_missing_raw_dir(tmp_path):
    la = _la()
    with pytest.raises(ValueError):
        la.scan(tmp_path / "нет", tmp_path / "out")


def test_scan_rejects_raw_dir_without_images(tmp_path):
    la = _la()
    _put(tmp_path / "raw" / "П" / "notes.txt", b"x")
    with pytest.raises(ValueError):
        la.scan(tmp_path / "raw", tmp_path / "out")


@pytest.mark.parametrize(
    "relative",
    ["П/photo.png", "a000_000009.png", "П/deeper/a000_000009.png", "П/a00_000009.png"],
    ids=["bad-name", "no-letter-folder", "too-deep", "two-digits"],
)
def test_scan_rejects_input_image_off_scheme(tmp_path, relative):
    la = _la()
    raw = tmp_path / "raw"
    _frame(raw, "П", "a000_000001.png", seed=1)
    bad = _write_image(raw / relative, _noise(9))
    with pytest.raises(ValueError) as info:
        la.scan(raw, tmp_path / "out")
    assert bad.name in str(info.value)


@pytest.mark.parametrize(
    ("first", "second"),
    [("a000_000001.png", "a090_000001.jpg"), ("a000_1.png", "a000_001.png")],
    ids=["same-digits", "same-value"],
)
def test_scan_rejects_two_inputs_with_one_number(tmp_path, first, second):
    la = _la()
    raw = tmp_path / "raw"
    _frame(raw, "П", first, seed=1)
    _frame(raw, "П", second, seed=2)
    with pytest.raises(ValueError) as info:
        la.scan(raw, tmp_path / "out")
    assert first in str(info.value)
    assert second in str(info.value)


@pytest.mark.parametrize("relation", ["equal", "inside", "contains"])
def test_scan_rejects_out_dir_overlapping_raw(tmp_path, relation):
    la = _la()
    raw = tmp_path / "base" / "raw"
    _frame(raw, "П", "a000_000001.png", seed=1)
    out = {"equal": raw, "inside": raw / "out", "contains": tmp_path / "base"}[relation]
    with pytest.raises(ValueError):
        la.scan(raw, out)


def test_scan_rejects_copy_with_different_content(tmp_path):
    la = _la()
    raw, out = tmp_path / "raw", tmp_path / "out"
    _frame(raw, "П", "a000_000001.png", seed=1)
    _put(out / "П" / "a045_000001.png", b"someone else's bytes")
    with pytest.raises(ValueError) as info:
        la.scan(raw, out)
    assert "a045_000001.png" in str(info.value)


def test_scan_rejects_two_copies_of_one_number(tmp_path):
    la = _la()
    raw, out = tmp_path / "raw", tmp_path / "out"
    source = _frame(raw, "П", "a000_000001.png", seed=1)
    _put(out / "П" / "a045_000001.png", source.read_bytes())
    _put(out / "П" / "a090_000001.png", source.read_bytes())
    with pytest.raises(ValueError) as info:
        la.scan(raw, out)
    assert "a045_000001.png" in str(info.value)
    assert "a090_000001.png" in str(info.value)


@pytest.mark.parametrize(
    "relative",
    [
        "П/photo.png",  # не по схеме
        "a045_000001.png",  # не по схеме: без папки буквы
        "П/a045_000099.png",  # нет входного кадра с этим номером
        "Р/a045_000001.png",  # кадр перенесли в другую букву
    ],
    ids=["bad-name", "no-letter-folder", "no-input-number", "other-letter"],
)
def test_scan_rejects_stray_image_in_out(tmp_path, relative):
    la = _la()
    raw, out = tmp_path / "raw", tmp_path / "out"
    source = _frame(raw, "П", "a000_000001.png", seed=1)
    stray = _put(out / relative, source.read_bytes())
    with pytest.raises(ValueError) as info:
        la.scan(raw, out)
    assert stray.name in str(info.value)


# --------------------------------------------------------------------------- #
# REDS 4: save_label                                                          #
# --------------------------------------------------------------------------- #


def _one_frame(tmp_path: Path, name: str = "a000_000007.png"):
    raw, out = tmp_path / "raw", tmp_path / "out"
    source = _frame(raw, "П", name, seed=7)
    return _la().scan(raw, out)[0], source, out


def test_save_label_writes_byte_copy_and_keeps_input(tmp_path):
    frame, source, out = _one_frame(tmp_path)
    original = source.read_bytes()
    result = _la().save_label(frame, out, 45)
    assert result == out / "П" / "a045_000007.png"
    assert _files(out) == {"П/a045_000007.png": original}
    assert _files(tmp_path / "raw") == {"П/a000_000007.png": original}


@pytest.mark.parametrize(
    ("angle", "name"),
    [(405, "a045_000007.png"), (-90, "a270_000007.png"), (360, "a000_000007.png"), (5, "a005_000007.png")],
)
def test_save_label_names_by_angle_modulo_360(tmp_path, angle, name):
    frame, _, out = _one_frame(tmp_path)
    _la().save_label(frame, out, angle)
    assert list(_files(out)) == [f"П/{name}"]


@pytest.mark.parametrize("name", ["a000_000007.jpg", "a000_000007.JPG", "a000_000007.tiff"])
def test_save_label_keeps_extension(tmp_path, name):
    frame, source, out = _one_frame(tmp_path, name)
    _la().save_label(frame, out, 45)
    assert _files(out) == {f"П/a045_{name.split('_')[1]}": source.read_bytes()}


def test_save_label_relabel_leaves_one_file_per_number(tmp_path):
    frame, source, out = _one_frame(tmp_path)
    la = _la()
    la.save_label(frame, out, 45)
    la.save_label(frame, out, 90)
    assert _files(out) == {"П/a090_000007.png": source.read_bytes()}


def test_save_label_same_angle_twice_keeps_the_file(tmp_path):
    frame, source, out = _one_frame(tmp_path)
    la = _la()
    la.save_label(frame, out, 45)
    la.save_label(frame, out, 45)
    assert _files(out) == {"П/a045_000007.png": source.read_bytes()}


def test_save_label_removes_own_copy_with_other_padding(tmp_path):
    frame, source, out = _one_frame(tmp_path)
    _put(out / "П" / "a010_7.png", source.read_bytes())
    _la().save_label(frame, out, 45)
    assert _files(out) == {"П/a045_000007.png": source.read_bytes()}


def test_save_label_does_not_touch_other_numbers(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    one = _frame(raw, "П", "a000_000001.png", seed=1)
    eleven = _frame(raw, "П", "a000_000011.png", seed=11)
    other = _frame(raw, "Р", "a000_000001.png", seed=21)
    _put(out / "П" / "a045_000011.png", eleven.read_bytes())
    _put(out / "Р" / "a045_000001.png", other.read_bytes())
    la = _la()
    frame = next(f for f in la.scan(raw, out) if f.path == one)
    la.save_label(frame, out, 90)
    assert _files(out) == {
        "П/a045_000011.png": eleven.read_bytes(),
        "П/a090_000001.png": one.read_bytes(),
        "Р/a045_000001.png": other.read_bytes(),
    }


@pytest.mark.parametrize("foreign", ["a045_000007.png", "a090_000007.png"], ids=["target-name", "other-angle"])
def test_save_label_refuses_foreign_file_under_number(tmp_path, foreign):
    frame, source, out = _one_frame(tmp_path)
    la = _la()
    _put(out / "П" / foreign, b"foreign bytes")
    with pytest.raises(FileExistsError):
        la.save_label(frame, out, 45)
    assert _files(out) == {f"П/{foreign}": b"foreign bytes"}
    assert source.exists()


def test_save_label_failed_replace_leaves_nothing_under_target(tmp_path, monkeypatch):
    frame, source, out = _one_frame(tmp_path)
    la = _la()
    la.save_label(frame, out, 10)

    def boom(*args, **kwargs):
        raise OSError("injected")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="injected"):
        la.save_label(frame, out, 45)
    assert not (out / "П" / "a045_000007.png").exists()
    assert (out / "П" / "a010_000007.png").read_bytes() == source.read_bytes()


# --------------------------------------------------------------------------- #
# REDS 5: связка с letters_baseline.scan_dir                                  #
# --------------------------------------------------------------------------- #


def _read_by_baseline(out: Path) -> list[tuple[str, int]]:
    from scripts import letters_baseline

    frames, skipped = letters_baseline.scan_dir(out)
    assert skipped == []
    return [(f.letter, f.angle) for f in frames]


def test_baseline_reads_saved_label(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    _frame(raw, "П", "a000_000001.png", seed=1)
    la = _la()
    la.save_label(la.scan(raw, out)[0], out, la.truth_angle(-90))
    assert _read_by_baseline(out) == [("П", 90)]


def test_baseline_reads_label_made_in_window(qtbot, tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    _frame(raw, "П", "a000_000001.png", seed=1)
    window = _open(qtbot, raw, out)
    window.set_turn(-90)
    _press(window, Qt.Key.Key_Return)
    assert _read_by_baseline(out) == [("П", 90)]


# --------------------------------------------------------------------------- #
# REDS 6: окно                                                                #
# --------------------------------------------------------------------------- #


def test_window_opens_on_first_unlabelled(qtbot, tmp_path):
    raw, out = _three_frames(tmp_path)
    _put(out / "П" / "a045_000001.png", (raw / "П" / "a000_000001.png").read_bytes())
    window = _open(qtbot, raw, out)
    assert _index(window) == "000002"
    assert window.turn_deg == 0


def test_window_with_all_labelled_has_no_current(qtbot, tmp_path):
    raw, out = _three_frames(tmp_path)
    for number in (1, 2, 3):
        _put(out / "П" / f"a045_{number:06d}.png", (raw / "П" / f"a000_{number:06d}.png").read_bytes())
    window = _open(qtbot, raw, out)
    assert window.current is None


@pytest.mark.parametrize(
    ("key", "turn"),
    [(Qt.Key.Key_Left, 21), (Qt.Key.Key_Right, 19), (Qt.Key.Key_Up, 30), (Qt.Key.Key_Down, 10)],
    ids=["left", "right", "up", "down"],
)
def test_window_arrow_keys(qtbot, tmp_path, key, turn):
    raw, out = _three_frames(tmp_path)
    window = _open(qtbot, raw, out)
    window.set_turn(20)
    _press(window, key)
    assert window.turn_deg == turn
    assert _files(out) == {}


@pytest.mark.parametrize(
    ("value", "expected"),
    [(270, -90), (-180, 180), (180, 180), (360, 0), (540, 180), (-181, 179), (181, -179), (-90, -90)],
)
def test_window_set_turn_wraps(qtbot, tmp_path, value, expected):
    raw, out = _three_frames(tmp_path)
    window = _open(qtbot, raw, out)
    window.set_turn(value)
    assert window.turn_deg == expected


@pytest.mark.parametrize(
    ("start", "key", "expected"),
    [
        (180, Qt.Key.Key_Left, -179),
        (-179, Qt.Key.Key_Right, 180),
        (175, Qt.Key.Key_Up, -175),
        (-175, Qt.Key.Key_Down, 175),
    ],
    ids=["left-over", "right-over", "up-over", "down-over"],
)
def test_window_keys_wrap(qtbot, tmp_path, start, key, expected):
    raw, out = _three_frames(tmp_path)
    window = _open(qtbot, raw, out)
    window.set_turn(start)
    _press(window, key)
    assert window.turn_deg == expected


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter], ids=["return", "enter"])
@pytest.mark.parametrize(("turn", "name"), [(-90, "a090_000001.png"), (30, "a330_000001.png"), (0, "a000_000001.png")])
def test_window_enter_writes_copy_and_advances(qtbot, tmp_path, key, turn, name):
    raw, out = _three_frames(tmp_path)
    window = _open(qtbot, raw, out)
    window.set_turn(turn)
    _press(window, key)
    assert _files(out) == {f"П/{name}": (raw / "П" / "a000_000001.png").read_bytes()}
    assert _index(window) == "000002"


def test_window_enter_goes_to_next_in_order_even_if_labelled(qtbot, tmp_path):
    raw, out = _three_frames(tmp_path)
    _put(out / "П" / "a045_000002.png", (raw / "П" / "a000_000002.png").read_bytes())
    window = _open(qtbot, raw, out)
    _press(window, Qt.Key.Key_Return)
    assert _index(window) == "000002"
    assert window.turn_deg == -45


@pytest.mark.parametrize("how", ["s", "ы", "Ы"])
def test_window_skip_writes_nothing(qtbot, tmp_path, how):
    raw, out = _three_frames(tmp_path)
    window = _open(qtbot, raw, out)
    if how == "s":
        _press(window, Qt.Key.Key_S)
    else:
        _send_key(window, 0x042B, how)
    assert _index(window) == "000002"
    assert _files(out) == {}


@pytest.mark.parametrize(("angle", "turn"), [(45, -45), (270, 90), (180, 180), (0, 0)])
def test_window_turn_of_labelled_frame_comes_from_its_angle(qtbot, tmp_path, angle, turn):
    raw, out = _three_frames(tmp_path)
    _put(out / "П" / f"a{angle:03d}_000001.png", (raw / "П" / "a000_000001.png").read_bytes())
    window = _open(qtbot, raw, out)
    window.set_turn(33)
    _press(window, Qt.Key.Key_Backspace)
    assert _index(window) == "000001"
    assert window.turn_deg == turn


def test_window_turn_is_kept_for_next_frame_of_same_letter(qtbot, tmp_path):
    raw, out = _three_frames(tmp_path)
    window = _open(qtbot, raw, out)
    window.set_turn(30)
    _press(window, Qt.Key.Key_Return)
    assert (_index(window), window.turn_deg) == ("000002", 30)
    window.set_turn(-12)
    _press(window, Qt.Key.Key_S)
    assert (_index(window), window.turn_deg) == ("000003", -12)


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_S], ids=["enter", "skip"])
def test_window_turn_is_reset_for_new_letter(qtbot, tmp_path, key):
    raw, out = tmp_path / "raw", tmp_path / "out"
    _frame(raw, "П", "a000_000001.png", seed=1)
    _frame(raw, "Р", "a000_000002.png", seed=2)
    window = _open(qtbot, raw, out)
    window.set_turn(30)
    _press(window, key)
    assert window.current.letter == "Р"
    assert window.turn_deg == 0


def test_window_return_to_frame_labelled_in_this_session_restores_its_turn(qtbot, tmp_path):
    raw, out = _three_frames(tmp_path)
    window = _open(qtbot, raw, out)
    window.set_turn(-90)
    _press(window, Qt.Key.Key_Return)
    window.set_turn(30)
    _press(window, Qt.Key.Key_Backspace)
    assert (_index(window), window.turn_deg) == ("000001", -90)


def test_window_backspace_then_enter_leaves_one_file(qtbot, tmp_path):
    raw, out = _three_frames(tmp_path)
    window = _open(qtbot, raw, out)
    window.set_turn(-90)
    _press(window, Qt.Key.Key_Return)
    _press(window, Qt.Key.Key_Backspace)
    window.set_turn(-45)
    _press(window, Qt.Key.Key_Return)
    assert _files(out) == {"П/a045_000001.png": (raw / "П" / "a000_000001.png").read_bytes()}
    assert _index(window) == "000002"


def test_window_after_last_frame(qtbot, tmp_path):
    raw, out = _three_frames(tmp_path)
    window = _open(qtbot, raw, out)
    for _ in range(3):
        _press(window, Qt.Key.Key_Return)
    assert window.current is None
    written = _files(out)
    assert sorted(written) == ["П/a000_000001.png", "П/a000_000002.png", "П/a000_000003.png"]
    window.set_turn(40)
    _press(window, Qt.Key.Key_Return)
    _press(window, Qt.Key.Key_Enter)
    _press(window, Qt.Key.Key_S)
    assert window.current is None
    assert _files(out) == written
    _press(window, Qt.Key.Key_Backspace)
    assert _index(window) == "000003"


def test_window_backspace_with_all_labelled_opens_last(qtbot, tmp_path):
    raw, out = _three_frames(tmp_path)
    for number in (1, 2, 3):
        _put(out / "П" / f"a045_{number:06d}.png", (raw / "П" / f"a000_{number:06d}.png").read_bytes())
    window = _open(qtbot, raw, out)
    _press(window, Qt.Key.Key_Backspace)
    assert (_index(window), window.turn_deg) == ("000003", -45)


def test_window_backspace_on_first_frame_stays(qtbot, tmp_path):
    raw, out = _three_frames(tmp_path)
    window = _open(qtbot, raw, out)
    _press(window, Qt.Key.Key_Backspace)
    assert _index(window) == "000001"
    assert _files(out) == {}


def test_window_reopen_continues_from_unlabelled(qtbot, tmp_path):
    raw, out = _three_frames(tmp_path)
    first = _open(qtbot, raw, out)
    _press(first, Qt.Key.Key_Return)
    first.close()
    second = _open(qtbot, raw, out)
    assert _index(second) == "000002"


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter], ids=["return", "enter"])
def test_window_ignores_autorepeat_enter(qtbot, tmp_path, key):
    raw, out = _three_frames(tmp_path)
    window = _open(qtbot, raw, out)
    _send_key(window, key, "\r", autorep=True)
    assert _index(window) == "000001"
    assert _files(out) == {}
    # контроль: то же событие без автоповтора записывает
    _send_key(window, key, "\r", autorep=False)
    assert _index(window) == "000002"
    assert list(_files(out)) == ["П/a000_000001.png"]


def test_window_escape_closes(qtbot, tmp_path):
    raw, out = _three_frames(tmp_path)
    window = _open(qtbot, raw, out)
    window.show()
    assert window.isVisible()
    _press(window, Qt.Key.Key_Escape)
    assert not window.isVisible()
    assert _files(out) == {}


@pytest.mark.parametrize("target", ["window", "slider"])
def test_window_keys_act_the_same_on_window_and_slider(qtbot, tmp_path, target):
    raw, out = _three_frames(tmp_path)
    window = _open(qtbot, raw, out)
    window.show()
    QApplication.processEvents()
    slider = window.findChild(QSlider)
    assert slider is not None
    widget = window if target == "window" else slider
    if target == "slider":
        slider.setFocus()
    turns = []
    for key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Down):
        QTest.keyClick(widget, key)
        turns.append(window.turn_deg)
    assert turns == [1, 11, 10, 0, -10]
    QTest.keyClick(widget, Qt.Key.Key_S)
    assert _index(window) == "000002"
    QTest.keyClick(widget, Qt.Key.Key_Backspace)
    assert _index(window) == "000001"
    QTest.keyClick(widget, Qt.Key.Key_Return)
    assert list(_files(out)) == ["П/a010_000001.png"]
    QTest.keyClick(widget, Qt.Key.Key_Escape)
    assert not window.isVisible()


def test_window_slider_is_linked_with_turn(qtbot, tmp_path):
    raw, out = _three_frames(tmp_path)
    window = _open(qtbot, raw, out)
    slider = window.findChild(QSlider)
    assert slider is not None
    assert (slider.minimum(), slider.maximum()) == (-180, 180)
    window.set_turn(270)
    assert slider.value() == -90
    _press(window, Qt.Key.Key_Up)
    assert slider.value() == -80
    slider.setValue(57)
    assert window.turn_deg == 57
    slider.setValue(-180)
    assert window.turn_deg == 180


def test_window_has_no_buttons(qtbot, tmp_path):
    raw, out = _three_frames(tmp_path)
    window = _open(qtbot, raw, out)
    assert window.findChildren(QAbstractButton) == []


def test_window_text_shows_frame_counters_and_angles(qtbot, tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    for number in (481, 482, 483):
        _frame(raw, "Ж", f"a000_000{number}.png", seed=number)
    window = _open(qtbot, raw, out)
    text = _text(window)
    assert "ж" in text
    assert "000481" in text
    assert "кадр 1 из 3, размечено 0" in text
    window.set_turn(37)
    text = _text(window)
    assert "37" in text
    assert "323" in text  # записываемый угол
    _press(window, Qt.Key.Key_Return)
    text = _text(window)
    assert "000482" in text
    assert "кадр 2 из 3, размечено 1" in text


# --------------------------------------------------------------------------- #
# Окно: что показано (DESIGN «Окно»)                                          #
# --------------------------------------------------------------------------- #


def test_window_view_turns_counterclockwise_on_screen(qtbot, tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    _write_image(raw / "П" / "a000_000001.png", _marker_frame(350, 60, 450, 140))  # метка у верхнего края
    window = _open(qtbot, raw, out)
    window.show()
    n0, x0, y0 = _magenta(window)
    assert n0 > 50, "кадр с меткой не виден в окне"
    window.set_turn(90)
    n_ccw, x_ccw, y_ccw = _magenta(window)
    window.set_turn(-90)
    n_cw, x_cw, y_cw = _magenta(window)
    assert n_ccw > 50 and n_cw > 50
    assert x_ccw < x0 - 30 and y_ccw > y0 + 30  # +90: метка ушла влево-вниз (к левому краю)
    assert x_cw > x0 + 30 and y_cw > y0 + 30  # -90: к правому краю


def test_window_full_frame_corner_is_not_cut_by_turn(qtbot, tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    _write_image(raw / "П" / "a000_000001.png", _marker_frame(5, 5, 105, 105))  # метка в углу кадра
    window = _open(qtbot, raw, out)
    window.show()
    base = _magenta(window)[0]
    assert base > 50, "метка в углу не видна без поворота"
    for turn in (45, -45, 135, -135):
        window.set_turn(turn)
        assert _magenta(window)[0] > 0.6 * base, f"угол кадра уехал за край при довороте {turn}"


def _disc_set(tmp_path: Path, image: np.ndarray) -> tuple[Path, Path]:
    raw, out = tmp_path / "raw", tmp_path / "out"
    _write_image(raw / "П" / "a000_000001.png", image)
    return raw, out


def test_window_shows_recipe_crop_enlarged(qtbot, tmp_path):
    from scripts import letters_baseline

    raw, out = _disc_set(tmp_path, _disc_frame())
    assert letters_baseline.RecipePipeline(RECIPE).crop(_disc_frame()) is not None  # предусловие: диск находится
    cropped = _open(qtbot, raw, out, RECIPE)
    cropped.show()
    full = _open(qtbot, raw, out, None)
    full.show()
    crop_pixels = _magenta(cropped)[0]
    full_pixels = _magenta(full)[0]
    assert full_pixels > 0
    assert crop_pixels > 4 * full_pixels  # вырез увеличен, весь кадр уменьшен


def test_window_turns_recipe_crop_counterclockwise(qtbot, tmp_path):
    raw, out = _disc_set(tmp_path, _disc_frame())
    window = _open(qtbot, raw, out, RECIPE)
    window.show()
    n0, x0, y0 = _magenta(window)
    window.set_turn(90)
    n1, x1, y1 = _magenta(window)
    assert n0 > 50 and n1 > 50
    assert x1 < x0 - 20 and y1 > y0 + 20


@pytest.mark.parametrize("case", ["no-circle", "no-recipe"])
def test_window_says_when_full_frame_is_shown(qtbot, tmp_path, case):
    """Формулировка надписи не задана: проверяется только, что текст отличается от случая с вырезом."""
    raw_a, out_a = _disc_set(tmp_path / "a", _disc_frame())
    with_crop = _text(_open(qtbot, raw_a, out_a, RECIPE))
    image = _black_frame() if case == "no-circle" else _disc_frame()
    raw_b, out_b = _disc_set(tmp_path / "b", image)
    without_crop = _text(_open(qtbot, raw_b, out_b, RECIPE if case == "no-circle" else None))
    assert with_crop != without_crop


# --------------------------------------------------------------------------- #
# REDS 7: плохие кадры и конфликт во время работы                             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("recipe", [None, RECIPE], ids=["no-crop", "recipe"])
def test_window_unreadable_file(qtbot, tmp_path, recipe):
    raw, out = tmp_path / "raw", tmp_path / "out"
    _put(raw / "П" / "a000_000001.png", b"this is not a png")
    _write_image(raw / "П" / "a000_000002.png", _disc_frame())
    window = _open(qtbot, raw, out, recipe)
    window.show()
    assert _index(window) == "000001"
    _press(window, Qt.Key.Key_Left)
    _press(window, Qt.Key.Key_Return)
    _press(window, Qt.Key.Key_Enter)
    assert _index(window) == "000001"
    assert _files(out) == {}
    assert window.isVisible()
    _press(window, Qt.Key.Key_S)
    assert _index(window) == "000002"
    _press(window, Qt.Key.Key_Return)
    assert len(_files(out)) == 1


def test_window_unreadable_file_has_a_message(qtbot, tmp_path):
    """Формулировка не задана: тот же номер с читаемым и нечитаемым файлом даёт разный текст окна."""
    raw_a, out_a = _disc_set(tmp_path / "a", _disc_frame())
    readable = _text(_open(qtbot, raw_a, out_a))
    raw_b, out_b = tmp_path / "b" / "raw", tmp_path / "b" / "out"
    _put(raw_b / "П" / "a000_000001.png", b"garbage")
    unreadable = _text(_open(qtbot, raw_b, out_b))
    assert readable != unreadable


def test_window_frame_without_circle_can_be_labelled(qtbot, tmp_path):
    raw, out = _disc_set(tmp_path, _black_frame())
    window = _open(qtbot, raw, out, RECIPE)
    window.show()
    assert _index(window) == "000001"
    window.set_turn(-90)
    _press(window, Qt.Key.Key_Return)
    assert _files(out) == {"П/a090_000001.png": (raw / "П" / "a000_000001.png").read_bytes()}
    assert window.current is None


def test_window_labelled_copy_of_cropped_frame_is_the_full_frame(qtbot, tmp_path):
    raw, out = _disc_set(tmp_path, _disc_frame())
    window = _open(qtbot, raw, out, RECIPE)
    window.set_turn(30)
    _press(window, Qt.Key.Key_Return)
    assert _files(out) == {"П/a330_000001.png": (raw / "П" / "a000_000001.png").read_bytes()}


def test_window_foreign_file_after_open_blocks_enter(qtbot, tmp_path):
    raw, out = _three_frames(tmp_path)
    window = _open(qtbot, raw, out)
    window.show()
    _put(out / "П" / "a123_000001.png", b"foreign bytes")
    before = _text(window)
    _press(window, Qt.Key.Key_Return)
    assert _index(window) == "000001"
    assert _files(out) == {"П/a123_000001.png": b"foreign bytes"}
    assert _text(window) != before  # сообщение в окне
    assert window.isVisible()
    _press(window, Qt.Key.Key_Left)
    assert window.turn_deg == 1


def test_window_write_error_keeps_frame(qtbot, tmp_path):
    raw, out = _three_frames(tmp_path)
    window = _open(qtbot, raw, out)
    window.show()
    _put(out / "П", b"a file where the letter folder must be")  # запись копии невозможна
    before = _text(window)
    _press(window, Qt.Key.Key_Return)
    assert _index(window) == "000001"
    assert _files(out) == {"П": b"a file where the letter folder must be"}
    assert _text(window) != before
    assert window.isVisible()


# --------------------------------------------------------------------------- #
# REDS 8: main и запуск скрипта                                               #
# --------------------------------------------------------------------------- #


def _run_main(qapp, argv: list[str], action=None) -> tuple[int, bool]:
    """(код main, открывалось ли окно). Окно закрывает QTimer; через 20 с — аварийный выход из цикла."""
    la = _la()
    opened: list[bool] = []

    def poke():
        if opened:
            return
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, la.LabelWindow) and widget.isVisible():
                opened.append(True)
                try:
                    if action is not None:
                        action(widget)
                finally:
                    widget.close()
                return

    poller = QTimer()
    poller.setInterval(100)
    poller.timeout.connect(poke)
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(lambda: qapp.exit(99))
    poller.start()
    deadline.start(20_000)
    try:
        code = la.main(argv)
    finally:
        poller.stop()
        deadline.stop()
    return code, bool(opened)


def _assert_refused(qapp, capsys, argv: list[str]) -> None:
    code, opened = _run_main(qapp, argv)
    assert code == 2
    assert opened is False
    assert capsys.readouterr().err.strip() != ""


def test_main_missing_input(qapp, capsys, tmp_path):
    _assert_refused(qapp, capsys, [str(tmp_path / "нет"), str(tmp_path / "out"), "--no-crop"])


def test_main_conflict_in_out(qapp, capsys, tmp_path):
    raw, out = _three_frames(tmp_path)
    _put(out / "П" / "a045_000001.png", b"foreign bytes")
    _assert_refused(qapp, capsys, [str(raw), str(out), "--no-crop"])
    assert _files(out) == {"П/a045_000001.png": b"foreign bytes"}


@pytest.mark.parametrize(
    "content",
    [None, "blueprint: [unclosed\n  : :\n", "blueprint:\n  processes:\n    - process_name: x\n      plugins: []\n"],
    ids=["missing-file", "bad-yaml", "no-plugin"],
)
def test_main_bad_recipe(qapp, capsys, tmp_path, content):
    raw, out = _three_frames(tmp_path)
    recipe = tmp_path / "recipe.yaml"
    if content is not None:
        recipe.write_text(content, encoding="utf-8")
    _assert_refused(qapp, capsys, [str(raw), str(out), "--recipe", str(recipe)])


def test_main_no_crop_does_not_need_recipe(qapp, tmp_path):
    raw, out = _three_frames(tmp_path)
    code, opened = _run_main(qapp, [str(raw), str(out), "--recipe", str(tmp_path / "нет.yaml"), "--no-crop"])
    assert (code, opened) == (0, True)


def test_main_default_recipe_from_other_cwd(qapp, tmp_path, monkeypatch):
    raw, out = _disc_set(tmp_path, _disc_frame())
    monkeypatch.chdir(tmp_path)  # рецепт по умолчанию берётся от корня репозитория, а не от cwd
    code, opened = _run_main(qapp, [str(raw), str(out)])
    assert (code, opened) == (0, True)


def test_main_prints_summary_per_letter(qapp, capsys, tmp_path):
    raw, out = _three_frames(tmp_path)
    _frame(raw, "Р", "a000_000001.png", seed=11)
    _frame(raw, "Р", "a000_000002.png", seed=12)
    _put(out / "П" / "a045_000001.png", (raw / "П" / "a000_000001.png").read_bytes())
    _put(out / "П" / "a090_000002.png", (raw / "П" / "a000_000002.png").read_bytes())
    code, opened = _run_main(qapp, [str(raw), str(out), "--no-crop"])
    assert (code, opened) == (0, True)
    lines = [line.strip() for line in capsys.readouterr().out.splitlines()]
    assert "П: кадров 3, размечено 2, разных углов 2" in lines
    assert "Р: кадров 2, размечено 0, разных углов 0" in lines


def test_main_summary_counts_labels_made_in_the_window(qapp, capsys, tmp_path):
    raw, out = _three_frames(tmp_path)

    def label_two(window):
        _press(window, Qt.Key.Key_Return)
        _press(window, Qt.Key.Key_Return)  # тот же угол: разных углов 1

    code, opened = _run_main(qapp, [str(raw), str(out), "--no-crop"], action=label_two)
    assert (code, opened) == (0, True)
    lines = [line.strip() for line in capsys.readouterr().out.splitlines()]
    assert "П: кадров 3, размечено 2, разных углов 1" in lines


def test_script_help_runs_from_foreign_cwd_without_pythonpath(tmp_path):
    env = {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    assert "--no-crop" in result.stdout
    assert "--recipe" in result.stdout


# --------------------------------------------------------------------------- #
# REDS 9: контроль схемы входа (зелёный сейчас, код не меняется)              #
# --------------------------------------------------------------------------- #


def test_control_day1_check_accepts_input_scheme(tmp_path):
    raw = tmp_path / "raw"
    for li, letter in enumerate("ПР"):
        for number in (1, 2, 3):
            _write_image(raw / letter / f"a000_{number:06d}.png", _noise(100 * li + number, 120, 160))
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-X",
            "utf8",
            str(REPO_ROOT / "scripts" / "day1_capture_check.py"),
            str(raw),
            "--angles",
            "0",
            "--min-per-cell",
            "3",
            "--letters",
            "ПР",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ИТОГ: PASS" in result.stdout
