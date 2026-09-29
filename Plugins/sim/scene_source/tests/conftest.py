# -*- coding: utf-8 -*-
"""Общие фикстуры тестов scene_source."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# Plugins/sim/scene_source/tests/conftest.py -> parents[4] == корень репо.
_REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def repo_texture_dir() -> Iterator[Path]:
    """Временный каталог ВНУТРИ репозитория (``data/`` в .gitignore) для текстур.

    Относительный путь «от корня репо» строится через ``os.path.relpath``, а на Windows
    он не существует между разными дисками (``ValueError: path is on mount 'C:', start
    on mount 'D:'``): ``tmp_path`` лежит в %TEMP% на C:, репозиторий — на D:. Кросс-дисковый
    относительный путь в конфиге невозможен и у пользователя (там пишут абсолютный), поэтому
    тесты «относительного пути» кладут файл на один диск с корнем репо.
    """
    base = _REPO_ROOT / "data"
    base.mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="pytest_texture_", dir=base))
    yield directory
    shutil.rmtree(directory)
