---
paths:
  - "multiprocess_prototype/**"
---

# Правила прототипа

## Активный прототип
- **Единственный:** `multiprocess_prototype/`
- Точка входа: `run.py`
- Регистры приложения: `registers/`
- Старые v1/v2 удалены (см. git log)

## CRITICAL: backup
- `multiprocess_prototype_backup/` — снэпшот предыдущей структуры
- Агентам **ЗАПРЕЩЕНО** вносить изменения, grep/sentrux/qex его игнорируют

## Composition root
- Prototype — верхний слой, может импортировать всё (framework, Services, Plugins)
- Сюда вносить **app-specific** изменения (не в framework)

## Конструктор
- Всё модульное: pluggable, testable, composable блоки
- Blueprint фреймворка: `multiprocess_framework/docs/CONSTRUCTOR_BLUEPRINT.md`
