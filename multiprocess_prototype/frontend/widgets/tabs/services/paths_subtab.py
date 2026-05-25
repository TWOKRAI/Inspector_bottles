# -*- coding: utf-8 -*-
"""ServicePathsSubtabWidget — подвкладка «Пути» в ServicesTab.

Позволяет просматривать, добавлять и удалять директории поиска сервисов.
После изменений и ресканирования emit'ит сигнал ``catalog_updated``
для автообновления каталога (аналог PathsSubtabWidget из PluginsTab).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from .presenter import ServicesPresenter


class ServicePathsSubtabWidget(QWidget):
    """Виджет управления директориями сервисов.

    Вертикальная компоновка:
    - Заголовок «Директории сервисов»
    - QListWidget со списком путей
    - Кнопки «Добавить папку...» / «Удалить» / «Рескан»
    - Строка статуса (результат последней операции)

    Сигналы:
        catalog_updated: emit'ится после ресканирования — сигнал для
                         ServicesTab.refresh_catalog() (Task 3.6).
    """

    catalog_updated = Signal()

    def __init__(
        self,
        presenter: "ServicesPresenter",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._presenter = presenter
        self._build_ui()
        self._populate()

    # ------------------------------------------------------------------ #
    #  Построение UI                                                       #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Заголовок
        header = QLabel("Директории сервисов")
        header.setObjectName("TabHeader")
        layout.addWidget(header)

        # Список путей
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        layout.addWidget(self._list, 1)

        # Кнопки управления
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._btn_add = QPushButton("Добавить папку...")
        self._btn_remove = QPushButton("Удалить")
        self._btn_rescan = QPushButton("Рескан")

        self._btn_add.clicked.connect(self._on_add)
        self._btn_remove.clicked.connect(self._on_remove)
        self._btn_rescan.clicked.connect(self._on_rescan)

        btn_row.addWidget(self._btn_add)
        btn_row.addWidget(self._btn_remove)
        btn_row.addWidget(self._btn_rescan)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Строка статуса
        self._status = QLabel("")
        self._status.setObjectName("MutedLabel")
        layout.addWidget(self._status)

    # ------------------------------------------------------------------ #
    #  Заполнение списка                                                   #
    # ------------------------------------------------------------------ #

    def _populate(self) -> None:
        """Перезаполнить список из presenter.get_service_paths()."""
        self._list.clear()
        paths = self._presenter.get_service_paths()
        self._list.addItems(paths)

    # ------------------------------------------------------------------ #
    #  Обработчики кнопок                                                  #
    # ------------------------------------------------------------------ #

    def _on_add(self) -> None:
        """Открыть диалог выбора папки, добавить путь."""
        path = QFileDialog.getExistingDirectory(self, "Выберите папку с сервисами")
        if not path:
            # Пользователь отменил диалог
            return
        self._presenter.add_service_path(path)
        self._populate()
        self._status.setText("Путь добавлен")

    def _on_remove(self) -> None:
        """Удалить выбранный путь из списка."""
        item = self._list.currentItem()
        if item is None:
            return
        self._presenter.remove_service_path(item.text())
        self._populate()
        self._status.setText("Путь удалён")

    def _on_rescan(self) -> None:
        """Запустить rescan через ServiceRegistry, обновить статус и emit signal."""
        summary = self._presenter.rescan()
        self._populate()
        self._status.setText(summary)
        self.catalog_updated.emit()
