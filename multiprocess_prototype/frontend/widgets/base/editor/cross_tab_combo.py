"""CrossTabComboBox — QComboBox с авто-обновлением из SystemTopologyEditor."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import QComboBox, QWidget


class CrossTabComboBox(QComboBox):
    """ComboBox, авто-обновляющийся при изменении секции editor.

    Подписывается на editor.subscribe(section, callback) для реактивного
    обновления содержимого при изменениях в любой вкладке.

    provider_fn — callable без аргументов, возвращает актуальный list[str].
    При изменении секции editor вызывает _refresh(), который перестраивает
    список и сохраняет текущий выбор (если элемент ещё существует).

    Пример использования:
        combo = CrossTabComboBox(
            editor=topology_editor,
            provider_fn=topology_editor.process_names,
            section=SECTION_PROCESSES,
            parent=self,
        )
    """

    def __init__(
        self,
        editor: Any,
        provider_fn: Callable[[], list[str]],
        section: str,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._provider = provider_fn
        self._editor = editor
        self._section = section

        # Подписаться на изменения указанной секции
        editor.subscribe(section, self._refresh)

        # Заполнить список при создании виджета
        self._refresh()

    def _refresh(self) -> None:
        """Перестроить items, сохранив текущий выбор."""
        current = self.currentText()

        # Блокируем сигналы, чтобы не генерировать ложные currentIndexChanged
        self.blockSignals(True)
        self.clear()
        items = self._provider()
        self.addItems(items)

        # Восстанавливаем выбор, если элемент ещё присутствует в списке
        idx = self.findText(current)
        if idx >= 0:
            self.setCurrentIndex(idx)

        self.blockSignals(False)

    def disconnect_editor(self) -> None:
        """Отписаться от editor при уничтожении виджета.

        Вызывает editor.unsubscribe(), если метод доступен.
        """
        if self._editor and hasattr(self._editor, "unsubscribe"):
            self._editor.unsubscribe(self._section, self._refresh)
