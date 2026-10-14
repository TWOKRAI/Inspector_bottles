# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 6.2 (`LayerSceneGenerator`, `TrainSection`): границы схемы, порядок rng, реентерабельность.

Слепая приёмка — `test_acceptance_6_2_layer_scene.py`; здесь — то, что автор видит опасным в своём коде:
  * схема: `lateral_offset_px` lo > hi, `radius_jitter_frac` 1.0, опечатки в `symmetry`/`augment.<эффект>`;
  * нечитаемый `tile:` — исключение при создании, а не молча выкинутый слой фона;
  * без `ScrollingTile` фаза тайла не тратит `rng`, с ним — тратит (контроль чувствительности);
  * без `class_index` первым тратится ровно один `integers`; плохой `class_index` не тратит `rng` вовсе;
  * сэмпл не оставляет следа в генераторе и пресете (порядок вызовов, `preset.train`, параллельные потоки).
Ожидаемые значения — литералы или реплей явными вызовами numpy/`layer_render`, не из `LayerSceneGenerator`.
"""

from __future__ import annotations

import copy
import threading
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml
from pydantic import ValidationError

from Services.dataset_gen.core.layer_scene import LayerSceneGenerator, TrainSection
from Services.layer_render import ObjectFactory, ScenePreset
from Services.layer_render.io import imwrite_unicode


def _square(side: int, index: int) -> np.ndarray:
    """Непрозрачный квадрат с цветом по индексу класса и тёмной меткой в углу (угол поворота виден)."""
    rgba = np.zeros((side, side, 4), dtype=np.uint8)
    rgba[:, :, :3] = (50 + 60 * index, 180 - 50 * index, 90)
    rgba[2:8, 2:8, :3] = 10
    rgba[:, :, 3] = 255
    return rgba


def _build(root: Path, train: dict | None = None, *, names: tuple[str, ...] = ("a", "b", "c")) -> Path:
    """Каталог `root/cat/<имя>/0.png` и пресет-YAML рядом; пути относительные."""
    for index, name in enumerate(names):
        (root / "cat" / name).mkdir(parents=True)
        imwrite_unicode(root / "cat" / name / "0.png", cv2.cvtColor(_square(30, index), cv2.COLOR_RGBA2BGRA))
    data: dict = {"catalog_dir": "cat", "angle_range_deg": [0.0, 360.0]}
    if train is not None:
        data["train"] = train
    path = root / "preset.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _write_tile(path: Path, width: int = 40) -> None:
    ys, xs = np.mgrid[:16, :width]
    rgb = np.dstack([(xs * 6) % 256, (ys * 15) % 256, ((xs + ys) * 4) % 256]).astype(np.uint8)
    imwrite_unicode(path, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))


_CROP = {"size_mode": "fixed", "side_px": 40, "output_size": 24, "center_jitter_px": 2.0}


# --------------------------------------------------------------------------- #
# Схема TrainSection                                                          #
# --------------------------------------------------------------------------- #


def test_lateral_offset_lo_above_hi_is_rejected():
    """`lateral_offset_px [5, 1]` — ValidationError с именем поля (знак смещения разыгрывается, lo > hi бессмыслен)."""
    with pytest.raises(ValidationError, match="lateral_offset_px"):
        TrainSection.model_validate({"lateral_offset_px": [5.0, 1.0]})


@pytest.mark.parametrize("bad", [[-1.0, 2.0], [0.0, 2000.5]], ids=["negative-lo", "hi-above-2000"])
def test_lateral_offset_out_of_bounds_is_rejected(bad):
    with pytest.raises(ValidationError, match="lateral_offset_px"):
        TrainSection.model_validate({"lateral_offset_px": bad})


def test_radius_jitter_frac_one_is_rejected():
    """`radius_jitter_frac 1.0` — ValidationError: радиус `× (1 + U(−1, 1))` мог бы стать нулём."""
    with pytest.raises(ValidationError, match="radius_jitter_frac"):
        TrainSection.model_validate({"crop": {"radius_jitter_frac": 1.0}})
    assert TrainSection.model_validate({"crop": {"radius_jitter_frac": 0.99}}).crop.radius_jitter_frac == 0.99


def test_typo_in_augment_effect_lists_allowed_keys():
    """Опечатка в `augment.noise` — ValidationError со списком допустимых ключей, а не молчаливый дефолт."""
    with pytest.raises(ValidationError) as info:
        TrainSection.model_validate({"augment": {"noise": {"enabled": True, "prb": 1.0}}})
    text = str(info.value)
    assert "train.augment.noise" in text
    for allowed in ("enabled", "prob", "std"):
        assert allowed in text


def test_typo_in_augment_root_and_symmetry_is_rejected():
    """Неизвестный эффект в `augment` и опечатка в `symmetry` — ValidationError с допустимыми ключами блока."""
    with pytest.raises(ValidationError) as info:
        TrainSection.model_validate({"augment": {"noize": {"enabled": True}}})
    assert "train.augment" in str(info.value) and "noise" in str(info.value)
    with pytest.raises(ValidationError) as info:
        TrainSection.model_validate({"symmetry": {"auto_detct": False}})
    assert "train.symmetry" in str(info.value) and "auto_detect" in str(info.value)


def test_known_keys_pass_and_augment_none_means_no_effects():
    """Контроль ограды: правильные ключи проходят; `augment` не задан — `None` (без фотометрии)."""
    train = TrainSection.model_validate(
        {"augment": {"noise": {"enabled": True, "prob": 1.0}}, "symmetry": {"auto_detect": False}}
    )
    assert train.augment is not None and train.augment.noise.prob == 1.0
    assert train.symmetry.auto_detect is False
    assert TrainSection().augment is None


# --------------------------------------------------------------------------- #
# Фон: нечитаемый tile                                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("kind", ["missing", "garbage"])
def test_unreadable_tile_raises_at_construction(tmp_path, kind):
    """Нечитаемый `tile:` — исключение в конструкторе. `None` от загрузчика выкинул бы слой: обучение без фона."""
    if kind == "garbage":
        (tmp_path / "belt.png").write_bytes(b"not an image at all")
    path = _build(tmp_path, {"background_layers": [{"solid": [1, 2, 3]}, {"tile": "belt.png"}]})
    with pytest.raises((ValueError, OSError)):
        LayerSceneGenerator.from_yaml(path)


# --------------------------------------------------------------------------- #
# Порядок розыгрышей rng                                                      #
# --------------------------------------------------------------------------- #


def _replay_state_without_phase(path: Path, ci: int, seed: int) -> dict:
    """Состояние rng после реплея DESIGN F без п. 6 (фазы тайла) и без эффектов: render -> 2 -> 3 розыгрыша."""
    preset = ScenePreset.from_yaml(path)
    rng = np.random.default_rng(seed)
    ObjectFactory(preset.model_copy(update={"defect_probability": 0.0})).render(rng, class_index=ci, label="train")
    rng.uniform(0.0, 4.0)
    rng.random()
    rng.uniform(-2.0, 2.0)
    rng.uniform(-2.0, 2.0)
    rng.uniform(-0.0, 0.0)
    return rng.bit_generator.state


def test_no_scrolling_tile_spends_no_phase_draw(tmp_path):
    """Без `ScrollingTile` состояние rng после сэмпла == реплей F без п. 6 (лишний `integers` сдвинул бы поток)."""
    path = _build(tmp_path, {"lateral_offset_px": [0.0, 4.0], "crop": _CROP})
    gen = LayerSceneGenerator.from_yaml(path)
    for seed in range(4):
        ci = seed % 3
        rng = np.random.default_rng(seed)
        gen.generate_sample(class_index=ci, rng=rng)
        assert rng.bit_generator.state == _replay_state_without_phase(path, ci, seed), f"seed={seed}"


def test_scrolling_tile_spends_phase_draw(tmp_path):
    """Контроль чувствительности: с `ScrollingTile` тот же реплей без п. 6 уже не совпадает (фаза тратит rng)."""
    _write_tile(tmp_path / "belt.png")
    path = _build(
        tmp_path,
        {
            "background_layers": [{"solid": [1, 2, 3]}, {"tile": "belt.png"}],
            "lateral_offset_px": [0.0, 4.0],
            "crop": _CROP,
        },
    )
    gen = LayerSceneGenerator.from_yaml(path)
    rng = np.random.default_rng(0)
    gen.generate_sample(class_index=0, rng=rng)
    assert rng.bit_generator.state != _replay_state_without_phase(path, 0, 0)


def test_class_index_none_draws_exactly_one_integers_first(tmp_path):
    """Без `class_index` первым тратится ровно один `rng.integers(num_classes)`, дальше — путь с заданным классом."""
    path = _build(tmp_path, {"lateral_offset_px": [1.0, 6.0], "crop": _CROP})
    gen = LayerSceneGenerator.from_yaml(path)
    for seed in range(5):
        free_frame, free_label = gen.generate_sample(rng=np.random.default_rng(seed))
        rng = np.random.default_rng(seed)
        ci = int(rng.integers(3))
        fixed_frame, fixed_label = gen.generate_sample(class_index=ci, rng=rng)
        assert free_label.class_index == ci
        assert free_frame.tobytes() == fixed_frame.tobytes(), f"seed={seed}"
        assert free_label.to_dict() == fixed_label.to_dict()


@pytest.mark.parametrize("bad", [-1, 3, True, 1.0])
def test_bad_class_index_fails_before_any_draw(tmp_path, bad):
    """Плохой `class_index` — ValueError с `class_index`, rng не тронут (ни переданный, ни внутренний поток)."""
    gen = LayerSceneGenerator.from_yaml(_build(tmp_path, {"crop": _CROP}), seed=5)
    rng = np.random.default_rng(1)
    before = copy.deepcopy(rng.bit_generator.state)
    with pytest.raises(ValueError, match="class_index"):
        gen.generate_sample(class_index=bad, rng=rng)
    assert rng.bit_generator.state == before
    with pytest.raises(ValueError, match="class_index"):
        gen.generate_sample(class_index=bad)
    reference = LayerSceneGenerator.from_yaml(tmp_path / "preset.yaml", seed=5)
    assert gen.generate_sample()[0].tobytes() == reference.generate_sample()[0].tobytes()


# --------------------------------------------------------------------------- #
# Реентерабельность: сэмпл не оставляет следа                                 #
# --------------------------------------------------------------------------- #


def _rich(tmp_path: Path) -> Path:
    _write_tile(tmp_path / "belt.png")
    return _build(
        tmp_path,
        {
            "background_layers": [{"solid": [5, 6, 7]}, {"tile": "belt.png"}],
            "lateral_offset_px": [1.0, 5.0],
            "crop": {"size_mode": "radius", "margin_px": 3, "output_size": 24, "radius_jitter_frac": 0.2},
            "augment": {"noise": {"enabled": True, "prob": 1.0}},
            "defect_probability": 0.5,
        },
    )


def test_sample_does_not_depend_on_previous_calls(tmp_path):
    """Тот же `(class_index, seed)` до и после чужих сэмплов — те же байты: кэши фабрики и `obj.rgba` не портятся."""
    gen = LayerSceneGenerator.from_yaml(_rich(tmp_path))
    first = gen.generate_sample(class_index=0, rng=np.random.default_rng(42))
    for seed in range(6):
        gen.generate_sample(rng=np.random.default_rng(seed))
    again = gen.generate_sample(class_index=0, rng=np.random.default_rng(42))
    assert first[0].tobytes() == again[0].tobytes()
    assert first[1].to_dict() == again[1].to_dict()


def test_generator_does_not_mutate_preset_train(tmp_path):
    """`preset.train` — изменяемый dict внутри frozen пресета: генератор его не трогает (пресет общий с симом)."""
    preset = ScenePreset.from_yaml(_rich(tmp_path))
    snapshot = copy.deepcopy(preset.train)
    gen = LayerSceneGenerator(preset)
    for seed in range(3):
        gen.generate_sample(rng=np.random.default_rng(seed))
    assert preset.train == snapshot
    assert preset.defect_probability == 0.0  # перекрытие train.defect_probability — на копии пресета


def test_parallel_threads_with_own_rng_match_sequential(tmp_path):
    """Один генератор, два потока со своими rng — те же байты, что последовательно (общая фабрика без гонок)."""
    gen = LayerSceneGenerator.from_yaml(_rich(tmp_path))
    seeds = {"t0": 100, "t1": 200}
    expected = {
        name: [gen.generate_sample(rng=rng)[0].tobytes() for rng in [np.random.default_rng(seed)] for _ in range(8)]
        for name, seed in seeds.items()
    }
    got: dict[str, list[bytes]] = {}
    errors: list[BaseException] = []

    def worker(name: str, seed: int) -> None:
        try:
            rng = np.random.default_rng(seed)
            got[name] = [gen.generate_sample(rng=rng)[0].tobytes() for _ in range(8)]
        except BaseException as exc:  # noqa: BLE001 — ошибку потока в тест
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=item, daemon=True) for item in seeds.items()]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads), "поток не завершился за 60 с"
    assert not errors, errors
    assert got == expected
