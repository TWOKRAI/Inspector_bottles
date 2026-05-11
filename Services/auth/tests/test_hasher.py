# -*- coding: utf-8 -*-
"""
Тесты BcryptHasher.

Bcrypt rounds=4 для скорости тестов.
"""
from __future__ import annotations

import pytest

from Services.auth.hasher import BcryptHasher


ROUNDS = 4


@pytest.fixture
def hasher() -> BcryptHasher:
    return BcryptHasher(rounds=ROUNDS)


# =============================================================================
# Основные сценарии
# =============================================================================


def test_hash_returns_string(hasher: BcryptHasher) -> None:
    """hash() возвращает непустую строку."""
    result = hasher.hash("MyPassword@1")
    assert isinstance(result, str)
    assert len(result) > 0


def test_hash_starts_with_bcrypt_prefix(hasher: BcryptHasher) -> None:
    """Хеш имеет формат bcrypt ($2b$...)."""
    result = hasher.hash("MyPassword@1")
    assert result.startswith("$2b$")


def test_round_trip_correct_password(hasher: BcryptHasher) -> None:
    """Верный пароль успешно верифицируется."""
    password = "CorrectHorse@1"
    hashed = hasher.hash(password)
    assert hasher.verify(password, hashed) is True


def test_round_trip_wrong_password(hasher: BcryptHasher) -> None:
    """Неверный пароль не верифицируется."""
    password = "CorrectHorse@1"
    hashed = hasher.hash(password)
    assert hasher.verify("WrongHorse@2", hashed) is False


def test_same_password_different_hashes(hasher: BcryptHasher) -> None:
    """Каждый вызов hash() создаёт уникальный хеш (разные соли)."""
    password = "SamePassword@1"
    h1 = hasher.hash(password)
    h2 = hasher.hash(password)
    assert h1 != h2


# =============================================================================
# Разные rounds
# =============================================================================


def test_verify_cross_rounds() -> None:
    """Хеш, созданный с rounds=4, верифицируется hasher'ом с другим rounds."""
    hasher4 = BcryptHasher(rounds=4)
    hasher6 = BcryptHasher(rounds=6)
    password = "CrossRounds@1"
    hashed = hasher4.hash(password)
    # bcrypt хранит rounds внутри хеша, verify не зависит от self._rounds
    assert hasher6.verify(password, hashed) is True


def test_rounds_property(hasher: BcryptHasher) -> None:
    """rounds property возвращает переданное значение."""
    assert hasher.rounds == ROUNDS


# =============================================================================
# Граничные случаи и защита от ошибок
# =============================================================================


def test_verify_empty_password_returns_false(hasher: BcryptHasher) -> None:
    """Верификация пустого пароля возвращает False, не исключение."""
    hashed = hasher.hash("ValidPassword@1")
    assert hasher.verify("", hashed) is False


def test_verify_malformed_hash_returns_false(hasher: BcryptHasher) -> None:
    """Верификация с malformed-хешем возвращает False, не исключение."""
    assert hasher.verify("SomePassword", "not_a_valid_hash") is False


def test_hash_empty_password_raises(hasher: BcryptHasher) -> None:
    """hash() пустого пароля выбрасывает ValueError."""
    with pytest.raises(ValueError, match="пустым"):
        hasher.hash("")


def test_hash_non_string_raises(hasher: BcryptHasher) -> None:
    """hash() не-строки выбрасывает TypeError."""
    with pytest.raises(TypeError):
        hasher.hash(12345)  # type: ignore[arg-type]


def test_invalid_rounds_raises() -> None:
    """rounds < 4 вызывает ValueError при создании BcryptHasher."""
    with pytest.raises(ValueError, match="rounds"):
        BcryptHasher(rounds=3)
