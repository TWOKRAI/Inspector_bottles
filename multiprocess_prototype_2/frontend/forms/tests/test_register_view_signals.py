"""Тесты RegisterView.field_changed signal (Phase 11, требует pytest-qt)."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QSpinBox

from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_prototype_2.frontend.forms.register_view import RegisterView
from multiprocess_prototype_2.registers.field_info import FieldInfo


# ---------------------------------------------------------------------------
# Вспомогательная функция для создания FieldInfo
# ---------------------------------------------------------------------------

def _make_int_field(
    field_name: str,
    *,
    default: int = 50,
    min_val: int = 0,
    max_val: int = 100,
    plugin_name: str = "color_mask",
    category: str = "processing",
) -> FieldInfo:
    """Создать FieldInfo для int-поля."""
    return FieldInfo(
        plugin_name=plugin_name,
        field_name=field_name,
        field_type=int,
        default=default,
        meta=FieldMeta(description=field_name.capitalize(), min=min_val, max=max_val),
        category=category,
    )


# ---------------------------------------------------------------------------
# Тесты field_changed signal
# ---------------------------------------------------------------------------

class TestRegisterViewSignals:
    def test_field_changed_emitted_on_editor_change(self, qtbot) -> None:
        """field_changed эмитится при программном изменении значения editor."""
        fi = _make_int_field("threshold")
        view = RegisterView([fi])
        qtbot.addWidget(view)

        received = []
        view.field_changed.connect(lambda reg, fld, old, new: received.append((reg, fld, old, new)))

        # Получаем editor и меняем значение через QSpinBox
        editors = view.editors()
        editor = editors["color_mask.threshold"]
        assert isinstance(editor.widget, QSpinBox)

        # Изменяем значение через виджет (имитируем пользовательский ввод)
        editor.widget.setValue(75)

        assert len(received) == 1

    def test_field_changed_carries_old_and_new_values(self, qtbot) -> None:
        """field_changed содержит правильные old и new значения."""
        fi = _make_int_field("gain", default=30, min_val=0, max_val=255)
        view = RegisterView([fi])
        qtbot.addWidget(view)

        received = []
        view.field_changed.connect(lambda reg, fld, old, new: received.append((reg, fld, old, new)))

        editors = view.editors()
        editor = editors["color_mask.gain"]

        initial_value = editor.getter()  # должно быть 30

        # Устанавливаем новое значение
        editor.widget.setValue(90)

        assert len(received) == 1
        reg_name, field_name, old_val, new_val = received[0]
        assert reg_name == "color_mask"
        assert field_name == "gain"
        assert old_val == initial_value
        assert new_val == 90

    def test_set_editor_value_no_signal(self, qtbot) -> None:
        """set_editor_value НЕ эмитит field_changed (подавление при undo/redo)."""
        fi = _make_int_field("brightness", default=10, min_val=0, max_val=200)
        view = RegisterView([fi])
        qtbot.addWidget(view)

        received = []
        view.field_changed.connect(lambda reg, fld, old, new: received.append((reg, fld, old, new)))

        # Программная установка через set_editor_value не должна эмитить сигнал
        view.set_editor_value("color_mask.brightness", 150)

        assert len(received) == 0

    def test_field_changed_carries_register_name(self, qtbot) -> None:
        """register_name в signal совпадает с plugin_name из FieldInfo."""
        fi = _make_int_field("contrast", plugin_name="edge_detector", category="filter")
        view = RegisterView([fi])
        qtbot.addWidget(view)

        received_reg_names = []
        view.field_changed.connect(
            lambda reg, fld, old, new: received_reg_names.append(reg)
        )

        editors = view.editors()
        editor = editors["edge_detector.contrast"]
        editor.widget.setValue(editor.getter() + 1)

        assert received_reg_names == ["edge_detector"]

    def test_field_changed_carries_field_name(self, qtbot) -> None:
        """field_name в signal совпадает с field_name из FieldInfo."""
        fi = _make_int_field("saturation")
        view = RegisterView([fi])
        qtbot.addWidget(view)

        received_field_names = []
        view.field_changed.connect(
            lambda reg, fld, old, new: received_field_names.append(fld)
        )

        editors = view.editors()
        editor = editors["color_mask.saturation"]
        editor.widget.setValue(editor.getter() + 1)

        assert received_field_names == ["saturation"]
