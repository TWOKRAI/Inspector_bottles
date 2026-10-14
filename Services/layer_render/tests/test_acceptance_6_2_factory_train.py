# -*- coding: utf-8 -*-
"""Слепые acceptance-тесты Task 6.2 (часть `layer_render`): `ObjectFactory.render(class_index=)`,
`ObjectFactory.catalog`, поле `ScenePreset.train`.

Источник контракта: `plans/layer-render/phase-6-task-6.2.md` — REDS 1-2, ACCEPTANCE 7 (граница импорта),
DESIGN A-B как контракт. Worktree на коммите брифа, до кода: нового API в дереве нет по построению.
Не читались: реализация 6.2, другие ветки, `data/`.

Как устроен файл.
  * Импорты существующих символов — в шапке; новое поведение (`class_index=`, `.catalog`, `.train`) идёт через
    вызов внутри теста, поэтому каждый тест падает сам, а не одной ошибкой сбора.
  * Все фикстуры синтетические: numpy-спрайты -> PNG во `tmp_path`; `data/` не читается.
  * Ожидаемые значения — литералы или независимые оракулы (реплей `numpy.random.default_rng`); не пересчитываются
    из тестируемого кода. Единственное исключение — реплей rng, которого требует бриф (REDS 1).
  * Тесты, зелёные уже сегодня (страховочная сеть, обязаны остаться зелёными): `test_render_default_keeps_old_order`,
    `*_key_set_and_yaml_unchanged`, `test_layer_render_import_is_clean`.
"""

from __future__ import annotations

import copy
import os
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from Services.layer_render import LayerSpec, ObjectFactory, ScenePreset
from Services.layer_render.io import imwrite_unicode

_ROOT = Path(__file__).resolve().parents[3]
_NAMES = ["a", "b", "c"]


# --------------------------------------------------------------------------- #
# Фикстуры: каталог из трёх классов во tmp_path                                #
# --------------------------------------------------------------------------- #


def _class_sprite(index: int, side: int = 40) -> np.ndarray:
    """RGBA-диск: внутри случайные (свои у каждого класса) цвета и альфа 255, снаружи RGB=0 и альфа 0."""
    rng = np.random.default_rng(1000 + index)
    yy, xx = np.mgrid[:side, :side]
    inside = (yy - (side - 1) / 2) ** 2 + (xx - (side - 1) / 2) ** 2 <= (side / 2 - 1) ** 2
    rgb = rng.integers(30, 256, size=(side, side, 3), dtype=np.uint8)
    rgba = np.zeros((side, side, 4), dtype=np.uint8)
    rgba[inside, :3] = rgb[inside]
    rgba[inside, 3] = 255
    return rgba


def _write_png(path: Path, rgba: np.ndarray) -> None:
    imwrite_unicode(path, cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))


def _make_catalog(root: Path, names: list[str] | None = None) -> Path:
    """`root/cat/<имя>/0.png` по одному эталону на класс; индекс класса = порядок имён."""
    names = names or _NAMES
    cat = root / "cat"
    for index, name in enumerate(names):
        (cat / name).mkdir(parents=True)
        _write_png(cat / name / "0.png", _class_sprite(index))
    return cat


def _factory(root: Path, *, angle_range: tuple[float, float] = (0.0, 360.0)) -> ObjectFactory:
    cat = _make_catalog(root)
    return ObjectFactory(ScenePreset(catalog_dir=str(cat), angle_range_deg=angle_range))


def _layers_only_factory(root: Path) -> ObjectFactory:
    """Пресет без `catalog_dir`: только слой из файла (Task 1.1b)."""
    root.mkdir(parents=True, exist_ok=True)
    plate = root / "plate.png"
    _write_png(plate, _class_sprite(7, side=30))
    layer = LayerSpec(name="plate", mode="static", sprite_source=str(plate))
    return ObjectFactory(ScenePreset(layers=[layer]))


# --------------------------------------------------------------------------- #
# REDS 1: render(class_index=)                                                 #
# --------------------------------------------------------------------------- #


def test_render_class_index(tmp_path):
    """REDS 1 дословно: класс по индексу, угол — первый розыгрыш rng, три вида отказа."""
    factory = _factory(tmp_path, angle_range=(0.0, 360.0))

    obj = factory.render(np.random.default_rng(5), class_index=1)
    assert obj.class_name == "b"  # class_names[1]; индекс 1 не разыгран, а задан
    # `rng.integers` не зовётся -> первым тратится `uniform` угла: реплей сида 5 (оракул из брифа)
    assert obj.angle_deg == float(np.random.default_rng(5).uniform(0, 360))

    for bad in (-1, 3):  # -1 и num_classes
        with pytest.raises(ValueError) as info:
            factory.render(np.random.default_rng(5), class_index=bad)
        text = str(info.value)
        assert "class_index" in text, f"class_index={bad}: {text!r}"
        assert "num_classes=3" in text, f"class_index={bad}: {text!r}"

    with pytest.raises(ValueError, match="class_index"):  # bool — не int
        factory.render(np.random.default_rng(5), class_index=True)

    with pytest.raises(ValueError, match="catalog_dir"):  # у пресета нет каталога
        _layers_only_factory(tmp_path / "layers_only").render(np.random.default_rng(5), class_index=0)


