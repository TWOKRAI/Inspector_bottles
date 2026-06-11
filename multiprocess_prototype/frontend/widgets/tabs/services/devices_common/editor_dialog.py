# -*- coding: utf-8 -*-
"""DeviceEditorDialog — диалог создания/редактирования устройства.

Поля: id (только при создании), name, kind (фиксирован), protocol (комбо),
transport type (tcp|bridge|rtu) с переключаемой формой:
  - tcp: host, port, unit_id
  - bridge: комбо робот-устройств из реестра
  - rtu: заглушка (serial/baudrate, disabled)
params: QPlainTextEdit с YAML/JSON dict.

Результат — entry dict для device_upsert.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class DeviceEditorDialog(QDialog):
    """Диалог создания/редактирования записи реестра устройств.

    Args:
        kind: вид устройства (фиксирован для вкладки).
        protocols: список имён протоколов для данного kind.
        robot_devices: список robot-устройств из реестра (для bridge-транспорта).
        existing: если dict — режим редактирования (id заблокирован).
        parent: родительский виджет.
    """

    def __init__(
        self,
        *,
        kind: str,
        protocols: list[str] | None = None,
        robot_devices: list[dict] | None = None,
        existing: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._kind = kind
        self._is_edit = existing is not None
        self.setWindowTitle("Изменить устройство" if self._is_edit else "Добавить устройство")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        layout.addLayout(form)

        # ID (только создание)
        self._edit_id = QLineEdit()
        if self._is_edit:
            self._edit_id.setText(existing.get("id", ""))  # type: ignore[union-attr]
            self._edit_id.setEnabled(False)
        form.addRow("ID устройства:", self._edit_id)

        # Имя
        self._edit_name = QLineEdit()
        if existing:
            self._edit_name.setText(existing.get("name", ""))
        form.addRow("Название:", self._edit_name)

        # Kind (отображение, не редактируется)
        form.addRow("Тип (kind):", QLabel(kind))

        # Протокол
        self._combo_protocol = QComboBox()
        if protocols:
            self._combo_protocol.addItems(protocols)
        if existing and existing.get("protocol"):
            idx = self._combo_protocol.findText(existing["protocol"])
            if idx >= 0:
                self._combo_protocol.setCurrentIndex(idx)
            else:
                # Протокол не в списке — добавить
                self._combo_protocol.addItem(existing["protocol"])
                self._combo_protocol.setCurrentText(existing["protocol"])
        form.addRow("Протокол:", self._combo_protocol)

        # Тип транспорта
        self._combo_transport = QComboBox()
        self._combo_transport.addItems(["tcp", "bridge", "rtu"])
        form.addRow("Транспорт:", self._combo_transport)

        # Стек страниц для параметров транспорта
        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # --- Страница TCP ---
        tcp_page = QWidget()
        tcp_form = QFormLayout(tcp_page)
        self._tcp_host = QLineEdit("192.168.1.7")
        self._tcp_port = QSpinBox()
        self._tcp_port.setRange(1, 65535)
        self._tcp_port.setValue(502)
        self._tcp_unit = QSpinBox()
        self._tcp_unit.setRange(0, 255)
        self._tcp_unit.setValue(1)
        tcp_form.addRow("Host:", self._tcp_host)
        tcp_form.addRow("Port:", self._tcp_port)
        tcp_form.addRow("Unit ID:", self._tcp_unit)
        self._stack.addWidget(tcp_page)  # index 0

        # --- Страница Bridge ---
        bridge_page = QWidget()
        bridge_form = QFormLayout(bridge_page)
        self._bridge_combo = QComboBox()
        if robot_devices:
            for rd in robot_devices:
                rid = rd.get("id", "")
                rname = rd.get("name", rid)
                self._bridge_combo.addItem(f"{rname} ({rid})", rid)
        bridge_form.addRow("Робот-носитель:", self._bridge_combo)
        self._stack.addWidget(bridge_page)  # index 1

        # --- Страница RTU (заглушка) ---
        rtu_page = QWidget()
        rtu_form = QFormLayout(rtu_page)
        self._rtu_serial = QLineEdit("COM1")
        self._rtu_serial.setEnabled(False)
        self._rtu_baud = QSpinBox()
        self._rtu_baud.setRange(1200, 115200)
        self._rtu_baud.setValue(9600)
        self._rtu_baud.setEnabled(False)
        rtu_form.addRow("Порт:", self._rtu_serial)
        rtu_form.addRow("Скорость:", self._rtu_baud)
        rtu_hint = QLabel("RTU будет доступен позже.")
        rtu_hint.setStyleSheet("color: gray; font-style: italic;")
        rtu_form.addRow(rtu_hint)
        self._stack.addWidget(rtu_page)  # index 2

        self._combo_transport.currentIndexChanged.connect(self._stack.setCurrentIndex)

        # Заполнить из existing
        if existing:
            transport = existing.get("transport", {})
            ttype = transport.get("type", "tcp")
            idx = self._combo_transport.findText(ttype)
            if idx >= 0:
                self._combo_transport.setCurrentIndex(idx)
            if ttype == "tcp":
                self._tcp_host.setText(transport.get("host", "192.168.1.7"))
                self._tcp_port.setValue(int(transport.get("port", 502)))
                self._tcp_unit.setValue(int(transport.get("unit_id", 1)))
            elif ttype == "bridge":
                bridge_id = transport.get("bridge", "")
                bidx = self._bridge_combo.findData(bridge_id)
                if bidx >= 0:
                    self._bridge_combo.setCurrentIndex(bidx)

        # Params (YAML/JSON)
        layout.addWidget(QLabel("Параметры (YAML/JSON dict):"))
        self._params_edit = QPlainTextEdit()
        self._params_edit.setMaximumHeight(100)
        if existing and existing.get("params"):
            import json

            self._params_edit.setPlainText(json.dumps(existing["params"], ensure_ascii=False, indent=2))
        layout.addWidget(self._params_edit)

        # Кнопки OK/Cancel
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_entry(self) -> dict[str, Any]:
        """Собрать entry dict для device_upsert."""
        transport = self._build_transport()
        params = self._parse_params()
        entry: dict[str, Any] = {
            "id": self._edit_id.text().strip(),
            "name": self._edit_name.text().strip(),
            "kind": self._kind,
            "protocol": self._combo_protocol.currentText(),
            "transport": transport,
            "params": params,
        }
        return entry

    def _build_transport(self) -> dict[str, Any]:
        """Собрать dict транспорта из текущей страницы."""
        ttype = self._combo_transport.currentText()
        if ttype == "tcp":
            return {
                "type": "tcp",
                "host": self._tcp_host.text().strip(),
                "port": self._tcp_port.value(),
                "unit_id": self._tcp_unit.value(),
            }
        elif ttype == "bridge":
            return {
                "type": "bridge",
                "bridge": self._bridge_combo.currentData() or "",
            }
        else:  # rtu
            return {
                "type": "rtu",
                "serial": self._rtu_serial.text().strip(),
                "baudrate": self._rtu_baud.value(),
            }

    def _parse_params(self) -> dict[str, Any]:
        """Парс params из текстового поля (YAML или JSON)."""
        text = self._params_edit.toPlainText().strip()
        if not text:
            return {}
        # Пробуем JSON
        import json

        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass
        # Пробуем YAML
        try:
            import yaml

            result = yaml.safe_load(text)
            if isinstance(result, dict):
                return result
        except Exception:
            pass
        return {}
