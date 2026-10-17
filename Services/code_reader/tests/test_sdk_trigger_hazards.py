# -*- coding: utf-8 -*-
# ruff: noqa: F811
"""Hazard-тесты Task 2.2a: гонки и порядок вокруг записи/возврата режима съёмки.

Приёмочные тесты тестера (``test_sdk_trigger.py``) проверяют последовательности вызовов в
одном потоке. Здесь — то, чего они не покрывают: ``stop()`` во время ``start()`` с записью
узлов, ``stop()`` из ``on_frame``, возврат при умершем ``get_frame``, повторный ``start()``
во время возврата, ``BaseException`` посреди записи. Блокирующие вызовы фейка держит ``Event``;
каждый вызов читателя из теста идёт в daemon-потоке с дедлайном (``_bounded``).
"""

from __future__ import annotations

import threading

import pytest

from Services.code_reader.core.sdk_reader import SdkCodeReader
from Services.code_reader.sdk.errors import E_GC_RANGE, SdkError
from Services.code_reader.tests.test_sdk_plugin import _bounded
from Services.code_reader.tests.test_sdk_reader import code, make_raw, make_reader, wait_until  # noqa: F401
from Services.code_reader.tests.test_sdk_trigger import FULL, M, P, START_FULL, STOP_FULL, FakeNodeApi, S

# Узлы записываются в порядке M, S, P; возврат — P, S, M. Литералы, не вывод из кода.
RESTORE_ONLY = [("set_int", P, 300), ("set_enum", S, 0), ("set_enum", M, 0)]


class GatedApi(FakeNodeApi):
    """Фейк, который встаёт на вызове ``gate_on = (метод, узел)`` до ``release.set()``."""

    def __init__(self, *args, gate_on: tuple[str, str], **kw):
        super().__init__(*args, **kw)
        self.gate_on = gate_on
        self.reached = threading.Event()
        self.release = threading.Event()

    def _enter(self, h, method: str, name: str = "", *args) -> None:
        super()._enter(h, method, name, *args)
        if (method, name) == self.gate_on:
            self.reached.set()
            self.release.wait(10.0)  # страховка: не повесить поток теста навсегда


class FrameApi(FakeNodeApi):
    """Фейк, отдающий один кадр с кодом на каждый ``get_frame`` (или бросающий ``get_frame_error``)."""

    get_frame_error: Exception | None = None

    def get_frame(self, h, timeout_ms):
        if self.get_frame_error is not None:
            raise self.get_frame_error
        import time

        time.sleep(0.005)
        return make_raw([code("QR-20MM")])


