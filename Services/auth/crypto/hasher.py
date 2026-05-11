# -*- coding: utf-8 -*-
"""
BcryptHasher — хеширование и верификация паролей через bcrypt.

Rounds передаётся в конструктор; рекомендуется rounds=12 (prod), rounds=4 (test).
Никогда не логирует plain-text пароли и хеши.

Использование:
    from Services.auth.hasher import BcryptHasher

    hasher = BcryptHasher(rounds=12)
    hashed = hasher.hash("MySecret@1")
    assert hasher.verify("MySecret@1", hashed) is True
    assert hasher.verify("WrongPass", hashed) is False
"""
from __future__ import annotations

import bcrypt


class BcryptHasher:
    """
    Утилита для хеширования паролей через bcrypt.

    Атрибуты:
        rounds — cost factor bcrypt (work factor).
                 prod: 12, test: 4.
    """

    def __init__(self, rounds: int = 12) -> None:
        if not (4 <= rounds <= 31):
            raise ValueError(f"rounds должен быть от 4 до 31, получено: {rounds}")
        self._rounds = rounds

    @property
    def rounds(self) -> int:
        """Cost factor, переданный в конструктор."""
        return self._rounds

    def hash(self, password: str) -> str:
        """
        Хешировать пароль через bcrypt.

        Args:
            password — plain-text пароль (строка).
                       Bcrypt обрабатывает первые 72 байта UTF-8.

        Returns:
            Строка bcrypt-хеша (формат $2b$...).

        Raises:
            ValueError — если password не строка или пустой.
        """
        if not isinstance(password, str):
            raise TypeError(f"password должен быть str, получено {type(password).__name__}")
        if not password:
            raise ValueError("password не может быть пустым")

        salt = bcrypt.gensalt(rounds=self._rounds)
        hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
        return hashed.decode("utf-8")

    def verify(self, password: str, hashed: str) -> bool:
        """
        Проверить пароль против bcrypt-хеша.

        Args:
            password — plain-text пароль для проверки.
            hashed   — хеш из хранилища (строка).

        Returns:
            True если пароль совпадает, False в противном случае.
            Никогда не выбрасывает исключение при неверном пароле.
        """
        if not isinstance(password, str) or not isinstance(hashed, str):
            return False
        if not password or not hashed:
            return False

        try:
            return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            # Защита от malformed-хешей — считаем неверным паролем
            return False
