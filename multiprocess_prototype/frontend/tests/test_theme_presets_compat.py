"""Тесты обратной совместимости ThemePresetsManager с расширенной схемой ThemeVariables.

Проверяет:
- Старые custom-темы (~24 оригинальных ключа) загружаются без ошибок,
  новые поля получают дефолтные значения.
- Полные темы (~152 ключа) корректно сохраняются и загружаются (round-trip).
- Лишние/неизвестные ключи игнорируются Pydantic.
- Оригинальные 24 переменные сохраняют те же дефолтные значения.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from multiprocess_prototype.registers.theme.schemas import (
    ThemeVariables,
    get_default_variables,
)
from multiprocess_prototype.frontend.managers.theme_presets_manager import (
    ThemePresetsManager,
)


# ---------------------------------------------------------------------------
# Оригинальные 24 переменные (до расширения схемы)
# Только ключи, которые были в первоначальной версии темы innotech_theme.
# ---------------------------------------------------------------------------
_ORIGINAL_24_VARS: dict[str, str] = {
    "bg_deep": "#1a1f28",
    "bg_mid": "#2d3440",
    "bg_hi": "#4a5362",
    "bg_hi2": "#5c6573",
    "surf_0": "#3a414e",
    "surf_1": "#5a6370",
    "surf_2": "#6e7886",
    "surf_deep": "#252a33",
    "silver_hi": "#c8ccd4",
    "silver": "#9ea6b2",
    "silver_lo": "#6a7280",
    "text_0": "#f2f5fa",
    "text_1": "#c0c7d2",
    "text_2": "#8a93a1",
    "text_3": "#5e6674",
    "accent": "#2b7fff",
    "accent_hi": "#4a95ff",
    "accent_lo": "#1f5fcc",
    "accent_deep": "#153f8a",
    "danger": "#e54863",
    "success": "#2ecc8f",
    "warn": "#f0a23a",
    "font_family": "Rajdhani",
    "font_family_mono": "JetBrains Mono",
}


class TestOldCustomThemeLoads:
    """Тест: старая custom-тема с ~24 ключами загружается через ThemeVariables."""

    def test_old_custom_theme_loads(self, tmp_path: Path) -> None:
        """YAML только с 24 оригинальными ключами — новые поля должны получить дефолты."""
        # Создаём YAML только с оригинальными переменными
        yaml_content = yaml.dump(
            _ORIGINAL_24_VARS,
            default_flow_style=False,
            allow_unicode=True,
        )
        theme_file = tmp_path / "old_custom.yaml"
        theme_file.write_text(yaml_content, encoding="utf-8")

        # Загружаем через ThemePresetsManager
        mgr = ThemePresetsManager(data_dir=tmp_path)
        # Кладём файл напрямую в custom_themes/
        custom_dir = tmp_path / "custom_themes"
        custom_dir.mkdir(parents=True, exist_ok=True)
        (custom_dir / "old_custom.yaml").write_text(yaml_content, encoding="utf-8")

        result = mgr.get_variables("old_custom")
        assert isinstance(result, ThemeVariables)

        # Оригинальные 24 переменных должны совпадать
        for key, expected_value in _ORIGINAL_24_VARS.items():
            actual = getattr(result, key)
            assert actual == expected_value, (
                f"Переменная '{key}': ожидалось '{expected_value}', получено '{actual}'"
            )

        # Новые поля (добавленные при расширении до 152 переменных)
        # должны получить дефолтные значения из ThemeVariables
        defaults = ThemeVariables()
        all_fields = set(ThemeVariables.model_fields.keys())
        new_fields = all_fields - set(_ORIGINAL_24_VARS.keys())

        # Проверяем, что все новые поля есть и равны дефолтам
        assert len(new_fields) > 0, "Должны существовать поля за пределами оригинальных 24"
        for field_name in new_fields:
            expected_default = getattr(defaults, field_name)
            actual = getattr(result, field_name)
            assert actual == expected_default, (
                f"Новое поле '{field_name}': ожидался дефолт '{expected_default}', "
                f"получено '{actual}'"
            )

    def test_old_custom_theme_loads_direct_model_validate(self) -> None:
        """ThemeVariables.model_validate из dict с 24 ключами — прямой тест без файла."""
        result = ThemeVariables.model_validate(_ORIGINAL_24_VARS)
        assert isinstance(result, ThemeVariables)

        # Оригинальные значения сохраняются
        assert result.bg_deep == "#1a1f28"
        assert result.accent == "#2b7fff"
        assert result.font_family == "Rajdhani"

        # Новые поля получают дефолтные значения
        defaults = ThemeVariables()
        assert result.shadow_xs == defaults.shadow_xs
        assert result.glow_xs == defaults.glow_xs
        assert result.radius_xs == defaults.radius_xs


class TestFullThemeRoundtrip:
    """Тест: полная тема (~152 ключа) сохраняется и загружается без потерь."""

    def test_full_theme_roundtrip(self, tmp_path: Path) -> None:
        """Создаём ThemeVariables, сохраняем через менеджер, загружаем обратно."""
        mgr = ThemePresetsManager(data_dir=tmp_path)

        # Создаём полный ThemeVariables с дефолтными значениями
        original = ThemeVariables()

        # Кастомизируем несколько полей для проверки
        original.bg_deep = "#111111"
        original.accent = "#ff0000"
        original.font_brand = "32px"

        # Сохраняем
        mgr.save_custom("full_theme", original)

        # Загружаем обратно
        loaded = mgr.get_variables("full_theme")
        assert isinstance(loaded, ThemeVariables)

        # Все поля должны совпадать
        original_data = original.model_dump()
        loaded_data = loaded.model_dump()

        for field_name, expected_value in original_data.items():
            actual_value = loaded_data[field_name]
            assert actual_value == expected_value, (
                f"Round-trip: поле '{field_name}': ожидалось '{expected_value}', "
                f"получено '{actual_value}'"
            )

    def test_full_theme_roundtrip_field_count(self, tmp_path: Path) -> None:
        """Проверяем что загруженная тема содержит все поля схемы."""
        mgr = ThemePresetsManager(data_dir=tmp_path)
        original = ThemeVariables()
        mgr.save_custom("count_test", original)

        loaded = mgr.get_variables("count_test")
        loaded_data = loaded.model_dump()

        expected_count = len(ThemeVariables.model_fields)
        actual_count = len(loaded_data)
        assert actual_count == expected_count, (
            f"Количество полей: ожидалось {expected_count}, получено {actual_count}"
        )
        # Схема должна содержать как минимум 24 оригинальных переменных
        assert expected_count >= 24, f"Схема должна иметь минимум 24 поля, имеет {expected_count}"


class TestUnknownKeysIgnored:
    """Тест: лишние/неизвестные ключи не вызывают ошибку при загрузке."""

    def test_unknown_keys_ignored_model_validate(self) -> None:
        """model_validate с неизвестными ключами не выбрасывает исключение."""
        data_with_extra = dict(_ORIGINAL_24_VARS)
        data_with_extra["unknown_legacy_key"] = "#abcdef"
        data_with_extra["another_unknown"] = "some_value"
        data_with_extra["_parent"] = "innotech_theme"  # метаполе менеджера

        # Не должно выбросить исключение
        result = ThemeVariables.model_validate(data_with_extra)
        assert isinstance(result, ThemeVariables)

        # Неизвестные поля не должны попасть в модель
        assert not hasattr(result, "unknown_legacy_key")
        assert not hasattr(result, "another_unknown")

    def test_unknown_keys_ignored_via_manager(self, tmp_path: Path) -> None:
        """ThemePresetsManager загружает YAML с лишними ключами без ошибок."""
        data_with_extra = dict(_ORIGINAL_24_VARS)
        data_with_extra["old_deprecated_var"] = "#ff00ff"
        data_with_extra["_parent"] = "base_theme"

        custom_dir = tmp_path / "custom_themes"
        custom_dir.mkdir(parents=True, exist_ok=True)
        yaml_content = yaml.dump(
            data_with_extra, default_flow_style=False, allow_unicode=True,
        )
        (custom_dir / "compat_test.yaml").write_text(yaml_content, encoding="utf-8")

        mgr = ThemePresetsManager(data_dir=tmp_path)
        result = mgr.get_variables("compat_test")

        # Загрузка должна пройти без ошибок
        assert isinstance(result, ThemeVariables)
        # Оригинальные значения сохранены
        assert result.bg_deep == "#1a1f28"
        assert result.accent == "#2b7fff"

    def test_extra_keys_do_not_raise_pydantic(self) -> None:
        """Pydantic v2 по умолчанию игнорирует лишние поля (extra='ignore')."""
        # Много лишних ключей
        large_extra = {**_ORIGINAL_24_VARS}
        for i in range(20):
            large_extra[f"legacy_var_{i}"] = f"#{'ab' * 3}{i:02d}"

        # Не должно выбросить ValidationError
        result = ThemeVariables.model_validate(large_extra)
        assert isinstance(result, ThemeVariables)
        # Схема вернула корректный объект
        assert result.bg_deep == _ORIGINAL_24_VARS["bg_deep"]


class TestAllOriginalVarsUnchanged:
    """Тест: все 24 оригинальных переменных сохраняют дефолтные значения после рефакторинга."""

    def test_all_original_vars_unchanged(self) -> None:
        """Дефолтные значения оригинальных 24 переменных совпадают с ожидаемыми."""
        defaults = get_default_variables()

        for field_name, expected_value in _ORIGINAL_24_VARS.items():
            assert field_name in defaults, (
                f"Оригинальная переменная '{field_name}' отсутствует в схеме"
            )
            actual_value = defaults[field_name]
            assert actual_value == expected_value, (
                f"Дефолт '{field_name}' изменился: "
                f"ожидалось '{expected_value}', получено '{actual_value}'"
            )

    def test_original_vars_present_in_schema(self) -> None:
        """Все 24 оригинальных переменных присутствуют в ThemeVariables.model_fields."""
        all_fields = set(ThemeVariables.model_fields.keys())
        for field_name in _ORIGINAL_24_VARS:
            assert field_name in all_fields, (
                f"Оригинальная переменная '{field_name}' пропала из схемы ThemeVariables"
            )

    def test_schema_has_more_than_24_fields(self) -> None:
        """Схема расширена и содержит больше 24 полей."""
        total_fields = len(ThemeVariables.model_fields)
        assert total_fields > 24, (
            f"Схема должна содержать более 24 полей (расширение), имеет {total_fields}"
        )

    def test_get_default_variables_returns_all_fields(self) -> None:
        """get_default_variables() возвращает все поля схемы как dict."""
        defaults = get_default_variables()
        expected_count = len(ThemeVariables.model_fields)
        assert len(defaults) == expected_count, (
            f"get_default_variables() вернул {len(defaults)} полей, "
            f"ожидалось {expected_count}"
        )
        # Все значения должны быть строками
        for key, value in defaults.items():
            assert isinstance(value, str), (
                f"Поле '{key}': ожидалась str, получено {type(value).__name__}"
            )
