"""ProcessIdCombo — комбобокс выбора процесса с опцией создания нового.

Содержит список известных процессов + sentinel-пункт «+ Новый процесс...».
При выборе sentinel показывает QInputDialog для ввода имени.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QInputDialog, QWidget

# Sentinel-значение в конце списка (не является валидным process_id)
_SENTINEL = "+ Новый процесс…"


class ProcessIdCombo(QComboBox):
    """Комбобокс выбора process_id с возможностью создания нового.

    Signals:
        process_id_changed(str): испускается при выборе нового process_id.
    """

    process_id_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setEditable(False)

        # Предыдущее выбранное значение (для отката при Cancel sentinel)
        self._previous_id: str | None = None
        # Блокировка рекурсивных сигналов
        self._suppress = False

        self.currentIndexChanged.connect(self._on_index_changed)

    def set_known_processes(
        self,
        processes: list[str],
        current: str | None = None,
    ) -> None:
        """Перезаполнить items: уникальные processes + sentinel.

        Если current не в списке — добавляется первым (legacy backward-compat).
        Устанавливает selection на current.

        Args:
            processes: Список известных process_id.
            current: Текущий process_id для выделения.
        """
        self._suppress = True
        try:
            self.clear()

            # Формируем список: current первым (если его нет в processes)
            items: list[str] = []
            seen: set[str] = set()

            if current and current not in processes:
                items.append(current)
                seen.add(current)

            for p in processes:
                if p not in seen:
                    items.append(p)
                    seen.add(p)

            for item in items:
                self.addItem(item, item)

            # Sentinel последним
            self.addItem(_SENTINEL, _SENTINEL)

            # Установить selection
            if current:
                idx = self.findData(current)
                if idx >= 0:
                    self.setCurrentIndex(idx)
                    self._previous_id = current
            elif items:
                self._previous_id = items[0]
            else:
                self._previous_id = None
        finally:
            self._suppress = False

    def _on_index_changed(self, index: int) -> None:
        """Обработчик изменения selection."""
        if self._suppress or index < 0:
            return

        value = self.itemData(index)

        if value == _SENTINEL:
            self._handle_sentinel()
            return

        if value != self._previous_id:
            self._previous_id = value
            self.process_id_changed.emit(value)

    def _handle_sentinel(self) -> None:
        """Показать диалог ввода нового process_id."""
        name, ok = QInputDialog.getText(
            self,
            "Новый процесс",
            "Имя процесса:",
        )
        if ok and name.strip():
            new_name = name.strip()
            # Добавляем перед sentinel
            sentinel_idx = self.count() - 1
            self._suppress = True
            self.insertItem(sentinel_idx, new_name, new_name)
            self.setCurrentIndex(sentinel_idx)
            self._suppress = False

            self._previous_id = new_name
            self.process_id_changed.emit(new_name)
        else:
            # Cancel — вернуть selection на предыдущий
            self._suppress = True
            if self._previous_id:
                idx = self.findData(self._previous_id)
                if idx >= 0:
                    self.setCurrentIndex(idx)
            self._suppress = False

    def set_value_silent(self, process_id: str) -> None:
        """Установить значение без испускания сигнала (для refresh после undo)."""
        self._suppress = True
        try:
            idx = self.findData(process_id)
            if idx >= 0:
                self.setCurrentIndex(idx)
                self._previous_id = process_id
        finally:
            self._suppress = False


__all__ = ["ProcessIdCombo"]
