# -*- coding: utf-8 -*-
"""Контрактный набор порта камеры: одни и те же проверки для ЛЮБОГО `DevicePort` (Task 1.5).

`PortContractSuite` — базовый класс БЕЗ префикса `Test`: pytest его сам не собирает (так и задумано).
Собирают подклассы с префиксом `Test`, которые переопределяют фикстуру `port_case`:

    from Services.camera_device.tests.port_contract import PortCase, PortContractSuite

    class TestMyVendorContract(PortContractSuite):
        @pytest.fixture
        def port_case(self):
            return PortCase(id="vendor", make=make_my_port, ident=..., rw_binding=..., frame_byte0=None)

Общего списка `PORT_CASES` нет: `pytest <каталог вендора>` не соберёт файл ядра.
Ожидаемые значения — литералы контракта; из кода под тестом ничего не вычисляется.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest

from Services.camera_device.interface import (
    Binding,
    DeviceIdentity,
    DevicePort,
    ParamInfo,
    PortError,
    RawFrame,
)

TRIGGER_SOFTWARE = Binding("genicam", "TriggerSoftware", "command")


@dataclass(frozen=True)
class PortCase:
    """Один порт под контрактной проверкой.

    `make()` возвращает СВЕЖИЙ порт; `frame_byte0` — ожидаемый первый байт кадра для проверки
    копии (`None` у не-фейковых портов: тогда проверяется только `f2.data is not f1.data`).
    """

    id: str
    make: Callable[[], DevicePort]
    ident: DeviceIdentity
    rw_binding: Binding
    frame_byte0: int | None


def _journal_names(port) -> list[str] | None:
    """Имена вызовов из журнала фейка (`port.calls`); `None`, если у порта журнала нет."""
    calls = getattr(port, "calls", None)
    if calls is None:
        return None
    return [entry[0] for entry in calls]


class PortContractSuite:
    """9 проверок. Подкласс обязан переопределить фикстуру `port_case`."""

    @pytest.fixture
    def port_case(self) -> PortCase:
        raise NotImplementedError("подкласс PortContractSuite переопределяет фикстуру port_case")

    @pytest.fixture
    def opened_port(self, port_case: PortCase) -> Iterator[DevicePort]:
        """Свежий порт после `open(ident)`; на выходе `stop_grabbing()` и `close()` (идемпотентны)."""
        port = port_case.make()
        port.open(port_case.ident)
        try:
            yield port
        finally:
            port.stop_grabbing()
            port.close()

    def test_isinstance_device_port(self, port_case: PortCase):
        assert isinstance(port_case.make(), DevicePort) is True
        assert isinstance(object(), DevicePort) is False

    def test_get_frame_before_start_grabbing_is_closed(self, opened_port: DevicePort):
        with pytest.raises(PortError) as exc_info:
            opened_port.get_frame(100)
        assert exc_info.value.kind == "closed"

    def test_get_frame_while_grabbing_returns_raw_frame(self, opened_port: DevicePort):
        opened_port.start_grabbing()
        frame = opened_port.get_frame(100)
        assert isinstance(frame, RawFrame)
        assert frame.width > 0
        assert frame.height > 0
        assert len(frame.data) > 0
        assert type(frame.frame_num) is int

    def test_frame_is_a_copy_of_the_sdk_buffer(self, port_case: PortCase, opened_port: DevicePort):
        opened_port.start_grabbing()
        f1 = opened_port.get_frame(100)
        assert isinstance(f1, RawFrame)
        if port_case.frame_byte0 is not None:
            assert f1.data[0] == port_case.frame_byte0
        f1.data[0] = 255
        f2 = opened_port.get_frame(100)
        assert isinstance(f2, RawFrame)
        if port_case.frame_byte0 is None:
            assert f2.data is not f1.data
        else:
            assert f2.data[0] == port_case.frame_byte0

    def test_get_frame_after_stop_grabbing_is_closed(self, opened_port: DevicePort):
        opened_port.start_grabbing()
        opened_port.stop_grabbing()
        with pytest.raises(PortError) as exc_info:
            opened_port.get_frame(100)
        assert exc_info.value.kind == "closed"

    def test_close_is_idempotent(self, port_case: PortCase):
        never_opened = port_case.make()
        never_opened.close()
        port = port_case.make()
        port.open(port_case.ident)
        port.close()
        port.close()
        with pytest.raises(PortError) as exc_info:
            port.get_param(port_case.rw_binding)
        assert exc_info.value.kind == "closed"

    def test_start_grabbing_in_grabbing_is_idempotent(self, opened_port: DevicePort):
        opened_port.start_grabbing()
        opened_port.start_grabbing()
        assert isinstance(opened_port.get_frame(100), RawFrame)
        names = _journal_names(opened_port)
        if names is not None:
            assert names.count("open") == 1

    def test_describe_param_follows_node_describe_capability(self, port_case: PortCase, opened_port: DevicePort):
        info = opened_port.describe_param(port_case.rw_binding)
        if "node_describe" in opened_port.capabilities:
            assert isinstance(info, ParamInfo)
        else:
            assert info is None

    def test_execute_follows_software_trigger_capability(self, port_case: PortCase, opened_port: DevicePort):
        if "software_trigger" not in opened_port.capabilities:
            with pytest.raises(PortError) as exc_info:
                opened_port.execute(port_case.rw_binding)
            assert exc_info.value.kind == "access"
            return
        opened_port.execute(TRIGGER_SOFTWARE)
        calls = getattr(opened_port, "calls", None)
        if calls is not None:
            assert calls[-1][0] == "execute"
            assert calls[-1][1] == ("TriggerSoftware",)
        with pytest.raises(PortError) as exc_info:
            opened_port.execute(port_case.rw_binding)
        assert exc_info.value.kind == "other"
