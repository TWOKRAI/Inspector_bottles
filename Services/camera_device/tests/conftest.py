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

from multiprocess_framework.modules.observability_declarations import restore, snapshot
from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
    ensure_framework_producers,
)

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


@pytest.fixture(autouse=True)
def declarations_snapshot():
    """Снимок реестра объявлений до теста, возврат к нему после.

    Реестр объявлений наблюдаемости процессный: плагин камеры зовёт `ctx.declare_metric` для `fps`, `frames`,
    `errors`, `dropped`, `pending`, `param_errors_count` (`test_plugin_observability.py`), и без возврата эти
    имена доставались сторожу каталога метрик фреймворка (`modules/tests/conftest.py::framework_metric_catalogue_guard`)
    в том же прогоне: `pytest Services/camera_device/tests/test_plugin_observability.py
    multiprocess_framework/modules/tests/test_one_connector_per_point.py` на чистом `main` давал 1 error на teardown
    (замер 2026-11-19); `Services` входит в `testpaths`, так что падал и общий `make test`.
    Близнец `Plugins/sim/robot_host/tests/conftest.py::declarations_snapshot`.
    """
    ensure_framework_producers()
    state = snapshot()
    yield
    restore(state)
