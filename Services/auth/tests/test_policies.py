# -*- coding: utf-8 -*-
"""
Тесты PasswordPolicy и LockoutPolicy.
"""
from __future__ import annotations

import pytest

from Services.auth.exceptions import WeakPassword
from Services.auth.policies import LockoutPolicy, PasswordPolicy


@pytest.fixture
def policy() -> PasswordPolicy:
    """Дефолтная политика паролей."""
    return PasswordPolicy()


# =============================================================================
# PasswordPolicy.validate — успешные случаи
# =============================================================================


def test_valid_password_passes(policy: PasswordPolicy) -> None:
    """Пароль с 3 классами и длиной >= 8 проходит валидацию."""
    # строчные + заглавные + цифры = 3 класса
    policy.validate("MyPassw0rd")


def test_valid_password_all_classes(policy: PasswordPolicy) -> None:
    """Пароль со всеми 4 классами проходит валидацию."""
    policy.validate("MyPass@1")


def test_valid_password_min_length_exact(policy: PasswordPolicy) -> None:
    """Пароль ровно min_length (8) с нужными классами проходит."""
    # строчные + заглавные + цифры = 3 класса, длина 8
    policy.validate("Abcde1fg")


# =============================================================================
# PasswordPolicy.validate — отказы
# =============================================================================


def test_too_short_raises(policy: PasswordPolicy) -> None:
    """Пароль короче min_length вызывает WeakPassword."""
    with pytest.raises(WeakPassword) as exc_info:
        policy.validate("Ab1!")  # 4 символа
    assert exc_info.value.code == "AUTH-006"
    assert "min_length" in exc_info.value.context.get("rule", "")


def test_too_long_raises() -> None:
    """Пароль длиннее max_length вызывает WeakPassword."""
    pol = PasswordPolicy(max_length=10)
    with pytest.raises(WeakPassword) as exc_info:
        pol.validate("A" * 11 + "b1@")
    assert "max_length" in exc_info.value.context.get("rule", "")


def test_max_length_72_enforced(policy: PasswordPolicy) -> None:
    """Пароль из 73 символов вызывает WeakPassword (bcrypt-ограничение)."""
    long_pass = "Aa1!" * 19  # 76 символов > 72
    with pytest.raises(WeakPassword):
        policy.validate(long_pass)


def test_insufficient_classes_raises(policy: PasswordPolicy) -> None:
    """Пароль только с одним классом символов не проходит."""
    with pytest.raises(WeakPassword) as exc_info:
        policy.validate("onlylower123")  # строчные + цифры = 2 класса, нужно 3
    # Проверяем, что причина — классы, не длина
    assert exc_info.value.context.get("rule") == "require_classes"


def test_only_lowercase_and_upper_fails(policy: PasswordPolicy) -> None:
    """Только строчные + заглавные (2 класса) — не проходит при require_classes=3."""
    with pytest.raises(WeakPassword):
        policy.validate("OnlyLetters")


def test_only_lowercase_fails(policy: PasswordPolicy) -> None:
    """Только строчные буквы — не проходит."""
    with pytest.raises(WeakPassword):
        policy.validate("onlylowercase")


def test_symbol_class_helps(policy: PasswordPolicy) -> None:
    """Строчные + заглавные + спецсимвол = 3 класса — проходит."""
    policy.validate("MyPassword!!")  # lower + upper + symbol = 3


# =============================================================================
# PasswordPolicy — параметры
# =============================================================================


def test_custom_min_length() -> None:
    """Кастомный min_length применяется."""
    pol = PasswordPolicy(min_length=12)
    with pytest.raises(WeakPassword):
        pol.validate("Short@1Aa")  # 9 символов < 12


def test_custom_require_classes() -> None:
    """require_classes=2 позволяет пароль с 2 классами."""
    pol = PasswordPolicy(require_classes=2)
    pol.validate("onlylower123")  # строчные + цифры = 2


def test_require_classes_4() -> None:
    """require_classes=4 требует все 4 класса."""
    pol = PasswordPolicy(require_classes=4)
    with pytest.raises(WeakPassword):
        pol.validate("MyPassword1")  # нет спецсимвола — 3 класса
    pol.validate("MyPassword1!")  # все 4


# =============================================================================
# LockoutPolicy
# =============================================================================


def test_lockout_policy_defaults() -> None:
    """Дефолтные значения LockoutPolicy."""
    pol = LockoutPolicy()
    assert pol.failed_threshold == 5
    assert pol.delays_sec == [30, 60, 120, 240, 480]
    assert pol.reset_after_sec == 1800


def test_get_delay_first() -> None:
    """Первая блокировка — первая задержка."""
    pol = LockoutPolicy()
    assert pol.get_delay(0) == 30


def test_get_delay_second() -> None:
    """Вторая блокировка — вторая задержка."""
    pol = LockoutPolicy()
    assert pol.get_delay(1) == 60


def test_get_delay_cap() -> None:
    """Превышение индекса — возвращает последнее значение (cap 480)."""
    pol = LockoutPolicy()
    assert pol.get_delay(10) == 480


def test_get_delay_last_index() -> None:
    """Последний индекс массива возвращает 480."""
    pol = LockoutPolicy()
    assert pol.get_delay(4) == 480


def test_custom_delays() -> None:
    """Кастомные задержки применяются корректно."""
    pol = LockoutPolicy(delays_sec=[10, 20, 30])
    assert pol.get_delay(0) == 10
    assert pol.get_delay(2) == 30
    assert pol.get_delay(5) == 30  # cap
