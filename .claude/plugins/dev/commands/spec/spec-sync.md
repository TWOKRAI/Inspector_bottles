---
description: Sync the living spec (docs/direction/) with the code — spec-writer + manager → a new plan with Task X.Y
---

Режим **SYNC**: пользователь отредактировал `docs/direction/*.md` → определяем расхождения с кодом → генерируем план задач для исправления.

Входные данные: $ARGUMENTS — путь к приложению (например `apps/specs` или `projects/quick_translate`).

## Алгоритм

1. **Проверь аргументы**
   Если $ARGUMENTS пустой:
   > Укажи приложение: `/dev:spec:spec-sync <путь>`
   > Например: `/dev:spec:spec-sync apps/specs` или `/dev:spec:spec-sync projects/specs`

2. **Проверь наличие spec**
   - Папка `$ARGUMENTS/docs/direction/` существует?
   - Есть хотя бы один `*.md` файл?
   - Если нет → `Сначала создай spec через /dev:spec:spec CREATE $ARGUMENTS`

3. **Вызови spec-writer в режиме SYNC**
   ```
   Agent(subagent_type: "spec-writer", prompt: "Режим SYNC для $ARGUMENTS. Прочитай все docs/direction/*.md и сравни с кодом. Выведи СПИСОК РАСХОЖДЕНИЙ — какие элементы UI описаны в spec, но отсутствуют в коде, или наоборот. Формат: файл spec → что изменить в коде.")
   ```

4. **Обработай результат spec-writer**
   - Если расхождений нет → `✓ Spec синхронизирован с кодом, задач не требуется`
   - Если есть расхождения → передай их manager для декомпозиции

5. **Вызови manager для декомпозиции**
   ```
   Agent(subagent_type: "manager", prompt: "Пользователь отредактировал docs/direction/ для $ARGUMENTS. Расхождения:\n\n<результат spec-writer>\n\nДекомпозируй на Task X.Y и сохрани план в plans/YYYY-MM-DD_spec-sync.md, где YYYY-MM-DD — сегодняшняя дата ISO создания плана (slug-конвенция как в /dev:plan)")
   ```

6. **Отчёт**
   ```
   ✓ Spec проанализирован: $ARGUMENTS/docs/direction/
   ✓ Расхождений найдено: N
   ✓ План создан: plans/YYYY-MM-DD_spec-sync.md
   → Запусти /dev:pipeline или /dev:implement <task> для реализации
   ```

## Типовой флоу пользователя

```
1. Пользователь редактирует apps/specs/docs/direction/02_editor.md
   (добавляет описание новой кнопки «Экспорт в PDF»)

2. /dev:spec:spec-sync apps/specs
   → spec-writer видит: в spec есть кнопка, в коде нет
   → manager декомпозирует: Task 1.1 — добавить QPushButton, Task 1.2 — обработчик, Task 1.3 — PDF-экспорт

3. /dev:implement 1.1 → /dev:implement 1.2 → /dev:implement 1.3
   или /dev:pipeline целиком
```

## Когда НЕ вызывать

- Первое создание spec для приложения → `/dev:spec:spec CREATE <app>`
- Изменения только в коде (spec не трогали) → `/dev:spec:spec UPDATE <app>`
- Маленькое точечное изменение spec → проще напрямую `/dev:plan "<описание>"` без spec-sync

## Граница с /dev:spec:spec

| Команда | Режим | Направление |
|---------|-------|-------------|
| `/dev:spec:spec CREATE <app>` | CREATE | код → spec (первичное создание) |
| `/dev:spec:spec UPDATE <app>` | UPDATE | код → spec (после изменений в коде) |
| `/dev:spec:spec-sync <app>` | SYNC | spec → код (пользователь отредактировал spec) |
