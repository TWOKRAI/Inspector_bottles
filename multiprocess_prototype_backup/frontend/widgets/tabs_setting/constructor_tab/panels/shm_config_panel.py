"""ShmConfigPanel — форма конфигурации SharedMemory для wire-канала конструктора.

Фаза 3: правые панели конструктора.
Панель принимает и возвращает только dict (Dict at Boundary).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class ShmConfigPanel(QWidget):
    """Форма конфигурации SharedMemory для wire-канала.

    Отображает и редактирует четыре поля SHM-конфига:
      - shm_name    — имя SHM региона
      - buffer_slots — количество слотов ring-buffer
      - owner_process — процесс-владелец SHM
      - strategy    — стратегия передачи данных

    Все данные принимаются и возвращаются как dict (Dict at Boundary).
    Pydantic-модели в API не используются.
    """

    # Сигнал эмитируется при изменении любого поля пользователем.
    # Аргумент — актуальный dict конфигурации (get_config()).
    # НЕ эмитируется при программном заполнении (set_config).
    config_changed = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()
        self._connect_signals()

    def _init_ui(self) -> None:
        """Построить layout: QGroupBox с QFormLayout."""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # Группа "SharedMemory"
        group = QGroupBox("SharedMemory", self)
        form = QFormLayout(group)
        form.setContentsMargins(8, 12, 8, 8)
        form.setSpacing(6)

        # Поле: shm_name
        self._shm_name = QLineEdit(self)
        self._shm_name.setPlaceholderText("авто (из wire_key)")
        form.addRow("shm_name:", self._shm_name)

        # Поле: buffer_slots
        self._buffer_slots = QSpinBox(self)
        self._buffer_slots.setMinimum(2)
        self._buffer_slots.setMaximum(32)
        self._buffer_slots.setValue(4)
        form.addRow("buffer_slots:", self._buffer_slots)

        # Поле: owner_process (заполняется при set_config)
        self._owner_process = QComboBox(self)
        form.addRow("owner_process:", self._owner_process)

        # Поле: strategy
        self._strategy = QComboBox(self)
        self._strategy.addItems(["direct", "via_pm"])
        form.addRow("strategy:", self._strategy)

        outer_layout.addWidget(group)
        outer_layout.addStretch()

    def _connect_signals(self) -> None:
        """Подключить сигналы всех полей к общему слоту _on_field_changed."""
        self._shm_name.textChanged.connect(self._on_field_changed)
        self._buffer_slots.valueChanged.connect(self._on_field_changed)
        self._owner_process.currentIndexChanged.connect(self._on_field_changed)
        self._strategy.currentIndexChanged.connect(self._on_field_changed)

    def _on_field_changed(self, *_args: object) -> None:
        """Общий слот: любое поле изменилось пользователем — эмитировать сигнал."""
        self.config_changed.emit(self.get_config())

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def set_config(
        self,
        shm_config: dict,
        source_proc: str,
        target_proc: str,
    ) -> None:
        """Заполнить форму из dict конфига и имён процессов.

        Блокирует сигналы виджетов на время программного заполнения,
        чтобы не вызвать бесконечный цикл обновлений.

        Args:
            shm_config: dict с ключами shm_name, buffer_slots, owner_process, strategy.
            source_proc: имя процесса-источника wire (для owner_process combo).
            target_proc: имя процесса-приёмника wire (для owner_process combo).
        """
        widgets = [self._shm_name, self._buffer_slots, self._owner_process, self._strategy]
        # Блокируем сигналы всех виджетов при программном заполнении
        old_blocked = [w.blockSignals(True) for w in widgets]
        try:
            # shm_name
            self._shm_name.setText(shm_config.get("shm_name", ""))

            # buffer_slots
            slots = shm_config.get("buffer_slots", 4)
            self._buffer_slots.setValue(int(slots))

            # owner_process: заполнить combo уникальными значениями [source, target]
            self._owner_process.clear()
            unique_procs: list[str] = []
            for proc in (source_proc, target_proc):
                if proc and proc not in unique_procs:
                    unique_procs.append(proc)
            self._owner_process.addItems(unique_procs)
            # Выбрать текущего владельца (или первый в списке)
            current_owner = shm_config.get("owner_process", "")
            idx = self._owner_process.findText(current_owner)
            if idx >= 0:
                self._owner_process.setCurrentIndex(idx)

            # strategy
            strategy = shm_config.get("strategy", "direct")
            idx = self._strategy.findText(strategy)
            if idx >= 0:
                self._strategy.setCurrentIndex(idx)
        finally:
            # Восстанавливаем исходное состояние блокировки сигналов
            for w, blocked in zip(widgets, old_blocked):
                w.blockSignals(blocked)

    def get_config(self) -> dict:
        """Собрать и вернуть dict текущего состояния формы.

        Returns:
            dict с ключами: shm_name, buffer_slots, owner_process, strategy.
        """
        return {
            "shm_name": self._shm_name.text(),
            "buffer_slots": self._buffer_slots.value(),
            "owner_process": self._owner_process.currentText(),
            "strategy": self._strategy.currentText(),
        }

    def clear(self) -> None:
        """Сбросить все поля к значениям по умолчанию."""
        widgets = [self._shm_name, self._buffer_slots, self._owner_process, self._strategy]
        old_blocked = [w.blockSignals(True) for w in widgets]
        try:
            self._shm_name.clear()
            self._buffer_slots.setValue(4)
            self._owner_process.clear()
            # Восстановить дефолтные items для strategy
            self._strategy.setCurrentIndex(0)  # "direct"
        finally:
            for w, blocked in zip(widgets, old_blocked):
                w.blockSignals(blocked)


__all__ = ["ShmConfigPanel"]
