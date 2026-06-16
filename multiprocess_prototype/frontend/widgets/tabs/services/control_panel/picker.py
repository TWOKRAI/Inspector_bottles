"""NodePickerDialog — диалог «Добавить из ноды» (дашборд-пикер пульта).

Выбор: нода активной топологии → режим (Параметр / Действие) → поле/команда →
proxy-контрол. Тонкий слой Qt: вся логика перечисления и построения спеки — в
``catalog.py`` (NodeCatalog + make_param_spec/make_action_spec), поэтому диалог
только собирает значения и зовёт билдеры.

Результат — спецификация контрола (dict) через ``result_spec()`` после Accepted.
"""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .catalog import (
    FieldRef,
    NodeCatalog,
    NodeRef,
    control_type_for_field,
    make_action_spec,
    make_param_spec,
)


class NodePickerDialog(QDialog):
    """Пикер «Добавить из ноды»: параметр (правка register-поля) или действие (команда)."""

    def __init__(self, catalog: NodeCatalog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Добавить контрол из ноды")
        self.setMinimumWidth(440)
        self._catalog = catalog
        self._nodes: list[NodeRef] = catalog.nodes()
        self._spec: dict[str, Any] | None = None

        root = QVBoxLayout(self)

        # --- Нода ---
        self._node_combo = QComboBox()
        for n in self._nodes:
            self._node_combo.addItem(n.label, n)
        self._node_combo.currentIndexChanged.connect(self._reload_node)
        node_form = QFormLayout()
        node_form.addRow("Нода:", self._node_combo)
        root.addLayout(node_form)

        # --- Режим ---
        mode_box = QGroupBox("Что выносим")
        mode_lay = QVBoxLayout(mode_box)
        self._mode_param = QRadioButton("Параметр (правка поля — live)")
        self._mode_action = QRadioButton("Действие (команда — триггер/значение)")
        self._mode_param.setChecked(True)
        self._mode_param.toggled.connect(self._reload_node)
        mode_lay.addWidget(self._mode_param)
        mode_lay.addWidget(self._mode_action)
        root.addWidget(mode_box)

        # --- Панель «Параметр» ---
        self._param_box = QGroupBox("Параметр")
        pf = QFormLayout(self._param_box)
        self._field_combo = QComboBox()
        self._field_combo.currentIndexChanged.connect(self._sync_param_type)
        self._param_ctype = QComboBox()  # наполняется под тип поля (_sync_param_type)
        pf.addRow("Поле:", self._field_combo)
        pf.addRow("Тип:", self._param_ctype)
        root.addWidget(self._param_box)

        # --- Панель «Действие» ---
        self._action_box = QGroupBox("Действие")
        af = QFormLayout(self._action_box)
        self._cmd_combo = QComboBox()
        self._action_ctype = QComboBox()
        self._action_ctype.addItem("Кнопка (триггер)", "button")
        self._action_ctype.addItem("Число", "number")
        self._action_ctype.addItem("Слайдер", "slider")
        self._action_ctype.currentIndexChanged.connect(self._sync_action_value_visibility)
        self._value_arg = QLineEdit()
        self._value_arg.setPlaceholderText("имя аргумента (напр. pct) — для слайдера/числа")
        self._cmd_args = QLineEdit()
        self._cmd_args.setPlaceholderText('фикс. аргументы JSON, напр. {"device_id": "robot_main"}')
        self._act_min = QDoubleSpinBox()
        self._act_min.setRange(-1e6, 1e6)
        self._act_min.setValue(0.0)
        self._act_max = QDoubleSpinBox()
        self._act_max.setRange(-1e6, 1e6)
        self._act_max.setValue(100.0)
        af.addRow("Команда:", self._cmd_combo)
        af.addRow("Тип:", self._action_ctype)
        af.addRow("Арг значения:", self._value_arg)
        af.addRow("Доп. аргументы:", self._cmd_args)
        af.addRow("Мин:", self._act_min)
        af.addRow("Макс:", self._act_max)
        root.addWidget(self._action_box)

        # --- Подпись + ошибка ---
        self._label_edit = QLineEdit()
        self._label_edit.setPlaceholderText("Подпись (необязательно — по умолчанию из поля/команды)")
        lf = QFormLayout()
        lf.addRow("Подпись:", self._label_edit)
        root.addLayout(lf)
        self._error = QLabel("")
        self._error.setProperty("role", "error")
        self._error.setWordWrap(True)
        root.addWidget(self._error)

        # --- Кнопки ---
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._reload_node()

    # ------------------------------------------------------------------ #

    def _current_node(self) -> NodeRef | None:
        return self._node_combo.currentData()

    def _is_param(self) -> bool:
        return self._mode_param.isChecked()

    def _reload_node(self) -> None:
        """Перестроить списки полей/команд под выбранную ноду и режим."""
        node = self._current_node()
        is_param = self._is_param()
        self._param_box.setVisible(is_param)
        self._action_box.setVisible(not is_param)

        self._field_combo.clear()
        self._cmd_combo.clear()
        if node is None:
            return
        if is_param:
            for f in self._catalog.fields(node.plugin_name):
                self._field_combo.addItem(f"{f.title}  ({f.name})", f)
            self._sync_param_type()
        else:
            for cmd in self._catalog.commands(node.plugin_name):
                self._cmd_combo.addItem(cmd, cmd)
            self._sync_action_value_visibility()

    def _sync_param_type(self) -> None:
        """Тип контрола следует типу register-поля: num→Число/Слайдер, bool→Тумблер, str→Текст."""
        field: FieldRef | None = self._field_combo.currentData()
        self._param_ctype.clear()
        if field is None:
            return
        if field.is_numeric:
            self._param_ctype.addItem("Число", "number")
            self._param_ctype.addItem("Слайдер", "slider")
            self._param_ctype.setEnabled(True)
        elif field.is_bool:
            self._param_ctype.addItem("Тумблер", "toggle")
            self._param_ctype.setEnabled(False)
        else:
            self._param_ctype.addItem("Текст", "text")
            self._param_ctype.setEnabled(False)

    def _sync_action_value_visibility(self) -> None:
        """Поля значения (арг/мин/макс) видны только для слайдера/числа."""
        with_value = self._action_ctype.currentData() in ("number", "slider")
        for w in (self._value_arg, self._cmd_args, self._act_min, self._act_max):
            w.setVisible(True)  # сами строки скрывать не будем — JSON-аргументы полезны и кнопке
        self._value_arg.setEnabled(with_value)
        self._act_min.setEnabled(with_value)
        self._act_max.setEnabled(with_value)

    def _on_accept(self) -> None:
        node = self._current_node()
        if node is None:
            self._error.setText("Нет нод в активной топологии.")
            return
        label = self._label_edit.text().strip()

        if self._is_param():
            field: FieldRef | None = self._field_combo.currentData()
            if field is None:
                self._error.setText("У ноды нет редактируемых register-полей.")
                return
            ctype = self._param_ctype.currentData() or control_type_for_field(field)
            # Стартовое значение — текущее значение поля ноды (из рецепта), а не min.
            current = self._catalog.field_value(node, field.name, field.default)
            self._spec = make_param_spec(node, field, ctype=ctype, label=label, value=current)
            self.accept()
            return

        # action
        command = self._cmd_combo.currentData()
        if not command:
            self._error.setText("У ноды нет команд.")
            return
        try:
            cmd_args = json.loads(self._cmd_args.text()) if self._cmd_args.text().strip() else {}
            if not isinstance(cmd_args, dict):
                raise ValueError("ожидался JSON-объект")
        except (ValueError, json.JSONDecodeError) as exc:
            self._error.setText(f"Доп. аргументы — некорректный JSON: {exc}")
            return
        ctype = self._action_ctype.currentData() or "button"
        self._spec = make_action_spec(
            node,
            command,
            ctype=ctype,
            label=label,
            value_arg=self._value_arg.text().strip() if ctype in ("number", "slider") else "",
            command_args=cmd_args,
            vmin=self._act_min.value() if ctype in ("number", "slider") else None,
            vmax=self._act_max.value() if ctype in ("number", "slider") else None,
        )
        self.accept()

    def result_spec(self) -> dict[str, Any] | None:
        """Спецификация proxy-контрола после Accepted (None если отменён)."""
        return self._spec


__all__ = ["NodePickerDialog"]
