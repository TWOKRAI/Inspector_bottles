# `multiprocess_framework/docs/`

Сборник справочников. Главный документ — [`../SPEC.md`](../SPEC.md).

---

## Для нового разработчика / агента — порядок чтения

1. [`../SPEC.md`](../SPEC.md) — что это, инварианты, слои, контракты.
2. [`MODULES_OVERVIEW.md`](MODULES_OVERVIEW.md) — какой модуль за что отвечает.
3. [`../modules/<X>/README.md`](../modules/) — детали модуля под задачу.
4. [`DESIGN_RULES.md`](DESIGN_RULES.md) — что обязано / что запрещено.
5. **Наблюдаемость** — [`OBSERVABILITY_MAP.md`](OBSERVABILITY_MAP.md) (карта плоскостей) и каталог
   [`observability/`](observability/): чем писать ([`CONNECTORS.md`](observability/CONNECTORS.md)),
   куда попадает ([`SINKS_MAP.md`](observability/SINKS_MAP.md)), чем управлять
   ([`CONTROL_PANEL.md`](observability/CONTROL_PANEL.md)), как подключить свой модуль
   ([`NEW_MODULE_RECIPE.md`](observability/NEW_MODULE_RECIPE.md)). Логи, ошибки, статистика и
   документы — четыре плоскости одного разъёма; кто пишет мимо них, пишет в никуда.

---

## Карта документов

### Спецификация

| Файл | Назначение |
|------|------------|
| [`MODULES_OVERVIEW.md`](MODULES_OVERVIEW.md) | **Навигатор по 27 модулям** `modules/` — точка входа |
| [`MODULE_CONTRACTS.md`](MODULE_CONTRACTS.md) | Контракт каждого модуля (API + инварианты) |
| [`MODULE_TIERS.md`](MODULE_TIERS.md) | Ярусы core / optional / frozen (сверяется контракт-тестом) |
| [`OBSERVABILITY_MAP.md`](OBSERVABILITY_MAP.md) + [`observability/`](observability/) | Наблюдаемость: плоскости, разъёмы, приёмники, пульт, рецепт подключения |
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
- `REFACTOR_PLAN_T1.1_COMPOSITION.md` — план **выполнен** (проверено по коду 2026-08-10, E3); лежит здесь как запись о причинах, а не как задача.

Дорожная карта frontend-команд перемещена в [`../modules/frontend_module/ROADMAP.md`](../modules/frontend_module/ROADMAP.md).
