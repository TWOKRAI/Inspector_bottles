# event_module — Архитектурные решения

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
