# -*- coding: utf-8 -*-
"""Hazard-тесты автора — Task 1.1b, блок D2 (`scene_source` собирает движок из
пресета-ФАЙЛА `.yaml`/`.yml`, не только из каталога классов).

Что проверяется и почему:
    H1. `preset_path`, оканчивающийся `.yaml`, реально даёт `ScenePreset.from_yaml()` (не
        старую ветку `ScenePreset(catalog_dir=preset_path, ...)`, которая интерпретировала
        бы путь к файлу КАК каталог классов и упала на `FileNotFoundError`/не-директорию) —
        движок собирается (`plugin._compositor is not None`) и реально рендерит кадры
        через полный цикл `start()`/`produce()` (не только `configure()` без падения).
    H2. Конфиг стенда БЕЗ ключа `defect_probability` — значение из файла пресета
        остаётся как есть (не молча заменяется дефолтом `_DEFAULT_DEFECT_PROBABILITY`).
        Проверено НАБЛЮДАЕМЫМ эффектом, не чтением поля: `defect_probability=1.0` в файле
        -> `sub.random() < 1.0` истинно ВСЕГДА (`np.random.Generator.random()` строго
        меньше 1.0) -> `LayeredObject.passport.defect == "damaged"` детерминированно,
        без розыгрыша по вероятности (не флейки-тест).
    H3. Конфиг стенда С ключом `defect_probability` (0.0) переопределяет файловое
        значение (1.0) — та же логика детерминизма в обратную сторону: `sub.random() <
        0.0` ложно всегда -> `passport.defect is None`. Переопределение идёт через
        `ScenePreset.from_dict({**p.to_dict(), ...})` (не прямая подмена поля
        frozen-модели), поэтому проверяет ещё и то, что пересборка не роняет остальные
        поля пресета (движок всё ещё собирается).

Паттерн `_FakeStateProxy`/`MagicMock`-ctx — копия `test_scene_source_task_3_6.py`
(указана лидом как готовая зависимость для этого файла), файл самодостаточен.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import cv2
import numpy as np

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from Plugins.sim.scene_source.plugin import SceneSourcePlugin
from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import ScenePreset


class _FakeStateProxy:
    """Минимальная замена ``StateProxy`` — копия паттерна `test_scene_source_task_3_6.py`."""

    def __init__(self) -> None:
        self._callbacks: list[Callable[[list[Delta]], None]] = []
        self.set_calls: list[tuple[str, object]] = []

    def subscribe(self, pattern, callback, exclude_self=True, sync=True):
        self._callbacks.append(callback)
        return str(uuid.uuid4())

    def emit(self, deltas: list[Delta]) -> None:
        for cb in self._callbacks:
            cb(deltas)

    def set(self, path: str, value: object) -> None:
        self.set_calls.append((path, value))


def _make_catalog(tmp_path: Path) -> Path:
    class_dir = tmp_path / "catalog" / "only_class"
    class_dir.mkdir(parents=True)
    sprite = np.zeros((16, 16, 4), dtype=np.uint8)
    sprite[:, :, :3] = 128
    sprite[:, :, 3] = 255
    imwrite_unicode(class_dir / "sprite.png", cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))
    return tmp_path / "catalog"


def _base_cfg(catalog_dir: Path, preset_path: Path) -> dict:
    return {
        "resolution_width": 64,
        "resolution_height": 64,
        "px_per_mm": 1.0,
        "belt_y_px": 32,
        "spawn_spacing_mm": [5.0, 5.0],
        "scene_length_mm": 1_000_000.0,
        "preset_path": str(preset_path),
        "seed": 0,
    }


def test_yaml_preset_path_builds_engine_and_renders(tmp_path: Path) -> None:
    """H1: `preset_path` на `.yaml`-файл -> `from_yaml()`, движок собран и реально
    рендерит кадры (не падает как «каталог классов» на попытке открыть файл как папку)."""
    catalog_dir = _make_catalog(tmp_path)
    preset_path = tmp_path / "preset.yaml"
    ScenePreset(catalog_dir=str(catalog_dir), defect_probability=0.0, angle_range_deg=(0.0, 0.0)).to_yaml(preset_path)

    state_proxy = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = state_proxy
    ctx.config = _base_cfg(catalog_dir, preset_path)

    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    assert plugin._compositor is not None, f"движок не собрался из .yaml: {ctx.log_error.call_args_list}"

    plugin.start(ctx)
    for i, enc in enumerate((0.0, 10.0, 20.0)):
        state_proxy.emit(
            [Delta(path="sim.belt.encoder", old_value=MISSING, new_value={"value": enc, "t": float(i)}, source="robot")]
        )
        items = plugin.produce()
        assert items[0]["frame"].shape == (64, 64, 3)
    assert len(plugin._spawner.active_objects()) > 0, "объекты должны были заспавниться из .yaml-пресета"


def test_yaml_preset_without_cfg_key_keeps_file_defect_probability(tmp_path: Path) -> None:
    """H2: cfg БЕЗ ключа `defect_probability` -> значение файла (1.0) сохраняется ->
    сделанный объект детерминированно получает активный дефект (без розыгрыша)."""
    catalog_dir = _make_catalog(tmp_path)
    preset_path = tmp_path / "preset.yaml"
    ScenePreset(catalog_dir=str(catalog_dir), defect_probability=1.0, angle_range_deg=(0.0, 0.0)).to_yaml(preset_path)

    ctx = MagicMock()
    ctx.state_proxy = _FakeStateProxy()
    ctx.config = _base_cfg(catalog_dir, preset_path)  # ключа "defect_probability" нет

    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    assert plugin._compositor is not None, f"движок не собрался: {ctx.log_error.call_args_list}"

    obj = plugin._spawner._factory.make("o1", 0.0, np.random.default_rng(0))
    assert obj.passport.defect == "damaged", (
        "defect_probability=1.0 из файла пресета должен был сохраниться без cfg-переопределения"
    )


def test_yaml_preset_cfg_defect_probability_overrides_file_value(tmp_path: Path) -> None:
    """H3: cfg С ключом `defect_probability=0.0` переопределяет файловое значение (1.0) ->
    сделанный объект детерминированно НЕ получает активный дефект."""
    catalog_dir = _make_catalog(tmp_path)
    preset_path = tmp_path / "preset.yaml"
    ScenePreset(catalog_dir=str(catalog_dir), defect_probability=1.0, angle_range_deg=(0.0, 0.0)).to_yaml(preset_path)

    ctx = MagicMock()
    ctx.state_proxy = _FakeStateProxy()
    ctx.config = {**_base_cfg(catalog_dir, preset_path), "defect_probability": 0.0}

    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    assert plugin._compositor is not None, f"движок не собрался: {ctx.log_error.call_args_list}"

    obj = plugin._spawner._factory.make("o1", 0.0, np.random.default_rng(0))
    assert obj.passport.defect is None, "cfg defect_probability=0.0 должен был переопределить файловое 1.0"
