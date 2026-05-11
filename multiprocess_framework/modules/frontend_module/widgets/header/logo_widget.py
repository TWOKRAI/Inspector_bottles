# -*- coding: utf-8 -*-
"""
LogoWidget — виджет логотипа для шапки.

Конфиг: LogoConfig (path, max_width, max_height, visible).
Принимает config (LogoConfig | dict) и parent.
FieldMeta — для консистентности, tooltips, unit, access_level.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional, Union

from multiprocess_framework.modules.frontend_module.schema_adapter import FieldMeta, SchemaBase, register_schema
from multiprocess_framework.modules.frontend_module.core.qt_imports import QHBoxLayout, QImage, QLabel, QPixmap, QSize, QWidget, Qt


@register_schema("LogoConfig")
class LogoConfig(SchemaBase):
    """Конфигурация LogoWidget."""

    path: Optional[str] = None
    max_width: Annotated[
        int,
        FieldMeta("Макс. ширина", info="Максимальная ширина логотипа в пикселях.", unit="px"),
    ] = 200
    max_height: Annotated[
        int,
        FieldMeta("Макс. высота", info="Максимальная высота логотипа в пикселях.", unit="px"),
    ] = 80
    visible: Annotated[
        bool,
        FieldMeta("Показывать", info="Отображать логотип."),
    ] = True


class LogoWidget(QWidget):
    """Виджет логотипа. Конфиг: path, max_width, max_height, visible."""

    def __init__(
        self,
        config: Union[LogoConfig, Dict[str, Any], None] = None,
        pixmap: Optional[QPixmap] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        cfg = LogoConfig(**(config or {})) if isinstance(config, dict) else (config or LogoConfig())
        data = cfg.model_dump()
        self._path = data.get("path")
        self._pixmap = pixmap
        self._max_width = data.get("max_width", 200)
        self._max_height = data.get("max_height", 80)
        self._visible = data.get("visible", True)
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setScaledContents(False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        layout.addWidget(self._label)
        layout.addStretch()
        self._update_pixmap()
        self.setVisible(self._visible)

    def _update_pixmap(self) -> None:
        pixmap = self._pixmap
        if pixmap is None and self._path:
            image = QImage(self._path)
            if not image.isNull():
                size = QSize(self._max_width, self._max_height)
                scaled = image.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                pixmap = QPixmap.fromImage(scaled)
        if pixmap and not pixmap.isNull():
            self._label.setPixmap(pixmap)
        else:
            self._label.clear()

    def set_pixmap(self, pixmap: QPixmap) -> None:
        """Установить pixmap напрямую."""
        self._pixmap = pixmap
        self._update_pixmap()

    def set_path(self, path: str) -> None:
        """Установить путь к изображению."""
        self._path = path
        self._pixmap = None
        self._update_pixmap()
