"""Hazard-тесты автора Task 4.2e: дыры слепого файла test_hikvision_presenter_m3.py, найденные инъекциями.

Слепой файл не различает: (а) убранную охрану `registers_manager is None` (ложный warning на каждое поле),
(б) убранный внутренний try вокруг set_value (внешний except тоже пишет warning). Ожидаемые значения — литералы.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from multiprocess_prototype.frontend.widgets.tabs.services.hikvision.presenter import (
    HikvisionSettingsPresenter,
)

SENT_FIELDS = ["frame_rate", "exposure_time", "gain"]


class Sender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict]] = []

    def send_command(self, target_process: str, command: str, args: dict | None = None) -> None:
        self.sent.append((target_process, command, args))


class Topology:
    def load(self) -> Any:
        data = {"processes": [{"process_name": "camera", "plugins": [{"plugin_name": "hikvision"}]}]}
        return SimpleNamespace(to_dict=lambda: data)


class Manager:
    """set_value: на `raise_field` бросает, иначе возвращает `ret`."""

    def __init__(self, ret: Any = True, raise_field: str | None = None) -> None:
        self._ret = ret
        self._raise_field = raise_field

    def set_value(self, register: str, field: str, value: Any) -> Any:
        if field == self._raise_field:
            raise RuntimeError("boom")
        return self._ret


def _run(sender: Sender, caplog: pytest.LogCaptureFixture, **kwargs: Any) -> tuple[bool, list[str]]:
    presenter = HikvisionSettingsPresenter(topology=Topology(), command_sender=sender, **kwargs)
    with caplog.at_level(logging.WARNING):
        return presenter.set_parameters(30, 900, 2)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def _fields(sender: Sender) -> list[str]:
    return [args["field"] for _, _, args in sender.sent]


@pytest.mark.parametrize("explicit", [False, True])
def test_no_manager_no_warning_and_ipc_sent(explicit: bool, caplog: pytest.LogCaptureFixture) -> None:
    """registers_manager=None (умолчание и явный): ни одного warning, IPC ушёл по трём полям."""
    sender = Sender()
    kwargs = {"registers_manager": None} if explicit else {}
    result = _run(sender, caplog, **kwargs)
    assert _warnings(caplog) == []
    assert _fields(sender) == SENT_FIELDS
    assert result == (True, [])


@pytest.mark.parametrize("field", SENT_FIELDS)
def test_set_value_raise_logged_by_inner_block_not_outer(field: str, caplog: pytest.LogCaptureFixture) -> None:
    """set_value бросил на одном поле: warning внутреннего блока (set_value + поле), без warning внешнего блока."""
    sender = Sender()
    result = _run(sender, caplog, registers_manager=Manager(raise_field=field))
    warnings = _warnings(caplog)
    assert any("set_value" in m and field in m for m in warnings), warnings
    assert not any("register_update провалился" in m for m in warnings), warnings
    assert _fields(sender) == SENT_FIELDS
    assert result == (True, [])


@pytest.mark.parametrize("ret", [None, 1])
def test_set_value_non_bool_result_is_not_failure(ret: Any, caplog: pytest.LogCaptureFixture) -> None:
    """Трактовка автора: warning только при ровно False; None и 1 сбоем не считаются. IPC ушёл."""
    sender = Sender()
    result = _run(sender, caplog, registers_manager=Manager(ret=ret))
    assert _warnings(caplog) == []
    assert _fields(sender) == SENT_FIELDS
    assert result == (True, [])
