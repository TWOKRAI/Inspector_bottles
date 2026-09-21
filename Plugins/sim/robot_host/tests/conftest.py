"""Фикстуры тестов ``Plugins/sim/robot_host``.

Реестр объявлений наблюдаемости процессный: ``SimRobotHostPlugin.configure`` зовёт
``ctx.declare_metric("encoder" | "belt_mm_s" | "writes_seen")`` (Task 2.2), и без
возврата эти имена доставались соседним наборам в том же прогоне. Замер 2026-09-22:
``pytest Plugins/sim/robot_host multiprocess_framework/.../test_telemetry_default_enabled_hazards.py``
давал 1 failed — каталог гейта расширился на ``belt_mm_s``; по отдельности оба зелёные.
Фикстура — близнец ``process_module/tests/conftest.py::declarations_snapshot``.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.observability_declarations import restore, snapshot
from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
    ensure_framework_producers,
)


@pytest.fixture(autouse=True)
def declarations_snapshot():
    """Снимок реестра объявлений до теста, возврат к нему после."""
    ensure_framework_producers()
    state = snapshot()
    yield
    restore(state)
