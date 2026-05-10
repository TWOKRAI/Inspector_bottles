"""Панели деталей для Plugins Tab."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QListWidget, QVBoxLayout, QWidget


class PluginInfoCard(QWidget):
    """Информационная карточка плагина без registers.

    Показывает: имя, категория, описание, список портов.
    Принимает чистые данные (dict), не знает о PluginEntry.
    """

    def __init__(
        self,
        info: dict,  # {name, category, description, inputs: list[str], outputs: list[str]}
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Заголовок
        name_label = QLabel(info.get("name", ""))
        name_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(name_label)

        # Категория
        cat_label = QLabel(f"Категория: {info.get('category', '—')}")
        cat_label.setStyleSheet("color: #aaa;")
        layout.addWidget(cat_label)

        # Описание
        desc = info.get("description", "")
        if desc:
            desc_label = QLabel(desc)
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)

        # Порты ввода
        inputs = info.get("inputs", [])
        if inputs:
            layout.addWidget(QLabel("Входы:"))
            in_list = QListWidget()
            in_list.addItems(inputs)
            in_list.setMaximumHeight(80)
            layout.addWidget(in_list)

        # Порты вывода
        outputs = info.get("outputs", [])
        if outputs:
            layout.addWidget(QLabel("Выходы:"))
            out_list = QListWidget()
            out_list.addItems(outputs)
            out_list.setMaximumHeight(80)
            layout.addWidget(out_list)

        layout.addStretch()
