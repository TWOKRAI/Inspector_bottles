---
description: Audit for secret leaks (API keys, JWT, private keys, hardcoded passwords) via regex
---

Запусти аудит утечек secrets в исходниках:

```bash
python scripts/secrets_audit/secrets_audit.py
```

Что ловит: AWS / GCP / Azure ключи, GitHub/GitLab PAT, OpenAI / Anthropic API keys, Stripe live, Slack / Telegram tokens, JWT, PEM/OpenSSH private keys, basic-auth в URL, generic `password|secret|token = "..."` присваивания.

Конфиг паттернов и allowlist: [scripts/secrets_audit/secrets_audit.toml](../../scripts/secrets_audit/secrets_audit.toml). Детали и Exit-коды — [README.md](../../scripts/secrets_audit/README.md).

Полезные варианты:
- `python scripts/secrets_audit/secrets_audit.py --root src` — только конкретный подкаталог.
- `python scripts/secrets_audit/secrets_audit.py --format json` — для CI/нотификаций.
- `python scripts/secrets_audit/secrets_audit.py --no-strict` — отчёт без падения (exit 0 даже при находках).

**Exit-коды:** `0` — чисто, `1` — есть находки (под `strict=true`), `2` — ошибка конфига.

**Когда использовать:**
- Перед коммитом / в `pre-push` хуке (вместе с sentrux).
- В CI как gate перед merge в main.
- При onboarding'е open-source репо — поиск артефактов разработки.

**Замечания:**
- Inline-suppression: добавь `# secrets-audit: ignore` в той же строке для разовых исключений (например, заведомо тестовый ключ в snippet'е документации).
- Тестовые fixtures (`tests/fixtures/**`, `tests/data/**`, `**/test_*.py`) уже в allowlist — поправь конфиг под свой стек.
- Regex — не AST: не отличает литерал от комментария. Для глубокого аудита git-истории смотри `gitleaks` / `trufflehog`.

$ARGUMENTS
