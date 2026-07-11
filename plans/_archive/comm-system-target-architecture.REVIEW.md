# Сводный архитектурный вердикт: `plans/comm-system-target-architecture.md`

> Источник: мульти-агентный ревью-workflow `comm-plan-review` (2026-06-02). 5 граней (correctness/completeness/architecture/consistency/evolution) + 35 адверсариальных проверок по коду. Грани: 8/8/8/7/7. Опровергнуто находок самих ревьюеров: 7.
> **Статус:** все M/S/G-пункты ниже внесены в план (правки 2026-06-02) — см. header плана.

## 1. Вердикт одной строкой

**Профессиональный, доказательно сильный план с одной критической фактической ошибкой и парой пробелов; готов к исполнению P0 после точечной коррекции.**
Итоговая оценка: **B+ / 8 из 10**. Рекомендация: **approve-with-changes**.

Консенсус пяти граней (8/8/8/7/7): план — лучшая из трёх итераций, доказательная база честна, но один «верифицированный» тезис (`reinitialize_in_child`) сам оказался неверным.

---

## 2. Сильные стороны

- **Адверсариальная верификация реально работает** — план опроверг 7+ собственных ранних claim-ов (RolesPanel «1 execute»→0; «90% cross-machine» снято; `register_message_handler` «суженный контракт»→refuted; `queue_type` «leaks»→refuted; channel «safe to remove»→refuted; 5 фич ActionBus «absorbed»→`capability-to-build`).
- **Статус-дисциплина `capability-to-build` vs `absorbed`** — честная категория, закрывает порок v2. 5 фич ActionBus подтверждённо отсутствуют в Orchestrator (confirmed, high).
- **Матрица сохранности §9 (~80 способностей)** — артефакт, которого нет в других планах репо. `_pending_paths` подтверждён у всех 5 адаптеров; `WorkerPoolDispatcher` 0 prod; `StatsManager` не использует router.
- **Шесть ортогональных систем** разграничены корректно; тезис RouterManager-хаб верен (3 живых `IMessageChannel`).
- **24 quick-wins**, из них 5 новых active-bug с file:line — прямой вклад в debuggability.
- **Q1-Q9 зафиксированы**, точно транслированы в контракт.
- **P0→P3 грамотна по риску**, инвариант приёмки объявлен.

---

## 3. MUST-FIX (подтверждённые) — ВНЕСЕНЫ

### M1 — [critical] Ложный GAP: `reinitialize_in_child` ВЫЗЫВАЕТСЯ в prod
Цепочка: `process_runner.py:130-131` → `_build_shared_resources_from_bundle()` → `bundle_builder.py:128` явно зовёт `shared_resources.reinitialize_in_child()`. `else`-ветка — только тестовый SRM-mode. → GAP убран из §3.7; §9.2 статус `capability-to-build` → **`preserved`**. ADR-020 устарел (делегировано в bundle_builder).

### M2 — [major] `release_process_memory` — fix в MemoryManager, не в PM
Caller в PM уже есть (`process_manager_process.py:608` + warning 614-617). Отсутствует **реализация метода** на `MemoryManager` (есть `release_memory`/`close_memory`/`close_all`; нет в `IMemoryManager`). → §3.7/§9.2 переформулировано: «отсутствует реализация (caller готов)».

### M3 — [major] Три quick-wins не распределены по этапам
§11 пп.8 (битый `MessageAdapter.create_message`), 11 (`update_handler_*` хардкод), 14 (мёртвый `DispatcherConfig`) — не упомянуты в §12. → распределены в P0.

### M4 — [major] `expects_full_message` НЕ vestigial — «убрать» опасно
Флаг ветвит поведение (`dispatcher.py:402`, `base_dispatcher.py:130`, `chain_match.py:207`, `scenarios.py:146`). Асимметрия default: `Dispatcher`→False, `register_message_handler`→True. Builtin worker-команды (`builtin_commands.py:77-118`) регистрируются default=False. → §4/§11 п.19 переформулировано: «оставить + документировать асимметрию».

### M5 — [downgrade] `LoggerManager:401` НЕ «дублирует»
В проде `_router_manager=None` (`process_managers.py:159-167`), guard `logger_manager.py:360`. Нет LOG-приёмника. Реальный дефект — при `enable_router_routing=True` без приёмника бесполезный `router.send()` (overhead/dead traffic). → §2/§3.8/§9.7 переформулировано: «dead path / overhead».

---

## 4. SHOULD-FIX — ВНЕСЕНЫ

