"""PluginChainEditor — редактор упорядоченной цепочки плагинов процесса.

Отображает plugin chain как вертикальный список карточек (PluginCardWidget).
Между карточками — индикатор совместимости портов.
Операции: удалить, переместить вверх/вниз, добавить.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .plugin_card_widget import PluginCardWidget

logger = logging.getLogger(__name__)

# --- Graceful degradation: PluginRegistry и are_ports_compatible ---
try:
    from multiprocess_framework.modules.process_module.plugins.registry import (
        PluginRegistry,
    )
    from multiprocess_framework.modules.process_module.plugins.port import (
        are_ports_compatible,
    )
    _HAS_REGISTRY = True
except ImportError:
    logger.warning(
        "PluginRegistry недоступен — карточки без портов, индикаторы серые"
    )
    PluginRegistry = None  # type: ignore[assignment, misc]
    are_ports_compatible = None  # type: ignore[assignment]
    _HAS_REGISTRY = False


# --- Стили индикаторов совместимости ---
_COMPAT_OK = (
    "color: #66BB6A; font-size: 16px; font-weight: bold; padding: 2px 0;"
)
_COMPAT_FAIL = (
    "color: #FF5252; font-size: 16px; font-weight: bold; padding: 2px 0;"
)
_COMPAT_UNKNOWN = (
    "color: #888; font-size: 16px; font-weight: bold; padding: 2px 0;"
)


class PluginChainEditor(QWidget):
    """Редактор цепочки плагинов процесса.

    Показывает упорядоченный список плагинов с карточками, индикаторами
    совместимости между ними и кнопкой добавления.

    Signals:
        plugin_selected(str, int): (proc_key, plugin_index) — выбор карточки
        plugin_removed(str, int): (proc_key, plugin_index) — удаление плагина
        plugin_moved(str, int, int): (proc_key, from_idx, to_idx) — перемещение
        add_plugin_requested(str): (proc_key) — запрос на добавление
    """

    plugin_selected = Signal(str, int)
    plugin_removed = Signal(str, int)
    plugin_moved = Signal(str, int, int)
    add_plugin_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._proc_key: str = ""
        self._plugins: list[dict] = []
        self._cards: list[PluginCardWidget] = []
        self._selected_index: int | None = None

        self._setup_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Построить layout: scroll area + кнопка добавления."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Scroll area для цепочки карточек
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self._inner = QWidget()
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(4, 4, 4, 4)
        self._inner_layout.setSpacing(0)

        self._scroll.setWidget(self._inner)
        outer.addWidget(self._scroll)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def set_chain(self, proc_key: str, plugins: list[dict]) -> None:
        """Установить цепочку плагинов для отображения.

        Очищает предыдущее содержимое и строит карточки + индикаторы заново.

        Args:
            proc_key: Ключ процесса (для сигналов).
            plugins: Упорядоченный список dict с ключами plugin_class,
                     plugin_name, category и пр.
        """
        self._proc_key = proc_key
        self._plugins = list(plugins)
        self._selected_index = None
        self._cards.clear()

        self._rebuild()

    def selected_plugin_index(self) -> int | None:
        """Индекс выбранной карточки или None."""
        return self._selected_index

    # ------------------------------------------------------------------
    # Внутренняя логика
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        """Пересобрать содержимое scroll area из текущего self._plugins."""
        # Очистить layout
        self._clear_layout()

        # Получить порты для всех плагинов
        ports_info = self._resolve_ports(self._plugins)

        # Создать карточки и индикаторы
        for i, plugin_data in enumerate(self._plugins):
            inputs_i, outputs_i = ports_info[i]

            card = PluginCardWidget(
                plugin_data=plugin_data,
                index=i,
                inputs=inputs_i,
                outputs=outputs_i,
            )
            card.selected.connect(self._on_card_selected)
            card.remove_requested.connect(self._on_card_remove)
            card.move_requested.connect(self._on_card_move)

            self._cards.append(card)
            self._inner_layout.addWidget(card)

            # Индикатор совместимости после каждой карточки кроме последней
            if i < len(self._plugins) - 1:
                next_inputs, _ = ports_info[i + 1]
                indicator = self._make_compatibility_indicator(
                    outputs_i, next_inputs
                )
                self._inner_layout.addWidget(
                    indicator, alignment=Qt.AlignmentFlag.AlignHCenter
                )

        # Кнопка "+ Добавить плагин"
        add_btn = QPushButton("+ Добавить плагин")
        add_btn.setStyleSheet(
            "QPushButton { color: #4A9EFF; border: 1px dashed #4A9EFF; "
            "border-radius: 4px; padding: 6px; margin-top: 4px; } "
            "QPushButton:hover { background: #333; }"
        )
        add_btn.clicked.connect(
            lambda: self.add_plugin_requested.emit(self._proc_key)
        )
        self._inner_layout.addWidget(add_btn)

        # Stretch в конце
        self._inner_layout.addStretch()

    def _clear_layout(self) -> None:
        """Удалить все виджеты из inner layout."""
        while self._inner_layout.count():
            item = self._inner_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards.clear()

    def _resolve_ports(
        self, plugins: list[dict]
    ) -> list[tuple[list | None, list | None]]:
        """Получить порты для каждого плагина из PluginRegistry.

        Returns:
            Список пар (inputs, outputs) для каждого плагина.
            None вместо списка если registry недоступен или плагин не найден.
        """
        result: list[tuple[list | None, list | None]] = []

        for plugin_data in plugins:
            plugin_name = plugin_data.get("plugin_name", "")
            inputs, outputs = self._get_plugin_ports(plugin_name)
            result.append((inputs, outputs))

        return result

    @staticmethod
    def _get_plugin_ports(
        plugin_name: str,
    ) -> tuple[list | None, list | None]:
        """Получить порты плагина из registry.

        Returns:
            (inputs, outputs) — списки Port или (None, None) если недоступно.
        """
        if not _HAS_REGISTRY or PluginRegistry is None:
            return None, None

        entry = PluginRegistry.get(plugin_name)
        if entry is None:
            return None, None

        return entry.inputs, entry.outputs

    def _make_compatibility_indicator(
        self,
        prev_outputs: list | None,
        next_inputs: list | None,
    ) -> QLabel:
        """Создать QLabel-индикатор совместимости между двумя плагинами.

        Args:
            prev_outputs: Выходные порты предыдущего плагина (или None).
            next_inputs: Входные порты следующего плагина (или None).

        Returns:
            QLabel со стрелкой: зелёной (совместимо), красной (нет) или серой (unknown).
        """
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Неизвестно — registry недоступен или плагин не найден
        if prev_outputs is None or next_inputs is None:
            label.setText("  ↓ ?  ")
            label.setStyleSheet(_COMPAT_UNKNOWN)
            label.setToolTip("Совместимость неизвестна — плагин не в registry")
            return label

        # Проверить совместимость
        compatible = self._check_compatibility(prev_outputs, next_inputs)

        if compatible:
            label.setText("  ↓  ")
            label.setStyleSheet(_COMPAT_OK)
            label.setToolTip("Порты совместимы")
        else:
            label.setText("  ↓ ✕  ")
            label.setStyleSheet(_COMPAT_FAIL)
            label.setToolTip("Порты НЕсовместимы")

        return label

    @staticmethod
    def _check_compatibility(
        prev_outputs: list, next_inputs: list
    ) -> bool:
        """Проверить совместимость выходов предыдущего с входами следующего.

        Логика: для каждого обязательного входа следующего плагина должен
        найтись хотя бы один совместимый выход предыдущего.

        Returns:
            True если все обязательные входы покрыты.
        """
        if are_ports_compatible is None:
            return False  # Не можем проверить без функции

        if not next_inputs:
            return True  # Нет входов — совместим

        for inp in next_inputs:
            # Опциональные входы не влияют на совместимость
            if getattr(inp, "optional", False):
                continue

            matched = False
            for out in prev_outputs:
                if are_ports_compatible(out, inp):
                    matched = True
                    break

            if not matched:
                return False

        return True

    # ------------------------------------------------------------------
    # Обработчики сигналов карточек
    # ------------------------------------------------------------------

    def _on_card_selected(self, index: int) -> None:
        """Обработать выбор карточки — обновить выделение и эмитить сигнал."""
        # Снять выделение с предыдущей
        if self._selected_index is not None:
            for card in self._cards:
                if card.index == self._selected_index:
                    card.set_selected(False)

        # Установить новое выделение
        self._selected_index = index
        for card in self._cards:
            if card.index == index:
                card.set_selected(True)

        self.plugin_selected.emit(self._proc_key, index)

    def _on_card_remove(self, index: int) -> None:
        """Обработать удаление карточки — эмитить сигнал."""
        self.plugin_removed.emit(self._proc_key, index)

    def _on_card_move(self, index: int, direction: int) -> None:
        """Обработать перемещение карточки — эмитить сигнал с целевым индексом.

        Args:
            index: Текущий индекс карточки.
            direction: -1 (вверх) или +1 (вниз).
        """
        to_idx = index + direction
        if 0 <= to_idx < len(self._cards):
            self.plugin_moved.emit(self._proc_key, index, to_idx)
