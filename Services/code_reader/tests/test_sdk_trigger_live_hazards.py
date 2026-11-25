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

from Services.code_reader.plugin import sdk_plugin
from Services.code_reader.tests.test_sdk_plugin import _bounded, _status
from Services.code_reader.tests.test_sdk_reader import make_reader  # noqa: F401
from Services.code_reader.tests.test_sdk_trigger import M, P, S, FakeNodeApi, _refused
from Services.code_reader.tests.test_sdk_trigger_live_contract import (  # noqa: F401
    REG,
    PREFIX,
    RESTART_TRIGGER_MODE,
    _grabbing_rig,
    _RefuseOpenNApi,
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


def _raise_once(monkeypatch, obj, name: str, exc: Exception) -> None:
    """Первый вызов `obj.name` бросает `exc`, следующие идут в настоящий метод (откат должен пройти)."""
    real = getattr(obj, name)
    raised: list[bool] = []

    def once(*args, **kwargs):
        if not raised:
            raised.append(True)
            raise exc
        return real(*args, **kwargs)

    monkeypatch.setattr(obj, name, once)


def test_set_trigger_error_reaches_last_error(make_rig, monkeypatch):
    rig = _grabbing_rig(make_rig, FakeNodeApi())
    _raise_once(monkeypatch, rig.plugin._reader, "set_trigger", RuntimeError("отказ читателя"))

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
    ("broken", "expected_tail"),
    [("set_trigger", " отказ: ValueError ok=True"), ("_trigger_from", " отказ: ValueError ok=-")],
    ids=["after_stop", "before_stop"],
)
def test_callback_never_raises_on_value_error(make_rig, monkeypatch, broken, expected_tail):
    api = FakeNodeApi()
    rig = _grabbing_rig(make_rig, api)
    # `_trigger_from` — разбор режима из регистра, первый шаг колбэка до остановки захвата.
    target = sdk_plugin if broken == "_trigger_from" else rig.plugin._reader
    _raise_once(monkeypatch, target, broken, ValueError("неизвестные ключи trigger"))

    # Колбэк зовём напрямую: через RegistersManager исключение глушится в WARNING, и «не бросает» не видно.
    _bounded(lambda: rig.plugin._on_trigger_update("trigger_mode", "On"), 10.0)

    assert rig.apply_msgs("ERROR") == [f"{RESTART_TRIGGER_MODE}{expected_tail}"]
    assert "trigger apply: field=trigger_mode отказ: ValueError" in rig.last_errors_seen()
    assert api.node_calls() == [], "отказавший разбор режима дошёл до узлов прибора"
    assert _status(rig)["device_held"] is True


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


# --------------------------------------------------------------------------
# 6. Ревизия дизайна (ревью стадии 5): намерение захвата, поздний get_frame, здоровье по фактам
# --------------------------------------------------------------------------

_RETAKE = "захват остановлен, возьмите прибор заново"


