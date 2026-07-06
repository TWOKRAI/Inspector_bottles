# secrets_audit

Аудит утечек secrets в исходниках по regex-паттернам. Stdlib-only, Python 3.12+.

**Дефолтные паттерны:**
AWS (Access Key + Secret), GCP (Service Account JSON, API Key), Azure Storage,
GitHub PAT (classic + fine-grained), GitLab PAT, OpenAI / Anthropic API keys,
Stripe live, Slack tokens, Telegram bot, JWT, PEM/OpenSSH private keys,
basic-auth в URL, generic `password|secret|token = "..."` присваивания.

## Быстрый старт

```bash
# Сканировать всё с дефолтным конфигом
python scripts/secrets_audit/secrets_audit.py

# Конкретный подкаталог
python scripts/secrets_audit/secrets_audit.py --root src

# JSON для CI (exit 1 при находках)
python scripts/secrets_audit/secrets_audit.py --format json

# Только отчёт, без падения (CI=soft mode)
python scripts/secrets_audit/secrets_audit.py --no-strict
```

## Exit-коды

| Код | Когда |
|-----|-------|
| `0` | Утечек не найдено |
| `1` | Есть утечки (в `--no-strict` → 0) |
| `2` | Ошибка конфига / scan root не существует / ни одного паттерна не загружено |

Идеально для **pre-push** хука и CI: дефолт `strict=true` → push блокируется при находке.

## Inline-suppression

В строке, которую заведомо хочется проигнорировать, добавь маркер:

```python
example_key = "AKIAEXAMPLE0000000000"  # secrets-audit: ignore
```

Маркер действует **только для этой строки** — не для всего файла.

## Allowlist для тестовых fixtures

В конфиге уже подключены типовые исключения:

```toml
path_patterns = [
    "tests/fixtures/**",
    "tests/data/**",
    "**/test_*.py",
    "**/conftest.py",
]
```

Тесты часто содержат фейковые ключи как реалистичные fixtures — это не утечки.
Если в твоём проекте тесты строже / отсутствуют — убери `**/test_*.py` из конфига.

## Что настраивается

| Секция | Что |
|--------|-----|
| `[scan]` | `root`, `recursive`, `follow_symlinks` |
| `[formats].include` | Расширения файлов (пустой = все) |
| `[exclude]` | `dirs` (имена), `file_patterns` (имена), `path_patterns` (relpath глобы) |
| `[detect].patterns` | Массив `[[detect.patterns]]` записей: `name`, `regex`, `entropy_check`, `min_entropy`, `ignore_case` |
| `[detect].default_min_entropy` | Дефолтный порог для паттернов с `entropy_check=true` без своего `min_entropy` |
| `[output]` | `format`, `group_by`, `sort_by`, `limit`, `max_text`, `strict` |

CLI-флаги (`--root`, `--format`, `--group-by`, `--sort-by`, `--limit`, `--no-strict`) перекрывают конфиг.

## Entropy check

Для generic-паттернов (которые могут давать false-positive на «обычных» словах) включается `entropy_check = true`. Считается **Shannon entropy** найденного матча; если ниже `min_entropy` — отбрасывается.

Эмпирические значения:
- `>= 4.5` — гарантированно случайная строка (high-entropy random key)
- `4.0–4.5` — вероятно секрет
- `3.0–4.0` — может быть human-readable пароль/токен
- `< 3.0` — обычное слово, шумит

Дефолт `4.0` — компромисс «ловим всё подозрительное, но без явного мусора».

## Колонки отчёта (`--format table`)

Две части:
1. **Сводка по `group_by`:** сколько находок на pattern / file.
2. **Список:** `pattern | entropy | file:line | match | text`.
   - `match` — что именно сматчилось (обрезается до 40 символов)
   - `text` — вся строка (обрезается до `max_text`)

## Когда полезно

- В `pre-commit` или `pre-push` хуке (вместе с sentrux).
- В CI как gate перед merge.
- При периодическом аудите (cron / `/loop`).
- При onboarding'е репо в open-source — быстрый поиск артефактов разработки.

## Ограничения

- **Regex, не AST.** Не отличает строковый литерал от комментария.
- **Не сканирует git-историю.** Только текущий tree. Для истории — `gitleaks` / `trufflehog`.
- **Не сканирует binary.** Файл читается с `errors="replace"`; чисто бинарные файлы фильтруются через `[formats].include` (не указано расширение → пропускается).
- **Inline-suppression — только посимвольно.** Маркер `secrets-audit: ignore` срабатывает на ту же строку, не на блок.
- **Дефолтные паттерны — best-effort.** Постоянно появляются новые форматы токенов; обновляй [secrets_audit.toml](secrets_audit.toml) под свой стек.
