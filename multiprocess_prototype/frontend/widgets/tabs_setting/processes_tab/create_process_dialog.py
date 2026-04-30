"""CreateProcessDialog — диалог создания процесса или воркера."""
from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# Известные классы процессов прототипа
KNOWN_PROCESS_CLASSES: dict[str, str] = {
    "CameraProcess": "multiprocess_prototype.backend.processes.camera.process.CameraProcess",
    "ProcessorProcess": "multiprocess_prototype.backend.processes.processor.process.ProcessorProcess",
    "RendererProcess": "multiprocess_prototype.backend.processes.renderer.process.RendererProcess",
    "RobotProcess": "multiprocess_prototype.backend.processes.robot.process.RobotProcess",
    "DatabaseProcess": "multiprocess_prototype.backend.processes.database.process.DatabaseProcess",
}

PRIORITY_OPTIONS = ["low", "normal", "high", "urgent"]

WORKER_TYPE_OPTIONS = ["camera_capture", "frame_processor", "data_writer", "custom"]


class CreateProcessDialog(QDialog):
    """Диалог создания нового процесса или воркера.

    Содержит QTabWidget с двумя табами:
    - "Процесс" — имя, класс, приоритет, автозапуск
    - "Воркер"  — имя воркера, процесс-владелец, тип, enabled, целевой интервал

    По умолчанию активен таб "Процесс" (backward-compatible).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Создать процесс / воркер")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        # Таб-виджет
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_process_tab(), "Процесс")
        self._tabs.addTab(self._build_worker_tab(), "Воркер")
        layout.addWidget(self._tabs)

        # Кнопки OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Построение табов
    # ------------------------------------------------------------------

    def _build_process_tab(self) -> QWidget:
        """Создать вкладку 'Процесс'."""
        widget = QWidget()
        form = QFormLayout(widget)

        # Имя процесса
        self._proc_name_edit = QLineEdit()
        self._proc_name_edit.setPlaceholderText("например: camera_2")
        form.addRow("Имя процесса:", self._proc_name_edit)

        # Класс процесса
        self._class_combo = QComboBox()
        self._class_combo.addItems(KNOWN_PROCESS_CLASSES.keys())
        form.addRow("Класс:", self._class_combo)

        # Приоритет
        self._priority_combo = QComboBox()
        self._priority_combo.addItems(PRIORITY_OPTIONS)
        self._priority_combo.setCurrentText("normal")
        form.addRow("Приоритет:", self._priority_combo)

        # Автозапуск
        self._auto_start_check = QCheckBox()
        self._auto_start_check.setChecked(True)
        form.addRow("Автозапуск:", self._auto_start_check)

        return widget

    def _build_worker_tab(self) -> QWidget:
        """Создать вкладку 'Воркер'."""
        widget = QWidget()
        form = QFormLayout(widget)

        # Имя воркера
        self._worker_name_edit = QLineEdit()
        self._worker_name_edit.setPlaceholderText("например worker_decode")
        form.addRow("Имя воркера:", self._worker_name_edit)

        # Процесс-владелец
        self._process_ref_combo = QComboBox()
        form.addRow("Процесс-владелец:", self._process_ref_combo)

        # Тип воркера
        self._worker_type_combo = QComboBox()
        self._worker_type_combo.addItems(WORKER_TYPE_OPTIONS)
        form.addRow("Тип воркера:", self._worker_type_combo)

        # Enabled
        self._worker_enabled_check = QCheckBox()
        self._worker_enabled_check.setChecked(True)
        form.addRow("Enabled:", self._worker_enabled_check)

        # Целевой интервал, мс
        self._target_interval_spin = QSpinBox()
        self._target_interval_spin.setRange(0, 10000)
        self._target_interval_spin.setValue(0)
        self._target_interval_spin.setToolTip("0 = максимальная скорость")
        form.addRow("Целевой интервал, мс:", self._target_interval_spin)

        return widget

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def set_available_processes(self, names: list[str]) -> None:
        """Заполнить QComboBox процессов-владельцев.

        Args:
            names: Список имён доступных процессов.
        """
        self._process_ref_combo.clear()
        self._process_ref_combo.addItems(names)

    def set_mode(self, mode: str) -> None:
        """Переключить активный таб.

        Args:
            mode: "process" — активировать таб Процесс,
                  "worker"  — активировать таб Воркер.
        """
        if mode == "worker":
            self._tabs.setCurrentIndex(1)
        else:
            self._tabs.setCurrentIndex(0)

    def get_data(self) -> dict:
        """Получить данные активного таба.

        Returns:
            Для таба "Процесс":
                {"mode": "process", "process_name": str, "class_path": str,
                 "priority": str, "auto_start": bool}
            Для таба "Воркер":
                {"mode": "worker", "worker_name": str, "process_ref": str,
                 "worker_type": str, "enabled": bool, "target_interval_ms": int}
        """
        if self._tabs.currentIndex() == 0:
            # Таб "Процесс"
            class_name = self._class_combo.currentText()
            return {
                "mode": "process",
                "process_name": self._proc_name_edit.text().strip(),
                "class_path": KNOWN_PROCESS_CLASSES.get(class_name, ""),
                "priority": self._priority_combo.currentText(),
                "auto_start": self._auto_start_check.isChecked(),
            }
        else:
            # Таб "Воркер"
            return {
                "mode": "worker",
                "worker_name": self._worker_name_edit.text().strip(),
                "process_ref": self._process_ref_combo.currentText(),
                "worker_type": self._worker_type_combo.currentText(),
                "enabled": self._worker_enabled_check.isChecked(),
                "target_interval_ms": self._target_interval_spin.value(),
            }


__all__ = ["CreateProcessDialog", "KNOWN_PROCESS_CLASSES"]
