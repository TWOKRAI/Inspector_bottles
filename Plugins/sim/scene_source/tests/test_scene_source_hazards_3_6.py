# -*- coding: utf-8 -*-
"""Hazard-тесты автора для Task 3.6 (плагин `Plugins.sim.scene_source`) — что может
сломаться конкретно в резолвинге пути и обработке ошибок `background_texture`, а не в
общей приёмке. Тестерский `test_scene_source_task_3_6.py` гоняет свой относительный-путь
тест с CWD == корень репозитория, поэтому не может отличить «резолвим от корня» от
«резолвим от CWD, который просто совпал с корнем» (H8). А для «файл не читается» тестер
проверяет только отсутствующий файл (`OSError` из `np.fromfile`) — H9 добавляет битые
байты (`ValueError` из `imread_unicode`), другой класс исключения на том же контракте.
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

from multiprocess_framework.modules.state_store_module.core.delta import Delta
from Plugins.sim.scene_source.plugin import SceneSourcePlugin
from Services.dataset_gen.core.catalog import imwrite_unicode

pytestmark = pytest.mark.timeout(30)

# Plugins/sim/scene_source/tests/test_scene_source_hazards_3_6.py -> parents[4] == корень репо.
_REPO_ROOT = Path(__file__).resolve().parents[4]


class _FakeStateProxy:
    """Минимальная замена ``StateProxy`` — копия паттерна тестерского файла Task 3.6."""

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


def test_h8_relative_background_texture_resolved_from_repo_root_not_cwd(tmp_path, monkeypatch):
    """H8: относительный `background_texture` резолвится от КОРНЯ РЕПОЗИТОРИЯ, не от
    CWD процесса. CWD намеренно меняется на `tmp_path` ДО `configure()` — наивная
    реализация (`Path(rel).resolve()` без похода к `_REPO_ROOT`) читала бы файл из
    `tmp_path/<rel>` (которого там нет), получила бы `log_error` и откатилась бы на
    сплошной фон, хотя по контракту фон обязан быть текстурой. Тестерский файл этого
    не ловит: там CWD уже совпадает с корнем репозитория."""
    catalog_dir = _make_catalog(tmp_path)
    texture_bgr = np.full((48, 48, 3), fill_value=(77, 88, 99), dtype=np.uint8)
    texture_path = tmp_path / "h8_texture.png"
    imwrite_unicode(texture_path, texture_bgr)
    relative_path = os.path.relpath(texture_path, _REPO_ROOT)

    monkeypatch.chdir(tmp_path)

    ctx = MagicMock()
    ctx.state_proxy = _FakeStateProxy()
    ctx.config = {
        "resolution_width": 48,
        "resolution_height": 48,
        "px_per_mm": 1.0,
        "belt_y_px": 24,
        "preset_path": str(catalog_dir),
        "seed": 0,
        "background_texture": relative_path,
    }

    plugin = SceneSourcePlugin()
    plugin.configure(ctx)

    assert ctx.log_error.call_count == 0, "путь от корня репо должен разрешиться и прочитаться без ошибок"
    plugin.start(ctx)
    items = plugin.produce()
    frame = items[0]["frame"]
    assert tuple(int(v) for v in frame[10, 10]) == (77, 88, 99)


def test_h9_corrupt_texture_file_same_single_log_error_as_missing_file(tmp_path):
    """H9: файл существует, но это не изображение (случайные байты) — контракт
    трактует «нет файла / битый» одинаково: ровно один `log_error`, движок остаётся
    живым на сплошном фоне. `imread_unicode` в этом случае бросает `ValueError` (не
    `OSError`, как для отсутствующего файла) — если ловушка плагина завязана
    конкретно на `OSError`/`FileNotFoundError` (соблазн из формулировки «файл не
    найден»), этот тест её поймает."""
    catalog_dir = _make_catalog(tmp_path)
    corrupt_path = tmp_path / "corrupt.png"
    corrupt_path.write_bytes(b"not a real png \x00\x01\x02")

    ctx = MagicMock()
    ctx.state_proxy = _FakeStateProxy()
    ctx.config = {
        "resolution_width": 32,
        "resolution_height": 32,
        "px_per_mm": 1.0,
        "belt_y_px": 16,
        "preset_path": str(catalog_dir),
        "seed": 0,
        "background_texture": str(corrupt_path),
    }

    plugin = SceneSourcePlugin()
    plugin.configure(ctx)

    assert plugin._compositor is not None
    assert ctx.log_error.call_count == 1

    plugin.start(ctx)
    items = plugin.produce()
    assert items[0]["frame"].shape == (32, 32, 3)
    assert ctx.log_error.call_count == 1
