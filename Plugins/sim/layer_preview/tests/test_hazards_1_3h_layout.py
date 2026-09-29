# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 1.3h-a — механизм `preset.layout` / `ObjectFactory.nominal_layers`.

Что в ЭТОЙ механике может сломаться, учитывая, как она устроена:

(a) `nominal_layers` и `make()` делят `_resolve_bottom_layers` — три розыгрыша rng в фиксированном
    порядке (integers -> uniform угла -> get_sprite). Превью-плитка и раскладка слоёв обязаны
    показывать ОДИН класс для одного seed: если кто-то поменяет порядок или конструкцию rng в
    `render_layout`, оператор увидит в редакторе слоёв не тот класс, что в плитке.
(b) `nominal_layers` не имеет права ни читать, ни гасить `force_defect_next()`: команда
    раскладки — это просмотр, нажатие оператора «следующий брак» она съесть не должна.
(c) Рефакторинг `make()` (вынос `_resolve_bottom_layers`) не должен сдвинуть ни одного розыгрыша:
    seed-контракт LS-006 — каждый объект ленты для каждого seed. Отпечатки сняты на ИСХОДНОМ
    коде (`c4fdee66`, до выноса) и вписаны литералами; расчёт «ожидаемого» из самого кода
    согласился бы с любым ответом.

Фикстура — своя (спрайты из фиксированного numpy-зерна, не константа: побитовая проверка на
одноцветных картинках слепа к перестановке пикселей).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import CLASS_SPRITE_SOURCE, LayerSpec, ScenePreset
from Services.line_sim.core.factory import ObjectFactory
from Services.line_sim.core.preview import render_preview_grid

_SEEDS = range(5)

#: Отпечатки (sha256[:16] от байт render() + class_name + angle_deg + defect) `make()` до выноса
#: `_resolve_bottom_layers`: ключ — вариант пресета, значение — по одному на seed 0..4.
_EXPECTED: dict[str, list[str]] = {
    "class_layer": ["dafe222d448bce45", "88aa46fc345ed895", "eed5374d890533f8", "101edcabdbbbec7d", "aace3566517cff2c"],
    "auto_base": ["2cd9410ae2319021", "805108b7c5a4b3bd", "f2c03c61cab0f5b5", "cb972639c41545f3", "19b3e1f8a2201dd4"],
    "no_catalog": ["b8b0c5c883ad1976", "8c728a03acf9bc3a", "a1b661cec64f882c", "59872064efeb4de3", "0779249b8d20ecf6"],
}


def _rand_sprite(rng: np.random.Generator, side: int) -> np.ndarray:
    """RGBA-спрайт со случайными цветами и круглой альфой (не константа)."""
    sprite = rng.integers(0, 256, size=(side, side, 4), dtype=np.uint8)
    yy, xx = np.mgrid[:side, :side]
    inside = (yy - side / 2) ** 2 + (xx - side / 2) ** 2 <= (side / 2) ** 2
    sprite[:, :, 3] = np.where(inside, 255, 0)
    return sprite


def _write_png(path: Path, rgba: np.ndarray) -> None:
    imwrite_unicode(path, cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))


def _make_fixture(tmp_path: Path) -> Path:
    """`cat/<A|B>/0.png` (случайные 30x30) + `disk.png` + `preset.yaml` с class://-слоем; вернуть путь пресета."""
    data_rng = np.random.default_rng(1234)
    for cls in ("A", "B"):
        (tmp_path / "cat" / cls).mkdir(parents=True)
        _write_png(tmp_path / "cat" / cls / "0.png", _rand_sprite(data_rng, 30))
    _write_png(tmp_path / "disk.png", _rand_sprite(data_rng, 48))
    preset = ScenePreset(
        catalog_dir=str(tmp_path / "cat"),
        angle_range_deg=(-30.0, 30.0),
        defect_probability=0.0,
        layers=[
            LayerSpec(name="disk", mode="static", sprite_source=str(tmp_path / "disk.png"), color_rgb=(255, 255, 255)),
            LayerSpec(name="letter", mode="static", sprite_source=CLASS_SPRITE_SOURCE, color_rgb=(0, 0, 0)),
        ],
    )
    preset_path = tmp_path / "preset.yaml"
    preset.to_yaml(preset_path)
    return preset_path


