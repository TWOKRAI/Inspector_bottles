"""validation.py — Middleware для валидации значений по схемам путей.

Проверяет тип, диапазон (min/max) и допустимые значения (enum)
для путей, заданных glob-паттернами. Пути без правил пропускаются.
"""

from __future__ import annotations

import logging
from typing import Any

from multiprocess_prototype.state_store.middleware.base import StateMiddleware
from multiprocess_prototype.state_store.core.subscription_manager import _split_pattern, _match_pattern


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

    def __init__(self, rules: dict[str, dict]) -> None:
        # rules: паттерн -> {"type": ..., "min": ..., "max": ..., "enum": [...]}
        self._rules = rules
        self._log = logging.getLogger(__name__)

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
            self._log.warning(
                "Validation rejected set('%s', %r): %s", path, value, error
            )
            return False, value

        return True, value

    def _find_rule(self, path: str) -> dict | None:
        """Найти первое матчащее правило для path."""
        path_segs = tuple(path.split("."))
        for pattern, rule in self._rules.items():
            pattern_segs = _split_pattern(pattern)
            if _match_pattern(pattern_segs, path_segs):
                return rule
        return None

    def _validate(self, value: Any, rule: dict) -> str | None:
        """Валидировать значение по правилу.

        Returns:
            Описание ошибки или None если значение валидно.
        """
        # Проверка type
        if "type" in rule:
            if not isinstance(value, rule["type"]):
                expected = (
                    rule["type"].__name__
                    if isinstance(rule["type"], type)
                    else str(rule["type"])
                )
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
