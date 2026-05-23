# -*- coding: utf-8 -*-
"""
Unit-тесты ThemeManager (Task C3).

Покрываем:
  - load_theme: одиночный .qss файл → setStyleSheet
  - load_theme: модульная папка (несколько .qss) → конкатенация по алфавиту
  - resolve_qss: подстановка @-переменных
  - read_default_variables: загрузка из variables.yaml
  - apply_theme / switch_theme: смена темы → другой QSS применяется
  - hot-reload: повторный вызов apply_theme → setStyleSheet вызван снова
  - отсутствующая тема → read_theme возвращает None, apply_theme → False
  - available_themes: корректный список из файлов и папок
  - read_theme_by_manifest: базовый файл + файлы манифеста в нужном порядке
  - apply_theme_by_manifest: применение по манифесту
  - default_variables_provider: провайдер по умолчанию подхватывается
  - variables.yaml обновляет только известные ключи из провайдера

Изоляция: tmp_path для .qss / .yaml файлов. QApplication мокируется через
unittest.mock.patch чтобы избежать зависимости от дисплея.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from multiprocess_framework.modules.frontend_module.managers.theme_manager import ThemeManager

# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------


def _make_manager(styles_dir: Path, **kwargs) -> ThemeManager:
    """Создаёт ThemeManager с заданной директорией styles/."""
    return ThemeManager(styles_dir=styles_dir, **kwargs)


def _write_qss(path: Path, content: str) -> None:
    """Создаёт директорию (при необходимости) и записывает QSS-файл."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_mock_app() -> MagicMock:
    """Мок QApplication с методом setStyleSheet."""
    app = MagicMock()
    app.setStyleSheet = MagicMock()
    return app


# ---------------------------------------------------------------------------
# Патч QApplication.instance() → мок, чтобы apply_theme не требовал дисплея
# ---------------------------------------------------------------------------

_QAPP_PATH = "multiprocess_framework.modules.frontend_module.managers.theme_manager.QApplication"


# ===========================================================================
# TestReadTheme — чтение QSS без применения
# ===========================================================================


class TestReadTheme:
    """Тесты read_theme(): одиночный файл и модульная папка."""

    def test_read_single_file_theme(self, tmp_path: Path) -> None:
        """
        Given: styles/dark.qss существует с определённым содержимым
        When: read_theme("dark")
        Then: возвращается содержимое файла
        """
        # Given
        styles_dir = tmp_path / "styles"
        _write_qss(styles_dir / "dark.qss", "QWidget { background: #1e1e1e; }")
        manager = _make_manager(styles_dir)

        # When
        result = manager.read_theme("dark")

        # Then
        assert result == "QWidget { background: #1e1e1e; }"

    def test_read_modular_theme_concatenates_alphabetically(self, tmp_path: Path) -> None:
        """
        Given: styles/themes/dark/ содержит a.qss, b.qss, c.qss
        When: read_theme("dark")
        Then: файлы склеены в алфавитном порядке (a, b, c)
        """
        # Given
        themes_dir = tmp_path / "styles" / "themes" / "dark"
        _write_qss(themes_dir / "c.qss", "C")
        _write_qss(themes_dir / "a.qss", "A")
        _write_qss(themes_dir / "b.qss", "B")
        manager = _make_manager(tmp_path / "styles")

        # When
        result = manager.read_theme("dark")

        # Then — алфавитный порядок: a, b, c
        assert result is not None
        parts = result.split("\n")
        assert parts == ["A", "B", "C"]

    def test_read_missing_theme_returns_none(self, tmp_path: Path) -> None:
        """
        Given: тема "nonexistent" отсутствует
        When: read_theme("nonexistent")
        Then: возвращается None
        """
        # Given
        styles_dir = tmp_path / "styles"
        styles_dir.mkdir(parents=True, exist_ok=True)
        manager = _make_manager(styles_dir)

        # When
        result = manager.read_theme("nonexistent")

        # Then
        assert result is None

    def test_modular_theme_takes_priority_over_file(self, tmp_path: Path) -> None:
        """
        Given: существует и styles/dark.qss, и styles/themes/dark/*.qss
        When: read_theme("dark")
        Then: приоритет — модульная папка (возвращается её содержимое)
        """
        # Given
        styles_dir = tmp_path / "styles"
        _write_qss(styles_dir / "dark.qss", "FILE_CONTENT")
        _write_qss(styles_dir / "themes" / "dark" / "main.qss", "MODULAR_CONTENT")
        manager = _make_manager(styles_dir)

        # When
        result = manager.read_theme("dark")

        # Then
        assert result == "MODULAR_CONTENT"


