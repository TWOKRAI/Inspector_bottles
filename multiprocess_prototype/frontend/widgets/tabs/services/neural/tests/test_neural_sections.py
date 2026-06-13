# -*- coding: utf-8 -*-
"""Секции группы «Нейронные сети»: сборка SectionSpec и базовое поведение виджетов."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from multiprocess_prototype.frontend.widgets.tabs.services.neural import build_neural_sections
from multiprocess_prototype.frontend.widgets.tabs.services.neural.dataset_gen_section import (
    DatasetGenWidget,
)
from multiprocess_prototype.frontend.widgets.tabs.services.neural.ml_inference_section import (
    MlInferenceWidget,
)
from multiprocess_prototype.frontend.widgets.tabs.services.neural.ml_train_section import (
    MlTrainWidget,
)


def test_build_neural_sections_specs():
    specs = build_neural_sections(None, None, parent_key="neural_networks")
    assert [s.key for s in specs] == ["__nn_dataset_gen__", "__nn_ml_train__", "__nn_ml_inference__"]
    assert all(s.parent_key == "neural_networks" for s in specs)
    assert [s.title for s in specs] == ["Генерация датасета", "Обучение", "Модели (инференс)"]


def test_dataset_gen_widget_presets_and_guard(qtbot):
    w = DatasetGenWidget()
    qtbot.addWidget(w)
    # комплектный пресет dataset_gen подхвачен в комбо
    items = [w.preset_combo.itemText(i) for i in range(w.preset_combo.count())]
    assert "ru_letters_disk.yaml" in items
    # пресет загружен в форму: размер кадра из YAML (128×128)
    assert w.size_h_spin.value() == 128 and w.size_w_spin.value() == 128
    assert w.procedural_check.isChecked()  # backgrounds_dir: null
    # нулевые сплиты → генерация не стартует, понятный статус
    for spin in (w.train_spin, w.val_spin, w.test_spin):
        spin.setValue(0)
    w._start_worker("generate")
    assert "нулевые" in w.status_label.text()
    assert w.generate_btn.isEnabled()  # busy-режим не включился


def _imwrite_unicode(path, image):
    """cv2.imwrite не умеет кириллические пути на Windows → imencode + tofile."""
    import cv2

    ok, buf = cv2.imencode(path.suffix, image)
    assert ok
    buf.tofile(str(path))


def _make_data_dirs(tmp_path):
    import numpy as np

    classes = tmp_path / "classes"
    for name in ("А", "Б"):  # кириллица — реальный кейс (классы-буквы)
        d = classes / name
        d.mkdir(parents=True)
        sprite = np.zeros((20, 20, 4), dtype=np.uint8)
        sprite[5:15, 5:15] = (255, 255, 255, 255)
        _imwrite_unicode(d / "base.png", sprite)
    backgrounds = tmp_path / "bg"
    backgrounds.mkdir()
    _imwrite_unicode(backgrounds / "b1.jpg", np.full((40, 60, 3), 90, dtype=np.uint8))
    _imwrite_unicode(backgrounds / "b2.jpg", np.full((40, 60, 3), 120, dtype=np.uint8))
    return classes, backgrounds


def test_dataset_gen_scanners_and_overlay(tmp_path):
    import numpy as np

    from multiprocess_prototype.frontend.widgets.tabs.services.neural.dataset_gen_section import (
        compose_overlay,
        scan_backgrounds,
        scan_classes,
    )

    classes, backgrounds = _make_data_dirs(tmp_path)
    found = scan_classes(classes)
    assert sorted(found) == ["А", "Б"] and all(len(v) == 1 for v in found.values())
    bgs = scan_backgrounds(backgrounds)
    assert len(bgs) == 2
    assert scan_backgrounds(None) == []

    bg = np.full((40, 60, 3), 90, dtype=np.uint8)
    sprite = np.zeros((20, 20, 4), dtype=np.uint8)
    sprite[:, :, :3] = 255
    sprite[:, :, 3] = 255
    out = compose_overlay(bg, sprite, canvas=64)
    assert out.shape == (64, 64, 3)
    assert out[32, 32].tolist() == [255, 255, 255]  # центр — непрозрачный спрайт
    assert out[2, 2].tolist() == [90, 90, 90]  # угол — фон


def test_dataset_gen_preset_roundtrip(tmp_path):
    from multiprocess_prototype.frontend.widgets.tabs.services.neural.dataset_gen_section import (
        load_preset_fields,
        save_preset_fields,
    )

    preset = tmp_path / "p.yaml"
    preset_text = (
        "# комментарий сохраняется\n"
        "catalog:\n  classes_dir: cls\n  backgrounds_dir: null\n"
        "output:\n  size: [128, 128]\n"
    )
    preset.write_text(preset_text, encoding="utf-8")
    fields = load_preset_fields(preset)
    assert fields["classes_dir"] == (tmp_path / "cls").resolve()
    assert fields["backgrounds_dir"] is None

    save_preset_fields(preset, classes_dir=tmp_path / "cls2", backgrounds_dir=tmp_path / "bg", size_hw=(96, 64))
    text = preset.read_text(encoding="utf-8")
    assert "# комментарий сохраняется" in text  # ruamel round-trip
    fields2 = load_preset_fields(preset)
    assert fields2["classes_dir"] == (tmp_path / "cls2").resolve()
    assert fields2["backgrounds_dir"] == (tmp_path / "bg").resolve()
    assert (fields2["size_h"], fields2["size_w"]) == (96, 64)


def test_dataset_gen_data_tab_panels(qtbot, tmp_path):
    classes, backgrounds = _make_data_dirs(tmp_path)
    w = DatasetGenWidget()
    qtbot.addWidget(w)
    w.classes_edit.setText(str(classes))
    w.procedural_check.setChecked(False)
    w.backgrounds_edit.setText(str(backgrounds))
    w._rescan_data()
    assert [w.class_combo.itemText(i) for i in range(w.class_combo.count())] == ["А", "Б"]
    assert "Классов: 2" in w.data_info.text()
    # листание фонов циклично
    w._step_bg(1)
    assert w._bg_idx == 1
    w._step_bg(1)
    assert w._bg_idx == 0


def test_ml_train_widget_configs_and_runs_table(qtbot):
    w = MlTrainWidget()
    qtbot.addWidget(w)
    items = [w.config_combo.itemText(i) for i in range(w.config_combo.count())]
    assert "ru_letters_synthetic.yaml" in items  # пресет ml_train
    assert w.runs_table.columnCount() == 6
    # без выбранного конфига запуск не падает, а пишет статус
    w.config_combo.clear()
    w._on_train()
    assert "Не выбран конфиг" in w.status_label.text()
    assert w._process is None


def test_ml_inference_widget_lists_models(qtbot, tmp_path, monkeypatch):
    import multiprocess_prototype.frontend.widgets.tabs.services.neural.ml_inference_section as mod

    # подменяем каталог моделей на tmp с одной валидной парой весов+sidecar
    (tmp_path / "m1.onnx").write_bytes(b"fake")
    (tmp_path / "m1.yaml").write_text(
        "name: Test Model\ntask: classification\nbackend: onnx\ninput_size: [32, 32]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_MODELS_DIR", tmp_path)

    w = MlInferenceWidget()
    qtbot.addWidget(w)
    assert w.table.rowCount() == 1
    assert w.table.item(0, 0).text() == "m1"
    assert w.table.item(0, 4).text() == "32×32"
    assert "Моделей: 1" in w.count_label.text()
