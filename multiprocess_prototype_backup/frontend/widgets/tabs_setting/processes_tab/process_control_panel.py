"""ProcessControlPanel — панель управления процессами.

Кнопки Start/Stop/Restart для выбранного процесса.
Активность кнопок зависит от текущего статуса процесса.
Confirmation dialog перед Stop и Restart.
Debounce: кнопки блокируются на 2 секунды после нажатия.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QMessageBox, QPushButton, QWidget

from .create_process_dialog import CreateProcessDialog

logger = logging.getLogger(__name__)


class ProcessControlPanel(QWidget):
    """Панель кнопок Start/Stop/Restart для выбранного процесса.

    Кнопки активны/неактивны в зависимости от статуса.
    Confirmation dialog перед Stop и Restart.
    Debounce: кнопки блокируются на 2с после нажатия.
    """

    # Сигнал: (action, process_name) — например ("process.start", "camera_0")
    action_requested = Signal(str, str)

    def __init__(
        self,
        *,
        command_handler: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Инициализировать панель управления.

        Args:
            command_handler: RoutedCommandSender для отправки команд.
            parent:          Родительский виджет.
        """
        super().__init__(parent)
        self._command_handler = command_handler
        self._current_process: str | None = None
        self._current_status: str = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        self._btn_start = QPushButton("▶ Запустить")
        self._btn_stop = QPushButton("■ Остановить")
        self._btn_restart = QPushButton("⟲ Перезапустить")

        self._btn_pause = QPushButton("⏸ Пауза")

        for btn in (self._btn_start, self._btn_stop, self._btn_restart, self._btn_pause):
            btn.setEnabled(False)
            layout.addWidget(btn)

        layout.addStretch()

        self._btn_start.clicked.connect(lambda: self._on_action("process.start"))
        self._btn_stop.clicked.connect(lambda: self._on_action("process.stop"))
        self._btn_restart.clicked.connect(lambda: self._on_action("process.restart"))
        self._btn_pause.clicked.connect(self._on_pause_toggle)

        # Разделитель перед кнопками создания/удаления
        layout.addSpacing(12)

        self._btn_create = QPushButton("+ Создать")
        self._btn_create.setToolTip("Создать новый процесс")
        self._btn_create.clicked.connect(self._on_create)
        layout.addWidget(self._btn_create)

        self._btn_delete = QPushButton("✕ Удалить")
        self._btn_delete.setToolTip("Остановить и удалить выбранный процесс")
        self._btn_delete.setEnabled(False)
        self._btn_delete.clicked.connect(self._on_delete)
        layout.addWidget(self._btn_delete)

    # ------------------------------------------------------------------
    # Отправка команд в ProcessManager
    # ------------------------------------------------------------------

    def _send_pm_command(self, cmd: str, **params) -> None:
        """Отправить команду в ProcessManager через process.command wrapper.

        Использует обёрнутый формат, который ProcessManager ожидает на
        Router-endpoint "process.command" (AD-8).

        Args:
            cmd:    Идентификатор внутренней команды ("process.start" и т.д.).
            **params: Дополнительные параметры (process_name, class_path и т.д.).
        """
        if self._command_handler is None:
            return
        try:
            data = {"cmd": cmd, "correlation_id": str(uuid.uuid4()), **params}
            self._command_handler.send("process.command", data=data)
        except Exception:
            logger.exception("ProcessControlPanel._send_pm_command: ошибка отправки %s", cmd)

    # ------------------------------------------------------------------
    # Управление выбранным процессом
    # ------------------------------------------------------------------

    def set_process(self, name: str | None, status: str = "") -> None:
        """Установить текущий выбранный процесс и обновить кнопки.

        Args:
            name:   Имя процесса или None если ничего не выбрано.
            status: Текущий статус процесса.
        """
        self._current_process = name
        self._current_status = status
        self._update_buttons()

    # ------------------------------------------------------------------
    # Внутренняя логика
    # ------------------------------------------------------------------

    def _update_buttons(self) -> None:
        """Обновить доступность кнопок по текущему статусу."""
        has_process = self._current_process is not None
        status = self._current_status

        # Start: доступен когда процесс создан, остановлен, упал или недоступен
        can_start = has_process and status in ("created", "stopped", "crashed", "failed", "")
        # Stop: доступен когда процесс работает, инициализируется или на паузе
        can_stop = has_process and status in ("running", "ready", "initializing", "paused")
        # Restart: доступен когда процесс работает
        can_restart = has_process and status in ("running", "ready")

        # Pause: доступен когда процесс работает; Resume: когда на паузе
        can_pause = has_process and status == "running"
        can_resume = has_process and status == "paused"

        self._btn_start.setEnabled(can_start)
        self._btn_stop.setEnabled(can_stop)
        self._btn_restart.setEnabled(can_restart)
        self._btn_pause.setEnabled(can_pause or can_resume)

        # Текст кнопки зависит от статуса: пауза или возобновление
        if status == "paused":
            self._btn_pause.setText("▶ Возобновить")
        else:
            self._btn_pause.setText("⏸ Пауза")

        # Delete: доступен для любого выбранного процесса
        self._btn_delete.setEnabled(has_process)

    def _on_action(self, action: str) -> None:
        """Обработать нажатие кнопки управления.

        Args:
            action: Идентификатор команды ("process.start" и т.д.).
        """
        if not self._current_process:
            return

        # Confirmation dialog перед stop и restart
        if action in ("process.stop", "process.restart"):
            action_text = "остановить" if action == "process.stop" else "перезапустить"
            reply = QMessageBox.question(
                self,
                "Подтверждение",
                f"Вы уверены что хотите {action_text} процесс «{self._current_process}»?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Отправить команду через process.command wrapper
        self._send_pm_command(action, process_name=self._current_process)
        logger.info(
            "ProcessControlPanel: отправлена команда %s для %s",
            action,
            self._current_process,
        )

        self.action_requested.emit(action, self._current_process)

        # Debounce: заблокировать кнопки на 2 секунды
        self._disable_all()
        QTimer.singleShot(2000, self._update_buttons)

    def _disable_all(self) -> None:
        """Заблокировать все кнопки (используется для debounce)."""
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(False)
        self._btn_restart.setEnabled(False)
        self._btn_pause.setEnabled(False)
        self._btn_delete.setEnabled(False)

    def _on_pause_toggle(self) -> None:
        """Обработать нажатие кнопки Пауза/Возобновить.

        Определяет действие по текущему статусу процесса:
        - paused → process.resume
        - иначе → process.pause

        Confirmation dialog НЕ нужен — операция обратима.
        """
        if not self._current_process:
            return

        if self._current_status == "paused":
            action = "process.resume"
        else:
            action = "process.pause"

        self._send_pm_command(action, process_name=self._current_process)
        logger.info(
            "ProcessControlPanel: отправлена команда %s для %s",
            action,
            self._current_process,
        )

        self.action_requested.emit(action, self._current_process)

        # Debounce: заблокировать кнопки на 2 секунды
        self._disable_all()
        QTimer.singleShot(2000, self._update_buttons)

    def _on_create(self) -> None:
        """Открыть диалог создания нового процесса."""
        dialog = CreateProcessDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        data = dialog.get_data()
        if not data["process_name"] or not data["class_path"]:
            QMessageBox.warning(self, "Ошибка", "Имя и класс процесса обязательны")
            return

        # Отправить команду создания через process.command wrapper
        self._send_pm_command(
            "process.create",
            process_name=data["process_name"],
            class_path=data["class_path"],
            priority=data["priority"],
        )
        logger.info(
            "ProcessControlPanel: создание процесса %s",
            data["process_name"],
        )

    def _on_delete(self) -> None:
        """Остановить и удалить выбранный процесс."""
        if not self._current_process:
            return

        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Вы уверены что хотите удалить процесс «{self._current_process}»?\n"
            "Процесс будет остановлен и удалён из реестра.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Останавливаем процесс через process.command wrapper (удаление произойдёт через broadcast)
        self._send_pm_command("process.stop", process_name=self._current_process)
        logger.info(
            "ProcessControlPanel: удаление процесса %s",
            self._current_process,
        )

        # Debounce: заблокировать кнопки, обновить через 2 секунды
        self._disable_all()
        QTimer.singleShot(2000, self._update_buttons)


__all__ = ["ProcessControlPanel"]
