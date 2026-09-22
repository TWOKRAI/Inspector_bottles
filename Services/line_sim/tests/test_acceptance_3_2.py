"""Независимые acceptance-тесты Task 3.2 — контент пресета `letters_disk` + ObjectFactory
+ дефект-слой "damaged". Написаны ДО реализации (RED-фаза, tester не видел `_impl/`/Steps
плана). Источник истины — Acceptance criteria и блок "Уточнено лидом 2026-09-22 перед
тестером" в `plans/line-sim/phase-3-object-engine.md` (раздел Task 3.2), НЕ код под тестом.

Публичный контракт под тестом (новое в этой задаче):
    from Services.line_sim import ObjectFactory
    ScenePreset — новые поля: catalog_dir, angle_range_deg, defect_probability, layers (default [])

================================================================================
ПРЕДПОЛОЖЕНИЯ О СИГНАТУРАХ (лид дал контракт явно там, где мог; ниже — что ИМЕННО
дано лидом дословно, и что ДОГАДАНО тестером сверх этого):
================================================================================

ДАНО ЛИДОМ ДОСЛОВНО (не догадка):
- `ObjectFactory(preset: ScenePreset)` — грузит каталог через catalog_bridge при
  конструировании (eager, не lazy — иначе num_classes сразу после конструктора не
  имел бы смысла).
- `ObjectFactory.num_classes: int`, `.class_names: list[str]`.
- `ObjectFactory.make(object_id, spawn_encoder, rng) -> LayeredObject` — класс и угол
  выбираются из rng внутри make(); база = спрайт класса (`mode="static"`, имя `"base"`),
  затем слои пресета (здесь всегда `[]`), последним — defect-слой `"damaged"` с
  `defect_probability` пресета.
- `ObjectFactory.force_defect_next()` — ровно следующий `make()` получает
  `passport.defect == "damaged"` независимо от вероятности.
- `ScenePreset` новые поля: `catalog_dir: str | None`, `angle_range_deg: tuple[float,
  float] = (0.0, 360.0)`, `defect_probability: float = 0.0` (вне [0,1] — ValidationError),
  `layers` — дефолт `[]`. Пресет без каталога И без слоёв — ValidationError
  (min_length=1 снимается).
- `catalog_dir` относителен от каталога YAML-файла (как `GeneratorConfig.classes_dir` в
  `Services.dataset_gen.core.config` — тот же паттерн, лид явно сослался на dataset_gen).
- Критерий 1 читается как `ObjectFactory(ScenePreset.from_yaml(...)).num_classes >= 1`.
- Критерий 2 (defect=None побитово равен объекту без defect-слоя): сравнивать объект
  фабрики (defect_probability=0) с объектом из ТЕХ ЖЕ слоёв БЕЗ defect-слоя, класс/угол
  берутся из паспорта объекта фабрики (не из рендера).

ДОГАДАНО ТЕСТЕРОМ (лид явно не писал число/имя — если реализация разойдётся,
developer поправит тест, сам факт критерия остаётся acceptance-требованием):
- Базовый слой конструируется фабрикой с ДЕФОЛТАМИ `LayerSpec` (offset_px=(0,0),
  scale=1.0, angle_deg=0.0) — лид сказал только "mode='static', имя 'base'", не
  параметры трансформа. Сравнительный объект в тесте построен так же.
- Имя дефект-слоя `"damaged"` — дано лидом дословно в Acceptance criteria/уточнении,
  НЕ догадка.
- `class_names` каталога отсортированы по имени листовой папки — подтверждено чтением
  `Services/dataset_gen/core/catalog.py::SpriteCatalog._collect_classes/load`
  (сортировка `leaves.sort(key=lambda item: item[0])`, путь = кортеж имён папок) — не
  догадка, а факт уже существующего (не переоткрываемого) кода.
- PNG-раундтрип через `imwrite_unicode`/`imread_unicode` (BGRA<->RGBA) не теряет данные
  (PNG lossless) — используется для побитового сравнения; если реализация каталога
  как-то трансформирует пиксели при загрузке (не должна, `dataset_gen` уже тестирован),
  это будет заметно как ложный failure с диагностируемой разницей, а не молчаливый.
- `ObjectFactory.make()` вызывается с ОДНИМ и тем же объектом `rng` в цикле (не новым
  на каждый вызов) — так гарантированно получаем варьирующиеся класс/угол между
  объектами; план явно этого не говорит, но иначе тест "угол варьируется по 50
  объектам" тестировал бы одно и то же значение 50 раз.

Каталог-фикстура строится в `tmp_path`: `<root>/<class_name>/sprite.png`, RGBA-квадраты
сплошного цвета (не буквы/диски — цвет и alpha делают то же самое для побитовых
сравнений и проще собрать вручную), записанные через `imwrite_unicode` (BGRA на диске,
конвертация из RGBA перед записью — то же соглашение, что у `SpriteCatalog._load_sprite`
при чтении, симметрично).
================================================================================
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml
from pydantic import ValidationError

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import LayerSpec, LayeredObject, ObjectFactory, ObjectPassport, ScenePreset

# --------------------------------------------------------------------------
# Фикстуры-помощники
# --------------------------------------------------------------------------

CLASS_COLORS: dict[str, tuple[int, int, int]] = {
    "class_a": (220, 40, 40),  # красный
    "class_b": (40, 200, 60),  # зелёный
    "class_c": (40, 80, 220),  # синий
}

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_PRESET_PATH = REPO_ROOT / "Services/line_sim/presets/letters_disk.yaml"
REAL_SPRITES_DIR = REPO_ROOT / "data/dataset_gen/ru_letters_real/sprites"


def _solid_rgba(color_rgb: tuple[int, int, int], size: int = 32) -> np.ndarray:
    """Непрозрачный RGBA-квадрат одного цвета — самодостаточный эталон класса."""
    sprite = np.zeros((size, size, 4), dtype=np.uint8)
    sprite[:, :, 0] = color_rgb[0]
    sprite[:, :, 1] = color_rgb[1]
    sprite[:, :, 2] = color_rgb[2]
    sprite[:, :, 3] = 255
    return sprite


def _write_fixture_catalog(root: Path, class_colors: dict[str, tuple[int, int, int]]) -> dict[str, np.ndarray]:
    """Создать `<root>/<class>/sprite.png` на класс; вернуть class_name -> исходный RGBA
    (эталон для побитового сравнения после раундтрипа через каталог)."""
    sprites: dict[str, np.ndarray] = {}
    for name, color in class_colors.items():
        rgba = _solid_rgba(color)
        class_dir = root / name
        class_dir.mkdir(parents=True, exist_ok=True)
        bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
        imwrite_unicode(class_dir / "sprite.png", bgra)
        sprites[name] = rgba
    return sprites


def _write_preset_yaml(tmp_path: Path, catalog_dir_name: str, filename: str = "preset.yaml", **preset_kwargs) -> Path:
    """Пресет-YAML с ОТНОСИТЕЛЬНЫМ catalog_dir (относительно каталога самого файла) —
    пиннит правило "относительно YAML-файла"."""
    preset_path = tmp_path / filename
    data: dict = {"catalog_dir": catalog_dir_name, "layers": []}
    data.update(preset_kwargs)
    preset_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return preset_path


def _base_only_render(rgba: np.ndarray, angle_deg: float) -> np.ndarray:
    """Прямая сборка объекта из ОДНОГО статического base-слоя (без defect-слоя вообще) —
    эталон для критерия 2 ("defect=None побитово равен объекту без defect-слоя")."""
    passport = ObjectPassport(
        object_id="cmp", class_name="cmp-class", angle_deg=angle_deg, defect=None, spawn_encoder=0.0
    )
    layer = LayerSpec(name="base", mode="static", sprite_source=rgba)
    obj = LayeredObject(passport=passport, layers=[layer], rng=np.random.default_rng(0))
    return obj.render()


def _differs(a: np.ndarray, b: np.ndarray) -> bool:
    """>0 пикселей отличается — устойчиво к тому, что форма канвы дефектного объекта
    может отличаться от чистого (occlusion-слой может расширить канву)."""
    if a.shape != b.shape:
        return True
    return bool(np.count_nonzero(a != b) > 0)


# --------------------------------------------------------------------------
# ObjectFactory — каталог-фикстура, num_classes
# --------------------------------------------------------------------------


def test_factory_num_classes_fixture_catalog(tmp_path):
    """AC критерий 1 (на фикстуре): num_classes >= 1, литерал = число классов фикстуры."""
    _write_fixture_catalog(tmp_path / "catalog", CLASS_COLORS)
    preset = ScenePreset.from_yaml(_write_preset_yaml(tmp_path, "catalog"))
    factory = ObjectFactory(preset)
    assert factory.num_classes == 3
    assert sorted(factory.class_names) == ["class_a", "class_b", "class_c"]


def test_single_class_catalog(tmp_path):
    """Edge case: каталог ровно с одним классом — line_sim не ломает поведение dataset_gen."""
    _write_fixture_catalog(tmp_path / "catalog", {"only_class": (10, 200, 10)})
    preset = ScenePreset.from_yaml(_write_preset_yaml(tmp_path, "catalog"))
    factory = ObjectFactory(preset)
    assert factory.num_classes == 1
    assert factory.class_names == ["only_class"]
    obj = factory.make(object_id="o1", spawn_encoder=0.0, rng=np.random.default_rng(1))
    assert obj.passport.class_name == "only_class"
    assert np.any(obj.render()[:, :, 3] > 0)


# --------------------------------------------------------------------------
# Дефект-слой "damaged" — критерии 2 и 3
# --------------------------------------------------------------------------


def test_defect_none_bitwise_equals_no_defect_layer(tmp_path):
    """AC критерий 2: defect=None -> рендер побитово равен объекту без defect-слоя
    (та же база/угол, взятые из паспорта объекта фабрики, не из его рендера)."""
    sprites = _write_fixture_catalog(tmp_path / "catalog", CLASS_COLORS)
    preset = ScenePreset.from_yaml(_write_preset_yaml(tmp_path, "catalog", defect_probability=0.0))
    factory = ObjectFactory(preset)

    obj = factory.make(object_id="o1", spawn_encoder=0.0, rng=np.random.default_rng(42))
    assert obj.passport.defect is None

    expected = _base_only_render(sprites[obj.passport.class_name], obj.passport.angle_deg)
    assert obj.render().shape == expected.shape
    assert np.array_equal(obj.render(), expected)


def test_defect_forced_differs_from_no_defect(tmp_path):
    """AC критерий 3: defect="damaged" -> рендер отличается (>0 пикселей) от объекта
    без дефекта при той же базовой букве/угле."""
    sprites = _write_fixture_catalog(tmp_path / "catalog", CLASS_COLORS)
    preset = ScenePreset.from_yaml(_write_preset_yaml(tmp_path, "catalog", defect_probability=1.0))
    factory = ObjectFactory(preset)

    obj = factory.make(object_id="o1", spawn_encoder=0.0, rng=np.random.default_rng(7))
    assert obj.passport.defect == "damaged"

    baseline = _base_only_render(sprites[obj.passport.class_name], obj.passport.angle_deg)
    assert _differs(obj.render(), baseline)


def test_defect_probability_extremes_20_of_20(tmp_path):
    """AC критерий 4: prob=1.0 -> 20/20 непустой defect; prob=0.0 -> 0/20 (только границы,
    per STRICT-канон — числа теста рядом с дефолтом, не промежуточные вероятности)."""
    _write_fixture_catalog(tmp_path / "catalog", CLASS_COLORS)

    preset_hi = ScenePreset.from_yaml(_write_preset_yaml(tmp_path, "catalog", "preset_hi.yaml", defect_probability=1.0))
    factory_hi = ObjectFactory(preset_hi)
    rng_hi = np.random.default_rng(123)
    defects_hi = [
        factory_hi.make(object_id=f"hi-{i}", spawn_encoder=0.0, rng=rng_hi).passport.defect for i in range(20)
    ]
    assert defects_hi.count(None) == 0
    assert all(d == "damaged" for d in defects_hi)

    preset_lo = ScenePreset.from_yaml(_write_preset_yaml(tmp_path, "catalog", "preset_lo.yaml", defect_probability=0.0))
    factory_lo = ObjectFactory(preset_lo)
    rng_lo = np.random.default_rng(321)
    defects_lo = [
        factory_lo.make(object_id=f"lo-{i}", spawn_encoder=0.0, rng=rng_lo).passport.defect for i in range(20)
    ]
    assert defects_lo.count(None) == 20


def test_force_defect_next_applies_to_exactly_one(tmp_path):
    """AC критерий 5: force_defect_next() один раз при prob=0.0 -> ровно СЛЕДУЮЩий
    объект получает defect не None, а объект после него — снова None."""
    _write_fixture_catalog(tmp_path / "catalog", CLASS_COLORS)
    preset = ScenePreset.from_yaml(_write_preset_yaml(tmp_path, "catalog", defect_probability=0.0))
    factory = ObjectFactory(preset)

    factory.force_defect_next()
    forced = factory.make(object_id="forced", spawn_encoder=0.0, rng=np.random.default_rng(5))
    assert forced.passport.defect == "damaged"

    after = factory.make(object_id="after", spawn_encoder=1.0, rng=np.random.default_rng(6))
    assert after.passport.defect is None


def test_angle_within_range(tmp_path):
    """Угол объекта фабрики остаётся внутри angle_range_deg пресета на 50 объектах
    (литеральный диапазон, не дефолтный 0..360)."""
    _write_fixture_catalog(tmp_path / "catalog", CLASS_COLORS)
    lo, hi = 10.0, 20.0
    preset = ScenePreset.from_yaml(_write_preset_yaml(tmp_path, "catalog", angle_range_deg=[lo, hi]))
    factory = ObjectFactory(preset)
    rng = np.random.default_rng(99)
    angles = [factory.make(object_id=f"a-{i}", spawn_encoder=0.0, rng=rng).passport.angle_deg for i in range(50)]
    assert all(lo <= a <= hi for a in angles)


# --------------------------------------------------------------------------
# ScenePreset — новые поля: валидация и round-trip
# --------------------------------------------------------------------------


def test_defect_probability_bounds():
    """defect_probability вне [0,1] -> ValidationError; валидное значение — не ошибка."""
    valid = ScenePreset.from_dict({"catalog_dir": "somewhere", "layers": [], "defect_probability": 0.5})
    assert valid.defect_probability == pytest.approx(0.5)

    with pytest.raises(ValidationError):
        ScenePreset.from_dict({"catalog_dir": "somewhere", "layers": [], "defect_probability": 1.5})


def test_preset_catalog_only_valid_and_empty_invalid():
    """Пресет только с каталогом (без layers) — валиден (min_length=1 снят); пресет БЕЗ
    каталога И без слоёв — ValidationError."""
    valid = ScenePreset.from_dict({"catalog_dir": "somewhere", "layers": []})
    assert valid.layers == []
    assert valid.catalog_dir == "somewhere"

    with pytest.raises(ValidationError):
        ScenePreset.from_dict({})


def test_scene_preset_roundtrip_new_fields():
    """AC: round-trip from_dict(to_dict()) сохраняется с новыми полями."""
    data = {
        "catalog_dir": "sprites/classes",
        "angle_range_deg": [15.0, 45.0],
        "defect_probability": 0.25,
        "layers": [],
    }
    preset = ScenePreset.from_dict(data)
    restored = ScenePreset.from_dict(preset.to_dict())
    assert restored == preset
    assert restored.catalog_dir == "sprites/classes"
    assert tuple(restored.angle_range_deg) == (15.0, 45.0)
    assert restored.defect_probability == pytest.approx(0.25)


# --------------------------------------------------------------------------
# Реальный пресет letters_disk.yaml
# --------------------------------------------------------------------------


def test_letters_disk_yaml_parses():
    """AC критерий 1 (парсинг): YAML грузится в ScenePreset БЕЗ обращения к каталогу
    спрайтов на диске (не skip — YAML сам по себе должен существовать и парситься)."""
    preset = ScenePreset.from_yaml(REAL_PRESET_PATH)
    assert preset.catalog_dir is not None


def test_real_letters_disk_num_classes_or_skip():
    """AC критерий 1 (на реальном каталоге): num_classes >= 1; skip с причиной, если
    эталоны дисков-букв реально не сняты на этой машине (2026-09-22: не сняты)."""
    if not REAL_SPRITES_DIR.is_dir():
        pytest.skip(f"эталоны не сняты владельцем: {REAL_SPRITES_DIR} отсутствует на этой машине")
    preset = ScenePreset.from_yaml(REAL_PRESET_PATH)
    factory = ObjectFactory(preset)
    assert factory.num_classes >= 1
