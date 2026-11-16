"""Авторские hazard-тесты Task 2.2a2 S4b (Б1-Б5): запись снимка из потоков, окно эпизода паузы, возраст с первого
такта, чистка возраста при remove/disconnect и запас окна медленной паузы.

Слепая приёмка — ``test_readiness_pause_v2.py`` (не правится). Стенд (сцена, двойники, часы) берётся оттуда.
Ожидаемые значения — литералы; всё, что может зависнуть, идёт в daemon-потоке с join-дедлайном.
"""

# ruff: noqa: F401, F811
from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from Plugins.hub.device_hub.plugin import TEXT_STATE_UNAVAILABLE
from Plugins.hub.device_hub.tests.test_readiness_and_pause import make_hub
from Plugins.hub.device_hub.tests.test_readiness_pause_v2 import (
    _DEV,
    _NOT_CONNECTED,
    _STALE_FAIL,
    _TCP,
    _THREE,
    Hang,
    Scene,
    bounded,
    make_scene,
    until,
)

_STALE = {"conn_stale_s": 1.0, "poll_interval_s": 0.1}


# --------------------------------------------------------------------------------------------------
# Б1. Запись снимка из потоков
# --------------------------------------------------------------------------------------------------


def test_b1_set_conn_from_many_threads_loses_nothing(tmp_path: Path) -> None:
    """8 потоков пишут по своим ``id`` (>= 1000 на поток) при переключении потоков каждые ~1 мкс: потерь 0;
    ``readiness`` в это время не бросает (не отвечает «состояние недоступно»)."""
    plugin, ctx = make_hub(tmp_path, (_DEV,))
    per_thread, workers = 1200, 8
    stop = threading.Event()
    bad: list[object] = []

    def reader() -> None:
        while not stop.is_set():
            res = plugin.readiness(ctx)
            if any(r.get("reason") == TEXT_STATE_UNAVAILABLE for r in res):
                bad.append(res)
                return

    def writer(k: int) -> None:
        for i in range(per_thread):
            plugin._set_conn(f"w{k}_{i}", "connected")

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    reader_thread = threading.Thread(target=reader, daemon=True, name="b1-reader")
    threads = [threading.Thread(target=writer, args=(k,), daemon=True, name=f"b1-w{k}") for k in range(workers)]
    try:
        reader_thread.start()
        for t in threads:
            t.start()
        for t in threads:
            t.join(30.0)
        assert not any(t.is_alive() for t in threads), "писатели не закончили за 30 с"
    finally:
        sys.setswitchinterval(old_interval)
        stop.set()
        reader_thread.join(5.0)
    assert not reader_thread.is_alive()
    assert bad == []
    snapshot = plugin._conn_snapshot  # приватное чтение: публичного перечисления снимка нет
    lost = [(k, i) for k in range(workers) for i in range(per_thread) if snapshot.get(f"w{k}_{i}") != "connected"]
    assert lost == [], f"потеряно записей: {len(lost)}"


# --------------------------------------------------------------------------------------------------
# Б2. Окно эпизода паузы
# --------------------------------------------------------------------------------------------------


def test_b2_episode_window_one_second_repeat_skips_robot_and_three_seconds_resends(
    make_scene: Callable[..., Scene],
) -> None:
    sc = make_scene(_THREE, clock=True)
    sc.drivers["belt"].reply = {"status": "error"}
    assert isinstance(sc.pause().error, RuntimeError)
    assert len(sc.drivers["r_v2"].stops()) == 1
    assert sc.clock is not None
    sc.clock.jump(1.0)  # повтор оркестратора: тот же эпизод
    assert isinstance(sc.pause().error, RuntimeError)
    assert len(sc.drivers["r_v2"].stops()) == 1, "повтор через 1,0 с не должен слать стоп уже остановленному"
    sc.clock.jump(3.1)  # больше окна от конца прошлого вызова: новый эпизод
    assert isinstance(sc.pause().error, RuntimeError)
    assert len(sc.drivers["r_v2"].stops()) == 2, "через 3,1 с эпизод новый: стоп должен уйти снова"


# --------------------------------------------------------------------------------------------------
# Б3. Висящий первый такт
# --------------------------------------------------------------------------------------------------


def test_b3_tick_hanging_from_the_first_tick_goes_stale(make_scene: Callable[..., Scene]) -> None:
    sc = make_scene(params=_STALE)
    sc.hook(_DEV, Hang())
    sc.start_worker()
    elapsed = sc.wait_readiness(_STALE_FAIL, 2.5)
    assert elapsed <= 2.5


def test_b6_threshold_unset_hanging_tick_stays_ready_right_after_clock_jump(make_scene: Callable[..., Scene]) -> None:
    """Порог не задан: ``connected`` и висящий такт не дают «нет обновления связи», даже сразу после сдвига часов
    (без ожидания тактов: успешный такт возраст бы освежил и скрыл порог по умолчанию)."""
    sc = make_scene(params={"poll_interval_s": 0.1}, clock=True)
    drv = sc.drivers[_DEV]
    sc.start_worker()
    until(lambda: drv.tick_count >= 2, 3.0, "два здоровых такта")
    sc.hook(_DEV, Hang())
    seen = drv.tick_count
    until(lambda: drv.tick_count > seen, 3.0, "воркер вошёл в висящий такт")
    assert sc.readiness() == []
    assert sc.clock is not None
    sc.clock.jump(3600.0)
    assert sc.readiness() == [], "без conn_stale_s возраст связи не проверяется"


