---
paths:
  - "Services/**"
---

# Правила Services

## Что такое Services
- Крупные SDK/backend-интеграции, вынесенные из framework (Phase 4 carve-out)
- Пример: `sql_module` → `Services/sql`
- Статус сервисов: `Services/STATUS.md`

## Слой импортов
```
Services может импортировать → multiprocess_framework
Services НЕ может импортировать → Plugins, multiprocess_prototype
```

## Отличие от Plugins
- **Services** = большие SDK/backend (SQL, Hikvision, etc.)
- **Plugins** = маленькие processing/bridges (19 шт., vocabulary)
- Plugins знают только `PluginContext`, не импортируют prototype — см. ADR-120
