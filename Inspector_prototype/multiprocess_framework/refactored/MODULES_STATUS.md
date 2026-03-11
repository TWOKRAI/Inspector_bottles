# Статус модулей — MODULES_STATUS.md

Обновляется после каждого этапа. Детали в `modules/{name}/STATUS.md`.

| Модуль | Этап | Код | Тесты | Docs | Связанность | Работает |
|--------|------|-----|-------|------|-------------|----------|
| base_manager | 0/8 | 7 | 6 | 4 | 5 | да |
| data_schema_module | 0/8 | 7 | 8 | 6 | 3 | да |
| message_module | 0/8 | 5 | 3 | 3 | 2 | ? |
| logger_module | 0/8 | 6 | 4 | 5 | 4 | да |
| error_module | 0/8 | 9 | 7 | 8 | 8 | да |
| config_module | 0/8 | 5 | 3 | 3 | 4 | ? |
| console_module | 0/8 | 5 | 3 | 4 | 4 | ? |
| shared_resources_module | 0/8 | 6 | 3 | 4 | 4 | да |
| dispatch_module | 0/8 | 5 | 3 | 4 | 3 | ? |
| router_module | 0/8 | 6 | 5 | 5 | 5 | да |
| command_module | 0/8 | 5 | 3 | 5 | 4 | ? |
| worker_module | - | - | - | - | - | - |
| registers_module | 0/8 | 7 | 3 | 3 | 3 | да |
| process_module | 0/8 | 5 | 3 | 4 | 2 | нет |
| process_manager_module | 0/8 | 6 | 5 | 5 | 3 | нет |

> `worker_module` — не найден в modules/, вероятно входит в состав `process_module`

## Прогресс по этапам

| Этап | Статус | Описание |
|------|--------|----------|
| 0 | ✅ Завершён | Инфраструктура, баги, validate.py, STATUS.md |
| 1 | ⏳ Следующий | SystemLauncher → ProcessManagerProcess |
| 2 | ⏳ | Дочерние процессы |
| 3 | ⏳ | Ping-pong коммуникация |
| 4 | ⏳ | Живое ДНК |
| 5 | ⏳ | CommandManager + correlation_id |
| 6 | ⏳ | Graceful shutdown |
| 7 | ⏳ | Unit-тесты |
| 8 | ⏳ | Документация |