# ===========================================================================
# TestResolveQss — подстановка CSS-переменных
# ===========================================================================


class TestResolveQss:
    """Тесты статического метода resolve_qss()."""

    def test_resolve_single_variable(self) -> None:
        """
        Given: шаблон "@bg_deep" и переменная bg_deep → #111
        When: resolve_qss(template, {"bg_deep": "#111"})
        Then: @bg_deep заменяется на #111
        """
        # Given
        template = "QWidget { background: @bg_deep; }"
        variables = {"bg_deep": "#111"}

        # When
        result = ThemeManager.resolve_qss(template, variables)

        # Then
        assert result == "QWidget { background: #111; }"

    def test_resolve_multiple_variables(self) -> None:
        """
        Given: шаблон с двумя переменными @bg и @fg
        When: resolve_qss с двумя значениями
        Then: оба плейсхолдера заменены
        """
        # Given
        template = "QWidget { background: @bg; color: @fg; }"
        variables = {"bg": "#000", "fg": "#fff"}

        # When
        result = ThemeManager.resolve_qss(template, variables)

        # Then
        assert "background: #000" in result
        assert "color: #fff" in result

    def test_unknown_variable_stays_as_is(self) -> None:
        """
        Given: шаблон с @unknown, которого нет в словаре
        When: resolve_qss({})
        Then: @unknown остаётся без изменений (безопасный fallback)
        """
        # Given
        template = "QWidget { border: @unknown_var; }"

        # When
        result = ThemeManager.resolve_qss(template, {})

        # Then
        assert "@unknown_var" in result

    def test_resolve_empty_variables_returns_template(self) -> None:
        """
        Given: пустой словарь переменных
        When: resolve_qss(template, {})
        Then: шаблон возвращается без изменений
        """
        # Given
        template = "QWidget { color: @fg; }"

        # When
        result = ThemeManager.resolve_qss(template, {})

        # Then
        assert result == template


# ===========================================================================
# TestReadDefaultVariables — загрузка переменных из variables.yaml
# ===========================================================================


class TestReadDefaultVariables:
    """Тесты read_default_variables() — variables.yaml в папке темы."""

    def test_variables_from_yaml_overrides_provider(self, tmp_path: Path) -> None:
        """
        Given: default_variables_provider возвращает {"bg_deep": "#000"},
               variables.yaml содержит {bg_deep: "#fff"}
        When: read_default_variables("dark")
        Then: значение из yaml приоритетнее провайдера
        """
        # Given
        theme_dir = tmp_path / "styles" / "themes" / "dark"
        theme_dir.mkdir(parents=True, exist_ok=True)
        yaml_path = theme_dir / "variables.yaml"
        yaml_path.write_text('bg_deep: "#fff"\n', encoding="utf-8")

        manager = _make_manager(
            tmp_path / "styles",
            default_variables_provider=lambda: {"bg_deep": "#000"},
        )

        # When
        result = manager.read_default_variables("dark")

        # Then — yaml обновил дефолт
        assert result["bg_deep"] == "#fff"

    def test_variables_yaml_only_updates_known_keys(self, tmp_path: Path) -> None:
        """
        Given: провайдер возвращает {"bg": "#000"},
               yaml содержит {bg: "#red", unknown_key: "value"}
        When: read_default_variables("dark")
        Then: "bg" обновлён, "unknown_key" отсутствует в результате
        """
        # Given
        theme_dir = tmp_path / "styles" / "themes" / "dark"
        theme_dir.mkdir(parents=True, exist_ok=True)
        (theme_dir / "variables.yaml").write_text('bg: "#red"\nunknown_key: value\n', encoding="utf-8")
        manager = _make_manager(
            tmp_path / "styles",
            default_variables_provider=lambda: {"bg": "#000"},
        )

        # When
        result = manager.read_default_variables("dark")

        # Then
        assert result["bg"] == "#red"
        assert "unknown_key" not in result

    def test_no_yaml_file_returns_provider_defaults(self, tmp_path: Path) -> None:
        """
        Given: variables.yaml отсутствует, провайдер возвращает {"fg": "#fff"}
        When: read_default_variables("dark")
        Then: возвращаются дефолты провайдера
        """
        # Given
        styles_dir = tmp_path / "styles"
        styles_dir.mkdir(parents=True, exist_ok=True)
        manager = _make_manager(
            styles_dir,
            default_variables_provider=lambda: {"fg": "#fff"},
        )

        # When
        result = manager.read_default_variables("dark")

        # Then
        assert result == {"fg": "#fff"}

    def test_no_yaml_no_provider_returns_empty(self, tmp_path: Path) -> None:
        """
        Given: нет yaml, нет провайдера
        When: read_default_variables("dark")
        Then: возвращается {}
        """
        # Given
        styles_dir = tmp_path / "styles"
        styles_dir.mkdir(parents=True, exist_ok=True)
        manager = _make_manager(styles_dir)

        # When
        result = manager.read_default_variables("dark")

        # Then
        assert result == {}


