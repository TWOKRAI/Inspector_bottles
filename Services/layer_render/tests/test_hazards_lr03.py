"""Опасности ЛР-03 от автора правки: дыра слепой приёмки и неизменность байтов/потока rng.

Эталоны `_MIXED_*` сняты на коде ДО правки ЛР-03 (коммит 6c40a91b2), а не вычисляются из проверяемого кода.
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from Services.layer_render import LayerAugment, LayerSpec, ScenePreset, compose_layers

# --------------------------------------------------------------------------- #
# Дыра слепой приёмки: defect_probability пресета не спасает                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("probability", [0.5, 1.0])
def test_preset_level_probability_does_not_legalize_bad_only_layers(probability: float) -> None:
    """Служебный слой `damaged` фабрики не считается: объекта без брака в таком пресете всё равно нет."""
    data = {
        "defect_probability": probability,
        "layers": [{"name": "scratch_zz", "mode": "defect", "sprite_source": "fixture://spot"}],
    }
    with pytest.raises(ValueError) as exc_info:
        ScenePreset.from_dict(data)
    msg = exc_info.value.errors()[0]["msg"]
    for word in ("scratch_zz", "catalog_dir", "defect", "static", "augmented"):
        assert word in msg, msg


# --------------------------------------------------------------------------- #
# Байты результата и поток rng годного входа не изменились                    #
# --------------------------------------------------------------------------- #

_SEEDS = range(8)
#: sha256 по 8 сидам: shape и байты rgba, layer_params, active_defects, следующие розыгрыши rng.
_MIXED_SHA256 = "e7deee9a82c6f5b02283378991302d1796363bf13284e472356aacbce5c35198"
#: Выпавшие дефекты по сидам — контроль, что эталон покрывает и выпадение, и невыпадение.
_MIXED_ACTIVE: list[tuple[str, ...]] = [
    ("blot",),
    ("chip", "blot"),
    ("chip", "blot"),
    ("chip", "blot"),
    ("chip",),
    (),
    (),
    (),
]


def _square(side: int, rgb: tuple[int, int, int], alpha: int) -> np.ndarray:
    sprite = np.zeros((side, side, 4), dtype=np.uint8)
    sprite[:, :, 0:3] = rgb
    sprite[:, :, 3] = alpha
    return sprite


def _mixed_stack() -> list[LayerSpec]:
    """static + augmented (только сдвиг и тон: без интерполяции) + два defect-слоя."""
    return [
        LayerSpec(name="body", mode="static", sprite_source=_square(20, (200, 40, 40), 255)),
        LayerSpec(
            name="mark",
            mode="augmented",
            sprite_source=_square(6, (40, 200, 40), 180),
            augment=LayerAugment(offset_x_px=(-9.0, 9.0), offset_y_px=(-9.0, 9.0), hue_shift_deg=(-40.0, 40.0)),
        ),
        LayerSpec(name="chip", mode="defect", sprite_source=_square(8, (10, 10, 10), 255), defect_probability=0.5),
        LayerSpec(
            name="blot",
            mode="defect",
            sprite_source=_square(4, (250, 250, 250), 255),
            offset_px=(14.0, 0.0),
            defect_probability=0.5,
        ),
    ]


def _digest_mixed() -> tuple[str, list[tuple[str, ...]]]:
    digest = hashlib.sha256()
    active: list[tuple[str, ...]] = []
    for seed in _SEEDS:
        rng = np.random.default_rng(seed)
        composed = compose_layers(_mixed_stack(), rng, label="x")
        after = [float(rng.random()), float(rng.spawn(1)[0].random())]
        digest.update(repr(composed.rgba.shape).encode())
        digest.update(composed.rgba.tobytes())
        digest.update(json.dumps(composed.layer_params, sort_keys=True).encode())
        digest.update(json.dumps([list(composed.active_defects), after]).encode())
        active.append(composed.active_defects)
    return digest.hexdigest(), active


def test_mixed_stack_bytes_and_rng_stream_are_unchanged() -> None:
    sha, active = _digest_mixed()
    assert active == _MIXED_ACTIVE
    assert sha == _MIXED_SHA256


# --------------------------------------------------------------------------- #
# Новая ошибка compose_layers: после розыгрыша, до канвы                      #
# --------------------------------------------------------------------------- #


def test_nothing_drawn_error_comes_after_the_draw() -> None:
    """Отказ не откатывает и не пропускает розыгрыш: `rng` породил по дочернему потоку на слой, как раньше."""
    layers = [
        LayerSpec(name=name, mode="defect", sprite_source=_square(4, (1, 2, 3), 255)) for name in ("spot", "dent")
    ]
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError, match=r"^LayeredObject 'x': "):
        compose_layers(layers, rng, label="x")
    assert rng.bit_generator.seed_seq.n_children_spawned == 2


def test_transparent_result_keeps_its_own_error() -> None:
    """Слой нарисован, но прозрачен целиком — это прежняя ошибка, а не «нечего рисовать»."""
    layers = [LayerSpec(name="ghost", mode="static", sprite_source=_square(4, (1, 2, 3), 0))]
    with pytest.raises(ValueError) as exc_info:
        compose_layers(layers, np.random.default_rng(0), label="x")
    assert str(exc_info.value) == "LayeredObject 'x': итоговый RGBA полностью прозрачен"
