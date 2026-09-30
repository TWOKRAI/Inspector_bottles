# -*- coding: utf-8 -*-
"""Hazard-тесты автора для Task 1.1b, блоки C/D (инструмент `make_font_letters`,
пресет `letters_layered.yaml`) — что может сломаться именно в ЭТОМ механизме, а не в
общей приёмке (`test_acceptance_1_1b_font_tool.py`).

Что проверяется и почему:
    H1. `build_disk()` — диаметр `size_px`, центр непрозрачный белый (255,255,255,255),
        углы канвы прозрачны (альфа 0): эллипс не касается краёв квадратной канвы, а
        `cv2.INTER_AREA`-даунсемпл 4x->1x не должен размазать угол в полупрозрачный.
    H2. Полный конвейер: инструмент строит каталог классов-букв + диск во ВРЕМЕННОМ
        каталоге -> `ScenePreset` со СТРУКТУРОЙ слоёв боевого `letters_layered.yaml`
        (disk снизу, class:// сверху, те же `color_rgb`) -> `ObjectFactory.make()` по
        20 seed'ам: центр рендера — чёрный (заливка слоя-буквы), где-то в пределах
        диска, но вне буквы — белое кольцо (заливка слоя-диска), и хотя бы для одного
        класса за 20 seed'ов проявляются ОБА шрифта (`SpriteCatalog.get_sprite`
        выбирает файл класса случайно — при двух файлах на класс совпадение всех 20
        выборов на одном файле практически невозможно, но чтобы не зависеть от
        точной вероятности, алфавит взят из двух букв, а различие подтверждается
        побайтовым сравнением рендеров, не именем файла).
    H3. Боевой `Services/line_sim/presets/letters_layered.yaml` реально грузится
        `ScenePreset.from_yaml()` (не только руками собранный пресет из H2) и имеет
        РОВНО один слой `class://`, идущий ПОСЛЕ слоя `disk` в списке (буква поверх
        диска, не наоборот — иначе диск замажет букву).

Алфавит H2 — «НХ» (не «АК», как в приёмке): у этих двух букв у ОБОИХ шрифтов
(DejaVuSans/-Bold) центр альфа-bbox гарантированно непрозрачен (замерено вручную
перед написанием теста) — у «А» центр приходится на промежуток между ножками буквы
(альфа=0), что сделало бы проверку «центр чёрный» случайно красной в зависимости от
шрифта. Буквы приёмки трогать нельзя (REDS), алфавит этого файла — свой.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import matplotlib
import numpy as np

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import CLASS_SPRITE_SOURCE, LayerSpec, ObjectFactory, ScenePreset
from Services.line_sim.tools.make_font_letters import build_disk, build_font_letters


_PRESET_PATH = Path(__file__).resolve().parents[1] / "presets" / "letters_layered.yaml"

_FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
_DEJAVU_SANS = _FONT_DIR / "DejaVuSans.ttf"
_DEJAVU_SANS_BOLD = _FONT_DIR / "DejaVuSans-Bold.ttf"

# Алфавит H2 — см. докстринг модуля: оба шрифта дают непрозрачный центр у ОБЕИХ букв.
_LETTERS = "НХ"
_SIZE_PX = 80
_LETTER_FRAC = 0.6


def test_disk_centre_opaque_white_corners_transparent() -> None:
    """H1: диск build_disk() — диаметр size_px, центр непрозрачный белый, углы прозрачны."""
    size = 64
    disk = build_disk(size)
    assert disk.shape == (size, size, 4)

    cy, cx = size // 2, size // 2
    assert tuple(int(v) for v in disk[cy, cx]) == (255, 255, 255, 255), "центр диска не непрозрачный белый"

    for y, x in ((0, 0), (0, size - 1), (size - 1, 0), (size - 1, size - 1)):
        assert disk[y, x, 3] == 0, f"угол ({y},{x}) не прозрачен: альфа={disk[y, x, 3]}"


def test_end_to_end_tool_catalog_disk_preset_over_seeds(tmp_path: Path) -> None:
    """H2: инструмент -> каталог+диск во tmp -> пресет со структурой боевого файла ->
    ObjectFactory -> по 20 seed'ам центр чёрный, есть белое кольцо диска, хотя бы один
    класс показывает оба шрифта."""
    catalog_dir = tmp_path / "letters_font"
    disk_path = tmp_path / "letters_font_disk.png"

    build_font_letters(_LETTERS, [_DEJAVU_SANS, _DEJAVU_SANS_BOLD], _SIZE_PX, _LETTER_FRAC, catalog_dir)
    disk_rgba = build_disk(_SIZE_PX)
    imwrite_unicode(disk_path, cv2.cvtColor(disk_rgba, cv2.COLOR_RGBA2BGRA))

    # Та же структура слоёв, что Services/line_sim/presets/letters_layered.yaml (H3
    # сверяет это буквально с файлом) — здесь пути указывают во tmp, не в data/.
    preset = ScenePreset(
        catalog_dir=str(catalog_dir),
        layers=[
            LayerSpec(name="disk", mode="static", sprite_source=str(disk_path), color_rgb=(255, 255, 255)),
            LayerSpec(name="letter", mode="static", sprite_source=CLASS_SPRITE_SOURCE, color_rgb=(0, 0, 0)),
        ],
        defect_probability=0.0,
        angle_range_deg=(0.0, 0.0),
    )
    factory = ObjectFactory(preset)

    renders_by_class: dict[str, list[np.ndarray]] = {}
    for seed in range(1, 21):
        obj = factory.make(f"o{seed}", 0.0, np.random.default_rng(seed))
        frame = obj.render()
        renders_by_class.setdefault(obj.passport.class_name, []).append(frame)

        cy, cx = frame.shape[0] // 2, frame.shape[1] // 2
        centre_rgb = tuple(int(v) for v in frame[cy, cx, 0:3])
        centre_alpha = int(frame[cy, cx, 3])
        assert centre_rgb == (0, 0, 0) and centre_alpha == 255, (
            f"seed={seed}, class={obj.passport.class_name}: центр не чёрный непрозрачный, "
            f"rgb={centre_rgb} alpha={centre_alpha}"
        )

        alpha = frame[:, :, 3]
        rgb = frame[:, :, 0:3]
        ring_mask = (alpha > 0) & np.all(rgb == 255, axis=-1)
        assert ring_mask.any(), f"seed={seed}: не нашлось белого кольца диска вокруг буквы"

    both_fonts_seen = any(len({render.tobytes() for render in renders}) > 1 for renders in renders_by_class.values())
    assert both_fonts_seen, (
        f"ни для одного класса за 20 seed не нашлось двух разных рендеров (оба шрифта): "
        f"классы -> число рендеров {[len(v) for v in renders_by_class.values()]}"
    )


def test_real_preset_file_has_one_class_layer_above_disk() -> None:
    """H3: боевой letters_layered.yaml грузится from_yaml, ровно один слой class://,
    идущий ПОСЛЕ слоя disk (буква поверх диска)."""
    preset = ScenePreset.from_yaml(_PRESET_PATH)

    names = [layer.name for layer in preset.layers]
    assert "disk" in names, f"нет слоя disk в {names}"

    class_indices = [i for i, layer in enumerate(preset.layers) if layer.sprite_source == CLASS_SPRITE_SOURCE]
    assert len(class_indices) == 1, f"ожидали ровно один слой class://, нашли {len(class_indices)}"

    disk_index = names.index("disk")
    assert class_indices[0] > disk_index, "слой class:// (буква) должен идти ПОСЛЕ слоя disk (быть сверху)"
