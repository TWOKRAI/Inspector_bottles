# -*- coding: utf-8 -*-
"""Тесты автора дешёвого пути кадра панели изображений (Task T6): время и шпионы на cv2.resize.

Purpose: удержать, что ``ImagePanelPresenter.on_frame`` уменьшает кадр до размера метки слота ДО
конвертации BGR -> RGB и ``QPixmap`` (тест времени), что ``cv2.resize`` получает тот же объект
кадра без промежуточной копии, что кадр не больше метки не увеличивается презентером и что
слот остаётся целым без колбэка или при ответе колбэка ``False``. Контракт качества картинки
(эталон INTER_AREA, ресайз туда-обратно) держит слепой файл ``test_cheap_frame_contract.py``.

Метка 480x360 и кадр 1440x1080 — синтетика теста, раскладка окна приложения из неё не выводится.
Шпион на ``cv2.resize`` ставится на сам модуль ``cv2`` (``monkeypatch.setattr(cv2, "resize", ...)``),
не на ``presenter.cv2``: так он ловит любой вызов, откуда бы он ни пришёл.

Запуск (из корня репозитория):
    python -m pytest multiprocess_prototype/frontend/widgets/image_panel/tests/test_cheap_frame.py -q
"""

from __future__ import annotations

import statistics
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QLabel

SLOT_ID = "main"
LABEL = (480, 360)

# Порог времени: лучшая из трёх медиан по 50 вызовов. Выше 4,0 мс не поднимать (решение лида, В5).
MEDIAN_LIMIT_MS = 3.0
SERIES = 3
CALLS_PER_SERIES = 50
WARMUP_CALLS = 5


def _settle() -> None:
    for _ in range(3):
        QApplication.processEvents()


def _setup(qtbot, label_size: tuple[int, int] = LABEL) -> SimpleNamespace:
    """Настоящие презентер и слот; метка ровно label_size (поля раскладки считаем по факту)."""
    from multiprocess_prototype.frontend.widgets.image_panel.display_slot import DisplaySlot
    from multiprocess_prototype.frontend.widgets.image_panel.presenter import ImagePanelPresenter

    presenter = ImagePanelPresenter()
    slot = DisplaySlot(SLOT_ID)
    qtbot.addWidget(slot)
    presenter.register_slot(SLOT_ID, slot)
    label = slot.findChild(QLabel, "DisplaySlotLabel")
    assert label is not None
    slot.show()
    _settle()
    for _ in range(4):
        slot.resize(
            label_size[0] + slot.width() - label.width(),
            label_size[1] + slot.height() - label.height(),
        )
        _settle()
        if (label.width(), label.height()) == label_size:
            break
    assert (label.width(), label.height()) == label_size, "страж: метка не выставилась, тест вакуумен"
    return SimpleNamespace(presenter=presenter, slot=slot, label=label)


def _spy_update_pixmap(env: SimpleNamespace, monkeypatch) -> list[tuple[int, int]]:
    """Шпион на slot.update_pixmap: размеры pixmap, которые получает слот."""
    received: list[tuple[int, int]] = []
    original = env.slot.update_pixmap

    def spy(pixmap):
        received.append((pixmap.width(), pixmap.height()))
        return original(pixmap)

    monkeypatch.setattr(env.slot, "update_pixmap", spy)
    return received


def _spy_cv2_resize(monkeypatch) -> list[tuple[object, tuple]]:
    """Шпион на cv2.resize: (первый аргумент, остальные аргументы); вызов проходит дальше."""
    calls: list[tuple[object, tuple]] = []
    original = cv2.resize

    def spy(src, *args, **kwargs):
        calls.append((src, args))
        return original(src, *args, **kwargs)

    monkeypatch.setattr(cv2, "resize", spy)
    return calls


def _median_ms(presenter, frame: np.ndarray) -> float:
    durations: list[float] = []
    for _ in range(CALLS_PER_SERIES):
        started = time.perf_counter()
        presenter.on_frame(SLOT_ID, frame)
        durations.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(durations)


# --------------------------------------------------------------------------- REDS


