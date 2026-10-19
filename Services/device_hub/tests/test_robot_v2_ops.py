"""Сторожа автора T5.3d d1: ``param_set`` и замок параметров ``RobotDriverV2`` против sim v2.

Purpose:
    Приёмка (``test_robot_v2_ops_acceptance.py``) пишется слепо; здесь — то, что видно только автору: сбой записи
    файла после ACK оставляет ``self._epoch`` прежним; откат значения при сбое метки (d-I21) и «откат не прошёл»;
    фабрика хаба передаёт драйверу единственное хранилище плагина (d-I8); ``_param_lock`` берётся не блокируя, а
    ``_syncing`` отказывает ``param_set`` / ``param_apply`` / ``jog_step`` и не трогает робота.
    Шов на сбой — в ``drv._client.cmd`` (транспорт клиента), а не барьер на входе метода.

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope

from Services.device_hub.manager import DeviceManager
from Services.robot_comm.core.params_v2 import PARAM_ID
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.errors import RobotTimeout
from Services.robot_comm.robot_data import load_params
from Services.robot_comm.store import RobotDataStore
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded

DEV = "rob_v2"
TEXT_SYNCING = "идёт синхронизация параметров"
TEXT_EPOCH_NOT_WRITTEN = "параметр не применён: метка не записана"
TEXT_DIVERGED = "параметр робота расходится с файлом"
_SPD = "P_SPD_DEFAULT"
_SPD_DEFAULT_RAW = 80  # умолчание словаря: драйвер без param_source стартует с ним

_SCOPE: Any = None


@pytest.fixture(autouse=True)
def driver_scope() -> Iterator[Any]:
    global _SCOPE
    scope = open_scope("rv2opsg", budget_s=6.0)
    _SCOPE = scope
    try:
        yield scope
    finally:
        _SCOPE = None
        report = scope.close()
        assert list(report.survivors) == [], f"выжившие потоки области теста: {list(report.survivors)}"


class _Hub:
    def __init__(self, mgr: DeviceManager, rig: E2eRig, drv: Any, store: RobotDataStore, errors: list[Any]) -> None:
        self.mgr, self.rig, self.drv, self.store, self.errors = mgr, rig, drv, store, errors

    def call(self, op: str, args: dict) -> dict:
        return bounded(lambda: self.mgr.call(DEV, op, dict(args)), 15.0)

    def robot_spd(self) -> int:
        return bounded(lambda: self.rig.client.param_get(_SPD))


@contextmanager
def _hub(tmp_path: Path) -> Iterator[_Hub]:
    """Менеджер с драйвером v2 над ``E2eRig``; тик НЕ идёт: проверяются только вызовы операций."""
    store = RobotDataStore(tmp_path / "robot")
    errors: list[Any] = []

    def publish(path: str, payload: Any) -> None:
        if path.endswith(".last_error"):
            errors.append(payload)

    mgr = DeviceManager(store=None, publish_cb=publish, spawn=_SCOPE.spawn, robot_store=store)
    with E2eRig() as rig:
        mgr.upsert(
            {
                "id": DEV,
                "name": DEV,
                "kind": "robot",
                "protocol": "delta_v2",
                "transport": {"type": "tcp", "host": "127.0.0.1", "port": rig.port, "unit_id": ROBOT_UNIT_ID},
            }
        )
        try:
            assert bounded(lambda: mgr.connect(DEV), 60.0) is True
            yield _Hub(mgr, rig, mgr.get_driver(DEV), store, errors)
        finally:
            try:
                bounded(lambda: mgr.disconnect(DEV), 15.0)
            except Exception:  # noqa: BLE001 — уборка не подменяет исключение теста
                pass


def _fail_cmd(drv: Any, fails: Callable[[str, Any], bool]) -> list[tuple[str, Any]]:
    """Шов в транспорте клиента: ``cmd`` бросает там, где ``fails(op, args)``; возвращает журнал вызовов."""
    client = drv._client
    real = client.cmd
    seen: list[tuple[str, Any]] = []

    def cmd(op: str, args: Any) -> Any:
        seen.append((op, list(args)))
        if fails(op, args):
            raise RobotTimeout("res")
        return real(op, args)

    client.cmd = cmd
    return seen


def test_factory_passes_the_one_store(tmp_path: Path) -> None:
    """d-I8: драйвер хаба держит именно ``robot_store`` менеджера, а не своё хранилище."""
    with _hub(tmp_path) as hub:
        assert hub.drv._store is hub.store


def test_save_params_failure_after_ack_keeps_epoch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Файл не записался после ACK значения и метки: ``self._epoch`` и ``self._values`` прежние (§11.4 п.4)."""
    import Services.device_hub.drivers.robot_driver_v2 as module

    def broken_save(*_a: Any, **_kw: Any) -> str:
        raise OSError("disk full")

    with _hub(tmp_path) as hub:
        epoch_before, values_before = hub.drv._epoch, dict(hub.drv._values)
        monkeypatch.setattr(module, "save_params", broken_save)
        answer = hub.call("param_set", {"name": _SPD, "value": 55, "base_rev": None})
        assert answer["status"] == "error", answer
        assert hub.drv._epoch == epoch_before
        assert hub.drv._values == values_before
        assert load_params(hub.store, DEV).rev is None  # файла нет: запись не прошла
        assert hub.drv._param_lock.acquire(blocking=False)  # замок отпущен
        hub.drv._param_lock.release()


