# -*- coding: utf-8 -*-
"""Слепая приёмка Task 2.2c (system-run-state): хук `CameraDevicePlugin.readiness(ctx)`.

Написана ДО кода по выдержке acceptance (таблица «состояние сеанса -> причина») и по контракту хука
`ProcessModulePlugin.readiness` (`plugins/base.py`): список `{"severity", "reason"}`, блокируют `failure` и
`check_function`; хук быстрый, без замков, без IO, не бросает; текст причины — короткий, БЕЗ значений.

Таблица (литералы; один элемент либо пусто):

    grabbing                          -> []
    opening                           -> check_function  "камера открывается"      (БЛОКИРУЕТ)
    stopping                          -> out_of_spec     "камера останавливается"
    busy                              -> failure         "камера занята"
    not_found                         -> failure         "камера не найдена"
    error                             -> failure         "ошибка камеры"           (текст last_error в reason НЕ входит)
    idle | closed  + auto_start       -> check_function  "камера не запущена"      (и после release_device оператора)
    idle | closed  + not auto_start   -> []
    session is None                   -> как idle
    closed + device_held=True         -> как closed (два чтения не атомарны, пара терпится)
    любое другое состояние            -> failure         "состояние камеры неизвестно"

Каркас. Настоящий плагин над фейковым портом (как в `test_plugin_base.py`: `PluginContext` над
`MockProcessServices`, настоящий `WorkerManager`). Два вида проверок:
  * таблица и сигнатура ответа — на ЗАГЛУШКЕ сеанса `_StubSession` (подмена `plugin._session`: единственный способ
    загнать сеанс в `stopping` и в «неизвестное состояние» без правки кода сеанса; заглушка отдаёт только `state`,
    `device_held`, `last_error`, а `params`/`params_status`/`param_errors` — берущие замок чтения — ЛОМАЮТ тест);
  * сквозные проверки — на НАСТОЯЩЕМ сеансе с фейковым портом (`take_device`, `release_device`, отказы открытия).
Вызов `readiness`, который может заблокироваться, идёт в daemon-потоке с дедлайном `join` 2 с.
Ожидаемые значения — литералы, не выведенные из кода.

# ASSUMPTION: текст причины совпадает с литералом БЕЗ префикса вида «camera_device: » (в отличие от ml_inference);
#   если реализация добавит префикс, тесты на равенство текста упадут — это вопрос к выдержке, не к тестам.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.testing.fake_port import make_port

PROCESS_NAME = "cam_readiness"
_DEADLINE_S = 2.0
_SECRET = "SN-12345 /dev/x"
_FAKE_CFG = {"camera_id": 3, "device_select": "serial", "device_serial": "FAKE-0001"}

# Литералы причин (acceptance).
NOT_STARTED = ("check_function", "камера не запущена")
OPENING = ("check_function", "камера открывается")
STOPPING = ("out_of_spec", "камера останавливается")
BUSY = ("failure", "камера занята")
NOT_FOUND = ("failure", "камера не найдена")
ERROR = ("failure", "ошибка камеры")
UNKNOWN = ("failure", "состояние камеры неизвестно")


# ---------------------------------------------------------------------------------------------- #
# Каркас
# ---------------------------------------------------------------------------------------------- #


def _bounded(fn: Callable[[], Any], seconds: float = 10.0) -> Any:
    """Вызов в daemon-потоке с дедлайном: зависший вызов -> падение теста, а не зависание набора."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробрасываем в поток теста как есть
            box["exc"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), f"вызов не вернулся за {seconds} с (завис / ждёт замок)"
    if "exc" in box:
        raise box["exc"]
    return box.get("value")


