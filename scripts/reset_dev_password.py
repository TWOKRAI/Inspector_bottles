#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/reset_dev_password.py — сбросить пароль dev-пользователя.

Используется в dev-окружении когда:
- Забыл пароль установленный при bootstrap.
- Нужно синхронизировать пароль с `multiprocess_prototype/dev_settings.py`.

Использование:
    python -m scripts.reset_dev_password <новый_пароль>
    python -m scripts.reset_dev_password <новый_пароль> --user <username>

Источник пути users.yaml: env `INSPECTOR_AUTH_USERS_PATH` (если задан),
иначе дефолт `~/.inspector_bottles/auth/users.yaml`.

Безопасность: пароль валидируется PasswordPolicy (минимум 8 символов,
3 из 4 классов символов). Скрипт работает только локально, на YAML-файле.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Сбросить пароль dev-пользователя")
    parser.add_argument("password", help="Новый пароль (plain-text)")
    parser.add_argument("--user", default="dev", help="Имя пользователя (по умолчанию: dev)")
    args = parser.parse_args()

    # Импорты после парсинга — быстрый ответ на --help
    from Services.auth import (
        AuthConfig,
        AuthManager,
        WeakPassword,
    )

    users_path = os.environ.get(
        "INSPECTOR_AUTH_USERS_PATH",
        str(Path.home() / ".inspector_bottles" / "auth" / "users.yaml"),
    )

    if not Path(users_path).exists():
        print(f"[ERROR] Файл хранилища не найден: {users_path}", file=sys.stderr)
        print(
            "        Сначала запусти bootstrap: python -m Services.auth.bootstrap",
            file=sys.stderr,
        )
        return 1

    config = AuthConfig(users_path=users_path)
    manager = AuthManager(config)
    manager.initialize()

    # Не используем `manager.reset_password` (он генерит случайный пароль).
    # Делаем вручную через storage — иначе нельзя задать конкретный пароль.
    storage = manager._storage  # type: ignore[attr-defined]
    hasher = manager._hasher  # type: ignore[attr-defined]

    try:
        config.password_policy.validate(args.password)
    except WeakPassword as exc:
        print(f"[ERROR] Слабый пароль: {exc}", file=sys.stderr)
        return 2

    users = storage.load()
    user = users.get(args.user)
    if user is None:
        print(f"[ERROR] Пользователь '{args.user}' не найден.", file=sys.stderr)
        print(f"        Доступные: {sorted(users.keys())}", file=sys.stderr)
        return 3

    updated = user.model_copy(update={"password_hash": hasher.hash(args.password)})
    users[args.user] = updated
    storage.save(users)

    print(f"[OK] Пароль пользователя '{args.user}' обновлён.")
    print(f"     Файл: {users_path}")
    print('     Теперь пропиши тот же пароль в multiprocess_prototype/dev_settings.py: DEV_PASSWORD = "..."')
    return 0


if __name__ == "__main__":
    sys.exit(main())
