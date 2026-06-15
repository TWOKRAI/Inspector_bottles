# -*- coding: utf-8 -*-
"""Чистые хелперы секции «Вырез эталона (диск)» — без Qt."""

from __future__ import annotations

import numpy as np
import pytest

from multiprocess_prototype.frontend.widgets.tabs.services.neural.disk_cutter_section import (
    bake_sprite,
    list_images,
    load_sprite,
    next_index,
    render_preview,
    rotate_sprite,
    save_sprite,
)


class _FakePanel:
    """Минимальная заглушка ImagePanelWidget для проверки зеркала превью."""

    def __init__(self) -> None:
        self.slots: list[str] = []
        self.frames: list[tuple[str, tuple]] = []

    def add_slot(self, slot_id: str, label: str = "") -> None:
        self.slots.append(slot_id)

    def remove_slot(self, slot_id: str) -> None:
        if slot_id in self.slots:
            self.slots.remove(slot_id)

    def display_frame(self, slot_id: str, frame) -> None:
        self.frames.append((slot_id, frame.shape))


def _imwrite_unicode(path, image):
    """cv2.imwrite не умеет кириллические/unicode пути на Windows."""
    import cv2

    ok, buf = cv2.imencode(path.suffix, image)
    assert ok
    buf.tofile(str(path))


