# multiprocess_prototype/frontend/widgets/settings_tab.py
"""
SettingsTabWidget — вкладка настроек.

SliderControl, CheckboxControl по конфигу. Привязка к RegistersManager.
"""

from typing import Any, List, Optional

from frontend_module.components import BaseTab, SliderControl, CheckboxControl
from frontend_module.core.qt_imports import QGroupBox, QVBoxLayout, QWidget


class SettingsTabWidget(BaseTab):
    """Вкладка настроек: слайдеры и чекбоксы по конфигу. Привязка к RegistersManager."""

    def __init__(
        self,
        *,
        registers_manager: Optional[Any] = None,
        controls_config: Optional[List[dict]] = None,
        group_title: str = "Параметры отображения",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._registers_manager = registers_manager
        self._controls_config = controls_config or self._default_controls()
        self._group_title = group_title
        self._init_ui()

    def _default_controls(self) -> List[dict]:
        """Конфиг по умолчанию: draw.dp, draw.minDist, draw.circles, draw.rectangles."""
        return [
            {"type": "slider", "register_name": "draw", "field_name": "dp"},
            {"type": "slider", "register_name": "draw", "field_name": "minDist"},
            {"type": "checkbox", "register_name": "draw", "field_name": "circles"},
            {"type": "checkbox", "register_name": "draw", "field_name": "rectangles"},
            {"type": "checkbox", "register_name": "draw", "field_name": "draw"},
        ]

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        group = QGroupBox(self._group_title)
        group_layout = QVBoxLayout(group)
        for cfg in self._controls_config:
            w = self._create_control(cfg)
            if w:
                group_layout.addWidget(w)
        layout.addWidget(group)
        layout.addStretch()

    def _create_control(self, cfg: dict) -> Optional[Any]:
        ctype = cfg.get("type", "slider")
        reg = cfg.get("register_name")
        field = cfg.get("field_name")
        if not reg or not field:
            return None
        if ctype == "slider":
            return SliderControl(
                register_name=reg,
                field_name=field,
                registers_manager=self._registers_manager,
                parent=self,
            )
        if ctype == "checkbox":
            return CheckboxControl(
                register_name=reg,
                field_name=field,
                registers_manager=self._registers_manager,
                parent=self,
            )
        return None
