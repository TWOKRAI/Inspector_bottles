"""Hazard-тесты Task 2.2a (run-state): ``DeviceHubPlugin.readiness`` / ``pause`` — наборы устройств, гонки, повтор.

Purpose:
    Авторские тесты REDS 9-12 (``plans/2026-10-27_system-run-state/tasks/2.2.md``); слепые REDS 1-8 лежат в
    ``test_readiness_and_pause.py`` (оттуда берутся только помощники: ``PauseHub``, ``bounded``, ``make_hub``).

    * REDS 9:  ``cmd_device_sync_set`` расширяет и ``readiness``, и ``pause``; устройство вне рецепта останавливается
      ``pause`` и не входит в ``readiness``; ``cmd_device_remove`` чистит снимок соединений.
    * REDS 10: параллельные публикации ``conn`` (много потоков, ``sys.setswitchinterval(1e-6)``) не теряют записей
      снимка; ``readiness`` в цикле при этом не бросает и отвечает только одним из двух литералов.
    * REDS 11: ``pause`` дважды подряд — те же команды, состояние не копится; при ``_shutting_down == True`` флаг не
      меняется; ``readiness`` не ждёт медленную команду ``pause`` (hazard: пауза идёт без замков плагина).
    * REDS 12: ``manager.call`` отвечает ``{"status": "error"}`` (а не исключением) — ``pause`` всё равно бросает, но
      после обхода остальных устройств.

    Ожидаемые значения — литералы. Вызов, который может повиснуть, идёт в daemon-потоке с join-дедлайном.

Public API:
    Только тесты ``test_*``.

Stability: lite

Приватные имена, на которые опирается файл: ``_conn_snapshot`` (только ЧТЕНИЕ в REDS 10 — счёт потерь записей
снимка: публичного перечисления снимка нет, ``readiness`` видит лишь рецепт), ``_shutting_down`` (REDS 11),
``_process_conn_queue``, ``_publish_state`` (названы в DESIGN как контракт).
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from Plugins.hub.device_hub.tests.test_readiness_and_pause import (
    PauseHub,
    bounded,
    make_hub,
    publish,
    readiness,
)
from Plugins.hub.device_hub.tests.test_spi_commands_acceptance import FakeDriver

pytestmark = pytest.mark.timeout(120)

_CALL_S = 15.0
_CONNECT_S = 60.0


def _entry(dev_id: str, kind: str, protocol: str) -> dict:
    return {
        "id": dev_id,
        "name": dev_id,
        "kind": kind,
        "protocol": protocol,
        "transport": {"type": "tcp", "host": "127.0.0.1", "port": 50999, "unit_id": 2},
    }


def _not_connected(dev_id: str) -> dict:
    return {"severity": "failure", "reason": f"{dev_id} не подключено"}


def _link_error(dev_id: str) -> dict:
    return {"severity": "failure", "reason": f"{dev_id}: ошибка связи"}


@pytest.fixture
def hub(tmp_path: Path) -> PauseHub:
    return PauseHub(tmp_path)


def _sync_set(hub: PauseHub, devices: list[dict]) -> dict:
    res = hub.plugin.cmd_device_sync_set({"devices": devices, "origin": "recipe:alpha"})
    assert res["status"] == "ok", res
    return res


def _connect_all(hub: PauseHub) -> None:
    """Разобрать очередь connect супервизора (воркеры в ``FakeWorkerManager`` сами не идут)."""
    bounded(hub.plugin._process_conn_queue, _CONNECT_S)


# --------------------------------------------------------------------------------------------------
# RED 9 — sync_set меняет набор; устройство вне рецепта; remove чистит снимок
# --------------------------------------------------------------------------------------------------


def test_red9_sync_set_widens_readiness_and_pause_to_the_new_set(hub: PauseHub) -> None:
    """RED 9: ``device_sync_set`` с новым набором — ``readiness`` и ``pause`` покрывают именно его, а не старый."""
    first = _sync_set(hub, [_entry("r_a", "robot", "delta_v2"), _entry("v_b", "vfd", "gd20_bridge")])
    assert first["upserted"] == ["r_a", "v_b"]
    assert readiness(hub.plugin, hub.ctx) == [_not_connected("r_a"), _not_connected("v_b")]

    _connect_all(hub)
    assert readiness(hub.plugin, hub.ctx) == []
    hub.pause()
    assert sorted(hub.ops()) == [("r_a", "stop", {"level": "SOFT"}), ("v_b", "stop", {})]

    second = _sync_set(hub, [_entry("v_b", "vfd", "gd20_bridge"), _entry("r_c", "robot", "delta_universal3")])
    assert second["removed"] == ["r_a"]
    # r_a снят (не перечислен, снимок чист); v_b остался подключённым; новый r_c ещё не подключён
    assert readiness(hub.plugin, hub.ctx) == [_not_connected("r_c")]

    before = len(hub.ops())
    hub.pause()
    # r_a удалён вместе с драйвером, r_c не подключён — молча пропущен; v_b остановлен
    assert hub.ops()[before:] == [("v_b", "stop", {})]


def test_red9_sync_set_reports_new_ids_in_the_order_of_the_sent_devices(hub: PauseHub) -> None:
    """RED 9: порядок причин — порядок присланного ``devices`` (не алфавит и не порядок ``set``)."""
    _sync_set(
        hub,
        [
            _entry("zz_last", "vfd", "gd20_bridge"),
            _entry("aa_first", "robot", "delta_v2"),
            _entry("mm", "robot", "delta_v2"),
        ],
    )

    assert readiness(hub.plugin, hub.ctx) == [
        _not_connected("zz_last"),
        _not_connected("aa_first"),
        _not_connected("mm"),
    ]


def test_red9_device_outside_the_recipe_is_stopped_by_pause_but_not_listed_by_readiness(hub: PauseHub) -> None:
    """RED 9: ручное устройство (``device_upsert``) вне рецепта: ``pause`` его останавливает, ``readiness`` — нет,
    даже когда его связь в ``error``."""
    _sync_set(hub, [_entry("r_rec", "robot", "delta_v2")])
    manual = _entry("r_manual", "robot", "delta_v2")
    assert hub.plugin.cmd_device_upsert(manual)["status"] == "ok"
    assert hub.plugin.cmd_device_connect({"device_id": "r_manual"})["status"] == "ok"
    _connect_all(hub)  # подключаются оба: рецептный и ручной
    assert hub.drivers["r_manual"].is_connected and hub.drivers["r_rec"].is_connected

    publish(hub.plugin, "r_manual", "error")
    assert readiness(hub.plugin, hub.ctx) == []  # ручное устройство вне рецепта; рецептное подключено

    hub.pause()

    assert sorted(hub.ops()) == [("r_manual", "stop", {"level": "SOFT"}), ("r_rec", "stop", {"level": "SOFT"})]


def test_red9_removed_connected_device_is_not_listed_and_comes_back_not_connected(hub: PauseHub) -> None:
    """RED 9: после ``device_remove`` подключённого устройства оно не перечислено; ``device_sync_set`` с тем же ``id``
    до первой публикации — «не подключено», а не устаревший ``connected``. (Не ловит снятие ``pop`` в ``remove``:
    ``manager.disconnect`` сам пишет ``disconnected`` — этот случай держит тест «без драйвера» ниже.)"""
    _sync_set(hub, [_entry("r_a", "robot", "delta_v2"), _entry("v_b", "vfd", "gd20_bridge")])
    _connect_all(hub)
    assert readiness(hub.plugin, hub.ctx) == []

    assert hub.plugin.cmd_device_remove({"device_id": "r_a"})["status"] == "ok"
    assert readiness(hub.plugin, hub.ctx) == []  # удалённый не перечислен, сосед v_b подключён

    _sync_set(hub, [_entry("r_a", "robot", "delta_v2")])  # тот же id снова; connect в очереди, не разобран
    assert readiness(hub.plugin, hub.ctx) == [_not_connected("r_a")]


def test_red9_remove_clears_a_stale_error_of_a_device_without_a_driver(hub: PauseHub) -> None:
    """RED 9: драйвера нет (``connect`` не разбирался) -> ``manager.remove`` ничего не публикует, и только
    ``cmd_device_remove`` убирает запись снимка: тот же ``id`` снова — «не подключено», а не прежняя «ошибка связи»."""
    _sync_set(hub, [_entry("r_x", "robot", "delta_v2")])
    publish(hub.plugin, "r_x", "error")
    assert readiness(hub.plugin, hub.ctx) == [_link_error("r_x")]

    assert hub.plugin.cmd_device_remove({"device_id": "r_x"})["status"] == "ok"
    _sync_set(hub, [_entry("r_x", "robot", "delta_v2")])

    assert readiness(hub.plugin, hub.ctx) == [_not_connected("r_x")]


# --------------------------------------------------------------------------------------------------
# RED 10 — параллельные публикации: снимок не теряет записей, readiness не бросает
# --------------------------------------------------------------------------------------------------


class _NullStateProxy:
    """State-plane без записи: параллельные публикации не упираются в запись вызовов ``MagicMock``."""

    def set(self, path: str, data: Any) -> None:
        return None

    def merge(self, path: str, data: Any) -> None:
        return None


def test_red10_parallel_publications_lose_no_snapshot_entry_and_readiness_never_raises(tmp_path: Path) -> None:
    """RED 10: 8 потоков x 1200 различных ``id`` публикуют ``conn`` параллельно при ``setswitchinterval(1e-6)`` ->
    ни одной потерянной записи; читатель ``readiness`` в цикле не бросает и отвечает одним из двух литералов
    (устройство рецепта переключается ``error`` <-> ``connected`` третьей стороной)."""
    plugin, ctx = make_hub(tmp_path, ("robot_main",))
    ctx.state_proxy = _NullStateProxy()
    publish(plugin, "robot_main", "connected")  # до гонки запись есть: без неё допустим был бы третий ответ
    threads_n, per_thread = 8, 1200
    start = threading.Event()
    writers_done = threading.Event()
    errors: list[BaseException] = []
    odd_answers: list[Any] = []
    allowed = ([], [_link_error("robot_main")])

    def write(tag: int) -> None:
        try:
            start.wait()
            for i in range(per_thread):
                publish(plugin, f"t{tag}_d{i}", "connected")
        except BaseException as exc:  # noqa: BLE001 — переносится в поток теста
            errors.append(exc)

    def toggle() -> None:
        try:
            start.wait()
            flip = False
            while not writers_done.is_set():
                publish(plugin, "robot_main", "error" if flip else "connected")
                flip = not flip
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def read() -> None:
        try:
            start.wait()
            while not writers_done.is_set():
                answer = plugin.readiness(ctx)
                if answer not in allowed:
                    odd_answers.append(answer)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    writers = [threading.Thread(target=write, args=(t,), daemon=True, name=f"red10-w{t}") for t in range(threads_n)]
    helpers = [
        threading.Thread(target=toggle, daemon=True, name="red10-toggle"),
        threading.Thread(target=read, daemon=True, name="red10-read"),
    ]
    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        for thread in [*writers, *helpers]:
            thread.start()
        start.set()
        deadline = time.monotonic() + 60.0
        for thread in writers:
            thread.join(max(0.0, deadline - time.monotonic()))
        writers_done.set()
        for thread in helpers:
            thread.join(10.0)
    finally:
        sys.setswitchinterval(old_interval)
        writers_done.set()

    assert not any(thread.is_alive() for thread in [*writers, *helpers]), "потоки не завершились в срок"
    assert errors == [], errors
    assert odd_answers == [], odd_answers[:3]
    snapshot = plugin._conn_snapshot  # приватное чтение: публичного перечисления снимка нет
    lost = [
        f"t{t}_d{i}" for t in range(threads_n) for i in range(per_thread) if snapshot.get(f"t{t}_d{i}") != "connected"
    ]
    assert len(lost) == 0, f"потеряно записей снимка: {len(lost)} из {threads_n * per_thread}, например {lost[:3]}"


# --------------------------------------------------------------------------------------------------
# RED 11 — повтор pause, флаг выключения, readiness во время медленной паузы
# --------------------------------------------------------------------------------------------------


def test_red11_pause_twice_repeats_the_same_commands_and_accumulates_nothing(hub: PauseHub) -> None:
    """RED 11: ``pause`` дважды подряд (повтор оркестратором) — без исключений, второй вызов шлёт тот же набор команд
    ровно один раз на устройство; ``_shutting_down``, число воркеров и снимок не меняются."""
    hub.add("r2", "robot", "delta_v2")
    hub.add("v1", "vfd", "gd20_bridge")
    workers_before = dict(hub.ctx.worker_manager.workers)
    ready_before = readiness(hub.plugin, hub.ctx)

    hub.pause()
    first = hub.ops()
    hub.pause()
    second = hub.ops()

    expected = [("r2", "stop", {"level": "SOFT"}), ("v1", "stop", {})]
    assert sorted(first) == expected
    assert sorted(second) == sorted(expected + expected)  # ровно по одной команде на устройство за вызов
    assert hub.plugin._shutting_down is False
    assert hub.ctx.worker_manager.workers == workers_before
    assert readiness(hub.plugin, hub.ctx) == ready_before


def test_red11_pause_leaves_a_set_shutdown_latch_alone(hub: PauseHub) -> None:
    """RED 11: при ``_shutting_down == True`` (выключение процесса идёт) ``pause`` флаг не меняет и не бросает."""
    hub.add("r2", "robot", "delta_v2")
    hub.plugin._shutting_down = True
    try:
        hub.pause()
        assert hub.plugin._shutting_down is True
    finally:
        hub.plugin._shutting_down = False  # уборка фикстуры вызывает shutdown сама


class _BlockingStopDriver(FakeDriver):
    """``stop`` ждёт события: имитация долгой команды драйвера (запись + ожидание эха)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.entered = threading.Event()
        self.release = threading.Event()

    def call(self, op: str, args: dict) -> dict:
        self.entered.set()
        self.release.wait(10.0)
        return super().call(op, args)