# ===========================================================================
# TestApplyTheme — применение темы через QApplication
# ===========================================================================


class TestApplyTheme:
    """Тесты apply_theme() — вызов setStyleSheet на QApplication."""

    def test_apply_single_file_theme_calls_set_stylesheet(self, tmp_path: Path) -> None:
        """
        Given: styles/dark.qss существует
        When: apply_theme("dark")
        Then: QApplication.instance().setStyleSheet вызывается с содержимым QSS
        """
        # Given
        styles_dir = tmp_path / "styles"
        _write_qss(styles_dir / "dark.qss", "QWidget { background: #000; }")
        manager = _make_manager(styles_dir)
        mock_app = _make_mock_app()

        # When
        with patch(_QAPP_PATH) as MockQApp:
            MockQApp.instance.return_value = mock_app
            result = manager.apply_theme("dark")

        # Then
        assert result is True
        mock_app.setStyleSheet.assert_called_once()
        applied_qss = mock_app.setStyleSheet.call_args[0][0]
        assert "background: #000" in applied_qss

    def test_apply_theme_sets_current_theme(self, tmp_path: Path) -> None:
        """
        Given: styles/light.qss существует
        When: apply_theme("light")
        Then: current_theme == "light"
        """
        # Given
        styles_dir = tmp_path / "styles"
        _write_qss(styles_dir / "light.qss", "QWidget { background: #fff; }")
        manager = _make_manager(styles_dir)
        mock_app = _make_mock_app()

        # When
        with patch(_QAPP_PATH) as MockQApp:
            MockQApp.instance.return_value = mock_app
            manager.apply_theme("light")

        # Then
        assert manager.current_theme == "light"

    def test_switch_theme_applies_different_qss(self, tmp_path: Path) -> None:
        """
        Given: styles/dark.qss и styles/light.qss существуют
        When: сначала apply_theme("dark"), затем apply_theme("light")
        Then: второй вызов применяет QSS light темы
        """
        # Given
        styles_dir = tmp_path / "styles"
        _write_qss(styles_dir / "dark.qss", "DARK_QSS")
        _write_qss(styles_dir / "light.qss", "LIGHT_QSS")
        manager = _make_manager(styles_dir)
        mock_app = _make_mock_app()

        # When
        with patch(_QAPP_PATH) as MockQApp:
            MockQApp.instance.return_value = mock_app
            manager.apply_theme("dark")
            manager.apply_theme("light")

        # Then — второй вызов применил LIGHT_QSS
        assert mock_app.setStyleSheet.call_count == 2
        last_call_qss = mock_app.setStyleSheet.call_args[0][0]
        assert "LIGHT_QSS" in last_call_qss

    def test_hot_reload_calls_set_stylesheet_again(self, tmp_path: Path) -> None:
        """
        Given: styles/dark.qss загружена один раз
        When: reload_current() вызывается повторно
        Then: setStyleSheet вызван дважды (hot-reload)
        """
        # Given
        styles_dir = tmp_path / "styles"
        _write_qss(styles_dir / "dark.qss", "QWidget { color: red; }")
        manager = _make_manager(styles_dir)
        mock_app = _make_mock_app()

        # When
        with patch(_QAPP_PATH) as MockQApp:
            MockQApp.instance.return_value = mock_app
            manager.apply_theme("dark")
            manager.reload_current()  # hot-reload

        # Then — setStyleSheet вызван дважды
        assert mock_app.setStyleSheet.call_count == 2

    def test_apply_missing_theme_returns_false(self, tmp_path: Path) -> None:
        """
        Given: тема "nonexistent" отсутствует
        When: apply_theme("nonexistent")
        Then: возвращается False (тема не найдена)
        """
        # Given
        styles_dir = tmp_path / "styles"
        styles_dir.mkdir(parents=True, exist_ok=True)
        manager = _make_manager(styles_dir)
        mock_app = _make_mock_app()

        # When
        with patch(_QAPP_PATH) as MockQApp:
            MockQApp.instance.return_value = mock_app
            result = manager.apply_theme("nonexistent")

        # Then
        assert result is False
        mock_app.setStyleSheet.assert_not_called()

    def test_apply_theme_no_qapp_returns_false(self, tmp_path: Path) -> None:
        """
        Given: QApplication.instance() возвращает None
        When: apply_theme("dark")
        Then: возвращается False (нет приложения)
        """
        # Given
        styles_dir = tmp_path / "styles"
        _write_qss(styles_dir / "dark.qss", "QWidget {}")
        manager = _make_manager(styles_dir)

        # When
        with patch(_QAPP_PATH) as MockQApp:
            MockQApp.instance.return_value = None
            result = manager.apply_theme("dark")

        # Then
        assert result is False

    def test_apply_theme_with_variables_substitutes_placeholders(self, tmp_path: Path) -> None:
        """
        Given: styles/dark.qss содержит @bg_deep плейсхолдер
        When: apply_theme_with_variables("dark", {"bg_deep": "#222"})
        Then: setStyleSheet вызывается с подставленным значением
        """
        # Given
        styles_dir = tmp_path / "styles"
        _write_qss(styles_dir / "dark.qss", "QWidget { background: @bg_deep; }")
        manager = _make_manager(styles_dir)
        mock_app = _make_mock_app()

        # When
        with patch(_QAPP_PATH) as MockQApp:
            MockQApp.instance.return_value = mock_app
            result = manager.apply_theme_with_variables("dark", {"bg_deep": "#222"})

        # Then
        assert result is True
        applied = mock_app.setStyleSheet.call_args[0][0]
        assert "#222" in applied
        assert "@bg_deep" not in applied


