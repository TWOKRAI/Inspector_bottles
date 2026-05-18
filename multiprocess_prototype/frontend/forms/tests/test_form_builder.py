"""Тесты build_form_for_register (cards-представление, ~5 тестов)."""

from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QScrollArea

from multiprocess_framework.modules.data_schema_module import FieldMeta
from multiprocess_prototype.frontend.forms.form_builder import build_form_for_register
from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo


def _fi(
    field_name: str,
    field_type: type = int,
    default=0,
    meta: FieldMeta | None = None,
    plugin_name: str = "test",
    category: str = "",
) -> FieldInfo:
    """Быстрое создание FieldInfo."""
    return FieldInfo(
        plugin_name=plugin_name,
        field_name=field_name,
        field_type=field_type,
        default=default,
        meta=meta,
        category=category,
    )


class TestBuildFormForRegister:
    """Тесты cards-представления."""

    def test_returns_scroll_area_and_editors(self, qtbot):
        """Возвращает QScrollArea и непустой dict editors."""
        fields = [_fi("x", int, 10), _fi("y", int, 20)]
        form, editors = build_form_for_register(fields)
        qtbot.addWidget(form)

        assert isinstance(form, QScrollArea)
        assert len(editors) == 2
        assert "test.x" in editors
        assert "test.y" in editors

    def test_grouping_by_category(self, qtbot):
        """Поля разных категорий попадают в разные QGroupBox."""
        fields = [
            _fi("a", int, 1, category="system"),
            _fi("b", int, 2, category="camera"),
        ]
        titles = {"system": "Система", "camera": "Камера"}
        form, editors = build_form_for_register(
            fields,
            category_titles=titles,
        )
        qtbot.addWidget(form)

        # Ищем QGroupBox внутри scroll area
        container = form.widget()
        group_boxes = container.findChildren(QGroupBox)
        group_names = {gb.title() for gb in group_boxes}

        assert "Система" in group_names
        assert "Камера" in group_names

    def test_no_grouping(self, qtbot):
        """group_by_category=False — все поля в одном layout без QGroupBox."""
        fields = [
            _fi("a", int, 1, category="system"),
            _fi("b", int, 2, category="camera"),
        ]
        form, editors = build_form_for_register(
            fields,
            group_by_category=False,
        )
        qtbot.addWidget(form)

        container = form.widget()
        group_boxes = container.findChildren(QGroupBox)
        assert len(group_boxes) == 0

    def test_editors_keys_match_fields(self, qtbot):
        """Ключи editors = plugin_name.field_name."""
        fields = [_fi("alpha", plugin_name="plug1"), _fi("beta", plugin_name="plug2")]
        form, editors = build_form_for_register(fields)
        qtbot.addWidget(form)

        assert "plug1.alpha" in editors
        assert "plug2.beta" in editors

    def test_empty_fields_returns_empty_editors(self, qtbot):
        """Пустой список полей → пустой dict editors."""
        form, editors = build_form_for_register([])
        qtbot.addWidget(form)

        assert editors == {}

    def test_integration_with_capture_plugin(self, qtbot):
        """build_form_for_register с реальным CapturePluginConfig."""
        from Plugins.sources.capture.config import CapturePluginConfig
        from multiprocess_framework.modules.registers_module.core.field_info import extract_fields

        fields = extract_fields("capture", CapturePluginConfig)
        form, editors = build_form_for_register(fields)
        qtbot.addWidget(form)

        assert len(editors) > 0
        # Проверяем, что для каждого поля есть editor
        for fi in fields:
            key = f"capture.{fi.field_name}"
            assert key in editors, f"Нет editor для {key}"