def test_on_frame_median_below_3ms_1440x1080(qtbot) -> None:
    """Кадр 1440x1080x3 в метке 480x360: лучшая из трёх медиан по 50 вызовов on_frame не больше 3,0 мс."""
    env = _setup(qtbot)
    frame = np.random.default_rng(0).integers(0, 256, size=(1080, 1440, 3), dtype=np.uint8)
    for _ in range(WARMUP_CALLS):
        env.presenter.on_frame(SLOT_ID, frame)
    _settle()

    medians: list[float] = []
    for _ in range(SERIES):
        medians.append(_median_ms(env.presenter, frame))
        _settle()

    best = min(medians)
    print(f"on_frame 1440x1080x3 -> метка 480x360: медианы по 50 вызовов, мс: {[round(m, 3) for m in medians]}")
    assert best <= MEDIAN_LIMIT_MS, (
        f"лучшая из трёх медиан {best:.3f} мс > {MEDIAN_LIMIT_MS} мс (медианы {[round(m, 3) for m in medians]}); "
        "кадр не уменьшается до BGR -> RGB или машина занята"
    )


def test_frame_resized_to_slot_size_before_conversion(qtbot, monkeypatch) -> None:
    """Слот получает pixmap 480x360; cv2.resize зовётся один раз над тем же объектом кадра, что пришёл в on_frame."""
    env = _setup(qtbot)
    received = _spy_update_pixmap(env, monkeypatch)
    resize_calls = _spy_cv2_resize(monkeypatch)
    frame = np.zeros((1080, 1440, 3), dtype=np.uint8)

    env.presenter.on_frame(SLOT_ID, frame)

    assert received == [LABEL], f"слот получил pixmap {received}, ожидался один 480x360"
    assert len(resize_calls) == 1, f"cv2.resize вызван {len(resize_calls)} раз, ожидался 1"
    src, args = resize_calls[0]
    assert src is frame, "первый аргумент cv2.resize — не тот объект кадра, что пришёл в on_frame (лишняя копия)"
    assert args[0] == LABEL, f"cv2.resize получил размер {args[0]}, ожидался 480x360"


# --------------------------------------------------------------------------- GUARDS


def test_frame_smaller_than_slot_is_not_enlarged(qtbot, monkeypatch) -> None:
    """Кадр 320x240 в метке 640x480: cv2.resize не вызван, слот получает pixmap 320x240 (увеличивает слот)."""
    env = _setup(qtbot, (640, 480))
    received = _spy_update_pixmap(env, monkeypatch)
    resize_calls = _spy_cv2_resize(monkeypatch)
    frame = np.zeros((240, 320, 3), dtype=np.uint8)

    env.presenter.on_frame(SLOT_ID, frame)

    assert resize_calls == [], f"cv2.resize вызван для кадра не больше метки: {len(resize_calls)} раз"
    assert received == [(320, 240)], f"слот получил pixmap {received}, ожидался один 320x240"


