# -*- coding: utf-8 -*-
"""Общие фикстуры тестов ``camera_service``."""

from __future__ import annotations

import os

import pytest

_FFMPEG_ENV = "OPENCV_FFMPEG_CAPTURE_OPTIONS"


@pytest.fixture(autouse=True)
def _restore_ffmpeg_env():
    """``StreamSourceBackend.start()`` пишет переменную в окружение ПРОЦЕССА — это его
    боевое поведение. В тестах без отката она переживает тест, и все следующие в сессии
    (и порождённые ими процессы) видят её. Замерено 2026-09-21: любой тест, дёргающий
    ``start()``, оставлял значение после себя."""
    before = os.environ.get(_FFMPEG_ENV)
    yield
    if before is None:
        os.environ.pop(_FFMPEG_ENV, None)
    else:
        os.environ[_FFMPEG_ENV] = before
