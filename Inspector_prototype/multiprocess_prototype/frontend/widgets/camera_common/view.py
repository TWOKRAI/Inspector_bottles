# multiprocess_prototype/frontend/widgets/camera_common/view.py
"""Protocol View для SimWebcamPresenter."""

from __future__ import annotations

from typing import Protocol


class SimWebcamView(Protocol):
    """Методы, которыми презентер обновляет UI."""

    def set_fps_label_text(self, text: str) -> None:
        ...
