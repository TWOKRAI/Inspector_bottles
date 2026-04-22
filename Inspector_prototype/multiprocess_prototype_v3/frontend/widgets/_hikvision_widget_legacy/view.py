# multiprocess_prototype_v3/frontend/widgets/hikvision_widget/view.py
"""Protocol View для HikvisionPresenter."""

from __future__ import annotations

from typing import Any, Protocol


class HikvisionView(Protocol):
    """Методы, которыми презентер обновляет UI. Пассивный View — только set_*."""

    def set_devices_list(self, devices: list) -> None:
        """Заполнить QListWidget списком устройств (display_name / index)."""
        ...

    def set_hikvision_params_lines(self, params: dict[str, Any]) -> None:
        """Обновить QLineEdit (fallback) значениями fps/exposure/gain из ответа камеры."""
        ...
