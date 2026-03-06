# -*- coding: utf-8 -*-
"""
tab_widget.py — модуль для работы с вкладками главного окна.

Содержит:
- BaseTab: абстрактный базовый класс для виджетов-вкладок, которые хотят получать уведомления о переключении.
- TabWidget: композитный виджет, управляющий QTabWidget и кнопкой сворачивания.
"""

import abc
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


# Объединённый метакласс для совместимости QWidget и ABC
class BaseTabMeta(type(QWidget), abc.ABCMeta):
    """Метакласс, объединяющий метакласс QWidget и ABCMeta."""
    pass


class BaseTab(QWidget, metaclass=BaseTabMeta):
    """
    Абстрактный базовый класс для виджетов, которые будут размещаться во вкладках.

    Предоставляет хуки жизненного цикла вкладки:
        on_tab_selected()   — вызывается, когда вкладка становится активной
        on_tab_deselected() — вызывается, когда вкладка перестаёт быть активной

    Эти методы могут быть переопределены в наследниках для выполнения
    специфических действий (например, обновление данных, остановка таймеров).
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

    def on_tab_selected(self) -> None:
        """
        Вызывается, когда данная вкладка становится активной.
        По умолчанию ничего не делает.
        """
        pass

    def on_tab_deselected(self) -> None:
        """
        Вызывается, когда данная вкладка перестаёт быть активной.
        По умолчанию ничего не делает.
        """
        pass


class TabWidget(QWidget):
    """
    Виджет, содержащий QTabWidget и кнопку сворачивания/разворачивания.
    Предоставляет метод add_tab() для добавления вкладок.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tabs_visible = True

        # Основной tab widget
        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet(
            "QTabBar::tab { height: 35px; width: 95px; }"
            "QTabWidget::pane { border: 1px solid #ccc; }"
        )
        # Убираем фиксированную минимальную высоту, чтобы можно было сжимать при сворачивании
        # self._tab_widget.setMinimumHeight(220)  # удалено

        # Кнопка сворачивания
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

        # Размещаем кнопку в правом верхнем углу tab widget
        corner = QWidget()
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.addWidget(self._toggle_btn)
        self._tab_widget.setCornerWidget(corner, Qt.TopRightCorner)

        # Основной layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tab_widget)

        # Подключаем сигнал смены вкладки для вызова хуков on_tab_selected/deselected
        self._tab_widget.currentChanged.connect(self._on_current_changed)

        # Словарь для хранения соответствия индексов вкладок и объектов BaseTab
        self._tab_index_to_widget: dict[int, BaseTab] = {}
        self._last_index = -1

    def add_tab(self, widget: QWidget, title: str, wrap_scroll: bool = True) -> None:
        """
        Добавляет вкладку. Если wrap_scroll=True, виджет оборачивается в QScrollArea.
        Если widget является экземпляром BaseTab, он будет автоматически получать
        уведомления о выборе/снятии выбора.
        """
        # Оборачиваем в скролл при необходимости
        if wrap_scroll:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("QScrollBar:vertical { width: 40px; }")
            scroll.setWidget(widget)
            content_widget = scroll
        else:
            content_widget = widget

        # Добавляем вкладку
        index = self._tab_widget.addTab(content_widget, title)

        # Если виджет наследует BaseTab, сохраняем его для вызова хуков
        if isinstance(widget, BaseTab):
            self._tab_index_to_widget[index] = widget

    def _on_current_changed(self, index: int) -> None:
        """
        Слот, вызываемый при смене активной вкладки.
        Уведомляет предыдущую и новую вкладки (если они являются BaseTab).
        """
        old_index = self._last_index
        new_index = index

        # Уведомляем старую вкладку (если она BaseTab и отличается от новой)
        if old_index != new_index and old_index in self._tab_index_to_widget:
            self._tab_index_to_widget[old_index].on_tab_deselected()

        # Уведомляем новую вкладку (если она BaseTab)
        if new_index in self._tab_index_to_widget:
            self._tab_index_to_widget[new_index].on_tab_selected()

        self._last_index = new_index

    def _toggle_tabs(self) -> None:
        """Скрывает/показывает содержимое вкладок, изменяя высоту всего виджета."""
        self._tabs_visible = not self._tabs_visible
        if self._tabs_visible:
            # Разворачиваем: снимаем ограничения высоты, устанавливаем минимальную высоту 220
            self.setMinimumHeight(220)
            self.setMaximumHeight(16777215)  # сброс максимума
            # Показываем содержимое вкладок (на всякий случай)
            for i in range(self._tab_widget.count()):
                w = self._tab_widget.widget(i)
                if w:
                    w.setVisible(True)
            self._toggle_btn.setText("Скрыть")
        else:
            # Сворачиваем: вычисляем высоту панели вкладок
            tab_bar_h = self._tab_widget.tabBar().sizeHint().height()
            corner_h = self._toggle_btn.sizeHint().height()
            total_h = max(tab_bar_h, corner_h) + 2
            # Фиксируем высоту внешнего контейнера
            self.setFixedHeight(total_h)
            # Скрываем содержимое вкладок (необязательно, но оставим для единообразия)
            for i in range(self._tab_widget.count()):
                w = self._tab_widget.widget(i)
                if w:
                    w.setVisible(False)
            self._toggle_btn.setText("Показать")

    @property
    def tab_widget(self) -> QTabWidget:
        """Доступ к внутреннему QTabWidget для обратной совместимости."""
        return self._tab_widget