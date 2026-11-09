# -*- coding: utf-8 -*-
"""Task R1, A3 — слепые acceptance-тесты ``ObjectFactory.render(rng, class_index=, angle_deg=)``.

Контракт — ТОЛЬКО пункт A3 раздела ACCEPTANCE задачи R1 (``plans/line-sim/tasks/R1.md``); DESIGN тестеру
не показывался. Worktree на коммите до реализации: у ``render`` нет параметра ``angle_deg`` — ожидаемый
красный ``TypeError: render() got an unexpected keyword argument 'angle_deg'``.

Фикстура — каталог из трёх классов ``a``/``b``/``c`` во ``tmp_path`` (RGBA-спрайты, ``layers=[]``,
``angle_range_deg=(0, 360)``), как в ``test_acceptance_6_2_factory_train.py``; ``data/`` не читается.
Ожидаемые значения — литералы из A3; единственное исключение — реплей ``numpy.random.default_rng`` для
пункта «``angle_deg=None`` с тем же seed даёт тот же угол, что вызов без параметра».
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from Services.layer_render import ObjectFactory, ScenePreset
from Services.layer_render.io import imwrite_unicode

_NAMES = ["a", "b", "c"]


def _factory(root: Path) -> ObjectFactory:
    cat = root / "cat"
    for index, name in enumerate(_NAMES):
        (cat / name).mkdir(parents=True)
        sprite = np.zeros((24, 24, 4), dtype=np.uint8)
        sprite[:, :, :3] = 50 + 40 * index
        sprite[:, :, 3] = 255
        imwrite_unicode(cat / name / "0.png", cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))
    return ObjectFactory(ScenePreset(catalog_dir=str(cat), angle_range_deg=(0.0, 360.0), defect_probability=0.0))


@pytest.mark.timeout(60)
def test_render_angle_deg_exact(tmp_path):
    """A3: ``render(rng, class_index=i, angle_deg=90.0)`` -> ``angle_deg == 90.0`` ровно (равенство float),
    ``class_name`` — имя класса ``i`` (``b`` для 1, ``c`` для 2), независимо от seed.
    Ловит: угол, снова разыгранный из диапазона пресета; потерю ``class_index`` при заданном угле."""
    factory = _factory(tmp_path)

    for seed in (0, 5, 123):
        obj = factory.render(np.random.default_rng(seed), class_index=1, angle_deg=90.0)
        assert obj.angle_deg == 90.0, (seed, obj.angle_deg)
        assert obj.class_name == "b"

    obj = factory.render(np.random.default_rng(7), class_index=2, angle_deg=359.5)
    assert obj.angle_deg == 359.5
    assert obj.class_name == "c"


@pytest.mark.timeout(60)
def test_render_angle_deg_zero_is_a_value_not_none(tmp_path):
    """A3: ``angle_deg=0.0`` — заданный угол (ровно ``0.0``), а не «не задан». Ловит: проверку
    ``if angle_deg:`` вместо ``is not None`` (ноль принимается за ``None`` и угол разыгрывается)."""
    factory = _factory(tmp_path)

    for seed in (0, 5, 123):
        obj = factory.render(np.random.default_rng(seed), class_index=0, angle_deg=0.0)
        assert obj.angle_deg == 0.0, (seed, obj.angle_deg)


@pytest.mark.timeout(60)
def test_render_angle_deg_none_keeps_old_path(tmp_path):
    """A3: ``angle_deg=None`` с тем же seed даёт тот же ``angle_deg``, что вызов без параметра (путь прежний).
    Ловит: изменение порядка расхода rng или другого розыгрыша угла при ``None``."""
    factory = _factory(tmp_path)

    without = factory.render(np.random.default_rng(5), class_index=1)
    with_none = factory.render(np.random.default_rng(5), class_index=1, angle_deg=None)

    assert with_none.angle_deg == without.angle_deg
    assert with_none.class_name == without.class_name == "b"


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(360.0, id="360"),
        pytest.param(-1.0, id="minus_1"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(True, id="bool_true"),
    ],
)
def test_render_angle_deg_invalid_value_error(tmp_path, bad):
    """A3: ``angle_deg`` = ``360.0`` / ``-1.0`` / ``nan`` / ``True`` -> ``ValueError`` (не ``TypeError``,
    не тихое принятие). Ловит: нет проверки диапазона ``[0, 360)``, ``bool`` принят как число, ``nan`` прошёл."""
    factory = _factory(tmp_path)

    with pytest.raises(ValueError):
        factory.render(np.random.default_rng(5), class_index=1, angle_deg=bad)
