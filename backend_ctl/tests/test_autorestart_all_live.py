# -*- coding: utf-8 -*-
"""Live-тест Ф4-добор: авто-рестарт ВСЕХ процессов по умолчанию + громкие supervisor-события.

Требование владельца (2026-07-08): все процессы конвейера автовосстанавливаемые (не
только source/hub из G1) + КАЖДОЕ падение/рестарт/восстановление громко видно (иначе
баг прячется за авто-рестартом). Механизм — глобальный дефолт RestartPolicy(enabled=True)
в PM (protected gui/PM монитор всё равно skip; per-process рецепт перекрывает; окно
give-up Ф3.6 ловит crash-loop); наблюдаемость — supervisor-события в
`processes.<name>.supervisor.*` (StateStore → GUI/подписчики).

**Почему live (урок Ф3.7).** Юнит доказывает эмиссию событий, но НЕ то, что процесс БЕЗ
per-process policy реально воскресает по глобальному дефолту. Здесь убиваем
`preprocessor` (non-source, non-protected, БЕЗ своего restart_policy в рецепте) —
до Ф4-добора он остался бы мёртвым (глобальная политика была выключена). SIGKILL (crash),
а не graceful stop.

GREEN (default-on): новый pid + supervisor-событие `recovered`.
RED (`FW_AUTORESTART=0`): тот же kill — процесс НЕ воскресает (глобальный дефолт выкл).

Порт 8794/8795 (изоляция от общих фикстур: ловушка «двух бэкендов»).
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager

import pytest

from backend_ctl.harness import BackendHarness
from backend_ctl.tests.conftest import bookmark_cursor as _bookmark
from backend_ctl.tests.conftest import page_events as _page

_PROC = "preprocessor"  # non-source, non-protected, БЕЗ per-process restart_policy
_PORT_GREEN = 8794
_PORT_RED = 8795


def _status_pid(drv, name: str):
    try:
        res = drv.introspect_status(name, timeout=5.0)
    except Exception:  # noqa: BLE001 — процесс может пересоздаваться
        return None, None
    node = res
    for _ in range(4):
        if isinstance(node, dict) and "pid" in node:
            return node.get("pid"), node.get("status")
        node = node.get("result") if isinstance(node, dict) else None
    return None, None


def _result(res: dict) -> dict:
    if isinstance(res, dict) and isinstance(res.get("result"), dict):
        return res["result"]
    return res if isinstance(res, dict) else {}


@contextmanager
def _backend(port: int, *, autorestart: str | None):
    prev = os.environ.get("FW_AUTORESTART")
    if autorestart is None:
        os.environ.pop("FW_AUTORESTART", None)
    else:
        os.environ["FW_AUTORESTART"] = autorestart
    harness = BackendHarness(with_base=True, port=port)
    try:
        yield harness, harness.start()
    finally:
        harness.stop()
        if prev is None:
            os.environ.pop("FW_AUTORESTART", None)
        else:
            os.environ["FW_AUTORESTART"] = prev


def _collect_supervisor_events(drv, name: str, deadline: float, cursor=None) -> list[str]:
    """Собрать значения processes.<name>.supervisor.event из state.changed-дельт."""
    path = f"processes.{name}.supervisor.event"
    seen: list[str] = []
    while time.time() < deadline:
        evts, cursor = _page(drv, cursor)
        for e in evts:
            if e.get("command") != "state.changed":
                continue
            for d in (e.get("data") or {}).get("deltas", []) or []:
                if d.get("path") == path and d.get("new_value") not in (None,):
                    seen.append(d.get("new_value"))
        if "recovered" in seen:
            break
        if not evts:
            time.sleep(0.2)
    return seen


@pytest.mark.harness_smoke
def test_default_on_restarts_unpoliced_process_green() -> None:
    """GREEN: kill non-policed процесса → авто-рестарт по глобальному дефолту +
    supervisor-события (crashed/restarting → recovered), новый pid."""
    with _backend(_PORT_GREEN, autorestart=None) as (harness, drv):
        sub = _result(drv.state_subscribe(f"processes.{_PROC}.**", timeout=8.0))
        assert sub.get("status") == "ok", f"state.subscribe не ok: {sub}"
        cursor = _bookmark(drv)  # осушить накопленное

        pid_1, _ = _status_pid(drv, _PROC)
        assert isinstance(pid_1, int) and pid_1 > 0, f"baseline pid '{_PROC}' не получен: {pid_1}"

        killed = harness.kill_child(_PROC)
        assert killed == pid_1

        events = _collect_supervisor_events(drv, _PROC, time.time() + 30.0, cursor)
        assert "recovered" in events, (
            f"нет supervisor-события 'recovered' для '{_PROC}' — авто-рестарт по дефолту "
            f"не сработал или событие не опубликовано (события: {events})"
        )
        # «упал» тоже должно быть видно (crashed или restarting — обе категории «упал/рестарт»)
        assert any(e in ("crashed", "restarting") for e in events), f"нет события падения/рестарта в потоке: {events}"

        # Прямое доказательство воскрешения: новый pid.
        pid_2, status_2 = None, None
        deadline = time.time() + 15.0
        while time.time() < deadline:
            pid_2, status_2 = _status_pid(drv, _PROC)
            if isinstance(pid_2, int) and pid_2 > 0 and pid_2 != pid_1:
                break
            time.sleep(1.0)
        assert isinstance(pid_2, int) and pid_2 != pid_1, (
            f"'{_PROC}' не воскрес с новым pid (default-on не сработал): pid1={pid_1} pid2={pid_2}"
        )


@pytest.mark.harness_smoke
def test_autorestart_off_leaves_process_dead_red() -> None:
    """RED (FW_AUTORESTART=0): тот же kill — процесс НЕ воскресает (дефолт выкл)."""
    with _backend(_PORT_RED, autorestart="0") as (harness, drv):
        pid_1, _ = _status_pid(drv, _PROC)
        assert isinstance(pid_1, int) and pid_1 > 0, f"baseline pid '{_PROC}' не получен: {pid_1}"

        harness.kill_child(_PROC)

        # Даём столько же, сколько GREEN на рестарт — и убеждаемся, что НЕ воскрес.
        time.sleep(12.0)
        pid_2, status_2 = _status_pid(drv, _PROC)
        # Либо процесс мёртв (pid None / тот же старый недоступен), либо статус не running
        assert not (isinstance(pid_2, int) and pid_2 > 0 and pid_2 != pid_1), (
            f"при FW_AUTORESTART=0 '{_PROC}' воскрес (pid {pid_1}→{pid_2}) — дефолт не выключился"
        )
