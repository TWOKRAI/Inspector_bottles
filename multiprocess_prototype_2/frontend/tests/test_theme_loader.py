"""Тесты для theme_loader — загрузка темы innotech_theme в v2."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from multiprocess_framework.modules.frontend_module.managers.theme_manager import ThemeManager
from multiprocess_prototype_2.frontend.styles.theme_loader import create_theme_manager

# Путь к директории styles/ в v2
# __file__ = .../multiprocess_prototype_2/frontend/tests/test_theme_loader.py
# parents[0] = tests/, parents[1] = frontend/
_STYLES_DIR = Path(__file__).resolve().parents[1] / "styles"
_THEME_NAME = "innotech_theme"


class TestCreateThemeManager:
    """Тесты фабричной функции create_theme_manager."""

    def test_returns_theme_manager_instance(self) -> None:
        """create_theme_manager() возвращает экземпляр ThemeManager."""
        tm = create_theme_manager()
        assert isinstance(tm, ThemeManager)

    def test_styles_dir_points_to_v2(self) -> None:
        """ThemeManager указывает на styles/ директорию v2."""
        tm = create_theme_manager()
        assert tm.styles_dir == _STYLES_DIR
        assert tm.styles_dir.is_dir()


class TestAvailableThemes:
    """Тесты списка доступных тем."""

    def test_innotech_theme_in_available(self) -> None:
        """available_themes() содержит 'innotech_theme'."""
        tm = create_theme_manager()
        themes = tm.available_themes()
        assert _THEME_NAME in themes

    def test_available_themes_is_sorted(self) -> None:
        """available_themes() возвращает отсортированный список."""
        tm = create_theme_manager()
        themes = tm.available_themes()
        assert themes == sorted(themes)


class TestReadTheme:
    """Тесты чтения QSS темы."""

    def test_read_theme_returns_nonempty_string(self) -> None:
        """read_theme('innotech_theme') возвращает непустую строку."""
        tm = create_theme_manager()
        qss = tm.read_theme(_THEME_NAME)
        assert qss is not None
        assert isinstance(qss, str)
        assert len(qss) > 0

    def test_read_theme_contains_qss_content(self) -> None:
        """Прочитанный QSS содержит ожидаемые CSS-правила."""
        tm = create_theme_manager()
        qss = tm.read_theme(_THEME_NAME)
        assert qss is not None
        # Проверяем наличие базовых секций темы
        assert "QPushButton" in qss
        assert "QWidget" in qss

    def test_read_theme_contains_variables(self) -> None:
        """Прочитанный QSS содержит @-плейсхолдеры переменных."""
        tm = create_theme_manager()
        qss = tm.read_theme(_THEME_NAME)
        assert qss is not None
        assert "@text_0" in qss
        assert "@accent" in qss

    def test_read_theme_line_count(self) -> None:
        """main.qss содержит не менее 700 строк."""
        tm = create_theme_manager()
        qss = tm.read_theme(_THEME_NAME)
        assert qss is not None
        line_count = len(qss.splitlines())
        assert line_count >= 700, f"Ожидалось >= 700 строк, получено {line_count}"

    def test_read_nonexistent_theme_returns_none(self) -> None:
        """read_theme() для несуществующей темы возвращает None."""
        tm = create_theme_manager()
        result = tm.read_theme("nonexistent_theme_xyz")
        assert result is None


class TestResolveQss:
    """Тесты подстановки переменных в QSS-шаблон."""

    def _load_variables(self) -> dict[str, str]:
        """Загрузить переменные напрямую из variables.yaml."""
        yaml_path = _STYLES_DIR / "themes" / _THEME_NAME / "variables.yaml"
        with open(yaml_path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        return {k: str(v) for k, v in loaded.items()}

    def test_resolve_replaces_bg_deep(self) -> None:
        """resolve_qss заменяет @bg_deep на реальное значение цвета."""
        variables = self._load_variables()
        template = "background: @bg_deep;"
        result = ThemeManager.resolve_qss(template, variables)
        assert "@bg_deep" not in result
        assert variables["bg_deep"] in result

    def test_resolve_replaces_accent(self) -> None:
        """resolve_qss заменяет @accent на реальный hex-цвет."""
        variables = self._load_variables()
        template = "border: 1px solid @accent;"
        result = ThemeManager.resolve_qss(template, variables)
        assert "@accent" not in result
        assert variables["accent"] in result

    def test_resolve_full_theme(self) -> None:
        """resolve_qss применяется к полному QSS без @-плейсхолдеров в итоге."""
        tm = create_theme_manager()
        qss = tm.read_theme(_THEME_NAME)
        assert qss is not None

        variables = self._load_variables()
        resolved = ThemeManager.resolve_qss(qss, variables)

        # После подстановки не должно остаться известных плейсхолдеров
        for var_name in variables:
            assert f"@{var_name}" not in resolved, (
                f"Плейсхолдер @{var_name} не был заменён"
            )

    def test_resolve_unknown_placeholder_stays(self) -> None:
        """Неизвестный плейсхолдер остаётся без изменений (безопасный fallback)."""
        template = "color: @unknown_variable_xyz;"
        result = ThemeManager.resolve_qss(template, {})
        assert "@unknown_variable_xyz" in result

    def test_variables_yaml_contains_expected_keys(self) -> None:
        """variables.yaml содержит ключевые переменные палитры."""
        variables = self._load_variables()
        expected_keys = [
            "bg_deep", "bg_mid", "bg_hi",
            "text_0", "text_1", "text_2",
            "accent", "accent_hi", "accent_lo",
            "danger", "success", "warn",
            "font_family", "font_family_mono",
        ]
        for key in expected_keys:
            assert key in variables, f"Ключ '{key}' отсутствует в variables.yaml"
