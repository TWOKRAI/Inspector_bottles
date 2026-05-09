"""ServicesTab — таб управления сервисами с боковой навигацией.

Композиция: SideNavLayout → каждый сервис = отдельная страница
(RegisterView + кнопки справа).

Layout:
    QVBoxLayout
      +-- QHBoxLayout (header)
      |     +-- QLabel "Сервисы"
      |     +-- stretch
      +-- SideNavLayout (stretch=1)
            nav (200px):              stack:
            ┌──────────────┐          ┌──────────────────────────────────┐
            │Камеры        │←default  │ RegisterView (поля)  │ кнопки   │
            │База данных   │          │                      │          │
            │Робот         │          │                      │          │
            │Сохранение    │          │                      │          │
            │              │          │                      │          │
            └──────────────┘          └──────────────────────────────────┘
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype_2.frontend.widgets.primitives import SideNavLayout
from multiprocess_prototype_2.frontend.forms import RegisterView

from .presenter import ServicesPresenter

if TYPE_CHECKING:
    from multiprocess_prototype_2.frontend.app_context import AppContext


class ServicesTab(QWidget):
    """Таб сервисов — камеры, БД, робот, сохранение кадров.

    Каждый сервис = отдельная страница в SideNavLayout с RegisterView
    и кнопками управления справа.
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._presenter = ServicesPresenter(ctx)
        self._register_views: list[RegisterView] = []

        self._init_ui()

        # Подписаться на ActionBus для обновления виджетов при undo/redo
        bus = self._ctx.action_bus()
        if bus is not None:
            bus.add_change_callback(self._on_bus_changed)

    @classmethod
    def create(cls, ctx: "AppContext") -> "ServicesTab":
        """Фабричный метод для TabFactory."""
        return cls(ctx)

    def _init_ui(self) -> None:
        """Построить layout таба с боковой навигацией."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Header
        header_layout = QHBoxLayout()
        title_label = QLabel("Сервисы")
        font = title_label.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title_label.setFont(font)
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        main_layout.addLayout(header_layout)

        # Боковая навигация
        self._side_nav = SideNavLayout()

        sections = self._presenter.get_service_sections()
        first_key: str | None = None

        for title, plugin_name, fields in sections:
            widget = self._build_service_page(plugin_name, fields)
            self._side_nav.add_section(plugin_name, title, widget)
            if first_key is None:
                first_key = plugin_name

        # Placeholder для нейронных сетей
        nn_placeholder = self._build_placeholder("Нейронные сети будут доступны в Phase 14+")
        self._side_nav.add_section("neural_networks", "Нейронные сети", nn_placeholder)

        if first_key:
            self._side_nav.set_current(first_key)

        main_layout.addWidget(self._side_nav, stretch=1)

    def _build_service_page(self, plugin_name: str, fields: list) -> QWidget:
        """Страница одного сервиса: RegisterView слева + кнопки справа."""
        container = QWidget()
        columns = QHBoxLayout(container)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(8)

        # Центральная часть: RegisterView с полями сервиса
        view = RegisterView(fields)
        view.field_changed.connect(self._on_field_changed)
        self._register_views.append(view)

        columns.addWidget(view, stretch=1)

        # Правая часть: кнопки управления
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(8)

        start_btn = QPushButton("Запустить")
        start_btn.setFixedWidth(100)
        start_btn.setToolTip(f"Запустить сервис {plugin_name}")
        btn_layout.addWidget(start_btn)

        stop_btn = QPushButton("Остановить")
        stop_btn.setFixedWidth(100)
        stop_btn.setToolTip(f"Остановить сервис {plugin_name}")
        btn_layout.addWidget(stop_btn)

        restart_btn = QPushButton("Перезапуск")
        restart_btn.setFixedWidth(100)
        restart_btn.setToolTip(f"Перезапустить сервис {plugin_name}")
        btn_layout.addWidget(restart_btn)

        btn_layout.addStretch()
        columns.addLayout(btn_layout)

        return container

    @staticmethod
    def _build_placeholder(text: str) -> QWidget:
        """Заглушка для секции, которая ещё не реализована."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: gray; font-size: 14px; font-style: italic;")
        layout.addWidget(label)
        return widget

    def _on_field_changed(
        self, register_name: str, field_name: str, old_value: object, new_value: object,
    ) -> None:
        """Изменение параметра сервиса → ActionBus.execute(field_set)."""
        bus = self._ctx.action_bus()
        if bus is None:
            return
        from multiprocess_prototype_2.frontend.actions.builder import V2ActionBuilder
        action = V2ActionBuilder.field_set_timed(
            register_name, field_name, new_value, old_value,
            description=f"{register_name}.{field_name} = {new_value}",
        )
        bus.execute(action)

    def _on_bus_changed(self) -> None:
        """Callback от ActionBus — обновить виджеты при undo/redo."""
        bus = self._ctx.action_bus()
        if bus is None:
            return
        event = bus.last_event
        if event is None:
            return
        event_type, action = event
        if event_type not in ("undo", "redo"):
            return
        if action.action_type != "field_set":
            return
        register_name = action.register_name or ""
        value = (
            action.backward_patch.get("value")
            if event_type == "undo"
            else action.forward_patch.get("value")
        )
        key = f"{register_name}.{action.field_name}"
        for view in self._register_views:
            if key in view.editors():
                view.set_editor_value(key, value)
                break