def test_render_default_keeps_old_order(tmp_path):
    """Без `class_index` путь прежний байт в байт: `integers` (класс) -> `uniform` (угол). Реплей сида 5."""
    factory = _factory(tmp_path, angle_range=(0.0, 360.0))
    replay = np.random.default_rng(5)
    expected_index = int(replay.integers(3))
    expected_angle = float(replay.uniform(0, 360))

    obj = factory.render(np.random.default_rng(5))
    assert obj.class_name == _NAMES[expected_index]
    assert obj.angle_deg == expected_angle


def test_render_class_index_none_equals_default(tmp_path):
    """`class_index=None` (явно) = аргумент не задан: тот же класс, угол и байты объекта."""
    factory = _factory(tmp_path, angle_range=(0.0, 360.0))
    default = factory.render(np.random.default_rng(5))
    explicit_none = factory.render(np.random.default_rng(5), class_index=None)
    assert explicit_none.class_name == default.class_name
    assert explicit_none.angle_deg == default.angle_deg
    assert explicit_none.rgba.tobytes() == default.rgba.tobytes()


def test_render_class_index_uses_sprite_of_that_class(tmp_path):
    """Угол 0: `rgba` объекта равен эталону заданного класса побайтно (спрайт 40x40, альфа 0/255, RGB=0 вне)."""
    factory = _factory(tmp_path, angle_range=(0.0, 0.0))
    seen = []
    for index in range(3):
        obj = factory.render(np.random.default_rng(9), class_index=index)
        assert obj.class_name == _NAMES[index]
        assert obj.rgba.shape == (40, 40, 4)
        assert obj.rgba.tobytes() == _class_sprite(index).tobytes(), f"class_index={index}"
        seen.append(obj.rgba.tobytes())
    assert len(set(seen)) == 3  # три разных класса — три разные картинки


@pytest.mark.parametrize("index", [np.int64(1), np.int32(2), 0])
def test_render_class_index_accepts_numpy_integers(tmp_path, index):
    """`np.integer` принимается так же, как `int` (DESIGN A: «`bool` — нет, `np.integer` — да»)."""
    factory = _factory(tmp_path)
    obj = factory.render(np.random.default_rng(5), class_index=index)
    assert obj.class_name == _NAMES[int(index)]


@pytest.mark.parametrize("bad", [1.0, "1", np.bool_(True), 2.5])
def test_render_class_index_rejects_non_int(tmp_path, bad):
    """Не `int` (`float`, `str`, `np.bool_`) -> `ValueError` с `class_index`."""
    factory = _factory(tmp_path)
    with pytest.raises(ValueError, match="class_index"):
        factory.render(np.random.default_rng(5), class_index=bad)


@pytest.mark.parametrize("bad", [-7, 99])
def test_render_class_index_error_text_has_no_input_value(tmp_path, bad):
    """TRAPS: текст ошибки несёт имя поля и допустимое множество, но не входное значение."""
    factory = _factory(tmp_path)
    with pytest.raises(ValueError) as info:
        factory.render(np.random.default_rng(5), class_index=bad)
    text = str(info.value)
    assert str(bad) not in text, text
    assert "class_index" in text and "num_classes=3" in text


def test_render_class_index_checks_before_any_draw(tmp_path):
    """DESIGN A: проверки идут до любого розыгрыша — после отказа состояние rng не сдвинуто."""
    factory = _factory(tmp_path)
    for bad in (3, -1, True):
        rng = np.random.default_rng(5)
        before = copy.deepcopy(rng.bit_generator.state)
        with pytest.raises(ValueError):
            factory.render(rng, class_index=bad)
        assert rng.bit_generator.state == before, f"class_index={bad!r} потратил rng"


def test_render_class_index_layers_only_error_before_any_draw(tmp_path):
    """Пресет без `catalog_dir`: отказ с `catalog_dir` в тексте и без расхода rng."""
    factory = _layers_only_factory(tmp_path)
    rng = np.random.default_rng(5)
    before = copy.deepcopy(rng.bit_generator.state)
    with pytest.raises(ValueError, match="catalog_dir"):
        factory.render(rng, class_index=0)
    assert rng.bit_generator.state == before


