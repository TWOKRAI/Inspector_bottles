---
description: Дамп Message / SchemaBase / BaseModel классов с полями (AST)
---

Запусти AST-дамп контрактов:

```bash
python scripts/message_contracts/message_contracts.py
```

Что находит:
- Классы, наследующие имена из `detect.base_classes` (по умолчанию `SchemaBase`, `BaseModel`, `Message`).
- Поля = `AnnAssign` (типизированные присваивания в теле класса).
- Игнорирует тестовые классы по `detect.ignore_name_prefixes`.

Конфиг: [scripts/message_contracts/message_contracts.toml](../../scripts/message_contracts/message_contracts.toml). Детали в [README.md](../../scripts/message_contracts/README.md).

Полезные варианты:
- `python scripts/message_contracts/message_contracts.py --group-by base` — сводка по базовым классам.
- `python scripts/message_contracts/message_contracts.py --format json` — для парсинга/диффа.
- `python scripts/message_contracts/message_contracts.py --format csv` — поля построчно (один файл-таблица для diff).

**Когда использовать:**
- Аудит Dict-at-Boundary: какие схемы летают между процессами, какие поля.
- Поиск дублирования между `Message`, `CommandMessageSchema`, `LogMessageSchema`.
- Дифф контрактов между ветками.
- Reverse-doc для модулей без актуальной документации.

$ARGUMENTS
