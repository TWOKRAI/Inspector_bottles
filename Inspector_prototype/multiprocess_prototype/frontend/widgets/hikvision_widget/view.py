# multiprocess_prototype/frontend/widgets/hikvision_widget/view.py
"""Protocol View для HikvisionPresenter."""

from __future__ import annotations

from typing import Any, Protocol


class HikvisionView(Protocol):
    """Методы, которыми презентер обновляет UI."""

    def get_selected_camera_index(self) -> int:
        ...

    def set_devices_list(self, devices: list) -> None:
        ...

    def set_hikvision_params_lines(self, params: dict[str, Any]) -> None:
        ...

    def get_hikvision_params_from_lines(self) -> tuple[float, float, float]:
        ...
