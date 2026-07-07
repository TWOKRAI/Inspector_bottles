# Идея: «контактная книжка» бэкенда (capability manifest)

- **Статус:** v0 РЕАЛИЗОВАН (Ф1.9, 2026-07-07) — `docs/contracts/CAPABILITIES.yaml`+`.md`, CI-gate живой. Отклонение: свод собирает driver (fan-out), не PM-хендлер — блокирующий сбор ответов детей внутри PM дедлочит message_processor. v1 (params_schema) — Ф4.2
- **Суть:** бэкенд самоописывается — машиночитаемый каталог команд (с параметрами), каналов, state-путей и регистров. Агент ЧИТАЕТ каталог → ЗНАЕТ, как управлять системой через backend_ctl, без чтения исходников.

## Зачем

Сегодня агент узнаёт «что умеет процесс» тремя дорогами: чтение кода, `introspect.handlers`
(имена без параметров), ROUTING_GLOSSARY/AGENTS.md (прозой, дрейфует). Контактная книжка
делает знание исполняемым: один источник истины, генерируется из кода, дрейф ловит CI.

## Дизайн (три слоя, source of truth — код)

```
[1] Регистрации в коде                [2] Runtime-агрегатор            [3] Статический дамп
CommandManager.register_command  ──►  introspect.capabilities  ──►    docs/contracts/CAPABILITIES.yaml
(metadata: description, +schema)      (PM собирает со всех             (+ CAPABILITIES.md для людей/агентов)
Ф4.2 реестр command→схема             процессов; driver.capabilities())  CI-gate: дамп == runtime (нет дрейфа)
FieldRouting/kind-каналы
health-схема state-путей (Ф2.1)
```

1. **Источник — существующие регистрации.** `register_command(name, handler, metadata={"description"})`
   уже несёт описание; Ф4.2 (реестр контрактов сообщений) добавляет схему параметров —
   контактная книжка НЕ вводит новый реестр, а агрегирует эти два.
2. **Runtime:** команда `introspect.capabilities` в PM — свод по всем процессам:
   - `commands`: process → [{name, description, params_schema?, tags}]
   - `channels`: имя канала → kind/направление (из FieldRouting/QoS-профилей Ф7 G.4)
   - `state_paths`: типизированные пути health-схемы (Ф2.1) + основные ветки дерева
   - `registers`: process → plugin → поля (уже есть introspect.registers — включить в свод)
   Обёртка `driver.capabilities()` + инструмент в MCP-обёртке (Ф1.7).
3. **Статический дамп:** `python -m backend_ctl.dump_capabilities` (поверх harness Ф1.3,
   headless) → `docs/contracts/CAPABILITIES.yaml` (+ .md «книжка» для агентов).
   CI-gate: перегенерировать и сравнить — дрейф код⇄документ = красный билд
   (ровно рекомендация аудита Тема 3: «schema-manifest дамп + CI-gate на дрифт»).

## Фазировка (не изобретать контракты до Ф4)

| Версия | Когда | Содержимое |
|---|---|---|
| **v0** | Ф1 (сразу после 1.2/1.3) | `introspect.capabilities` = свод того, что УЖЕ регистрируется (имена команд + descriptions + registers + процессы/каналы); дамп + .md; без схем параметров |
| **v1** | Ф4 (после 4.2/4.4) | + `params_schema` из реестра контрактов; манифесты плагинов (4.4) включаются в книжку; strict-режим: команда без схемы = warning в CI |
| **v2** | Ф7 | + QoS-профили каналов (G.4) и drop-счётчики как часть свода |

## Предлагаемые задачи в plan.md

- **Ф1.9 (S/M):** `introspect.capabilities` v0 в PM + `driver.capabilities()` +
  `dump_capabilities` → docs/contracts/ + CI-сравнение. Acceptance: агент по одному
  дампу воспроизводит сценарий smoke_proof (шлёт команды, не читая исходников).
- **Ф4.2-доп:** книжка v1 — params_schema из реестра контрактов (уже в acceptance 4.2
  добавить строку «capabilities отдаёт схемы»).

## Правила

- Книжка ГЕНЕРИРУЕТСЯ, руками не пишется (иначе станет третьим дрейфующим документом).
- AGENTS.md/README backend_ctl ссылаются на неё, а не дублируют список команд.
- Связь: [[feedback-backend-ctl-for-agents]] (driver — единственная дверь агента в бэкенд).
