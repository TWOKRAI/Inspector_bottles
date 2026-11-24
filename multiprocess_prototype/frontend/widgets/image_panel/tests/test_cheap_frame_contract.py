# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты дешёвого пути кадра панели изображений (Task T6).

Purpose: зафиксировать внешний контракт — кадр больше label уменьшается в презентере
``cv2.resize(INTER_AREA)`` до размера ``QSize(w, h).scaled(label, KeepAspectRatio)``; кадр не больше
label уходит как есть и увеличивается слотом; ресайз слота перерисовывает из СЫРОГО кадра;
серый кадр уменьшается так же; заглушки («Нет сигнала», «Ошибка кадра») ресайз не стирает.

Эталон считает сам тест из СЫРОГО кадра: ``cv2.resize(raw, size, INTER_AREA)`` и BGR -> RGB.
Метрика — среднее абсолютное отклонение по каналам RGB (numpy); ожидается ровно 0.
Размеры label и литералы — из приёмочного блока задачи, не из кода презентера и слота.

Тесты написаны слепо, до реализации: код ``presenter.py`` и ``display_slot.py`` не читался.
Презентер и слот импортируются ВНУТРИ тестов, чтобы красный падал на тесте, а не на сборе.

Запуск (из корня репозитория):
    python -m pytest multiprocess_prototype/frontend/widgets/image_panel/tests/test_cheap_frame_contract.py -q
"""

from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QLabel

SLOT_ID = "main"
NO_SIGNAL = "Нет сигнала"
REJECTED = "Ошибка кадра"

LABEL = (480, 360)
FLOOR = (320, 240)


# --------------------------------------------------------------------------- кадры


def _detail_bgr(width: int, height: int) -> np.ndarray:
    """Шахматка клетками 4 px + диагонали (всё высокочастотное), BGR uint8 (h, w, 3)."""
    yy, xx = np.mgrid[0:height, 0:width]
    checker = (((yy // 4) + (xx // 4)) % 2) * 255
    arr = np.stack([checker, checker, checker], axis=-1).astype(np.uint8)
    arr[((xx - yy) % 97) < 2] = (255, 0, 0)
    arr[((xx + yy) % 101) < 2] = (0, 0, 255)
    return np.ascontiguousarray(arr)


# --------------------------------------------------------------------------- помощники


def _settle() -> None:
    """Прогнать события ресайза/перерисовки (ограниченно, без ожиданий)."""
    for _ in range(3):
        QApplication.processEvents()


def _label_of(slot) -> QLabel:
    label = slot.findChild(QLabel, "DisplaySlotLabel")
    assert label is not None, "в слоте нет QLabel с objectName 'DisplaySlotLabel'"
    return label


def _shown(label: QLabel) -> QPixmap | None:
    pm = label.pixmap()
    if pm is None or pm.isNull():
        return None
    return pm


def _rgb_array(pixmap: QPixmap) -> np.ndarray:
    """QPixmap -> numpy (h, w, 3) uint8 RGB: один формат, без паддинга строк."""
    img = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    raw = np.frombuffer(img.constBits(), dtype=np.uint8, count=img.sizeInBytes())
    return raw.reshape(h, img.bytesPerLine())[:, : w * 4].reshape(h, w, 4)[:, :, :3].copy()


def _reference(raw_bgr: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Эталон: INTER_AREA из СЫРОГО BGR-кадра до size=(w, h), затем BGR -> RGB."""
    small = cv2.resize(raw_bgr, size, interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2RGB)


def _qt_fit_size(frame_wh: tuple[int, int], label_wh: tuple[int, int]) -> tuple[int, int]:
    """Размер, до которого Qt вписывает кадр в label (KeepAspectRatio) — эталон размера."""
    fitted = QSize(*frame_wh).scaled(QSize(*label_wh), Qt.AspectRatioMode.KeepAspectRatio)
    return fitted.width(), fitted.height()


def _fit_label(slot, label: QLabel, size: tuple[int, int]) -> None:
    """Выставить размер label ровно ``size`` через геометрию слота (поля раскладки считаем по факту)."""
    slot.show()
    _settle()
    for _ in range(4):
        dx = slot.width() - label.width()
        dy = slot.height() - label.height()
        slot.resize(size[0] + dx, size[1] + dy)
        slot.show()
        _settle()
        if (label.width(), label.height()) == size:
            return
    pytest.fail(
        f"страж: label не удалось выставить в {size[0]}x{size[1]} через геометрию слота "
        f"(получилось {label.width()}x{label.height()}), тест вакуумен"
    )


