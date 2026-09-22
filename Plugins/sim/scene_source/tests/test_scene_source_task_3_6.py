# -*- coding: utf-8 -*-
"""Независимые acceptance-тесты Task 3.6 (плагин `Plugins.sim.scene_source`) — написаны
ДО реализации по контракту из `plans/line-sim/phase-3-object-engine.md`, раздел
"### Task 3.6 (новая, 2026-09-23)", блок "**Уточнено лидом 2026-09-23 перед тестером**"
(источник истины, отменяет расходящиеся более ранние строки того же раздела).

Рабочее дерево — git worktree на коммите 27b1800f ("docs(plans): line-sim 3.6 — контракт
фона-текстуры до тестера"), ДО имплементации: ключ конфига `background_texture` в
`plugin.py` этого дерева не существует по конструкции.

ЗАПРЕЩЁННЫЕ ПУТИ: diff/реализация Task 3.6 (её физически нет в этом коммите). Прочитано
как ГОТОВАЯ ЗАВИСИМОСТЬ (не то, что тестируется здесь): `Plugins/sim/scene_source/plugin.py`
(Task 3.4 как есть, ДО `background_texture`), `Services/dataset_gen/core/catalog.py`,
`Plugins/sim/scene_source/tests/test_scene_source_task_3_3a.py` (паттерн `_FakeStateProxy`
и `MagicMock`-ctx скопирован оттуда буквально — файл самодостаточен, не импортирует его).

СИГНАТУРЫ, ПРЕДПОЛАГАЕМЫЕ (источник — блок "Уточнено лидом"), сверить при имплементации:
  - `configure()` читает `ctx.config["background_texture"]` (путь, относительный — от
    корня репозитория, ТЕМ ЖЕ `_resolve_preset_path`, что и `preset_path`); читает через
    `imread_unicode(path, cv2.IMREAD_COLOR)`, BGR -> RGB -> `background_tile` компоновщика.
  - Файл не читается (нет файла/битый) -> ровно один `ctx.log_error` в `configure()`,
    движок продолжает работать (объекты рисуются) на сплошном фоне; из `produce()` — ни
    одного `log_error` по этой причине.
  - `produce()[0]["frame"]` — BGR; текстура с BGR-пикселем `(200, 10, 30)` должна дать
    ровно `(200, 10, 30)` на строке ленты вне объектов.
"""

from __future__ import annotations

import os
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

# Plugins/sim/scene_source/tests/test_scene_source_task_3_6.py -> parents[4] == корень репо
# (тот же приём, что `_REPO_ROOT` в `plugin.py`, но посчитан независимо тестом, не импортом
# приватной константы из кода под тестом).
_REPO_ROOT = Path(__file__).resolve().parents[4]


class _FakeStateProxy:
    """Минимальная замена ``StateProxy`` — копия паттерна `test_scene_source_task_3_3a.py`."""

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


def test_unreadable_texture_logs_once_and_falls_back(tmp_path):
    """Критерий 4: `background_texture` указывает на несуществующий файл -> ровно 1
    `log_error` в `configure()`, 0 из `produce()`, движок продолжает спавнить объекты
    (НЕ ветка «движок недоступен» — это out of scope, отдельная ветка `_background_only_frame`)."""
    catalog_dir = _make_catalog(tmp_path)
    state_proxy = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = state_proxy
    ctx.config = {
        "resolution_width": 64,
        "resolution_height": 64,
        "px_per_mm": 1.0,
        "belt_y_px": 32,
        "spawn_spacing_mm": [5.0, 5.0],
        "scene_length_mm": 1_000_000.0,
        "preset_path": str(catalog_dir),
        "seed": 0,
        "background_texture": str(tmp_path / "missing_texture.png"),  # файла нет на диске
    }

    plugin = SceneSourcePlugin()
    plugin.configure(ctx)

    assert plugin._compositor is not None, "движок должен собраться -- НЕ ветка fallback на фон"
    assert ctx.log_error.call_count == 1, f"ожидался ровно 1 log_error, вызовов: {ctx.log_error.call_count}"

    plugin.start(ctx)
    for i, enc in enumerate((0.0, 50.0, 100.0, 150.0, 200.0)):
        state_proxy.emit(
            [
                Delta(
                    path="sim.belt.encoder",
                    old_value=MISSING,
                    new_value={"value": enc, "t": float(i)},
                    source="robot",
                )
            ]
        )
        items = plugin.produce()
        assert items[0]["frame"].shape == (64, 64, 3)

    assert ctx.log_error.call_count == 1, "produce() не должен добавлять log_error по причине текстуры"
    assert len(plugin._spawner.active_objects()) > 0, "объекты должны продолжать спавниться на сплошном фоне"


def test_texture_channel_order_in_frame(tmp_path):
    """Добавленный критерий: BGR-пиксель `(200, 10, 30)` в файле-текстуре -> ровно
    `(200, 10, 30)` в `produce()[0]["frame"]` (BGR) на строке ленты. Путь передаётся
    ОТНОСИТЕЛЬНО КОРНЯ РЕПОЗИТОРИЯ (`os.path.relpath`), чтобы покрыть и root-relative
    резолвинг тем же приёмом, что `preset_path`, а не только абсолютный путь."""
    catalog_dir = _make_catalog(tmp_path)

    texture_bgr = np.empty((64, 64, 3), dtype=np.uint8)
    texture_bgr[:, :, 0], texture_bgr[:, :, 1], texture_bgr[:, :, 2] = 200, 10, 30
    texture_path = tmp_path / "texture.png"
    imwrite_unicode(texture_path, texture_bgr)
    relative_texture_path = os.path.relpath(texture_path, _REPO_ROOT)

    ctx = MagicMock()
    ctx.state_proxy = _FakeStateProxy()
    ctx.config = {
        "resolution_width": 64,
        "resolution_height": 64,
        "px_per_mm": 1.0,
        "belt_y_px": 32,  # top = round(32 - 64/2) = 0 -> полоса тайла = вся высота кадра [0,64)
        "preset_path": str(catalog_dir),
        "seed": 0,
        "background_texture": relative_texture_path,
    }

    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    # мир ни разу не эмитился -> _world_ready остаётся False -> спавнер не тикает ->
    # активных объектов нет -> весь кадр это чистый фон (текстура), без риска попасть
    # на спрайт объекта
    items = plugin.produce()
    frame = items[0]["frame"]

    assert frame.shape == (64, 64, 3)
    assert tuple(int(v) for v in frame[10, 10]) == (200, 10, 30)