# ===========================================================================
# TestAvailableThemes — список тем
# ===========================================================================


class TestAvailableThemes:
    """Тесты available_themes() — обнаружение доступных тем."""

    def test_single_file_themes_listed(self, tmp_path: Path) -> None:
        """
        Given: styles/dark.qss, styles/light.qss
        When: available_themes()
        Then: ["dark", "light"] (отсортировано)
        """
        # Given
        styles_dir = tmp_path / "styles"
        _write_qss(styles_dir / "dark.qss", "/* dark */")
        _write_qss(styles_dir / "light.qss", "/* light */")
        manager = _make_manager(styles_dir)

        # When
        themes = manager.available_themes()

        # Then
        assert "dark" in themes
        assert "light" in themes
        assert themes == sorted(themes)

    def test_modular_theme_listed(self, tmp_path: Path) -> None:
        """
        Given: styles/themes/custom/ содержит хотя бы один .qss
        When: available_themes()
        Then: "custom" присутствует в списке
        """
        # Given
        themes_dir = tmp_path / "styles" / "themes" / "custom"
        _write_qss(themes_dir / "main.qss", "/* main */")
        manager = _make_manager(tmp_path / "styles")

        # When
        themes = manager.available_themes()

        # Then
        assert "custom" in themes

    def test_empty_modular_dir_not_listed(self, tmp_path: Path) -> None:
        """
        Given: styles/themes/empty_theme/ существует, но без .qss файлов
        When: available_themes()
        Then: "empty_theme" отсутствует в списке
        """
        # Given
        empty_dir = tmp_path / "styles" / "themes" / "empty_theme"
        empty_dir.mkdir(parents=True, exist_ok=True)
        manager = _make_manager(tmp_path / "styles")

        # When
        themes = manager.available_themes()

        # Then
        assert "empty_theme" not in themes

    def test_no_duplicates_when_modular_and_file_exist(self, tmp_path: Path) -> None:
        """
        Given: существует и styles/dark.qss, и styles/themes/dark/main.qss
        When: available_themes()
        Then: "dark" встречается ровно один раз
        """
        # Given
        styles_dir = tmp_path / "styles"
        _write_qss(styles_dir / "dark.qss", "/* file */")
        _write_qss(styles_dir / "themes" / "dark" / "main.qss", "/* modular */")
        manager = _make_manager(styles_dir)

        # When
        themes = manager.available_themes()

        # Then
        assert themes.count("dark") == 1


# ===========================================================================
# TestReadThemeByManifest — чтение по manifest-списку
# ===========================================================================


