---
paths:
  - "multiprocess_framework/modules/frontend_module/**"
  - "multiprocess_prototype/registers/**"
---

# Правила GUI (PySide6)

## Виджеты
- v3 сгруппированы по доменам: `chrome/`, `sources/`, `recipes/`, `processing/`, `settings/`, `pipeline/`, `tabs_setting/`, `base/`
- Реорганизация: `docs/refactors/2026-04_widgets_reorg.md`

## Qt-паттерны (КРИТИЧНО)
- **blockSignals** перед программной правкой виджетов — иначе рекурсия сигналов
- **setFlags** с осторожностью — может вызвать рекурсию (ItemChanged → setFlags → ItemChanged)
- **EditTriggers** — отключать на деревьях/списках если не нужно inline-редактирование
- Новые табы — **полный MVP** (presenter + view Protocol)

## Dict at Boundary для GUI
- Виджеты работают **только с dict**, никогда с live SchemaBase
- Данные: dict → виджет → dict (round-trip)

## Register routing
- FieldRouting **без IPC-канала** = зависание GUI
- Всегда проверять что канал зарегистрирован перед send_message

## Tab order
- Settings первым → Recipes → функциональные табы (не Settings последним)
