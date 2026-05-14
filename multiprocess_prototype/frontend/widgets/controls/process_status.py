"""ProcessStatusWidget — отображение статусов процессов."""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView
from PySide6.QtCore import Slot
from PySide6.QtGui import QColor


class ProcessStatusWidget(QWidget):
    """Таблица статусов процессов. Обновляется через on_state_updated()."""

    # Цвета статусов
    _STATUS_COLORS = {
        "running": QColor("#4caf50"),  # зелёный
        "ready": QColor("#8bc34a"),  # светло-зелёный
        "stopped": QColor("#9e9e9e"),  # серый
        "error": QColor("#f44336"),  # красный
        "starting": QColor("#ff9800"),  # оранжевый
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._processes: dict[str, dict] = {}  # process_name → {status, pid, ...}
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Процесс", "Статус", "PID"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        layout.addWidget(self._table)

    @Slot(dict)
    def on_state_updated(self, msg_dict: dict) -> None:
        """Обработать state update от процесса.

        msg_dict: {"data_type": "status", "sender": "camera_0", "data": {"status": "running", "pid": 1234}}
        """
        sender = msg_dict.get("sender", "")
        data = msg_dict.get("data", {})
        status = data.get("status", "unknown")
        pid = data.get("pid", "")

        if not sender:
            return

        self._processes[sender] = {"status": status, "pid": str(pid)}
        self._refresh_table()

    def _refresh_table(self) -> None:
        """Перерисовать таблицу."""
        self._table.setRowCount(len(self._processes))

        for row, (name, info) in enumerate(sorted(self._processes.items())):
            # Имя
            name_item = QTableWidgetItem(name)
            self._table.setItem(row, 0, name_item)

            # Статус с цветом
            status = info.get("status", "unknown")
            status_item = QTableWidgetItem(status)
            color = self._STATUS_COLORS.get(status, QColor("#757575"))
            status_item.setForeground(color)
            self._table.setItem(row, 1, status_item)

            # PID
            pid_item = QTableWidgetItem(info.get("pid", ""))
            self._table.setItem(row, 2, pid_item)
