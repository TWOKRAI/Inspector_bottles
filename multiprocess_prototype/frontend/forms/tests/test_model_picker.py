"""Тесты кастомного виджета model_picker (динамический dropdown моделей).

Проверяют B1-фикс: widget="model_picker" → kind резолвится → builder вызывается
и строит QComboBox со списком из data/models.
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox

from multiprocess_framework.modules.data_schema_module import FieldMeta
from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo
from multiprocess_prototype.frontend.forms import register_model_picker
from multiprocess_prototype.frontend.forms import model_picker as mp
from multiprocess_prototype.frontend.forms.factory import CardsFieldFactory


def _fi(default: str = "") -> FieldInfo:
    return FieldInfo(
        plugin_name="ml_inference",
        field_name="model",
        field_type=str,
        default=default,
        meta=FieldMeta("Модель", widget="model_picker"),
        category="",
    )


def test_resolve_kind_model_picker():
    assert CardsFieldFactory.resolve_kind(_fi()) == "model_picker"


def test_builder_creates_combobox(qtbot):
    register_model_picker()  # идемпотентно
    editor = CardsFieldFactory.create(_fi())
    qtbot.addWidget(editor.widget)
    assert isinstance(editor.widget, QComboBox)
    # всегда есть пункт «модель не выбрана»
    assert editor.widget.itemText(0) == ""
    assert callable(editor.getter)


def test_dropdown_lists_scanned_models(qtbot, tmp_path, monkeypatch):
    """Builder показывает модели, найденные ModelRegistry в data/models."""
    # подменяем папку моделей на tmp с одной фиктивной записью
    (tmp_path / "m1.onnx").write_bytes(b"\x00")
    (tmp_path / "m1.yaml").write_text("name: M1\nweights: m1.onnx\n", encoding="utf-8")
    monkeypatch.setattr(mp, "_MODELS_DIR", tmp_path)

    register_model_picker()
    editor = CardsFieldFactory.create(_fi())
    qtbot.addWidget(editor.widget)
    items = [editor.widget.itemText(i) for i in range(editor.widget.count())]
    assert "m1" in items
