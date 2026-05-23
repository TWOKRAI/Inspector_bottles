---
description: Синхронизировать живое ТЗ (docs/direction/) с кодом — spec-writer + manager → новый план с Task X.Y
---

Режим **SYNC**: пользователь отредактировал `docs/direction/*.md` → определяем расхождения с кодом → генерируем план задач для исправления.

Входные данные: $ARGUMENTS — путь к приложению (например `apps/specs` или `projects/quick_translate`).

## Алгоритм

1. **Проверь аргументы**
   Если $ARGUMENTS пустой:
   > Укажи приложение: `/spec-sync <путь>`
   > Например: `/spec-sync apps/specs` или `/spec-sync projects/specs`

2. **Проверь наличие spec**
   - Папка `$ARGUMENTS/docs/direction/` существует?
   - Есть хотя бы один `*.md` файл?
   - Если нет → `Сначала создай spec через /spec CREATE $ARGUMENTS`

3. **Вызови spec-writer в режиме SYNC**
   ```
   Agent(subagent_type: "spec-writer", prompt: "Режим SYNC для $ARGUMENTS. Прочитай все docs/direction/*.md и сравни с кодом. Выведи СПИСОК РАСХОЖДЕНИЙ — какие элементы UI описаны в spec, но отсутствуют в коде, или наоборот. Формат: файл spec → что изменить в коде.")
   ```

4. **Обработай результат spec-writer**
   - Если расхождений нет → `✓ Spec синхронизирован с кодом, задач не требуется`
   - Если есть расхождения → передай их manager для декомпозиции

5. **Вызови manager для декомпозиции**
   ```
   Agent(subagent_type: "manager", prompt: "Пользователь отредактировал docs/direction/ для $ARGUMENTS. Расхождения:\n\n<результат spec-writer>\n\nДекомпозируй на Task X.Y и сохрани план в plans/spec-sync.md")
   ```

6. **Отчёт**
   ```
   ✓ Spec проанализирован: $ARGUMENTS/docs/direction/
   ✓ Расхождений найдено: N
   ✓ План создан: plans/spec-sync.md
   → Запусти /pipeline или /implement <task> для реализации
   ```

## Типовой флоу пользователя

```
1. Пользователь редактирует apps/specs/docs/direction/02_editor.md
   (добавляет описание новой кнопки «Экспорт в PDF»)

2. /spec-sync apps/specs
   → spec-writer видит: в spec есть кнопка, в коде нет
   → manager декомпозирует: Task 1.1 — добавить QPushButton, Task 1.2 — обработчик, Task 1.3 — PDF-экспорт

3. /implement 1.1 → /implement 1.2 → /implement 1.3
   или /pipeline целиком
```

## Когда НЕ вызывать

- Первое создание spec для приложения → `/spec CREATE <app>`
- Изменения только в коде (spec не трогали) → `/spec UPDATE <app>`
- Маленькое точечное изменение spec → проще напрямую `/plan "<описание>"` без spec-sync

## Граница с /spec

| Команда | Режим | Направление |
|---------|-------|-------------|
| `/spec CREATE <app>` | CREATE | код → spec (первичное создание) |
| `/spec UPDATE <app>` | UPDATE | код → spec (после изменений в коде) |
| `/spec-sync <app>` | SYNC | spec → код (пользователь отредактировал spec) |
