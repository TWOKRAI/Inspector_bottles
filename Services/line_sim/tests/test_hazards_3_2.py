"""Автор-хазард-тесты Task 3.2 — ObjectFactory + catalog_bridge + defect-слой.

Что может сломаться именно в ЭТОМ механизме (не общий acceptance):
    - force_defect_next() — флаг потребляется безусловно в начале make(), даже если
      make() дальше падает (пин выбора: "следующий вызов", не "следующий успешный").
    - фабрика не мутирует спрайты каталога (общая ссылка `catalog._sprites` живёт
      между вызовами make() — порча одного объекта испортила бы все следующие).
    - дефект-заплатка строится под РЕАЛЬНЫЙ размер базового спрайта, включая
      неквадратный (h != w) — иначе occlusion уехал бы за канву или дал неверную
      долю площади.
    - относительный catalog_dir в YAML резолвится от каталога ФАЙЛА, а не от текущего
      cwd процесса — иначе `from_yaml` работал бы только при запуске из одного места.
"""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import ObjectFactory, ScenePreset
from Services.line_sim.core.factory import _DEFECT_OFFSET_FRAC, _DEFECT_SIDE_FRAC

CLASS_COLORS: dict[str, tuple[int, int, int]] = {
    "class_a": (220, 40, 40),
    "class_b": (40, 200, 60),
}


def _write_fixture_catalog(root: Path, class_colors: dict[str, tuple[int, int, int]], size: int = 32) -> None:
    for name, color in class_colors.items():
        rgba = np.zeros((size, size, 4), dtype=np.uint8)
        rgba[:, :, 0], rgba[:, :, 1], rgba[:, :, 2], rgba[:, :, 3] = color[0], color[1], color[2], 255
        class_dir = root / name
        class_dir.mkdir(parents=True, exist_ok=True)
        imwrite_unicode(class_dir / "sprite.png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))


def _write_preset_yaml(tmp_path: Path, catalog_dir_name: str, **kwargs) -> Path:
    preset_path = tmp_path / "preset.yaml"
    data = {"catalog_dir": catalog_dir_name, "layers": []}
    data.update(kwargs)
    preset_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return preset_path


# --------------------------------------------------------------------------
# force_defect_next() — одноразовость флага под исключением
# --------------------------------------------------------------------------


def test_force_defect_flag_consumed_even_if_make_raises(tmp_path):
    """Пин выбора: флаг потребляется В НАЧАЛЕ make(), безусловно — если каталог не
    задан (make() гарантированно падает ValueError), флаг всё равно потрачен, и
    следующий make() на факторе с каталогом брак уже не форсирует."""
    layer_sprite = tmp_path / "layer.png"
    rgba = np.zeros((8, 8, 4), dtype=np.uint8)
    rgba[:, :, 3] = 255
    imwrite_unicode(layer_sprite, cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))

    preset = ScenePreset.from_dict(
        {"catalog_dir": None, "layers": [{"name": "l", "mode": "static", "sprite_source": str(layer_sprite)}]}
    )
    factory = ObjectFactory(preset)  # catalog_dir=None -> _catalog is None, layers загрузились нормально
    factory.force_defect_next()
    with pytest.raises(ValueError):
        factory.make(object_id="x", spawn_encoder=0.0, rng=np.random.default_rng(0))
    assert factory._force_defect_pending is False  # флаг уже израсходован, не "восстановился"


# --------------------------------------------------------------------------
# Каталог не мутируется фабрикой
# --------------------------------------------------------------------------


def test_factory_does_not_mutate_catalog_sprites(tmp_path):
    """Спрайт класса, отданный catalog.get_sprite(), после make() остаётся тем же
    массивом побитово — дефект-заплатка строится в НОВОМ массиве, не поверх него."""
    _write_fixture_catalog(tmp_path / "catalog", CLASS_COLORS)
    preset = ScenePreset.from_yaml(_write_preset_yaml(tmp_path, "catalog", defect_probability=1.0))
    factory = ObjectFactory(preset)

    before = {
        name: sprite.copy()
        for name, sprite in zip(
            factory.class_names, [factory._catalog.sprites(i)[0] for i in range(factory.num_classes)], strict=True
        )
    }

    for i in range(5):
        factory.make(object_id=f"o{i}", spawn_encoder=0.0, rng=np.random.default_rng(i))

    for i, name in enumerate(factory.class_names):
        assert np.array_equal(factory._catalog.sprites(i)[0], before[name]), (
            f"класс '{name}': спрайт каталога изменился после make()"
        )


# --------------------------------------------------------------------------
# Дефект-заплатка на неквадратном спрайте
# --------------------------------------------------------------------------


def test_defect_blob_matches_nonsquare_base_shape(tmp_path):
    """Базовый спрайт h != w — дефект-заплатка (и итоговый рендер) не падает и не
    обрезает/не растягивает канву мимо реального размера базы."""
    root = tmp_path / "catalog" / "tall"
    root.mkdir(parents=True)
    rgba = np.zeros((48, 16, 4), dtype=np.uint8)  # h=48, w=16 — заведомо не квадрат
    rgba[:, :, 1] = 200
    rgba[:, :, 3] = 255
    imwrite_unicode(root / "sprite.png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))

    preset = ScenePreset.from_yaml(_write_preset_yaml(tmp_path, "catalog", defect_probability=1.0))
    factory = ObjectFactory(preset)
    blob = factory._build_defect_blob(rgba)
    assert blob.shape == (48, 16, 4)

    side = min(48, 16)
    expected_size = max(1, round(side * _DEFECT_SIDE_FRAC))
    x = round(16 * _DEFECT_OFFSET_FRAC)
    y = round(48 * _DEFECT_OFFSET_FRAC)
    x1, y1 = min(16, x + expected_size), min(48, y + expected_size)
    assert int(np.count_nonzero(blob[:, :, 3])) == (y1 - y) * (x1 - x)  # площадь пятна = клип по канве

    obj = factory.make(object_id="o", spawn_encoder=0.0, rng=np.random.default_rng(1))
    assert obj.render().ndim == 3 and obj.render().shape[2] == 4


# --------------------------------------------------------------------------
# Относительный путь — от каталога YAML-файла, не от cwd процесса
# --------------------------------------------------------------------------


def test_relative_catalog_dir_resolved_from_yaml_dir_not_cwd(tmp_path, monkeypatch):
    """from_yaml вызван из ДРУГОГО cwd — catalog_dir всё равно резолвится от каталога
    файла пресета, не от текущей рабочей директории процесса."""
    presets_dir = tmp_path / "some" / "nested" / "presets"
    presets_dir.mkdir(parents=True)
    _write_fixture_catalog(presets_dir / "catalog", CLASS_COLORS)
    preset_path = _write_preset_yaml(presets_dir, "catalog")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert os.getcwd() == str(elsewhere)

    preset = ScenePreset.from_yaml(preset_path)  # путь абсолютный, cwd тут ни при чём
    assert Path(preset.catalog_dir) == (presets_dir / "catalog").resolve()
    factory = ObjectFactory(preset)
    assert factory.num_classes == 2
