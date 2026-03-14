# Multiprocess Framework — Documentation Index

**Полная документация фреймворка в одном месте.**

**Структура:** В корне — [README.md](./README.md), [DECISIONS.md](./DECISIONS.md), [MODULES_STATUS.md](./MODULES_STATUS.md). В [docs/](./docs/) — детальные документы. [DOCUMENTATION_SCORE.md](./DOCUMENTATION_SCORE.md) — оценка тимлида (8.2/10).

---

## 📚 Структура документации

### 0. **[docs/ARCHITECTURE_PHILOSOPHY.md](./docs/ARCHITECTURE_PHILOSOPHY.md)** ← FOR NEURAL AGENTS
**Философская архитектура для нейросетевых агентов (5000+ слов)**

Содержит:
- ✅ Основная проблема (почему Python multiprocessing сложен)
- ✅ Два взаимодополняющих взгляда (иерархия + биология)
- ✅ Тройца создания циклов (ProcessManagerCore, ProcessModule, WorkerManager)
- ✅ Аналогия с живым организмом
- ✅ Архитектурные слои
- ✅ Фундаментальные принципы (6 принципов)
- ✅ Жизненный цикл системы

**Используй когда:**
- Первый раз анализируешь архитектуру (лучше всего начать отсюда!)
- Нужно понять глубокую философию системы
- Хочешь объяснить архитектуру нейросети
- Планируешь расширение фреймворка

---

### 1. **[docs/FRAMEWORK_OVERVIEW.md](./docs/FRAMEWORK_OVERVIEW.md)** ← START HERE (AFTER PHILOSOPHY)
**Comprehensive overview всего фреймворка (8000+ строк)**

Содержит:
- ✅ Что это такое и зачем
- ✅ Архитектурные слои (15 модулей, описание каждого)
- ✅ Принципы архитектуры
- ✅ Диаграмма зависимостей
- ✅ Жизненный цикл приложения (4 фазы)
- ✅ Паттерны и принципы
- ✅ Ключевые архитектурные решения (из DECISIONS.md)
- ✅ Как всё работает вместе (сценарий обработки видео)
- ✅ Быстрый старт
- ✅ FAQ и anti-patterns

**Используй когда:**
- Первый раз изучаешь фреймворк
- Нужен полный overview
- Ищешь ответ на общий вопрос
- Нужно показать архитектуру коллеге

---

### 2. **[docs/ARCHITECTURE_REFERENCE.md](./docs/ARCHITECTURE_REFERENCE.md)** ← VISUAL GUIDE
**Диаграммы, таблицы, матрицы (для быстрого понимания)**

Содержит:
- 📊 Иерархия классов (наследование)
- 📊 Layer Cake (слои архитектуры)
- 📊 Message Flow (отправка/получение)
- 📊 Process Lifecycle
- 📊 Таблица модулей и их роли (15x6)
- 📊 Таблица типов сообщений (9x4)
- 📊 Таблица приоритетов AsyncSender
- 📊 Worker Modes, Process States
- 📊 Scope-based Logging Levels
- 📊 Dict at Boundary (преобразования)
- 📊 Channel Resolution Flow
- 📊 Initialization Order
- 📊 Error Handling Strategy
- 📊 Graceful Shutdown Cascade
- 📊 Module Dependencies Matrix (15x15)
- 📊 Performance Characteristics
- 📊 Memory и Resources

**Используй когда:**
- Нужна быстрая справка
- Ищешь специфичную информацию
- Нужно показать соотношение компонентов
- Анализируешь производительность

---

### 3. **[docs/ARCHITECTURE_ESSAY.md](./docs/ARCHITECTURE_ESSAY.md)** ← DEEP DIVE
**Развёрнутое эссе о том, почему архитектура работает (5000+ слов)**

