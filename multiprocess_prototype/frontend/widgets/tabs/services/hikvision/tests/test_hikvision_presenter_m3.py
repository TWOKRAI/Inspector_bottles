"""Приёмка Task 4.2e: «Применить» вкладки Hikvision обновляет GUI-регистр перед IPC.

Контракт (слепые тесты, RED до кода): после «Применить» GUI-копия регистра (`RegistersManager`) показывает то же
значение, что ушло в процесс камеры. Порядок на каждое поле: сначала `registers_manager.set_value(register, field,
value)`, потом IPC `send_command(proc, "register_update", {register, field, value})`. Эталон порядка — живая запись
поля в `frontend/app.py` (`_on_plugin_config_changed`). Регистр называется `hikvision`, процесс камеры — `camera`.

Шпионы менеджера и отправителя пишут в ОБЩИЙ журнал: порядок событий проверяется целиком, а не по двум спискам.
Ожидаемые значения — литералы. Презентер создаётся внутри теста (kw `registers_manager` появляется с задачей;
на сборке файла TypeError быть не должен).
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from multiprocess_prototype.frontend.widgets.tabs.services.hikvision.controller import (
    HikvisionWidgetController,
    build_hikvision_controls,
)
from multiprocess_prototype.frontend.widgets.tabs.services.hikvision.presenter import (
    HikvisionSettingsPresenter,
)

# Журнал (30, 900, 2): на каждое поле сначала set_value в GUI-регистр, потом register_update в процесс камеры.
FULL_JOURNAL = [
    ("set_value", "hikvision", "frame_rate", 30.0),
    ("send", "camera", "register_update", {"register": "hikvision", "field": "frame_rate", "value": 30.0}),
    ("set_value", "hikvision", "exposure_time", 900.0),
    ("send", "camera", "register_update", {"register": "hikvision", "field": "exposure_time", "value": 900.0}),
    ("set_value", "hikvision", "gain", 2.0),
    ("send", "camera", "register_update", {"register": "hikvision", "field": "gain", "value": 2.0}),
]

# Журнал (30, 900, 2) без менеджера: только IPC.
SEND_ONLY_JOURNAL = [event for event in FULL_JOURNAL if event[0] == "send"]

# Журнал (0, 900, 2): frame_rate пропущен целиком (ни set_value, ни send).
NO_FPS_JOURNAL = [
    ("set_value", "hikvision", "exposure_time", 900.0),
    ("send", "camera", "register_update", {"register": "hikvision", "field": "exposure_time", "value": 900.0}),
    ("set_value", "hikvision", "gain", 2.0),
    ("send", "camera", "register_update", {"register": "hikvision", "field": "gain", "value": 2.0}),
]


class SpyRegistersManager:
    """Спай `RegistersManager.set_value`: пишет событие в общий журнал; на `fail_field` возвращает False или бросает."""

    def __init__(self, journal: list, *, fail_field: str | None = None, fail_mode: str = "false") -> None:
        self._journal = journal
        self._fail_field = fail_field
        self._fail_mode = fail_mode
        self.calls: list[tuple[str, str, Any]] = []

    def set_value(self, register: str, field: str, value: Any) -> bool:
        self.calls.append((register, field, value))
        self._journal.append(("set_value", register, field, value))
        if field == self._fail_field:
            if self._fail_mode == "raise":
                raise RuntimeError(f"spy: set_value {field} failed")
            return False
        return True


class JournalSender:
    """Спай `CommandSender`: `send_command` пишет в общий журнал, `request_command` — отдельно (в журнал не идёт)."""

    def __init__(self, journal: list) -> None:
        self._journal = journal
        self.sent: list[tuple[str, str, dict]] = []
        self.requests: list[tuple[str, str, dict]] = []

    def send_command(self, target_process: str, command: str, args: dict | None = None) -> None:
        self.sent.append((target_process, command, args))
        self._journal.append(("send", target_process, command, args))

    def request_command(self, target_process: str, command: str, args: dict | None = None) -> dict:
        self.requests.append((target_process, command, args))
        return {}


class SyncRunner:
    """RequestRunner без потока: результат сразу в колбэк."""

    def submit(self, fn: Any, on_result: Any) -> None:
        on_result(fn())


class FakeTopology:
    """Топология с одним процессом `camera`, где живёт плагин `hikvision`."""

    def load(self) -> Any:
        data = {"processes": [{"process_name": "camera", "plugins": [{"plugin_name": "hikvision"}]}]}
        return SimpleNamespace(to_dict=lambda: data)


def _presenter(sender: Any, **kwargs: Any) -> HikvisionSettingsPresenter:
    """Презентер с процессом `camera`; `kwargs` — только то, что тест проверяет (например `registers_manager`)."""
    return HikvisionSettingsPresenter(
        topology=FakeTopology(), command_sender=sender, request_runner=SyncRunner(), **kwargs
    )


def _register_events(journal: list) -> list:
    """События записи поля в журнале (set_value и register_update); другое (запросы устройств и т.п.) отфильтровано."""
    return [e for e in journal if e[0] == "set_value" or (e[0] == "send" and e[2] == "register_update")]


# --- (1) порядок: set_value строго перед send, поле за полем ---


def test_set_parameters_updates_gui_register_before_each_ipc() -> None:
    """(1) set_parameters(30, 900, 2): журнал = [set_value, send] на каждое из трёх полей, в порядке полей."""
    journal: list = []
    presenter = _presenter(JournalSender(journal), registers_manager=SpyRegistersManager(journal))
    result = presenter.set_parameters(30, 900, 2)
    assert journal == FULL_JOURNAL
    assert result == (True, [])


# --- (2) пропуск frame_rate при fps = 0 ---


def test_set_parameters_zero_fps_skips_frame_rate_in_gui_and_ipc() -> None:
    """(2) set_parameters(0, 900, 2): по frame_rate нет ни set_value, ни send; остальные четыре события как в (1)."""
    journal: list = []
    presenter = _presenter(JournalSender(journal), registers_manager=SpyRegistersManager(journal))
    result = presenter.set_parameters(0, 900, 2)
    assert journal == NO_FPS_JOURNAL
    assert result == (True, ["frame_rate"])


# --- (3) отказ GUI-регистра не отменяет IPC ---


@pytest.mark.parametrize("fail_mode", ["false", "raise"])
@pytest.mark.parametrize("fail_field", ["frame_rate", "exposure_time", "gain"])
def test_set_value_failure_does_not_block_ipc(fail_field: str, fail_mode: str) -> None:
    """(3) set_value вернул False / бросил на одном поле: send этого поля и всех остальных всё равно ушёл."""
    journal: list = []
    manager = SpyRegistersManager(journal, fail_field=fail_field, fail_mode=fail_mode)
    presenter = _presenter(JournalSender(journal), registers_manager=manager)
    result = presenter.set_parameters(30, 900, 2)
    assert journal == FULL_JOURNAL
    assert result == (True, [])


@pytest.mark.parametrize("fail_mode", ["false", "raise"])
@pytest.mark.parametrize("fail_field", ["frame_rate", "exposure_time", "gain"])
def test_set_value_failure_is_logged_as_warning(
    fail_field: str, fail_mode: str, caplog: pytest.LogCaptureFixture
) -> None:
    """(3) отказ GUI-регистра по полю не молчит: warning с именем поля (как в app.py: `GUI rm.set_value не прошёл`)."""
    journal: list = []
    manager = SpyRegistersManager(journal, fail_field=fail_field, fail_mode=fail_mode)
    presenter = _presenter(JournalSender(journal), registers_manager=manager)
    with caplog.at_level(logging.WARNING):
        presenter.set_parameters(30, 900, 2)
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(fail_field in message for message in warnings), warnings


# --- (4) без менеджера: поведение как до задачи ---


def test_without_registers_manager_kw_only_ipc_as_before() -> None:
    """(4) kw не передан (умолчание None): только send, результат (True, []) — как до задачи."""
    journal: list = []
    result = _presenter(JournalSender(journal)).set_parameters(30, 900, 2)
    assert journal == SEND_ONLY_JOURNAL
    assert result == (True, [])


def test_registers_manager_none_explicit_only_ipc_as_before() -> None:
    """(4) registers_manager=None явно: только send, пропущенные поля — как до задачи."""
    journal: list = []
    result = _presenter(JournalSender(journal), registers_manager=None).set_parameters(0, 900, 2)
    assert journal == [e for e in SEND_ONLY_JOURNAL if e[3]["field"] != "frame_rate"]
    assert result == (True, ["frame_rate"])


# --- (7) тип значения: float и в GUI-регистре, и в IPC ---


def test_values_are_float_for_gui_register_and_ipc_payload() -> None:
    """(7) целые 30/900/2 из поля ввода: и set_value, и payload register_update получают именно float."""
    journal: list = []
    manager = SpyRegistersManager(journal)
    sender = JournalSender(journal)
    _presenter(sender, registers_manager=manager).set_parameters(30, 900, 2)
    assert [type(value) for _register, _field, value in manager.calls] == [float, float, float]
    assert [type(args["value"]) for _proc, _cmd, args in sender.sent] == [float, float, float]


# --- (5) контроллер: менеджер берётся из runtime ---


def _controls(runtime: Any, services: Any | None = None) -> tuple[Any, HikvisionWidgetController]:
    return build_hikvision_controls(
        services=services if services is not None else SimpleNamespace(topology=FakeTopology()),
        runtime=runtime,
        request_runner=SyncRunner(),
    )


def test_controller_apply_updates_runtime_registers_manager_before_ipc(qapp) -> None:
    """(5) runtime.registers_manager есть: _on_apply_params(30, 900, 2) -> set_value x3 перед соответствующим send."""
    journal: list = []
    manager = SpyRegistersManager(journal)
    runtime = SimpleNamespace(command_sender=JournalSender(journal), registers_manager=manager)
    _widget, controller = _controls(runtime)
    controller._on_apply_params(30, 900, 2)
    assert manager.calls == [
        ("hikvision", "frame_rate", 30.0),
        ("hikvision", "exposure_time", 900.0),
        ("hikvision", "gain", 2.0),
    ]
    assert _register_events(journal) == FULL_JOURNAL


@pytest.mark.parametrize("runtime_has_attr", [False, True], ids=["attr_absent", "attr_none"])
def test_controller_apply_without_runtime_registers_manager_calls_nothing(qapp, runtime_has_attr: bool) -> None:
    """(5) у runtime нет registers_manager (нет атрибута / None): set_value не зовётся ни у кого, IPC уходит как раньше.

    Приманка `services.registers_manager`: менеджер берётся из runtime, а не откуда придётся.
    """
    journal: list = []
    decoy = SpyRegistersManager(journal)
    runtime = SimpleNamespace(command_sender=JournalSender(journal))
    if runtime_has_attr:
        runtime.registers_manager = None
    services = SimpleNamespace(topology=FakeTopology(), registers_manager=decoy)
    _widget, controller = _controls(runtime, services)
    controller._on_apply_params(30, 900, 2)
    assert decoy.calls == []
    assert _register_events(journal) == SEND_ONLY_JOURNAL


# --- (6) настоящие объекты: RegistersManager + виджет, IPC — шпион ---


@pytest.mark.parametrize("trigger", ["method", "button"])
def test_apply_with_real_registers_manager_gui_copy_matches_ipc(qapp, trigger: str) -> None:
    """(6) Настоящий RegistersManager + HikvisionCameraRegisters: после «Применить» (30, 900, 2) GUI-копия 30/900/2.

    До «Применить» в регистре умолчания (25.0 / 10000.0 / 0.0) — сдвиг виден. В процесс камеры ушли три register_update
    с теми же значениями. Фильтр по command: другие презентеры могут слать иное.
    """
    from multiprocess_framework.modules.registers_module.core.manager import RegistersManager
    from Services.hikvision_camera.plugin.registers import HikvisionCameraRegisters

    manager = RegistersManager({"hikvision": HikvisionCameraRegisters()})
    register = manager.get_register("hikvision")
    assert (register.frame_rate, register.exposure_time, register.gain) == (25.0, 10000.0, 0.0)

    sender = JournalSender([])
    runtime = SimpleNamespace(command_sender=sender, registers_manager=manager)
    widget, controller = _controls(runtime)
    if trigger == "method":
        controller._on_apply_params(30, 900, 2)
    else:
        widget._edit_fps.setText("30")
        widget._edit_exposure.setText("900")
        widget._edit_gain.setText("2")
        widget._btn_apply.click()

    register = manager.get_register("hikvision")
    assert (register.frame_rate, register.exposure_time, register.gain) == (30.0, 900.0, 2.0)
    updates = [call for call in sender.sent if call[1] == "register_update"]
    assert updates == [
        ("camera", "register_update", {"register": "hikvision", "field": "frame_rate", "value": 30.0}),
        ("camera", "register_update", {"register": "hikvision", "field": "exposure_time", "value": 900.0}),
        ("camera", "register_update", {"register": "hikvision", "field": "gain", "value": 2.0}),
    ]
