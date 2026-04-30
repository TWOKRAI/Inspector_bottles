"""test_validation.py — Тесты для ValidationMiddleware (Task 4b+.3).

Проверяет:
- Валидные и невалидные значения (type, min, max, enum)
- Пути без правил всегда пропускаются
- Glob-паттерн матчит конкретные пути
- context содержит validation_error при отклонении
- add_rule() добавляет правило в runtime
- before_merge наследуется из базового (пропуск без изменений)
"""

from __future__ import annotations

import pytest
from state_store.middleware.validation import ValidationMiddleware


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture()
def middleware() -> ValidationMiddleware:
    """Middleware со стандартными правилами для тестов."""
    return ValidationMiddleware({
        "cameras.*.config.fps": {"type": int, "min": 1, "max": 120},
        "cameras.*.config.camera_type": {
            "type": str,
            "enum": ["webcam", "hikvision", "simulator", "file"],
        },
        "renderer.config.overlay_alpha": {"type": float, "min": 0.0, "max": 1.0},
    })


# ---------------------------------------------------------------------------
# Тесты: int в диапазоне (fps)
# ---------------------------------------------------------------------------


class TestFpsValidation:
    """Тесты валидации fps (int, min=1, max=120)."""

    def test_fps_valid_accepted(self, middleware: ValidationMiddleware) -> None:
        """fps=30 — валидный int в диапазоне, принимается."""
        proceed, value = middleware.before_set(
            "cameras.0.config.fps", 30, "gui", {}
        )
        assert proceed is True
        assert value == 30

    def test_fps_below_min_rejected(self, middleware: ValidationMiddleware) -> None:
        """fps=0 — ниже min=1, отклоняется."""
        proceed, value = middleware.before_set(
            "cameras.0.config.fps", 0, "gui", {}
        )
        assert proceed is False
        assert value == 0

    def test_fps_above_max_rejected(self, middleware: ValidationMiddleware) -> None:
        """fps=200 — выше max=120, отклоняется."""
        proceed, _value = middleware.before_set(
            "cameras.0.config.fps", 200, "gui", {}
        )
        assert proceed is False

    def test_fps_wrong_type_rejected(self, middleware: ValidationMiddleware) -> None:
        """fps='строка' — не int, отклоняется."""
        proceed, _value = middleware.before_set(
            "cameras.0.config.fps", "строка", "gui", {}
        )
        assert proceed is False

    def test_fps_boundary_min_accepted(self, middleware: ValidationMiddleware) -> None:
        """fps=1 — граница min, принимается."""
        proceed, _value = middleware.before_set(
            "cameras.0.config.fps", 1, "gui", {}
        )
        assert proceed is True

    def test_fps_boundary_max_accepted(self, middleware: ValidationMiddleware) -> None:
        """fps=120 — граница max, принимается."""
        proceed, _value = middleware.before_set(
            "cameras.0.config.fps", 120, "gui", {}
        )
        assert proceed is True


# ---------------------------------------------------------------------------
# Тесты: enum (camera_type)
# ---------------------------------------------------------------------------


class TestEnumValidation:
    """Тесты валидации camera_type (str, enum)."""

    def test_camera_type_valid_accepted(self, middleware: ValidationMiddleware) -> None:
        """camera_type='webcam' — допустимое значение, принимается."""
        proceed, _value = middleware.before_set(
            "cameras.0.config.camera_type", "webcam", "gui", {}
        )
        assert proceed is True

    def test_camera_type_invalid_rejected(self, middleware: ValidationMiddleware) -> None:
        """camera_type='invalid' — не входит в enum, отклоняется."""
        proceed, _value = middleware.before_set(
            "cameras.0.config.camera_type", "invalid", "gui", {}
        )
        assert proceed is False

    def test_camera_type_all_valid_values(self, middleware: ValidationMiddleware) -> None:
        """Все допустимые значения camera_type принимаются."""
        for cam_type in ("webcam", "hikvision", "simulator", "file"):
            proceed, _value = middleware.before_set(
                "cameras.5.config.camera_type", cam_type, "gui", {}
            )
            assert proceed is True, f"Ожидалось принятие для {cam_type!r}"