Содержит:
- 💭 Введение (проблема многопроцессных приложений)
- 💭 BaseManager и ObservableMixin
- 💭 Message и Dict at Boundary
- 💭 Request-Response паттерн
- 💭 ChannelRoutingManager (DRY для Router/Logger/Error)
- 💭 SchemaBase и типизация данных
- 💭 ProcessModule и Graceful Shutdown
- 💭 Signal Handling
- 💭 Явные зависимости и OCP
- 💭 Pickle-Safe и reinitialize_in_child()
- 💭 8 паттернов проектирования
- 💭 9 преимуществ архитектуры
- 💭 Когда использовать / НЕ использовать
- 💭 Фундаментальные принципы

**Используй когда:**
- Хочешь понять философию проектирования
- Нужно обосновать архитектурное решение
- Учишь коллегу архитектуре
- Планируешь расширение фреймворка

---

### 4. **[DECISIONS.md](./DECISIONS.md)** ← DECISION LOG
**21 архитектурное решение (ADR) с обоснованием**

Содержит:
- 📋 ADR-001 до ADR-021
- 📋 Для каждого решения: дата, статус, контекст, решение, причина, альтернативы

**Ключевые решения:**
- ADR-001: ObservableMixin остаётся
- ADR-008: Dict at Boundary
- ADR-013: ChannelRoutingManager (база для трёх менеджеров)
- ADR-018: SRM.register_process() — единая точка регистрации
- ADR-021: Прямой pickle SRM

**Используй когда:**
- Хочешь понять, почему сделано так, а не иначе
- Закрыл issue и не хочешь открыть его заново
- Планируешь большое изменение в архитектуре

---

## 📖 Документация модулей (15 модулей)

### Foundation Layer

1. **base_manager**
   - README.md — BaseManager, ObservableMixin, BaseAdapter
   - STATUS.md — этап рефакторинга
   - tests/ — примеры использования

2. **data_schema_module**
   - README.md — SchemaBase, FieldMeta, SchemaRegistry, RegistersContainer
   - STATUS.md — оценки критериев
   - docs/QUICK_REFERENCE.md — краткая справка
   - docs/USER_GUIDE.md — полное руководство

3. **message_module**
   - README.md — Message (9 типов), MessageAdapter
   - tests/ — примеры

### Infrastructure Layer

4. **logger_module**
   - README.md — LoggerManager, LogConfig, BatchBuffer
   - docs/USAGE_GUIDE.md — как использовать

5. **error_module**
   - README.md — ErrorManager (extends LoggerManager)
   - config/error_config.py — конфигурация

6. **config_module**
   - README.md — ConfigManager, Config, ConfigSection
   - docs/USAGE_GUIDE.md — примеры

7. **console_module**
   - README.md — ConsoleManager, три уровня (пассивный/активный/God Mode), кроссплатформенность (Windows/Linux/macOS)
   - STATUS.md — этап 8/8
   - interfaces.py — IConsoleManager, IPlatformConsole
   - tests/ — 5 файлов (manager, adapter, redirector, log_channel, platforms)

8. **shared_resources_module**
   - README.md — SharedResourcesManager, ProcessData, MemoryManager
   - docs/ARCHITECTURE.md — архитектура

### Communication Layer

9. **router_module**
   - README.md — RouterManager, AsyncSender/AsyncReceiver
   - docs/COMMUNICATION.md — протокол

10. **dispatch_module**
    - README.md — Dispatcher (4 стратегии)

11. **command_module**
    - README.md — CommandManager (обёртка над dispatch_module)

### Process Layer

12. **worker_module**
    - README.md — WorkerManager (управление потоками)
    - docs/... — примеры

13. **process_module**
    - README.md — ProcessModule (базовый класс процесса)
    - docs/COMMUNICATION.md — как общаться между процессами

### Orchestration Layer

14. **process_manager_module**
    - README.md — SystemLauncher, ProcessRegistry, ProcessManagerProcess
    - STATUS.md — этап 8/8, полностью готов
    - interfaces.py — публичные контракты

---

## 🚀 Quick Navigation

### Я хочу...

