# -*- coding: utf-8 -*-
"""
Политики безопасности для модуля auth.

PasswordPolicy — правила валидации паролей (длина, классы символов).
LockoutPolicy  — правила блокировки после неудачных попыток входа.

Оба класса используются внутри AuthConfig (models.py) и напрямую
компонентами BcryptHasher / LockoutTracker.
"""
from __future__ import annotations

import re
from typing import Annotated

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase

from .exceptions import WeakPassword


class PasswordPolicy(SchemaBase):
    """
    Политика паролей.

    Параметры:
        min_length          — минимальная длина пароля
        max_length          — максимальная длина (ограничение bcrypt = 72 байта)
        require_classes     — минимальное число классов символов из 4 (lower/upper/digit/symbol)
        bcrypt_rounds_prod  — rounds для bcrypt в production
        bcrypt_rounds_test  — rounds для bcrypt в тестах (низкое для скорости)
    """

    min_length: Annotated[
        int,
        FieldMeta(
            "Минимальная длина пароля",
            info="Минимальное число символов в пароле.",
            min=4, max=128,
        ),
    ] = 8

    max_length: Annotated[
        int,
        FieldMeta(
            "Максимальная длина пароля",
            info="Ограничение bcrypt — не более 72 байт.",
            min=8, max=128,
        ),
    ] = 72

    require_classes: Annotated[
        int,
        FieldMeta(
            "Требуемое число классов символов",
            info="Из 4 классов: строчные, заглавные, цифры, спецсимволы.",
            min=1, max=4,
        ),
    ] = 3

    bcrypt_rounds_prod: Annotated[
        int,
        FieldMeta(
            "Rounds bcrypt (production)",
            info="Стоимость хеширования в prod-окружении.",
            min=4, max=31,
        ),
    ] = 12

    bcrypt_rounds_test: Annotated[
        int,
        FieldMeta(
            "Rounds bcrypt (тесты)",
            info="Стоимость хеширования в тестах (низкое для скорости).",
            min=4, max=14,
        ),
    ] = 4

    # -------------------------------------------------------------------------
    # Константы классов символов
    # -------------------------------------------------------------------------

    _RE_LOWER = re.compile(r"[a-z]")
    _RE_UPPER = re.compile(r"[A-Z]")
    _RE_DIGIT = re.compile(r"[0-9]")
    _RE_SYMBOL = re.compile(r"[^a-zA-Z0-9]")

    def validate(self, password: str) -> None:
        """
        Проверить пароль по политике.

        Raises:
            WeakPassword — если пароль не соответствует требованиям.
        """
        if len(password) < self.min_length:
            raise WeakPassword(
                f"Пароль слишком короткий: минимум {self.min_length} символов.",
                rule="min_length",
                required=self.min_length,
                actual=len(password),
            )

        if len(password) > self.max_length:
            raise WeakPassword(
                f"Пароль слишком длинный: максимум {self.max_length} символов (ограничение bcrypt).",
                rule="max_length",
                required=self.max_length,
                actual=len(password),
            )

        classes_present = sum([
            bool(self._RE_LOWER.search(password)),
            bool(self._RE_UPPER.search(password)),
            bool(self._RE_DIGIT.search(password)),
            bool(self._RE_SYMBOL.search(password)),
        ])

        if classes_present < self.require_classes:
            raise WeakPassword(
                f"Пароль должен содержать символы из не менее {self.require_classes} классов "
                f"(строчные, заглавные, цифры, спецсимволы). Найдено: {classes_present}.",
                rule="require_classes",
                required=self.require_classes,
                actual=classes_present,
            )

    model_config = {
        **SchemaBase.model_config,
        "arbitrary_types_allowed": True,
    }


class LockoutPolicy(SchemaBase):
    """
    Политика блокировки аккаунта после неудачных попыток входа.

    Параметры:
        failed_threshold    — число неудач до первой блокировки
        delays_sec          — список задержек (экспоненциальный backoff): [30, 60, 120, 240, 480]
        reset_after_sec     — секунд неактивности → счётчик обнуляется
    """

    failed_threshold: Annotated[
        int,
        FieldMeta(
            "Порог неудачных попыток",
            info="Число неудачных входов до блокировки.",
            min=1, max=100,
        ),
    ] = 5

    reset_after_sec: Annotated[
        int,
        FieldMeta(
            "Сброс после бездействия (сек)",
            info="Через сколько секунд неактивности счётчик ошибок обнуляется.",
            min=1, max=86400,
        ),
    ] = 1800

    delays_sec: list[int] = [30, 60, 120, 240, 480]
    """Задержки при последовательных блокировках (экспоненциальный backoff)."""

    def get_delay(self, failure_index: int) -> int:
        """
        Вернуть задержку для указанного индекса блокировки (0-based).

        При превышении списка возвращает последнее значение (cap).
        """
        if not self.delays_sec:
            return 0
        idx = min(failure_index, len(self.delays_sec) - 1)
        return self.delays_sec[idx]