def test_red11_readiness_does_not_wait_for_a_slow_pause(hub: PauseHub) -> None:
    """RED 11 (hazard): пока ``pause`` ждёт ответа драйвера, ``readiness`` возвращается в срок (``pause`` не держит
    ни ``_workers_lock``, ни замок реестра на время команды)."""
    hub.add("r_slow", "robot", "delta_v2", driver_cls=_BlockingStopDriver)
    driver = hub.drivers["r_slow"]
    assert isinstance(driver, _BlockingStopDriver)
    box: dict[str, Any] = {}

    def run_pause() -> None:
        try:
            hub.plugin.pause(hub.ctx)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=run_pause, daemon=True, name="red11-slow-pause")
    thread.start()
    try:
        assert driver.entered.wait(5.0), "обвязка: pause не дошёл до команды драйвера"
        assert readiness(hub.plugin, hub.ctx) == []  # bounded: зависание -> AssertionError
        # замки плагина и реестра в ходе паузы свободны
        assert bounded(lambda: hub.plugin.cmd_device_list({}), 5.0)["status"] == "ok"
    finally:
        driver.release.set()
        thread.join(10.0)
    assert not thread.is_alive()
    assert "error" not in box, box


# --------------------------------------------------------------------------------------------------
# RED 12 — ответ {"status": "error"} от manager.call — тоже сбой
# --------------------------------------------------------------------------------------------------


