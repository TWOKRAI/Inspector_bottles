# MEMORY — index

> **Status: empty by design.** Это не сломано — память специально пуста на старте.
> Заполняется автоматически агентом по правилам `auto memory` из системного промпта
> (а также вручную через `/core:memory:init`).

## Что это

Project-local memory store. Долговременная память агентов:
- хранится под `.claude/memory/` (git-tracked, портативна вместе с репо);
- каждая запись — отдельный `.md` файл с frontmatter (`name`, `description`, `metadata.type`);
- этот файл — **только индекс** (одна строка на запись), он не несёт содержимого.

Полные правила записи и чтения — см. `.claude/CLAUDE.md` → секция «Memory (OVERRIDE)»
и системный промпт `auto memory` (типы `user`/`feedback`/`project`/`reference`).

## Как заполняется

**Автоматически** — агент пишет запись когда:
- узнаёт устойчивые предпочтения пользователя (тип `user`);
- получает корректирующую обратную связь («не делай так», «делай вот так» — тип `feedback`);
- узнаёт долгоиграющие факты о проекте/ролях/датах (тип `project`);
- запоминает внешний ресурс, в который стоит ходить за состоянием (тип `reference`).

**Вручную** — slash-команды:
- `/core:memory:init` — создать первый каркас (только в новом проекте).
- `/core:memory:status` — что сейчас лежит в `.claude/memory/`.
- `/core:memory:search <query>` — найти запись по содержанию (grep + опционально qex).

## Формат строки в этом индексе

```
- [Title in ~50 chars](filename.md) — one-line hook ≤150 chars total
```

Например (когда будет наполнено):

```
- [Russian-only user-facing output](feedback_russian.md) — все ответы и docs на русском
- [User is solo dev](user_role.md) — single maintainer, no team conventions
```

## Секции

Группируем записи по типу — агент при поиске «куда вставить» смотрит в нужную секцию.

### Feedback
_(empty)_

### User
_(empty)_

### Project
_(empty)_

### Reference
_(empty)_

---

> Не путать с `~/.claude/projects/<project>/memory/` (нативный путь Claude Code) —
> мы намеренно переопределяем его на `.claude/memory/` ради портативности.
> Этот каталог per-project и не входит в seed (не шипается, остаётся с проектом).
