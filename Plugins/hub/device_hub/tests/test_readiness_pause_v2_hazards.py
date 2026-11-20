"""Авторские hazard-тесты Task 2.2a2 S4b (Б1-Б5): запись снимка из потоков, стоп на каждом вызове pause, возраст с
первого такта, чистка возраста при remove/disconnect и запас окна медленной паузы.

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
from typing import Any

import pytest

from Plugins.hub.device_hub.plugin import TEXT_STATE_UNAVAILABLE
from Plugins.hub.device_hub.tests.test_readiness_and_pause import make_hub
from Plugins.hub.device_hub.tests.test_readiness_pause_v2 import (
    _DEV,
    _LINK_ERROR,
    _NOT_CONNECTED,
    _STALE_FAIL,
    _TCP,
    _THREE,
    Hang,
    Scene,
    Steps,
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
# Б2. Стоп на каждом вызове pause; пропуск только при стопе «в полёте» (решение владельца 2026-11-20)
# --------------------------------------------------------------------------------------------------


def _stops3(sc: Scene) -> tuple[int, int, int]:
    return (len(sc.drivers["r_v2"].stops()), len(sc.drivers["r_v1"].stops()), len(sc.drivers["belt"].stops()))


def test_b2_pause_after_failed_pause_and_start_resends_stop_to_every_device(make_scene: Callable[..., Scene]) -> None:
    """X1 ревью: pause упал (лента ответила ``error``) -> ЗАПУСТИТЬ -> через 2,0 с pause без ошибки: стоп ушёл ВСЕМ,
    роботам тоже (прежде повтор пропускал уже остановленных, и ОСТАНОВИТЬ «успешен» без команды роботам)."""
    sc = make_scene(_THREE)
    belt = sc.drivers["belt"]
    belt.reply = {"status": "error"}
    assert isinstance(sc.pause().error, RuntimeError)
    assert _stops3(sc) == (1, 1, 1)
    time.sleep(2.0)  # оператор: ЗАПУСТИТЬ, затем ОСТАНОВИТЬ
    belt.reply = {"status": "ok"}
    assert sc.pause().error is None
    assert _stops3(sc) == (2, 2, 2), "стоп должен уйти всем на втором вызове"


def test_b2_stop_still_in_flight_is_not_resent_and_resent_after_it_ends(make_scene: Callable[..., Scene]) -> None:
    """Стоп r_v2 из первого вызова ещё идёт (команда дольше бюджета): второй вызов не шлёт r_v2 вторую параллельную
    команду (счётчик остаётся 1), r_v1 и belt получают стоп (2, 2). После завершения стопа следующий вызов шлёт r_v2
    стоп снова."""
    sc = make_scene(_THREE)
    r_v2 = sc.drivers["r_v2"]
    r_v2.cmd_delay_s = 30.0  # держится, пока тест не откроет ``cmd_gate``
    assert isinstance(sc.pause().error, RuntimeError)
    assert _stops3(sc) == (1, 1, 1)
    assert isinstance(sc.pause().error, RuntimeError), "r_v2: предыдущий стоп ещё идёт — сбой вызова"
    assert _stops3(sc) == (1, 2, 2), "r_v2 не получает второй параллельный стоп; r_v1 и belt — получают"
    r_v2.cmd_gate.set()  # стоп r_v2 завершился
    until(lambda: sc.pause().error is None, 10.0, "стоп r_v2 завершён, pause без ошибки")
    assert len(r_v2.stops()) == 2, "после завершения стопа следующий вызов шлёт r_v2 стоп снова"


def test_b2_resume_then_pause_sends_stop_to_every_device(make_scene: Callable[..., Scene]) -> None:
    sc = make_scene(_THREE)
    assert sc.pause().error is None
    assert _stops3(sc) == (1, 1, 1)
    sc.resume()
    assert sc.pause().error is None
    assert _stops3(sc) == (2, 2, 2)


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


def test_b4d_zombie_tick_returning_after_disconnect_does_not_write_age(make_scene: Callable[..., Scene]) -> None:
    """Такт завис, воркер снят (disconnect), такт вернулся ПОЗДНО: снятый воркер возраст не пишет. Иначе после паузы
    дольше ``conn_stale_s`` и ``connect`` новый воркер получил бы чужой возраст -> ложное «нет обновления связи»."""
    sc = make_scene(params=_STALE, clock=True)
    hang = sc.hook(_DEV, Hang())
    sc.start_worker()
    sc.wait_readiness(_STALE_FAIL, 2.5)
    assert sc.plugin.cmd_device_disconnect({"device_id": _DEV})["status"] == "ok"
    bounded(sc.plugin._process_conn_queue)
    for evt in sc.stop_events:  # настоящий remove_worker взводит stop_evt воркера; ``FakeWorkerManager`` — нет
        evt.set()
    hang.release()  # зависший такт возвращается после снятия воркера
    for thread in sc.threads:
        thread.join(3.0)
    assert not any(t.is_alive() for t in sc.threads)
    assert sc.clock is not None
    sc.clock.jump(5.0)  # устройство отключено дольше порога
    assert sc.plugin.cmd_device_connect({"device_id": _DEV})["status"] == "ok"
    bounded(sc.plugin._process_conn_queue)
    assert sc.readiness() == [], "до первого хода нового воркера возраст не проверяется"


def test_b7_health_failure_in_tick_exception_branch_keeps_worker_and_fact(make_scene: Callable[..., Scene]) -> None:
    """Исключение такта + сбой ``health.report_error``: факт связи уже опубликован, поток воркера жив, следующий
    успешный такт освежает возраст (порог 1,0 с, часы +5 с)."""
    sc = make_scene(params={"poll_interval_s": 0.05, "conn_stale_s": 1.0}, clock=True)
    steps = sc.hook(_DEV, Steps(["raise", "ok"]))
    thread = sc.start_worker()
    steps.wait_first_entry()
    sc.drivers[_DEV].up = False
    sc.ctx.health.report_error.side_effect = RuntimeError("health boom")
    steps.step()
    assert thread.is_alive(), "воркер умер от сбоя health в ветке исключения такта"
    assert sc.readiness() == _NOT_CONNECTED, "факт связи должен быть опубликован до отчётов"
    sc.drivers[_DEV].up = True
    assert sc.clock is not None
    sc.clock.jump(5.0)
    steps.step()
    assert thread.is_alive()
    assert sc.readiness() == [], "успешный такт после сбоя health освежает возраст"


def test_b4e_zombie_tick_returning_after_remove_writes_nothing_to_store(make_scene: Callable[..., Scene]) -> None:
    """Такт завис, устройство снято (remove), такт вернулся ПОЗДНО: снятый воркер не пишет в стор ни ``conn``, ни
    ``status``/``stats``/``io_peek`` — иначе удалённое устройство воскресло бы в дереве состояния (``disconnected``)."""
    sc = make_scene(params={"poll_interval_s": 0.05})
    drv = sc.drivers[_DEV]
    sc.start_worker()
    until(lambda: drv.tick_count >= 2, 3.0, "два здоровых такта")
    hang = sc.hook(_DEV, Hang())
    seen = drv.tick_count
    until(lambda: drv.tick_count > seen, 3.0, "воркер вошёл в висящий такт")
    assert sc.plugin.cmd_device_remove({"device_id": _DEV})["status"] == "ok"
    for evt in sc.stop_events:  # настоящий remove_worker взводит stop_evt воркера; ``FakeWorkerManager`` — нет
        evt.set()
    prefix = f"devices.state.{_DEV}."
    state = sc.ctx.state_proxy

    def writes() -> list[str]:
        calls = list(state.set.call_args_list) + list(state.merge.call_args_list)
        return [c.args[0] for c in calls if c.args and str(c.args[0]).startswith(prefix)]

    n_before = len(writes())
    hang.release()  # зависший такт возвращается после снятия воркера
    for thread in sc.threads:
        thread.join(3.0)
    assert not any(t.is_alive() for t in sc.threads)
    assert writes()[n_before:] == [], "снятый воркер не должен писать в стор"


class _HangThenRaise(Hang):
    """Тик висит, после ``release()`` бросает (так ведёт себя такт, у которого remove закрыл драйвер)."""

    def __call__(self) -> None:
        self.gate.wait(30.0)
        raise RuntimeError("tick boom after remove")


def test_b4f_zombie_tick_raising_after_remove_writes_nothing_to_store(make_scene: Callable[..., Scene]) -> None:
    """Такт завис, устройство снято (remove), такт вернулся ИСКЛЮЧЕНИЕМ: ветка ``except`` снятого воркера не пишет
    в стор ни ``conn`` (связь оборвана), ни ``last_error``: удалённое устройство не должно воскреснуть в дереве."""
    sc = make_scene(params={"poll_interval_s": 0.05})
    drv = sc.drivers[_DEV]
    sc.start_worker()
    until(lambda: drv.tick_count >= 2, 3.0, "два здоровых такта")
    hang = sc.hook(_DEV, _HangThenRaise())
    seen = drv.tick_count
    until(lambda: drv.tick_count > seen, 3.0, "воркер вошёл в висящий такт")
    assert sc.plugin.cmd_device_remove({"device_id": _DEV})["status"] == "ok"
    drv.up = False  # remove закрыл драйвер
    for evt in sc.stop_events:  # настоящий remove_worker взводит stop_evt воркера; ``FakeWorkerManager`` — нет
        evt.set()
    prefix = f"devices.state.{_DEV}."
    state = sc.ctx.state_proxy

    def writes() -> list[str]:
        calls = list(state.set.call_args_list) + list(state.merge.call_args_list)
        return [c.args[0] for c in calls if c.args and str(c.args[0]).startswith(prefix)]

    n_before = len(writes())
    hang.release()
    for thread in sc.threads:
        thread.join(3.0)
    assert not any(t.is_alive() for t in sc.threads)
    assert writes()[n_before:] == [], "снятый воркер не должен писать в стор из ветки исключения"


def test_b10_state_write_failure_in_tick_exception_branch_keeps_worker(make_scene: Callable[..., Scene]) -> None:
    """Исключение такта + сбой записи ``conn`` в ветке исключения (``state_proxy.set`` бросает): поток воркера жив,
    следующий тик отрабатывает (ADR-PH-004: сбой отчёта не убивает поток воркера)."""
    sc = make_scene(params={"poll_interval_s": 0.05})
    steps = sc.hook(_DEV, Steps(["raise", "ok"]))
    thread = sc.start_worker()
    steps.wait_first_entry()
    sc.drivers[_DEV].up = False  # связь оборвана: ветка исключения публикует conn сразу
    sc.ctx.state_proxy.set.side_effect = RuntimeError("store boom")
    steps.step()
    assert thread.is_alive(), "воркер умер от сбоя записи conn в ветке исключения такта"
    sc.ctx.state_proxy.set.side_effect = None
    sc.drivers[_DEV].up = True
    steps.step()
    assert thread.is_alive()
    until(lambda: sc.last_conn_record() == {"conn": "connected", "ts": 2}, 2.0, "следующий тик опубликовал conn")


def _fail_scene(make_scene: Callable[..., Scene], outcomes: list[str], **params: Any) -> tuple[Scene, Steps]:
    sc = make_scene(params={"poll_interval_s": 0.05, **params})
    steps = sc.hook(_DEV, Steps(outcomes))
    sc.start_worker()
    steps.wait_first_entry()
    return sc, steps


def _tune_warnings(sc: Scene, key: str) -> list[str]:
    return [str(c) for c in sc.ctx.log_warning.call_args_list if key in str(c)]


def test_b8_tick_fails_limit_one_reports_link_error_from_first_exception(make_scene: Callable[..., Scene]) -> None:
    sc, steps = _fail_scene(make_scene, ["raise"], tick_fails_limit=1)
    steps.step()
    sc.wait_readiness(_LINK_ERROR, 1.5)
    assert _tune_warnings(sc, "tick_fails_limit") == []


def test_b8_tick_fails_limit_two_waits_for_second_exception(make_scene: Callable[..., Scene]) -> None:
    sc, steps = _fail_scene(make_scene, ["raise", "raise"], tick_fails_limit=2)
    steps.step()
    assert sc.readiness() == [], "после одного исключения при лимите 2 связь ещё не ошибочна"
    steps.step()
    sc.wait_readiness(_LINK_ERROR, 1.5)


@pytest.mark.parametrize("value", [0, -1, 2.5, "3", True, "abc"], ids=["zero", "neg", "float", "str3", "true", "abc"])
def test_b8_invalid_tick_fails_limit_falls_back_to_default_three_with_one_warning(
    make_scene: Callable[..., Scene], value: Any
) -> None:
    sc, steps = _fail_scene(make_scene, ["raise", "raise", "raise"], tick_fails_limit=value)
    steps.step()
    steps.step()
    assert sc.readiness() == [], "негодный лимит: умолчание 3, после двух исключений связь ещё не ошибочна"
    steps.permits.release()
    sc.wait_readiness(_LINK_ERROR, 1.5)
    assert len(_tune_warnings(sc, "tick_fails_limit")) == 1, _tune_warnings(sc, "tick_fails_limit")


def test_b8_absent_tick_fails_limit_is_silent_default_three(make_scene: Callable[..., Scene]) -> None:
    sc, steps = _fail_scene(make_scene, ["raise", "raise"])
    steps.step()
    steps.step()
    assert sc.readiness() == []
    assert _tune_warnings(sc, "tick_fails_limit") == []


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
