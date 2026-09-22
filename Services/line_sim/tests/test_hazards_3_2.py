"""Автор-хазард-тесты Task 3.2 — ObjectFactory + catalog_bridge + defect-слой.

Что может сломаться именно в ЭТОМ механизме (не общий acceptance):
    - force_defect_next() — флаг читается в начале make(), но гасится ТОЛЬКО после
      успешной постройки LayeredObject: транзитная ошибка каталога не должна съедать
      нажатие оператора (ревью 2026-09-22, репродукция флаки-каталога).
    - фабрика не мутирует спрайты каталога (общая ссылка `catalog._sprites` живёт
      между вызовами make() — порча одного объекта испортила бы все следующие).
    - дефект-заплатка строится под РЕАЛЬНЫЙ размер базового спрайта, включая
      неквадратный (h != w) — иначе occlusion уехал бы за канву или дал неверную
      долю площади.
    - дефект-заплатка замаскирована альфой базового спрайта — на круглом диске не
      красит прозрачные углы квадратного холста (ревью 2026-09-22).
    - относительный catalog_dir в YAML резолвится от каталога ФАЙЛА, а не от текущего
      cwd процесса — иначе `from_yaml` работал бы только при запуске из одного места.
    - имена "base"/"damaged" зарезервированы за ObjectFactory — пресет с catalog_dir
      отклоняет их на границе, а не даёт make() падать глубже (ревью 2026-09-22).
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
# force_defect_next() — выживает транзитную ошибку каталога
# --------------------------------------------------------------------------


def test_force_defect_survives_transient_catalog_failure(tmp_path):
    """Ревью 2026-09-22: оператор жмёт «выпусти брак сейчас», первый make() падает по
    транзитной причине (каталог/диск моргнул) — флаг НЕ должен сгорать впустую.
    Наблюдаем только публичный API (passport.defect), без обращения к приватному полю."""
    _write_fixture_catalog(tmp_path / "catalog", CLASS_COLORS)
    preset = ScenePreset.from_yaml(_write_preset_yaml(tmp_path, "catalog"))
    factory = ObjectFactory(preset)

    original_get_sprite = factory._catalog.get_sprite
    calls = {"n": 0}

    def flaky_get_sprite(class_index, rng):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("transient disk hiccup")
        return original_get_sprite(class_index, rng)

    factory._catalog.get_sprite = flaky_get_sprite  # monkeypatch каталога, не приватного поля фабрики

    factory.force_defect_next()
    with pytest.raises(OSError):
        factory.make(object_id="fail", spawn_encoder=0.0, rng=np.random.default_rng(0))

    # Флаг пережил транзитный сбой — следующий УСПЕШНЫЙ make() всё равно получает брак.
    ok = factory.make(object_id="ok", spawn_encoder=0.0, rng=np.random.default_rng(1))
    assert ok.passport.defect == "damaged"

    # А следующий за ним — уже нет (флаг одноразовый, не залип).
    after = factory.make(object_id="after", spawn_encoder=1.0, rng=np.random.default_rng(2))
    assert after.passport.defect is None


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


# --------------------------------------------------------------------------
# Зарезервированные имена слоёв "base"/"damaged"
# --------------------------------------------------------------------------


@pytest.mark.parametrize("reserved_name", ["base", "damaged"])
def test_reserved_layer_name_rejected_with_catalog(tmp_path, reserved_name):
    """Ревью 2026-09-22: раньше пресет+фабрика собирались ОК, а падал только make() на
    дубликате имени слоя — ошибка должна быть на границе пресета, с понятным текстом."""
    from pydantic import ValidationError

    _write_fixture_catalog(tmp_path / "catalog", CLASS_COLORS)
    layer_sprite = tmp_path / "layer.png"
    rgba = np.zeros((8, 8, 4), dtype=np.uint8)
    rgba[:, :, 3] = 255
    imwrite_unicode(layer_sprite, cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))

    with pytest.raises(ValidationError, match=reserved_name):
        ScenePreset.from_dict(
            {
                "catalog_dir": str(tmp_path / "catalog"),
                "layers": [{"name": reserved_name, "mode": "static", "sprite_source": str(layer_sprite)}],
            }
        )


def test_reserved_layer_name_allowed_without_catalog():
    """Без catalog_dir (layers-only пресет) имя "base" остаётся легальным — коллизии нет,
    ObjectFactory в эту ветку не заходит (test_acceptance_3_1.py уже использует "base" так)."""
    preset = ScenePreset.from_dict(
        {"catalog_dir": None, "layers": [{"name": "base", "mode": "static", "sprite_source": "fixture://x"}]}
    )
    assert preset.layers[0].name == "base"


# --------------------------------------------------------------------------
# Дефект-заплатка замаскирована альфой базы (круглый диск)
# --------------------------------------------------------------------------


def test_defect_blob_masked_by_base_alpha_round_disk(tmp_path):
    """Ревью 2026-09-22: круглый диск на квадратном холсте (alpha=0 в углах) — заплатка
    не красит прозрачные углы, даже если прямоугольник occlusion геометрически туда лезет."""
    size = 64
    base = np.zeros((size, size, 4), dtype=np.uint8)
    base[:, :, :3] = 180
    mask = np.zeros((size, size), dtype=np.uint8)
    cv2.circle(mask, (size // 2, size // 2), int(0.7 * size / 2), 255, -1)  # диск, не квадрат
    base[:, :, 3] = mask

    blob = ObjectFactory._build_defect_blob(base)
    blob_opaque = blob[:, :, 3] > 0
    outside_base = base[:, :, 3] == 0
    assert int(np.count_nonzero(blob_opaque & outside_base)) == 0  # ни одного пикселя мимо базы


# --------------------------------------------------------------------------
# [lead 3.2, break-injection K4/K10] — свойства, которые выживали под инъекцией
# --------------------------------------------------------------------------


def test_defect_last_with_augmented_extra_layer(tmp_path):
    """LS-006/LS-007: defect-слой стоит ПОСЛЕ слоёв пресета. Без доп. слоя порядок не наблюдаем
    (K4 выживал); с augmented-слоем перестановка сдвигает его rng-подпоток, и «defect=None
    побитово равен объекту без defect-слоя» ломается.

    Эталон — draw-order-free: класс/угол берутся из ГОТОВОГО паспорта объекта фабрики (не
    повторным розыгрышем в предполагаемом порядке трат rng — порядок трат make() НЕ часть
    контракта seed, см. LS-007), а рендер строится СВЕЖИМ `np.random.default_rng(seed)` —
    `Generator.spawn()` даёт независимые подпотоки вне зависимости от того, что было прочитано
    из родителя раньше (проверено вручную: `rng.spawn(2)[1]` не меняется от лишних draw()
    перед spawn()), поэтому эталон валиден без знания внутреннего порядка вызовов factory.make().
    Свойство, которое реально проверяется — «damaged» последним в списке слоёв: если временно
    переставить его перед `label` в `factory.py`, этот тест краснеет (проверено вручную и
    отменено — production-код не меняется этим тестом)."""
    from Services.line_sim import LayerAugment, LayeredObject, LayerSpec, ObjectPassport

    _write_fixture_catalog(tmp_path / "catalog", {"red": (200, 30, 30), "green": (30, 200, 30)})
    label = np.zeros((10, 10, 4), dtype=np.uint8)
    label[2:8, 2:8] = (20, 20, 220, 255)
    imwrite_unicode(tmp_path / "label.png", cv2.cvtColor(label, cv2.COLOR_RGBA2BGRA))
    extra = {
        "name": "label",
        "mode": "augmented",
        "sprite_source": "label.png",
        "augment": {"offset_x_px": [-8.0, 8.0], "angle_deg": [-40.0, 40.0]},
    }
    preset = ScenePreset.from_yaml(_write_preset_yaml(tmp_path, "catalog", layers=[extra], defect_probability=0.0))
    factory = ObjectFactory(preset)

    from Services.line_sim.core.catalog_bridge import load_catalog

    catalog = load_catalog(tmp_path / "catalog")

    for seed in range(5):
        obj = factory.make(object_id="o", spawn_encoder=0.0, rng=np.random.default_rng(seed))
        assert obj.passport.defect is None

        # База — эталон УЖЕ ИЗВЕСТНОГО класса объекта (из паспорта), не повторный розыгрыш
        # индекса классом фабрики; фикстура даёт по одному эталону на класс, alpha=255 везде.
        class_index = catalog.class_names.index(obj.passport.class_name)
        base = catalog.sprites(class_index)[0]

        layers = [
            LayerSpec(name="base", mode="static", sprite_source=base),
            LayerSpec(
                name="label",
                mode="augmented",
                sprite_source=label,
                augment=LayerAugment(offset_x_px=(-8.0, 8.0), angle_deg=(-40.0, 40.0)),
            ),
        ]
        passport = ObjectPassport(
            object_id="o",
            class_name=obj.passport.class_name,
            angle_deg=obj.passport.angle_deg,
            defect=None,
            spawn_encoder=0.0,
        )
        expected = LayeredObject(passport, layers, np.random.default_rng(seed))
        assert obj.passport.layer_params["label"] == expected.passport.layer_params["label"]
        assert np.array_equal(obj.render(), expected.render())


def test_angle_range_lo_gt_hi_rejected():
    """K10 выживал: angle_range_deg с lo > hi — ошибка валидации с именем поля."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="angle_range_deg"):
        ScenePreset.from_dict({"catalog_dir": "x", "angle_range_deg": [30.0, 10.0]})


def test_rgb_extra_layer_image_rejected_with_clear_text(tmp_path):
    """[lead 3.2, break-injection M4] без проверки RGB-картинка доп. слоя падала на невнятном
    cv2.error из cvtColor; отказ обязан назвать файл и сказать про альфа-канал."""
    _write_fixture_catalog(tmp_path / "catalog", {"red": (200, 30, 30)})
    rgb = np.zeros((8, 8, 3), dtype=np.uint8)
    imwrite_unicode(tmp_path / "flat.png", rgb)
    extra = {"name": "label", "mode": "static", "sprite_source": "flat.png"}
    preset = ScenePreset.from_yaml(_write_preset_yaml(tmp_path, "catalog", layers=[extra]))
    with pytest.raises(ValueError, match=r"flat\.png.*(RGBA|альфа)"):
        ObjectFactory(preset)
