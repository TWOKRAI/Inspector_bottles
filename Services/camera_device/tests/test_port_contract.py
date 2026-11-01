# -*- coding: utf-8 -*-
"""Контрактные тесты порта камеры (Task 1.5, решение П18).

Три прогона одного набора `PortContractSuite`: полный фейк, фейк без capabilities и реальный прибор
(`TestHardwareContract`, только с `CAMERA_HARDWARE=1`). Вендорские каталоги подклассируют набор у себя.
"""

from __future__ import annotations

import importlib
import os

import pytest

from Services.camera_device.interface import Binding, DeviceIdentity
from Services.camera_device.testing.fake_port import make_port
from Services.camera_device.tests.port_contract import PortCase, PortContractSuite

FAKE_IDENT = DeviceIdentity("serial", "FAKE-0001")
FAKE_RW_BINDING = Binding("genicam", "ExposureTime", "float")
ALL_CAPABILITIES = frozenset({"read_back", "live_write", "node_describe", "software_trigger", "restart_regrab"})


class TestFakeContract(PortContractSuite):
    @pytest.fixture
    def port_case(self) -> PortCase:
        return PortCase(
            id="fake",
            make=lambda: make_port(),
            ident=FAKE_IDENT,
            rw_binding=FAKE_RW_BINDING,
            frame_byte0=0,
        )

    def test_full_fake_declares_all_five_capabilities(self, port_case: PortCase):
        # Страж от вакуума: без него набор в TestFakeBareContract проходил бы и на фейке,
        # игнорирующем опцию capabilities.
        assert port_case.make().capabilities == ALL_CAPABILITIES


class TestFakeBareContract(PortContractSuite):
    @pytest.fixture
    def port_case(self) -> PortCase:
        return PortCase(
            id="fake-bare",
            make=lambda: make_port(capabilities=frozenset()),
            ident=FAKE_IDENT,
            rw_binding=FAKE_RW_BINDING,
            frame_byte0=0,
        )

    def test_bare_fake_declares_no_capabilities(self, port_case: PortCase):
        assert port_case.make().capabilities == frozenset()


@pytest.mark.hardware
class TestHardwareContract(PortContractSuite):
    """Реальный прибор. `CAMERA_PORT_FACTORY=<пакет.модуль:функция>` — фабрика свежего порта."""

    @pytest.fixture
    def port_case(self) -> PortCase:
        spec = os.environ.get("CAMERA_PORT_FACTORY", "")
        kind = os.environ.get("CAMERA_DEVICE_KIND", "")
        value = os.environ.get("CAMERA_DEVICE_VALUE", "")
        if not (spec and kind and value):
            pytest.fail(
                "CAMERA_HARDWARE=1 задан, но не заданы CAMERA_PORT_FACTORY, CAMERA_DEVICE_KIND, CAMERA_DEVICE_VALUE"
            )
        module_name, _, func_name = spec.partition(":")
        factory = getattr(importlib.import_module(module_name), func_name)
        return PortCase(
            id="hardware",
            make=factory,
            ident=DeviceIdentity(kind, value),
            rw_binding=FAKE_RW_BINDING,
            frame_byte0=None,
        )