# ---------------------------------------------------------------------------
# Тесты: float в диапазоне (overlay_alpha)
# ---------------------------------------------------------------------------


class TestFloatValidation:
    """Тесты валидации overlay_alpha (float, min=0.0, max=1.0)."""

    def test_overlay_alpha_valid_accepted(self, middleware: ValidationMiddleware) -> None:
        """overlay_alpha=0.5 — валидный float в диапазоне, принимается."""
        proceed, _value = middleware.before_set(
            "renderer.config.overlay_alpha", 0.5, "gui", {}
        )
        assert proceed is True

    def test_overlay_alpha_above_max_rejected(self, middleware: ValidationMiddleware) -> None:
        """overlay_alpha=1.5 — выше max=1.0, отклоняется."""
        proceed, _value = middleware.before_set(
            "renderer.config.overlay_alpha", 1.5, "gui", {}
        )
        assert proceed is False

    def test_overlay_alpha_below_min_rejected(self, middleware: ValidationMiddleware) -> None:
        """overlay_alpha=-0.1 — ниже min=0.0, отклоняется."""
        proceed, _value = middleware.before_set(
            "renderer.config.overlay_alpha", -0.1, "gui", {}
        )
        assert proceed is False


# ---------------------------------------------------------------------------
# Тесты: пути без правил
# ---------------------------------------------------------------------------


class TestUnknownPath:
    """Пути без правил всегда пропускаются."""

    def test_unknown_path_always_accepted(self, middleware: ValidationMiddleware) -> None:
        """Путь без правила принимается без проверки."""
        proceed, value = middleware.before_set(
            "some.unknown.path", "anything", "gui", {}
        )
        assert proceed is True
        assert value == "anything"

    def test_unknown_path_any_type_accepted(self, middleware: ValidationMiddleware) -> None:
        """Любой тип значения для неизвестного пути принимается."""
        for value in (None, [], {}, 42, 3.14, True, "text"):
            proceed, _ = middleware.before_set("no.rule.here", value, "src", {})
            assert proceed is True, f"Ожидалось принятие для {value!r}"


# ---------------------------------------------------------------------------
# Тесты: glob-матчинг
# ---------------------------------------------------------------------------


class TestGlobMatching:
    """Glob-паттерн cameras.*.config.fps матчит конкретные пути."""

    def test_glob_matches_numeric_segment(self, middleware: ValidationMiddleware) -> None:
        """Паттерн cameras.*.config.fps матчит cameras.0.config.fps."""
        # Валидное значение — должно быть принято через glob
        proceed, _value = middleware.before_set(
            "cameras.0.config.fps", 60, "gui", {}
        )
        assert proceed is True

    def test_glob_matches_different_camera_ids(self, middleware: ValidationMiddleware) -> None:
        """Паттерн матчит любой camera id — 0, 1, cam_left и т.д."""
        for camera_id in ("0", "1", "cam_left", "cam_right"):
            proceed, _ = middleware.before_set(
                f"cameras.{camera_id}.config.fps", 30, "gui", {}
            )
            assert proceed is True, f"Ожидалось принятие для camera_id={camera_id!r}"

    def test_glob_no_match_different_structure(self, middleware: ValidationMiddleware) -> None:
        """cameras.0.fps (без .config.) не матчит паттерн cameras.*.config.fps."""
        # Не матчит паттерн → пропускается без валидации
        proceed, _value = middleware.before_set(
            "cameras.0.fps", "не_число", "gui", {}
        )
        assert proceed is True


# ---------------------------------------------------------------------------
# Тесты: context при отклонении
# ---------------------------------------------------------------------------


