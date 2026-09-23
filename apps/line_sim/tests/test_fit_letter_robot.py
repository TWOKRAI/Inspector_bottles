# -*- coding: utf-8 -*-
"""RED-приёмка Task 5.3b — сторож дрейфа «сим под боевой рецепт», §4.1 контракта.

Независимый tester, worktree на коммите контракта лида (``bfe9edd4``), до реализации.
Контракт — ТОЛЬКО §4.1/§4.4 ``plans/line-sim/phase-5-contract-5.3.md``. Числа обоих
YAML читаются как данные (не копируются литералом из плана, кроме признаков «есть
такой ключ»), диск рисуется настоящим ``SceneCompositor``, центр ищется по пикселям
кадра, сверка — настоящей ``bilinear_px_to_mm`` прототипа в нескольких точках ROI.

**Интерпретация тестера:** ``SceneCompositor`` сегодня НЕ принимает ``belt_direction``/
``entry_x_px`` (Task 4.2.1 контракта, ещё не реализован) — главный дрейф-тест ожидаемо
падает ``TypeError: unexpected keyword argument`` на конструкции компоновщика, до того
как числа вообще сравниваются. ``resolution``-тест и diameter-тест падают на числах
конфигов (сим ещё не подогнан) и на отсутствующем модуле
``Services.line_sim.tools.make_letter_catalog`` (Task 4.2.4, новый файл) — оба
провала «по конфигу/модулю», не по фейку харнесса.

**Фейк харнесса (назван явно):** вместо реального ``ObjectSpawner``/``ObjectFactory``
(требуют ``LayerSpec``+``rng`` — лишняя сложность для геометрического теста) —
дьюк-тайпнутый спавнер с ОДНИМ объектом: ``.active_objects()`` -> список из одного
объекта с ``.passport`` (``ObjectPassport``) и ``.render()`` (RGBA-диск). Это ровно
то, что читает ``SceneCompositor.render()`` (``spawner.active_objects()``,
``obj.render()``, ``obj.passport``) — проверено чтением ``scene_compositor.py`` в
этом же коммите.

**Ловушка кадра (BGR-в-имени / RGB-в-памяти):** докстринг ``scene_compositor.py``
говорит прямо — кадр хранится RGB uint8, ``background_bgr`` — только имя параметра
из более старого контракта, канал 0 кадра ЭТО НЕ «B». Центр диска здесь ищется по
НОМЕРУ канала (индекс 1), а не по названию цвета: спрайт заливает канал 1 значением
255, фон (по умолчанию (60,60,60)) держит канал 1 на 60 — маска
``frame[:, :, 1] > 200`` находит диск независимо от каких-либо RGB/BGR-соглашений.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

from Plugins.processing.pixel_to_robot.geometry import bilinear_px_to_mm
from Services.line_sim.core.matching import BeltGeometry, object_robot_xy
from Services.line_sim.core.scene_compositor import SceneCompositor
from Services.line_sim.interfaces import ObjectPassport
from Services.robot_comm.core.registers import FACTOR_MM

pytestmark = pytest.mark.timeout(30)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RECIPE_PATH = _REPO_ROOT / "multiprocess_prototype/recipes/hikvision_letter_robot.yaml"
_SIM_RECIPE_PATH = _REPO_ROOT / "multiprocess_prototype/recipes/letter_robot_sim.yaml"
_PIPELINE_PATH = _REPO_ROOT / "apps/line_sim/pipeline.yaml"

# Маркер-канал спрайта — диск заливается этим значением в индексе 1 кадра (см. докстринг
# файла, «ловушка кадра»); фон по умолчанию (60,60,60) даёт 60 в том же канале.
_MARKER_CHANNEL = 1
_MARKER_VALUE = 255
_BG_DEFAULT = 60
_MARKER_THRESHOLD = (_MARKER_VALUE + _BG_DEFAULT) // 2  # 157


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _find_plugin_config(process: dict, plugin_class_suffix: str) -> dict:
    """Конфиг первого плагина процесса, чей ``plugin_class`` кончается на суффикс."""
    for plugin in process["plugins"]:
        if plugin["plugin_class"].endswith(plugin_class_suffix):
            return plugin["config"]
    raise AssertionError(f"плагин с суффиксом класса {plugin_class_suffix!r} не найден в процессе")


def _find_process(processes: list[dict], name: str) -> dict:
    for proc in processes:
        if proc["process_name"] == name:
            return proc
    raise AssertionError(f"процесс {name!r} не найден")


def _recipe_camera_config() -> dict:
    recipe = _load_yaml(_RECIPE_PATH)
    camera = _find_process(recipe["blueprint"]["processes"], "camera_0")
    return _find_plugin_config(camera, "HikvisionCameraPlugin")


def _recipe_roi_crop_config() -> dict:
    recipe = _load_yaml(_RECIPE_PATH)
    vision = _find_process(recipe["blueprint"]["processes"], "vision")
    return _find_plugin_config(vision, "RoiCropPlugin")


def _recipe_circle_detector_config() -> dict:
    recipe = _load_yaml(_RECIPE_PATH)
    vision = _find_process(recipe["blueprint"]["processes"], "vision")
    return _find_plugin_config(vision, "CircleDetectorPlugin")


def _recipe_pixel_to_robot_config() -> dict:
    recipe = _load_yaml(_RECIPE_PATH)
    recog = _find_process(recipe["blueprint"]["processes"], "recog")
    return _find_plugin_config(recog, "PixelToRobotPlugin")


def _sim_recipe_camera_config() -> dict:
    sim_recipe = _load_yaml(_SIM_RECIPE_PATH)
    camera = _find_process(sim_recipe["blueprint"]["processes"], "camera_0")
    return _find_plugin_config(camera, "CameraServicePlugin")


def _pipeline_scene_source_config() -> dict:
    pipeline = _load_yaml(_PIPELINE_PATH)
    camera_proc = next(p for p in pipeline["processes"] if p["process_name"] == "camera")
    for plugin in camera_proc["plugins"]:
        if plugin["plugin_class"].endswith("SceneSourcePlugin"):
            return plugin
    raise AssertionError("scene_source плагин не найден в apps/line_sim/pipeline.yaml")


def _make_disc_sprite(diameter_px: int) -> np.ndarray:
    """Непрозрачный диск RGBA: альфа=255 внутри круга, маркер-канал=255 внутри."""
    r = diameter_px // 2
    size = diameter_px
    yy, xx = np.ogrid[:size, :size]
    center = size / 2.0
    mask = (xx - center) ** 2 + (yy - center) ** 2 <= r * r
    sprite = np.zeros((size, size, 4), dtype=np.uint8)
    sprite[mask, _MARKER_CHANNEL] = _MARKER_VALUE
    sprite[mask, 3] = 255
    return sprite


class _FakeObj:
    """Дьюк-тайпнутый объект спавнера — см. докстринг файла, «фейк харнесса»."""

    def __init__(self, passport: ObjectPassport, sprite: np.ndarray) -> None:
        self.passport = passport
        self._sprite = sprite

    def render(self) -> np.ndarray:
        return self._sprite


class _FakeSpawner:
    """Ровно один активный объект — минимум, который читает ``SceneCompositor.render()``."""

    def __init__(self, obj: _FakeObj) -> None:
        self._obj = obj

    def active_objects(self) -> list[_FakeObj]:
        return [self._obj]


def _find_marker_centroid(frame: np.ndarray) -> tuple[float, float]:
    mask = frame[:, :, _MARKER_CHANNEL] > _MARKER_THRESHOLD
    ys, xs = np.nonzero(mask)
    assert xs.size > 0, "диск не найден в кадре — маркер-канал пуст (спрайт целиком за кадром?)"
    return float(xs.mean()), float(ys.mean())


def test_sim_disc_centre_maps_to_same_robot_xy_as_prototype():
    """Проверка согласованности §4.1 (главный критерий контракта): центр диска,
    нарисованного настоящим ``SceneCompositor``, переведённый ``bilinear_px_to_mm``
    прототипа, совпадает с ``object_robot_xy`` сима не хуже 0.5 мм в >= 3 точках ROI.
    """
    roi = _recipe_roi_crop_config()
    lin = _recipe_pixel_to_robot_config()
    tl = (lin["lin_tl_x"], lin["lin_tl_y"])
    tr = (lin["lin_tr_x"], lin["lin_tr_y"])
    br = (lin["lin_br_x"], lin["lin_br_y"])
    bl = (lin["lin_bl_x"], lin["lin_bl_y"])

    scene_cfg = _pipeline_scene_source_config()
    px_per_mm = float(scene_cfg["px_per_mm"])
    belt_y_px = float(scene_cfg["belt_y_px"])
    resolution_width = int(scene_cfg["resolution_width"])
    resolution_height = int(scene_cfg["resolution_height"])
    geom_cfg = scene_cfg["geometry"]
    geometry = BeltGeometry(origin_x_mm=float(geom_cfg["origin_x_mm"]), origin_y_mm=float(geom_cfg["origin_y_mm"]))
    # §4.2.1/§4.2.2: ключи, которых сегодня ещё нет в pipeline.yaml — дефолты те же,
    # что документирует контракт для belt_direction=+1 (поведение до Task 4.2.2).
    belt_direction = int(scene_cfg.get("belt_direction", 1))
    entry_x_px = float(scene_cfg.get("entry_x_px", 0.0))

    diameter_px = 300  # §4.1: диаметр диска сима (окно circle_detector 90..230, середина ~150)
    sprite = _make_disc_sprite(diameter_px)

    # >= 3 точки, разнесённые по ROI (мм от точки спавна вдоль ленты).
    offsets_mm = [30.0, 55.0, 80.0]
    max_delta_mm = 0.5

    for off_mm in offsets_mm:
        encoder = off_mm / FACTOR_MM
        passport = ObjectPassport(object_id="disc-1", class_name="А", angle_deg=0.0, defect=None, spawn_encoder=0.0)
        obj = _FakeObj(passport, sprite)
        spawner = _FakeSpawner(obj)

        # Task 4.2.1: конструктор ещё не принимает belt_direction/entry_x_px — TypeError
        # ожидаемый провал ДО реализации.
        compositor = SceneCompositor(
            spawner,
            px_per_mm=px_per_mm,
            belt_y_px=belt_y_px,
            belt_direction=belt_direction,
            entry_x_px=entry_x_px,
        )
        camera_rect = (0.0, 0.0, float(resolution_width), float(resolution_height))
        frame, passports = compositor.render(now_encoder=encoder, camera_rect=camera_rect)
        assert passports, "диск не попал в кадр — сместите offsets_mm теста"

        centre_x_px, centre_y_px = _find_marker_centroid(frame)
        x_roi = centre_x_px - float(roi["x"])
        y_roi = centre_y_px - float(roi["y"])
        proto_x_mm, proto_y_mm = bilinear_px_to_mm(x_roi, y_roi, roi["width"], roi["height"], tl, tr, br, bl)

        sim_x_mm, sim_y_mm = object_robot_xy(spawn_encoder=0.0, ecap=encoder, geometry=geometry)

        assert abs(proto_x_mm - sim_x_mm) <= max_delta_mm, (
            f"off={off_mm}мм: X прототипа={proto_x_mm:.3f} против X сима={sim_x_mm:.3f}"
        )
        assert abs(proto_y_mm - sim_y_mm) <= max_delta_mm, (
            f"off={off_mm}мм: Y прототипа={proto_y_mm:.3f} против Y сима={sim_y_mm:.3f}"
        )


def test_resolutions_agree():
    """§4.1/§4.3: разрешение сима = разрешению камеры рецепта = блоку источника
    сим-рецепта (``letter_robot_sim.yaml``, camera_0.plugins[0].config)."""
    recipe_cam = _recipe_camera_config()
    scene_cfg = _pipeline_scene_source_config()
    sim_recipe_cam = _sim_recipe_camera_config()

    assert scene_cfg["resolution_width"] == recipe_cam["resolution_width"]
    assert scene_cfg["resolution_height"] == recipe_cam["resolution_height"]
    assert sim_recipe_cam["resolution_width"] == recipe_cam["resolution_width"]
    assert sim_recipe_cam["resolution_height"] == recipe_cam["resolution_height"]


def test_disc_diameter_inside_circle_detector_window():
    """§4.1/§4.2.4: ``DEFAULT_DIAMETER_PX / 2`` каталожного инструмента внутри окна
    ``circle_detector`` [min_radius, max_radius] рецепта."""
    circle_cfg = _recipe_circle_detector_config()

    # Services.line_sim.tools.make_letter_catalog — НОВЫЙ модуль (Task 4.2.4), сегодня
    # не существует: ModuleNotFoundError — ожидаемый провал ДО реализации.
    from Services.line_sim.tools import make_letter_catalog

    radius_px = make_letter_catalog.DEFAULT_DIAMETER_PX / 2
    assert circle_cfg["min_radius"] <= radius_px <= circle_cfg["max_radius"], (
        f"радиус диска {radius_px} вне окна circle_detector [{circle_cfg['min_radius']}, {circle_cfg['max_radius']}]"
    )
