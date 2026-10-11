# Обратные ссылки для соседних планов — готовый текст

Этот план чужие файлы не правит. Тексты ниже вносит владелец или лид после approve, каждый своим коммитом
(`docs(plans): <план> — обратная ссылка на memory-rules-delivery`). Даты и SHA в угловых скобках — заполнить при внесении.

## 1. `plans/2026-10-04_atlas/plan.md` — строка Task 2.4 (трек 2.4g) или раздел «Открытые вопросы»

```markdown
- [ ] Доставка уроков по пути — план [`memory-rules-delivery`](../2026-10-11_memory-rules-delivery/plan.md) (с 2026-10-11).
  Кто чем владеет: Atlas — парсер и словари уроков (`scripts/memory/_lessons.py`, `tags.py`, `TAGS.yaml`, `modules.yaml`);
  memory-rules-delivery — генератор `scripts/memory/rules.py` и слой `.claude/rules/memory/` (push по `paths:`).
  Берёт у Atlas: `_lessons.py`, ключи `id`/`paths` из `modules.yaml`; `scripts/atlas` не импортирует.
  Отдаёт Atlas: дату и SHA слияния генератора — <YYYY-MM-DD>, `<sha>`; K1.1 (kill №6, «повторные грабли») считает повторы
  отдельно до и после этой точки. Строка должна стоять в плане ДО слияния генератора.
  1.10c («Уроки (N)» в `card`) читает те же теги через `_lessons.py` — второго парсера нет.
  1.10d (строки `scripts/{atlas,plans_progress,validate_commit,channel_map,memory}` в `modules.yaml`): адрес доставки
  уроков `module: scripts` не меняется, меняется только `card`; после новых строк генератор даст узлы для новых id только
  у перетегированных уроков. Замечание: строка `scripts/atlas` в `modules.yaml` уже есть (`modules.yaml:847`).
  Конфликт: узел `scripts` (`paths: scripts/**`) грузится и при касании `scripts/atlas/**` — вложенные узлы грузятся оба,
  это иное правило, чем «самый длинный префикс» в `scripts/atlas/modules.py:67-79` (записано в docstring `scripts/memory/rules.py`).
  R5 (`.rules/`, 8 файлов, 24,8 КБ, устарел: «20 модулей» вместо 35; `commits.md` с `paths: "**"` противоречит ролям,
  которые коммитят): тот же механизм `paths:`, но отдельная правка ПОСЛЕ этого плана — сначала ревизия текста, потом
  перенос в `.claude/rules/`, другим коммитом и другой датой.
```

## 2. `plans/2026-10-07_tooling-py-modernization.md` — раздел о рисках или «Связанные планы»

```markdown
- Пересечение с [`memory-rules-delivery`](2026-10-11_memory-rules-delivery/plan.md): он добавляет `scripts/memory/rules.py`
  (новый код — сразу в синтаксисе 3.12, в долг 885 файлов не входит) и одну функцию в `scripts/validate.py`
  (старые аннотации не трогает). Фаза 1 этого плана идёт по слоям `multiprocess_framework → Services → Plugins →
  multiprocess_prototype`, `scripts/` не задевает — конфликта файлов нет. Если Фаза 2 тронет `scripts/validate.py` —
  после слияния 2.1 memory-rules-delivery, ребейз на его шаг 9.
```

## 3. `plans/queue/ORDER.md` — строка в §4.1 (правило «план дольше дня получает строку»)

```markdown
| [2026-10-11_memory-rules-delivery](../2026-10-11_memory-rules-delivery/plan.md) | М | DRAFT 2026-10-11; опыт, откатываемый одним коммитом; Gate 0 — проба G0, Gate 3 — замер на 10 парах | 0.1 проба G0 → 0.2 список пар |
```

Полоса М: механизм работы, не продукт; лимит полосы (§1, п. 5) — решение владельца при постановке.