def _setup(qtbot, monkeypatch, label_size: tuple[int, int] = LABEL) -> SimpleNamespace:
    """Настоящие презентер и слот; label нужного размера; шпион на update_pixmap."""
    from multiprocess_prototype.frontend.widgets.image_panel.display_slot import DisplaySlot
    from multiprocess_prototype.frontend.widgets.image_panel.presenter import ImagePanelPresenter

    presenter = ImagePanelPresenter()
    slot = DisplaySlot(SLOT_ID)
    qtbot.addWidget(slot)
    presenter.register_slot(SLOT_ID, slot)
    label = _label_of(slot)
    _fit_label(slot, label, label_size)

    received: list[tuple[int, int]] = []
    original = slot.update_pixmap

    def spy(pixmap):
        received.append((pixmap.width(), pixmap.height()))
        return original(pixmap)

    monkeypatch.setattr(slot, "update_pixmap", spy)
    return SimpleNamespace(presenter=presenter, slot=slot, label=label, received=received)


def _show(env: SimpleNamespace, frame: np.ndarray) -> None:
    env.presenter.on_frame(SLOT_ID, frame)
    _settle()


def _mad(shown: QPixmap, ref_rgb: np.ndarray, where: str) -> float:
    shown_arr = _rgb_array(shown)
    assert shown_arr.shape == ref_rgb.shape, (
        f"{where}: размер показанного кадра {shown_arr.shape[1]}x{shown_arr.shape[0]} "
        f"!= эталон {ref_rgb.shape[1]}x{ref_rgb.shape[0]}"
    )
    return float(np.abs(shown_arr.astype(np.int16) - ref_rgb.astype(np.int16)).mean())


def _assert_equals_reference(env: SimpleNamespace, raw: np.ndarray, size: tuple[int, int], where: str) -> None:
    shown = _shown(env.label)
    assert shown is not None, f"{where}: кадр не показан, label.pixmap() пуст (текст {env.label.text()!r})"
    dev = _mad(shown, _reference(raw, size), where)
    assert dev == 0.0, f"{where}: отклонение от INTER_AREA-эталона {dev:.4f}, ожидалось 0"


def _shrink_and_restore(env: SimpleNamespace, big: tuple[int, int], small: tuple[int, int]) -> None:
    """Сжать слот и вернуть. Страж: ресайз реально дошёл до label."""
    _fit_label(env.slot, env.label, small)
    assert (env.label.width(), env.label.height()) == small, "страж: label не сжался"
    _fit_label(env.slot, env.label, big)
    assert (env.label.width(), env.label.height()) == big, "страж: label не вернулся"


# --------------------------------------------------------------------------- REDS


def test_first_show_equals_inter_area_reference(qtbot, monkeypatch) -> None:
    """Кадр 1440x1080x3 в label 480x360: показанное == INTER_AREA сырого кадра, MAD ровно 0."""
    env = _setup(qtbot, monkeypatch)
    raw = _detail_bgr(1440, 1080)

    _show(env, raw)

    assert env.presenter.frame_stats(SLOT_ID)["shown"] == 1
    _assert_equals_reference(env, raw, (480, 360), "первый показ 1440x1080 в 480x360")


