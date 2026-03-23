# -*- coding: utf-8 -*-
"""
TabWidget — композитный виджет: QTabWidget + кнопка сворачивания.
BaseTab — абстрактный базовый класс для вкладок с хуками on_tab_selected/on_tab_deselected.
"""
from __future__ import annotations

import abc
from typing import Dict, Optional

from frontend_module.core.qt_imports import (
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    Qt,
)


class BaseTabMeta(type(QWidget), abc.ABCMeta):
    pass


class BaseTab(QWidget, metaclass=BaseTabMeta):
    """
    Абстрактный базовый класс для виджетов-вкладок.
    Хуки: on_tab_selected(), on_tab_deselected().
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

    def on_tab_selected(self) -> None:
        pass

    def on_tab_deselected(self) -> None:
        pass


class TabWidget(QWidget):
    """Виджет с QTabWidget и кнопкой сворачивания/разворачивания."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tabs_visible = True
        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet(
            "QTabBar::tab { height: 35px; width: 95px; }"
            "QTabWidget::pane { border: 1px solid #ccc; }"
        )
        self._toggle_btn = QPushButton("Скрыть")
        self._toggle_btn.setFixedHeight(35)
        self._toggle_btn.setFixedWidth(95)
        self._toggle_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #f0f0f0; border: none;"
            "  border-top-left-radius: 4px; border-top-right-radius: 4px;"
            "  padding: 0px; font-size: 12px;"
            "}"
            "QPushButton:hover { background-color: #e0e0e0; }"
            "QPushButton:pressed { background-color: #d0d0d0; }"
        )
        self._toggle_btn.clicked.connect(self._toggle_tabs)
        corner = QWidget()
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.addWidget(self._toggle_btn)
        self._tab_widget.setCornerWidget(corner, Qt.TopRightCorner)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tab_widget)
        self._tab_widget.currentChanged.connect(self._on_current_changed)
        self._tab_index_to_widget: Dict[int, BaseTab] = {}
        self._last_index = -1

    def add_tab(self, widget: QWidget, title: str, wrap_scroll: bool = True) -> None:
        if wrap_scroll:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("QScrollBar:vertical { width: 40px; }")
            scroll.setWidget(widget)
            content_widget = scroll
        else:
            content_widget = widget
        index = self._tab_widget.addTab(content_widget, title)
        if isinstance(widget, BaseTab):
            self._tab_index_to_widget[index] = widget

    def _on_current_changed(self, index: int) -> None:
        old_index = self._last_index
        new_index = index
        if old_index != new_index and old_index in self._tab_index_to_widget:
            self._tab_index_to_widget[old_index].on_tab_deselected()
        if new_index in self._tab_index_to_widget:
            self._tab_index_to_widget[new_index].on_tab_selected()
        self._last_index = new_index

    def _toggle_tabs(self) -> None:
        self._tabs_visible = not self._tabs_visible
        if self._tabs_visible:
            self.setMinimumHeight(220)
            self.setMaximumHeight(16777215)
            for i in range(self._tab_widget.count()):
                w = self._tab_widget.widget(i)
                if w:
                    w.setVisible(True)
            self._toggle_btn.setText("Скрыть")
        else:
            tab_bar_h = self._tab_widget.tabBar().sizeHint().height()
            corner_h = self._toggle_btn.sizeHint().height()
            total_h = max(tab_bar_h, corner_h) + 2
            self.setFixedHeight(total_h)
            for i in range(self._tab_widget.count()):
                w = self._tab_widget.widget(i)
                if w:
                    w.setVisible(False)
            self._toggle_btn.setText("Показать")

    @property
    def tab_widget(self) -> QTabWidget:
        return self._tab_widget
