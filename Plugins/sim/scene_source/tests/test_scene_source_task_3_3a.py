# -*- coding: utf-8 -*-
"""Hazard-тест автора — Task 3.3a, ревью, находка 4: «призрак на spawn_encoder=0».

До первой дельты от `robot_host` мир (`self._world`) пуст, и `_read_world_encoder()`
возвращает конфигурационный `spawn_encoder` (обычно `0`). Без гейта `_world_ready`
`produce()` тикал бы спавнер уже на этом фиктивном `0`, порождая объект с
`spawn_encoder=0`, который либо никогда не деспавнится (если реальный энкодер стартует
далеко от нуля), либо путает счёт `spacing_mm` (Task 3.3a). Фикс — не тикать спавнер, пока
`_world_ready is False`; свой файл, не расширяет `test_scene_source_hazards.py`
(тесты лида) и не трогает `apps/line_sim/tests/**` — по инструкции ревью.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from Plugins.sim.scene_source.plugin import SceneSourcePlugin
from Services.dataset_gen.core.catalog import imwrite_unicode

pytestmark = pytest.mark.timeout(30)


class _FakeStateProxy:
    """Минимальная замена ``StateProxy`` — тот же паттерн, что в
    ``test_scene_source_hazards.py``/``test_scene_source_acceptance.py`` (не импортируется
    оттуда — своя копия, файл самодостаточен)."""

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


def _make_plugin_with_spacing_engine(tmp_path: Path) -> tuple[SceneSourcePlugin, "_FakeStateProxy"]:
    catalog_dir = _make_catalog(tmp_path)
    state_proxy = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = state_proxy
    ctx.config = {
        "resolution_width": 64,
        "resolution_height": 64,
        "px_per_mm": 1.0,
        "belt_y_px": 32,
        "spawn_spacing_mm": [60.0, 60.0],
        "scene_length_mm": 1_000_000.0,
        "preset_path": str(catalog_dir),
        "seed": 0,
    }
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    assert plugin._spawner is not None, "фикстура должна собрать реальный движок, не fallback"
    return plugin, state_proxy


def test_no_ghost_object_before_first_world_delta(tmp_path):
    """Пока мира ещё не было (ни одной дельты) — спавнер НЕ тикает, `sim.objects` пуст;
    несколько подряд `produce()` (не один) не создают призрачный объект на
    `spawn_encoder=0`."""
    plugin, state_proxy = _make_plugin_with_spacing_engine(tmp_path)

    for _ in range(10):
        items = plugin.produce()
        assert isinstance(items, list) and items
        assert items[0]["frame"].shape == (64, 64, 3)

    assert plugin._spawner.active_objects() == [], "мира ещё нет -- спавнить нечего"
    assert state_proxy.set_calls == [], "sim.objects не должен получить фиктивную запись"


def test_first_spawn_uses_real_world_encoder_not_config_default(tmp_path):
    """Как только приходит ПЕРВАЯ дельта с реальным энкодером — спавн происходит на
    РЕАЛЬНОМ значении (`spawn_encoder`), не на конфигурационном дефолте `0`."""
    plugin, state_proxy = _make_plugin_with_spacing_engine(tmp_path)

    for _ in range(5):
        plugin.produce()  # мира ещё нет -- ничего не спавнится (см. тест выше)
    assert plugin._spawner.active_objects() == []

    real_encoder = 500_000  # заведомо далеко от конфигурационного spawn_encoder=0
    state_proxy.emit(
        [Delta(path="sim.belt.encoder", old_value=MISSING, new_value={"value": real_encoder, "t": 0.0}, source="robot")]
    )

    plugin.produce()
    active = plugin._spawner.active_objects()
    assert len(active) == 1
    assert active[0].passport.spawn_encoder == float(real_encoder)
