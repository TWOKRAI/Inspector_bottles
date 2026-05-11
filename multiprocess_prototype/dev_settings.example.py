# -*- coding: utf-8 -*-
"""dev_settings.py — локальные dev-настройки приложения.

⚠️  Это **шаблон**. Скопируй в `dev_settings.py` (без `.example`) и отредактируй.
    Файл `dev_settings.py` в `.gitignore` — пароли не попадут в репозиторий.

Используется в `multiprocess_prototype/frontend/app.py` для удобного dev-режима:
автологин под dev-пользователя, без необходимости вводить пароль каждый раз
и без выставления env-переменных в shell.

Приоритет:
    env (`INSPECTOR_AUTH_DEV_AUTO_LOGIN`, `INSPECTOR_DEV_PASSWORD`, `INSPECTOR_DEV_USERNAME`)
    →  переопределяет
    `dev_settings.py` (этот файл)
    →  переопределяет
    дефолты в коде

Так prod / CI могут перебить env'ом, а локальная разработка — через этот файл.

Безопасность:
- НЕ редактируй `dev_settings.example.py` (он в репо). Редактируй только `dev_settings.py`.
- Пароль здесь — plain-text. **Не выставляй DEV_AUTO_LOGIN = True в production.**
- Если забыл пароль `dev`-пользователя — сбрось через
  `python -m scripts.reset_dev_password <новый_пароль>`
  (см. ниже инструкцию).
"""
from __future__ import annotations

# Автоматически логиниться при старте приложения под пользователем DEV_USERNAME.
# True  → залогинится без LoginDialog при наличии валидного пароля.
# False → штатный LoginDialog (как в prod).
DEV_AUTO_LOGIN: bool = False

# Имя пользователя для автологина. Должен существовать в users.yaml.
DEV_USERNAME: str = "dev"

# Пароль в plain-text. Заполни после копирования файла.
# Если не помнишь пароль:
#   python -m scripts.reset_dev_password <новый_пароль>
DEV_PASSWORD: str = ""
