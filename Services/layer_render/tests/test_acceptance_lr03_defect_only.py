# -*- coding: utf-8 -*-
"""Слепая приёмка ЛР-03 (критерии 1-5), написана ДО реализации.

Пресет сцены без `catalog_dir`, все слои которого `mode="defect"`, должен отклоняться при
загрузке; `compose_layers`, которому нечего рисовать, обязан дать понятную ошибку.

Тексты ошибок загрузки берутся из `exc.errors()[0]["msg"]`, а не из `str(exc)`: `str` повторяет
`input_value`, и проверка слова по нему была бы пустой. Плохие пресеты заданы сырыми dict/YAML:
после реализации конструктор `ScenePreset` их уже не соберёт. Ожидаемые значения — литералы.

Имена тестов намеренно не содержат слов `static`/`augmented`/`catalog`/`defect`: имя теста
попадает в путь `tmp_path`, а путь может попасть в текст ошибки и сделать проверку пустой.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pytest
import yaml

from Services.layer_render import (
    LayerSpec,
    ObjectFactory,
    ScenePreset,
    compose_layers,
    imwrite_unicode,
)

#: Слова, которые обязано называть сообщение об отказе (критерий 1).
_REQUIRED_WORDS = ("catalog_dir", "defect", "static", "augmented")
_SEEDS = range(20)


# --------------------------------------------------------------------------- #
# Помощники                                                                   #
# --------------------------------------------------------------------------- #


def _bad_layer(name: str, sprite: str = "fixture://spot", **fields: object) -> dict:
    return {"name": name, "mode": "defect", "sprite_source": sprite, **fields}


def _first_msg(exc_info: pytest.ExceptionInfo) -> str:
    """Текст первой ошибки pydantic (без эха `input_value`)."""
    exc = exc_info.value
    assert hasattr(exc, "errors"), f"ожидалась pydantic.ValidationError, получено {type(exc).__name__}: {exc}"
    return exc.errors()[0]["msg"]


def _assert_words(msg: str, *extra: str) -> None:
    missing = [word for word in (*_REQUIRED_WORDS, *extra) if word not in msg]
    assert not missing, f"в сообщении нет {missing}: {msg!r}"


def _opaque_rgba(side: int = 12) -> np.ndarray:
    sprite = np.full((side, side, 4), 200, dtype=np.uint8)
    sprite[:, :, 3] = 255
    return sprite


def _write_assets(root: Path) -> tuple[str, str]:
    """Настоящие файлы: `spot.png` (спрайт любого слоя) и каталог `cat/A/0.png`."""
    spot = root / "spot.png"
    imwrite_unicode(spot, _opaque_rgba(12))
    class_dir = root / "cat" / "A"
    class_dir.mkdir(parents=True)
    imwrite_unicode(class_dir / "0.png", _opaque_rgba(30))
    return str(spot), str(root / "cat")


def _layer_for_mode(name: str, mode: str, sprite: str) -> dict:
    layer: dict = {"name": name, "mode": mode, "sprite_source": sprite}
    if mode == "augmented":
        layer["augment"] = {"offset_x_px": [-2.0, 2.0], "angle_deg": [-10.0, 10.0]}
    return layer


# --------------------------------------------------------------------------- #
# Критерий 1: один слой брака без catalog_dir                                 #
# --------------------------------------------------------------------------- #


def test_ac1_single_layer_rejected_by_from_dict() -> None:
    with pytest.raises(ValueError) as exc_info:
        ScenePreset.from_dict({"layers": [_bad_layer("scratch_zz")]})
    _assert_words(_first_msg(exc_info), "scratch_zz")


# --------------------------------------------------------------------------- #
# Критерий 2: два слоя, вероятность 1.0, from_yaml                            #
# --------------------------------------------------------------------------- #


def test_ac2_two_layers_rejected_by_from_dict() -> None:
    with pytest.raises(ValueError) as exc_info:
        ScenePreset.from_dict({"layers": [_bad_layer("scratch_zz"), _bad_layer("dent_qq")]})
    msg = _first_msg(exc_info)
    _assert_words(msg)
    # Критерий говорит «имя слоя»; требуем хотя бы одно из двух, а не оба.
    assert "scratch_zz" in msg or "dent_qq" in msg, f"сообщение не называет ни одного слоя: {msg!r}"


def test_ac2_always_firing_layer_still_rejected() -> None:
    with pytest.raises(ValueError) as exc_info:
        ScenePreset.from_dict({"layers": [_bad_layer("scratch_zz", defect_probability=1.0)]})
    _assert_words(_first_msg(exc_info), "scratch_zz")


@pytest.mark.parametrize(
    "layers",
    [
        pytest.param([_bad_layer("scratch_zz")], id="one"),
        pytest.param([_bad_layer("scratch_zz"), _bad_layer("dent_qq")], id="two"),
        pytest.param([_bad_layer("scratch_zz", defect_probability=1.0)], id="prob_one"),
    ],
)
def test_ac2_from_yaml_rejects_the_same_file(tmp_path: Path, layers: list[dict]) -> None:
    path = tmp_path / "preset.yaml"
    path.write_text(yaml.safe_dump({"layers": layers}, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError) as exc_info:
        ScenePreset.from_yaml(path)
    msg = _first_msg(exc_info)
    _assert_words(msg)
    assert "scratch_zz" in msg or "dent_qq" in msg, f"сообщение не называет ни одного слоя: {msg!r}"


# --------------------------------------------------------------------------- #
# Критерий 3: compose_layers, которому нечего рисовать                        #
# --------------------------------------------------------------------------- #


def _spec(name: str, probability: float) -> LayerSpec:
    return LayerSpec(name=name, mode="defect", sprite_source=_opaque_rgba(12), defect_probability=probability)


@pytest.mark.parametrize("names", [("spot",), ("spot", "dent")], ids=["one", "two"])
def test_ac3_nothing_visible_raises_clear_error(names: tuple[str, ...]) -> None:
    layers = [_spec(name, 0.0) for name in names]
    with pytest.raises(ValueError) as exc_info:
        compose_layers(layers, np.random.default_rng(0), label="x")
    text = str(exc_info.value)
    assert text.startswith("LayeredObject 'x':"), f"неожиданное начало текста: {text!r}"
    assert "max()" not in text, f"наружу вышла внутренняя ошибка: {text!r}"


def test_ac3_control_certain_layer_renders() -> None:
    composed = compose_layers([_spec("spot", 1.0)], np.random.default_rng(0), label="x")
    assert composed.active_defects == ("spot",)
    assert composed.rgba.shape == (12, 12, 4)
    assert int(composed.rgba[:, :, 3].max()) == 255


def test_ac3_control_forced_layer_renders() -> None:
    composed = compose_layers([_spec("spot", 0.0)], np.random.default_rng(0), 0.0, ("spot",), label="x")
    assert composed.active_defects == ("spot",)
    assert composed.rgba.shape == (12, 12, 4)
    assert int(composed.rgba[:, :, 3].max()) == 255


# --------------------------------------------------------------------------- #
# Критерий 4: что обязано приниматься и рисоваться                            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("modes", "with_catalog", "nominal_names"),
    [
        pytest.param(("static", "defect"), False, ["l0"], id="plain_plus_bad_no_cat"),
        pytest.param(("defect", "static"), False, ["l1"], id="bad_first_then_plain_no_cat"),
        pytest.param(("augmented",), False, ["l0"], id="varied_only_no_cat"),
        pytest.param(("defect",), True, ["base"], id="one_bad_with_cat"),
        pytest.param(("defect", "defect"), True, ["base"], id="two_bad_with_cat"),
    ],
)
def test_ac4_accepted_preset_renders_and_lays_out(
    tmp_path: Path, modes: tuple[str, ...], with_catalog: bool, nominal_names: list[str]
) -> None:
    sprite, catalog = _write_assets(tmp_path)
    data: dict = {"layers": [_layer_for_mode(f"l{i}", mode, sprite) for i, mode in enumerate(modes)]}
    if with_catalog:
        data["catalog_dir"] = catalog
    factory = ObjectFactory(ScenePreset.from_dict(data))
    for seed in _SEEDS:
        rendered = factory.render(np.random.default_rng(seed))
        assert int(rendered.rgba[:, :, 3].max()) > 0, f"seed={seed}: объект полностью прозрачен"
        _class_name, layers = factory.nominal_layers(np.random.default_rng(seed))
        assert [layer[0] for layer in layers] == nominal_names, f"seed={seed}"


# --------------------------------------------------------------------------- #
# Критерий 5: все наборы из 1..3 слоёв, с каталогом и без                     #
# --------------------------------------------------------------------------- #


def test_ac5_every_generated_preset_is_rejected_or_renders(tmp_path: Path) -> None:
    """Порядок слоёв — часть контракта seed, поэтому наборы упорядоченные: (3 + 9 + 27) * 2 = 78.

    Отклоняются ровно три: «без каталога, все слои брака» длиной 1, 2 и 3. `defect_probability`
    у слоёв брака — 0.0: худший случай, слой брака не выпадает никогда.
    """
    sprite, catalog = _write_assets(tmp_path)
    generated = 0
    accepted = 0
    rejected: list[tuple[bool, tuple[str, ...]]] = []
    render_failures: list[str] = []

    for size in (1, 2, 3):
        for modes in itertools.product(("static", "augmented", "defect"), repeat=size):
            for with_catalog in (False, True):
                generated += 1
                data: dict = {"layers": [_layer_for_mode(f"l{i}", mode, sprite) for i, mode in enumerate(modes)]}
                if with_catalog:
                    data["catalog_dir"] = catalog
                try:
                    preset = ScenePreset.from_dict(data)
                except ValueError:
                    rejected.append((with_catalog, modes))
                    continue
                accepted += 1
                factory = ObjectFactory(preset)
                for seed in _SEEDS:
                    try:
                        factory.render(np.random.default_rng(seed))
                    except Exception as exc:  # noqa: BLE001 — собираем все сбои, а не первый
                        render_failures.append(f"cat={with_catalog} modes={modes} seed={seed}: {exc!r}")
                        break

    assert generated == 78
    assert not render_failures, "принятый пресет не рисуется:\n" + "\n".join(render_failures)
    assert sorted(rejected) == [
        (False, ("defect",)),
        (False, ("defect", "defect")),
        (False, ("defect", "defect", "defect")),
    ]
    assert len(rejected) == 3
    assert accepted == 75
