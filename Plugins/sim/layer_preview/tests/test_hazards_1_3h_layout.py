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
import pytest

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


# --------------------------------------------------------------------------- #
# Итерация 2 ревью 1.3h-a: origin_px, canvas_size без _compose, read-only      #
# --------------------------------------------------------------------------- #
#
# Что тут может сломаться. (1) Страница ставит PNG слоя по `center_px`, а лента — по
# `int(round(cx - sw/2))` (банкирское округление `composite`): при полупиксельном
# положении JS `Math.round` даёт другой пиксель, редактор рисует не то, что увидит лента.
# Поэтому ответ несёт целый угол `origin_px`, и тест собирает объект ленты ИМЕННО по нему.
# (2) `render_layout` считал размер канвы полным `_compose` (для offset 20000 px это канва
# 40000 px — сотни мс и сотни МБ ради двух чисел). (3) `nominal_layers` отдавал ссылки на
# кэш фабрики (`_transform` без трансформа возвращает сам спрайт): запись через ответ
# портит все следующие `make()`.


def _origin_fixture(tmp_path: Path) -> ScenePreset:
    """Пресет без каталога, слои static: угол 37 (повёрнутый размер нечётный) + дробные смещения;
    диапазон угла объекта [0, 0], брак 0 — объект ленты для любого seed один и тот же."""
    data_rng = np.random.default_rng(99)
    paths = {}
    for name, (h, w) in {"a": (30, 30), "b": (21, 14)}.items():
        sprite = data_rng.integers(0, 256, size=(h, w, 4), dtype=np.uint8)
        sprite[:, :, 3] = data_rng.choice([0, 90, 255], size=(h, w)).astype(np.uint8)  # полупрозрачные пиксели
        _write_png(tmp_path / f"{name}.png", sprite)
        paths[name] = str(tmp_path / f"{name}.png")
    return ScenePreset(
        angle_range_deg=(0.0, 0.0),
        defect_probability=0.0,
        layers=[
            LayerSpec(name="a", mode="static", sprite_source=paths["a"], angle_deg=37.0, offset_px=(3.5, -2.0)),
            LayerSpec(name="b", mode="static", sprite_source=paths["b"], offset_px=(-1.5, 4.0)),
        ],
    )


def _decode_layer(layer: dict) -> np.ndarray:
    import base64

    raw = np.frombuffer(base64.b64decode(layer["png_b64"]), dtype=np.uint8)
    return cv2.cvtColor(cv2.imdecode(raw, cv2.IMREAD_UNCHANGED), cv2.COLOR_BGRA2RGBA)


def _over_premultiplied(pm: np.ndarray, a: np.ndarray, sprite: np.ndarray, x0: int, y0: int) -> None:
    """Свой малый «over» в целый угол (x0, y0): та же арифметика, что `compose.composite`,
    но место задано снаружи, без собственного выбора угла. Пишет в pm/a на месте."""
    sh, sw = sprite.shape[:2]
    bh, bw = a.shape
    bx0, by0, bx1, by1 = max(0, x0), max(0, y0), min(bw, x0 + sw), min(bh, y0 + sh)
    region = sprite[by0 - y0 : by1 - y0, bx0 - x0 : bx1 - x0]
    alpha = region[:, :, 3:4].astype(np.float32) / 255.0
    fg = region[:, :, :3].astype(np.float32)
    bg = pm[by0:by1, bx0:bx1].astype(np.float32)
    pm[by0:by1, bx0:bx1] = np.clip(fg * alpha + bg * (1.0 - alpha) + 0.5, 0, 255).astype(np.uint8)
    white = np.full_like(fg, 255.0)
    a3 = np.repeat(a[by0:by1, bx0:bx1, None], 3, axis=2).astype(np.float32)
    a[by0:by1, bx0:bx1] = np.clip(white * alpha + a3 * (1.0 - alpha) + 0.5, 0, 255).astype(np.uint8)[:, :, 0]


def _assemble_by_origin(result: dict) -> np.ndarray:
    w, h = result["canvas_px"]
    pm = np.zeros((h, w, 3), dtype=np.uint8)
    a = np.zeros((h, w), dtype=np.uint8)
    for layer in result["layers"]:
        x0, y0 = layer["origin_px"]
        _over_premultiplied(pm, a, _decode_layer(layer), x0, y0)
    af = a.astype(np.float32)
    rgb = np.where(af[:, :, None] > 0, pm.astype(np.float32) * 255.0 / np.maximum(af, 1.0)[:, :, None], 0.0)
    return np.dstack([np.clip(rgb + 0.5, 0, 255).astype(np.uint8), a])


