# scripts/validate_commit/ — валидатор commit-сообщений

Проверяет формат commit-сообщения по правилам Inspector_bottles
(Conventional Commits + обязательные trailers `Why:` / `Layer:`).

Полный гайд по формату: [`docs/claude/COMMIT_GUIDE.md`](../../docs/claude/COMMIT_GUIDE.md).

## Установка hook

```bash
bash scripts/validate_commit/install_hook.sh
```

Ставит `commit-msg` hook в `.git/hooks/`. Запускается автоматически на
каждом `git commit` (кроме `--no-verify`).

## Запуск вручную

```bash
# Из файла
python3 scripts/validate_commit/validate_commit.py path/to/commit-msg.txt

# Из stdin
git log -1 --format=%B | python3 scripts/validate_commit/validate_commit.py -
```

Exit code: `0` — OK, `1` — есть ошибки.

## Что проверяется

| Правило | Тип |
|---|---|
| Subject в формате `<type>(<scope>): <subject>` | error |
| `type` из whitelist (feat/fix/refactor/...) | error |
| Subject ≤ 72 символа | warning |
| Пустая строка между subject и body | error |
| Trailer `Why:` присутствует | error |
| Trailer `Layer:` присутствует | error |
| `Layer:` значения из whitelist | error |
| `Risk:` начинается с low/medium/high | warning |
| `Reversible:` ∈ {yes, no, migration-needed} | warning |
| Неизвестные trailers | warning |
| Слишком короткий `Why:` (<5 симв) | warning |

## Что НЕ проверяется (skip)

- Merge-коммиты (`Merge ...`)
- Revert-коммиты (`Revert ...`)
- Fixup/squash для interactive rebase (`fixup!`, `squash!`, `amend!`)

## CI-интеграция (опционально)

```bash
# Проверить все коммиты PR-ветки против main
for sha in $(git log --format=%H main..HEAD); do
    git log -1 --format=%B "$sha" | \
        python3 scripts/validate_commit/validate_commit.py - || exit 1
done
```

## Расширение whitelist'ов

Whitelist'ы захардкожены в [`validate_commit.py`](validate_commit.py):

- `ALLOWED_TYPES` — типы Conventional Commits
- `ALLOWED_LAYERS` — слои архитектуры (синхронизируй с CLAUDE.md правило 9)
- `ALLOWED_RISK`, `ALLOWED_REVERSIBLE` — значения trailer'ов
- `KNOWN_TRAILERS` — все известные trailers (неизвестные → warning)

При расширении: обновить `validate_commit.py` + `.gitmessage` (шаблон) +
`docs/claude/COMMIT_GUIDE.md`.

## Bypass

```bash
git commit --no-verify  # только для merge/rebase
```