class _Rig:
    """Настоящий плагин над фейковым портом; `configure` вызван, `start` — НЕТ (порт сам не открывается)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, cfg: dict, port: Any) -> None:
        self.port = port
        monkeypatch.setattr(plugin_base, "create_port", lambda driver: port)
        services = MockProcessServices(name=PROCESS_NAME, config=cfg)
        self.wm = WorkerManager("test_cam_readiness")
        services.worker_manager = self.wm
        self.ctx = PluginContext(services=services, config=cfg, plugin_name=CameraDevicePlugin.name)
        self.plugin = CameraDevicePlugin()
        self.plugin.configure(self.ctx)

    def readiness(self, seconds: float = _DEADLINE_S) -> Any:
        return _bounded(lambda: self.plugin.readiness(self.ctx), seconds)

    def pairs(self) -> list[tuple[str, str]]:
        return _pairs(self.readiness())

    def take(self) -> dict:
        return _bounded(lambda: self.plugin.cmd_take_device({}))

    def release(self) -> dict:
        return _bounded(lambda: self.plugin.cmd_release_device({}))

    def close(self) -> None:
        if isinstance(self.plugin._session, _StubSession):  # у заглушки нет stop(): shutdown ей не нужен
            self.plugin._session = None
        self.plugin.shutdown(self.ctx)
        self.wm.stop_all_workers(2.0)


@pytest.fixture
def make(monkeypatch: pytest.MonkeyPatch):
    rigs: list[_Rig] = []

    def factory(*, auto_start: bool, port: Any = None, **cfg_extra: Any) -> _Rig:
        cfg = {**_FAKE_CFG, "auto_start": auto_start, **cfg_extra}
        rig = _Rig(monkeypatch, cfg, port if port is not None else make_port(frame_period_s=0.02))
        rigs.append(rig)
        return rig

    yield factory
    for rig in rigs:
        rig.close()


class _StubSession:
    """Сеанс с тремя голыми атрибутами, как у настоящего (`state`, `device_held`, `last_error`).

    Чтения, берущие замок профиля сеанса, в `readiness` запрещены: заглушка роняет тест при обращении.
    """

    def __init__(self, state: str, held: bool = False, last_error: str | None = None) -> None:
        self.state = state
        self.device_held = held
        self.last_error = last_error

    @property
    def params(self) -> dict:
        raise AssertionError("readiness прочитал session.params (берёт замок профиля)")

    @property
    def params_status(self) -> dict:
        raise AssertionError("readiness прочитал session.params_status (берёт замок профиля)")

    @property
    def param_errors(self) -> dict:
        raise AssertionError("readiness прочитал session.param_errors (берёт замок профиля)")


def _stubbed(make: Callable[..., _Rig], *, auto_start: bool, state: str, held: bool = False, last_error=None) -> _Rig:
    rig = make(auto_start=auto_start)
    rig.plugin._session = _StubSession(state, held, last_error)  # шов: подмена сеанса заглушкой
    return rig


def _pairs(raw: Any) -> list[tuple[str, str]]:
    """Ответ хука как пары (severity, reason); форма проверяется отдельно, здесь — жёстко по контракту."""
    assert isinstance(raw, list), raw
    out: list[tuple[str, str]] = []
    for item in raw:
        assert isinstance(item, dict), item
        assert set(item) == {"severity", "reason"}, item
        assert type(item["severity"]) is str and type(item["reason"]) is str, item
        out.append((item["severity"], item["reason"]))
    return out


def _await(cond: Callable[[], bool], what: str, deadline: float = 10.0) -> None:
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.01)
    pytest.fail(f"не дождались: {what}")


# ---------------------------------------------------------------------------------------------- #
# Таблица «состояние -> причина» (заглушка сеанса, все состояния, оба значения auto_start)
# ---------------------------------------------------------------------------------------------- #

# (состояние, device_held, auto_start, ожидаемые пары). `held` — то, что реально бывает при этом состоянии.
_TABLE = [
    ("grabbing", True, True, []),
    ("grabbing", True, False, []),
    ("opening", True, True, [OPENING]),
    ("opening", True, False, [OPENING]),  # opening блокирует независимо от auto_start
    ("stopping", True, True, [STOPPING]),
    ("stopping", True, False, [STOPPING]),
    ("busy", True, True, [BUSY]),
    ("busy", True, False, [BUSY]),
    ("busy", False, True, [BUSY]),
    ("not_found", True, True, [NOT_FOUND]),
    ("not_found", True, False, [NOT_FOUND]),
    ("not_found", False, False, [NOT_FOUND]),
    ("error", True, True, [ERROR]),
    ("error", True, False, [ERROR]),
    ("error", False, True, [ERROR]),
    ("error", False, False, [ERROR]),
    ("idle", False, True, [NOT_STARTED]),
    ("idle", False, False, []),
    ("closed", False, True, [NOT_STARTED]),
    ("closed", False, False, []),
    # пара closed + held=True (два чтения не атомарны) терпится как closed
    ("closed", True, True, [NOT_STARTED]),
    ("closed", True, False, []),
]


@pytest.mark.parametrize(
    ("state", "held", "auto_start", "expected"),
    _TABLE,
    ids=[f"{s}-held{int(h)}-auto{int(a)}" for s, h, a, _ in _TABLE],
)
def test_table_state_to_reason(make, state, held, auto_start, expected) -> None:
    rig = _stubbed(make, auto_start=auto_start, state=state, held=held)

    assert rig.pairs() == expected


def test_table_covers_every_session_state() -> None:
    """Охранный: таблица выше не потеряла ни одного состояния сеанса из выдержки (литерал списка)."""
    covered = {state for state, _, _, _ in _TABLE}

    assert covered == {"idle", "opening", "grabbing", "stopping", "closed", "busy", "not_found", "error"}


@pytest.mark.parametrize("auto_start", [True, False], ids=["auto1", "auto0"])
def test_session_none_is_idle(make, auto_start) -> None:
    rig = make(auto_start=auto_start)
    assert rig.plugin._session is None  # предпосылка: сеанса ещё нет (configure его не создаёт)

    assert rig.pairs() == ([NOT_STARTED] if auto_start else [])


@pytest.mark.parametrize("auto_start", [True, False], ids=["auto1", "auto0"])
@pytest.mark.parametrize("state", ["", "weird", "GRABBING", "paused"])
def test_unknown_state_is_failure(make, auto_start, state) -> None:
    rig = _stubbed(make, auto_start=auto_start, state=state)

    assert rig.pairs() == [UNKNOWN]


def test_unknown_state_is_blocking_not_empty(make) -> None:
    """Неизвестное состояние не маскируется пустым списком: ответ непустой и блокирующий."""
    rig = _stubbed(make, auto_start=False, state="weird")

    got = rig.readiness()

    assert len(got) == 1
    assert got[0]["severity"] in ("failure", "check_function")


# ---------------------------------------------------------------------------------------------- #
# Форма ответа
# ---------------------------------------------------------------------------------------------- #


def test_result_is_list_of_dicts_with_exact_keys(make) -> None:
    rig = _stubbed(make, auto_start=True, state="idle")

    got = rig.readiness()

    assert type(got) is list
    assert len(got) == 1
    assert type(got[0]) is dict
    assert set(got[0]) == {"severity", "reason"}
    assert got[0] == {"severity": "check_function", "reason": "камера не запущена"}


@pytest.mark.parametrize("state", ["opening", "busy", "not_found", "error", "stopping", "weird"])
def test_reason_is_short_text_without_path_or_serial(make, state) -> None:
    rig = _stubbed(make, auto_start=True, state=state, last_error=_SECRET)

    got = rig.pairs()
    assert len(got) == 1, got  # без причины проверять нечего
    reason = got[0][1]

    assert len(reason) <= 200
    assert "/" not in reason and "\\" not in reason, reason
    assert "SN-" not in reason and "12345" not in reason, reason


def test_readiness_does_not_mutate_state(make) -> None:
    """Хук ничего не создаёт: сеанса нет — после вызова его по-прежнему нет, порт не тронут."""
    rig = make(auto_start=True)

    rig.readiness()
    rig.readiness()

    assert rig.plugin._session is None
    assert rig.port.calls == []


# ---------------------------------------------------------------------------------------------- #
# last_error не попадает в reason
# ---------------------------------------------------------------------------------------------- #


@pytest.mark.parametrize("auto_start", [True, False], ids=["auto1", "auto0"])
def test_error_reason_hides_last_error_text(make, auto_start) -> None:
    rig = _stubbed(make, auto_start=auto_start, state="error", last_error=_SECRET)

    got = rig.pairs()

    assert got == [ERROR]
    assert "SN-12345" not in got[0][1]
    assert "/dev/x" not in got[0][1]


@pytest.mark.parametrize("state", ["busy", "not_found", "error", "closed", "idle", "opening", "stopping", "weird"])
def test_no_state_leaks_last_error(make, state) -> None:
    rig = _stubbed(make, auto_start=True, state=state, last_error=_SECRET)

    got = rig.pairs()
    assert len(got) == 1, got  # без причины проверять нечего
    for _, reason in got:
        assert "SN-12345" not in reason, reason
        assert "/dev/x" not in reason, reason


def test_error_reason_same_with_and_without_last_error(make) -> None:
    with_text = _stubbed(make, auto_start=False, state="error", last_error=_SECRET).pairs()
    without = _stubbed(make, auto_start=False, state="error", last_error=None).pairs()

    assert with_text == without == [ERROR]


# ---------------------------------------------------------------------------------------------- #
# Замки и запретные чтения
# ---------------------------------------------------------------------------------------------- #


def _holding(locks: list[Any], hold_s: float = 30.0):
    """Контекст: другой поток держит все замки списка; на выходе отпускает и ждёт поток."""

    class _Holder:
        def __enter__(self) -> None:
            self._ready = threading.Event()
            self._release = threading.Event()

            def hold() -> None:
                for lock in locks:
                    lock.acquire()
                try:
                    self._ready.set()
                    self._release.wait(hold_s)
                finally:
                    for lock in reversed(locks):
                        lock.release()

            self._thread = threading.Thread(target=hold, daemon=True)
            self._thread.start()
            assert self._ready.wait(5.0), "держатель не взял замки"

        def __exit__(self, *exc: object) -> None:
            self._release.set()
            self._thread.join(5.0)

    return _Holder()


@pytest.mark.parametrize(
    ("state", "auto_start", "expected"),
    [
        ("error", False, [ERROR]),
        ("closed", True, [NOT_STARTED]),
        ("opening", False, [OPENING]),
        ("grabbing", True, []),
    ],
    ids=["error", "closed-auto", "opening", "grabbing"],
)
def test_readiness_returns_while_plugin_locks_are_held(make, state, auto_start, expected) -> None:
    """`plugin._lock` и `plugin._session_lock` заняты другим потоком: ответ приходит за дедлайн, причина прежняя."""
    rig = _stubbed(make, auto_start=auto_start, state=state, held=state != "closed")

    with _holding([rig.plugin._lock, rig.plugin._session_lock]):
        got = rig.pairs()

    assert got == expected


def test_readiness_does_not_take_plugin_lock(make) -> None:
    """Только `plugin._lock` (замок слота кадра) занят: хук не ждёт его."""
    rig = _stubbed(make, auto_start=False, state="error")

    with _holding([rig.plugin._lock]):
        got = rig.pairs()

    assert got == [ERROR]


def test_readiness_does_not_take_session_lock(make) -> None:
    """Только `plugin._session_lock` (ленивое создание сеанса) занят: хук не ждёт его."""
    rig = _stubbed(make, auto_start=False, state="error")

    with _holding([rig.plugin._session_lock]):
        got = rig.pairs()

    assert got == [ERROR]


def test_readiness_with_session_none_does_not_take_session_lock(make) -> None:
    """`session is None` + занятый `_session_lock`: ни ожидания замка, ни создания сеанса."""
    rig = make(auto_start=True)

    with _holding([rig.plugin._lock, rig.plugin._session_lock]):
        got = rig.pairs()

    assert got == [NOT_STARTED]
    assert rig.plugin._session is None


def test_readiness_does_not_call_ensure_session(make, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = make(auto_start=True)
    calls: list[str] = []
    monkeypatch.setattr(rig.plugin, "_ensure_session", lambda: calls.append("ensure") or None)

    got = rig.pairs()

    assert calls == []
    assert got == [NOT_STARTED]


def test_readiness_does_not_read_locking_session_properties(make) -> None:
    """`params`/`params_status`/`param_errors` берут замок профиля: заглушка роняет тест при обращении."""
    rig = _stubbed(make, auto_start=True, state="grabbing", held=True)

    assert rig.pairs() == []  # AssertionError заглушки пришёл бы сюда исключением


# ---------------------------------------------------------------------------------------------- #
# Сквозные: настоящий сеанс над фейковым портом
# ---------------------------------------------------------------------------------------------- #


@pytest.mark.timeout(30)
@pytest.mark.parametrize("auto_start", [True, False], ids=["auto1", "auto0"])
def test_real_grabbing_is_ready(make, auto_start) -> None:
    rig = make(auto_start=auto_start)
    assert rig.take()["status"] == "ok"
    assert rig.plugin.cmd_get_status({})["state"] == "grabbing"  # предпосылка

    assert rig.pairs() == []


@pytest.mark.timeout(30)
def test_real_release_by_operator_blocks_when_auto_start(make) -> None:
    """release_device оператором -> closed -> при auto_start `check_function` «камера не запущена» (намеренно)."""
    rig = make(auto_start=True)
    assert rig.take()["status"] == "ok"
    assert rig.pairs() == []  # до release камера готова
    assert rig.release()["status"] == "ok"
    assert rig.plugin.cmd_get_status({})["state"] == "closed"  # предпосылка

    assert rig.pairs() == [NOT_STARTED]


@pytest.mark.timeout(30)
def test_real_release_without_auto_start_is_ready(make) -> None:
    rig = make(auto_start=False)
    assert rig.take()["status"] == "ok"
    assert rig.release()["status"] == "ok"
    assert rig.plugin.cmd_get_status({})["state"] == "closed"  # предпосылка

    assert rig.pairs() == []


@pytest.mark.timeout(30)
def test_real_fresh_session_idle_follows_auto_start(make) -> None:
    """Сеанс создан, но не запущен (`idle`): шов — `_ensure_session()` (публичного пути к idle-сеансу нет)."""
    on = make(auto_start=True)
    off = make(auto_start=False)
    _bounded(on.plugin._ensure_session)
    _bounded(off.plugin._ensure_session)
    assert on.plugin.cmd_get_status({})["state"] == "idle"  # предпосылка
    assert off.plugin.cmd_get_status({})["state"] == "idle"

    assert on.pairs() == [NOT_STARTED]
    assert off.pairs() == []


@pytest.mark.timeout(30)
def test_real_not_found(make) -> None:
    rig = make(auto_start=True, device_serial="NOPE-9")
    assert rig.take()["status"] == "error"
    assert rig.plugin.cmd_get_status({})["state"] == "not_found"  # предпосылка

    assert rig.pairs() == [NOT_FOUND]


@pytest.mark.timeout(30)
def test_real_busy(make) -> None:
    rig = make(auto_start=False, port=make_port(busy_for_s=60.0))
    assert rig.take()["status"] == "error"
    assert rig.plugin.cmd_get_status({})["state"] == "busy"  # предпосылка

    assert rig.pairs() == [BUSY]


@pytest.mark.timeout(30)
def test_real_opening_blocks_even_without_auto_start(make) -> None:
    """Порт открывается 3 с: пока `opening`, `readiness` блокирует (иначе на boot `ready` наступит до открытия)."""
    rig = make(auto_start=False, port=make_port(open_delay_s=3.0, frame_period_s=0.02))
    taker = threading.Thread(target=lambda: rig.plugin.cmd_take_device({}), daemon=True)
    taker.start()
    try:
        _await(lambda: rig.plugin.cmd_get_status({})["state"] == "opening", "состояние opening")

        got = rig.pairs()

        assert got == [OPENING]
        assert got[0][0] in ("failure", "check_function")  # блокирующая серьёзность
    finally:
        taker.join(10.0)


@pytest.mark.timeout(30)
def test_real_grabbing_with_all_locks_held(make) -> None:
    """Настоящий сеанс в `grabbing` + заняты замки плагина, замок сеанса и замок профиля: ответ за дедлайн."""
    rig = make(auto_start=True)
    assert rig.take()["status"] == "ok"
    session = rig.plugin._session
    locks = [rig.plugin._lock, rig.plugin._session_lock, session._lock, session._profile.lock]

    with _holding(locks):
        got = rig.pairs()

    assert got == []


@pytest.mark.timeout(30)
def test_real_closed_with_all_locks_held_still_reports_not_started(make) -> None:
    rig = make(auto_start=True)
    assert rig.take()["status"] == "ok"
    assert rig.release()["status"] == "ok"
    session = rig.plugin._session
    locks = [rig.plugin._lock, rig.plugin._session_lock, session._lock, session._profile.lock]

    with _holding(locks):
        got = rig.pairs()

    assert got == [NOT_STARTED]
