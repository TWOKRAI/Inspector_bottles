# -*- coding: utf-8 -*-
"""Хуки и помощники тестов ядра camera_device (Task 1.5).

`skip_without_hardware(items)` пропускает тесты с маркером `hardware`, пока не задан `CAMERA_HARDWARE=1`.
Вендорские conftest вызывают её из своего `pytest_collection_modifyitems`:

    from Services.camera_device.tests.conftest import skip_without_hardware

    def pytest_collection_modifyitems(config, items):
        skip_without_hardware(items)

Маркер `hardware` регистрируется строкой в `pyproject.toml` (`markers`), здесь он НЕ регистрируется:
иначе проверка `-W error::pytest.PytestUnknownMarkWarning` скрыла бы отсутствие строки в корне.
"""

from __future__ import annotations

import os

import pytest

HARDWARE_ENV = "CAMERA_HARDWARE"
HARDWARE_SKIP_REASON = "CAMERA_HARDWARE=1 not set"


def skip_without_hardware(items) -> None:
    """Пометить `skip` каждый тест с маркером `hardware`, если `CAMERA_HARDWARE` не равен `"1"`."""
    if os.environ.get(HARDWARE_ENV) == "1":
        return
    skip = pytest.mark.skip(reason=HARDWARE_SKIP_REASON)
    for item in items:
        if item.get_closest_marker("hardware") is not None:
            item.add_marker(skip)


def pytest_collection_modifyitems(config, items):
    skip_without_hardware(items)
