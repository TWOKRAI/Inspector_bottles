"""Тесты для theme_loader — загрузка темы innotech_theme в v2."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from multiprocess_framework.modules.frontend_module.managers.theme_manager import ThemeManager
from multiprocess_prototype.frontend.styles.theme_loader import (
    available_themes,
    create_theme_manager,
    load_theme,
)

# Путь к директории styles/ в v2
# __file__ = .../multiprocess_prototype/frontend/tests/test_theme_loader.py
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
        themes = available_themes()
        assert _THEME_NAME in themes

    def test_available_themes_is_sorted(self) -> None:
        """available_themes() возвращает отсортированный список."""
        themes = available_themes()
        assert themes == sorted(themes)

    def test_available_themes_via_theme_manager(self) -> None:
        """available_themes() совпадает с ThemeManager.available_themes()."""
        tm = create_theme_manager()
        assert available_themes() == tm.available_themes()


class TestReadTheme:
    """Тесты чтения QSS темы через ThemeManager."""

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


class TestLoadTheme:
    """Тесты функции load_theme — полный цикл с подстановкой переменных."""

    def test_load_theme_returns_nonempty_string(self) -> None:
        """load_theme('innotech_theme') возвращает непустую строку."""
        qss = load_theme(_THEME_NAME)
        assert isinstance(qss, str)
        assert len(qss) > 0

    def test_load_theme_no_unresolved_variables(self) -> None:
        """После load_theme() в QSS не остаётся @-плейсхолдеров переменных из yaml."""
        qss = load_theme(_THEME_NAME)
        # Загружаем список известных переменных из yaml
        yaml_path = _STYLES_DIR / "themes" / _THEME_NAME / "variables.yaml"
        with open(yaml_path, encoding="utf-8") as f:
            variables = yaml.safe_load(f)
        for var_name in variables:
            assert f"@{var_name}" not in qss, (
                f"Плейсхолдер @{var_name} не был заменён в load_theme()"
            )

    def test_load_theme_invalid_raises_file_not_found(self) -> None:
        """load_theme() с несуществующей темой бросает FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_theme("nonexistent_theme_xyz")

    def test_load_theme_contains_hex_colors(self) -> None:
        """load_theme() содержит реальные hex-цвета вместо переменных."""
        qss = load_theme(_THEME_NAME)
        # Акцентный цвет из variables.yaml — #2b7fff
        assert "#2b7fff" in qss.lower() or "2b7fff" in qss.lower()

    def test_load_theme_default_is_innotech(self) -> None:
        """load_theme() без аргументов загружает innotech_theme."""
        qss_explicit = load_theme("innotech_theme")
        qss_default = load_theme()
        assert qss_explicit == qss_default


class TestResolveQss:
    """Тесты подстановки переменных в QSS-шаблон через ThemeManager.resolve_qss."""

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


