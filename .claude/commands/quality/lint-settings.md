---
description: Проверить .claude/settings.json — критичные deny/ask/allow и хуки на месте?
---

Запусти проверку инвариантов `settings.json`:

```bash
python scripts/lint_settings.py
```

Что проверяет:

1. **`deny` содержит критичные паттерны:** `--no-verify`, `git push --force`, `git reset --hard`, `git clean -f`, `sudo`, `chmod 777`, `mkfs`, `dd if=`
2. **Secrets защищены:** `Write/Edit(**/.env)`, `**/*.pem`, `**/*.key`, `**/id_rsa`, `**/id_ed25519`
3. **`allow` не содержит slop-векторов:** `uv add *`, `pip install *`, `npx *`, `cp *`, `chmod *`, `git merge *`, `git rebase *`, `sudo *`, и др.
4. **Хуки подключены:** `validate-safe-command`, `protect-readonly`, `protect-branch`, `autoformat-python`, `check-imports`, `restore-context`, `session-health-check` (Stop-хук `session-end-daily-log` убран с v0.4.0 — журналирование переведено на pre-commit)

Exit codes:
- `0` — всё ок
- `1` — нарушены required invariants (CI должен падать)
- `2` — только warnings (рекомендуется исправить)

Запуск в strict-режиме (warnings → fail):
```bash
python scripts/lint_settings.py --strict
```

**Когда вызывать:**
- Перед `/ship` если правил `settings.json` в этой сессии
- В CI workflow на каждый PR
- После `claude-kit upgrade --apply` чтобы убедиться что upgrade не уронил защиту
- Когда подозреваешь что кто-то локально ослабил permissions
