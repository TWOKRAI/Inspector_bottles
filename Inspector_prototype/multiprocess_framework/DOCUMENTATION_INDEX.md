# Multiprocess Framework — индекс документации

**Корень:** [README.md](./README.md) · [DECISIONS.md](./DECISIONS.md) · [MODULES_STATUS.md](./MODULES_STATUS.md) · [PROBLEMS.md](./PROBLEMS.md)  
**Папка docs:** [docs/README.md](./docs/README.md)

---

## Главные документы

| Документ | Для чего |
|----------|----------|
| [docs/FRAMEWORK_OVERVIEW.md](./docs/FRAMEWORK_OVERVIEW.md) | Обзор архитектуры, модули, принципы, сценарии |
| [docs/CONFIG_SCHEMA_DATA_FLOW.md](./docs/CONFIG_SCHEMA_DATA_FLOW.md) | Цепочка: SchemaBase, dict, Config, process_manager / process_module |
| [docs/CONFIG_SCHEMA_REGISTERS.md](./docs/CONFIG_SCHEMA_REGISTERS.md) | data_schema ↔ config_module ↔ registers_module; `model_dump` / `model_validate` (ADR-112) |
| [docs/CONFIG_PATHS.md](./docs/CONFIG_PATHS.md) | Слой schema→dict, ветки доставки, фасад чтения конфига в процессе |
| [docs/ARCHITECTURE_REFERENCE.md](./docs/ARCHITECTURE_REFERENCE.md) | Таблицы, диаграммы, матрицы зависимостей |
| [docs/ROUTING_GLOSSARY.md](./docs/ROUTING_GLOSSARY.md) | Термины маршрутизации и регистров |
| [docs/ARCHITECTURE_MODULE_CATALOG.md](./docs/ARCHITECTURE_MODULE_CATALOG.md) | Каталог модулей и пакетов прототипа |
| [docs/FRONTEND_COMMAND_LAUNCHER_ROADMAP.md](./docs/FRONTEND_COMMAND_LAUNCHER_ROADMAP.md) | Дорожная карта команд UI / лаунчера |
| [DECISIONS.md](./DECISIONS.md) | ADR — принятые решения; **оглавление и сортировка по номеру**, раздел «Устарело» |
| [docs/MODULE_README_TEMPLATE.md](./docs/MODULE_README_TEMPLATE.md) | Шаблон README нового модуля |

---

## Быстрая навигация

| Задача | Куда смотреть |
|--------|----------------|
| Понять систему целиком | [FRAMEWORK_OVERVIEW.md](./docs/FRAMEWORK_OVERVIEW.md) |
| Цепочка схемы, dict, config, процессы | [CONFIG_SCHEMA_DATA_FLOW.md](./docs/CONFIG_SCHEMA_DATA_FLOW.md) |
| Одна модель schema→dict и куда уходит dict | [CONFIG_PATHS.md](./docs/CONFIG_PATHS.md) |
| Найти таблицу / схему | [ARCHITECTURE_REFERENCE.md](./docs/ARCHITECTURE_REFERENCE.md) |
| Понять «почему так» | [DECISIONS.md](./DECISIONS.md) |
| Сообщения, Dict at Boundary | Overview + ADR-008 |
| ChannelRoutingManager | Overview + ADR-013 |
| Остановка процессов | Overview (Graceful Shutdown) + `process_manager_module` |
| Новый модуль | Шаблон + `base_manager` README + тесты |
| Запуск unit-тестов фреймворка | [README.md — Testing](./README.md#testing); из `Inspector_prototype`: `python scripts/run_framework_tests.py` |

---

## Документация по модулям

В каждом пакете под [modules/](./modules/):

- `README.md` — назначение и API
- `STATUS.md` — этап и известные ограничения
- `interfaces.py` — публичный контракт
- `tests/` — pytest

Слои (16 модулей): Foundation (`base_manager`, `data_schema_module`, `message_module`), Infrastructure (`logger_module`, `error_module`, `config_module`, `console_module`, `shared_resources_module`, `registers_module`), Communication (`dispatch_module`, `router_module`, `command_module`), Process (`worker_module`, `process_module`), Orchestration (`process_manager_module`), Frontend (`frontend_module`). Дополнительно в дереве: `channel_routing_module`, `statistics_module` — см. [ARCHITECTURE_MODULE_CATALOG.md](./docs/ARCHITECTURE_MODULE_CATALOG.md).

Углублённые гайды внутри модулей (например `data_schema_module/docs/`, `config_module/docs/`) остаются частью актуального набора.

---

## Отладка и проблемы

- [PROBLEMS.md](./PROBLEMS.md) — известные ограничения unit-тестов
- [tests/integration/TEST_ISSUES.md](./tests/integration/TEST_ISSUES.md) — интеграционные тесты

---

*Обновлено: 2026-03-30 — добавлены [CONFIG_SCHEMA_DATA_FLOW.md](./docs/CONFIG_SCHEMA_DATA_FLOW.md) и [CONFIG_PATHS.md](./docs/CONFIG_PATHS.md) (ADR-102). Ранее (2026-03-24): сжатие документации; единая канва — Overview + Reference + DECISIONS.*
