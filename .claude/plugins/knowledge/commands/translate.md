---
description: Запустить sci-translator — перевод файла или текста с английского на русский с dynamic routing Haiku/Sonnet.
---

Переведи файл или текст с английского на русский язык.

Входные данные: $ARGUMENTS — путь к файлу или текст для перевода.

## Алгоритм

1. **Проверь аргументы**
   Если $ARGUMENTS пустой:
   > Укажи файл или текст: `/knowledge:translate <путь_к_файлу>`

2. **Определи входные данные**
   - Если $ARGUMENTS выглядит как путь к файлу (содержит `/` или `.md`) — читай файл
   - Иначе — переводи как текст inline

3. **Выбери модель по сложности (по длине И содержимому)**

   Собрать метрики (для файла):
   ```bash
   wc -w "$ARGUMENTS"              # количество слов
   grep -c '^```' "$ARGUMENTS"     # количество кодовых блоков
   head -1 "$ARGUMENTS"            # детекция frontmatter ---
   grep -cE '(pipeline|embedding|inference|frontmatter|slug|API|SDK|CLI|async|awaits?)' "$ARGUMENTS"
   ```

   **Sonnet** (`claude-sonnet-5`) — если ВЫПОЛНЕНО ЛЮБОЕ:
   - ≥ 300 слов
   - ЛИБО есть хотя бы один кодовый блок
   - ЛИБО первая строка `---` (YAML frontmatter)
   - ЛИБО > 3 технических терминов
   - ЛИБО путь в `knowledge/wiki/`, `.claude/plugins/*/agents/`, `workspace/plans/`

   **Haiku** (`claude-haiku-4-5-20251001`) — только если ВСЕ выполнены:
   - < 300 слов
   - И нет кодовых блоков
   - И нет frontmatter
   - И ≤ 3 технических терминов
   - И простой путь (knowledge/inbox/, обычная заметка)

   **При сомнении — выбирай Sonnet.** Haiku дешевле, но плохой перевод технического текста дороже переделок.

4. **Вызови sci-translator с выбранной моделью**
   - Для Haiku: `Agent(subagent_type: "sci-translator", model: "haiku", prompt: ...)`
   - Для Sonnet: `Agent(subagent_type: "sci-translator", prompt: ...)`

5. **Сохранение**
   - Файл → `{имя_без_расширения}_ru.md` рядом с оригиналом
   - Текст inline → вывести в чат

6. **Отчёт**
   ```
   ✓ Модель: {haiku/sonnet}
     Причина: {длина=XXX слов, код=Y блоков, frontmatter=да/нет, техтермины=N}
   ✓ Переведено: {источник}
   ✓ Сохранено: {путь_к_файлу_ru.md}
   ```

## Примеры

```
/knowledge:translate workspace/plans/META_PLAN.md       → Sonnet (план, всегда технический)
/knowledge:translate .claude/plugins/knowledge/agents/sci-curator.md → Sonnet (frontmatter)
/knowledge:translate knowledge/inbox/notes.md           → Haiku если <300 слов без кода
/knowledge:translate This is a short note               → Haiku (короткий inline)
```

## Особенности перевода

- **Сохраняет структуру**: заголовки, списки, таблицы, frontmatter
- **Не трогает**: кодовые блоки, URL, имена переменных, CLI-команды
- **Технические термины**: первое упоминание — оригинал + перевод в скобках
- **Не редактирует** исходный файл — только создаёт `_ru.md`