class TestReadThemeByManifest:
    """Тесты read_theme_by_manifest() и apply_theme_by_manifest()."""

    def test_read_by_manifest_includes_base_and_manifest_files(self, tmp_path: Path) -> None:
        """
        Given: styles/themes/dark/base.qss и styles/themes/dark/buttons.qss
        When: read_theme_by_manifest("dark", ["buttons.qss"])
        Then: результат содержит содержимое обоих файлов
        """
        # Given
        theme_dir = tmp_path / "styles" / "themes" / "dark"
        _write_qss(theme_dir / "base.qss", "BASE")
        _write_qss(theme_dir / "buttons.qss", "BUTTONS")
        manager = _make_manager(tmp_path / "styles")

        # When
        result = manager.read_theme_by_manifest("dark", ["buttons.qss"])

        # Then
        assert result is not None
        assert "BASE" in result
        assert "BUTTONS" in result

    def test_read_by_manifest_preserves_order(self, tmp_path: Path) -> None:
        """
        Given: styles/themes/dark/base.qss, z_last.qss, a_first.qss
        When: manifest = ["z_last.qss", "a_first.qss"]
        Then: порядок в результате соответствует manifest, не алфавиту
        """
        # Given
        theme_dir = tmp_path / "styles" / "themes" / "dark"
        _write_qss(theme_dir / "base.qss", "BASE")
        _write_qss(theme_dir / "z_last.qss", "Z_LAST")
        _write_qss(theme_dir / "a_first.qss", "A_FIRST")
        manager = _make_manager(tmp_path / "styles")

        # When
        result = manager.read_theme_by_manifest("dark", ["z_last.qss", "a_first.qss"])

        # Then — Z_LAST должен стоять перед A_FIRST
        assert result is not None
        z_pos = result.index("Z_LAST")
        a_pos = result.index("A_FIRST")
        assert z_pos < a_pos

    def test_apply_by_manifest_calls_set_stylesheet(self, tmp_path: Path) -> None:
        """
        Given: styles/themes/dark/base.qss и buttons.qss
        When: apply_theme_by_manifest("dark", ["buttons.qss"], variables={})
        Then: setStyleSheet вызывается, возвращается True
        """
        # Given
        theme_dir = tmp_path / "styles" / "themes" / "dark"
        _write_qss(theme_dir / "base.qss", "BASE")
        _write_qss(theme_dir / "buttons.qss", "BUTTONS")
        manager = _make_manager(tmp_path / "styles")
        mock_app = _make_mock_app()

        # When
        with patch(_QAPP_PATH) as MockQApp:
            MockQApp.instance.return_value = mock_app
            result = manager.apply_theme_by_manifest("dark", ["buttons.qss"], {})

        # Then
        assert result is True
        mock_app.setStyleSheet.assert_called_once()


# ===========================================================================
# TestIsModular / TestThemeParts — вспомогательные методы
# ===========================================================================


class TestIsModularAndThemeParts:
    """Тесты is_modular() и theme_parts()."""

    def test_is_modular_true_for_dir_with_qss(self, tmp_path: Path) -> None:
        """
        Given: styles/themes/dark/ содержит .qss файлы
        When: is_modular("dark")
        Then: True
        """
        # Given
        theme_dir = tmp_path / "styles" / "themes" / "dark"
        _write_qss(theme_dir / "main.qss", "/* qss */")
        manager = _make_manager(tmp_path / "styles")

        # When / Then
        assert manager.is_modular("dark") is True

    def test_is_modular_false_for_file_only_theme(self, tmp_path: Path) -> None:
        """
        Given: только styles/dark.qss (нет папки themes/dark)
        When: is_modular("dark")
        Then: False
        """
        # Given
        styles_dir = tmp_path / "styles"
        _write_qss(styles_dir / "dark.qss", "/* qss */")
        manager = _make_manager(styles_dir)

        # When / Then
        assert manager.is_modular("dark") is False

    def test_theme_parts_returns_sorted_names(self, tmp_path: Path) -> None:
        """
        Given: styles/themes/dark/ содержит c.qss, a.qss, b.qss
        When: theme_parts("dark")
        Then: ['a.qss', 'b.qss', 'c.qss']
        """
        # Given
        theme_dir = tmp_path / "styles" / "themes" / "dark"
        _write_qss(theme_dir / "c.qss", "")
        _write_qss(theme_dir / "a.qss", "")
        _write_qss(theme_dir / "b.qss", "")
        manager = _make_manager(tmp_path / "styles")

        # When
        parts = manager.theme_parts("dark")

        # Then
        assert parts == ["a.qss", "b.qss", "c.qss"]

    def test_theme_parts_empty_for_nonexistent(self, tmp_path: Path) -> None:
        """
        Given: тема "ghost" отсутствует
        When: theme_parts("ghost")
        Then: []
        """
        # Given
        styles_dir = tmp_path / "styles"
        styles_dir.mkdir(parents=True, exist_ok=True)
        manager = _make_manager(styles_dir)

        # When
        parts = manager.theme_parts("ghost")

        # Then
        assert parts == []
