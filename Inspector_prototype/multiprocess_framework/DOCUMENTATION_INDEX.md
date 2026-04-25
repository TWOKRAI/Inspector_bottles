# Multiprocess Framework — Индекс документации

**Обновлено:** 2026-04-25 — после миграции на каноничные импорты и наведения порядка.

---

## Корневые документы

| Документ | Назначение |
|----------|------------|
| [`README.md`](./README.md) | Что это, как запустить, как тестировать |
| [`SPEC.md`](./SPEC.md) | **Главное ТЗ** — спецификация фреймворка |
| [`MODULES_STATUS.md`](./MODULES_STATUS.md) | Таблица 19 модулей: размер, статус, тесты |
| [`PROBLEMS.md`](./PROBLEMS.md) | Известные ограничения и failing-тесты |
| [`DECISIONS.md`](./DECISIONS.md) | Глобальные ADR (`ADR-NNN`) |
| [`STRUCTURE.md`](./STRUCTURE.md) | Дерево пакета |

## `docs/` — справочники

| Документ | Назначение |
|----------|------------|
| [`docs/MODULES_OVERVIEW.md`](./docs/MODULES_OVERVIEW.md) | **Навигатор**: какой модуль за что отвечает |
| [`docs/MODULE_CONTRACTS.md`](./docs/MODULE_CONTRACTS.md) | Контракт каждого из 19 модулей |
| [`docs/INTERACTION_FLOWS.md`](./docs/INTERACTION_FLOWS.md) | Цепочки взаимодействия |
| [`docs/DESIGN_RULES.md`](./docs/DESIGN_RULES.md) | Императивные правила |
| [`docs/GLOSSARY.md`](./docs/GLOSSARY.md) | Термины и сокращения |
| [`docs/ROUTING_GLOSSARY.md`](./docs/ROUTING_GLOSSARY.md) | Канал vs имя процесса |
| [`docs/DIAGRAMS.md`](./docs/DIAGRAMS.md) | Сводные mermaid-диаграммы |
| [`docs/QUICK_START.md`](./docs/QUICK_START.md) | Минимальный запуск |
| [`docs/TROUBLESHOOTING.md`](./docs/TROUBLESHOOTING.md) | Типичные проблемы |
| [`docs/EXTENSION_GUIDE.md`](./docs/EXTENSION_GUIDE.md) | Расширение: новый процесс / менеджер |
| [`docs/CONFIG_GUIDE.md`](./docs/CONFIG_GUIDE.md) | Конфиги: schema → dict → ConfigStore |
| [`docs/ADR_REGISTRY.md`](./docs/ADR_REGISTRY.md) | Реестр кодов модульных ADR |
| [`docs/MODULE_README_TEMPLATE.md`](./docs/MODULE_README_TEMPLATE.md) | Шаблон README нового модуля |
| [`docs/archive/`](./docs/archive/) | Устаревшие / объединённые документы |

## Документация по модулям

В каждой папке `modules/<name>/`:
- `README.md` — назначение и API
- `STATUS.md` — этап и ограничения
- `DECISIONS.md` — локальные ADR
- `interfaces.py` — публичный контракт
- `tests/` — pytest

Список модулей и краткая роль — [`docs/MODULES_OVERVIEW.md`](./docs/MODULES_OVERVIEW.md).

---

## Быстрая навигация по задачам

| Задача | Куда смотреть |
|--------|----------------|
| Понять идею фреймворка | [`SPEC.md`](./SPEC.md) §1–4 |
| Найти подходящий модуль для своей задачи | [`docs/MODULES_OVERVIEW.md`](./docs/MODULES_OVERVIEW.md) |
| Посмотреть контракт модуля | [`docs/MODULE_CONTRACTS.md`](./docs/MODULE_CONTRACTS.md) или `modules/<X>/interfaces.py` |
| Цепочка вызовов сценария | [`docs/INTERACTION_FLOWS.md`](./docs/INTERACTION_FLOWS.md) |
| Что обязано / что запрещено | [`docs/DESIGN_RULES.md`](./docs/DESIGN_RULES.md) |
| Сообщения, Dict at Boundary | [`SPEC.md`](./SPEC.md) §6 + [`modules/message_module/README.md`](./modules/message_module/README.md) |
| Маршрутизация (channel/target/Field) | [`docs/ROUTING_GLOSSARY.md`](./docs/ROUTING_GLOSSARY.md) |
| Запуск и graceful shutdown | [`docs/INTERACTION_FLOWS.md`](./docs/INTERACTION_FLOWS.md) §1 и §4 |
| Создать новый модуль | [`docs/EXTENSION_GUIDE.md`](./docs/EXTENSION_GUIDE.md) + [`docs/MODULE_README_TEMPLATE.md`](./docs/MODULE_README_TEMPLATE.md) |
| Запуск тестов | `cd Inspector_prototype && python scripts/run_framework_tests.py` |
| Известные проблемы | [`PROBLEMS.md`](./PROBLEMS.md) |
