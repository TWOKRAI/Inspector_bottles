"""RED-приёмка Task 1.1b, блок A — слой класса (`sprite_source: "class://"`).

Независимый тест (blind): пишется ДО реализации, по спеке `plans/line-sim-layer-editor/phase-1-engine.md`
(раздел Task 1.1b, критерии A1-A5). НЕ читает `Services/line_sim/core/*.py`.

Каталог фикстур: `cat/<class>/<file>.png` — по одному спрайту на класс, BGRA на диске
(cv2.imwrite ожидает BGR(A), контракт `SpriteCatalog._load_sprite` конвертирует обратно
в RGBA при чтении). Диск — `disk.png`, 60x60 белый непрозрачный круг.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from Services.line_sim import ObjectFactory, ScenePreset
from Services.line_sim.interfaces import LayerSpec

CLASS_SPRITE_SOURCE = "class://"  # литерал спеки А; сверяется отдельным тестом с экспортом модуля


def _rgba(h: int, w: int, rgb: tuple[int, int, int], alpha: int = 255) -> np.ndarray:
    """Непрозрачный прямоугольник h x w цвета rgb (RGBA uint8)."""
    img = np.zeros((h, w, 4), dtype=np.uint8)
    img[:, :, 0], img[:, :, 1], img[:, :, 2] = rgb
    img[:, :, 3] = alpha
    return img


def _write_rgba_png(path: Path, rgba: np.ndarray) -> None:
    """Записать RGBA-массив на диск как BGRA (cv2.imwrite ждёт BGR(A))."""
    path.parent.mkdir(parents=True, exist_ok=True)
    bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
    ok = cv2.imwrite(str(path), bgra)
    assert ok, f"cv2.imwrite не смог записать {path}"


def _make_disk(diameter: int = 60) -> np.ndarray:
    """Белый непрозрачный диск на прозрачном фоне размера diameter x diameter."""
    img = np.zeros((diameter, diameter, 4), dtype=np.uint8)
    r = diameter // 2
    cy = cx = r
    yy, xx = np.ogrid[:diameter, :diameter]
    mask = (yy - cy) ** 2 + (xx - cx) ** 2 <= (r - 1) ** 2
    img[mask, 0:3] = 255
    img[mask, 3] = 255
    return img


@pytest.fixture
def catalog_dir(tmp_path: Path) -> Path:
    """cat/A -> красный квадрат 20x20 непрозрачный; cat/B -> зелёный квадрат 20x20."""
    root = tmp_path / "cat"
    _write_rgba_png(root / "A" / "sprite.png", _rgba(20, 20, (255, 0, 0)))
    _write_rgba_png(root / "B" / "sprite.png", _rgba(20, 20, (0, 255, 0)))
    return root


@pytest.fixture
def bar_catalog_dir(tmp_path: Path) -> Path:
    """cat/C -> чёрная горизонтальная полоса 20 (ширина) x 4 (высота), для теста поворота (A4)."""
    root = tmp_path / "cat_bar"
    _write_rgba_png(root / "C" / "sprite.png", _rgba(4, 20, (0, 0, 0)))
    return root


@pytest.fixture
def disk_path(tmp_path: Path) -> Path:
    p = tmp_path / "disk.png"
    _write_rgba_png(p, _make_disk(60))
    return p


@pytest.fixture
def extra_sprite_path(tmp_path: Path) -> Path:
    """Доп. непрозрачный синий квадрат 8x8 — вне каталога классов, sprite_source = строка-путь
    (ScenePreset.layers требует sprite_source строкой-id, сырые ndarray в него не проходят)."""
    p = tmp_path / "extra.png"
    _write_rgba_png(p, _rgba(8, 8, (0, 0, 255)))
    return p


COLOR_BY_CLASS = {"A": (255, 0, 0), "B": (0, 255, 0)}  # литерал, совпадает с catalog_dir выше


def test_class_sprite_source_constant_matches_export() -> None:
    """Экспортированная константа CLASS_SPRITE_SOURCE == "class://" (сборка публичного API)."""
    from Services.line_sim import CLASS_SPRITE_SOURCE as exported

    assert exported == "class://"


def test_legacy_catalog_control_renders_green(catalog_dir: Path, extra_sprite_path: Path) -> None:
    """GREEN-контроль: каталог-фикстура валиден уже сегодня — legacy-пресет без class:// рендерится.

    Проверяет фикстуру `catalog_dir`, а не новую фичу: если этот тест красный —
    проблема в фикстуре, а не в отсутствующей реализации 1.1b.
    """
    extra = LayerSpec(name="extra", mode="static", sprite_source=str(extra_sprite_path), offset_px=(5.0, 5.0))
    preset = ScenePreset(
        catalog_dir=str(catalog_dir), layers=[extra], defect_probability=0.0, angle_range_deg=(0.0, 0.0)
    )
    obj = ObjectFactory(preset).make("o1", 0.0, np.random.default_rng(1))
    frame = obj.render()
    assert frame.dtype == np.uint8
    assert frame.shape[2] == 4
    assert obj.passport.class_name in ("A", "B")


def test_class_layer_first_equals_legacy_base(catalog_dir: Path, extra_sprite_path: Path) -> None:
    """A1: [class://, доп.слой] рендерится побитово как [доп.слой] без class:// (тот же seed)."""
    extra = LayerSpec(name="extra", mode="static", sprite_source=str(extra_sprite_path), offset_px=(5.0, 5.0))
    legacy = ScenePreset(
        catalog_dir=str(catalog_dir), layers=[extra], defect_probability=0.0, angle_range_deg=(0.0, 0.0)
    )
    class_layer = LayerSpec(name="letter", mode="static", sprite_source=CLASS_SPRITE_SOURCE)
    with_class = ScenePreset(
        catalog_dir=str(catalog_dir),
        layers=[class_layer, extra],
        defect_probability=0.0,
        angle_range_deg=(0.0, 0.0),
    )

    frame_legacy = ObjectFactory(legacy).make("o1", 0.0, np.random.default_rng(7)).render()
    frame_class = ObjectFactory(with_class).make("o1", 0.0, np.random.default_rng(7)).render()

    assert frame_legacy.shape == frame_class.shape
    assert np.array_equal(frame_legacy, frame_class)


def test_class_layer_order_decides_what_is_on_top(catalog_dir: Path, disk_path: Path) -> None:
    """A2: порядок [disk, class://] -> центр = цвет буквы класса; [class://, disk] -> центр = белый диск."""
    class_layer = LayerSpec(name="letter", mode="static", sprite_source=CLASS_SPRITE_SOURCE, offset_px=(0.0, 0.0))
    disk_layer = LayerSpec(name="disk", mode="static", sprite_source=str(disk_path), offset_px=(0.0, 0.0))

    preset_class_on_top = ScenePreset(
        catalog_dir=str(catalog_dir),
        layers=[disk_layer, class_layer],
        defect_probability=0.0,
        angle_range_deg=(0.0, 0.0),
    )
    preset_disk_on_top = ScenePreset(
        catalog_dir=str(catalog_dir),
        layers=[class_layer, disk_layer],
        defect_probability=0.0,
        angle_range_deg=(0.0, 0.0),
    )

    obj_class_top = ObjectFactory(preset_class_on_top).make("o1", 0.0, np.random.default_rng(3))
    frame_class_top = obj_class_top.render()
    cy, cx = frame_class_top.shape[0] // 2, frame_class_top.shape[1] // 2
    expected_color = COLOR_BY_CLASS[obj_class_top.passport.class_name]
    assert tuple(int(v) for v in frame_class_top[cy, cx, 0:3]) == expected_color

    obj_disk_top = ObjectFactory(preset_disk_on_top).make("o1", 0.0, np.random.default_rng(3))
    frame_disk_top = obj_disk_top.render()
    cy2, cx2 = frame_disk_top.shape[0] // 2, frame_disk_top.shape[1] // 2
    assert tuple(int(v) for v in frame_disk_top[cy2, cx2, 0:3]) == (255, 255, 255)


def _two_class_layers() -> list[LayerSpec]:
    return [
        LayerSpec(name="letter_a", mode="static", sprite_source=CLASS_SPRITE_SOURCE),
        LayerSpec(name="letter_b", mode="static", sprite_source=CLASS_SPRITE_SOURCE),
    ]


def _one_class_layer() -> list[LayerSpec]:
    return [LayerSpec(name="letter_a", mode="static", sprite_source=CLASS_SPRITE_SOURCE)]


def _class_layer_in_defect_mode() -> list[LayerSpec]:
    return [
        LayerSpec(
            name="letter_a",
            mode="defect",
            sprite_source=CLASS_SPRITE_SOURCE,
            defect_probability=0.5,
        )
    ]


@pytest.mark.parametrize(
    ("build_layers", "use_catalog_dir"),
    [
        (_two_class_layers, True),
        (_one_class_layer, False),
        (_class_layer_in_defect_mode, True),
    ],
    ids=["two_class_layers", "class_without_catalog_dir", "class_in_defect_mode"],
)
def test_class_layer_validation_errors(catalog_dir: Path, build_layers, use_catalog_dir: bool) -> None:
    """A3: два class://; class:// без catalog_dir; class:// в defect — ValidationError с именем слоя."""
    layers = build_layers()
    catalog_arg = str(catalog_dir) if use_catalog_dir else None

    with pytest.raises(ValidationError) as exc_info:
        ScenePreset(catalog_dir=catalog_arg, layers=layers, defect_probability=0.0, angle_range_deg=(0.0, 0.0))

    assert "letter" in str(exc_info.value)


def test_class_layer_augmented_rotates_only_letter(bar_catalog_dir: Path, disk_path: Path) -> None:
    """A4: слой класса augmented angle_deg=(90,90) поворачивает только букву; диск на месте."""
    from Services.line_sim.interfaces import LayerAugment

    disk_layer = LayerSpec(name="disk", mode="static", sprite_source=str(disk_path), offset_px=(0.0, 0.0))
    class_layer = LayerSpec(
        name="letter",
        mode="augmented",
        sprite_source=CLASS_SPRITE_SOURCE,
        offset_px=(0.0, 0.0),
        augment=LayerAugment(angle_deg=(90.0, 90.0)),
    )
    preset = ScenePreset(
        catalog_dir=str(bar_catalog_dir),
        layers=[disk_layer, class_layer],
        defect_probability=0.0,
        angle_range_deg=(0.0, 0.0),
    )
    obj = ObjectFactory(preset).make("o1", 0.0, np.random.default_rng(11))
    frame = obj.render()

    alpha = frame[:, :, 3]
    ys, xs = np.nonzero(alpha)
    assert len(ys) > 0, "после поворота нет непрозрачных пикселей вовсе"
    # диск (60px) доминирует в общем bbox альфа-канала кадра, поэтому bbox всей альфы
    # тут не покажет поворот буквы отдельно — берём непрозрачные пиксели буквы через
    # цвет: полоса чёрная (0,0,0), диск белый (255,255,255).
    rgb = frame[:, :, 0:3]
    letter_mask = (alpha > 0) & (rgb[:, :, 0] < 50) & (rgb[:, :, 1] < 50) & (rgb[:, :, 2] < 50)
    lys, lxs = np.nonzero(letter_mask)
    assert len(lys) > 0, "чёрных пикселей буквы не найдено после поворота"
    letter_h = int(lys.max() - lys.min() + 1)
    letter_w = int(lxs.max() - lxs.min() + 1)
    # исходная полоса 20(ширина) x 4(высота); после поворота на 90° ожидаем 4(ширина) x 20(высота)
    assert abs(letter_w - 4) <= 1, f"ширина буквы после поворота {letter_w}, ожидали 4±1"
    assert abs(letter_h - 20) <= 1, f"высота буквы после поворота {letter_h}, ожидали 20±1"

    disk_mask = (alpha > 0) & (rgb[:, :, 0] > 200) & (rgb[:, :, 1] > 200) & (rgb[:, :, 2] > 200)
    dys, dxs = np.nonzero(disk_mask)
    assert len(dys) > 0, "белых пикселей диска не найдено"
    disk_h = int(dys.max() - dys.min() + 1)
    disk_w = int(dxs.max() - dxs.min() + 1)
    assert abs(disk_h - 60) <= 1 and abs(disk_w - 60) <= 1, "диск сдвинулся/изменился поворотом буквы"


def test_forced_defect_with_class_layer_keeps_alpha(catalog_dir: Path) -> None:
    """A5: force_defect_next() + слой класса -> defect == "damaged", рендер отличается, альфа та же."""
    class_layer = LayerSpec(name="letter", mode="static", sprite_source=CLASS_SPRITE_SOURCE)
    preset = ScenePreset(
        catalog_dir=str(catalog_dir),
        layers=[class_layer],
        defect_probability=0.0,
        angle_range_deg=(0.0, 0.0),
    )

    factory_plain = ObjectFactory(preset)
    obj_plain = factory_plain.make("o1", 0.0, np.random.default_rng(5))
    frame_plain = obj_plain.render()
    assert obj_plain.passport.defect is None

    factory_defect = ObjectFactory(preset)
    factory_defect.force_defect_next()
    obj_defect = factory_defect.make("o1", 0.0, np.random.default_rng(5))
    frame_defect = obj_defect.render()

    assert obj_defect.passport.defect == "damaged"
    assert frame_defect.shape == frame_plain.shape
    assert not np.array_equal(frame_defect[:, :, 0:3], frame_plain[:, :, 0:3])
    assert np.array_equal(frame_defect[:, :, 3], frame_plain[:, :, 3])
