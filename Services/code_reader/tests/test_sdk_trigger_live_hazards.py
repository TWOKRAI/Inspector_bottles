# -*- coding: utf-8 -*-
# ruff: noqa: F811
"""Тесты-ловушки W1-b (автор кода): живая правка режима съёмки считывателя SDK — гонки, замок, повторная конфигурация.

Приёмка контракта — слепой `test_sdk_trigger_live_contract.py`; здесь свойства, которые он не держит:
подписка не удваивается при повторном `configure`; `take_device` / `shutdown` ждут идущий колбэк (замок
`_trigger_lock`); отказ `set_trigger` доходит до `last_error` и журнала, а колбэк не бросает; отказ правки
делает процесс `degraded`, удачная правка снимает деградацию; отказ разбора в `set_trigger` оставляет прежний
режим читателя.

Стенд — `_Rig` из контракта (настоящие плагин + RegistersManager + PluginOrchestrator + читатель на `FakeNodeApi`).
Всё, что может зависнуть, идёт в daemon-потоке с дедлайном (pytest-timeout не установлен).
"""

from __future__ import annotations

import threading
import time

import pytest

from Services.code_reader.tests.test_sdk_plugin import _bounded, _status
from Services.code_reader.tests.test_sdk_reader import make_reader  # noqa: F401
from Services.code_reader.tests.test_sdk_trigger import M, FakeNodeApi, _refused
from Services.code_reader.tests.test_sdk_trigger_live_contract import (  # noqa: F401
    REG,
    RESTART_TRIGGER_MODE,
    _grabbing_rig,
    _Rig,
    _wait,
    make_rig,
)

__all__ = []


