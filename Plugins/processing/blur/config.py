"""Конфиг BlurPlugin — параметры GaussianBlur."""

from __future__ import annotations

from pydantic import field_validator

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import PluginConfig


@register_schema("BlurPluginConfigV2")
class BlurPluginConfig(PluginConfig):
    """Конфиг плагина blur.

    Processing: вход BGR → cv2.GaussianBlur → выход BGR.
    kernel_size должен быть нечётным и положительным.
    """

    plugin_class: str = "Plugins.processing.blur.plugin.BlurPlugin"

    # Размер ядра свёртки (нечётное, > 0)
    kernel_size: int = 5

    # Стандартное отклонение по X (0 = вычисляется автоматически из kernel_size)
    sigma: float = 0.0

    @field_validator("kernel_size")
    @classmethod
    def kernel_size_must_be_odd_and_positive(cls, v: int) -> int:
        """Проверяет, что kernel_size нечётный и положительный."""
        if v <= 0:
            raise ValueError(f"kernel_size должен быть > 0, получено {v}")
        if v % 2 == 0:
            raise ValueError(
                f"kernel_size должен быть нечётным числом, получено {v} (чётное). "
                f"Используйте нечётные значения: 3, 5, 7, 9, ..."
            )
        return v
