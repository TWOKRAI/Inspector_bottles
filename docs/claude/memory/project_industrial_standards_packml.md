---
name: project-industrial-standards-packml
description: "Решение владельца 2026-10-27 — состояния машины/системы строить по PackML (ISA-TR88.00.02, OPC 30050); причины готовности — NAMUR NE 107; категории остановки — IEC 60204-1 / packml, state machine, stop categories, readiness"
module: [process_manager_module]
mechanism: [owner-decision, lifecycle]
metadata:
  node_type: memory
  type: project
  modified: 2026-10-27T14:00:00.000Z
---

Владелец 2026-10-27: «придерживайся PackML и запомни»; общее — «подтягивай промышленные стандарты».

- **Состояния системы и машины — по PackML** (модель состояний OPC 30050 v1.01, 2020; ISA-TR88.00.02, издание 2022 не подтверждено): Idle / Starting / Execute / Stopping / Stopped / Aborting / Aborted / Clearing / Resetting (+ Held, Suspended, Complete — только если нужны). Режимы Production / Maintenance / Manual. Наши имена мапятся на PackML явно, в design-документе раздел «Соответствие стандартам»: что берём, что сознательно нет. Минимальное подмножество — принцип «меньше слоёв».
- **Выход из аварии — через Clear (сброс/квитирование), не через Start** (PackML Aborted → Clearing → Stopped; ISA-18.2 — квитирование отдельно). Позиция координатора по плану 14а, владелец ещё не ответил.
- **Причины «не готов» — шкала NAMUR NE 107** (ревизия 2017): Failure / Function check / Out of specification / Maintenance required / OK.
- **Остановка — категории IEC 60204-1** (Ed. 6.0 2016 + AMD1:2021): 0 — снять питание приводов (программно у нас нет, это STO/контактор; ближе всего HALT), 1 — управляемый стоп и снятие питания («Остановить»: домой → серво OFF), 2 — управляемый стоп с питанием (HARD и SOFT робота v2, серво ON). Программный стоп ≠ аварийный (e-stop — аппаратная функция безопасности, ISO 13849 / IEC 62061).
- OPC UA (PackML companion, DI 1.05.0) — в 1.0 нет; пути `state_store` выбирать так, чтобы их можно было выставить позже без переименования.

**Why:** framework — промышленный конструктор; своя модель состояний без опоры на стандарт расходится с тем, что ждут интеграторы и операторы, и переделывается дважды.
**How to apply:** любой план про состояния, готовность, старт/стоп, аварии, пульт оператора — сверять с PackML и строить мапинг; агенту давать ссылку на этот файл. Планы-носители: `plans/2026-10-27_system-run-state/` (14а), `plans/robot-protocol-v2/tasks/T5.3e.terms.md`. Связано: [[project-universal-lifecycle-decision]], [[feedback-framework-first]].