@pytest.mark.parametrize("shape", [(240, 320), (240, 320, 1)], ids=["gray_2d", "gray_hw1"])
def test_small_gray_frame_not_enlarged_and_read_within_buffer(qtbot, monkeypatch, shape) -> None:
    """Серый кадр 320x240 (заливка 100) в метке 640x480: pixmap 320x240, все точки 100 (без чтения за буфером)."""
    env = _setup(qtbot, (640, 480))
    received = _spy_update_pixmap(env, monkeypatch)
    resize_calls = _spy_cv2_resize(monkeypatch)

    env.presenter.on_frame(SLOT_ID, np.full(shape, 100, dtype=np.uint8))

    assert env.presenter.frame_stats(SLOT_ID)["rejected"] == 0
    assert resize_calls == [], "cv2.resize вызван для кадра не больше метки"
    assert received == [(320, 240)], f"слот получил pixmap {received}, ожидался один 320x240"
    image = env.label.pixmap().toImage()
    width, height = image.width(), image.height()
    for x, y in [(2, 2), (width - 3, 2), (width // 2, height // 2), (2, height - 3), (width - 3, height - 3)]:
        colour = image.pixelColor(x, y)
        assert (colour.red(), colour.green(), colour.blue()) == (100, 100, 100), (
            f"точка ({x}, {y}) = {(colour.red(), colour.green(), colour.blue())}, ожидалось (100, 100, 100)"
        )


# --------------------------------------------------------------------------- слот без колбэка


def test_slot_without_callback_scales_itself(qtbot) -> None:
    """Слот без presenter-а и колбэка: ресайз метки перемасштабирует pixmap слотом (_show_scaled)."""
    from PySide6.QtGui import QPixmap

    from multiprocess_prototype.frontend.widgets.image_panel.display_slot import DisplaySlot

    slot = DisplaySlot(SLOT_ID)
    qtbot.addWidget(slot)
    label = slot.findChild(QLabel, "DisplaySlotLabel")
    slot.show()
    _settle()
    pixmap = QPixmap(320, 240)
    pixmap.fill()
    slot.update_pixmap(pixmap)

    slot.resize(slot.width() + 160, slot.height() + 120)
    _settle()

    shown = label.pixmap()
    assert shown is not None and not shown.isNull(), "после ресайза слот без колбэка потерял кадр"
    assert (shown.width(), shown.height()) == (label.width(), label.height()), (
        f"pixmap {shown.width()}x{shown.height()} не равен метке {label.width()}x{label.height()}"
    )


def test_callback_returning_false_falls_back_to_show_scaled(qtbot) -> None:
    """Колбэк вернул False (нет сырого кадра): resizeEvent всё равно масштабирует pixmap слота."""
    from PySide6.QtGui import QPixmap

    from multiprocess_prototype.frontend.widgets.image_panel.display_slot import DisplaySlot

    slot = DisplaySlot(SLOT_ID)
    qtbot.addWidget(slot)
    label = slot.findChild(QLabel, "DisplaySlotLabel")
    calls: list[int] = []
    slot.set_resize_callback(lambda: calls.append(1) or False)
    slot.show()
    _settle()
    pixmap = QPixmap(320, 240)
    pixmap.fill()
    slot.update_pixmap(pixmap)
    calls.clear()

    slot.resize(slot.width() + 160, slot.height() + 120)
    _settle()

    assert calls, "колбэк ресайза не вызван при показанном изображении"
    shown = label.pixmap()
    assert shown is not None and not shown.isNull(), "колбэк вернул False, а слот не перерисовал кадр"
    assert (shown.width(), shown.height()) == (label.width(), label.height())


def test_resize_without_raw_frame_scales_slot_pixmap(qtbot) -> None:
    """Настоящие presenter и слот: pixmap пришёл мимо on_frame (сырого кадра нет), ресайз всё равно его масштабирует."""
    from PySide6.QtGui import QPixmap

    env = _setup(qtbot)
    pixmap = QPixmap(320, 240)
    pixmap.fill()
    env.slot.update_pixmap(pixmap)
    _settle()

    env.slot.resize(env.slot.width() + 160, env.slot.height() + 120)
    _settle()

    shown = env.label.pixmap()
    assert shown is not None and not shown.isNull(), "pixmap без сырого кадра пропал после ресайза"
    assert (shown.width(), shown.height()) == (env.label.width(), env.label.height()), (
        f"pixmap {shown.width()}x{shown.height()} не масштабирован до метки {env.label.width()}x{env.label.height()}"
    )


def test_target_size_has_floor_320x240(qtbot) -> None:
    """target_size() — размер метки, но не ниже защитного предела 320x240 (метка меньше предела — берётся предел)."""
    from multiprocess_prototype.frontend.widgets.image_panel.display_slot import DisplaySlot

    slot = DisplaySlot(SLOT_ID)
    qtbot.addWidget(slot)
    label = slot.findChild(QLabel, "DisplaySlotLabel")
    # Предел QLabel (320x240) снят, чтобы метка могла быть меньше защитного предела target_size.
    label.setMinimumSize(0, 0)
    label.resize(100, 50)
    assert (label.width(), label.height()) == (100, 50), "страж: метка не уменьшилась, тест вакуумен"

    assert slot.target_size() == (320, 240), f"метка 100x50: target_size {slot.target_size()}, ожидалось (320, 240)"

    label.resize(500, 400)
    assert slot.target_size() == (500, 400), f"метка 500x400: target_size {slot.target_size()}, ожидалось (500, 400)"


@pytest.mark.parametrize("registered", [True, False])
def test_rerender_without_raw_frame_returns_false(qtbot, registered) -> None:
    """Нет сырого кадра (или слот не зарегистрирован): _rerender возвращает False и ничего не рисует."""
    env = _setup(qtbot)
    slot_id = SLOT_ID if registered else "unknown"

    assert env.presenter._rerender(slot_id) is False
    assert env.label.pixmap() is None or env.label.pixmap().isNull()


def test_unregistered_live_slot_resize_does_not_touch_new_slot(qtbot) -> None:
    """Старый слот отписан, но жив; на его id зарегистрирован новый слот без кадра. Ресайз старого новый не трогает."""
    from multiprocess_prototype.frontend.widgets.image_panel.display_slot import DisplaySlot

    env = _setup(qtbot)
    env.presenter.on_frame(SLOT_ID, np.zeros((1080, 1440, 3), dtype=np.uint8))
    env.presenter.unregister_slot(SLOT_ID)
    new_slot = DisplaySlot(SLOT_ID)
    qtbot.addWidget(new_slot)
    env.presenter.register_slot(SLOT_ID, new_slot)
    new_slot.show()
    _settle()
    new_label = new_slot.findChild(QLabel, "DisplaySlotLabel")
    assert new_label.pixmap() is None or new_label.pixmap().isNull(), "страж: у нового слота уже есть кадр"

    env.slot.resize(env.slot.width() + 100, env.slot.height() + 80)
    _settle()

    assert new_label.pixmap() is None or new_label.pixmap().isNull(), "ресайз отписанного слота воскресил кадр в новом"
    assert new_label.text() == "Нет сигнала", f"текст нового слота {new_label.text()!r}, ожидалось 'Нет сигнала'"


def test_register_over_occupied_id_old_slot_resize_does_not_touch_new_slot(qtbot) -> None:
    """Новый слот зарегистрирован на занятый id БЕЗ unregister: ресайз вытесненного слота новый не трогает."""
    from multiprocess_prototype.frontend.widgets.image_panel.display_slot import DisplaySlot

    env = _setup(qtbot)
    env.presenter.on_frame(SLOT_ID, np.zeros((1080, 1440, 3), dtype=np.uint8))
    new_slot = DisplaySlot(SLOT_ID)
    qtbot.addWidget(new_slot)
    env.presenter.register_slot(SLOT_ID, new_slot)
    new_slot.show()
    _settle()
    new_label = new_slot.findChild(QLabel, "DisplaySlotLabel")
    assert new_label.pixmap() is None or new_label.pixmap().isNull(), "страж: у нового слота уже есть кадр"

    env.slot.resize(env.slot.width() + 100, env.slot.height() + 80)
    _settle()

    assert new_label.pixmap() is None or new_label.pixmap().isNull(), "ресайз вытесненного слота воскресил кадр в новом"
    assert new_label.text() == "Нет сигнала", f"текст нового слота {new_label.text()!r}, ожидалось 'Нет сигнала'"
    assert env.label.pixmap() is not None and not env.label.pixmap().isNull(), "вытесненный слот потерял свой кадр"


# --------------------------------------------------------------------------- кадр больше метки по одной оси


@pytest.mark.parametrize(
    ("shape", "expected"),
    [
        ((200, 1000, 3), (480, 96)),
        ((1000, 200, 3), (72, 360)),
        ((360, 481, 3), (480, 359)),
        ((361, 480, 3), (478, 360)),
    ],
    ids=["wide_strip", "tall_strip", "width_by_1px", "height_by_1px"],
)
def test_frame_exceeding_label_on_one_axis_only_is_shrunk(qtbot, monkeypatch, shape, expected) -> None:
    """Кадр (H, W, 3) больше метки 480x360 только по одной оси: слот получает вписанный в метку pixmap."""
    env = _setup(qtbot)
    received = _spy_update_pixmap(env, monkeypatch)

    env.presenter.on_frame(SLOT_ID, np.zeros(shape, dtype=np.uint8))

    assert received == [expected], f"кадр {shape}: слот получил {received}, ожидался один {expected}"


@pytest.mark.parametrize(
    ("frame_wh", "expected"),
    [((1440, 1080), (482, 362)), ((1280, 1024), (452, 362))],
    ids=["1440x1080", "1280x1024"],
)
def test_nonstandard_label_size_literal_anchor(qtbot, monkeypatch, frame_wh, expected) -> None:
    """Метка 483x362: размер pixmap — литерал (усечение Qt: 362*1440/1080=482, а не round 483), не QSize.scaled."""
    env = _setup(qtbot, (483, 362))
    received = _spy_update_pixmap(env, monkeypatch)

    env.presenter.on_frame(SLOT_ID, np.zeros((frame_wh[1], frame_wh[0], 3), dtype=np.uint8))

    assert received == [expected], f"кадр {frame_wh}: слот получил {received}, ожидался один {expected}"


def test_degenerate_strip_frame_is_shown_not_rejected(qtbot, monkeypatch) -> None:
    """Кадр (1, 5000, 3): целевая высота по Qt 0 — размер поднят до 1; кадр показан, pixmap 480x1."""
    env = _setup(qtbot)
    received = _spy_update_pixmap(env, monkeypatch)

    env.presenter.on_frame(SLOT_ID, np.zeros((1, 5000, 3), dtype=np.uint8))

    stats = env.presenter.frame_stats(SLOT_ID)
    assert (stats["shown"], stats["rejected"]) == (1, 0), f"stats {stats}, ожидалось shown 1, rejected 0"
    assert received == [(480, 1)], f"слот получил {received}, ожидался один 480x1"


# --------------------------------------------------------------------------- перерисовка: сбой и счётчики


def _grow_label(env: SimpleNamespace, size: tuple[int, int]) -> None:
    for _ in range(4):
        env.slot.resize(
            size[0] + env.slot.width() - env.label.width(),
            size[1] + env.slot.height() - env.label.height(),
        )
        _settle()
        if (env.label.width(), env.label.height()) == size:
            return
    pytest.fail(f"страж: метка не выставилась в {size}")


def test_rerender_failure_falls_back_to_slot_scaling(qtbot, monkeypatch) -> None:
    """cv2.resize падает при перерисовке: исключение не уходит из resizeEvent, слот сам масштабирует pixmap."""
    env = _setup(qtbot)
    env.presenter.on_frame(SLOT_ID, np.zeros((1080, 1440, 3), dtype=np.uint8))
    _settle()

    def boom(*args, **kwargs):
        raise cv2.error("test: cv2.resize failed")

    monkeypatch.setattr(cv2, "resize", boom)
    _grow_label(env, (640, 480))  # исключение из resizeEvent pytest-qt превращает в падение теста

    shown = env.label.pixmap()
    assert shown is not None and not shown.isNull(), "после сбоя перерисовки кадр пропал"
    assert (shown.width(), shown.height()) == (640, 480), (
        f"после сбоя слот показал {shown.width()}x{shown.height()}, ожидалось 640x480 (слот масштабирует сам)"
    )


def test_rerender_does_not_touch_frame_counters(qtbot) -> None:
    """Один on_frame и два ресайза метки: received 1, shown 1, rejected 0 (перерисовка счётчики не трогает)."""
    env = _setup(qtbot)
    env.presenter.on_frame(SLOT_ID, np.zeros((1080, 1440, 3), dtype=np.uint8))

    _grow_label(env, (640, 480))
    _grow_label(env, (320, 240))

    assert env.presenter.frame_stats(SLOT_ID) == {"received": 1, "shown": 1, "rejected": 0}


def test_rerender_failure_is_logged_as_error(qtbot, monkeypatch) -> None:
    """Сбой перерисовки не молчит: одна запись ERROR с id слота (stdlib-путь логгера не зависит от менеджера)."""
    from multiprocess_prototype.frontend.widgets.image_panel import presenter as presenter_module

    errors: list[tuple] = []

    class _RecordingLogger:
        def error(self, msg, *args, **kwargs) -> None:
            errors.append((msg, args))

        def __getattr__(self, name):  # debug/warning/info — молча
            return lambda *args, **kwargs: None

    env = _setup(qtbot)
    env.presenter.on_frame(SLOT_ID, np.zeros((1080, 1440, 3), dtype=np.uint8))
    _settle()

    def boom(*args, **kwargs):
        raise cv2.error("test: cv2.resize failed")

    monkeypatch.setattr(cv2, "resize", boom)
    monkeypatch.setattr(presenter_module, "logger", _RecordingLogger())
    _grow_label(env, (640, 480))

    assert len(errors) == 1, f"записей ERROR {len(errors)}, ожидалась 1: {errors}"
    assert SLOT_ID in errors[0][1], f"в записи нет id слота {SLOT_ID!r}: {errors[0]}"


def _orphan_old_slot(qtbot, how: str) -> SimpleNamespace:
    """Старый слот показал кадр 1440x1080 (pixmap 480x360), затем вытеснен: how = 'unregister' | 'register_over'."""
    from multiprocess_prototype.frontend.widgets.image_panel.display_slot import DisplaySlot

    env = _setup(qtbot)
    env.presenter.on_frame(SLOT_ID, np.zeros((1080, 1440, 3), dtype=np.uint8))
    _settle()
    if how == "unregister":
        env.presenter.unregister_slot(SLOT_ID)
    new_slot = DisplaySlot(SLOT_ID)
    qtbot.addWidget(new_slot)
    env.presenter.register_slot(SLOT_ID, new_slot)
    new_slot.show()
    _settle()
    return env


@pytest.mark.parametrize("how", ["unregister", "register_over"])
def test_orphaned_slot_keeps_scaling_its_own_pixmap(qtbot, how) -> None:
    """Вытесненный слот (после unregister или регистрации поверх id) на росте метки сам масштабирует pixmap."""
    env = _orphan_old_slot(qtbot, how)
    before = env.label.pixmap()
    assert (before.width(), before.height()) == (480, 360), "страж: у старого слота не 480x360 до роста"

    _grow_label(env, (640, 480))

    shown = env.label.pixmap()
    assert shown is not None and not shown.isNull(), "старый слот потерял кадр"
    assert (shown.width(), shown.height()) == (640, 480), (
        f"старый слот ({how}) показал {shown.width()}x{shown.height()}, ожидалось 640x480 (масштабирует сам)"
    )


def test_new_slot_over_occupied_id_rerenders_from_raw_frame(qtbot) -> None:
    """Слот B зарегистрирован поверх занятого id: ресайз B перерисовывает его из сырого кадра (INTER_AREA, MAD 0)."""
    from PySide6.QtGui import QImage

    from multiprocess_prototype.frontend.widgets.image_panel.display_slot import DisplaySlot

    env = _setup(qtbot)
    new_slot = DisplaySlot(SLOT_ID)
    qtbot.addWidget(new_slot)
    env.presenter.register_slot(SLOT_ID, new_slot)  # без unregister
    new_slot.show()
    _settle()
    new_env = SimpleNamespace(slot=new_slot, label=new_slot.findChild(QLabel, "DisplaySlotLabel"))
    _grow_label(new_env, (320, 240))
    raw = np.random.default_rng(1).integers(0, 256, size=(1080, 1440, 3), dtype=np.uint8)
    env.presenter.on_frame(SLOT_ID, raw)
    _settle()

    _grow_label(new_env, (640, 480))

    shown = new_env.label.pixmap()
    assert shown is not None and not shown.isNull(), "новый слот не показал кадр"
    image = shown.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = image.width(), image.height()
    assert (width, height) == (640, 480), f"новый слот показал {width}x{height}, ожидалось 640x480"
    got = np.frombuffer(image.constBits(), dtype=np.uint8, count=image.sizeInBytes())
    got = got.reshape(height, image.bytesPerLine())[:, : width * 4].reshape(height, width, 4)[:, :, :3]
    reference = cv2.cvtColor(cv2.resize(raw, (640, 480), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    deviation = float(np.abs(got.astype(np.int16) - reference.astype(np.int16)).mean())
    assert deviation == 0.0, (
        f"новый слот: отклонение от INTER_AREA-эталона из сырого кадра {deviation:.4f}, ожидалось 0"
    )
