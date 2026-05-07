"""validation.py — Middleware для валидации значений по схемам путей.

Проверяет тип, диапазон (min/max) и допустимые значения (enum)
для путей, заданных glob-паттернами. Пути без правил пропускаются.
"""

from __future__ import annotations

from typing import Any

from ..core import match_pattern, split_pattern
from .base import StateMiddleware


class ValidationMiddleware(StateMiddleware):
    """Валидация значений по схемам путей.

    Пример:
        ValidationMiddleware({
            "cameras.*.config.fps": {"type": int, "min": 1, "max": 120},
            "cameras.*.config.camera_type": {"type": str, "enum": ["webcam", "hikvision", "simulator", "file"]},
            "cameras.*.config.resolution_width": {"type": int, "min": 1, "max": 7680},
            "renderer.config.overlay_alpha": {"type": float, "min": 0.0, "max": 1.0},
        })

    Правила валидации:
    - type: проверка isinstance (int, float, str, bool, list, dict)
    - min/max: для int/float — диапазон значений
    - enum: список допустимых значений
    - Путь не в правилах = пропускать (не валидировать)
    - Невалидное значение → reject + log warning + context['validation_error']
    """

    @property
    def name(self) -> str:
        return "validation"

    def __init__(self, rules: dict[str, dict], logger: Any = None) -> None:
        # rules: паттерн -> {"type": ..., "min": ..., "max": ..., "enum": [...]}
        self._rules = rules
        self._log = logger

    def add_rule(self, pattern: str, rule: dict) -> None:
        """Добавить правило валидации в runtime."""
        self._rules[pattern] = rule

    def before_set(self, path: str, value: Any, source: str, context: dict) -> tuple[bool, Any]:
        """Валидирует value для path перед записью в TreeStore.

        Если для path найдено правило и значение не проходит валидацию:
        - записывает описание ошибки в context["validation_error"]
        - записывает "validation" в context["rejection_reason"]
        - логирует warning
        - возвращает (False, value) — операция отклонена

        Если правило не найдено — пропускает без изменений.
        """
        # 1. Найти первое матчащее правило для path
        rule = self._find_rule(path)

        # 2. Если нет правила → пропустить
        if rule is None:
            return True, value

        # 3. Валидировать значение по найденному правилу
        error = self._validate(value, rule)

        # 4. Если невалидно — отклонить с логированием
        if error is not None:
            context["validation_error"] = error
            context["rejection_reason"] = "validation"
            if self._log is not None:
                self._log._log_warning(f"Validation rejected set('{path}', {value!r}): {error}")
            return False, value

        return True, value

    def _find_rule(self, path: str) -> dict | None:
        """Найти первое матчащее правило для path."""
        path_segs = tuple(path.split("."))
        for pattern, rule in self._rules.items():
            pattern_segs = split_pattern(pattern)
            if match_pattern(pattern_segs, path_segs):
                return rule
        return None

    def _validate(self, value: Any, rule: dict) -> str | None:
        """Валидировать значение по правилу.

        Returns:
            Описание ошибки или None если значение валидно.
        """
        # Проверка type. rule["type"] может быть type, кортежем types,
        # либо строкой (legacy) — формируем читаемое имя для каждого случая.
        if "type" in rule:
            if not isinstance(value, rule["type"]):
                expected = self._format_type(rule["type"])
                return f"Ожидается тип {expected}, получен {type(value).__name__}"

        # Проверка min (только для числовых типов)
        if "min" in rule and isinstance(value, (int, float)):
            if value < rule["min"]:
                return f"Значение {value} меньше минимума {rule['min']}"

        # Проверка max (только для числовых типов)
        if "max" in rule and isinstance(value, (int, float)):
            if value > rule["max"]:
                return f"Значение {value} больше максимума {rule['max']}"

        # Проверка enum
        if "enum" in rule:
            if value not in rule["enum"]:
                return f"Значение '{value}' не входит в допустимые: {rule['enum']}"

        return None

    @staticmethod
    def _format_type(type_spec: Any) -> str:
        """Читаемое имя для type/tuple-of-types/строки."""
        if isinstance(type_spec, type):
            return type_spec.__name__
        if isinstance(type_spec, tuple):
            return " | ".join(
                t.__name__ if isinstance(t, type) else str(t) for t in type_spec
            )
        return str(type_spec)
