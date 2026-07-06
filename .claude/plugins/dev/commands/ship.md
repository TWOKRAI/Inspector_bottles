---
description: Final check before merge/push — tests + linter + review of the changes
disable-model-invocation: true
---

Выполни финальную проверку перед отправкой кода:

1. **Quality gate:**
   ```bash
   make gate        # если Makefile есть (lint + типы + тесты)
   ```
   Fallback (если make недоступен):
   ```bash
   uv run ruff check .
   uv run pyright
   uv run pytest -q
   ```

2. **Итог изменений:**
   ```bash
   git diff --stat
   git log --oneline -5
   ```

3. **Проверка Refs-трассировки (plan-driven workflow):**
   - Определи текущую ветку: `git branch --show-current`
   - Извлеки slug из имени ветки (всё после `feat/`, `fix/`, `refactor/`, `docs/` и т.д.)
   - Найди файл плана (новая конвенция — дата в имени):
     - Single plan: `ls plans/*_<slug>.md` (формат `plans/YYYY-MM-DD_<slug>.md`)
     - Multi-phase: `ls -d plans/*_<slug>` (папка `plans/YYYY-MM-DD_<slug>/`)
   - Если план найден — **план→коммит инфорсен (Phase 1.6): БЛОКИРУЙ ship**, если хоть
     один коммит `main..HEAD` без `Refs:` (раньше было только предупреждение). Проверь
     каждый коммит, а не агрегатным `--grep` (он зелёный, даже если Refs только у одного):
     ```bash
     missing=$(git log --format='%H %s' main..HEAD | while read -r sha subj; do
       git log -1 --format=%B "$sha" | grep -q '^Refs:' || echo "  ✗ $sha $subj"
     done)
     if [ -n "$missing" ]; then
       echo "STOP: коммиты без Refs: на план — допиши Refs (rebase/amend) перед ship:"
       echo "$missing"
       exit 1
     fi
     ```
     - Прочитай план (single `plan.md` или metaplan + phase-N.md) и проверь: если все Task = [DONE] → предложи закрыть план (Status: DONE)
   - Если план НЕ найден (legacy ветка, hotfix, старая конвенция без даты) — пропусти, не блокируй (нет плана = нет требования Refs)

4. **Результат:**
   - Если всё зелёное — предложи commit message в правильном формате
     (см. ниже) и спроси разрешение на push
   - Если есть ошибки — покажи их и предложи исправить

## Закрытие плана + архив (archive-on-done)

Если план найден и все Task = [DONE] (остаток — только backlog / гейт будущего релиза):

1. **Статус → DONE** в плане: `Status: DONE` (single) или все фазы `[DONE]` в §2 (multi-phase).
2. **Архивируй план** (он покидает активный набор — archive-on-done):
   ```bash
   # quarter = по дате в имени плана (Q1=Jan-Mar, Q2=Apr-Jun, Q3=Jul-Sep, Q4=Oct-Dec)
   git mv plans/YYYY-MM-DD_<slug>.md plans/_archive/<YYYY-Qn>/   # single
   git mv plans/YYYY-MM-DD_<slug>/   plans/_archive/<YYYY-Qn>/   # multi-phase
   ```
3. **Обнови ledger** `plans/README.md`: перенеси строку из «Active» в «Archived».
   Добавь строку в `plans/_archive/<YYYY-Qn>/README.md` (создай файл с шапкой, если квартала ещё нет).
4. Коммит:
   ```bash
   git add plans/
   git commit -m "docs(plans): архив <slug> (план выполнен)

   Why: все задачи плана выполнены → archive-on-done
   Layer: docs
   Refs: plans/_archive/<YYYY-Qn>/<slug>(.md|/plan.md)"   # пропусти Layer если commit-layers.txt пуст
   ```

**НИКОГДА** не удаляй план (история `Refs:` зависит от него) и **НЕ** архивируй план
с открытыми пунктами — держи его в «Active» (`plans/README.md`) с пометкой остатка.

## Формат commit-сообщения

**Canonical guide:** [`.claude/COMMIT_GUIDE.md`](../../COMMIT_GUIDE.md) — полный формат, типы, trailers, примеры.
**Project settings:** [`.claude/modes/_stack.md`](../../.claude/modes/_stack.md) (validator on/off) + [`.claude/commit-layers.txt`](../../.claude/commit-layers.txt) (если файл пуст → `Layer:` опционален).

Hook `commit-msg` отклоняет неправильный формат (если установлен). Перед коммитом можно прогнать валидацию вручную:

```bash
echo "<полное сообщение>" | python3 scripts/validate_commit/validate_commit.py -
```

$ARGUMENTS