class TestContextOnReject:
    """context содержит validation_error при отклонении."""

    def test_context_contains_validation_error(self, middleware: ValidationMiddleware) -> None:
        """При отклонении context['validation_error'] содержит описание."""
        context: dict = {}
        proceed, _value = middleware.before_set(
            "cameras.0.config.fps", 0, "gui", context
        )
        assert proceed is False
        assert "validation_error" in context
        assert len(context["validation_error"]) > 0

    def test_context_contains_rejection_reason(self, middleware: ValidationMiddleware) -> None:
        """При отклонении context['rejection_reason'] == 'validation'."""
        context: dict = {}
        middleware.before_set("cameras.0.config.fps", 999, "gui", context)
        assert context.get("rejection_reason") == "validation"

    def test_context_empty_on_accept(self, middleware: ValidationMiddleware) -> None:
        """При принятии context не содержит validation_error."""
        context: dict = {}
        proceed, _value = middleware.before_set(
            "cameras.0.config.fps", 30, "gui", context
        )
        assert proceed is True
        assert "validation_error" not in context


# ---------------------------------------------------------------------------
# Тест: add_rule() в runtime
# ---------------------------------------------------------------------------


class TestAddRule:
    """add_rule() добавляет правило в runtime."""

    def test_add_rule_takes_effect(self, middleware: ValidationMiddleware) -> None:
        """После add_rule новый путь начинает валидироваться."""
        # До добавления — принимается без проверки
        proceed_before, _ = middleware.before_set(
            "system.config.timeout", "не_число", "src", {}
        )
        assert proceed_before is True

        # Добавляем правило
        middleware.add_rule("system.config.timeout", {"type": int, "min": 0, "max": 300})

        # После добавления — строка отклоняется
        proceed_after, _ = middleware.before_set(
            "system.config.timeout", "не_число", "src", {}
        )
        assert proceed_after is False

    def test_add_rule_valid_value_accepted(self, middleware: ValidationMiddleware) -> None:
        """После add_rule валидное значение для нового пути принимается."""
        middleware.add_rule("system.config.timeout", {"type": int, "min": 0, "max": 300})
        proceed, value = middleware.before_set(
            "system.config.timeout", 60, "src", {}
        )
        assert proceed is True
        assert value == 60


# ---------------------------------------------------------------------------
# Тест: before_merge наследуется из базового (пропуск)
# ---------------------------------------------------------------------------


class TestBeforeMergeInherited:
    """before_merge наследуется из StateMiddleware — пропускает без изменений."""

    def test_before_merge_passthrough(self, middleware: ValidationMiddleware) -> None:
        """before_merge возвращает (True, data) без модификаций."""
        data = {"fps": 30, "camera_type": "invalid_but_not_validated_in_merge"}
        proceed, result_data = middleware.before_merge(
            "cameras.0.config", data, "gui", {}
        )
        assert proceed is True
        assert result_data is data


# ---------------------------------------------------------------------------
# Тест: несколько проверок одновременно (type + min + max)
# ---------------------------------------------------------------------------


class TestMultipleChecks:
    """type + min + max проверяются одновременно (первый failing возвращается)."""

    def test_type_check_before_range(self) -> None:
        """Если type неверный, range-проверки не применяются (нет смысла)."""
        mw = ValidationMiddleware({
            "x": {"type": int, "min": 0, "max": 100},
        })
        context: dict = {}
        proceed, _ = mw.before_set("x", "текст", "src", context)
        assert proceed is False
        # Ошибка — именно type, а не range
        assert "тип" in context["validation_error"].lower()

    def test_valid_value_passes_all_checks(self) -> None:
        """Значение, прошедшее type + min + max, принимается."""
        mw = ValidationMiddleware({
            "score": {"type": float, "min": 0.0, "max": 1.0},
        })
        proceed, value = mw.before_set("score", 0.75, "src", {})
        assert proceed is True
        assert value == 0.75