def _disk_photo(side: int = 200) -> np.ndarray:
    """Синтетический снимок: белый диск с тёмной чёрточкой на тёмно-синем фоне."""
    import cv2

    bgr = np.full((side, side, 3), (60, 30, 20), dtype=np.uint8)  # тёмный фон (BGR)
    cv2.circle(bgr, (side // 2, side // 2), side // 3, (245, 245, 245), thickness=-1)
    # тёмная вертикальная метка-«глиф» внутри диска (для проверки поворота)
    cv2.line(bgr, (side // 2, side // 3), (side // 2, 2 * side // 3), (20, 20, 20), thickness=6)
    return bgr


def test_load_sprite_returns_square_rgba(tmp_path):
    photo = tmp_path / "снимок.png"  # unicode-путь
    _imwrite_unicode(photo, _disk_photo())

    sprite = load_sprite(photo)
    assert sprite is not None
    assert sprite.ndim == 3 and sprite.shape[2] == 4  # RGBA
    assert sprite.shape[0] == sprite.shape[1]  # квадрат
    # альфа непустая (диск вырезан), но не весь кадр (углы прозрачны)
    alpha = sprite[:, :, 3]
    assert alpha.max() == 255
    assert alpha[0, 0] == 0  # угол прозрачен


def test_load_sprite_none_on_bad_file(tmp_path):
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"not an image")
    assert load_sprite(bad) is None


def test_rotate_sprite_preserves_shape():
    rgba = np.zeros((40, 40, 4), dtype=np.uint8)
    rgba[10:30, 18:22] = (255, 255, 255, 255)
    rotated = rotate_sprite(rgba, 37.0)
    assert rotated.shape == rgba.shape
    # поворот на 0 — no-op (тот же массив)
    assert rotate_sprite(rgba, 0.0) is rgba


def test_bake_sprite_resizes_to_size():
    rgba = np.zeros((60, 60, 4), dtype=np.uint8)
    rgba[:, :, 3] = 255
    baked = bake_sprite(rgba, 15.0, size=128)
    assert baked.shape == (128, 128, 4)


def test_render_preview_rgb_box():
    rgba = np.zeros((50, 50, 4), dtype=np.uint8)
    rgba[:, :, :3] = 255
    rgba[:, :, 3] = 255
    preview = render_preview(rgba, 0.0, grid=True, box=120)
    assert preview.shape == (120, 120, 3)  # RGB, без альфы
    assert preview.dtype == np.uint8


def test_next_index_and_save_sprite(tmp_path):
    rgba = np.zeros((40, 40, 4), dtype=np.uint8)
    rgba[:, :, 3] = 255

    out = tmp_path / "sprites"
    assert next_index(out / "б") == 0

    p0 = save_sprite(rgba, out, "б", size=64)  # кириллический класс
    assert p0.name == "000.png"
    assert p0.exists()
    assert (out / "б" / "meta.yaml").exists()

    p1 = save_sprite(rgba, out, "б", size=64)
    assert p1.name == "001.png"
    assert next_index(out / "б") == 2


def test_saved_sprite_is_rgba_of_requested_size(tmp_path):
    from PIL import Image

    rgba = np.zeros((40, 40, 4), dtype=np.uint8)
    rgba[:, :, 3] = 255
    target = save_sprite(rgba, tmp_path, "x", size=96, angle=22.0)
    with Image.open(target) as im:
        assert im.mode == "RGBA"
        assert im.size == (96, 96)


@pytest.mark.parametrize("angle", [-180, -1, 0, 1, 90, 180])
def test_rotate_sprite_various_angles(angle):
    rgba = np.zeros((32, 32, 4), dtype=np.uint8)
    rgba[8:24, 14:18] = (255, 255, 255, 255)
    assert rotate_sprite(rgba, float(angle)).shape == rgba.shape


def test_widget_full_flow_via_section_factory(qtbot, tmp_path):
    """Сборка через реальную фабрику секции + сквозной путь без QFileDialog.

    Превью теперь только в верхней панели (локального дисплея в виджете нет),
    поэтому здесь проверяем проводку слайдера/сетки (без падений) и
    «Готово» → save_sprite → файл; зеркало в панель — в test_top_display_mirror.
    """
    pytest.importorskip("PySide6")
    from multiprocess_prototype.frontend.widgets.tabs.services.neural import build_neural_sections
    from multiprocess_prototype.frontend.widgets.tabs.services.neural.disk_cutter_section import (
        DiskCutterWidget,
    )

    # секция реально собирается и отдаёт наш виджет
    specs = build_neural_sections(None, None, parent_key="neural_networks")
    section = next(s.factory(None) for s in specs if s.key == "__nn_disk_cutter__")
    widget = section.widget()
    qtbot.addWidget(widget)
    assert isinstance(widget, DiskCutterWidget)
    assert not hasattr(widget, "display")  # локального дисплея в виджете больше нет

    # подготовить снимок и прогнать путь, минуя файловый диалог
    photo = tmp_path / "снимок.png"
    _imwrite_unicode(photo, _disk_photo())
    widget._sprite = load_sprite(photo)
    assert widget._sprite is not None
    widget.done_btn.setEnabled(True)

    # слайдер угла и сетка не роняют рендер (без панели — no-op)
    widget.angle_slider.setValue(20)
    assert widget.angle_label.text() == "20°"
    widget.grid_check.setChecked(True)

    # «Готово» → файл на диске
    widget.class_edit.setText("б")
    widget.out_edit.setText(str(tmp_path / "out"))
    widget.size_spin.setValue(128)
    widget._on_done()
    saved = tmp_path / "out" / "б" / "000.png"
    assert saved.exists()
    assert "Сохранено" in widget.status_label.text()


def test_list_images(tmp_path):
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "b.JPG").write_bytes(b"x")
    (tmp_path / "note.txt").write_text("nope", encoding="utf-8")
    found = list_images(tmp_path)
    assert [p.name for p in found] == ["a.png", "b.JPG"]
    assert list_images(tmp_path / "missing") == []


def test_widget_auto_advance_after_save(qtbot, tmp_path):
    """После «Готово» виджет сам грузит следующее фото папки, нумеруя эталоны."""
    from multiprocess_prototype.frontend.widgets.tabs.services.neural.disk_cutter_section import (
        DiskCutterWidget,
    )

    src = tmp_path / "src"
    src.mkdir()
    for name in ("p0.png", "p1.png"):
        _imwrite_unicode(src / name, _disk_photo())

    widget = DiskCutterWidget()
    qtbot.addWidget(widget)
    widget._playlist = list_images(src)
    widget._idx = 0
    widget._load_current()
    assert widget._sprite is not None
    assert "[1/2]" in widget.file_label.text()

    out = tmp_path / "out"
    widget.class_edit.setText("к")
    widget.out_edit.setText(str(out))
    widget.size_spin.setValue(96)

    widget._on_done()  # сохранить p0 → авто-переход на p1
    assert (out / "к" / "000.png").exists()
    assert widget._idx == 1
    assert "[2/2]" in widget.file_label.text()
    assert widget._sprite is not None  # следующее загружено

    widget._on_done()  # сохранить p1 → конец плейлиста
    assert (out / "к" / "001.png").exists()
    assert "обработаны" in widget.status_label.text()
    assert not widget.done_btn.isEnabled()


def test_top_display_mirror(qtbot, tmp_path):
    """Превью зеркалится в верхнюю панель: attach → слот, refresh → кадр, detach → убран."""
    from multiprocess_prototype.frontend.widgets.tabs.services.neural.disk_cutter_section import (
        DiskCutterWidget,
    )

    panel = _FakePanel()
    widget = DiskCutterWidget(image_panel=panel)
    qtbot.addWidget(widget)

    photo = tmp_path / "снимок.png"
    _imwrite_unicode(photo, _disk_photo())
    widget._playlist = [photo]
    widget._idx = 0

    widget.attach_top_display()
    assert "disk_cutter" in panel.slots
    widget._load_current()  # триггерит _refresh_preview → кадр в панель
    assert any(slot == "disk_cutter" for slot, _shape in panel.frames)
    # кадр для display_frame — BGR (3 канала), не RGBA
    assert panel.frames[-1][1][2] == 3

    widget.detach_top_display()
    assert "disk_cutter" not in panel.slots


def test_comparison_slots(qtbot, tmp_path):
    """«В сравнение» замораживает вид отдельным слотом; очистка/detach убирают их."""
    from multiprocess_prototype.frontend.widgets.tabs.services.neural.disk_cutter_section import (
        DiskCutterWidget,
    )

    panel = _FakePanel()
    widget = DiskCutterWidget(image_panel=panel)
    qtbot.addWidget(widget)

    photo = tmp_path / "p.png"
    _imwrite_unicode(photo, _disk_photo())
    widget._playlist = [photo]
    widget._idx = 0
    widget.attach_top_display()
    widget._load_current()
    widget.class_edit.setText("ж")

    widget._add_comparison()
    widget._add_comparison()
    cmp_slots = [s for s in panel.slots if s.startswith("disk_cutter_cmp_")]
    assert len(cmp_slots) == 2  # два замороженных вида
    assert widget._cmp_count == 2  # id монотонные

    widget._clear_comparisons()
    assert not any(s.startswith("disk_cutter_cmp_") for s in panel.slots)

    # повторно добавить и проверить, что detach всё чистит
    widget._add_comparison()
    widget.detach_top_display()
    assert panel.slots == []  # ни редактора, ни сравнений


def test_comparison_disabled_without_panel(qtbot):
    """Без верхней панели кнопки сравнения отключены (сравнивать негде)."""
    from multiprocess_prototype.frontend.widgets.tabs.services.neural.disk_cutter_section import (
        DiskCutterWidget,
    )

    widget = DiskCutterWidget(image_panel=None)
    qtbot.addWidget(widget)
    assert not widget.cmp_add_btn.isEnabled()
    assert not widget.cmp_clear_btn.isEnabled()
