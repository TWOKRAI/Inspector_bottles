# Документация `multiprocess_framework`

**Корень пакета:** [../README.md](../README.md)  
**Индекс:** [../DOCUMENTATION_INDEX.md](../DOCUMENTATION_INDEX.md)  
**Глобальные ADR:** [../DECISIONS.md](../DECISIONS.md)  
**Реестр модульных ADR:** [ADR_REGISTRY.md](./ADR_REGISTRY.md)

---

## Для нового разработчика

1. [QUICK_START.md](./QUICK_START.md) — минимальный запуск и термины.
2. [EXTENSION_GUIDE.md](./EXTENSION_GUIDE.md) — новый `ProcessModule` / менеджер.
3. `modules/<name>/README.md` и `STATUS.md` — модульная глубина.

## Для архитектора

1. [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) — таблицы и матрицы.
2. [../ARCHITECTURE.md](../ARCHITECTURE.md) — единый архитектурный документ.
3. [../DECISIONS.md](../DECISIONS.md) + [ADR_REGISTRY.md](./ADR_REGISTRY.md) — решения и коды ADR.

## Для AI-агента

1. [FRAMEWORK_OVERVIEW.md](./FRAMEWORK_OVERVIEW.md) — обзор и сценарии.
2. [ROUTING_GLOSSARY.md](./ROUTING_GLOSSARY.md) — процесс vs канал, регистры.
3. [CONFIG_GUIDE.md](./CONFIG_GUIDE.md) — schema → dict → процессы.

## Для тестировщика

1. [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) — типовые сбои.
2. [../PROBLEMS.md](../PROBLEMS.md) — известные ограничения тестов.
3. `modules/<name>/tests/` — pytest по модулю.

---

## Карта документов

| Файл | Назначение |
|------|------------|
| [FRAMEWORK_OVERVIEW.md](./FRAMEWORK_OVERVIEW.md) | Полный обзор, слои, принципы |
| [CONFIG_GUIDE.md](./CONFIG_GUIDE.md) | Конфигурация (консолидация; архив: [archive/](./archive/)) |
| [DIAGRAMS.md](./DIAGRAMS.md) | Шесть mermaid-диаграмм |
| [QUICK_START.md](./QUICK_START.md) | Быстрый старт |
| [EXTENSION_GUIDE.md](./EXTENSION_GUIDE.md) | Расширение фреймворка |
| [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) | FAQ и отладка |
| [ADR_REGISTRY.md](./ADR_REGISTRY.md) | Коды модулей и миграция ADR |
| [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) | Справка |
| [ARCHITECTURE_MODULE_CATALOG.md](./ARCHITECTURE_MODULE_CATALOG.md) | Каталог модулей и прототипа |
| [ROUTING_GLOSSARY.md](./ROUTING_GLOSSARY.md) | Термины маршрутизации |
| [MODULE_README_TEMPLATE.md](./MODULE_README_TEMPLATE.md) | Шаблон README модуля |
| [FRONTEND_COMMAND_LAUNCHER_ROADMAP.md](./FRONTEND_COMMAND_LAUNCHER_ROADMAP.md) | Дорожная карта UI-команд |

---

*Обновлено: 2026-04-10 — навигация по ролям, CONFIG_GUIDE, архив legacy config docs.*
