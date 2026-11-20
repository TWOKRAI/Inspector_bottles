"""Задача S4b2: воркер hub переживает исключение из ``RobotDriverV2.tick``, счёт подряд — по ``tick_fails_limit``.

Отличие от ``test_readiness_pause_v2_hazards.py`` (``test_b8_*``): там ``tick_fails_limit`` гоняется на ДВОЙНИКЕ
драйвера (``Steps``), здесь — на НАСТОЯЩЕМ ``RobotDriverV2`` с ``RobotClientV2`` поверх
``FakeRobotTransport(RobotSimCoreV2())``, под настоящим ``DeviceHubPlugin`` (``configure`` / ``start``), без
``make_scene`` (его фабрика берёт двойники).

ЧЕСТНАЯ ГРАНИЦА. Настоящий ``RobotDriverV2.tick`` оборачивает в ``try`` пульс, чтение TLM и ``poll_errors``; строки
``self._park.step(...)`` и ``self._dispatch(...)`` стоят вне ``try``, но реального пути исключения из них без подмены
НЕТ: ``ParkMachine.step`` по контракту не бросает (внутри ``except Exception -> _on_error``), ``_run_next_job`` ловит
``except Exception``. Поэтому исключение вносится подменой ``_dispatch`` / ``_park.step`` НА ЭКЗЕМПЛЯРЕ драйвера
(для исхода «ок» обёртка делегирует исходному методу). Тест доказывает «воркер hub переживает ЛЮБОЕ исключение из
``RobotDriverV2.tick`` и считает подряд по ``tick_fails_limit``», а не живой сценарий: реальный путь такого
исключения не найден; сим-робот v2 не умеет ``fault.*``; стенд — отдельная задача (день №2).

Кто что пишет: счётчик подряд — локальная ``fails`` в ``tick_loop`` плагина (виден только через ``conn``);
``tick_fails_limit`` читает ПЛАГИН (``drv.entry.params``, один раз при старте воркера), драйвер ключ не использует;
``last_error`` и ``conn`` пишет воркер плагина.

Каждый шаг ждёт ВХОДА воркера в следующий такт (иначе умерший воркер незаметен: без ``conn_stale_s`` ``readiness``
остаётся ``[]`` навсегда). Всё, что может зависнуть, — с дедлайном; потоки daemon. Ожидаемые значения — литералы.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Plugins.hub.device_hub.tests.conftest import make_ctx
from Plugins.hub.device_hub.tests.test_readiness_pause_v2 import (
    _DEV,
    _LINK_ERROR,
    _TCP,
    Scene,
    bounded,
    until,
)
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2
from Services.robot_comm.testing.fake_transport import FakeRobotTransport

_TICK_CONTEXT = f"device_hub.tick.{_DEV}"
_LAST_ERROR_PATH = f"devices.state.{_DEV}.last_error"


# --------------------------------------------------------------------------------------------------
# Подмена метода настоящего драйвера: пошаговые исходы, «ок» делегирует исходному методу
# --------------------------------------------------------------------------------------------------


class Injector:
    """Обёртка метода драйвера: один пермит = один вызов; исход по списку (``"raise"`` бросает, иное — делегирует)."""

    def __init__(self, original: Callable[..., Any], outcomes: list[str]) -> None:
        self.original = original
        self.outcomes = list(outcomes)
        self.permits = threading.Semaphore(0)
        self.cond = threading.Condition()
        self.started = 0
        self.finished = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        with self.cond:
            self.started += 1
            self.cond.notify_all()
        if not self.permits.acquire(timeout=30.0):
            return self.original(*args, **kwargs)
        outcome = self.outcomes.pop(0) if self.outcomes else "ok"
        with self.cond:
            self.finished += 1
            self.cond.notify_all()
        if outcome == "raise":
            raise RuntimeError("tick boom")
        return self.original(*args, **kwargs)

    def wait_first_entry(self, deadline_s: float = 5.0) -> None:
        until(lambda: self.started >= 1, deadline_s, "воркер вошёл в первый такт")

    def step(self, deadline_s: float = 5.0) -> None:
        """Разрешить один вызов и дождаться, пока воркер отработал его итог и вошёл в следующий такт."""
        target = self.finished + 1
        self.permits.release()
        until(lambda: self.finished >= target and self.started >= target + 1, deadline_s, f"такт {target} отработан")

    def close(self) -> None:
        self.permits.release(1000)


class Real:
    """Сцена с настоящим драйвером v2: плагин, драйвер, подмена и поток воркера."""

    def __init__(self, scene: Scene, drv: Any, inj: Injector, where: str) -> None:
        self.sc = scene
        self.drv = drv
        self.inj = inj
        self.where = where
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = self.sc.start_worker()
        self.inj.wait_first_entry()

    def remove_injection(self) -> None:
        """Снять подмену с экземпляра (методы класса снова видны) и отпустить воркера, застрявшего в обёртке."""
        target = self.drv if self.where == "dispatch" else self.drv._park
        del target.__dict__["_dispatch" if self.where == "dispatch" else "step"]
        self.inj.close()

    def alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def conn(self) -> Any:
        rec = self.sc.last_conn_record()
        return rec.get("conn") if isinstance(rec, dict) else rec

    def tick_reports(self) -> list[Any]:
        return [c for c in self.sc.ctx.health.report_error.call_args_list if c.kwargs.get("context") == _TICK_CONTEXT]

    def last_errors(self) -> list[Any]:
        calls = self.sc.ctx.state_proxy.merge.call_args_list
        return [c.args[1] for c in calls if c.args and c.args[0] == _LAST_ERROR_PATH]


@pytest.fixture
def make_real(tmp_path: Path):
    """Фабрика: ``make_real(outcomes, where=..., start=True, **params)``. Одна сцена на тест."""
    scenes: list[Scene] = []

    def make(outcomes: list[str], *, where: str = "dispatch", start: bool = True, **params: Any) -> Real:
        registry = tmp_path / "devices.yaml"
        recipe = [
            {
                "id": _DEV,
                "name": _DEV,
                "kind": "robot",
                "protocol": "delta_v2",
                "transport": _TCP,
                "params": {"poll_interval_s": 0.05, **params},
            }
        ]
        ctx = make_ctx({"registry_path": str(registry), "recipe_devices": recipe}, tmp_registry=registry)
        ctx.health = MagicMock()
        ctx.log_warning = MagicMock()
        plugin = DeviceHubPlugin()
        plugin.configure(ctx)
        scene = Scene(plugin=plugin, ctx=ctx, ids=[_DEV])  # drivers пуст: двойников нет
        scenes.append(scene)
        # именно ядро v2: ``sim_core`` из conftest плагина построен на v1 и даёт WrongFirmware
        plugin._manager.set_driver_options("robot", "delta_v2", transport=FakeRobotTransport(RobotSimCoreV2()))
        plugin.start(ctx)
        assert plugin.cmd_device_connect({"device_id": _DEV})["status"] == "ok"
        bounded(plugin._process_conn_queue)
        drv = plugin._manager.get_driver(_DEV)
        assert drv is not None, "обвязка: настоящий драйвер не создан"
        assert type(drv).__name__ == "RobotDriverV2", type(drv)
        assert drv.is_connected is True, "обвязка: драйвер v2 не подключился к FakeRobotTransport"
        if where == "dispatch":
            inj = Injector(drv._dispatch, outcomes)
            drv._dispatch = inj
        else:
            inj = Injector(drv._park.step, outcomes)
            drv._park.step = inj
        scene.hooks.append(inj)  # ``Scene.close`` зовёт ``close`` каждой записи и отпускает воркер
        real = Real(scene, drv, inj, where)
        if start:
            real.start()
        return real

    yield make
    for scene in reversed(scenes):
        scene.close()


# --------------------------------------------------------------------------------------------------
# REDS 0. Предусловие: подмена действительно даёт исключение из настоящего tick
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("where", ["dispatch", "park_step"])
def test_r0_direct_tick_raises_when_method_is_replaced(make_real: Callable[..., Real], where: str) -> None:
    """Прямой ``drv.tick()`` из потока теста с подменой БРОСАЕТ ``RuntimeError``: тик не оборачивает эти строки в
    ``try``. Если драйвер начнёт их ловить, тест краснеет — сигнал «дефект драйвера починен, тест устарел»."""
    real = make_real(["raise"], where=where, start=False)
    real.inj.permits.release()
    with pytest.raises(RuntimeError, match="tick boom"):
        bounded(real.drv.tick)


# --------------------------------------------------------------------------------------------------
# REDS 1. Одиночные броски не роняют воркер и не портят связь
# --------------------------------------------------------------------------------------------------


def test_r1_isolated_raises_keep_link_and_worker(make_real: Callable[..., Real]) -> None:
    real = make_real(["raise", "ok", "raise", "raise", "ok"])
    for n in range(5):
        real.inj.step()
        assert real.sc.readiness() == [], f"после шага {n + 1}"
        assert real.conn() == "connected", f"после шага {n + 1}: {real.sc.last_conn_record()}"
        assert real.drv.is_connected is True, f"после шага {n + 1}"
    assert real.alive(), "поток воркера умер"


# --------------------------------------------------------------------------------------------------
# REDS 2, 3. Три броска подряд при живой связи: error, отчёты на каждом броске
# --------------------------------------------------------------------------------------------------


def _three_raises(make_real: Callable[..., Real], where: str) -> None:
    real = make_real(["raise", "raise", "raise"], where=where)
    for n in (1, 2, 3):
        real.inj.step()
        assert real.drv.is_connected is True, f"после шага {n}"
        reports = real.tick_reports()
        assert len(reports) == n, f"health.report_error по контексту {_TICK_CONTEXT!r} после шага {n}: {reports}"
        assert all(isinstance(c.args[0], RuntimeError) for c in reports), reports
        # last_error пишется на КАЖДОМ броске, включая первый
        assert real.last_errors() == ["tick boom"] * n, f"после шага {n}"
        if n < 3:
            assert real.sc.readiness() == [], f"после шага {n}: связь ещё не ошибочна"
            assert real.conn() == "connected", f"после шага {n}"
    assert real.sc.readiness() == _LINK_ERROR
    assert real.conn() == "error"
    # контекст не «device_hub.tick» без id устройства
    assert [
        c for c in real.sc.ctx.health.report_error.call_args_list if c.kwargs.get("context") == "device_hub.tick"
    ] == []
    assert real.alive(), "поток воркера умер"


def test_r2_three_dispatch_raises_in_a_row_report_link_error(make_real: Callable[..., Real]) -> None:
    _three_raises(make_real, "dispatch")


def test_r3_three_park_step_raises_in_a_row_report_link_error(make_real: Callable[..., Real]) -> None:
    _three_raises(make_real, "park_step")


# --------------------------------------------------------------------------------------------------
# REDS 4. Серия прервана успехом: счёт подряд идёт заново
# --------------------------------------------------------------------------------------------------


def test_r4_success_resets_streak_link_error_only_on_third_after_it(make_real: Callable[..., Real]) -> None:
    real = make_real(["raise", "raise", "ok", "raise", "raise", "raise"])
    for n in range(1, 6):
        real.inj.step()
        assert real.sc.readiness() == [], f"после шага {n}: подряд меньше трёх"
    real.inj.step()
    assert real.sc.readiness() == _LINK_ERROR, "третий бросок подряд после «ок»"
    assert real.conn() == "error"
    assert real.alive()


# --------------------------------------------------------------------------------------------------
# REDS 5. params.tick_fails_limit доходит до воркера через drv.entry.params
# --------------------------------------------------------------------------------------------------


def _tick_fails_warnings(real: Real) -> list[str]:
    return [str(c) for c in real.sc.ctx.log_warning.call_args_list if "tick_fails_limit" in str(c)]


def test_r5_limit_one_reports_link_error_from_first_raise(make_real: Callable[..., Real]) -> None:
    real = make_real(["raise"], tick_fails_limit=1)
    real.inj.step()
    assert real.sc.readiness() == _LINK_ERROR
    assert real.conn() == "error"
    assert _tick_fails_warnings(real) == []


def test_r5_limit_two_waits_for_second_raise(make_real: Callable[..., Real]) -> None:
    real = make_real(["raise", "raise"], tick_fails_limit=2)
    real.inj.step()
    assert real.sc.readiness() == [], "лимит 2: после первого броска связь ещё не ошибочна"
    real.inj.step()
    assert real.sc.readiness() == _LINK_ERROR
    assert _tick_fails_warnings(real) == []


@pytest.mark.parametrize("value", [0, "x"], ids=["zero", "str"])
def test_r5_invalid_limit_falls_back_to_default_three_with_one_warning(
    make_real: Callable[..., Real], value: Any
) -> None:
    real = make_real(["raise", "raise", "raise"], tick_fails_limit=value)
    real.inj.step()
    real.inj.step()
    assert real.sc.readiness() == [], "негодный лимит: умолчание 3, после двух бросков связь ещё не ошибочна"
    real.inj.step()
    assert real.sc.readiness() == _LINK_ERROR
    assert len(_tick_fails_warnings(real)) == 1, _tick_fails_warnings(real)


# --------------------------------------------------------------------------------------------------
# REDS 6. После снятия подмены связь восстанавливается
# --------------------------------------------------------------------------------------------------


def test_r6_after_injection_removed_next_tick_restores_connected(make_real: Callable[..., Real]) -> None:
    real = make_real(["raise", "raise", "raise"])
    for _ in range(3):
        real.inj.step()
    assert real.sc.readiness() == _LINK_ERROR
    assert real.conn() == "error"
    real.remove_injection()
    until(lambda: real.conn() == "connected", 5.0, "успешный такт вернул conn == connected")
    until(lambda: real.sc.readiness() == [], 5.0, "readiness == [] после восстановления")
    assert real.alive(), "поток воркера умер"