**...понять архитектуру сразу**
→ [docs/ARCHITECTURE_PHILOSOPHY.md](./docs/ARCHITECTURE_PHILOSOPHY.md), потом [docs/FRAMEWORK_OVERVIEW.md](./docs/FRAMEWORK_OVERVIEW.md) (Part 1-7)

**...быстро найти информацию**
→ [docs/ARCHITECTURE_REFERENCE.md](./docs/ARCHITECTURE_REFERENCE.md) + `Ctrl+F`

**...понять, почему сделано так**
→ [docs/ARCHITECTURE_ESSAY.md](./docs/ARCHITECTURE_ESSAY.md) + [DECISIONS.md](./DECISIONS.md)

**...создать новый процесс**
→ [docs/FRAMEWORK_OVERVIEW.md](./docs/FRAMEWORK_OVERVIEW.md) (Quick Start) + process_module README

**...добавить новый менеджер**
→ base_manager README + [docs/ARCHITECTURE_ESSAY.md](./docs/ARCHITECTURE_ESSAY.md) (Dependency Injection)

**...отладить сообщения между процессами**
→ message_module README + router_module README + [docs/ARCHITECTURE_REFERENCE.md](./docs/ARCHITECTURE_REFERENCE.md) (Message Flow)

**...правильно остановить приложение**
→ [docs/FRAMEWORK_OVERVIEW.md](./docs/FRAMEWORK_OVERVIEW.md) (Graceful Shutdown) + process_manager_module STATUS.md

**...выбрать тип сообщения**
→ [docs/ARCHITECTURE_REFERENCE.md](./docs/ARCHITECTURE_REFERENCE.md) (Message Types Table) + message_module README

**...понять ChannelRoutingManager**
→ [docs/ARCHITECTURE_ESSAY.md](./docs/ARCHITECTURE_ESSAY.md) (Part 3) + [DECISIONS.md](./DECISIONS.md) (ADR-013)

**...узнать про Dict at Boundary**
→ [docs/FRAMEWORK_OVERVIEW.md](./docs/FRAMEWORK_OVERVIEW.md) (Message Flow) + [docs/ARCHITECTURE_ESSAY.md](./docs/ARCHITECTURE_ESSAY.md) (Part 2) + [DECISIONS.md](./DECISIONS.md) (ADR-008)

---

## 📊 Statistics

| Документ | Строк | Время чтения | Сложность |
|----------|--------|-----------|----------|
| FRAMEWORK_OVERVIEW.md | ~1500 | 45 мин | Средняя |
| ARCHITECTURE_REFERENCE.md | ~1000 | 30 мин | Низкая (таблицы) |
| ARCHITECTURE_ESSAY.md | ~800 | 30 мин | Высокая |
| DECISIONS.md | ~280 | 20 мин | Средняя |
| **ИТОГО** | **~3500** | **125 мин** | - |

**Минимум для начала:** [docs/FRAMEWORK_OVERVIEW.md](./docs/FRAMEWORK_OVERVIEW.md) Part 1-7 (45 мин)

---

## 🎯 Learning Path

### День 1: Основы
1. [docs/ARCHITECTURE_PHILOSOPHY.md](./docs/ARCHITECTURE_PHILOSOPHY.md) (введение в философию)
2. [docs/FRAMEWORK_OVERVIEW.md](./docs/FRAMEWORK_OVERVIEW.md) (Part 1-7)
3. [docs/ARCHITECTURE_REFERENCE.md](./docs/ARCHITECTURE_REFERENCE.md) (иерархия классов, слои)

### День 2: Детали
1. [docs/ARCHITECTURE_ESSAY.md](./docs/ARCHITECTURE_ESSAY.md) (Part 1-7)
2. [DECISIONS.md](./DECISIONS.md) (ADR-001, 008, 013, 018, 021)

### День 3: Практика
1. Создать простой процесс (Process1, Process2)
2. Добавить обмен сообщениями между ними
3. Запустить через SystemLauncher
4. Дебажить через логирование