class _VanishingLinkDriver(FakeDriver):
    """После ``arm()`` ``is_connected`` истинно ровно один раз (предпроверка ``pause``), дальше — ложно: связь пропала
    между предпроверкой и ``DeviceManager.call``, и САМ менеджер отвечает ``{"status": "error"}`` (не драйвер)."""

    armed = False
    _reads_left = 1

    def arm(self) -> None:
        self._reads_left = 1
        self.armed = True

    @property
    def is_connected(self) -> bool:
        if not self.armed:
            return self.up
        if self._reads_left > 0:
            self._reads_left -= 1
            return True
        return False


def test_red12_manager_error_reply_is_a_failure_and_pause_raises_after_the_walk(hub: PauseHub) -> None:
    """RED 12: ``DeviceManager.call`` отвечает ``{"status": "error"}`` (связь пропала после предпроверки) — это не
    исключение, но ``pause`` обязан бросить; остальные устройства остановлены ДО броска."""
    hub.add("r_a", "robot", "delta_v2", driver_cls=_VanishingLinkDriver)
    hub.add("v_b", "vfd", "gd20_bridge")
    hub.add("r_c", "robot", "delta_universal3")
    vanishing = hub.drivers["r_a"]
    assert isinstance(vanishing, _VanishingLinkDriver)
    vanishing.arm()

    with pytest.raises(RuntimeError) as excinfo:
        hub.pause()

    assert str(excinfo.value) == "pause: сбой останова устройств"
    # r_a: команда до драйвера не дошла (ответил менеджер); соседи после него в обходе остановлены
    assert sorted(hub.ops()) == [("r_c", "abort", {"mode": 1}), ("v_b", "stop", {})]


@pytest.mark.parametrize(
    "reply",
    [{"status": "error", "message": "отказ"}, {"status": "busy"}, {}, {"ok": True}],
    ids=["error", "busy", "empty", "no_status_key"],
)
def test_red12_any_reply_other_than_status_ok_is_a_failure(hub: PauseHub, reply: dict) -> None:
    """RED 12: ответ драйвера без ``status == "ok"`` (и без ключа ``status``) — сбой; остальные остановлены."""
    hub.add("r_a", "robot", "delta_v2")
    hub.add("v_b", "vfd", "gd20_bridge")
    hub.drivers["r_a"].reply = reply

    with pytest.raises(RuntimeError) as excinfo:
        hub.pause()

    assert str(excinfo.value) == "pause: сбой останова устройств"
    assert sorted(hub.ops()) == [("r_a", "stop", {"level": "SOFT"}), ("v_b", "stop", {})]
