# -*- coding: utf-8 -*-
"""Live-тест Ф3.2 self-reported ready (acceptance): switch закрывается по ready.

harness_smoke: boot headless-бэкенда (base.yaml → devices) уже неявно проверяет
boot-барьер — ``BackendHarness.start`` ждёт ``system_ready_event``, который PM
теперь выставляет ТОЛЬКО после self-reported ready детей (либо boot-таймаут).
Затем ``topology.apply`` (full-replace pipeline) — в ответе поле ``ready`` должно
быть заполнено и все процессы True: барьер закрылся по факту готовности
(per-process mp.Event), а не по одному лишь settle-window.

Собственный порт ≥8781 (изоляция «двух бэкендов»; 8765-8779 заняты соседними
live-модулями). См. project_concurrent_backends_trap.
"""

from __future__ import annotations

import pytest
from backend_ctl.protocol import unwrap

from backend_ctl.harness import BackendHarness

_PORT = 8781  # уникальный порт этого модуля


@pytest.fixture(scope="module")
def ready_backend():
    """Свой headless-бэкенд на уникальном порту (изоляция от общих фикстур)."""
    harness = BackendHarness(with_base=True, port=_PORT)
    drv = harness.start()
    try:
        yield drv
    finally:
        harness.stop()


@pytest.mark.harness_smoke
def test_switch_reports_all_ready(ready_backend) -> None:
    """topology.apply → response['ready'] заполнен и все процессы True (acceptance)."""
    drv = ready_backend

    from multiprocess_prototype.backend.launch import load_topology_dict
    from multiprocess_prototype.main import DEFAULT_BLUEPRINT

    bp = load_topology_dict(DEFAULT_BLUEPRINT)
    applied = unwrap(
        drv.send_command("ProcessManager", "topology.apply", {"topology_dict": bp}, timeout=30.0), leaf=True
    )

    assert applied.get("success") is True, f"topology.apply не success: {applied}"
    ready = applied.get("ready")
    assert isinstance(ready, dict) and ready, f"ready-карта пуста/отсутствует: {ready}"
    not_ready = sorted(n for n, ok in ready.items() if not ok)
    assert not not_ready, f"процессы не сообщили ready после switch: {not_ready} (карта: {ready})"