def _new_preview(preset_path: Path):
    from Plugins.sim.layer_preview.plugin import LayerPreviewPlugin

    ctx = MagicMock()
    ctx.config = {"preset_path": str(preset_path)}
    plugin = LayerPreviewPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin


def _presets(tmp_path: Path) -> dict[str, ScenePreset]:
    """Три ветки `make()`: class://-слой, авто-`base`-слой, пресет без каталога; брак 50% — ветка дефекта."""
    preset_path = _make_fixture(tmp_path)
    with_class = ScenePreset.from_yaml(preset_path).model_copy(update={"defect_probability": 0.5})
    auto_base = with_class.model_copy(
        update={"layers": [with_class.layers[0].model_copy(update={"offset_px": (5, -3), "angle_deg": 20.0})]}
    )
    no_catalog = ScenePreset(
        angle_range_deg=(-30.0, 30.0),
        defect_probability=0.5,
        layers=[LayerSpec(name="disk", mode="static", sprite_source=str(tmp_path / "disk.png"))],
    )
    return {"class_layer": with_class, "auto_base": auto_base, "no_catalog": no_catalog}


def _fingerprints(tmp_path: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for variant, preset in _presets(tmp_path).items():
        factory = ObjectFactory(preset)
        digests = []
        for seed in _SEEDS:
            obj = factory.make(f"fp-{seed}", 0.0, np.random.default_rng(seed))
            passport = obj.passport
            h = hashlib.sha256(obj.render().tobytes())
            h.update(f"|{passport.class_name}|{passport.angle_deg!r}|{passport.defect}".encode())
            digests.append(h.hexdigest()[:16])
        result[variant] = digests
    return result


# --------------------------------------------------------------------------- #
# (a) class_name раскладки == class_name плитки превью для того же seed        #
# --------------------------------------------------------------------------- #


def test_a_layout_class_name_equals_preview_tile_class_name(tmp_path: Path) -> None:
    preset_path = _make_fixture(tmp_path)
    plugin = _new_preview(preset_path)
    seeds = list(range(10))

    _, tiles = render_preview_grid(ScenePreset.from_yaml(preset_path), seeds, 32)
    layout_names = []
    for seed in seeds:
        res = plugin.cmd_preset_layout({"seed": seed})
        assert res["status"] == "ok", res
        layout_names.append(res["class_name"])

    assert layout_names == [tile["class_name"] for tile in tiles], (layout_names, tiles)
    assert set(layout_names) == {"A", "B"}, f"seeds 0..9 дали один класс {set(layout_names)} — тест вакуумен"


# --------------------------------------------------------------------------- #
# (b) force_defect_next() переживает nominal_layers                            #
# --------------------------------------------------------------------------- #


def test_b_nominal_layers_keeps_force_defect_pending(tmp_path: Path) -> None:
    factory = ObjectFactory(_presets(tmp_path)["class_layer"].model_copy(update={"defect_probability": 0.0}))
    factory.force_defect_next()
    assert factory.force_defect_pending is True

    class_name, layers = factory.nominal_layers(np.random.default_rng(3))

    assert class_name in {"A", "B"}
    assert [name for name, *_ in layers] == ["disk", "letter"], "defect-слой не должен попадать в раскладку"
    assert factory.force_defect_pending is True, "nominal_layers погасил force_defect_next()"
    obj = factory.make("after", 0.0, np.random.default_rng(3))
    assert obj.passport.defect == "damaged", "следующий make() после nominal_layers не получил форсированный дефект"
    assert factory.force_defect_pending is False


# --------------------------------------------------------------------------- #
# (c) make() после выноса _resolve_bottom_layers — побитово прежний            #
# --------------------------------------------------------------------------- #


def test_c_make_output_unchanged_by_resolve_bottom_layers_extraction(tmp_path: Path) -> None:
    assert _fingerprints(tmp_path) == _EXPECTED
