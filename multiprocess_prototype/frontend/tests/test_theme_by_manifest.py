"""Тесты read_theme_by_manifest / apply_theme_by_manifest."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


from multiprocess_framework.modules.frontend_module.managers.theme_manager import ThemeManager


class TestReadThemeByManifest:
    """Тесты ThemeManager.read_theme_by_manifest()."""

    def _create_theme_files(self, tmp_path: Path) -> Path:
        """Создать тестовую тему с base.qss и компонентами."""
        styles_dir = tmp_path / "styles"
        theme_dir = styles_dir / "themes" / "test_theme"

        # base.qss
        base = theme_dir / "base.qss"
        base.parent.mkdir(parents=True)
        base.write_text("QWidget { color: @text_0; }", encoding="utf-8")

        # components/primitives/
        comp_dir = theme_dir / "components" / "primitives"
        comp_dir.mkdir(parents=True)
        (comp_dir / "buttons.qss").write_text("QPushButton { background: @btn_bg; }", encoding="utf-8")
        (comp_dir / "inputs.qss").write_text("QLineEdit { border: 1px solid @border; }", encoding="utf-8")

        return styles_dir

    def test_happy_path(self, tmp_path: Path) -> None:
        """base.qss + 2 файла из manifest — собирается в правильном порядке."""
        styles_dir = self._create_theme_files(tmp_path)
        tm = ThemeManager(styles_dir)

        manifest = [
            "components/primitives/buttons.qss",
            "components/primitives/inputs.qss",
        ]
        result = tm.read_theme_by_manifest("test_theme", manifest)

        assert result is not None
        assert "QWidget { color: @text_0; }" in result
        assert "QPushButton { background: @btn_bg; }" in result
        assert "QLineEdit { border: 1px solid @border; }" in result
        # Порядок: base перед компонентами
        assert result.index("QWidget") < result.index("QPushButton")
        assert result.index("QPushButton") < result.index("QLineEdit")

    def test_missing_base_qss(self, tmp_path: Path) -> None:
        """Нет base.qss — собирается только из manifest."""
        styles_dir = self._create_theme_files(tmp_path)
        # Удалить base.qss
        (styles_dir / "themes" / "test_theme" / "base.qss").unlink()

        tm = ThemeManager(styles_dir)

        manifest = ["components/primitives/buttons.qss"]
        result = tm.read_theme_by_manifest("test_theme", manifest)

        assert result is not None
        assert "QPushButton" in result

    def test_missing_manifest_file(self, tmp_path: Path) -> None:
        """Файл из manifest не существует — warning, пропуск."""
        styles_dir = self._create_theme_files(tmp_path)
        tm = ThemeManager(styles_dir)

        manifest = [
            "components/primitives/buttons.qss",
            "components/primitives/nonexistent.qss",
        ]
        result = tm.read_theme_by_manifest("test_theme", manifest)

        assert result is not None
        assert "QPushButton" in result

    def test_empty_manifest(self, tmp_path: Path) -> None:
        """Пустой manifest — возвращается только base.qss."""
        styles_dir = self._create_theme_files(tmp_path)
        tm = ThemeManager(styles_dir)

        result = tm.read_theme_by_manifest("test_theme", [])

        assert result is not None
        assert "QWidget" in result

    def test_empty_manifest_no_base(self, tmp_path: Path) -> None:
        """Пустой manifest + нет base.qss -> None."""
        styles_dir = self._create_theme_files(tmp_path)
        (styles_dir / "themes" / "test_theme" / "base.qss").unlink()

        tm = ThemeManager(styles_dir)

        result = tm.read_theme_by_manifest("test_theme", [])
        assert result is None

    def test_manifest_order_preserved(self, tmp_path: Path) -> None:
        """Порядок файлов в manifest определяет порядок в QSS."""
        styles_dir = self._create_theme_files(tmp_path)
        tm = ThemeManager(styles_dir)

        # inputs перед buttons
        manifest = [
            "components/primitives/inputs.qss",
            "components/primitives/buttons.qss",
        ]
        result = tm.read_theme_by_manifest("test_theme", manifest)

        assert result is not None
        assert result.index("QLineEdit") < result.index("QPushButton")


class TestApplyThemeByManifest:
    """Тесты ThemeManager.apply_theme_by_manifest()."""

    def _create_theme_files(self, tmp_path: Path) -> Path:
        """Создать тестовую тему с base.qss и кнопкой."""
        styles_dir = tmp_path / "styles"
        theme_dir = styles_dir / "themes" / "test_theme"

        base = theme_dir / "base.qss"
        base.parent.mkdir(parents=True)
        base.write_text("QWidget { color: red; }", encoding="utf-8")

        comp_dir = theme_dir / "components"
        comp_dir.mkdir(parents=True)
        (comp_dir / "buttons.qss").write_text("QPushButton { background: blue; }", encoding="utf-8")

        return styles_dir

    def test_returns_false_when_no_qss(self, tmp_path: Path) -> None:
        """apply_theme_by_manifest возвращает False если тема не собрана."""
        styles_dir = tmp_path / "styles"
        styles_dir.mkdir(parents=True)
        tm = ThemeManager(styles_dir)

        # Нет ни base.qss, ни файлов в manifest
        result = tm.apply_theme_by_manifest("nonexistent_theme", [], {})
        assert result is False

    def test_returns_false_without_qapplication(self, tmp_path: Path) -> None:
        """apply_theme_by_manifest возвращает False если нет QApplication."""
        styles_dir = self._create_theme_files(tmp_path)
        tm = ThemeManager(styles_dir)

        # QApplication.instance() == None. В полном suite singleton QApplication
        # (его нельзя уничтожить в рамках процесса) протекает между тестами → мокаем
        # детерминированно, иначе тест order-dependent (зелёный только изолированно).
        with patch("multiprocess_framework.modules.frontend_module.managers.theme_manager.QApplication") as mock_qapp:
            mock_qapp.instance.return_value = None
            result = tm.apply_theme_by_manifest("test_theme", [], {})
        assert result is False