def test_factory_catalog_property(tmp_path):
    """`ObjectFactory.catalog` — каталог пресета (один и тот же объект при каждом чтении); без каталога — None."""
    factory = _factory(tmp_path / "with_catalog")
    catalog = factory.catalog
    assert catalog is not None
    assert catalog.class_names == ["a", "b", "c"]
    assert catalog.num_classes == 3
    assert factory.catalog is catalog
    assert _layers_only_factory(tmp_path / "layers_only").catalog is None


# --------------------------------------------------------------------------- #
# REDS 2: ScenePreset.train                                                    #
# --------------------------------------------------------------------------- #


def test_scene_preset_train_section(tmp_path):
    """REDS 2 дословно: `train` — непрозрачный dict; без `train` ключа нет ни в `to_dict`, ни в YAML."""
    with_train = ScenePreset.from_dict({"catalog_dir": "cat", "train": {"crop": {"side_px": 96}}})
    assert with_train.train == {"crop": {"side_px": 96}}
    assert with_train.to_dict()["train"] == {"crop": {"side_px": 96}}
    assert ScenePreset.from_dict(with_train.to_dict()) == with_train

    without = ScenePreset.from_dict({"catalog_dir": "cat"})
    assert without.train is None
    assert "train" not in without.to_dict()
    target = tmp_path / "without_train.yaml"
    without.to_yaml(target)
    text = target.read_text(encoding="utf-8")
    assert not re.search(r"^\s*-?\s*train\b", text, re.M), text  # строки `train` нет
    assert ScenePreset.from_dict(without.to_dict()) == without


def test_scene_preset_without_train_key_set_and_yaml_unchanged(tmp_path):
    """Совместимость с 3.1: `to_dict`/`to_yaml` пресета без `train` побайтно прежние (литералы текущего вывода)."""
    preset = ScenePreset.from_dict({"catalog_dir": "cat"})
    assert set(preset.to_dict()) == {"catalog_dir", "angle_range_deg", "defect_probability", "layers", "base_dir"}

    target = tmp_path / "plain.yaml"
    preset.to_yaml(target)
    expected = "catalog_dir: cat\nangle_range_deg:\n- 0.0\n- 360.0\ndefect_probability: 0.0\nlayers: []\n"
    assert target.read_text(encoding="utf-8") == expected


def test_scene_preset_train_none_given_explicitly(tmp_path):
    """`train: None` в данных = ключ не задан: ни в `to_dict`, ни в YAML, круг замыкается."""
    preset = ScenePreset.from_dict({"catalog_dir": "cat", "train": None})
    assert preset.train is None
    assert "train" not in preset.to_dict()
    assert ScenePreset.from_dict(preset.to_dict()) == preset


def test_scene_preset_train_yaml_roundtrip(tmp_path):
    """`from_yaml(to_yaml(p, f)) == p` с `train` внутри (файл в каталоге `base_dir`)."""
    train = {"crop": {"side_px": 96, "output_size": 64}, "background_layers": [{"solid": [1, 2, 3]}], "n": [1, 2]}
    preset = ScenePreset(catalog_dir="cat", train=train, base_dir=str(tmp_path.resolve()))
    target = tmp_path / "with_train.yaml"
    preset.to_yaml(target)
    loaded = ScenePreset.from_yaml(target)
    assert loaded.train == train
    assert loaded == preset


def test_scene_preset_train_content_is_opaque_but_must_be_dict():
    """Содержимое `train` не проверяется (проверяет генератор); не-словарь отвергается типом поля."""
    weird = {"anything": [1, {"x": 2}], "crop": "not-a-dict", "unknown_key": None}
    assert ScenePreset.from_dict({"catalog_dir": "cat", "train": weird}).train == weird
    for not_a_dict in ([1, 2], "x", 5):
        with pytest.raises(ValidationError):
            ScenePreset.from_dict({"catalog_dir": "cat", "train": not_a_dict})


# --------------------------------------------------------------------------- #
# ACCEPTANCE 7: граница слоёв                                                  #
# --------------------------------------------------------------------------- #


def test_layer_render_import_is_clean():
    """Чистый процесс `import Services.layer_render`: в sys.modules нет `Services.dataset_gen*`/`Services.line_sim*`."""
    code = (
        "import sys; import Services.layer_render; "
        "bad = sorted(m for m in sys.modules if m.startswith(('Services.dataset_gen', 'Services.line_sim'))); "
        "print('BAD=' + ','.join(bad)); sys.exit(1 if bad else 0)"
    )
    env = {**os.environ, "PYTHONPATH": str(_ROOT), "PYTHONUTF8": "1"}
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=_ROOT, env=env, capture_output=True, text=True, timeout=120, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
