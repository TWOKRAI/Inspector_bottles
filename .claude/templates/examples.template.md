# EXAMPLES — Project-specific anti-patterns

Live document. Add entries when the agent (or you) repeatedly trips on the same kind of mistake. Captures lessons that don't belong in any single file's comment but are too project-specific for the global agent prompt.

Each entry follows a fixed format so the agent can scan and apply them.

## Format

```
## N. <Short rule name>

**Правило:** <one sentence that states the rule>

**❌ Признак нарушения:**
- <concrete signal — code shape / comment / structure>
- ...

**✅ Что делать:**
- <concrete alternative>
- ...

**Почему:** <reason, ideally with consequence>

**Где живёт:** <relevant file paths or modules>
```

## Когда добавлять запись

- Заметил что агент **дважды или больше** сделал одну и ту же ошибку
- Заметил что **сам** недавно сделал ошибку которую система не поймала
- Возник архитектурный паттерн который не очевиден из кода
- Не для тривиальных стилевых правил (это покрывает ruff/pyright)

## Когда удалять запись

- Правило теперь enforced автоматически (lint, тест, type check)
- Кодбаза изменилась так что нарушение больше невозможно
- Запись устарела (deprecated module, удалённая зона)

## Связи

- Ссылка из корневого `CLAUDE.md`: `Project-specific anti-patterns → [EXAMPLES.md](EXAMPLES.md)`
- Дополняет, но не дублирует комментарии в коде

---

<!-- Удали этот placeholder и добавь реальные правила по мере накопления.
     Минимальный smoke-пример ниже — для иллюстрации формата. -->

## 1. (placeholder) Не дублировать в скрипте то, что уже есть в Makefile

**Правило:** разовые команды для запуска тестов / линтера / сборки — через `make <target>`, не через свои bash-скрипты.

**❌ Признак нарушения:**
```bash
# scripts/run_tests.sh
uv run pytest --cov=mypackage --cov-report=term-missing
```

**✅ Что делать:**
```bash
# Use existing target
make test
```

**Почему:** дублирующие скрипты разъезжаются с Makefile, забываются при обновлении флагов pytest. Единая точка входа — `Makefile`.

**Где живёт:** `Makefile`, `scripts/`.
