# message_contracts

AST-дамп классов, наследующих `SchemaBase` / `Message` / `BaseModel` (настраивается).

## Что находит

- Класс, у которого среди базовых есть имя из `detect.base_classes` (сравнение по последнему сегменту — `pkg.SchemaBase` ⇒ `SchemaBase`).
- Поля = `AnnAssign` (типизированные присваивания в теле класса). Тип и default извлекаются через `ast.unparse`.
- Игнорирует классы по префиксу имени (`detect.ignore_name_prefixes`, например `_Test`/`Test` для тестовых фикстур).

## Запуск

```bash
python scripts/message_contracts/message_contracts.py
python scripts/message_contracts/message_contracts.py --group-by base --format json
python scripts/message_contracts/message_contracts.py --root multiprocess_framework/modules/message_module
python scripts/message_contracts/message_contracts.py --no-fields --limit 20
```

## Колонки table

- `class` — имя класса
- `base` — найденный базовый (если совпало несколько — берётся первый по алфавиту)
- `module` — `modules/X`, `Services/Y`, `Plugins/Y`, `multiprocess_prototype`
- `fields` — число полей
- `preview` — `name:type` через запятую, обрезано до `max_fields_preview`

CSV-вывод разворачивает поля построчно (одна строка = одно поле) — удобно для diff.

## Когда полезно

- **Аудит Dict-at-Boundary**: какие схемы летят между процессами, что в них.
- **Поиск дублирования полей** между `Message` и `CommandMessageSchema` / `LogMessageSchema`.
- **Диф контрактов** между ветками: `--format json > before.json` → переключиться → сравнить.
- **Reverse-doc** для модулей без актуальной документации.

## Ограничения

- Только статический AST: `from x import SchemaBase as SB` → не сработает (редкий кейс).
- Не разворачивает наследование транзитивно (если `B(A)` и `A(SchemaBase)` — найдётся только `B`).
  Если нужно — расширь `detect.base_classes` явно.
- Дефолты и типы — текстовые, как написано в исходнике (не вычисляются).