class _HangFrameApi(FakeNodeApi):
    """`get_frame` открытий из `hang_opens` (с 1) стоит на `gate`: `stop()` не укладывается в свой дедлайн."""

    def __init__(self, *args, hang_opens=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.hang_opens = set(hang_opens)
        self.open_number = 0
        self.hung = threading.Event()
        self.gate = threading.Event()

    def open(self, entry):
        self.open_number += 1
        return super().open(entry)

    def get_frame(self, h, timeout_ms):
        if self.open_number in self.hang_opens and not self.gate.is_set():
            self.hung.set()
            self.gate.wait(10.0)
        return super().get_frame(h, timeout_ms)


@pytest.fixture
def hang_api():
    made: list[_HangFrameApi] = []

    def factory(**kwargs) -> _HangFrameApi:
        made.append(_HangFrameApi(**kwargs))
        return made[-1]

    yield factory
    for api in made:
        api.gate.set()  # не оставляем висящих потоков захвата


def _nodes_written_after(api, open_number: int) -> list[tuple]:
    """Записи узлов начиная с открытия `open_number` (с 1)."""
    calls = api.calls
    start = [i for i, c in enumerate(calls) if c == ("open",)][open_number - 1]
    return [c for c in calls[start:] if c[0] in ("set_enum_str", "set_int")]


def _release_hung(rig: _Rig, api: _HangFrameApi) -> None:
    api.gate.set()
    _wait(lambda: _status(rig)["device_held"] is False, "поздний поток захвата вышел")


def _all_errors(rig: _Rig) -> list[str]:
    return [str(r["msg"]) for r in list(rig.services.logs) if r["level"] == "ERROR"]


def test_stop_timeout_inside_rollback_then_take_then_old_value(make_rig, hang_api):
    api = hang_api(fail=_refused(M), hang_opens={2})
    rig = _grabbing_rig(make_rig, api)

    assert rig.register_update("trigger_mode", "On")["success"] is True

    errors = rig.apply_msgs("ERROR")
    assert len(errors) == 1, errors
    assert errors[0].startswith(f"{RESTART_TRIGGER_MODE} restarted=True applied=False param_errors=TriggerMode: ")
    assert errors[0].endswith(f" fallback=old ok=False; {_RETAKE}")
    cause = [m for m in _all_errors(rig) if "applied=False param_errors=TriggerMode: " in m]
    assert len(cause) == 2 and cause[1] == errors[0], f"первая причина не записана до отката: {cause}"
    assert _status(rig)["last_error"] == f"trigger apply: field=trigger_mode applied=False; {_RETAKE}"
    assert _health_status(rig) == "degraded"

    _release_hung(rig, api)
    api.fail.clear()
    assert _bounded(lambda: rig.plugin.cmd_take_device({}), 10.0)["status"] == "ok"
    assert _nodes_written_after(api, 3) == [], "take_device взял прибор с отвергнутым режимом"
    assert _health_status(rig) == "degraded"  # регистр хранит «On», прибор в прежнем режиме
    assert _status(rig)["last_error"].startswith("trigger apply: field=trigger_mode applied=False")

    assert rig.register_update("trigger_mode", "")["success"] is True
    assert _health_status(rig) == "ok"
    assert _status(rig)["last_error"] == ""
    assert rig.opens() == 3


def test_release_with_late_thread_then_edit_does_not_regrab(make_rig, hang_api):
    api = hang_api(hang_opens={1})
    rig = _grabbing_rig(make_rig, api)
    assert api.hung.wait(5.0)
    assert _bounded(lambda: rig.plugin.cmd_release_device({}), 10.0)["device_held"] is True
    threading.Timer(0.5, api.gate.set).start()

    assert rig.register_update("trigger_mode", "On")["success"] is True

    _wait(lambda: _status(rig)["device_held"] is False, "поздний поток захвата вышел")
    time.sleep(0.3)
    assert rig.opens() == 1, "правка захватила отпущенный оператором прибор"
    assert _health_status(rig) == "ok"  # прибор отпущен оператором: здоровье не трогаем
    assert rig.apply_msgs() == [
        f"{RESTART_TRIGGER_MODE} restarted=False: захват не идёт, значение войдёт в следующий take_device"
    ]
    assert _bounded(lambda: rig.plugin.cmd_take_device({}), 10.0)["status"] == "ok"
    assert _nodes_written_after(api, 2) == [("set_enum_str", M, "On")]


def test_callback_after_shutdown_does_nothing(make_rig, hang_api):
    api = hang_api(hang_opens={1})
    rig = _grabbing_rig(make_rig, api)
    assert api.hung.wait(5.0)
    _bounded(lambda: rig.plugin.shutdown(rig.ctx), 10.0)
    rig.down = True
    threading.Timer(0.5, api.gate.set).start()

    _bounded(lambda: rig.plugin._on_trigger_update("trigger_mode", "On"), 10.0)  # колбэк, уже отданный в доставку

    _wait(lambda: _status(rig)["device_held"] is False, "поздний поток захвата вышел")
    time.sleep(0.3)
    assert rig.opens() == 1, "колбэк после shutdown снова взял прибор"
    assert rig.apply_msgs() == []


def test_stop_timeout_on_first_stop_asks_to_take_device_again(make_rig, hang_api):
    api = hang_api(hang_opens={1})
    rig = _grabbing_rig(make_rig, api)
    assert api.hung.wait(5.0)

    assert rig.register_update("trigger_mode", "On")["success"] is True

    assert rig.apply_msgs("ERROR") == [
        f"{RESTART_TRIGGER_MODE} restarted=False: захват не остановился в срок; {_RETAKE}"
    ]
    assert _status(rig)["last_error"] == f"trigger apply: field=trigger_mode {_RETAKE}"
    assert _health_status(rig) == "degraded"
    _release_hung(rig, api)
    time.sleep(0.3)
    assert rig.opens() == 1, "плагин сам повторил захват"

    assert _bounded(lambda: rig.plugin.cmd_take_device({}), 10.0)["status"] == "ok"
    assert _nodes_written_after(api, 2) == [("set_enum_str", M, "On")]
    assert _health_status(rig) == "ok"
    assert _status(rig)["last_error"] == ""


def test_old_value_written_while_grab_is_down_keeps_degraded(make_rig):
    api = _RefuseOpenNApi(refuse_open_numbers=(2, 3))
    rig = _grabbing_rig(make_rig, api)
    assert rig.register_update("trigger_mode", "On")["success"] is True
    expected = f"trigger apply: field=trigger_mode restarted=False; прежний режим не запущен; {_RETAKE}"
    assert _status(rig)["last_error"] == expected

    assert rig.register_update("trigger_mode", "")["success"] is True

    assert _health_status(rig) == "degraded", "здоровье снято, хотя захват не идёт"
    assert _status(rig)["last_error"] == expected
    assert _bounded(lambda: rig.plugin.cmd_take_device({}), 10.0)["status"] == "ok"
    assert _health_status(rig) == "ok"
    assert _status(rig)["last_error"] == ""


def test_node_refusal_at_take_device_after_stopped_edit_degrades(make_rig):
    api = FakeNodeApi(fail=_refused(M))
    rig = make_rig(api, auto_start=False)
    assert rig.register_update("trigger_mode", "On")["success"] is True
    assert _health_status(rig) == "ok"

    assert _bounded(lambda: rig.plugin.cmd_take_device({}), 10.0)["status"] == "ok"

    errors = _all_errors(rig)
    assert len(errors) == 1 and "param_errors=TriggerMode: " in errors[0], errors
    assert _health_status(rig) == "degraded"
    assert _status(rig)["last_error"].startswith("trigger apply: take_device: param_errors=TriggerMode: ")

    assert _bounded(lambda: rig.plugin.cmd_release_device({}), 10.0)["released"] is True
    assert _health_status(rig) == "degraded"  # отпущенный прибор здоровье не меняет
    api.fail.clear()
    assert _bounded(lambda: rig.plugin.cmd_take_device({}), 10.0)["status"] == "ok"
    assert _health_status(rig) == "ok"
    assert _status(rig)["last_error"] == ""


def test_old_refusal_of_another_node_does_not_block_the_edit(make_rig):
    api = FakeNodeApi(fail=_refused(P, "set_int"))
    rig = _grabbing_rig(make_rig, api, trigger_mode="On", trigger_source="SelfTrigger", trigger_period_ms=40)
    assert _health_status(rig) == "degraded"

    assert rig.register_update("trigger_source", "Line0")["success"] is True

    head = f"{PREFIX}trigger_source policy=restart"
    assert rig.apply_msgs("ERROR") == []
    warnings = rig.apply_msgs("WARNING")
    assert len(warnings) == 1, rig.apply_msgs()
    assert warnings[0].startswith(f"{head} restarted=True applied=True param_errors=TriggerSelfTriggerPeriod: ")
    assert rig.opens() == 2, "старый отказ другого узла откатил правку"
    assert ("set_enum_str", S, "Line0") in _nodes_written_after(api, 2)
    assert _health_status(rig) == "degraded"


def test_new_refusal_of_another_node_rolls_back(make_rig):
    api = FakeNodeApi()
    rig = _grabbing_rig(make_rig, api, trigger_mode="On", trigger_source="SelfTrigger", trigger_period_ms=40)
    api.fail.update(_refused(P, "set_int"))

    assert rig.register_update("trigger_source", "Line0")["success"] is True

    errors = rig.apply_msgs("ERROR")
    assert len(errors) == 1 and "applied=False param_errors=TriggerSelfTriggerPeriod: " in errors[0], errors
    assert rig.opens() == 3
    assert ("set_enum_str", S, "SelfTrigger") in _nodes_written_after(api, 3)
    assert _health_status(rig) == "degraded"


# --------------------------------------------------------------------------
# 7. Ревью стадии 5, раунд 2: хвосты last_error после удачного take; отказы прошлого сеанса
# --------------------------------------------------------------------------


def _boot_refused_period_rig(make_rig, api) -> _Rig:
    """Захват идёт, период собственного триггера отказан узлом с самого старта: процесс `degraded`."""
    rig = _grabbing_rig(make_rig, api, trigger_mode="On", trigger_source="SelfTrigger", trigger_period_ms=40)
    assert _health_status(rig) == "degraded"
    return rig


def test_take_after_both_opens_refused_drops_not_running_tails(make_rig):
    api = _RefuseOpenNApi(refuse_open_numbers=(2, 3))
    rig = _grabbing_rig(make_rig, api)
    assert rig.register_update("trigger_mode", "On")["success"] is True

    assert _bounded(lambda: rig.plugin.cmd_take_device({}), 10.0)["status"] == "ok"

    assert _status(rig)["device_state"] == "running"
    assert _status(rig)["device_held"] is True
    assert _status(rig)["last_error"] == "trigger apply: field=trigger_mode restarted=False"
    assert _health_status(rig) == "degraded"  # регистр хранит «On», прибор в прежнем режиме


def test_take_after_refusal_and_stop_timeout_drops_retake_tail(make_rig, hang_api):
    api = hang_api(fail=_refused(M), hang_opens={2})
    rig = _grabbing_rig(make_rig, api)
    assert rig.register_update("trigger_mode", "On")["success"] is True
    _release_hung(rig, api)
    api.fail.clear()

    assert _bounded(lambda: rig.plugin.cmd_take_device({}), 10.0)["status"] == "ok"

    assert _status(rig)["device_state"] == "running"
    assert _status(rig)["last_error"] == "trigger apply: field=trigger_mode applied=False"
    assert _health_status(rig) == "degraded"


def test_boot_refusal_stays_old_after_failed_opens(make_rig):
    api = _RefuseOpenNApi(fail=_refused(P, "set_int"), refuse_open_numbers=(2, 3))
    rig = _boot_refused_period_rig(make_rig, api)
    assert rig.register_update("trigger_source", "Line0")["success"] is True
    assert rig.opens() == 3
    assert _status(rig)["device_held"] is False

    assert rig.register_update("trigger_mode", "Off")["success"] is True

    warnings = rig.apply_msgs("WARNING")
    assert len(warnings) == 1, rig.apply_msgs()
    assert warnings[0].startswith(
        f"{PREFIX}trigger_mode policy=restart restarted=True applied=True param_errors=TriggerSelfTriggerPeriod: "
    )
    assert len(rig.apply_msgs("ERROR")) == 1, rig.apply_msgs()  # только ERROR первой правки
    assert rig.opens() == 4, "старый отказ периода откатил правку trigger_mode"
    assert ("set_enum_str", M, "Off") in _nodes_written_after(api, 4)
    assert _status(rig)["last_error"].startswith("trigger apply: param_errors=TriggerSelfTriggerPeriod: ")
    assert _health_status(rig) == "degraded"


def test_applied_with_old_refusals_replaces_applied_false_error(make_rig):
    api = FakeNodeApi(fail=_refused(P, "set_int"))
    rig = _boot_refused_period_rig(make_rig, api)
    api.fail.update(_refused(S))
    assert rig.register_update("trigger_source", "Line0")["success"] is True
    assert _status(rig)["last_error"] == "trigger apply: field=trigger_source applied=False"
    del api.fail[("set_enum_str", S)]  # источник снова пишется, период по-прежнему отказывает

    assert rig.register_update("trigger_source", "Line0")["success"] is True

    last_error = _status(rig)["last_error"]
    assert last_error.startswith("trigger apply: param_errors=TriggerSelfTriggerPeriod: "), last_error
    assert "applied=False" not in last_error
    assert "TriggerSource:" not in last_error
    assert last_error in rig.proxy.seen("last_error"), "замена не дошла до дерева состояния"
    assert _health_status(rig) == "degraded"
