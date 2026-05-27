# -*- coding: utf-8 -*-
"""
Базовые фикстуры для тестов domain-слоя.

fixtures_dir — путь к корню YAML-файлов проекта (корень multiprocess_prototype).
make_test_app_services() — builder фикстура будет добавлена в Task B.6.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    """Путь к корню multiprocess_prototype (содержит recipes/, backend/topology/)."""
    return Path(__file__).resolve().parent.parent.parent
