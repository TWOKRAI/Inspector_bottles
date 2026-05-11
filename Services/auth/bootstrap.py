# -*- coding: utf-8 -*-
"""
Bootstrap CLI для первичной инициализации хранилища пользователей.

Создаёт predefined роли (dev/admin/operator/viewer) и первого пользователя:
- Если задан INSPECTOR_DEV_PASSWORD → dev-пользователь с ролью dev.
- Иначе → интерактивный prompt, создаётся admin-пользователь.

Exit codes:
    0 — успешная инициализация
    1 — хранилище уже инициализировано (users.yaml существует)
    2 — невалидный пароль (WeakPassword)
    3 — неожиданная ошибка

Использование:
    python -m Services.auth.bootstrap
"""
from __future__ import annotations

import getpass
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

from .crypto import BcryptHasher, PasswordPolicy
from .exceptions import WeakPassword
from .models import AuthConfig, User
from .predefined_roles import PREDEFINED_ROLES as _PREDEFINED_ROLES
from .storage import YamlUserStorage


def _create_user(
    username: str,
    password: str,
    role_name: str,
    hasher: BcryptHasher,
) -> User:
    """Создать объект User с хешированным паролем."""
    user_id = f"uid-{secrets.token_hex(8)}"
    return User(
        user_id=user_id,
        username=username,
        password_hash=hasher.hash(password),
        role_name=role_name,
        created_at=datetime.now(timezone.utc),
    )


def main() -> int:
    """
    Точка входа CLI.

    Returns:
        Exit code (0/1/2/3).
    """
    # Определяем путь к users.yaml (читаем env при каждом вызове)
    users_path = os.environ.get(
        "INSPECTOR_AUTH_USERS_PATH",
        str(Path.home() / ".inspector_bottles" / "auth" / "users.yaml"),
    )
    storage = YamlUserStorage(users_path)

    # Проверяем: уже инициализировано?
    if storage.exists():
        print(f"[ERROR] Хранилище уже инициализировано: {users_path}")
        print("  Для повторной инициализации удалите файл вручную.")
        return 1

    # Используем bcrypt rounds=12 (prod)
    hasher = BcryptHasher(rounds=12)
    policy = PasswordPolicy()

    # Режим 1: INSPECTOR_DEV_PASSWORD задан → dev-пользователь
    dev_password = os.environ.get("INSPECTOR_DEV_PASSWORD", "").strip()
    if dev_password:
        # Сначала валидируем пароль — до записи на диск
        try:
            policy.validate(dev_password)
        except WeakPassword as exc:
            print(f"[ERROR] INSPECTOR_DEV_PASSWORD не соответствует политике паролей: {exc}")
            return 2

        # Сохраняем роли и пользователя
        try:
            storage.save_roles(_PREDEFINED_ROLES)
            user = _create_user("dev", dev_password, "dev", hasher)
            storage.save({"dev": user})
            print(f"[OK] Создан пользователь 'dev' с ролью 'dev'")
            print(f"[OK] Predefined роли: {', '.join(_PREDEFINED_ROLES)}")
            print(f"[OK] Хранилище: {users_path}")
            return 0
        except Exception as exc:
            print(f"[ERROR] Не удалось создать пользователя: {exc}")
            return 3

    # Режим 2: Интерактивный prompt → admin-пользователь
    print("=== Inspector Bottles — первичная инициализация auth ===")
    print(f"Файл хранилища: {users_path}")
    print()

    # Username
    try:
        username = input("Имя пользователя [admin]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n[ABORT] Инициализация отменена.")
        return 3
    if not username:
        username = "admin"

    # Password (дважды)
    while True:
        try:
            password = getpass.getpass(f"Пароль для '{username}': ")
        except (EOFError, KeyboardInterrupt):
            print("\n[ABORT] Инициализация отменена.")
            return 3

        try:
            policy.validate(password)
        except WeakPassword as exc:
            print(f"[WARN] Пароль не соответствует требованиям: {exc}")
            print("  Требования: минимум 8 символов, ≥3 класса (lower/upper/digit/symbol)")
            continue

        try:
            password_confirm = getpass.getpass("Подтвердите пароль: ")
        except (EOFError, KeyboardInterrupt):
            print("\n[ABORT] Инициализация отменена.")
            return 3

        if password != password_confirm:
            print("[WARN] Пароли не совпадают. Повторите ввод.")
            continue

        break

    # Создаём роли и пользователя
    try:
        storage.save_roles(_PREDEFINED_ROLES)
        user = _create_user(username, password, "admin", hasher)
        storage.save({username: user})
        print(f"\n[OK] Создан пользователь '{username}' с ролью 'admin'")
        print(f"[OK] Predefined роли: {', '.join(_PREDEFINED_ROLES)}")
        print(f"[OK] Хранилище: {users_path}")
        return 0
    except Exception as exc:
        print(f"[ERROR] Не удалось создать пользователя: {exc}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
