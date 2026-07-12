# -*- coding: utf-8 -*-
"""LazyTab — обёртка ленивой инициализации содержимого вкладки.

Generic-механика (перенесена из прототипа, NEW-D1). Содержимое создаётся при
первом ``showEvent`` — до этого показывается метка «Loading...». Исключение в
фабрике поглощается и заменяется меткой ошибки, чтобы одна «плохая» вкладка не
роняла всё окно.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QLabel,
    Qt,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class LazyTab(QWidget):
    """Обёртка ленивой инициализации вкладки.

    Содержимое создаётся при первом событии ``showEvent`` (не при добавлении в
    ``QTabWidget``), поэтому неактивные вкладки не платят за построение виджетов.
    """

    def __init__(
        self,
        factory_fn: Callable[[], QWidget],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._factory_fn = factory_fn
        self._initialized = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        # Временная метка до первого показа
        self._loading_label = QLabel("Loading...")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._loading_label)

    def showEvent(self, event) -> None:  # type: ignore[override]
        """Инициализировать содержимое при первом показе."""
        super().showEvent(event)
        if not self._initialized:
            self._initialized = True
            self._loading_label.deleteLater()
            self._loading_label = None  # type: ignore[assignment]
            try:
                widget = self._factory_fn()
                if widget is not None:
                    self._layout.addWidget(widget)
            except Exception:
                logger.exception("Ошибка создания вкладки")
                # Fallback — показываем метку об ошибке
                err_label = QLabel("Ошибка загрузки")
                err_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._layout.addWidget(err_label)
