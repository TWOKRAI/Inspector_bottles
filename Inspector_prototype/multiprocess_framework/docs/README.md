# `multiprocess_framework/docs/`

Сборник справочников. Главный документ — [`../SPEC.md`](../SPEC.md).

---

## Для нового разработчика / агента — порядок чтения

1. [`../SPEC.md`](../SPEC.md) — что это, инварианты, слои, контракты.
2. [`MODULES_OVERVIEW.md`](MODULES_OVERVIEW.md) — какой модуль за что отвечает.
3. [`../modules/<X>/README.md`](../modules/) — детали модуля под задачу.
4. [`DESIGN_RULES.md`](DESIGN_RULES.md) — что обязано / что запрещено.

---

## Карта документов

### Спецификация

| Файл | Назначение |
|------|------------|
| [`MODULES_OVERVIEW.md`](MODULES_OVERVIEW.md) | **Навигатор по 19 модулям** — точка входа |
| [`MODULE_CONTRACTS.md`](MODULE_CONTRACTS.md) | Контракт каждого модуля (API + инварианты) |
| [`INTERACTION_FLOWS.md`](INTERACTION_FLOWS.md) | Цепочки вызовов (запуск, send, shutdown, FieldRouting…) |
| [`DESIGN_RULES.md`](DESIGN_RULES.md) | Императивные правила |
| [`GLOSSARY.md`](GLOSSARY.md) | Термины и сокращения |
| [`ROUTING_GLOSSARY.md`](ROUTING_GLOSSARY.md) | Подробно: канал ≠ имя процесса |
| [`DIAGRAMS.md`](DIAGRAMS.md) | Сводные mermaid-диаграммы |

### Эксплуатация

| Файл | Назначение |
|------|------------|
| [`QUICK_START.md`](QUICK_START.md) | Минимальный запуск |
| [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) | Типичные проблемы |
| [`EXTENSION_GUIDE.md`](EXTENSION_GUIDE.md) | Новый `ProcessModule` или менеджер |
| [`MODULE_README_TEMPLATE.md`](MODULE_README_TEMPLATE.md) | Шаблон `README.md` для нового модуля |
| [`CONFIG_GUIDE.md`](CONFIG_GUIDE.md) | Schema → dict → ConfigStore |

### ADR

| Файл | Назначение |
|------|------------|
| [`../DECISIONS.md`](../DECISIONS.md) | Глобальные ADR (`ADR-NNN`) |
| [`ADR_REGISTRY.md`](ADR_REGISTRY.md) | Реестр кодов модульных ADR |
| `../modules/<X>/DECISIONS.md` | Локальные ADR модуля |

### Архив

[`archive/`](archive/) — устаревшие документы, заменённые новой структурой:
- `ARCHITECTURE_old.md`, `FRAMEWORK_OVERVIEW.md`, `ARCHITECTURE_REFERENCE.md`, `ARCHITECTURE_MODULE_CATALOG.md` — заменены на корневой `SPEC.md` + `MODULES_OVERVIEW.md` + `MODULE_CONTRACTS.md`.
- `CONFIG_PATHS.md`, `CONFIG_SCHEMA_DATA_FLOW.md`, `CONFIG_SCHEMA_REGISTERS.md`, `CONFIG_UNIFICATION_PLAN.md` — объединены в `CONFIG_GUIDE.md`.
- `Deepseek.md` — экспериментальные заметки.

Дорожная карта frontend-команд перемещена в [`../modules/frontend_module/ROADMAP.md`](../modules/frontend_module/ROADMAP.md).
