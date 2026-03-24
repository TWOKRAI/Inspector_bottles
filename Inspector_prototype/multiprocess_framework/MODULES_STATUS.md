# Статус модулей — MODULES_STATUS.md

Обновляется после каждого этапа. Детали в `modules/{name}/STATUS.md`.

| Модуль | Этап | Код | Тесты | Docs | Связанность | Работает |
|--------|------|-----|-------|------|-------------|----------|
| **channel_routing_module** | **8/8** ✅ | **9** | **8** | **10** | **10** | **да** |
| **sql_module** | **8/8** ✅ | **9** | **20** | **9** | **9** | **да** |
| base_manager | 0/8 | 7 | 6 | 4 | 5 | да |
| data_schema_module | 0/8 | 7 | 8 | 6 | 3 | да |
| message_module | 0/8 | 5 | 3 | 3 | 2 | ? |
| **logger_module** | **4/8** | **9** | **7** | **8** | **9** | **да** |
| **error_module** | **3/8** | **10** | **7** | **9** | **9** | **да** |
| **config_module** | **8/8** ✅ | **9** | **9** | **9** | **8** | **✅ 49 тестов** |
| **console_module** | **8/8** | **8** | **7** | **9** | **8** | **да** |
| shared_resources_module | 0/8 | 6 | 3 | 4 | 4 | да |
| dispatch_module | 0/8 | 5 | 3 | 4 | 3 | ? |
| **router_module** | **4/8** | **9** | **8** | **9** | **9** | **да** |
| command_module | 0/8 | 5 | 3 | 5 | 4 | ? |
| worker_module | 2/8 | 6 | 5 | 3 | 3 | да |
| registers_module | 0/8 | 7 | 3 | 3 | 3 | да |
| process_module | 2/8 | 5 | 3 | 4 | 2 | да |
| process_manager_module | 2/8 | 7 | 5 | 5 | 3 | да |

---

## Модули первого приоритета (8/8 готовы к production)

- **channel_routing_module** — CRM, каналы, буфер, 58 тестов
- **config_module** — runtime конфиги, подписки, env-fallback, 49 тестов
- **console_module** — консольный вывод, 7+ тестов
- **sql_module** — SQLManager, sync/async UoW, доступ к БД через канал `database`, 20 тестов

---

## Прогресс по этапам (общий roadmap)

| Этап | Статус | Описание |
|------|--------|----------|
| 0 | ✅ Завершён | Инфраструктура, баги, validate.py, STATUS.md |
| 1 | ✅ Завершён | SystemLauncher → ProcessManagerProcess запускается |
| 2 | ✅ Завершён | ProcessManager создаёт Process1Module, Process2Module; воркеры работают |
| 3 | ⏳ | Ping-pong коммуникация |
| 4 | ⏳ | Живое ДНК |
| 5 | ⏳ | CommandManager + correlation_id |
| 6 | ⏳ | Graceful shutdown |
| 7 | ⏳ | Unit-тесты |
| 8 | ⏳ | Документация |

---

## CRM Unification Plan — Статус фаз

| Фаза | Статус | Описание |
|------|--------|----------|
| Фаза 1 | ✅ Завершена | channel_routing_module создан (CRM, IChannel, ChannelRegistry, IBufferStrategy, буферы, тесты) |
| Фаза 2 | ✅ Завершена | LoggerManager(ChannelRoutingManager), ILogChannel(IChannel), ChannelRoutingConfig |
| Фаза 3 | ✅ Завершена | ErrorManagerConfig(ChannelRoutingConfig), _level_to_channel, log() override |
| Фаза 4 | ✅ Завершена | RouterManager(ChannelRoutingManager), IMessageChannel(IChannel), _channel_registry из CRM |
| Фаза 5 | ✅ Завершена | Документация: README, DECISIONS.md (ADR-013..016), STATUS.md всех модулей, cursor rules |

---

## Config Module Refactoring — Статус

| Фаза | Статус | Описание |
|------|--------|----------|
| Этап 0-8 | ✅ Завершено | Config (~160 строк), ConfigManager (~215 строк), ConfigSection, ConfigManagerConfig |
| Документация | ✅ Завершено | README.md, docs/ARCHITECTURE.md, docs/USAGE_GUIDE.md (20+ примеров) |
| Интеграция | ✅ Завершено | Добавлен в MODULES_STATUS, DECISIONS (ADR-023), docs/ |
| Тесты | ✅ 49 passed | Config, ConfigManager, ConfigSection полностью покрыты |

---

## Тесты после CRM-миграции и config_module рефакторинга

```
channel_routing_module  58 passed  ✅
logger_module           ~30 passed ✅
error_module            ~30 passed ✅
router_module           ~37 passed ✅
config_module           49 passed  ✅
─────────────────────────────────────
ИТОГО                   204 passed ✅
```
