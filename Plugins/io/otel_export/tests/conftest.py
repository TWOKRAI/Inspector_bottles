# -*- coding: utf-8 -*-
"""Тот же предохранитель, что у набора сервиса: никакой настоящей сети в тестах.

Фикстура не копируется, а ИМПОРТИРУЕТСЯ: две копии одного предохранителя
разъезжаются молча, и узнать об этом можно только по тому, что одна половина
набора однажды ушла в сеть. Разбор, замер и причина — в докстринге
`Services/otel_export/tests/conftest.py`.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.observability_declarations import restore, snapshot
from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
    ensure_framework_producers,
)
from Services.otel_export.tests.conftest import forbid_real_sdk_in_process  # noqa: F401


@pytest.fixture(autouse=True)
def declarations_snapshot():
    """Снимок реестра объявлений до теста, возврат к нему после.

    Плагин зовёт `ctx.declare_metric(...)` в configure(): без возврата объявления
    счётчиков (`exported`, `export_failed`, ...) остаются в процессном реестре и
    сторож каталога метрик на закрытии сессии краснеет в teardown чужого теста.
    """
    ensure_framework_producers()
    state = snapshot()
    yield
    restore(state)
