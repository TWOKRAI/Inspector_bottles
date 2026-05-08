"""ServicesTab — таб управления сервисами.

Композиция: SectionedForm[RegisterView × N_services].
Секция на каждый сервисный плагин (камеры, БД, робот и т.д.).
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from multiprocess_prototype_2.frontend.widgets.primitives import SectionedForm
from multiprocess_prototype_2.frontend.forms import RegisterView

from .presenter import ServicesPresenter

if TYPE_CHECKING:
    from multiprocess_prototype_2.frontend.app_context import AppContext


class ServicesTab(QWidget):
    """Таб сервисов — камеры, БД, робот, нейронки.

    Каждый сервис = секция (QGroupBox) с RegisterView внутри.
    Нейронные сети = placeholder.
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._presenter = ServicesPresenter(ctx)

        self._init_ui()
        self._populate()

    @classmethod
    def create(cls, ctx: "AppContext") -> "ServicesTab":
        """Фабричный метод для TabFactory."""
        return cls(ctx)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        header = QLabel("Сервисы")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)

        self._form = SectionedForm()
        layout.addWidget(self._form, stretch=1)

    def _populate(self) -> None:
        """Заполнить секции из presenter."""
        sections = self._presenter.get_service_sections()

        for title, plugin_name, fields in sections:
            view = RegisterView(fields)
            self._form.add_section(title, view)

        # Placeholder для нейронных сетей
        nn_placeholder = QLabel("Нейронные сети будут доступны в Phase 14+")
        nn_placeholder.setStyleSheet("color: #888; padding: 16px; font-style: italic;")
        self._form.add_section("Нейронные сети", nn_placeholder)