def test_epoch_write_failure_rolls_value_back(tmp_path: Path) -> None:
    """d-I21: метка не записана после ACK значения -> роботу возвращено прежнее значение, файл и эпоха целы."""
    with _hub(tmp_path) as hub:
        epoch_before = hub.drv._epoch
        assert hub.robot_spd() == _SPD_DEFAULT_RAW
        epoch_id = PARAM_ID["P_CONFIG_EPOCH"]
        seen = _fail_cmd(hub.drv, lambda op, args: op == "PARAM_SET" and args[0] == epoch_id)

        answer = hub.call("param_set", {"name": _SPD, "value": 55, "base_rev": None})

        assert answer == {"status": "error", "message": TEXT_EPOCH_NOT_WRITTEN}
        assert hub.robot_spd() == _SPD_DEFAULT_RAW  # откат дошёл до робота
        assert hub.drv._epoch == epoch_before
        assert load_params(hub.store, DEV).rev is None  # файл не тронут
        spd_id = PARAM_ID[_SPD]
        assert [a for op, a in seen if op == "PARAM_SET" and a[0] == spd_id] == [
            [spd_id, 55],
            [spd_id, _SPD_DEFAULT_RAW],
        ]
        assert hub.errors[-1] == TEXT_EPOCH_NOT_WRITTEN


def test_rollback_failure_reports_divergence(tmp_path: Path) -> None:
    """Откат тоже не прошёл: ответ тот же, ``last_error`` — «параметр робота расходится с файлом»."""
    with _hub(tmp_path) as hub:
        spd_id, epoch_id = PARAM_ID[_SPD], PARAM_ID["P_CONFIG_EPOCH"]
        _fail_cmd(
            hub.drv,
            lambda op, a: op == "PARAM_SET" and (a[0] == epoch_id or (a[0] == spd_id and a[1] == _SPD_DEFAULT_RAW)),
        )

        answer = hub.call("param_set", {"name": _SPD, "value": 55, "base_rev": None})

        assert answer == {"status": "error", "message": TEXT_EPOCH_NOT_WRITTEN}
        assert hub.errors[-1] == TEXT_DIVERGED
        assert hub.drv._epoch == 1  # метка в драйвере не тронута


@pytest.mark.parametrize("how", ["lock_held", "syncing"])
def test_param_ops_refused_while_syncing_and_robot_untouched(tmp_path: Path, how: str) -> None:
    """``_param_lock`` занят или ``_syncing`` -> отказ сразу, без записи роботу; ``jog_step`` при ``_syncing`` тоже."""
    with _hub(tmp_path) as hub:
        drv = hub.drv
        seen = _fail_cmd(drv, lambda *_: False)
        refusal = {"status": "error", "message": TEXT_SYNCING}
        holder: list[bool] = []
        if how == "lock_held":
            assert drv._param_lock.acquire(blocking=False)
        else:
            with drv._flags_lock:
                drv._syncing = True
        try:
            done = threading.Event()

            def run() -> None:
                holder.append(hub.call("param_set", {"name": _SPD, "value": 55, "base_rev": None}) == refusal)
                holder.append(hub.call("param_apply", {}) == refusal)
                done.set()

            threading.Thread(target=run, daemon=True).start()
            assert done.wait(5.0), "param_set / param_apply заблокировались на замке параметров"
            assert holder == [True, True]
            if how == "syncing":
                assert hub.call("jog_step", {"dx": 1, "dy": 0, "spd": 50}) == refusal
            assert [op for op, _ in seen if op in ("PARAM_SET", "PARAM_APPLY", "JOG_STEP")] == []
        finally:
            if how == "lock_held":
                drv._param_lock.release()
            else:
                with drv._flags_lock:
                    drv._syncing = False


# --------------------------------------------------------------------------------------------------
# d2: синхронизация параметров, _syncing, _param_lock
# --------------------------------------------------------------------------------------------------


def _block_first_param_set(drv: Any) -> tuple[threading.Event, threading.Event, list[tuple[str, Any]]]:
    """Шов в транспорте клиента: первый ``PARAM_SET`` ждёт ``release`` ДО исходного ``cmd``; журнал вызовов."""
    client = drv._client
    real = client.cmd
    entered, release = threading.Event(), threading.Event()
    seen: list[tuple[str, Any]] = []

    def cmd(op: str, args: Any) -> Any:
        seen.append((op, list(args)))
        if op == "PARAM_SET" and not entered.is_set():
            entered.set()
            assert release.wait(5.0), "release не поставлен"
        return real(op, args)

    client.cmd = cmd
    return entered, release, seen


