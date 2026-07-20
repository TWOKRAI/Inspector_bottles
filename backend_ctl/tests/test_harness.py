# -*- coding: utf-8 -*-
"""Тесты BackendHarness (Ф1 Task 1.3): честный headless + гарантированный teardown.

- strip_gui — чистая функция фильтрации gui из топологии (юнит, без запуска системы);
- harness_smoke — live-прогон: старт → introspect.status пары процессов → стоп < 30с;
- регресс из 1.1: state_subscribe → set_register → ожидаем push state.changed в
  событийном канале (events_page). Помечен xfail — push физически не доходит до
  внешнего сокет-клиента (диагноз в тесте).
"""

from __future__ import annotations

import time

import pytest

from backend_ctl.harness import BackendHarness, strip_gui
from backend_ctl.tests.conftest import wait_for_events as _wait_events


class TestStripGui:
    """Юнит: честный headless = исключить процесс презентации из топологии."""

    def test_removes_gui_process(self) -> None:
        bp = {
            "processes": [
                {"process_name": "gui", "protected": True},
                {"process_name": "camera_0"},
            ],
            "wires": [],
        }
        out = strip_gui(bp)
        names = [p["process_name"] for p in out["processes"]]
        assert "gui" not in names
        assert "camera_0" in names

    def test_does_not_mutate_input(self) -> None:
        bp = {"processes": [{"process_name": "gui"}, {"process_name": "cam"}]}
        strip_gui(bp)
        # исходный dict не тронут (Dict-at-Boundary: работаем на копии)
        assert [p["process_name"] for p in bp["processes"]] == ["gui", "cam"]

    def test_noop_when_no_gui(self) -> None:
        bp = {"processes": [{"process_name": "cam"}]}
        # gui и так нет → возвращаем тот же объект (no-op, без копии)
        assert strip_gui(bp) is bp

    def test_custom_gui_name(self) -> None:
        bp = {"processes": [{"process_name": "frontend"}, {"process_name": "cam"}]}
        out = strip_gui(bp, gui_name="frontend")
        assert [p["process_name"] for p in out["processes"]] == ["cam"]

    def test_robust_to_missing_processes(self) -> None:
        assert strip_gui({}) == {}
        assert strip_gui({"processes": "not-a-list"}) == {"processes": "not-a-list"}


@pytest.mark.harness_smoke
def test_harness_smoke_start_status_stop() -> None:
    """Live smoke: honest headless старт → introspect.status пары процессов → стоп < 30с.

    with_base=True: топология включает фундамент, где объявлен gui — strip_gui обязан
    его исключить, иначе поднялся бы Qt/LoginDialog (Ф0.4). Порт 8766 — чтобы не
    конфликтовать с session-фикстурой headless_backend (8765), если та активна.
    """
    t0 = time.monotonic()
    harness = BackendHarness(with_base=True, port=8766)
    try:
        drv = harness.start()
        for proc in ("preprocessor", "region_splitter"):
            res = drv.introspect_status(proc, timeout=8.0)
            assert res.get("success") is True, f"{proc}: introspect.status не success: {res}"
    finally:
        harness.stop()
    elapsed = time.monotonic() - t0
    assert elapsed < 30.0, f"старт+стоп {elapsed:.1f}s ≥ 30s (бюджет acceptance)"


