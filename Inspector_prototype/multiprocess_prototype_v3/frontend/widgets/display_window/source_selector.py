"""Комбо-бокс для выбора источника кадров (камера или процессор)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox


class SourceSelectorCombo(QComboBox):
    """ComboBox для выбора активного источника кадров.

    Поддерживает два типа источников:
    - камеры: ``camera_{id}``
    - процессоры: произвольный ref вида ``processor_0.region_0.final``

    Сигналы:
        source_changed(str) — эмитируется при смене выбранного источника.
    """

    # Сигнал: новый source_ref при смене выбора
    source_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Подключаем изменение текста к сигналу source_changed
        self.currentTextChanged.connect(self._on_text_changed)

    # -------------------------------------------------------------------------
    # Публичный API
    # -------------------------------------------------------------------------

    def refresh_sources(
        self,
        cameras: list[int],
        processors: list[str] | None = None,
    ) -> None:
        """Обновить список доступных источников.

        Временно блокирует сигналы, чтобы не было ложных emits
        при очистке и заполнении списка.

        Args:
            cameras: Список ID камер (каждый → ``camera_{id}``).
            processors: Список ref процессоров (добавляются как есть).
        """
        # Блокируем сигналы на время перестройки списка
        self.blockSignals(True)
        self.clear()

        # Добавляем камеры
        for cam_id in cameras:
            self.addItem(f"camera_{cam_id}")

        # Добавляем процессоры (если переданы)
        if processors:
            for proc_ref in processors:
                self.addItem(proc_ref)

        self.blockSignals(False)

    def set_current_source(self, source_ref: str) -> None:
        """Установить текущий источник по source_ref.

        Args:
            source_ref: Строка источника (например ``camera_0``).
                        Если не найден — выбор не меняется.
        """
        index = self.findText(source_ref)
        if index >= 0:
            self.setCurrentIndex(index)

    @property
    def current_source(self) -> str:
        """Текущий выбранный source_ref."""
        return self.currentText()

    # -------------------------------------------------------------------------
    # Приватные методы
    # -------------------------------------------------------------------------

    def _on_text_changed(self, text: str) -> None:
        """Ретранслирует изменение текста в source_changed."""
        self.source_changed.emit(text)


__all__ = ["SourceSelectorCombo"]
