# Multiprocess Framework — индекс документации

**Корень:** [README.md](./README.md) · [DECISIONS.md](./DECISIONS.md) · [MODULES_STATUS.md](./MODULES_STATUS.md) · [PROBLEMS.md](./PROBLEMS.md)  
**Папка docs:** [docs/README.md](./docs/README.md)

---

## Главные документы

| Документ | Для чего |
|----------|----------|
| [docs/QUICK_START.md](./docs/QUICK_START.md) | Минимальный запуск, термины, ссылки дальше |
| [docs/FRAMEWORK_OVERVIEW.md](./docs/FRAMEWORK_OVERVIEW.md) | Обзор архитектуры, модули, принципы, сценарии |
| [docs/CONFIG_GUIDE.md](./docs/CONFIG_GUIDE.md) | Конфиг: три слоя, schema→dict, ветки доставки (замена трёх legacy docs → [archive](./docs/archive/)) |
| [docs/DIAGRAMS.md](./docs/DIAGRAMS.md) | Шесть mermaid-диаграмм (слои, IPC, lifecycle, config, граф, аналогия) |
| [docs/EXTENSION_GUIDE.md](./docs/EXTENSION_GUIDE.md) | Новый ProcessModule / менеджер, чеклисты |
| [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md) | FAQ, отладка, тесты |
| [docs/ADR_REGISTRY.md](./docs/ADR_REGISTRY.md) | Коды модулей ADR-{CODE}-NNN, маппинг старых номеров |
| [docs/ARCHITECTURE_REFERENCE.md](./docs/ARCHITECTURE_REFERENCE.md) | Таблицы, диаграммы, матрицы зависимостей |
| [docs/ROUTING_GLOSSARY.md](./docs/ROUTING_GLOSSARY.md) | Термины маршрутизации и регистров |
| [docs/ARCHITECTURE_MODULE_CATALOG.md](./docs/ARCHITECTURE_MODULE_CATALOG.md) | Каталог модулей и пакетов прототипа |
| [docs/FRONTEND_COMMAND_LAUNCHER_ROADMAP.md](./docs/FRONTEND_COMMAND_LAUNCHER_ROADMAP.md) | Дорожная карта команд UI / лаунчера |
| [DECISIONS.md](./DECISIONS.md) | Глобальные ADR (ADR-NNN); модульные — в `modules/*/DECISIONS.md` + реестр |
| [docs/MODULE_README_TEMPLATE.md](./docs/MODULE_README_TEMPLATE.md) | Шаблон README нового модуля |

---

## Быстрая навигация

| Задача | Куда смотреть |
|--------|----------------|
| Понять систему целиком | [FRAMEWORK_OVERVIEW.md](./docs/FRAMEWORK_OVERVIEW.md) |
| Цепочка схемы, dict, config, процессы | [CONFIG_GUIDE.md](./docs/CONFIG_GUIDE.md) |
| Диаграммы mermaid | [DIAGRAMS.md](./docs/DIAGRAMS.md) |
| Найти таблицу / схему | [ARCHITECTURE_REFERENCE.md](./docs/ARCHITECTURE_REFERENCE.md) |
| Понять «почему так» | [DECISIONS.md](./DECISIONS.md) |
| Сообщения, Dict at Boundary | Overview + ADR-008 |
| ChannelRoutingManager | Overview + глобальный ADR-013 / модульный ADR-CRM-001 |
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

Пакеты под `modules/`: **19** — см. [ARCHITECTURE_MODULE_CATALOG.md](./docs/ARCHITECTURE_MODULE_CATALOG.md), [DIAGRAMS.md](./docs/DIAGRAMS.md).

Углублённые гайды внутри модулей (например `data_schema_module/docs/`, `config_module/docs/`) остаются частью актуального набора.

---

## Отладка и проблемы

- [PROBLEMS.md](./PROBLEMS.md) — известные ограничения unit-тестов
- [tests/integration/TEST_ISSUES.md](./tests/integration/TEST_ISSUES.md) — интеграционные тесты

---

*Обновлено: 2026-04-10 — CONFIG_GUIDE, DIAGRAMS, ADR_REGISTRY, QUICK_START; legacy config docs → [docs/archive](./docs/archive/).*
