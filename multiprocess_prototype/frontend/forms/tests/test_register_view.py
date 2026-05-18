"""Тесты RegisterView — reparenting + shared editors (~4 теста)."""

from __future__ import annotations

from PySide6.QtWidgets import QSpinBox, QStackedWidget

from multiprocess_framework.modules.data_schema_module import FieldMeta
from multiprocess_prototype.frontend.forms.register_view import RegisterView
from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewMode
from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo


def _fi(
    field_name: str,
    field_type: type = int,
    default=0,
    meta: FieldMeta | None = None,
    plugin_name: str = "test",
    category: str = "",
) -> FieldInfo:
    return FieldInfo(
        plugin_name=plugin_name,
        field_name=field_name,
        field_type=field_type,
        default=default,
        meta=meta,
        category=category,
    )


class TestRegisterView:
    """Тесты RegisterView."""

    def test_cards_to_table_reparenting(self, qtbot):
        """set_mode(TABLE) — виджеты переезжают в QTableWidget."""
        fields = [_fi("x", int, 42, meta=FieldMeta("Координата X", min=0, max=100))]
        view = RegisterView(fields)
        qtbot.addWidget(view)

        # Начальный режим — cards
        assert view.mode() == ViewMode.CARDS

        # Переключаем в table
        view.set_mode(ViewMode.TABLE)
        assert view.mode() == ViewMode.TABLE

        # Виджет должен быть в table
        editors = view.editors()
        editor = editors["test.x"]
        assert isinstance(editor.widget, QSpinBox)
        assert editor.getter() == 42

    def test_shared_editors_preserve_state(self, qtbot):
        """Изменение значения в cards → переключение в table → getter() возвращает то же значение."""
        fields = [_fi("val", int, 10, meta=FieldMeta("Значение", min=0, max=999))]
        view = RegisterView(fields)
        qtbot.addWidget(view)

        editors = view.editors()
        editor = editors["test.val"]

        # Изменяем значение в cards-режиме
        editor.setter(77)
        assert editor.getter() == 77

        # Переключаем в table
        view.set_mode(ViewMode.TABLE)

        # Значение сохранилось (тот же виджет)
        assert editor.getter() == 77

        # Переключаем обратно в cards
        view.set_mode(ViewMode.CARDS)
        assert editor.getter() == 77

    def test_mode_changed_signal(self, qtbot):
        """mode_changed эмитится при переключении."""
        fields = [_fi("x")]
        view = RegisterView(fields)
        qtbot.addWidget(view)

        received = []
        view.mode_changed.connect(lambda m: received.append(m))

        view.set_mode(ViewMode.TABLE)
        assert len(received) == 1
        assert received[0] == ViewMode.TABLE.value

    def test_initial_mode_table(self, qtbot):
        """initial_mode=TABLE — начинаем в табличном режиме."""
        fields = [_fi("x", int, 5)]
        view = RegisterView(fields, initial_mode=ViewMode.TABLE)
        qtbot.addWidget(view)

        assert view.mode() == ViewMode.TABLE
        # Stack на нужной странице
        stack = view.findChild(QStackedWidget)
        assert stack is not None
        assert stack.currentIndex() == 1