@pytest.mark.harness_smoke
def test_state_changed_push_reaches_driver_regression() -> None:
    """Регресс 1.1 (закрыт Ф1.1b): живой бэкенд, state_subscribe('**') → set_register → push в событийный канал.

    Мост push→SocketChannel (RouterManager._deliver_by_targets): DeltaDispatcher шлёт
    state.changed с targets=['backend_ctl'] + queue_type='system'; очереди
    'backend_ctl_system' нет (backend_ctl не процесс), но зарегистрирован SocketChannel
    'backend_ctl' → доставка идёт через канал во внешний driver. Раньше — silent drop.
    """
    harness = BackendHarness(with_base=True, port=8767)
    try:
        drv = harness.start()
        sub = drv.state_subscribe("**", timeout=8.0)
        assert (sub.get("result") or {}).get("status") == "ok" or sub.get("success"), sub
        # Verify-probe (Ф1.6): запись реально применилась, не молчаливый no-op.
        # Исторический урок: тут писали plugin_name+width (несуществующие ключ и
        # поле) — тест зеленел на чужих state.changed от heartbeat'ов.
        res = drv.set_register_verified("preprocessor", "resize", "target_width", 512, timeout=8.0)
        assert res["verified"], res
        evts, _ = _wait_events(drv, timeout=5.0)
        changed = [e for e in evts if e.get("command") == "state.changed"]
        assert changed, "push state.changed не дошёл до событийного канала driver'а"
    finally:
        harness.stop()


# --- Task 0.4: env-restore (без живого бэкенда — мокаем тяжёлые части) ---


class _FakeLauncher:
    def start(self):
        pass

    def wait_until_ready(self, timeout):
        return True

    def get_status(self):
        return {"process": {"pid": None}}

    def stop(self):
        pass


class _FakeDriver:
    def __init__(self, *args, **kwargs):
        pass

    def connect(self, timeout=5.0):
        pass

    def introspect_status(self, process, *, timeout=None):
        return {"success": True}

    def close(self):
        pass


class TestEnvRestore:
    def test_env_restored_to_prior_state_after_stop(self, monkeypatch) -> None:
        import os as _os

        from backend_ctl import harness as _h

        # Прежнее окружение: BACKEND_CTL задан, PORT отсутствует, PID_FILE задан.
        monkeypatch.setenv("BACKEND_CTL", "orig")
        monkeypatch.delenv("BACKEND_CTL_PORT", raising=False)
        monkeypatch.setenv("INSPECTOR_PID_FILE", "orig_pid")
        keys = ("BACKEND_CTL", "BACKEND_CTL_PORT", "INSPECTOR_PID_FILE")
        before = {k: _os.environ.get(k) for k in keys}

        h = BackendHarness(port=8799, launcher_factory=_FakeLauncher)
        monkeypatch.setattr(_h, "BackendDriver", _FakeDriver)
        monkeypatch.setattr(_h, "_subtree", lambda pid: [])
        monkeypatch.setattr(_h, "_shutdown_with_watchdog", lambda *a, **k: None)

        h.start()
        # Во время работы окружение замучено под endpoint.
        assert _os.environ["BACKEND_CTL"] == "1"
        assert _os.environ["BACKEND_CTL_PORT"] == "8799"

        h.stop()
        after = {k: _os.environ.get(k) for k in keys}
        assert after == before, f"env не восстановлен: {before} → {after}"

    def test_env_restored_when_start_raises(self, monkeypatch) -> None:
        # Регресс на MAJOR #4 ревью: исключение на пути start() (до wait_until_ready)
        # не должно оставлять env-мутации (__exit__ не зовётся при падении __enter__).
        import os as _os

        from backend_ctl import harness as _h

        monkeypatch.setenv("BACKEND_CTL", "orig")
        monkeypatch.delenv("BACKEND_CTL_PORT", raising=False)
        monkeypatch.delenv("INSPECTOR_PID_FILE", raising=False)
        keys = ("BACKEND_CTL", "BACKEND_CTL_PORT", "INSPECTOR_PID_FILE")
        before = {k: _os.environ.get(k) for k in keys}

        def _boom_factory():
            raise RuntimeError("launcher build failed")

        h = BackendHarness(port=8798, launcher_factory=_boom_factory)
        monkeypatch.setattr(_h, "_subtree", lambda pid: [])
        monkeypatch.setattr(_h, "_shutdown_with_watchdog", lambda *a, **k: None)

        with pytest.raises(RuntimeError, match="launcher build failed"):
            h.start()

        after = {k: _os.environ.get(k) for k in keys}
        assert after == before, f"env утёк после падения start(): {before} → {after}"
