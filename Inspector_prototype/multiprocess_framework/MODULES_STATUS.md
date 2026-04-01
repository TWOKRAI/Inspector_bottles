# Статус модулей — MODULES_STATUS.md

Сводка синхронизирована с `modules/{name}/STATUS.md` (2026-03-31). Детали и чеклисты — только в файлах STATUS модулей.

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
| data_schema_module | 10/11 | 9 | 8 | 8 | 9 | да |
| base_manager | 6/8 | 8 | 8 | 8 | 8 | да |
| frontend_module | 6/8 | 9 | 7 | 8 | 9 | да |
| logger_module | 4/8 | 9 | 7 | 8 | 9 | да |
| error_module | 3/8 | 10 | 7 | 9 | 9 | да |
| router_module | 4/8 | 9 | 8 | 9 | 9 | да |
| statistics_module | 4/8 | 9 | 8 | 8 | 9 | да |
| message_module | 2/8 | 8 | 6 | 8 | 8 | да |
| registers_module | 0/8 | 7 | 3 | 4 | 3 | да |

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

Глобальные этапы 0–8 в разных модулях закрыты неравномерно. Актуальная правда — **`modules/*/STATUS.md`** и **DECISIONS.md** (ADR).

---

## CRM Unification Plan — Статус фаз

| Фаза | Статус | Описание |
|------|--------|----------|
| Фаза 1 | Завершена | channel_routing_module (CRM, IChannel, ChannelRegistry, буферы) |
| Фаза 2 | Завершена | LoggerManager → CRM |
| Фаза 3 | Завершена | ErrorManager, severity routing |
| Фаза 4 | Завершена | RouterManager → CRM |
| Фаза 5 | Завершена | Документация, ADR-013..016 |

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

Полный прогон (2026-03-31): из каталога `multiprocess_framework/modules` выполнить `python -m pytest` — **1567 passed** (конфиг `pytest.ini` в том же каталоге).
