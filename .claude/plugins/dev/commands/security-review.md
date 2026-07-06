---
description: Run a focused read-only security audit of the diff (deserialization/IPC/injection/secret-leak) — drives the reviewer agent in security-only mode
---

Запусти агента **reviewer** (subagent_type: "reviewer", model: opus) в
**security-only режиме** — сфокусированный **read-only** аудит безопасности. С Phase 2
выделенный агент `security-review` свёрнут в `reviewer` → `## Specialization: Security`
(пять классов + secrets-audit). Агент только читает и отдаёт список находок; правки
применяет `developer`/`teamlead`, не он.

Входные данные: $ARGUMENTS — что аудировать (git diff, конкретные файлы, или номер Task X.Y).
Если $ARGUMENTS пуст — аудит последних изменений (`git diff` от последнего коммита).

Передай агенту:
1. Что аудировать: diff/файлы/Task.
2. Режим: «Прогони ТОЛЬКО `## Specialization: Security` — это выделенный pre-merge
   security-gate, не полное ревью. Остальные специализации (architecture, UI, …) пропусти».
3. Контекст: «Прочитай `CLAUDE.md` + `.claude/modes/_stack.md` — trust boundaries, IPC-карта,
   правило сериализации, конвенции секретов».
4. Напоминание: пять классов — deserialization, IPC/events, shared-memory, injection, secrets;
   секреты — через Bash `python scripts/secrets_audit/secrets_audit.py --format json`
   (тот же скрипт, что и `/core:quality:secrets-audit`), не новый MCP-tool.

После получения результата:
- Если находок нет (security clear) — сообщи пользователю (укажи использованные fallback'и,
  exit-статус `secrets_audit.py`, и что всё ещё стоит проверить вручную).
- Если есть находки (CHANGES REQUESTED) — покажи их (confirmed blocker'ы первыми),
  спроси пользователя: отправить `developer`/`teamlead` на исправление?

## Когда вызывать

- Перед merge ветки, где менялся код с десериализацией, IPC, пользовательским вводом,
  рендером HTML или авторизацией.
- Когда `/dev:review` (полное ревью) порекомендовал более глубокий security-проход.
- В составе `/dev:pipeline` перед `/dev:ship` для security-чувствительных задач.

## Когда НЕ вызывать

- Нет кода в зоне риска (чистый рефакторинг, docs, dep-bump) → пропусти.
- Нужна только проверка секретов → `/core:quality:secrets-audit` напрямую (дешевле).
- Нужно ПРИМЕНИТЬ фикс → это `developer`/`teamlead`, security-проход только диагностирует.

Что аудировать: $ARGUMENTS
