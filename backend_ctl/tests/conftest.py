# -*- coding: utf-8 -*-
"""Фикстуры backend_ctl-тестов: headless-бэкенд на BackendHarness (Ф1 Task 1.3).

``headless_backend`` поднимает реальную систему прототипа БЕЗ gui (honest headless),
отдаёт подключённый ``BackendDriver`` и гарантированно гасит систему в teardown
(watchdog + kill поддерева) — висящих процессов после теста не остаётся.

Session-scope: старт/стоп системы дорогой (~секунды), поэтому один бэкенд на все
harness-тесты модуля. Тесты только читают состояние — общий инстанс безопасен.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from backend_ctl.harness import BackendHarness


def wire_line(msg: Dict[str, Any]) -> bytes:
    """Собрать проводную строку push'а так же, как её видит reader-поток.

    Общий хелпер unit-тестов событийного контура (инжекция через dispatch_raw) —
    одна точка правды о wire-кодировке вместо копий по тест-файлам.
    """
    return json.dumps(msg, ensure_ascii=False).encode("utf-8")


@pytest.fixture(scope="session")
def headless_backend():
    """Подключённый BackendDriver к headless-системе прототипа (без gui).

    with_base=True — подмешиваем фундамент (там объявлен gui), чтобы strip_gui реально
    его исключил: доказываем честный headless на топологии, которая иначе спавнит Qt.
    """
    harness = BackendHarness(with_base=True)
    drv = harness.start()
    try:
        yield drv
    finally:
        harness.stop()
