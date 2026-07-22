# -*- coding: utf-8 -*-
"""Тесты MCP-слоя flight recorder (D.4, Steps 5-6).

Session-owned диспетчеризация record_* + REPLAY_SERVED-маршрутизация + обучающая
ошибка live-инструментов в replay-режиме + path-confinement (§5.4). Сессия — реальная
DriverSession с fake-factory (detached driver вместо сокета).
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

from backend_ctl.dispatch import RECORD_HANDLERS, REPLAY_SERVED, dispatch_tool, resolve_record_path
from backend_ctl.driver import BackendDriver
from backend_ctl.mcp_driver_session import MODE_LIVE, MODE_REPLAY, DriverSession
from backend_ctl.mcp_tools import TOOL_SAFETY


def _state_push(path: str, value: Any) -> Dict[str, Any]:
    return {"command": "state.changed", "data": {"deltas": [{"path": path, "new_value": value}]}}


@pytest.fixture
def record_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("BACKEND_CTL_RECORD_DIR", str(tmp_path / "records"))
    return tmp_path


@pytest.fixture
def session_and_driver():
    """DriverSession поверх detached driver (fake live-бэкенд)."""
    drv = BackendDriver("127.0.0.1", 8765)
    session = DriverSession(driver_factory=lambda: drv)
    return session, drv


# --------------------------------------------------------------------------- #
#  Safety + path confinement (§5.4)                                           #
# --------------------------------------------------------------------------- #


def test_all_record_tools_are_read_safety() -> None:
    for name in RECORD_HANDLERS:
        assert TOOL_SAFETY[name] == "read", f"{name} должен быть SAFETY_READ"


def test_path_confinement_rejects_separators(record_dir: Path) -> None:
    for bad in ["../escape", "sub/dir", "..", "a\\b", ""]:
        with pytest.raises(ValueError):
            resolve_record_path(bad)


def test_path_confinement_rejects_reserved_device_names(record_dir: Path) -> None:
    """Зарезервированные имена устройств ОС проходят проверку символов, но уводят из каталога.

    ``NUL`` проглотил бы запись (success без файла), ``CON`` писал бы ленту в консоль —
    на stdio-сервере прямо в MCP-транспорт, а ``record_load("CON")`` повесил бы сервер
    на stdin. Проверка обязана быть по ФАКТИЧЕСКИ отрезолвленному пути, а не по символам.
    """
    for bad in ["CON", "NUL", "COM1", "LPT1", "AUX", "PRN", "nul", "con.jsonl"]:
        with pytest.raises(ValueError):
            resolve_record_path(bad)
    # Контроль: обычное имя по-прежнему резолвится внутрь каталога записей.
    good = resolve_record_path("good")
    assert good.endswith("good.jsonl")
    assert os.path.commonpath([str(record_dir / "records"), good]) == str(record_dir / "records")


def test_read_tool_does_not_create_record_dir(record_dir: Path) -> None:
    """Резолв для чтения не создаёт каталог побочным эффектом (пишет — только пишущий)."""
    base = record_dir / "records"
    assert not base.exists()
    resolve_record_path("some_name")
    assert not base.exists(), "read-путь создал каталог записей"
    resolve_record_path("some_name", create_dir=True)
    assert base.exists()


def test_parallel_record_start_second_refuses_no_orphan(record_dir: Path, session_and_driver) -> None:
    """Два одновременных record_start: ровно один стартует, второй честно отказывает.

    Каждый tools/call уходит в свой поток (SDK-сервер отдаёт их в to_thread без
    per-session сериализации), поэтому проверка «запись уже идёт» и присвоение
    _recorder обязаны быть атомарны. Без лока проходят оба: сессия помнит только
    вторую запись, а первая остаётся осиротевшим подписчиком на hot-path EventHub —
    её никто уже не остановит и не отпишет.
    """
    session, drv = session_and_driver
    before = len(drv._hub._subscribers)
    barrier = threading.Barrier(2)
    results: List[Dict[str, Any]] = []
    lock = threading.Lock()

    def racer(name: str) -> None:
        barrier.wait()  # столкнуть вызовы максимально плотно
        res = dispatch_tool(session, "record_start", {"name": name})
        with lock:
            results.append(res)

    threads = [threading.Thread(target=racer, args=(f"race_{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert len(results) == 2
    ok = [r for r in results if r.get("success")]
    refused = [r for r in results if not r.get("success")]
    assert len(ok) == 1, f"стартовали обе записи — гонка не закрыта: {results}"
    assert len(refused) == 1
    assert "уже идёт" in refused[0]["error"]

    # Осиротевших подписчиков нет: ровно одна живая запись держит одну подписку.
    assert len(drv._hub._subscribers) == before + 1
    session.stop_recording()
    # После остановки подписка снята полностью — hub вернулся к исходному состоянию.
    assert len(drv._hub._subscribers) == before


def test_record_start_bad_name_returns_error(record_dir: Path, session_and_driver) -> None:
    session, _drv = session_and_driver
    res = dispatch_tool(session, "record_start", {"name": "../evil"})
    assert res["success"] is False
    assert "имя" in res["error"]


def test_record_start_bad_max_events_learning_error(record_dir: Path, session_and_driver) -> None:
    """Нечисловой max_events → обучающая ошибка, НЕ сырой ValueError сквозь протокол."""
    session, _drv = session_and_driver
    res = dispatch_tool(session, "record_start", {"name": "ok", "max_events": "не-число"})
    assert res["success"] is False
    assert "max_events" in res["error"]


def test_record_load_bad_ring_maxlen_learning_error(record_dir: Path, session_and_driver) -> None:
    session, drv = session_and_driver
    dispatch_tool(session, "record_start", {"name": "r"})
    time.sleep(0.02)
    dispatch_tool(session, "record_stop", {})
    res = dispatch_tool(session, "record_load", {"name": "r", "ring_maxlen": "оуч"})
    assert res["success"] is False
    assert "ring_maxlen" in res["error"]


# --------------------------------------------------------------------------- #
#  Полный цикл record → replay через dispatch_tool                            #
# --------------------------------------------------------------------------- #


def test_record_lifecycle_and_replay_routing(record_dir: Path, session_and_driver) -> None:
    session, drv = session_and_driver

    # 1. Старт записи.
    start = dispatch_tool(session, "record_start", {"name": "sess1"})
    assert start["success"] is True

    # 2. Активность (state-дельты).
    for v in (10.0, 20.0, 30.0):
        drv._emit_event(_state_push("processes.cam.state.fps", v))
    deadline = time.monotonic() + 2.0
    while session._recorder._events_written < 3 and time.monotonic() < deadline:
        time.sleep(0.01)

    # 3. record_status в live — активная запись.
    status = dispatch_tool(session, "record_status", {})
    assert status["recording"] is True

    # 4. Стоп.
    stop = dispatch_tool(session, "record_stop", {})
    assert stop["events_written"] == 3

    # 5. Загрузка реплея — сессия в replay.
    load = dispatch_tool(session, "record_load", {"name": "sess1", "position": "end"})
    assert load["success"] is True
    assert session.mode == MODE_REPLAY

    # 6. REPLAY_SERVED: telemetry_snapshot отвечает ПО ЗАПИСИ.
    snap = dispatch_tool(session, "telemetry_snapshot", {})
    assert snap["metrics"]["processes.cam.state.fps"]["value"] == 30.0

    # 7. REPLAY_SERVED: await_condition (offline-семантика).
    await_res = dispatch_tool(
        session, "await_condition", {"kind": "state_path", "spec": {"path": "processes.cam.state.fps", "value": 30.0}}
    )
    assert await_res["success"] is True
    assert "replay" in await_res

    # 8. system_overview — записанный (recorded=True).
    ov = dispatch_tool(session, "system_overview", {})
    assert ov.get("recorded") is True

    # 9. Возврат в live.
    unload = dispatch_tool(session, "record_unload", {})
    assert unload["success"] is True
    assert session.mode == MODE_LIVE


def test_live_tool_in_replay_gives_learning_error(record_dir: Path, session_and_driver) -> None:
    session, drv = session_and_driver
    dispatch_tool(session, "record_start", {"name": "s"})
    drv._emit_event(_state_push("processes.cam.state.fps", 1.0))
    time.sleep(0.05)
    dispatch_tool(session, "record_stop", {})
    dispatch_tool(session, "record_load", {"name": "s"})

    # write-инструмент над записью → обучающая ошибка, НЕ «not connected».
    res = dispatch_tool(session, "set_register", {"process": "cam", "register": "x", "value": 1})
    assert res["success"] is False
    assert "record_unload" in res["error"]
    assert "not connected" not in res["error"]


def test_record_start_rejected_in_replay(record_dir: Path, session_and_driver) -> None:
    session, drv = session_and_driver
    dispatch_tool(session, "record_start", {"name": "a"})
    time.sleep(0.02)
    dispatch_tool(session, "record_stop", {})
    dispatch_tool(session, "record_load", {"name": "a"})
    res = dispatch_tool(session, "record_start", {"name": "b"})
    assert res["success"] is False
    assert "replay" in res["error"]


def test_record_load_unknown_name_error(record_dir: Path, session_and_driver) -> None:
    session, _drv = session_and_driver
    res = dispatch_tool(session, "record_load", {"name": "does_not_exist"})
    assert res["success"] is False


def test_reset_finalizes_active_recording(record_dir: Path, session_and_driver) -> None:
    """reset() (обрыв сессии) финализирует запись footer'ом disconnect — файл не без footer'а."""
    session, drv = session_and_driver
    dispatch_tool(session, "record_start", {"name": "onreset"})
    drv._emit_event(_state_push("processes.cam.state.fps", 5.0))
    time.sleep(0.05)
    session.reset()  # эмулируем обрыв/реконнект

    path = resolve_record_path("onreset")
    import json

    lines = [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    footer = lines[-1]
    assert footer.get("footer") is True
    assert footer["reason"] == "disconnect"


def test_record_dump_one_shot(record_dir: Path, session_and_driver) -> None:
    session, drv = session_and_driver
    # Наполняем arrival-кольцо (без активной записи — чёрный ящик always-on).
    drv._emit_event(_state_push("processes.cam.state.fps", 1.0))
    drv._emit_event(_state_push("processes.cam.state.fps", 2.0))
    res = dispatch_tool(session, "record_dump", {"name": "blackbox"})
    assert res["success"] is True
    assert res["reason"] == "dump"
    # Дамп грузится тем же record_load.
    load = dispatch_tool(session, "record_load", {"name": "blackbox"})
    assert load["success"] is True


def test_replay_served_covers_documented_set() -> None:
    """Пин набора REPLAY_SERVED (страховка от тихого расхождения с планом §3)."""
    assert REPLAY_SERVED == {
        "events",
        "events_page",
        "telemetry_snapshot",
        "telemetry_history",
        "system_overview",
        "state_get",
        "state_get_subtree",
        "await_condition",
    }