def _in_thread(fn) -> tuple[threading.Thread, dict]:
    """Запустить fn в daemon-потоке; результат/исключение — в словаре."""
    box: dict = {}

    def run() -> None:
        try:
            box["r"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["e"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, box


# --------------------------------------------------------------------------
# stop() во время start() с записью узлов
# --------------------------------------------------------------------------


def test_stop_during_start_waits_for_writes_then_restores_after_grabbing(make_reader):
    """Гонка: stop() приходит, пока start() внутри записи TriggerMode.

    stop() обязан дождаться конца start() (замок _life), и только потом поток захвата вернёт режим.
    Если бы stop() прошёл раньше, возврат стоял бы до start_grabbing (запись при не начатом захвате)
    или не случился бы вовсе (сессии ещё нет): прибор остался бы в самотриггере.
    """
    api = GatedApi(gate_on=("set_enum_str", M))
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    start_t, start_box = _in_thread(r.reader.start)
    try:
        assert api.reached.wait(5.0), "start() не дошёл до записи TriggerMode"
        stop_t, _ = _in_thread(r.reader.stop)
        stop_t.join(0.3)
        assert stop_t.is_alive(), "stop() вернулся, пока start() ещё пишет узлы"
        assert api.calls == START_FULL[:3]  # дальше записи режима start() не ушёл
    finally:
        api.release.set()
    start_t.join(5.0)
    stop_t.join(5.0)
    assert not start_t.is_alive() and not stop_t.is_alive()
    assert start_box["r"] is True
    assert wait_until(lambda: api.calls[-1] == ("close",), 3.0), api.calls
    assert api.calls == START_FULL + STOP_FULL
    assert api.values[101] == {M: 0, S: 0, P: 300}


# --------------------------------------------------------------------------
# stop() из on_frame
# --------------------------------------------------------------------------


def test_stop_from_on_frame_still_restores_before_close_without_deadlock(make_reader):
    """stop() из колбэка потока захвата не ждёт сам себя, а возврат всё равно идёт перед close."""
    api = FrameApi()
    holder: dict = {}

    def stop_once(_frame) -> None:
        holder["stopped"] = holder.get("stopped", 0) + 1
        if holder["stopped"] == 1:
            holder["r"].reader.stop()

    r = make_reader(api, trigger=FULL, timeout_ms=20, on_frame=stop_once)
    holder["r"] = r
    assert _bounded(r.reader.start, 5.0) is True
    assert wait_until(lambda: api.calls[-1:] == [("close",)], 5.0), api.calls
    assert api.calls == START_FULL + STOP_FULL
    assert api.count("close") == 1
    assert api.values[101] == {M: 0, S: 0, P: 300}
    assert wait_until(lambda: not r.reader.stats()["device_held"], 3.0)


# --------------------------------------------------------------------------
# Возврат при умершем get_frame
# --------------------------------------------------------------------------


def test_restore_is_attempted_when_get_frame_dies_and_first_cause_survives(make_reader):
    """Три ошибки get_frame подряд закрывают сессию сами (без stop()): возврат всё равно идёт.

    Возврат отказывает (прибор «умер»): его отказы растут в errors, но last_error остаётся
    первопричиной (get_frame), а не отказом возврата.
    """
    api = FrameApi()
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _bounded(r.reader.start, 5.0) is True
    # Отказы и смерть get_frame включаем после start(): запись узлов при старте должна пройти.
    api.fail[("set_int", P)] = SdkError(E_GC_RANGE, "x")
    api.fail[("set_enum", S)] = RuntimeError("dead")
    api.get_frame_error = SdkError(0x80020001, "MV_CODEREADER_GetOneFrame")
    assert wait_until(lambda: api.calls[-1:] == [("close",)], 5.0), api.calls
    assert api.calls == START_FULL + [("stop_grabbing",), *RESTORE_ONLY, ("close",)]
    assert api.values[101][M] == 0  # то, что отказа не получило, вернулось
    assert wait_until(lambda: "get_frame" in (r.reader.stats()["last_error"] or ""), 3.0), r.reader.stats()
    s = r.reader.stats()
    assert s["state"] == "error"
    # 2 ошибки get_frame (note_error) + итоговая (count_error) + 2 отказа возврата
    assert s["errors"] == 5


# --------------------------------------------------------------------------
# Повторный start() и дедлайн stop() во время возврата
# --------------------------------------------------------------------------


def test_start_during_restore_is_refused_and_stop_deadline_holds(make_reader):
    """Пока поток захвата возвращает режим (блок на set_enum TriggerMode), второй start() отказывает,
    второго open нет, а stop() с коротким дедлайном возвращается вовремя; прибор считается занятым."""
    api = GatedApi(gate_on=("set_enum", M))
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _bounded(r.reader.start, 5.0) is True
    try:
        _bounded(lambda: r.reader.stop(0.2), 5.0)  # дедлайн stop() держится, хотя поток завис в возврате
        assert api.reached.wait(5.0), "поток захвата не дошёл до возврата"
        assert r.reader.stats()["device_held"] is True
        calls_before = list(api.calls)

        assert _bounded(r.reader.start, 5.0) is False  # не True и не второй open поверх живого handle
        assert api.calls == calls_before
        assert api.count("open") == 1
        assert ("close",) not in api.calls  # close ждёт конца возврата
    finally:
        api.release.set()
    assert wait_until(lambda: api.calls[-1:] == [("close",)], 5.0), api.calls
    assert api.calls == START_FULL + STOP_FULL
    assert wait_until(lambda: not r.reader.stats()["device_held"], 3.0)

    # После возврата прибор снова доступен, и последовательность та же.
    api.release.clear()
    api.gate_on = ("", "")
    n = len(api.calls)
    assert _bounded(r.reader.start, 5.0) is True
    _bounded(r.reader.stop, 5.0)
    assert wait_until(lambda: api.calls[-1:] == [("close",)] and len(api.calls) > n, 5.0)
    assert api.calls[n:] == START_FULL + STOP_FULL


# --------------------------------------------------------------------------
# Отказы возврата
# --------------------------------------------------------------------------


def test_every_restore_and_stop_grabbing_failing_still_attempts_all_and_closes(make_reader):
    """stop_grabbing упал, потом упали все три возврата: попытки всё равно все, close ровно один."""
    api = FakeNodeApi()
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _bounded(r.reader.start, 5.0) is True
    api.fail[("stop_grabbing", "")] = RuntimeError("sg")
    api.fail[("set_int", P)] = RuntimeError("p")
    api.fail[("set_enum", S)] = RuntimeError("s")
    api.fail[("set_enum", M)] = RuntimeError("m")
    errors_before = r.reader.stats()["errors"]
    cb_before = len(r.errors)
    _bounded(r.reader.stop, 5.0)
    assert api.calls == START_FULL + [("stop_grabbing",), *RESTORE_ONLY, ("close",)]
    assert r.reader.stats()["errors"] == errors_before + 4
    assert len(r.errors) == cb_before + 4
    assert api.count("close") == 1


def test_restore_failure_of_start_grabbing_path_is_reported_and_close_is_called(make_reader):
    """Путь отказа start_grabbing: возврат узла отказал -> errors +1, on_error зван, остальные и close идут."""
    api = FakeNodeApi(fail={("start_grabbing", ""): SdkError(0x80020001, "sg"), ("set_enum", S): RuntimeError("s")})
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _bounded(r.reader.start, 5.0) is False
    assert api.calls == START_FULL + [*RESTORE_ONLY, ("close",)]
    assert api.count("close") == 1
    # старт-путь сообщает и о возврате, и об отказе start_grabbing
    assert any("возврат TriggerSource" in m for m in r.errors), r.errors
    assert r.reader.stats()["errors"] == 1


# --------------------------------------------------------------------------
# Непредвиденные исключения при записи
# --------------------------------------------------------------------------


class _Abort(BaseException):
    """Не Exception: имитирует KeyboardInterrupt/SystemExit посреди start()."""


def test_base_exception_during_node_write_restores_written_and_closes_handle(make_reader):
    """BaseException на записи периода: start() его не глотает, но записанное возвращено и handle закрыт."""
    api = FakeNodeApi(fail={("set_int", P): _Abort()})
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    with pytest.raises(_Abort):
        _bounded(r.reader.start, 5.0)
    assert api.calls == [
        ("open",),
        ("get_enum", M),
        ("set_enum_str", M, "On"),
        ("get_enum", S),
        ("set_enum_str", S, "SelfTrigger"),
        ("get_int", P),
        ("set_int", P, 40),
        ("set_enum", S, 0),
        ("set_enum", M, 0),
        ("close",),
    ]
    assert "start_grabbing" not in [c[0] for c in api.calls]
    assert api.values[101] == {M: 0, S: 0, P: 300}
    assert r.reader.stats()["state"] == "stopped"  # читатель не застрял в "running"


def test_type_error_from_set_int_is_contained_and_value_not_leaked(make_reader):
    """Нечисловой период: TypeError от набора на узле ловится; в param_errors только имя типа."""
    api = FakeNodeApi()
    r = make_reader(api, trigger={"trigger_mode": "On", "trigger_source": "SelfTrigger", "trigger_period_ms": "секрет"})
    assert _bounded(r.reader.start, 5.0) is True
    pe = r.reader.stats()["param_errors"]
    assert pe == {P: "TypeError"}
    assert "секрет" not in pe[P]
    _bounded(r.reader.stop, 5.0)
    # период не записан -> не возвращается; режим и источник возвращены
    assert api.calls[-4:] == [("stop_grabbing",), ("set_enum", S, 0), ("set_enum", M, 0), ("close",)]
    assert r.reader.stats()["errors"] == 0


# --------------------------------------------------------------------------
# Валидация и очистка
# --------------------------------------------------------------------------


@pytest.mark.parametrize("trigger", [{"trigger_mod": "On"}, {"trigger_mode": "On", "exposure_time": 1}])
def test_unknown_trigger_key_raises_value_error_before_touching_device(trigger):
    api = FakeNodeApi()
    with pytest.raises(ValueError):
        SdkCodeReader(lambda f: None, api=api, trigger=trigger)
    assert api.calls == []


def test_second_start_while_running_keeps_param_errors(make_reader):
    """start() на идущем захвате возвращает True БЕЗ очистки: ошибки текущего запуска не теряются."""
    api = FakeNodeApi(fail={("set_enum_str", M): SdkError(E_GC_RANGE, "x")})
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _bounded(r.reader.start, 5.0) is True
    before = r.reader.stats()["param_errors"]
    assert set(before) == {M, S, P}
    n = len(api.calls)
    assert _bounded(r.reader.start, 5.0) is True
    assert len(api.calls) == n  # ни одного нового вызова
    assert r.reader.stats()["param_errors"] == before


def test_param_errors_reset_even_when_next_start_fails_to_find_device(make_reader):
    """Старые ошибки узлов не переживают следующий start(), даже если прибор не нашёлся."""
    api = FakeNodeApi(fail={("set_enum_str", M): SdkError(E_GC_RANGE, "x")})
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _bounded(r.reader.start, 5.0) is True
    assert r.reader.stats()["param_errors"]
    _bounded(r.reader.stop, 5.0)
    assert wait_until(lambda: not r.reader.stats()["device_held"], 3.0)
    api.entries.clear()
    assert _bounded(r.reader.start, 5.0) is False
    assert r.reader.stats()["state"] == "not_found"
    assert r.reader.stats()["param_errors"] == {}


# --------------------------------------------------------------------------
# Раунд 2 ревью: M1 (close при любом выходе из возврата), M2 (колбэк после close),
# M3 (значение в тексте отказа), M4 (нечитаемое исходное), замеры в логе
# --------------------------------------------------------------------------


def test_keyboard_interrupt_in_restore_on_start_failure_still_closes_once_and_tries_rest(make_reader):
    """M1: start_grabbing упал (RuntimeError), возврат TriggerSource бросил KeyboardInterrupt.

    close обязан быть ровно один (handle не утекает), возврат P и M всё равно пробован, KeyboardInterrupt
    не проглочен.
    """
    api = FakeNodeApi(fail={("start_grabbing", ""): RuntimeError("sg"), ("set_enum", S): KeyboardInterrupt()})
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    with pytest.raises(KeyboardInterrupt):
        _bounded(r.reader.start, 5.0)
    assert api.calls == START_FULL + [*RESTORE_ONLY, ("close",)]
    assert api.count("close") == 1


class _BlockingOnError:
    """on_error, который встаёт до ``release``; ``reached`` — колбэк вызван."""

    def __init__(self) -> None:
        self.reached = threading.Event()
        self.release = threading.Event()

    def __call__(self, _msg: str) -> None:
        self.reached.set()
        self.release.wait(10.0)


def test_hanging_on_error_does_not_delay_close_after_restore_failure(make_reader):
    """M2: отказ возврата зовёт on_error, а он завис. close уже должен быть вызван (прибор не держится колбэком)."""
    hang = _BlockingOnError()
    api = FakeNodeApi()
    r = make_reader(api, trigger=FULL, timeout_ms=20, on_error=hang)
    assert _bounded(r.reader.start, 5.0) is True
    api.fail[("set_enum", S)] = RuntimeError("boom")
    try:
        _bounded(lambda: r.reader.stop(0.2), 5.0)
        assert hang.reached.wait(5.0), "on_error не вызван"
        assert api.calls == START_FULL + [("stop_grabbing",), *RESTORE_ONLY, ("close",)]
    finally:
        hang.release.set()
    assert wait_until(lambda: not r.reader.stats()["device_held"], 3.0)


def test_raising_on_error_does_not_skip_close(make_reader):
    """M2: on_error бросает при отказе stop_grabbing и возврата — close всё равно ровно один, последним."""

    def bad(_msg: str) -> None:
        raise RuntimeError("callback")

    api = FakeNodeApi()
    r = make_reader(api, trigger=FULL, timeout_ms=20, on_error=bad)
    assert _bounded(r.reader.start, 5.0) is True
    api.fail[("stop_grabbing", "")] = RuntimeError("sg")
    api.fail[("set_int", P)] = RuntimeError("p")
    _bounded(r.reader.stop, 5.0)
    assert wait_until(lambda: not r.reader.stats()["device_held"], 3.0)
    assert api.calls == START_FULL + [("stop_grabbing",), *RESTORE_ONLY, ("close",)]
    assert api.count("close") == 1


def test_restore_failure_text_carries_value_to_return_by_hand(make_reader):
    """M3: текст отказа возврата называет узел и значение, которое надо вернуть руками."""
    api = FakeNodeApi(initial={101: {S: 5, P: 123}})
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _bounded(r.reader.start, 5.0) is True
    api.fail[("set_int", P)] = RuntimeError("p")
    api.fail[("set_enum", M)] = RuntimeError("m")
    _bounded(r.reader.stop, 5.0)
    assert any(m.startswith("возврат TriggerSelfTriggerPeriod -> 123:") for m in r.errors), r.errors
    assert any(m.startswith("возврат TriggerMode -> 0:") for m in r.errors), r.errors
    assert r.reader.stats()["last_error"].startswith("возврат TriggerMode -> 0:")


class _NoneOriginalApi(FakeNodeApi):
    """get_enum(TriggerMode) отвечает, но ``cur`` пуст."""

    def get_enum(self, h, name):
        res = super().get_enum(h, name)
        if name == M:
            res["cur"] = None
        return res


def test_none_original_is_not_written_and_not_restored(make_reader):
    """M4: исходное None -> узел не пишется, param_errors непуст, потомки пропущены, set_*(None) нет."""
    api = _NoneOriginalApi()
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _bounded(r.reader.start, 5.0) is True
    pe = r.reader.stats()["param_errors"]
    assert pe[M] == "ValueError"
    assert pe[S].startswith("пропущен") and pe[P].startswith("пропущен")
    _bounded(r.reader.stop, 5.0)
    assert api.calls == [
        ("open",),
        ("get_enum", M),
        ("start_grabbing",),
        ("stop_grabbing",),
        ("close",),
    ]
    assert not any(c[0].startswith("set_") for c in api.calls)
    assert api.values[101] == {M: 0, S: 0, P: 300}


def _capture_info(monkeypatch):
    """Подменить логгер читателя записывающей заглушкой: тест не зависит от уровней и каналов логирования проекта."""
    from Services.code_reader.core import sdk_reader

    records: list[str] = []

    class _Rec:
        def _add(self, msg, *args, **_kw) -> None:
            records.append(msg % args if args else msg)

        info = warning = error = debug = _add

        def exception(self, msg, *args, **_kw) -> None:
            self._add(msg, *args)

    monkeypatch.setattr(sdk_reader, "_log", _Rec())
    return records, lambda: None


def test_release_logs_durations_for_stop_grabbing_and_each_restore(make_reader, monkeypatch):
    """Замеры для опыта на приборе: stop_grabbing, каждая запись возврата и вход в возврат попадают в INFO-лог."""
    import re

    records, detach = _capture_info(monkeypatch)
    try:
        api = FakeNodeApi(delay_s=0.02)
        r = make_reader(api, trigger=FULL, timeout_ms=20)
        assert _bounded(r.reader.start, 10.0) is True
        _bounded(r.reader.stop, 10.0)
        assert wait_until(lambda: not r.reader.stats()["device_held"], 3.0)
    finally:
        detach()
    text = "\n".join(records)
    sg = re.search(r"stop_grabbing мс=(\d+)", text)
    assert sg and int(sg.group(1)) >= 15, text
    for node in (P, S, M):
        m = re.search(rf"возврат {node} мс=(\d+)", text)
        assert m and int(m.group(1)) >= 15, (node, text)
    entry = re.search(r"от stop\(\) до начала мс=(\d+)", text)
    assert entry and int(entry.group(1)) >= 15, text  # stop_grabbing 20 мс лежит между stop() и началом возврата


def test_start_failure_path_logs_restore_durations(make_reader, monkeypatch):
    records, detach = _capture_info(monkeypatch)
    try:
        api = FakeNodeApi(delay_s=0.02, fail={("start_grabbing", ""): SdkError(0x80020001, "sg")})
        r = make_reader(api, trigger=FULL, timeout_ms=20)
        assert _bounded(r.reader.start, 10.0) is False
    finally:
        detach()
    text = "\n".join(records)
    for node in (P, S, M):
        assert f"возврат {node} мс=" in text, text