def test_origin_px_assembles_belt_object_bitwise(tmp_path: Path) -> None:
    from Services.line_sim.core.preview import render_layout

    preset = _origin_fixture(tmp_path)
    factory = ObjectFactory(preset)
    for seed in range(6):
        result = render_layout(preset, seed)
        belt = factory.make(f"o-{seed}", 0.0, np.random.default_rng(seed)).render()
        assembled = _assemble_by_origin(result)
        assert assembled.shape == belt.shape, (seed, assembled.shape, belt.shape)
        assert np.array_equal(assembled, belt), f"seed {seed}: сборка по origin_px != объект ленты"


def test_origin_px_differs_from_js_round_somewhere(tmp_path: Path) -> None:
    """Страж вакуумности теста выше: есть слой, чей неокруглённый угол ровно .5 и где банкирское
    `round` расходится с JS `Math.round` (floor(v + 0.5)) — иначе тест собрал бы объект и по центру."""
    import math

    from Services.line_sim.core.preview import render_layout

    result = render_layout(_origin_fixture(tmp_path), 0)
    cw, ch = result["canvas_px"]
    diverging = []
    for layer in result["layers"]:
        (cx, cy), (sw, sh) = layer["center_px"], layer["size_px"]
        for raw in (cw / 2.0 + cx - sw / 2.0, ch / 2.0 + cy - sh / 2.0):
            if raw % 1 == 0.5 and round(raw) != math.floor(raw + 0.5):
                diverging.append((layer["name"], raw))
    assert diverging, "в фикстуре нет полупиксельного случая с расхождением round/Math.round"
    assert any(layer["size_px"][0] % 2 == 1 for layer in result["layers"]), "нет слоя нечётной ширины"


def test_canvas_px_equals_belt_render_shape(tmp_path: Path) -> None:
    from Services.line_sim.core.preview import render_layout

    preset = _origin_fixture(tmp_path)
    factory = ObjectFactory(preset)
    for seed in range(4):
        belt = factory.make(f"c-{seed}", 0.0, np.random.default_rng(seed)).render()
        canvas = render_layout(preset, seed)["canvas_px"]
        assert canvas == [belt.shape[1], belt.shape[0]], (seed, canvas, belt.shape)
    assert canvas == [50, 48], "фикстура должна давать непустую канву с нечётным слоем внутри"


def test_nominal_layers_arrays_read_only(tmp_path: Path) -> None:
    preset = _origin_fixture(tmp_path)
    # слой без трансформа: `_transform` вернул бы сам кэш фабрики, а не копию
    plain = LayerSpec(name="plain", mode="static", sprite_source=preset.layers[1].sprite_source)
    preset = preset.model_copy(update={"layers": [preset.layers[0], plain]})
    factory = ObjectFactory(preset)
    before = factory.make("r", 0.0, np.random.default_rng(3)).render().tobytes()

    _, layers = factory.nominal_layers(np.random.default_rng(3))

    assert [name for name, *_ in layers] == ["a", "plain"]
    for name, arr, _ox, _oy in layers:
        assert arr.flags.writeable is False, f"слой {name}: массив записываемый"
    with pytest.raises(ValueError):
        layers[1][1][:] = 0  # запись в «plain» не должна дойти до кэша фабрики
    after = factory.make("r", 0.0, np.random.default_rng(3)).render().tobytes()
    assert after == before, "make() после nominal_layers изменился"


def test_render_layout_does_not_compose(tmp_path: Path) -> None:
    """Наблюдаемая цена, а не имя вызова: слой со смещением 20000 px раньше давал канву
    40000 px через полный `_compose` (ревью: 714 мс на слое 1200 px). Фикстура: второй слой
    x30 (630x420 px) со смещением 20000 -> канва 40420x630. Замер 2026-09-29, прогретый кэш:
    ДО правки 1491-1698 мс, ПОСЛЕ 10 мс. Граница 150 мс: в 15 раз выше замера после правки
    (запас на загруженную машину) и в 10 раз ниже замера до правки."""
    import time

    from Services.line_sim.core.preview import render_layout

    preset = _origin_fixture(tmp_path)
    far = preset.layers[1].model_copy(update={"offset_px": (20000.0, 0.0), "scale": 30.0})
    preset = preset.model_copy(update={"layers": [preset.layers[0], far]})
    render_layout(preset, 0)  # прогрев кэша фабрики
    start = time.perf_counter()
    result = render_layout(preset, 0)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    assert result["canvas_px"][0] > 40000, result["canvas_px"]
    assert elapsed_ms < 150.0, f"render_layout со смещением 20000 px: {elapsed_ms:.0f} мс"
