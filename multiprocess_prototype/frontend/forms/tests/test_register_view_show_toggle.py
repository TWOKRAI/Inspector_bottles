# -*- coding: utf-8 -*-
"""Тесты RegisterView: параметр show_toggle.

Проверяют, что ``show_toggle=False`` скрывает встроенный тумблер, но
``set_mode()`` продолжает работать.

См. ADR-126, Phase 3.4.
"""

from __future__ import annotations

import pytest

from multiprocess_prototype.frontend.forms.register_view import RegisterView
from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewMode


def _make_minimal_field_info() -> list:
    """Создать минимальный список FieldInfo для RegisterView."""
    from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo

    return [
        FieldInfo(
            plugin_name="test",
            field_name="value",
            field_type=int,
            default=0,
            category="general",
        ),
    ]


@pytest.fixture
def field_infos() -> list:
    return _make_minimal_field_info()


class TestRegisterViewShowToggle:
    """Тесты параметра show_toggle в RegisterView."""

    def test_default_show_toggle_visible(self, qtbot, field_infos) -> None:
        """По умолчанию тумблер виден."""
        view = RegisterView(field_infos)
        qtbot.addWidget(view)
        view.show()

        assert view._toggle.isVisible() is True

    def test_show_toggle_false_hides(self, qtbot, field_infos) -> None:
        """show_toggle=False скрывает тумблер."""
        view = RegisterView(field_infos, show_toggle=False)
        qtbot.addWidget(view)
        view.show()

        assert view._toggle.isVisible() is False

    def test_show_toggle_false_still_allows_set_mode(
        self,
        qtbot,
        field_infos,
    ) -> None:
        """set_mode() работает даже при скрытом тумблере."""
        view = RegisterView(field_infos, show_toggle=False)
        qtbot.addWidget(view)

        view.set_mode(ViewMode.TABLE)
        assert view.mode() == ViewMode.TABLE

        view.set_mode(ViewMode.CARDS)
        assert view.mode() == ViewMode.CARDS