- **S1** — silent-drops пп.20-21 на деле логируют (`_log_warning`/`_log_error`). Баг в потере/нарушении контракта, не в «бесшумности». Переформулировано.
- **S2** — `bundle_builder` «в обход ADR-018» partial: очереди создаются в `process_registry` (родитель), bundle_builder лишь `add_queue`; обход касается фасада `SRM.register_process` (`bundle_builder.py:63,68`). Уточнено.
- **S3** — Modbus cmd-путь: §9.3 «intentionally-dropped» ↔ §12 P2 «слить» — выровнено на «слить (убрать дубль cmd_* в пользу channel.send)».
- **S4** — контракт §11 не покрывал silent-drops/relay/console/P1.5 — добавлен cross-reference на план §11/§12.
- **S5** — heartbeat race: окно <2s (не ~5s), бесконечный grace (`process_monitor.py:380 if last_hb is None: return`) → не false-positive, а задержка телеметрии. Переформулировано.
- **S6** — EventBus order refuted: bucket-ы изолированы по типу; реальный инвариант — порядок ВНУТРИ bucket `TopologyReplaced` (`app.py:477` до `presenter.py:121`), он соблюдён. Переписано.
- **S7** — добавлен cleanup-чеклист (судьба `_salvage_digest.md`, v1, v2).
- **S8** — добавлены чекбоксы `[ ]` для P0-P3 (трекинг `/plan-status`).
- **S9** — повторы §2↔§9 признаны допустимыми для справочника.

---

## 5. Пробелы покрытия — ВНЕСЕНЫ

- **G1** — `local_channel` (`{proc}_local`): живой `QueueChannel` в каждом процессе (`process_communication.py:99-109`), но **0 потребителей** (grep) — registered-but-never-consumed dead-end. → дан явный статус в §9 (не footnote).
- **G2** — `PluginContext` (ADR-120 enforcement) — добавлен в §9 как канонический comm-фасад плагина.
- **G3** — `ProcessIO` фасад — каталогизирован `preserved` в §9.
- **G4** — back-pressure refuted как «отсутствует»: реализован системно (AsyncSender `PriorityQueue(512)` drop+warn, `IBufferStrategy`, DataReceiver Q6, WorkerPool drop-oldest, SHM RingBuffer, mp.Queue bounded). Реальный gap — `events_queue` fallback (`process_communication.py:119`) без `maxsize`. → добавлена строка.
- **G5** — нет schema version в `Message` для cross-machine/long-lived → открытый вопрос §13.
- **G6** — стратегия тестирования/rollback P1/acceptance на этап — добавлены в §12.
- **G7** — единый Carve-out раздел (как v1 §6) с file:line — восстановлен.

---

## 6. Архитектурное мнение

Целевой дизайн **здрав** для конструктора распределённых систем. Единый хаб + `IMessageChannel` + push-канон (`on_inbound`) — правильно (снимает зависимость от хрупкого prefix-фильтра). Гибрид «почта/трубы» обоснован (zero-copy SHM). Принцип «не используется ≠ не нужно» применён корректно. Пять осей pub/sub без перекрытия.

**Риски масштабирования (честно):**
- Cross-machine: блокеры (SHM локален, нет discovery, bundle через inheritance, mp.Event in-process) реальны, но план их НЕ скрывает (§9.10 `intentionally-dropped`, §3.5, Q1). Добавлен явный список блокеров в §13.
- `routing_table` не подключён (P1 техдолг) — kind на хардкодах, осознанно.
- Latency/perf budget на hot-path (middleware при 30+ FPS) и span propagation — добавлены как открытые вопросы.

Вывод: дизайн без фундаментальных изъянов; пробелы — честно отложенные вопросы, не скрытые дефекты.

---

## 7. Эволюция vs первоисточники

Новый план объективно лучше v1/v2. Приобретено: адверсариальная верификация, статус-дисциплина `capability-to-build`, матрица §9, 24 quick-wins (vs 4), закрытие Q1-Q9. Потеряно (восстановлено правками): focused carve-out таблица (G7), coverage `local_channel` (G1), cleanup-инструкция (S7). Чистый баланс — существенно положительный.

---

## 8. Находки ревьюеров, которые САМИ оказались неверны (НЕ чинить)

1. `reinitialize_in_child` «не вызывается в prod» — **refuted** (вызывается, `bundle_builder.py:128`). Чинить формулировку плана (M1), не код.
2. `expects_full_message` vestigial — **refuted**, флаг активен (M4).
3. `LoggerManager` дублирует записи — **refuted/partial**, в проде router=None (M5).
4. Back-pressure отсутствует — **refuted**, реализован с тестами (G4).
5. EventBus order `TopologyReplaced`/`PluginConfigChanged` — **refuted**, bucket-ы изолированы (S6).
6. Heartbeat «окно ~5s → UNRESPONSIVE» — **partial**, окно <2s, бесконечный grace (S5).
7. silent-drops «бесшумны» — оба пути логируют (S1).
8. `StatsManager` «не подключён» — **partial**: router хранится (`stats_manager.py:86`), но не используется (dead wire); статус `capability` безопасен.

---

## 9. Готов ли план к исполнению P0

**Да — после внесённых правок.** Три MUST-FIX из четырёх — коррекция формулировок плана, не блокеры кода. Условия (выполнены): M1 (убрать ложный GAP), M3 (распределить пп.8/11/14 в P0), M4 (не убирать `expects_full_message`), S1/S5/S6 (переформулировать реальные баги). M2/G1 — уточнены параллельно, P0 не блокируют.

---
*Правки внесены в `plans/comm-system-target-architecture.md` (§3.7, §3.8, §4, §9.2, §9.3, §9.5, §9.7, §9.11, §11, §12, §13, §14, §15) и `multiprocess_framework/docs/COMMUNICATION_ARCHITECTURE.md` (§2, §3, §11).*