@pytest.mark.parametrize(
    "shape",
    [(1080, 1440), (1080, 1440, 1)],
    ids=["gray_2d", "gray_hw1"],
)
def test_gray_frame_supported(qtbot, monkeypatch, shape) -> None:
    """Серый кадр (заливка 100) уменьшается презентером до 480x360 и показан без отказа."""
    env = _setup(qtbot, monkeypatch)
    gray = np.full(shape, 100, dtype=np.uint8)

    _show(env, gray)

    stats = env.presenter.frame_stats(SLOT_ID)
    assert stats["shown"] == 1, f"shown {stats['shown']}, ожидалось 1"
    assert stats["rejected"] == 0, f"rejected {stats['rejected']}, ожидалось 0"
    assert env.received, "update_pixmap не вызывался: кадр не дошёл до слота"
    assert env.received[-1] == (480, 360), (
        f"слот получил pixmap {env.received[-1][0]}x{env.received[-1][1]}, ожидалось 480x360 "
        "(презентер обязан уменьшить кадр больше label)"
    )
    shown = _shown(env.label)
    assert shown is not None, "серый кадр не показан"
    img = shown.toImage()
    centre = img.pixelColor(img.width() // 2, img.height() // 2)
    for name, value in (("R", centre.red()), ("G", centre.green()), ("B", centre.blue())):
        assert abs(value - 100) <= 1, f"центр label: канал {name} = {value}, ожидалось 100 +-1"


@pytest.mark.parametrize(
    "frame_wh",
    [(1440, 1080), (1280, 1024)],
    ids=["1440x1080", "1280x1024"],
)
def test_nonstandard_aspect_equals_qsize_scaled_reference(qtbot, monkeypatch, frame_wh) -> None:
    """Label 483x362: размер показанного = QSize.scaled (Qt), пиксели = INTER_AREA сырого кадра, MAD 0."""
    env = _setup(qtbot, monkeypatch, (483, 362))
    raw = _detail_bgr(*frame_wh)
    expected_size = _qt_fit_size(frame_wh, (483, 362))

    _show(env, raw)

    _assert_equals_reference(env, raw, expected_size, f"кадр {frame_wh[0]}x{frame_wh[1]} в label 483x362")


def test_resize_roundtrip_keeps_quality(qtbot, monkeypatch) -> None:
    """Сжать до 320x240 -> эталон из СЫРОГО кадра; вернуть -> равно первому показу; пять циклов то же."""
    env = _setup(qtbot, monkeypatch)
    raw = _detail_bgr(1440, 1080)
    _show(env, raw)
    _assert_equals_reference(env, raw, LABEL, "первый показ")
    first = _rgb_array(_shown(env.label))

    _fit_label(env.slot, env.label, FLOOR)
    _assert_equals_reference(env, raw, FLOOR, "после сжатия до 320x240 (эталон из сырого кадра)")

    _fit_label(env.slot, env.label, LABEL)
    _assert_equals_reference(env, raw, LABEL, "после возврата в 480x360")
    assert np.array_equal(_rgb_array(_shown(env.label)), first), "после возврата кадр не равен первому показу"

    for cycle in range(1, 6):
        _shrink_and_restore(env, LABEL, FLOOR)
        _assert_equals_reference(env, raw, LABEL, f"после цикла сжать/вернуть №{cycle}")
        assert np.array_equal(_rgb_array(_shown(env.label)), first), f"цикл №{cycle}: кадр не равен первому показу"


# --------------------------------------------------------------------------- GUARDS


def test_growth_beyond_raw_goes_through_slot(qtbot, monkeypatch) -> None:
    """Кадр 320x240 не больше label 480x360: слот увеличивает; рост label до 960x720 даёт pixmap 960x720."""
    env = _setup(qtbot, monkeypatch)
    raw = _detail_bgr(320, 240)

    _show(env, raw)
    first = _shown(env.label)
    assert first is not None, "страж: кадр 320x240 не показан"
    assert (first.width(), first.height()) == (480, 360), (
        f"кадр не больше label должен быть увеличен слотом до 480x360, показано {first.width()}x{first.height()}"
    )

    _fit_label(env.slot, env.label, (960, 720))

    grown = _shown(env.label)
    assert grown is not None, "после роста label кадр пропал"
    assert (grown.width(), grown.height()) == (960, 720), (
        f"после роста label до 960x720 показано {grown.width()}x{grown.height()}, ожидалось 960x720"
    )


def test_resize_after_placeholder_keeps_placeholder(qtbot, monkeypatch) -> None:
    """Кадр показан, потом set_placeholder('Нет сигнала'), потом ресайз слота: текст есть, pixmap нет."""
    env = _setup(qtbot, monkeypatch)
    _show(env, _detail_bgr(1440, 1080))
    assert _shown(env.label) is not None, "страж: кадр не показан до заглушки"

    env.slot.set_placeholder(NO_SIGNAL)
    _settle()
    _shrink_and_restore(env, LABEL, FLOOR)

    assert _shown(env.label) is None, "после заглушки и ресайза на экране вернулся кадр"
    assert env.label.text() == NO_SIGNAL, f"текст {env.label.text()!r}, ожидалось {NO_SIGNAL!r}"


def test_resize_after_rejected_frame_keeps_error_placeholder(qtbot, monkeypatch) -> None:
    """Валидный кадр, затем кадр неподдерживаемой формы (4 канала), затем ресайз: «Ошибка кадра»."""
    env = _setup(qtbot, monkeypatch)
    _show(env, _detail_bgr(1440, 1080))
    assert _shown(env.label) is not None, "страж: кадр не показан до отвергнутого"

    _show(env, np.zeros((1080, 1440, 4), dtype=np.uint8))
    assert env.label.text() == REJECTED, f"страж: после отвергнутого кадра текст {env.label.text()!r}"
    assert env.presenter.frame_stats(SLOT_ID)["rejected"] == 1

    _shrink_and_restore(env, LABEL, FLOOR)

    assert _shown(env.label) is None, "после отвергнутого кадра и ресайза воскрес старый кадр"
    assert env.label.text() == REJECTED, f"текст {env.label.text()!r}, ожидалось {REJECTED!r}"
