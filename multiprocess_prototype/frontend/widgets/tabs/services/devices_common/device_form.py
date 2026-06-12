# -*- coding: utf-8 -*-
"""DeviceFormWidget — переиспользуемая форма полей устройства (без кнопок).

Поля: id (блокируется в режиме edit), name, kind (label), protocol (combo),
transport type (tcp|bridge|rtu) с переключаемой под-формой, params (YAML/JSON).
``get_entry()`` собирает entry dict для device_upsert.

Используется и :class:`DeviceEditorDialog` (модальный), и :class:`AddDevicePage`
(встроенная страница добавления, Фаза D) — единый источник формы, без дублирования.

Refs: plans/device-tree-recipe.md Фаза D
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class DeviceFormWidget(QWidget):
    """Форма полей устройства (без кнопок ОК/Отмена).

    Args:
        kind:          вид устройства (фиксирован для вкладки).
        protocols:     имена протоколов для данного kind.
        robot_devices: robot-устройства реестра (для bridge-транспорта).
        existing:      dict — режим редактирования (id заблокирован), иначе создание.
        parent:        родитель.
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

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()
        root.addLayout(form)

        # ID
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
                self._combo_protocol.addItem(existing["protocol"])
                self._combo_protocol.setCurrentText(existing["protocol"])
        form.addRow("Протокол:", self._combo_protocol)

        # Транспорт
        self._combo_transport = QComboBox()
        self._combo_transport.addItems(["tcp", "bridge", "rtu"])
        form.addRow("Транспорт:", self._combo_transport)

        self._stack = QStackedWidget()
        root.addWidget(self._stack)

        # TCP (index 0)
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
        self._stack.addWidget(tcp_page)

        # Bridge (index 1)
        bridge_page = QWidget()
        bridge_form = QFormLayout(bridge_page)
        self._bridge_combo = QComboBox()
        if robot_devices:
            for rd in robot_devices:
                rid = rd.get("id", "")
                rname = rd.get("name", rid)
                self._bridge_combo.addItem(f"{rname} ({rid})", rid)
        bridge_form.addRow("Робот-носитель:", self._bridge_combo)
        self._stack.addWidget(bridge_page)

        # RTU (index 2, заглушка)
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
        self._stack.addWidget(rtu_page)

        self._combo_transport.currentIndexChanged.connect(self._stack.setCurrentIndex)

        if existing:
            self._load_existing(existing)

        # Params
        root.addWidget(QLabel("Параметры (YAML/JSON dict):"))
        self._params_edit = QPlainTextEdit()
        self._params_edit.setMaximumHeight(100)
        if existing and existing.get("params"):
            import json

            self._params_edit.setPlainText(json.dumps(existing["params"], ensure_ascii=False, indent=2))
        root.addWidget(self._params_edit)

    # ------------------------------------------------------------------ #

    def set_id(self, device_id: str) -> None:
        """Установить id (автогенерация slug из имени в AddDevicePage)."""
        self._edit_id.setText(device_id)

    def id_text(self) -> str:
        return self._edit_id.text().strip()

    def name_text(self) -> str:
        return self._edit_name.text().strip()

    def get_entry(self) -> dict[str, Any]:
        """Собрать entry dict для device_upsert."""
        return {
            "id": self._edit_id.text().strip(),
            "name": self._edit_name.text().strip(),
            "kind": self._kind,
            "protocol": self._combo_protocol.currentText(),
            "transport": self._build_transport(),
            "params": self._parse_params(),
        }

    # ------------------------------------------------------------------ #

    def _load_existing(self, existing: dict) -> None:
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
            bidx = self._bridge_combo.findData(transport.get("bridge", ""))
            if bidx >= 0:
                self._bridge_combo.setCurrentIndex(bidx)

    def _build_transport(self) -> dict[str, Any]:
        ttype = self._combo_transport.currentText()
        if ttype == "tcp":
            return {
                "type": "tcp",
                "host": self._tcp_host.text().strip(),
                "port": self._tcp_port.value(),
                "unit_id": self._tcp_unit.value(),
            }
        if ttype == "bridge":
            return {"type": "bridge", "bridge": self._bridge_combo.currentData() or ""}
        return {"type": "rtu", "serial": self._rtu_serial.text().strip(), "baudrate": self._rtu_baud.value()}

    def _parse_params(self) -> dict[str, Any]:
        text = self._params_edit.toPlainText().strip()
        if not text:
            return {}
        import json

        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass
        try:
            import yaml

            result = yaml.safe_load(text)
            if isinstance(result, dict):
                return result
        except Exception:
            pass
        return {}


__all__ = ["DeviceFormWidget"]
