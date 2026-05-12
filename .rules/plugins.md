---
paths:
  - "Plugins/**"
---

# Правила Plugins

## Что такое Plugins
- 19 vocabulary-плагинов, reuse между приложениями (Phase 5 carve-out)
- Маленькие processing/bridges — в отличие от Services (крупные SDK)

## Изоляция (ADR-120)
- Плагин знает **только** `PluginContext`
- **ЗАПРЕЩЕНО** импортировать `multiprocess_prototype.*`
- **ЗАПРЕЩЕНО** читать SHM напрямую — использовать framework middleware

## Слой импортов
```
Plugins может импортировать → multiprocess_framework
Plugins НЕ может импортировать → Services, multiprocess_prototype
```
