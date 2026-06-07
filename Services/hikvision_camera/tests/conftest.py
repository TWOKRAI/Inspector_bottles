# -*- coding: utf-8 -*-
"""Фикстуры для тестов hikvision_camera."""

from __future__ import annotations

import pytest
import numpy as np
from unittest.mock import patch


@pytest.fixture
def mock_sdk_available():
    """Мокаем SDK как доступный."""
    with patch("Services.hikvision_camera.sdk.bindings.SDK_AVAILABLE", True):
        yield


@pytest.fixture
def mock_sdk_unavailable():
    """Мокаем SDK как недоступный."""
    with patch("Services.hikvision_camera.sdk.bindings.SDK_AVAILABLE", False):
        yield


@pytest.fixture
def sample_bayer_frame():
    """Тестовый Bayer RG8 кадр (2D, одноканальный)."""
    return np.random.randint(0, 255, (480, 640), dtype=np.uint8)


@pytest.fixture
def sample_bgr_frame():
    """Тестовый BGR кадр (3 канала)."""
    return np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)


@pytest.fixture
def sample_rgba_frame():
    """Тестовый RGBA кадр (4 канала)."""
    return np.random.randint(0, 255, (480, 640, 4), dtype=np.uint8)
