# -*- coding: utf-8 -*-
"""Приёмочные тесты DisplaySlot: ресайз слота не меняет качество показанного кадра.

Требование владельца: ресайз слота, включая «сжать и вернуть», не меняет качество
кадра. Показанный кадр (label.pixmap()) после любого ресайза равен ЭТАЛОНУ: исходная
QImage, отмасштабированная напрямую средствами Qt до ТЕКУЩЕГО label.size() с
KeepAspectRatio и SmoothTransformation. Эталон считает сам тест из исходника,
не из кода слота и не из label.pixmap().

Мера: среднее абсолютное отклонение по каналам RGB (numpy); ожидаемое значение == 0.

Тесты написаны слепо, до реализации: контракт — формулировка владельца, код слота не читался.

Запуск (из корня репозитория):
    python -m pytest multiprocess_prototype/frontend/widgets/image_panel/tests/test_display_slot_resize.py -v
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QLabel

from multiprocess_prototype.frontend.widgets.image_panel.display_slot import DisplaySlot

NO_SIGNAL = "Нет сигнала"
BIG = (700, 560)
SMALL = (400, 300)
HUGE = (900, 720)


# --------------------------------------------------------------------------- кадры


def _make_image_a(width: int, height: int) -> QImage:
    """Шахматка клетками 4 px + красные и синие диагонали (всё высокочастотное)."""
    yy, xx = np.mgrid[0:height, 0:width]
    checker = (((yy // 4) + (xx // 4)) % 2) * 255
    arr = np.stack([checker, checker, checker], axis=-1).astype(np.uint8)
    arr[((xx - yy) % 97) < 2] = (255, 0, 0)
    arr[((xx + yy) % 101) < 2] = (0, 0, 255)
    arr = np.ascontiguousarray(arr)
    return QImage(arr.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()


def _make_image_b(width: int, height: int) -> QImage:
    """Другой рисунок: инвертированная шахматка 6 px + зелёные диагонали другого шага."""
    yy, xx = np.mgrid[0:height, 0:width]
    checker = 255 - (((yy // 6) + (xx // 6)) % 2) * 255
    arr = np.stack([checker, checker, checker], axis=-1).astype(np.uint8)
    arr[((xx - yy) % 53) < 3] = (0, 255, 0)
    arr[((xx + yy) % 67) < 2] = (255, 255, 0)
    arr = np.ascontiguousarray(arr)
    return QImage(arr.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()


# --------------------------------------------------------------------------- помощники


def _rgb_array(image: QImage) -> np.ndarray:
    """QImage -> numpy (h, w, 3) uint8: один формат, без паддинга строк."""
    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    raw = np.frombuffer(img.constBits(), dtype=np.uint8, count=img.sizeInBytes())
    return raw.reshape(h, img.bytesPerLine())[:, : w * 4].reshape(h, w, 4)[:, :, :3].copy()


def _label_of(slot: DisplaySlot) -> QLabel:
    label = slot.findChild(QLabel, "DisplaySlotLabel")
    assert label is not None, "в слоте нет QLabel с objectName 'DisplaySlotLabel'"
    return label


def _shown_pixmap(label: QLabel) -> QPixmap | None:
    pm = label.pixmap()
    if pm is None or pm.isNull():
        return None
    return pm


def _settle() -> None:
    """Прогнать события ресайза/перерисовки (ограниченно, без ожиданий)."""
    for _ in range(3):
        QApplication.processEvents()


def _resize(slot: DisplaySlot, size: tuple[int, int]) -> None:
    slot.resize(*size)
    slot.show()
    _settle()


def _deviation(label: QLabel, source: QImage) -> float:
    """Среднее абс. отклонение показанного кадра от эталона из исходника (0.0 == идентично)."""
    shown = _shown_pixmap(label)
    assert shown is not None, "кадр не показан: label.pixmap() пуст"
    # Эталон — свежее масштабирование ИСХОДНОГО кадра в том же виде, в каком его получает слот (QPixmap):
    # сглаживающий скейлер Qt даёт разные пиксели на QImage RGB888 и на QPixmap (RGB32), даже без ресайза.
    reference = QPixmap.fromImage(source).scaled(
        label.size(),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    shown_arr = _rgb_array(shown.toImage())
    ref_arr = _rgb_array(reference.toImage())
    assert shown_arr.shape == ref_arr.shape, (
        f"размер показанного кадра {shown_arr.shape[1]}x{shown_arr.shape[0]} "
        f"!= эталон {ref_arr.shape[1]}x{ref_arr.shape[0]} при label.size()={label.width()}x{label.height()}"
    )
    return float(np.abs(shown_arr.astype(np.int16) - ref_arr.astype(np.int16)).mean())


def _assert_equal_to_reference(label: QLabel, source: QImage, where: str) -> None:
    dev = _deviation(label, source)
    assert dev == 0.0, f"{where}: среднее абс. отклонение от эталона {dev:.4f}, ожидалось 0"


def _shrink_and_restore(slot: DisplaySlot, label: QLabel, big: tuple[int, int], small: tuple[int, int]) -> None:
    """Сжать слот и вернуть. Страж «ноль наблюдений»: ресайз реально дошёл до label."""
    before = label.size()
    _resize(slot, small)
    shrunk = label.size()
    assert shrunk.width() < before.width() or shrunk.height() < before.height(), (
        f"страж: label не уменьшился при сжатии слота ({before.width()}x{before.height()} -> "
        f"{shrunk.width()}x{shrunk.height()}), событие ресайза не дошло, тест вакуумен"
    )
    _resize(slot, big)
    assert label.size() == before, (
        f"страж: label не вернулся к исходному размеру ({before.width()}x{before.height()} -> "
        f"{label.width()}x{label.height()})"
    )


@pytest.fixture()
def slot(qtbot):
    s = DisplaySlot("s1")
    qtbot.addWidget(s)
    _resize(s, BIG)
    return s


# --------------------------------------------------------------------------- тесты


def test_baseline_first_frame_matches_reference(slot) -> None:
    """Диагностика (не AC): сразу после update_pixmap кадр == эталон, т.е. эталон корректен."""
    label = _label_of(slot)
    img = _make_image_a(1280, 1024)
    slot.update_pixmap(QPixmap.fromImage(img))
    _settle()
    _assert_equal_to_reference(label, img, "кадр без ресайза")


def test_ac1_shrink_and_restore_keeps_frame(slot) -> None:
    label = _label_of(slot)
    img = _make_image_a(1280, 1024)
    slot.update_pixmap(QPixmap.fromImage(img))
    _settle()
    _shrink_and_restore(slot, label, BIG, SMALL)
    _assert_equal_to_reference(label, img, "после сжать/вернуть")


def test_ac8_shrunk_slot_shows_frame_fitted_to_smaller_area(slot) -> None:
    """Промежуточное состояние: пока слот СЖАТ, кадр вписан в меньшую область (это видит пользователь).

    Тесты «сжать и вернуть» его не видят: без перемасштабирования в resizeEvent нетронутый pixmap после
    возврата случайно совпадает с эталоном (находка матрицы инъекций I5, 2026-10-16).
    """
    label = _label_of(slot)
    img = _make_image_a(1280, 1024)
    slot.update_pixmap(QPixmap.fromImage(img))
    _settle()
    before = label.size()
    _resize(slot, SMALL)
    assert label.width() < before.width() or label.height() < before.height(), (
        f"страж: label не уменьшился ({before.width()}x{before.height()} -> {label.width()}x{label.height()})"
    )
    _assert_equal_to_reference(label, img, "в сжатом состоянии")


def test_ac9_frame_arrived_on_hidden_slot_is_shown_after_show(slot) -> None:
    """Кадр пришёл, пока слот скрыт (вкладка не активна); после show() он показан без ресайза."""
    label = _label_of(slot)
    slot.hide()
    _settle()
    img = _make_image_a(1280, 1024)
    slot.update_pixmap(QPixmap.fromImage(img))
    slot.show()
    _settle()
    _assert_equal_to_reference(label, img, "кадр, пришедший на скрытый слот")


def test_ac10_null_pixmap_after_frame_shows_no_signal_and_survives_resize(slot) -> None:
    """Пустой pixmap после кадра = «Нет сигнала»; ресайз не возвращает старый кадр."""
    label = _label_of(slot)
    slot.update_pixmap(QPixmap.fromImage(_make_image_a(1280, 1024)))
    _settle()
    assert _shown_pixmap(label) is not None, "страж: кадр не показан до пустого pixmap"
    slot.update_pixmap(QPixmap())
    _settle()
    _shrink_and_restore(slot, label, BIG, SMALL)
    assert _shown_pixmap(label) is None, "после пустого pixmap и ресайза на экране остался кадр"
    assert label.text() == NO_SIGNAL, f"текст {label.text()!r}, ожидалось {NO_SIGNAL!r}"


def test_ac2_five_shrink_restore_cycles_keep_frame(slot) -> None:
    label = _label_of(slot)
    img = _make_image_a(1280, 1024)
    slot.update_pixmap(QPixmap.fromImage(img))
    _settle()
    for _ in range(5):
        _shrink_and_restore(slot, label, BIG, SMALL)
    _assert_equal_to_reference(label, img, "после 5 циклов сжать/вернуть")


def test_ac3_shrink_then_enlarge_beyond_original_matches_reference(slot) -> None:
    label = _label_of(slot)
    img = _make_image_a(1280, 1024)
    slot.update_pixmap(QPixmap.fromImage(img))
    _settle()
    before = label.size()
    _resize(slot, SMALL)
    assert label.width() < before.width() or label.height() < before.height(), (
        "страж: label не уменьшился при сжатии слота, тест вакуумен"
    )
    small_label = label.size()
    _resize(slot, HUGE)
    assert label.width() > before.width() and label.height() > before.height(), (
        f"страж: label не вырос больше исходного ({before.width()}x{before.height()} -> "
        f"{label.width()}x{label.height()}; после сжатия был {small_label.width()}x{small_label.height()})"
    )
    _assert_equal_to_reference(label, img, "после сжатия и растяжения больше прежнего")


def test_ac4_clear_after_frame_then_resize_shows_no_signal(slot) -> None:
    label = _label_of(slot)
    slot.update_pixmap(QPixmap.fromImage(_make_image_a(1280, 1024)))
    _settle()
    slot.clear()
    _settle()
    _shrink_and_restore(slot, label, BIG, SMALL)
    assert _shown_pixmap(label) is None, "после clear() и ресайза вернулся старый кадр"
    assert label.text() == NO_SIGNAL


def test_ac4_placeholder_after_frame_then_resize_shows_text(slot) -> None:
    label = _label_of(slot)
    slot.update_pixmap(QPixmap.fromImage(_make_image_a(1280, 1024)))
    _settle()
    slot.set_placeholder("тест")
    _settle()
    _shrink_and_restore(slot, label, BIG, SMALL)
    assert _shown_pixmap(label) is None, "после set_placeholder() и ресайза вернулся старый кадр"
    assert label.text() == "тест"


def test_ac5_new_frame_after_resize_is_shown_and_survives_next_resize(slot) -> None:
    label = _label_of(slot)
    img_a = _make_image_a(1280, 1024)
    img_b = _make_image_b(1280, 1024)
    slot.update_pixmap(QPixmap.fromImage(img_a))
    _settle()
    _shrink_and_restore(slot, label, BIG, SMALL)
    slot.update_pixmap(QPixmap.fromImage(img_b))
    _settle()
    # страж: новый кадр действительно отличается от старого на этом размере label
    assert _deviation(label, img_a) > 0.0, "страж: кадры A и B неразличимы, тест вакуумен"
    _assert_equal_to_reference(label, img_b, "новый кадр сразу после прихода")
    _shrink_and_restore(slot, label, BIG, SMALL)
    _assert_equal_to_reference(label, img_b, "новый кадр после ещё одного сжать/вернуть")


def test_ac6_resize_before_first_frame_keeps_placeholder(slot) -> None:
    label = _label_of(slot)
    _shrink_and_restore(slot, label, BIG, SMALL)
    assert _shown_pixmap(label) is None
    assert label.text() == NO_SIGNAL


def test_ac7_wide_frame_1000x300_shrink_and_restore_keeps_frame(slot) -> None:
    label = _label_of(slot)
    img = _make_image_a(1000, 300)
    slot.update_pixmap(QPixmap.fromImage(img))
    _settle()
    _shrink_and_restore(slot, label, BIG, SMALL)
    _assert_equal_to_reference(label, img, "кадр 1000x300 после сжать/вернуть")
