"""test_state_store_config.py — Unit-тесты для state_store_config.py (Задача 1.4).

Проверяют:
- Структуру build_validation_rules() и build_throttle_rules()
- Поведение ValidationMiddleware с реальными доменными правилами
- Поведение ThrottleMiddleware при быстрых повторных вызовах
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]   # Inspector_bottles/
_V3_ROOT = Path(__file__).resolve().parents[2]  # multiprocess_prototype/
for _p in (_ROOT, _V3_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest

from multiprocess_prototype.backend.processes.process_manager.state_store_config import (
    build_throttle_rules,
    build_validation_rules,
)
from multiprocess_prototype.state_store.middleware.throttle import ThrottleMiddleware
from multiprocess_prototype.state_store.middleware.validation import ValidationMiddleware


# ---------------------------------------------------------------------------
# Тест 1: структура build_validation_rules()
# ---------------------------------------------------------------------------

class TestValidationRulesStructure:
    """build_validation_rules() возвращает правильную структуру."""

    def test_returns_dict(self):
        """Возвращаемое значение является словарём."""
        rules = build_validation_rules()
        assert isinstance(rules, dict)

    def test_contains_fps_key(self):
        """Правила содержат ключ cameras.*.config.fps."""
        rules = build_validation_rules()
        assert "cameras.*.config.fps" in rules

    def test_contains_camera_type_key(self):
        """Правила содержат ключ cameras.*.config.camera_type."""
        rules = build_validation_rules()
        assert "cameras.*.config.camera_type" in rules

    def test_contains_resolution_width_key(self):
        """Правила содержат ключ cameras.*.config.resolution_width."""
        rules = build_validation_rules()
        assert "cameras.*.config.resolution_width" in rules

    def test_contains_resolution_height_key(self):
        """Правила содержат ключ cameras.*.config.resolution_height."""
        rules = build_validation_rules()
        assert "cameras.*.config.resolution_height" in rules

    def test_contains_status_key(self):
        """Правила содержат ключ cameras.*.state.status."""
        rules = build_validation_rules()
        assert "cameras.*.state.status" in rules

    def test_fps_rule_has_correct_bounds(self):
        """Правило fps содержит min=1, max=240 и type=int."""
        rule = build_validation_rules()["cameras.*.config.fps"]
        assert rule.get("type") is int
        assert rule.get("min") == 1
        assert rule.get("max") == 240

    def test_camera_type_rule_has_enum(self):
        """Правило camera_type содержит enum с допустимыми значениями."""
        rule = build_validation_rules()["cameras.*.config.camera_type"]
        assert "enum" in rule
        assert "webcam" in rule["enum"]
        assert "simulator" in rule["enum"]


# ---------------------------------------------------------------------------
# Тест 2: структура build_throttle_rules()
# ---------------------------------------------------------------------------

class TestThrottleRulesStructure:
    """build_throttle_rules() возвращает правильную структуру."""

    def test_returns_dict(self):
        """Возвращаемое значение является словарём."""
        rules = build_throttle_rules()
        assert isinstance(rules, dict)

    def test_contains_actual_fps_path(self):
        """Правила содержат паттерн для actual_fps."""
        rules = build_throttle_rules()
        fps_keys = [k for k in rules if "actual_fps" in k]
        assert len(fps_keys) >= 1, "Нет ни одного правила с actual_fps"

    def test_actual_fps_interval_positive(self):
        """Интервал для actual_fps строго больше 0."""
        rules = build_throttle_rules()
        fps_keys = [k for k in rules if "actual_fps" in k]
        for key in fps_keys:
            assert rules[key] > 0, f"Интервал для {key} должен быть > 0"

    def test_all_values_are_numeric(self):
        """Все значения правил являются числами (int или float)."""
        rules = build_throttle_rules()
        for key, interval in rules.items():
            assert isinstance(interval, (int, float)), (
                f"Правило '{key}' имеет нечисловой интервал: {interval!r}"
            )

    def test_non_empty(self):
        """Словарь правил не пустой."""
        rules = build_throttle_rules()
        assert len(rules) > 0


# ---------------------------------------------------------------------------
# Тест 3: ValidationMiddleware принимает валидное значение fps
# ---------------------------------------------------------------------------

class TestValidationMiddlewareAcceptsValid:
    """ValidationMiddleware пропускает валидные значения."""

    def test_accepts_valid_fps(self):
        """before_set для cameras.0.config.fps=30 → proceed=True."""
        mw = ValidationMiddleware(build_validation_rules())
        proceed, value = mw.before_set(
            path="cameras.0.config.fps",
            value=30,
            source="test",
            context={},
        )
        assert proceed is True
        assert value == 30

    def test_accepts_valid_camera_type(self):
        """before_set для cameras.0.config.camera_type='webcam' → proceed=True."""
        mw = ValidationMiddleware(build_validation_rules())
        ctx: dict = {}
        proceed, _ = mw.before_set(
            path="cameras.0.config.camera_type",
            value="webcam",
            source="test",
            context=ctx,
        )
        assert proceed is True
        assert "validation_error" not in ctx

    def test_accepts_valid_status(self):
        """before_set для cameras.0.state.status='running' → proceed=True."""
        mw = ValidationMiddleware(build_validation_rules())
        proceed, _ = mw.before_set(
            path="cameras.0.state.status",
            value="running",
            source="test",
            context={},
        )
        assert proceed is True

    def test_unknown_path_passes_through(self):
        """before_set для пути без правила → proceed=True."""
        mw = ValidationMiddleware(build_validation_rules())
        proceed, value = mw.before_set(
            path="system.some_field",
            value="anything",
            source="test",
            context={},
        )
        assert proceed is True


# ---------------------------------------------------------------------------
# Тест 4: ValidationMiddleware отклоняет невалидные значения
# ---------------------------------------------------------------------------

class TestValidationMiddlewareRejectsInvalid:
    """ValidationMiddleware отклоняет невалидные значения."""

    def test_rejects_fps_too_high(self):
        """before_set для fps=999 (выше max=240) → proceed=False."""
        mw = ValidationMiddleware(build_validation_rules())
        ctx: dict = {}
        proceed, _ = mw.before_set(
            path="cameras.0.config.fps",
            value=999,
            source="test",
            context=ctx,
        )
        assert proceed is False
        assert "validation_error" in ctx
        assert ctx.get("rejection_reason") == "validation"

    def test_rejects_fps_too_low(self):
        """before_set для fps=0 (ниже min=1) → proceed=False."""
        mw = ValidationMiddleware(build_validation_rules())
        ctx: dict = {}
        proceed, _ = mw.before_set(
            path="cameras.0.config.fps",
            value=0,
            source="test",
            context=ctx,
        )
        assert proceed is False

    def test_rejects_fps_wrong_type(self):
        """before_set для fps='fast' (не int) → proceed=False."""
        mw = ValidationMiddleware(build_validation_rules())
        ctx: dict = {}
        proceed, _ = mw.before_set(
            path="cameras.0.config.fps",
            value="fast",
            source="test",
            context=ctx,
        )
        assert proceed is False

    def test_rejects_invalid_camera_type(self):
        """before_set для camera_type='unknown' (не в enum) → proceed=False."""
        mw = ValidationMiddleware(build_validation_rules())
        ctx: dict = {}
        proceed, _ = mw.before_set(
            path="cameras.0.config.camera_type",
            value="unknown",
            source="test",
            context=ctx,
        )
        assert proceed is False
        assert "validation_error" in ctx

    def test_rejects_invalid_status(self):
        """before_set для status='broken' (не в enum) → proceed=False."""
        mw = ValidationMiddleware(build_validation_rules())
        ctx: dict = {}
        proceed, _ = mw.before_set(
            path="cameras.0.state.status",
            value="broken",
            source="test",
            context=ctx,
        )
        assert proceed is False


# ---------------------------------------------------------------------------
# Тест 5: ThrottleMiddleware блокирует быстрые повторные записи
# ---------------------------------------------------------------------------

class TestThrottleMiddlewareBlocksRapidWrites:
    """ThrottleMiddleware пропускает первый вызов и блокирует второй."""

    def test_first_call_passes(self):
        """Первый вызов before_set для actual_fps → proceed=True."""
        rules = build_throttle_rules()
        # Найти путь с actual_fps
        fps_pattern = next(k for k in rules if "actual_fps" in k)
        # Подставить конкретный путь, соответствующий паттерну
        concrete_path = fps_pattern.replace("*", "0")

        mw = ThrottleMiddleware(rules)
        ctx: dict = {}
        proceed, _ = mw.before_set(
            path=concrete_path,
            value=25.0,
            source="camera_0",
            context=ctx,
        )
        assert proceed is True

    def test_second_rapid_call_blocked(self):
        """Второй немедленный вызов before_set для actual_fps → proceed=False."""
        rules = build_throttle_rules()
        fps_pattern = next(k for k in rules if "actual_fps" in k)
        concrete_path = fps_pattern.replace("*", "0")

        mw = ThrottleMiddleware(rules)

        # Первый вызов — пропускаем
        ctx1: dict = {}
        mw.before_set(path=concrete_path, value=25.0, source="camera_0", context=ctx1)

        # Второй немедленный вызов — должен быть заблокирован (интервал 1 сек)
        ctx2: dict = {}
        proceed, _ = mw.before_set(
            path=concrete_path,
            value=26.0,
            source="camera_0",
            context=ctx2,
        )
        assert proceed is False
        assert ctx2.get("rejection_reason") == "throttled"

    def test_blocked_path_is_zero_interval(self):
        """Путь с интервалом 0 (last_frame_seq) всегда блокируется."""
        rules = build_throttle_rules()
        blocked_keys = [k for k in rules if rules[k] == 0]
        if not blocked_keys:
            pytest.skip("Нет путей с интервалом 0 в правилах throttle")

        pattern = blocked_keys[0]
        concrete_path = pattern.replace("*", "0")

        mw = ThrottleMiddleware(rules)
        ctx: dict = {}
        proceed, _ = mw.before_set(
            path=concrete_path,
            value=1,
            source="camera_0",
            context=ctx,
        )
        assert proceed is False
        assert ctx.get("rejection_reason") == "throttled"

    def test_throttle_middleware_instantiation(self):
        """ThrottleMiddleware создаётся без ошибок с реальными правилами."""
        mw = ThrottleMiddleware(build_throttle_rules())
        assert mw.name == "throttle"

    def test_validation_middleware_instantiation(self):
        """ValidationMiddleware создаётся без ошибок с реальными правилами."""
        mw = ValidationMiddleware(build_validation_rules())
        assert mw.name == "validation"