class TestSchemaYamlSync:
    """Тесты синхронизации ThemeVariables (schema) ↔ variables.yaml."""

    def _load_yaml_variables(self) -> dict[str, str]:
        """Загрузить переменные из variables.yaml."""
        yaml_path = _STYLES_DIR / "themes" / _THEME_NAME / "variables.yaml"
        with open(yaml_path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        return {k: str(v) for k, v in loaded.items()}

    def test_all_schema_fields_in_yaml(self) -> None:
        """Все поля ThemeVariables.model_fields присутствуют в variables.yaml.

        Проверяет синхронизацию: если добавили поле в схему, оно должно быть
        и в yaml-файле темы, иначе подстановка не произойдёт.
        """
        from multiprocess_prototype.registers.theme.schemas import ThemeVariables

        yaml_vars = self._load_yaml_variables()
        schema_fields = set(ThemeVariables.model_fields.keys())
        yaml_keys = set(yaml_vars.keys())

        missing_in_yaml = schema_fields - yaml_keys
        assert not missing_in_yaml, (
            f"Поля схемы отсутствуют в variables.yaml: {sorted(missing_in_yaml)}"
        )

    def test_all_yaml_keys_in_schema(self) -> None:
        """Все ключи variables.yaml присутствуют в ThemeVariables.model_fields.

        Обратная проверка: если убрали поле из схемы, его не должно быть в yaml
        (устаревшие ключи засоряют файл).
        """
        from multiprocess_prototype.registers.theme.schemas import ThemeVariables

        yaml_vars = self._load_yaml_variables()
        schema_fields = set(ThemeVariables.model_fields.keys())
        yaml_keys = set(yaml_vars.keys())

        extra_in_yaml = yaml_keys - schema_fields
        assert not extra_in_yaml, (
            f"Ключи yaml отсутствуют в схеме ThemeVariables: {sorted(extra_in_yaml)}"
        )


class TestQssTemplate:
    """Тесты QSS-шаблона main.qss (до подстановки переменных)."""

    def _read_template(self) -> str:
        """Прочитать raw-шаблон main.qss без подстановки переменных."""
        qss_path = _STYLES_DIR / "themes" / _THEME_NAME / "main.qss"
        return qss_path.read_text(encoding="utf-8")

    def _non_comment_lines(self, qss: str) -> list[str]:
        """Вернуть строки шаблона, которые не являются QSS-комментариями.

        Убирает строки внутри /* ... */ блоков.
        Простая (строчная) фильтрация: строка является комментарием,
        если она находится между /* и */ (многострочный блок).
        """
        lines = []
        inside_comment = False
        for line in qss.splitlines():
            stripped = line.strip()
            if inside_comment:
                if "*/" in stripped:
                    inside_comment = False
                # Строки внутри блочного комментария пропускаем
                continue
            if stripped.startswith("/*"):
                if "*/" not in stripped:
                    # Открывающая строка многострочного комментария
                    inside_comment = True
                # Строки-комментарии (однострочные и открывающие) пропускаем
                continue
            lines.append(line)
        return lines

    def test_no_hardcoded_hex_in_template_qss(self) -> None:
        """Шаблон main.qss не содержит хардкодных hex-цветов (кроме #fff/#000).

        Допустимые литералы: #ffffff, #fff, #000, #000000.
        Все остальные hex-цвета должны быть заменены на @-переменные.
        """
        import re

        # Допустимые hex: белый и чёрный во всех вариантах
        ALLOWED_HEX = {
            "#ffffff", "#fff", "#000", "#000000",
        }

        qss = self._read_template()
        non_comment = "\n".join(self._non_comment_lines(qss))

        # Ищем все hex-литералы в не-комментарных строках
        found = re.findall(r"#[0-9a-fA-F]{3,8}\b", non_comment)
        forbidden = [h for h in found if h.lower() not in ALLOWED_HEX]

        assert not forbidden, (
            f"Хардкодные hex-цвета в main.qss (должны быть заменены на @-переменные): "
            f"{sorted(set(forbidden))}"
        )

    def test_no_literal_rgba_in_template_qss(self) -> None:
        """Шаблон main.qss не содержит литеральных rgba() вне комментариев.

        Все rgba()-значения должны быть вынесены в переменные variables.yaml.

        Известные исключения (xfail → known):
            строка ~900: border: 1px solid rgba(0, 0, 0, 0.3) — QCheckBox#ViewModeSwitch.
            Помечено как xfail до выноса в переменную (например shadow_30).
        """
        import re

        # Известные допустимые rgba-исключения (до выноса в переменные)
        KNOWN_EXCEPTIONS = {
            "rgba(0, 0, 0, 0.3)",  # QCheckBox#ViewModeSwitch::indicator:checked
        }

        qss = self._read_template()
        non_comment_lines = self._non_comment_lines(qss)

        violations = []
        for line in non_comment_lines:
            for match in re.finditer(r"rgba\([^)]+\)", line):
                value = match.group(0)
                if value not in KNOWN_EXCEPTIONS:
                    violations.append(f"  {line.strip()!r}")

        assert not violations, (
            "Литеральные rgba() в main.qss (должны быть заменены на @-переменные):\n"
            + "\n".join(violations)
        )


class TestScaleTokenValues:
    """Тесты валидности значений size/scale токенов из variables.yaml."""

    def _load_yaml_variables(self) -> dict[str, str]:
        """Загрузить переменные из variables.yaml."""
        yaml_path = _STYLES_DIR / "themes" / _THEME_NAME / "variables.yaml"
        with open(yaml_path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        return {k: str(v) for k, v in loaded.items()}

    def test_scale_tokens_are_valid_css_values(self) -> None:
        """Все font_*, radius_*, shadow_*, glow_* содержат корректные CSS-значения.

        - font_* (кроме font_family*): формат «Npx»
        - radius_*: формат «Npx»
        - shadow_* и glow_*: содержат «rgba(»
        """
        import re

        variables = self._load_yaml_variables()
        px_pattern = re.compile(r"^\d+px$")
        errors = []

        for key, value in variables.items():
            # font_family и font_family_mono — строки шрифтов, не px
            if key.startswith("font_") and not key.startswith("font_family"):
                if not px_pattern.match(value):
                    errors.append(
                        f"font-токен '{key}' = {value!r}: ожидается формат 'Npx'"
                    )

            elif key.startswith("radius_"):
                if not px_pattern.match(value):
                    errors.append(
                        f"radius-токен '{key}' = {value!r}: ожидается формат 'Npx'"
                    )

            elif key.startswith("shadow_") or key.startswith("glow_"):
                if "rgba(" not in value:
                    errors.append(
                        f"shadow/glow-токен '{key}' = {value!r}: ожидается rgba()"
                    )

        assert not errors, (
            "Некорректные значения scale-токенов в variables.yaml:\n"
            + "\n".join(f"  {e}" for e in errors)
        )
