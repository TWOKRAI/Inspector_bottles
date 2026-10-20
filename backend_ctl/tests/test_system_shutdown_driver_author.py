# -*- coding: utf-8 -*-
"""Task 0.2 (gui-graceful-close): авторский тест опасности к решению лида по шагу 4.

PM отверг ``system.shutdown`` (ошибка аргументов) — стоп не начат, сокет не закроется. Драйвер обязан
вернуться сразу, а не ждать ``wait_timeout``. Транспорт фейковый: ``system_command`` подменён на
экземпляре, ``connection_lost`` никогда не становится ``True``.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from backend_ctl.driver import BackendDriver


class _NeverLostDriver(BackendDriver):
    """Сокет не закрывается никогда: ожидание, если оно есть, длится весь ``wait_timeout``."""

    @property
    def connection_lost(self) -> bool:  # type: ignore[override]
        return False


def test_rejected_command_returns_without_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    drv = _NeverLostDriver()

    def fake_system_command(command: dict, *, timeout: float | None = None) -> dict:
        return {"error": "deadline_s: 0.1..5.0"}

    monkeypatch.setattr(drv, "system_command", fake_system_command)

    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = drv.system_shutdown(mode="force", deadline_s=9.0, wait=True, wait_timeout=2.0)
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(5.0)
    assert not thread.is_alive(), "system_shutdown завис дольше 5.0 с"
    if "error" in box:
        raise box["error"]
    res = box["value"]

    assert res["accepted"] is False, res
    assert res["pm_gone"] is False, res
    assert res["outcomes"] is None, res
    assert res["elapsed_s"] < 0.5, f"отвергнутая команда, а драйвер ждал {res['elapsed_s']} с"
