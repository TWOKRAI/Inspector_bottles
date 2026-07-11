# event_module — Архитектурные решения

## EVT-002: `EventBus` (event_module) vs `EventManager` (shared_resources_module) — НЕ дубль, только коллизия имён

**Дата:** 2026-07-11
**Статус:** Принято
**Refs:** `docs/audits/2026-07-10_module-responsibility-duplication-map.md` §1/§4 (N1), decision-log Ф5-добора в `plans/2026-07-06_constructor-master/plan.md` (Q1), `multiprocess_framework/docs/MODULES_RESPONSIBILITY_MAP.md` §2 «Три оси событий», зеркало — [`shared_resources_module/DECISIONS.md`](../shared_resources_module/DECISIONS.md) ADR-SRM-010

### Контекст

Аудит дублирования 2026-07-10 (N1) зафиксировал: `event_module.EventBus`
(`event_bus.py:81`) и `shared_resources_module.events.core.manager.EventManager`
(`events/core/manager.py:22`) звучат как «одно и то же» (оба — «шина событий»), но
живут на разных осях:

- **`event_module.EventBus`** — **in-process** typed pub/sub «фактов»: синхронная
  диспетчеризация по `type(event)`, pure Python, generic (`TypeVar E` без bound),
  ничего не знает про процессы (leaf-модуль, см. EVT-001).
- **`shared_resources_module.EventManager`** — **межпроцессный** примитив: `emit`
  уходит и локальным подписчикам, и в роутер (pickle-safe payload), часть слоя
  `shared_resources_module` (очереди/SHM/EventManager/ConfigStore/PSR — межпроцессные
  ресурсы).

Владелец решил (2026-07-10, decision-log Ф5-добора): **имена НЕ переименовываются**
(Принцип №1 «не трогать работающее без необходимости» — `SystemEventBus` и другие
варианты обсуждались и отклонены как churn ради косметики, риск сломать импорты в
40+ потребителях без архитектурной выгоды). Вместо переименования — зафиксировать
семантическую границу текстом (эта запись + зеркало в SRM + уже существующая таблица
§2 `MODULES_RESPONSIBILITY_MAP.md`), чтобы при чтении/поиске «EventBus» не путали ось.

### Решение

1. **Имена остаются как есть.** `event_module.EventBus` — in-proc; SRM `EventManager` —
   cross-proc. Разводить по контексту вызова (внутри одного процесса без адресата →
   `EventBus`; событие должно уйти в другой процесс → `EventManager`), не по названию.
2. **Вектор на будущее — не отдельный рефактор.** Консолидация cross-proc событийности
   (`EventManager` dual-write: emit локальным подписчикам + роутер отдельно) — часть
   более широкого сворачивания транспорта в `router.send` по [ADR-COMM-001](../../DECISIONS.md#adr-comm-001-routersendmessage--единственный-способ-отправки-каналы-по-kind--канонический-транспорт)
   (план `transport-router-hub`; `EventManager` уже числится в списке обходов Router,
   см. `MODULES_RESPONSIBILITY_MAP.md:135`). Переименование `EventManager`, если
   когда-нибудь понадобится, решается **только в связке** с этой консолидацией, не
   отдельным именным рефактором — иначе имя разъедется с тем, что модуль реально делает
   после переезда транспорта в router.
3. **`event_module.EventBus` вектора на изменение НЕ имеет** — in-proc ось стабильна,
   ADR-COMM-001 её не касается (COMM-серия — про межпроцессный транспорт).

### Причина

Переименование ради устранения коллизии имён создаёт churn без архитектурной пользы
(обе оси и так корректно разделены по ответственности — см. `MODULES_RESPONSIBILITY_MAP.md`
§2) и рискует сломать импорты раньше, чем понятна форма транспорта после ADR-COMM-001.
Текстовая фиксация границы (эта запись + зеркало) достаточна: разработчик, ищущий
«EventBus», находит обе записи и явную инструкцию, как выбрать.

### Отклонённые альтернативы

- **Переименовать `EventManager` → `SystemEventBus` сейчас** — отклонено: `EventManager`
  затронут консолидацией транспорта (ADR-COMM-001); переименование до/вне этой
  консолидации создало бы второе имя, которое снова придётся менять при переезде на
  router.
- **Переименовать `event_module.EventBus`** — отклонено: модуль — leaf, 0 связи с
  cross-proc транспортом, переименование не решает проблему коллизии (коллизия — в
  имени SRM-класса, не EventBus).

### Последствия

- Документация (эта запись + `MODULES_RESPONSIBILITY_MAP.md` §2) — единственный
  механизм устранения путаницы; кода это решение не меняет.
- Будущая консолидация cross-proc событийности (в рамках ADR-COMM-001) — кандидат
  пересмотреть имя `EventManager`, но не раньше её реализации.

---

## EVT-001: EventBus вынесен во framework как generic typed pub/sub

**Дата:** 2026-06-18
**Статус:** Принято
**Refs:** docs/audits/2026-06-18_command-undo-system.md, memory `feedback_framework_first`

### Контекст

Конструктор различает три ортогональные оси: команды/undo, реактивное состояние,
**события-факты**. Событийная ось (EventBus) жила в прототипе
(`multiprocess_prototype/domain/event_bus.py`) и формально была связана с доменным
union `ProjectEvent` (`TypeVar bound=ProjectEvent`). Правило framework-first: механизм,
нужный любому проекту, принадлежит фреймворку.

### Решение

Вынести EventBus в новый framework-модуль `event_module` как **generic** pub/sub: тип
события НЕ ограничен (`TypeVar E` без bound), т.к. шина диспетчеризует только по
`type(event)` и ничего не вызывает на самом событии — оно непрозрачно. Контракты
(`EventBusProtocol`, `Subscription`) — рядом в `interfaces.py`. Прототип становится тонким
потребителем через **re-export-шим** (`domain/event_bus.py`, `domain/protocols/event_bus.py`)
— импорты всех потребителей сохраняются без изменений.

Qt-thread-safety (`QtEventBus`) остаётся в прототипном `frontend/` — это обёртка над
generic-шиной, а не часть ядра (domain/framework — Qt-free).

### Альтернативы

- Оставить EventBus в прототипе — нарушает framework-first (конструктор без событийной оси).
- Сразу переключить всех 40+ потребителей на framework-импорт — churn/риск без выгоды;
  re-export-шим достаточен (прототип = тонкий потребитель), переключение — при необходимости.
- Ограничить `E` структурным Event-Protocol — избыточно: шина не вызывает методов события.

### Последствия

- Framework владеет generic EventBus; следующий проект переиспользует с любым набором событий.
- 0 обратных импортов (generic, без app-типов); прототип-шимы — pure re-export.
- characterization прототипа (test_event_bus/test_protocols/test_qt_event_bus) зелёные 1:1.