class _GatedStopApi(FakeNodeApi):
    """`FakeNodeApi`, у которого первый `stop_grabbing` после `arm()` встаёт на событии (поток захвата в `_release`).

    Пока он стоит, `SdkCodeReader.stop()` из колбэка ждёт `join` потока (до `timeout + timeout_ms` = 2,02 с),
    то есть колбэк живой правки держит `_trigger_lock` посреди остановки.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.armed = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def stop_grabbing(self, h):
        if self.armed and not self.entered.is_set():
            self.entered.set()
            self.release.wait(10.0)
        super().stop_grabbing(h)


def _update_in_thread(rig: _Rig, field: str, value) -> tuple[threading.Thread, dict]:
    """`register_update` из отдельного daemon-потока без ожидания ответа: ответ появится в `box["result"]`."""
    box: dict = {}

    def system_thread() -> None:
        box["result"] = rig.orch._on_register_update({"data": {"register": REG, "field": field, "value": value}})

    thread = threading.Thread(target=system_thread, name="system_sim", daemon=True)
    thread.start()
    return thread, box


def _call_in_thread(fn) -> tuple[threading.Thread, dict]:
    box: dict = {}

    def run() -> None:
        try:
            box["r"] = fn()
        except BaseException as exc:  # noqa: BLE001 — отдаём в поток теста
            box["e"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, box


def _health_status(rig: _Rig) -> str:
    status = rig.ctx.health.status
    return str(getattr(status, "value", status))


# --------------------------------------------------------------------------
# 1. Повторный configure не удваивает подписку
# --------------------------------------------------------------------------


def test_reconfigure_does_not_double_subscriptions(make_rig):
    rig = make_rig(FakeNodeApi(), auto_start=False)
    rig.plugin.configure(rig.ctx)  # второй configure того же плагина на том же RegistersManager

    assert rig.register_update("trigger_mode", "On")["success"] is True

    stopped_line = f"{RESTART_TRIGGER_MODE} restarted=False: захват не идёт, значение войдёт в следующий take_device"
    _wait(lambda: stopped_line in rig.apply_msgs(), "строка применения после правки")
    time.sleep(0.2)  # лишний подписчик дописал бы вторую строку; события «ничего больше» нет, ждём окно
    assert rig.apply_msgs() == [stopped_line], "правка вызвала колбэк не один раз: подписка удвоилась"


# --------------------------------------------------------------------------
# 2. Параллельные take_device / shutdown ждут идущий колбэк
# --------------------------------------------------------------------------


def test_concurrent_take_device_waits_for_callback(make_rig):
    api = _GatedStopApi()
    rig = _grabbing_rig(make_rig, api)
    api.armed = True

    updater, update_box = _update_in_thread(rig, "trigger_mode", "On")
    assert api.entered.wait(5.0), "колбэк не дошёл до остановки захвата"
    taker, take_box = _call_in_thread(lambda: rig.plugin.cmd_take_device({}))
    time.sleep(0.3)  # take_device без замка вернулся бы сразу («предыдущий поток ещё не завершился»)
    assert taker.is_alive(), f"take_device не дождался колбэка и вернул {take_box!r}"

    api.release.set()
    updater.join(10.0)
    taker.join(10.0)

    assert not updater.is_alive() and not taker.is_alive(), "колбэк или take_device завис"
    assert update_box["result"]["success"] is True
    assert take_box["r"]["status"] == "ok", take_box
    assert rig.opens() == 2, "take_device открыл прибор второй раз поверх перезапуска"
    assert rig.apply_msgs("INFO") == [f"{RESTART_TRIGGER_MODE} restarted=True applied=True"]
    assert rig.apply_msgs("ERROR") == []
    assert ("set_enum_str", M, "On") in api.calls
    assert _status(rig)["device_held"] is True


def test_shutdown_waits_for_inflight_callback(make_rig):
    api = _GatedStopApi()
    rig = _grabbing_rig(make_rig, api)
    api.armed = True

    updater, update_box = _update_in_thread(rig, "trigger_mode", "On")
    assert api.entered.wait(5.0), "колбэк не дошёл до остановки захвата"
    closer, close_box = _call_in_thread(lambda: rig.plugin.shutdown(rig.ctx))
    time.sleep(0.3)

    api.release.set()
    updater.join(10.0)
    closer.join(10.0)
    rig.down = True  # shutdown уже выполнен этим тестом

    assert not updater.is_alive() and not closer.is_alive(), "колбэк или shutdown завис"
    assert "e" not in close_box, close_box
    assert update_box["result"]["success"] is True
    assert rig.opens() == 2, "колбэк не довёл перезапуск до конца"
    assert _status(rig)["device_held"] is False, "shutdown прошёл посреди перезапуска: захват пережил его"


# --------------------------------------------------------------------------
# 3. Отказ set_trigger: last_error, журнал, ok захвата; колбэк не бросает
# --------------------------------------------------------------------------


def test_set_trigger_error_reaches_last_error(make_rig, monkeypatch):
    rig = _grabbing_rig(make_rig, FakeNodeApi())

    def refusing_set_trigger(trigger):
        raise RuntimeError("режим съёмки меняется только при остановленном захвате")

    monkeypatch.setattr(rig.plugin._reader, "set_trigger", refusing_set_trigger)

    assert rig.register_update("trigger_mode", "On")["success"] is True

    _wait(lambda: len(rig.apply_msgs("ERROR")) == 1, "ERROR-строка отказа")
    errors = rig.apply_msgs("ERROR")
    assert errors[0] == f"{RESTART_TRIGGER_MODE} отказ: RuntimeError ok=True"
    expected = "trigger apply: field=trigger_mode отказ: RuntimeError"
    _wait(lambda: expected in rig.last_errors_seen(), f"last_error == {expected!r}")
    status = _status(rig)
    assert status["device_held"] is True, "прежний режим не вернулся в захват после отказа"
    assert rig.opens() == 2  # остановка и возврат захвата с прежним режимом
    assert _health_status(rig) == "degraded"


@pytest.mark.parametrize(
    ("auto_start", "expected_tail"),
    [(True, " отказ: ValueError ok=True"), (False, " отказ: ValueError ok=-")],
    ids=["held", "not_held"],
)
def test_callback_never_raises_on_value_error(make_rig, monkeypatch, auto_start, expected_tail):
    api = FakeNodeApi()
    rig = _grabbing_rig(make_rig, api) if auto_start else make_rig(api, auto_start=False)

    def refusing_set_trigger(trigger):
        raise ValueError("неизвестные ключи trigger")

    monkeypatch.setattr(rig.plugin._reader, "set_trigger", refusing_set_trigger)

    # Колбэк зовём напрямую: через RegistersManager исключение глушится в WARNING, и «не бросает» не видно.
    _bounded(lambda: rig.plugin._on_trigger_update("trigger_mode", "On"), 10.0)

    errors = rig.apply_msgs("ERROR")
    assert errors == [f"{RESTART_TRIGGER_MODE}{expected_tail}"]
    expected = "trigger apply: field=trigger_mode отказ: ValueError"
    assert expected in rig.last_errors_seen()
    assert api.node_calls() == [], "отказавший разбор режима дошёл до узлов прибора"


# --------------------------------------------------------------------------
# 4. Деградация: отказ правки — degraded, удачная правка — снята
# --------------------------------------------------------------------------


def _refused_then_ready(make_rig) -> tuple[_Rig, FakeNodeApi]:
    """Захват идёт, `trigger_mode "On"` отказан узлом и откачен: процесс `degraded`, регистр хранит «On»."""
    api = FakeNodeApi(fail=_refused(M))
    rig = _grabbing_rig(make_rig, api)
    assert rig.register_update("trigger_mode", "On")["success"] is True
    _wait(lambda: rig.opens() == 3 and len(rig.apply_msgs("ERROR")) == 1, "перезапуск, откат и ERROR-строка")
    _wait(lambda: _health_status(rig) == "degraded", "процесс degraded после отказа узла")
    return rig, api


def test_failed_apply_degrades_and_next_successful_restart_clears(make_rig):
    rig, api = _refused_then_ready(make_rig)
    api.fail.clear()  # узел больше не отказывает

    assert (
        rig.register_update("trigger_mode", "On")["success"] is True
    )  # то же значение регистра, режим прибора прежний

    _wait(lambda: rig.opens() == 4, "перезапуск с записью режима")
    _wait(lambda: _health_status(rig) == "ok", "деградация снята удачной правкой")
    assert f"{RESTART_TRIGGER_MODE} restarted=True applied=True" in rig.apply_msgs("INFO")
    assert api.values[101][M] == 1  # On на приборе


def test_failed_apply_degradation_cleared_by_return_to_old_value(make_rig):
    rig, _api = _refused_then_ready(make_rig)

    assert rig.register_update("trigger_mode", "")["success"] is True  # регистр снова совпал с прибором

    _wait(lambda: _health_status(rig) == "ok", "деградация снята возвратом к прежнему значению")
    assert rig.opens() == 3


# --------------------------------------------------------------------------
# 5. set_trigger: отказ разбора не трогает прежний режим читателя
# --------------------------------------------------------------------------


def test_set_trigger_value_error_keeps_previous_mode(make_reader):
    api = FakeNodeApi()
    r = make_reader(api, timeout_ms=20)
    r.reader.set_trigger({"trigger_mode": "On"})

    with pytest.raises(ValueError):
        r.reader.set_trigger({"trigger_mode": "Off", "bogus_key": 1})

    assert _bounded(r.reader.start, 10.0) is True
    writes = [c for c in api.calls if c[0].startswith("set_")]
    assert writes == [("set_enum_str", "TriggerMode", "On")], "после отказа разбора пишется не прежний режим"
    _bounded(r.reader.stop, 10.0)