# --------------------------------------------------------------------------------------------------
# Б4. Нет устаревшего возраста после remove / disconnect
# --------------------------------------------------------------------------------------------------


def _stop_manual_worker(sc: Scene) -> None:
    """Остановить поток воркера теста (``FakeWorkerManager.remove_worker`` потоки не гасит): иначе он сам
    освежает или пишет возраст после чистки плагина."""
    for evt in sc.stop_events:
        evt.set()
    for thread in sc.threads:
        thread.join(3.0)
    assert not any(t.is_alive() for t in sc.threads)


def test_b4a_remove_then_sync_set_does_not_inherit_old_age(make_scene: Callable[..., Scene]) -> None:
    sc = make_scene(params=_STALE, clock=True)
    drv = sc.drivers[_DEV]
    sc.start_worker()
    until(lambda: drv.tick_count >= 2, 3.0, "два здоровых такта")
    _stop_manual_worker(sc)
    assert sc.clock is not None
    sc.clock.jump(3600.0)
    assert sc.plugin.cmd_device_remove({"device_id": _DEV})["status"] == "ok"
    entry = {
        "id": _DEV,
        "name": _DEV,
        "kind": "robot",
        "protocol": "delta_v2",
        "transport": _TCP,
        "params": dict(_STALE),
    }
    assert sc.plugin.cmd_device_sync_set({"devices": [entry], "origin": "recipe:b4"})["status"] == "ok"
    assert sc.readiness() == _NOT_CONNECTED
    bounded(sc.plugin._process_conn_queue)
    assert sc.readiness() == [], "до первого хода нового воркера возраст не проверяется"


def test_b4b_disconnect_then_connect_does_not_inherit_old_age(make_scene: Callable[..., Scene]) -> None:
    sc = make_scene(params=_STALE, clock=True)
    drv = sc.drivers[_DEV]
    sc.start_worker()
    until(lambda: drv.tick_count >= 2, 3.0, "два здоровых такта")
    _stop_manual_worker(sc)
    assert sc.clock is not None
    sc.clock.jump(3600.0)
    assert sc.plugin.cmd_device_disconnect({"device_id": _DEV})["status"] == "ok"
    bounded(sc.plugin._process_conn_queue)
    assert sc.plugin.cmd_device_connect({"device_id": _DEV})["status"] == "ok"
    bounded(sc.plugin._process_conn_queue)
    assert sc.readiness() == [], "до первого хода нового воркера возраст не проверяется"


def test_b4c_desired_false_then_true_does_not_inherit_old_age(make_scene: Callable[..., Scene]) -> None:
    """Воркер снят супервизором (``desired=False`` в ``_ensure_device_workers``), затем желание вернулось: до первого
    хода нового воркера возраст последнего такта старого не проверяется."""
    sc = make_scene(params=_STALE, clock=True)
    drv = sc.drivers[_DEV]
    sc.start_worker()
    until(lambda: drv.tick_count >= 2, 3.0, "два здоровых такта")
    _stop_manual_worker(sc)
    assert sc.clock is not None
    sc.clock.jump(3600.0)
    sc.plugin._desired_connected[_DEV] = False  # приватная запись: публичного «снять желание без disconnect» нет
    bounded(sc.plugin._ensure_device_workers)
    assert f"dev_{_DEV}" not in sc.ctx.worker_manager.workers, "обвязка: воркер должен быть снят"
    sc.plugin._desired_connected[_DEV] = True
    assert sc.readiness() == [], "до первого хода нового воркера возраст не проверяется"


# --------------------------------------------------------------------------------------------------
# Б5. Запас окна медленной паузы
# --------------------------------------------------------------------------------------------------


def test_b5_slow_pause_window_entered_to_release_is_measured_and_short(make_scene: Callable[..., Scene]) -> None:
    """Окно «команда вошла в драйвер -> тест отпустил» сценария 2.2a RED 11 (``readiness`` и ``cmd_device_list``
    за время медленной паузы): 20 прогонов; наибольшее окно — в сообщении; бюджет паузы 1,5 с держит окно < 1,0 с."""
    sc = make_scene(_THREE)
    drv = sc.drivers["r_v2"]
    drv.cmd_delay_s = 10.0
    windows: list[float] = []
    for _ in range(20):
        drv.cmd_gate.clear()
        before = drv.commands()
        box: dict[str, object] = {}

        def run_pause() -> None:
            try:
                sc.plugin.pause(sc.ctx)
            except BaseException as exc:  # noqa: BLE001
                box["error"] = exc

        thread = threading.Thread(target=run_pause, daemon=True, name="b5-pause")
        thread.start()
        until(lambda: drv.commands() > before, 5.0, "команда вошла в драйвер")
        entered = time.monotonic()
        assert sc.readiness() == []
        assert bounded(lambda: sc.plugin.cmd_device_list({}), 5.0)["status"] == "ok"
        windows.append(time.monotonic() - entered)
        drv.cmd_gate.set()
        thread.join(10.0)
        assert not thread.is_alive()
        assert "error" not in box, box
    print(f"b5: наибольшее окно entered -> release {max(windows):.4f} с из {len(windows)} прогонов")
    assert max(windows) < 1.0, f"наибольшее окно {max(windows):.3f} с из {len(windows)}"