### День 4+: Углубление
1. Добавить новый менеджер
2. Создать кастомный канал (для БД, HTTP, etc)
3. Добавить кастомные стратегии диспетчеризации

---

## 🔗 Cross-References

### Если читаешь про Message
- Сначала: message_module README
- Потом: [docs/FRAMEWORK_OVERVIEW.md](./docs/FRAMEWORK_OVERVIEW.md) (Message & Dict at Boundary)
- Углубление: [docs/ARCHITECTURE_ESSAY.md](./docs/ARCHITECTURE_ESSAY.md) (Part 2)
- Decision: [DECISIONS.md](./DECISIONS.md) (ADR-008)

### Если читаешь про ChannelRoutingManager
- Сначала: [docs/ARCHITECTURE_ESSAY.md](./docs/ARCHITECTURE_ESSAY.md) (Part 3)
- Потом: [DECISIONS.md](./DECISIONS.md) (ADR-013)
- Реализация: router_module + logger_module README

### Если читаешь про ProcessModule
- Сначала: process_module README
- Потом: [docs/FRAMEWORK_OVERVIEW.md](./docs/FRAMEWORK_OVERVIEW.md) (Lifecycle)
- Примеры: multiprocess_prototype/main.py
- Graceful: process_manager_module STATUS.md

---

## 📝 Notes for Developers

### Adding New Module
1. Наследуй `BaseManager + ObservableMixin`
2. Реализуй `initialize()` и `shutdown()`
3. Создай `interfaces.py` с публичным контрактом
4. Напиши `README.md` по шаблону
5. Добавь unit-тесты в `tests/`
6. Обнови DECISIONS.md если нужно

### Adding New Manager Type
1. Реши: нужны ли каналы? → наследуй `ChannelRoutingManager`
2. Реши: нужна логирование? → добавь `ObservableMixin`
3. Реализуй специфичные методы
4. Добавь в таблицу [docs/ARCHITECTURE_REFERENCE.md](./docs/ARCHITECTURE_REFERENCE.md)

### Modifying Architecture
1. Прочитай [DECISIONS.md](./DECISIONS.md)
2. Запиши новое решение в DECISIONS.md
3. Запусти `python scripts/validate.py`
4. Обнови [docs/FRAMEWORK_OVERVIEW.md](./docs/FRAMEWORK_OVERVIEW.md)
5. Обнови [docs/ARCHITECTURE_REFERENCE.md](./docs/ARCHITECTURE_REFERENCE.md)

---

## 🐛 Debugging Tips

### Сообщения не идут между процессами
- Проверь: правильно ли указаны `targets` в сообщении?
- Проверь: инициализирован ли RouterManager в обоих процессах?
- Включи логирование: `LoggerManager(...)` с level=DEBUG
- Дебажь через: [docs/ARCHITECTURE_REFERENCE.md](./docs/ARCHITECTURE_REFERENCE.md) (Message Flow)

### Процесс не завершается на Ctrl+C
- Проверь: проверяет ли worker `stop_event.is_set()`?
- Проверь: не заблокирован ли в `queue.get()` без timeout?
- Проверь: timeout в ProcessRegistry.stop_all()
- Дебажь через: [docs/FRAMEWORK_OVERVIEW.md](./docs/FRAMEWORK_OVERVIEW.md) (Graceful Shutdown)

### Pickle ошибка на Windows
- Помни: Dict at Boundary! Используй `msg.to_dict()` перед `queue.put()`
- Проверь: не передаёшь ли Pydantic модели через очередь?
- Помни: после unpickle нужен `srm.reinitialize_in_child()`
- Дебажь через: [DECISIONS.md](./DECISIONS.md) (ADR-021)

---

## 📄 Version History

| Дата | Версия | Статус | Примечание |
|------|--------|--------|-----------|
| 2026-03-13 | 1.0 | Complete | Первая версия документации, все 15 модулей |

---

**Последнее обновление:** March 14, 2026

