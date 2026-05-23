# Commit message format — TL;DR

Hook `commit-msg` валидирует автоматически. Полный референс с примерами и edge-cases: **[`.claude/COMMIT_GUIDE_REFERENCE.md`](COMMIT_GUIDE_REFERENCE.md)**.

## Шаблон

```
<type>(<scope>): краткое imperative описание

- bullets: что сделано (файлы, классы, числа тестов)
- describe implementation, not motivation

Why: одна-две строки про мотивацию
Layer: <one or many from .claude/commit-layers.txt>
Refs: plans/<slug>.md, ADR-XXX, PR#NN
Risk: low|medium|high — короткое почему
Reversible: yes | migration-needed | no
Tested: scope/N passed
Rejected: alternative X — rejected because Y

Co-Authored-By: ...
```

## Обязательные поля

| Trailer | Когда | Что |
|---|---|---|
| **subject** | всегда | `<type>(<scope>): description` (Conventional Commits) |
| **`Why:`** | всегда | мотивация (не реализация). Одна-две строки. |
| **`Layer:`** | если `.claude/commit-layers.txt` непустой | значение из whitelist |
| **`Refs:`** | если есть `plans/<slug>.md` для текущей ветки `<type>/<slug>` | путь к плану (+ ADR, PR опционально) |

Остальные trailers (`Risk:`, `Reversible:`, `Tested:`, `Rejected:`) — opt-in, но добавляй когда есть что сказать. Особенно `Rejected:` — самое ценное поле через год.

## Types

`feat` · `fix` · `refactor` · `docs` · `test` · `chore` · `perf` · `build` · `ci` · `revert`

Breaking change → `!` suffix: `feat(api)!: drop legacy endpoint`.

## Don'ts

- ❌ Дублировать body и `Why:` — body = что, Why = почему
- ❌ `--no-verify` для обхода валидации (только merge/rebase fixes)
- ❌ Переводить ключи trailers (`Зачем:`, `Слой:`) — parser expects Latin
- ❌ `Tested:` в body — должен быть отдельный trailer для `git log --grep`

## Когда читать REFERENCE

Открывай **[COMMIT_GUIDE_REFERENCE.md](COMMIT_GUIDE_REFERENCE.md)** если нужно:

- Полный пример хорошего коммита с разбором
- Точные определения `Risk:` / `Reversible:` / `Tested:` / `Rejected:`
- Три режима поведения `Layer:` (файл missing / non-empty / empty)
- Git history queries (`--grep`, `--trailer`, cheat-sheet)
- Edge cases: Detached HEAD, hotfix-branches, `fixup!`/`squash!`/`amend!`
- Почему этот формат вообще нужен (ROI обоснование)