def _break_epoch(hub: _Hub) -> None:
    """Метка робота расходится с меткой ПК при живом соединении."""
    hub.rig.core.regs[REG["TLM_CFG_EPOCH"]] = 0


def test_param_set_during_sync_answers_fast_and_robot_untouched(tmp_path: Path) -> None:
    """d-I9: ``param_set`` во время ``sync_params`` (поток синхронизации стоит на ``PARAM_SET``) отвечает ≤ 0,5 с."""
    with _hub(tmp_path) as hub:
        drv = hub.drv
        entered, release, seen = _block_first_param_set(drv)
        _break_epoch(hub)
        worker = threading.Thread(target=lambda: drv._resync_maybe(drv._client), daemon=True)
        worker.start()
        try:
            assert entered.wait(3.0), "синхронизация не дошла до PARAM_SET"
            writes = len([1 for op, _ in seen if op == "PARAM_SET"])
            t0 = time.monotonic()
            answer = hub.call("param_set", {"name": _SPD, "value": 55, "base_rev": None})
            elapsed = time.monotonic() - t0
            assert answer == {"status": "error", "message": TEXT_SYNCING}
            assert elapsed <= 0.5, elapsed
            assert len([1 for op, _ in seen if op == "PARAM_SET"]) == writes  # робот не тронут
        finally:
            release.set()
            worker.join(10.0)
        assert not worker.is_alive()
        assert drv._syncing is False  # флаг снят в finally
        assert drv._param_lock.acquire(blocking=False)  # замок отпущен последним
        drv._param_lock.release()


@pytest.mark.parametrize("flag", ["_busy", "_job_active", "_jog_starting", "_jog_stopping", "_prog_alive"])
def test_syncing_is_set_atomically_with_activity_check(tmp_path: Path, flag: str) -> None:
    """d-I20: при активности синхронизации нет, ``_syncing`` и ``_last_resync`` не ставятся; без неё — ставится."""
    with _hub(tmp_path) as hub:
        drv = hub.drv
        seen = _fail_cmd(drv, lambda *_: False)
        _break_epoch(hub)
        with drv._flags_lock:
            setattr(drv, flag, True)
        try:
            drv._resync_maybe(drv._client)
            assert [op for op, _ in seen if op == "PARAM_SET"] == []
            assert drv._syncing is False
            assert drv._last_resync == 0.0  # отказ по активности задержки в 2 с не создаёт
        finally:
            with drv._flags_lock:
                setattr(drv, flag, False)
        drv._resync_maybe(drv._client)  # активности нет: сразу, без паузы
        assert [op for op, _ in seen if op == "PARAM_SET"] != []
        assert hub.rig.read("TLM_CFG_EPOCH") == [drv._epoch]
        assert drv._syncing is False


def test_resync_rereads_epoch_under_lock(tmp_path: Path) -> None:
    """d-I10: метка тика устарела (``param_set`` уже записал её) — под замком читается заново, sync не идёт."""
    with _hub(tmp_path) as hub:
        drv = hub.drv
        seen = _fail_cmd(drv, lambda *_: False)
        assert hub.rig.read("TLM_CFG_EPOCH") == [drv._epoch]  # метки равны; тик «видел» расхождение раньше
        drv._resync_maybe(drv._client)
        assert [op for op, _ in seen if op == "PARAM_SET"] == []
        assert drv._last_resync == 0.0


def test_param_set_vs_resync_between_epoch_ack_and_save(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Тик видит расхождение меток между ACK метки и записью ``self._epoch``: полной пересинхронизации нет."""
    import Services.device_hub.drivers.robot_driver_v2 as module

    real_save = module.save_params
    entered, release = threading.Event(), threading.Event()

    def save(*args: Any, **kwargs: Any) -> str:
        entered.set()
        assert release.wait(5.0), "release не поставлен"
        return real_save(*args, **kwargs)

    with _hub(tmp_path) as hub:
        drv = hub.drv
        monkeypatch.setattr(module, "save_params", save)
        seen = _fail_cmd(drv, lambda *_: False)
        answer: list[dict] = []
        worker = threading.Thread(
            target=lambda: answer.append(hub.call("param_set", {"name": _SPD, "value": 55, "base_rev": None})),
            daemon=True,
        )
        worker.start()
        try:
            assert entered.wait(5.0), "param_set не дошёл до записи файла"
            assert hub.rig.read("TLM_CFG_EPOCH") != [drv._epoch]  # робот уже с новой меткой, драйвер ещё со старой
            drv._resync_maybe(drv._client)  # тик в этом окне
        finally:
            release.set()
            worker.join(10.0)
        assert answer and answer[0]["status"] == "ok", answer
        assert len([1 for op, _ in seen if op == "PARAM_SET"]) == 2  # значение и метка, полной синхронизации нет
        assert hub.rig.read("TLM_CFG_EPOCH") == [drv._epoch]
