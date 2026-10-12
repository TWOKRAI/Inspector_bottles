# Plan: Горячая смена рецепта на живом стенде и ложные разрывы ревизий

- **Slug:** stand-recipe-switch
- **Дата:** 2026-10-12
- **Статус:** DRAFT — ждёт ревью (`reviewer` MODE: plan) и слова владельца о слоте в очереди
- **Plan review:** PENDING
- **Ветка:** (назначает лид при старте; от свежего `main`)
- **Слой:** framework (`process_manager_module`, `state_store_module`, `app_module`), prototype (`backend/assembly`, `frontend/bridge`, `recipes`)
- **Источник:** находки 2026-10-12 (три исследователя, ревьюер, живой стенд `scripts/run_sim_all.ps1`); дефекты
  [`R-8`…`R-12`](../queue/defects.md) — строки реестра, сводка — [`_proposals/2026-10-12_plans-sync.md`](../queue/_proposals/2026-10-12_plans-sync.md)

## Почему новый план

Путь `topology.apply` в PM и доставку дельт `state_store` не ведёт ни один живой план: hot-swap закрыт в 2026-06
(`_archive/2026-06-06_replace-blueprint-hotswap.md`), `2026-07-06_constructor-master` (ревизии 4.9, 4.10 DEFERRED) стоит в
ORDER §4.2 на закрытии, `2026-09-22_gui-service` фаза 1b (активация рецепта на бэкенде) отложена решением О-16,
`framework-architecture-rework` — DRAFT. Один план на оба механизма: оба — дефекты фреймворка с одного стенда, без хозяина.
Порядок устройств при горячей смене (R-10) — у владельца механизма, [`device-tree-recipe`](../device-tree-recipe.md) Task B2.

## Цель

Владелец на стенде загружает GUI, запускает симуляторы и включает конвейер сменой рецепта — без зависания PM, без
ложного конфликта protected `devices`, на нужный рецепт. Подписчик `state_store` не делает resync без реальной потери.

## Порядок выполнения

### Ф1 — горячая смена рецепта не вешает PM (R-8, R-9, R-11)

- Task 1.1: Воспроизвести зависание `topology.apply` с дампом стека (`faulthandler` / `py-spy`), назвать блокирующий вызов [PENDING] — R-8; без кода фреймворка; 2026-10-12
- Task 1.2: `topology.apply` не исполняется на единственном потоке сообщений PM [PENDING] (после 1.1) — R-8; дизайн — по дампу 1.1, решает teamlead/CTO
- Task 1.3: `log_dir` движка топологии из `MULTIPROCESS_LOG_DIR`, без ложного конфликта protected `devices` [PENDING] — R-9
- Task 1.4: GUI передаёт `recipe_path` в `topology.apply`; ретаргет не читает старый манифест [PENDING] — R-11
- Task 1.5: Живая приёмка: «Сделать активным» на стенде `run_sim_all.ps1` — смена проходит, устройства подняты, ответ < 30 с [PENDING] (после 1.2, 1.3, 1.4) — нужна и `device-tree-recipe` Task B2 (R-10)

### Ф2 — запуск конвейера владельцем без новой кнопки GUI (находка F)

- Task 2.1: Рецепт `idle` (GUI + protected, без конвейера); старт и стоп конвейера — «Сделать активным» на рабочем или `idle` рецепте [PENDING] (после 1.5) — кнопка «Старт/Стоп» в GUI — полоса И, ⛔ О-16

### Ф3 — ложные разрывы ревизий (R-12)

- Task 3.1: Свой `seq` на подписчика в `DeltaDispatcher`; `StateProxy` и `GuiStateProxy` судят разрыв по `seq`, `revision` остаётся для свежести [PENDING] — R-12, ADR-SS-015; на line_sim `camera` 0 resync без потери (было 1813 WARNING)

## Риски

- R-9 — вероятный спуск R-8, но связь не доказана: Task 1.3 не закрывает R-8.
- Task 1.2 трогает PM — пересечение с Ж (`lifecycle-owner-scope`, `process_manager_module`): старт после сверки файлов с сессией Ж.
- Task 3.1 меняет контракт конверта дельты — ADR в `state_store_module/DECISIONS.md` (смена ADR-SS-015).
