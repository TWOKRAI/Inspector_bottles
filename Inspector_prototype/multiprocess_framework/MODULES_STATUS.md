# Статус модулей — MODULES_STATUS.md

Сводка синхронизирована с `modules/{name}/STATUS.md` (**2026-04-10**). Детали и чеклисты — только в файлах STATUS модулей.

| Модуль | Этап | Код | Тесты | Docs | Связанность | Работает |
|--------|------|-----|-------|------|-------------|----------|
| **channel_routing_module** | **8/8** | **9** | **8** | **10** | **10** | да |
| **sql_module** | **8/8** | **8** | **8** | **8** | **8** | да |
| **config_module** | **8/8** | **9** | **9** | **8** | **8** | да |
| **console_module** | **8/8** | **8** | **7** | **9** | **8** | да |
| **dispatch_module** | **8/8** | **9** | **9** | **9** | **9** | да |
| **command_module** | **8/8** | **9** | **9** | **9** | **8** | да |
| **shared_resources_module** | **8/8** | **9** | **8** | **9** | **8** | да |
| **process_manager_module** | **8/8** | **9** | **8** | **9** | **5** | да |
| **worker_module** | **8/8** | **9** | **10** | **8** | **9** | да |
| **process_module** | готов (см. STATUS) | **8** | **8** | **9** | — | да |
| **data_schema_module** | **11/11** | **9** | **8** | **8** | **9** | да |
| **base_manager** | **8/8** (рефакторинг завершён) | **8** | **8** | **8** | **8** | да |
| **frontend_module** | **6/8** | **9** | **7** | **8** | **9** | да |
| **logger_module** | **5/8** | **9** | **7** | **9** | **9** | да |
| **error_module** | **5/8** | **10** | **9** | **10** | **9** | да |
| **router_module** | **5/8** | **8** | **8** | **8** | **9** | да |
| **statistics_module** | **5/8** | **9** | **9** | **10** | **9** | да |
| **message_module** | **2/8** | **9** | **9** | **9** | **9** | да |
| **registers_module** | **8/8** | **9** | **9** | **9** | **8** | да |

Оценки «Код» / «Тесты» / … — из столбцов соответствующих `STATUS.md` (или среднее, где в STATUS несколько метрик).

---

## Модули с завершённым чеклистом 8/8 (ориентир production)

- **channel_routing_module** — CRM, каналы, буферы
- **config_module** — runtime-конфиги, подписки
- **console_module** — консольный вывод
- **sql_module** — SQLManager, адаптеры
- **dispatch_module** / **command_module** — диспетчеризация и команды
- **shared_resources_module** — очереди, ConfigStore, PSR
- **process_manager_module** — оркестратор
- **worker_module** — потоки и воркеры

---

## Прогресс по этапам (общий roadmap)

Глобальные этапы 0–8 в разных модулях закрыты неравномерно. Актуальная правда — **`modules/*/STATUS.md`** и **DECISIONS** (глобальный + модульные ADR, см. [docs/ADR_REGISTRY.md](./docs/ADR_REGISTRY.md)).

---

## CRM Unification Plan — Статус фаз

| Фаза | Статус | Описание |
|------|--------|----------|
| Фаза 1 | Завершена | channel_routing_module (CRM, IChannel, ChannelRegistry, буферы) |
| Фаза 2 | Завершена | LoggerManager → CRM |
| Фаза 3 | Завершена | ErrorManager, severity routing |
| Фаза 4 | Завершена | RouterManager → CRM |
| Фаза 5 | Завершена | Документация; модульные ADR: **ADR-CRM-001…004**, **ADR-CRM-005** (ex ADR-108) |

---

## Тесты (ориентир; точные числа — pytest по модулю)

| Область | Примечание |
|---------|------------|
| channel_routing_module | 58+ тестов |
| logger_module / error_module / router_module | десятки тестов каждый |
| config_module | 49 тестов |
| dispatch_module | 56 тестов |
| command_module | 34 теста |
| worker_module | 49 тестов |
| shared_resources_module | 50+ тестов |

Полный прогон: из каталога `multiprocess_framework/modules` выполнить `python -m pytest` — ориентир **1567+ passed** (конфиг `pytest.ini` в том же каталоге).
