# -*- coding: utf-8 -*-
"""Тесты ядра camera_device. Перепись assert в контрактном наборе: падение набора у вендора показывает значения."""

import pytest

pytest.register_assert_rewrite("Services.camera_device.tests.port_contract")
