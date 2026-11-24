# -*- coding: utf-8 -*-
"""Task 4.2i: диапазон усиления ``gain`` в ``HikvisionCameraRegisters``.

Узел ``Gain`` первой камеры стенда (MV-CS020-10GC) допускает до 23.98 дБ; register обязан принимать
23.0 (значение рецепта ``hikvision_id3013_quad``) и 24.0, но отвергать значения вне [0, 24].
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from Services.hikvision_camera.plugin.registers import HikvisionCameraRegisters


@pytest.mark.parametrize("value", [0.0, 23.0, 24.0])
def test_gain_inside_range_is_accepted(value: float) -> None:
    assert HikvisionCameraRegisters(gain=value).gain == value


@pytest.mark.parametrize("value", [25.0, -1.0])
def test_gain_outside_range_is_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        HikvisionCameraRegisters(gain=value)
