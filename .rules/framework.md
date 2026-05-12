---
paths:
  - "multiprocess_framework/**"
---

# Правила фреймворка

## Структура модуля
- Каждый модуль: `interfaces.py` (зависимости) + `README.md` + `STATUS.md` + `tests/`
- 20 модулей в `modules/`. Обзор: `docs/MODULES_OVERVIEW.md`, контракты: `docs/MODULE_CONTRACTS.md`
- Конструктор-blueprint: `docs/CONSTRUCTOR_BLUEPRINT.md`

## ADR-решения
- Локальные → `modules/X/DECISIONS.md`
- Глобальные → `multiprocess_framework/DECISIONS.md`
- **Auto-sync:** после правок DECISIONS.md → `python -m scripts.sync`
- CI ловит дрифт через `python scripts/validate.py`

## IPC и роутинг
- **НЕ путать:** имя процесса (`targets`, `send_message`) ≠ канал Router (`FieldRouting.channel`, `msg["channel"]`)
- Справочник: `ROUTING_GLOSSARY.md`
- `Message` / `MessageAdapter` → `RouterManager` → `shared_resources_module` (pickle-safe)

## Dict at Boundary
- Между процессами только `dict` (`to_dict`/`from_dict`)
- Pydantic v2 внутри процесса, dict на конфиг-границе

## Логирование
- Через `ObservableMixin`, пути из env (`MULTIPROCESS_LOG_DIR`)
- Ошибки логировать, не подавлять

## Слои импортов
```
multiprocess_framework → Services → Plugins → multiprocess_prototype
```
Обратные запрещены. Enforced через `.sentrux/rules.toml`.
