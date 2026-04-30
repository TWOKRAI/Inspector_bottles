---
name: kb-lint
description: Семантический health-check wiki по Karpathy + impute через web search. 7 проверок — противоречия, stale-факты, orphans, asymmetric backlinks, empty stubs (<200 слов), missing pages, type validation (frontmatter type из enum schema.md). Структурный слой делегирует /library. Только отчёт, не правит.
---

# kb-lint

Семантический lint wiki. Структуру (broken links, дубли, frontmatter) делегирует `/library`. Сам делает 6 проверок:

| Проверка | Что ищет |
|---|---|
| contradictions | парные конфликты внутри темы (X говорит N=5 vs Y говорит N=10) |
| stale | версии/даты/цены старше актуальных (по `pyproject.toml` + общему знанию) |
| orphans | incoming wikilinks = 0 (исключая index/log/schema/qa/daily) |
| asymmetric | A → B есть, B → A нет |
| empty stubs | статьи < 200 слов (без учёта frontmatter и `## Связи`) |
| missing pages | `[[ссылка]]` на тему, страницы нет → если `--impute` → web search → создать заглушку |
| **type validation** | `type:` отсутствует в frontmatter (MEDIUM) ИЛИ не из enum (HIGH). Enum см. `wiki/schema.md` |

## Вход

```
kb-lint [--scope all|topic:<name>|since:YYYY-MM-DD] [--severity high|all] [--impute] [--dry-run]
```

- `--impute` — для missing pages делает WebSearch и создаёт seed-статью со `status: draft`. Без флага — только список.
- `--dry-run` — отчёт только в чат, не пишет в `workspace/lint_reports/`.

## Алгоритм

1. **`/library check`** → структурные находки (войдут в HIGH).
2. **Параллельный sweep по темам** (до 6 агентов):
   - Для каждой темы запусти 1 subagent с парами/тройками статей.
   - Промпт: «Найди противоречия. Формат: `[[A]]: «цитата» vs [[B]]: «цитата»`. Нет — `OK`.»
3. **Stale**: статьи `date_updated > 6 мес` ИЛИ `status: draft > 3 мес` → грепни маркеры (Claude X.X, Python X.X, цены, "недавно").
4. **Orphans + asymmetric**: один проход grep `[[wikilink]]` по `wiki/**/*.md`, построить граф, инвертировать.
5. **Empty stubs**: `wc -w` минус frontmatter и хвостовая секция связей. < 200 → флаг.
6. **Missing pages**: разница (упомянутые `[[X]]` ∖ существующие файлы). Если `--impute` → для каждого WebSearch запросом `<X> wiki context` → создать `wiki/{topic-guess}/X.md` с фронтматтером и кратким seed-summary.
7. **Type validation**: проход по всем `wiki/**/*.md` (исключая spec/qa/daily). Парси frontmatter. Без `type:` → MEDIUM. С `type:` не из enum (`concept|person|paper|video|tool|comparison|qa|daily`) → HIGH.
8. **Append log.md**:
   ```
   ## [YYYY-MM-DD] lint | scope=<s> sev=<h/m/l>
   - HIGH: n1, MEDIUM: n2, LOW: n3
   - Imputed: N (если --impute)
   ```

## Формат отчёта

```markdown
# kb-lint от YYYY-MM-DD

Статей: N | Orphans: M | Asymmetric: K | Stubs: S | Missing: P
HIGH: n1 | MEDIUM: n2 | LOW: n3

## HIGH
🔴 contradiction [[A]]/[[B]]: «X=5» vs «X=10» → /synthesize
🔴 broken (от /library) [[C]]: [[gone]] → /library
🔴 type-invalid [[K]]: type=`unknownX` (не из enum) → исправить или удалить

## MEDIUM
🟡 stale [[D]] (Claude 3.5 vs Opus 4.7) → /curate <свежий>
🟡 orphan [[E]] → добавить incoming или /library
🟡 asymmetric [[F]] → [[G]] (нет обратной) → ручная правка
🟡 type-missing [[J]] → добавить `type:` (см. wiki/schema.md)

## LOW
🟢 stub [[H]] (120 слов) → дописать или удалить
🟢 missing [[concept-X]] → kb-lint --impute или kb-discover
```

## Правила

- Read-only. Никаких `--fix`. Imputed seed-статьи — только `status: draft`, требуют валидации `/library validate`.
- Параллелизм ≤ 6 (не упереться в RAM).
- Раз в 1-2 недели; чаще — дорого по токенам.
- Не сравнивать пары между темами — комбинаторный взрыв.
