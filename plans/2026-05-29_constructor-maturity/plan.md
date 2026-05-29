# Plan: Constructor maturity — примирение движка, конструкторные оси, вынос в framework (master)

- **Slug:** constructor-maturity
- **Дата:** 2026-05-29
- **Статус:** PLANNED. P0 (gate) → P1 DETAILED ([`phase-1-command-engine.md`](phase-1-command-engine.md)); P2–P6 — манифест (детализируются по очереди).
- **Ветка:** `refactor/constructor-maturity` (создаётся при старте P1; НЕ создана автоматически)
- **Предшественник:** [`plans/_archive/2026-05-27_cross-tab-architecture/`](../_archive/2026-05-27_cross-tab-architecture/plan.md) — все фазы A–G закрыты (архив).

## Назначение

Этот файл — индекс/манифест следующего архитектурного шага **после** cross-tab.
Цель владельца (зафиксирована в обсуждении): **всё модульно — плагины, сервисы, виджеты, как конструктор.**
Плюс перспектива: **вынести универсальные части прототипа во framework** для переиспользования в других приложениях.

Cross-tab дал доменное ядро (typed entities/commands/events, `AppServices` DI, snapshot-undo).
Этот план закрывает оставшиеся швы и достраивает самую слабую ось конструктора — **виджеты/UI-генерацию** — до уровня плагинов и сервисов.

## Принципы (перенесены из cross-tab, проверены практикой)

1. **No big-bang.** Фаза за фазой, строгая цепочка, каждая мержится с зелёными тестами.
2. **Reality-audit перед КАЖДОЙ фазой (Phase A-style).** Урок cross-tab: премисы плана систематически расходились с кодом (6 повторов). Перед детализацией Pn — read-only investigator, факты `file:line`, и только потом task-spec.
3. **Detail-on-demand.** Pn+1 не детализируется до approval deliverable Pn. Этот файл держит только манифест.
4. **Engine vs model.** Всё, что универсально (движок), отделяется от app-specific (модель пайплайна камер). Вынос в framework — только движка.
5. **Вынос triggered, не scheduled.** Универсальное доказывается **вторым потребителем**, а не календарём (brief cross-tab §8: не вводить абстракцию до 2-го реализатора). P6 стартует при появлении app #2, не раньше.
6. **Закрывать швы Protocol'ом только если adapter реально покрывает API** (урок E.4/E.5). Иначе bridge остаётся by design.

## P0 — Gate: merge + стабилизация cross-tab (не работа, условие)

- **Условие старта P1.** Завершить G.6 (UX), смержить `refactor/cross-tab-architecture` в `main`, дать API domain/adapters/events **отстояться** (несколько недель реальной работы прототипа стабилизируют контракты лучше любого ревью).
- Пока cross-tab не смержен — P1+ не начинать (не стекать большой рефактор поверх несмерженной ветки).
- **Acceptance:** cross-tab в `main`, тесты зелёные, нет открытых блокеров G.6.

## Фазы

| Фаза | Название | Зачем | Ось конструктора | Риск | Зависит | Статус |
|------|----------|-------|------------------|------|---------|--------|
| **P0** | Merge + стабилизация cross-tab | условие | — | — | G.6 done | gate |
| **P1** | Примирение движка команд/undo | убрать дублирование domain-dispatch ⟷ ActionBus; один движок + pluggable middleware (auth/audit) | фундамент под вынос | MED | P0 | **DETAILED** |
| **P2** | Единый манифест плагина + domain-driven Inspector | закрыть sandbox-костыль `_registry`; UI строится из domain `FieldMeta`, не framework `FieldInfo` | **плагины + виджеты** (слабейшая ось) | MED-HIGH | P1 | манифест |
| **P3** | Granular events + ликвидация `PipelineModel`-dict | сделать SSOT настоящим; убрать двойную репрезентацию + 10 raw-dict обходов | виджеты | HIGH | P1 | манифест |
| **P4** | Runtime snapshot aggregate | разделить editor `Project` и runtime (PID/FPS/lifecycle/метрики); дать `RuntimeDeps` типизированные Protocol'ы | сервисы/runtime | MED-HIGH | P1 | манифест |
| **P5** | Декларативный реестр табов/виджетов + typed Service⟷Recipe | табы регистрируются как данные (симметрия плагинам); рецепт типизированно резолвит/поднимает сервисы | виджеты + сервисы | MED | P2, P4 | манифест |
| **P6** | Вынос движка в framework | переиспользование в других приложениях | мета-конструктор | HIGH | **app #2** (trigger) | манифест (triggered) |

## Обоснование порядка

- **P1 первой** — это фундамент: пока два движка команд/undo конкурируют, любой вынос в framework законсервирует конкуренцию. Низко-средний риск, форма уже разобрана (см. phase-1).
- **P2 — главная для цели владельца:** виджеты/UI-генерация — самая слабая ось конструктора. Единый манифест плагина + domain-driven Inspector доводят её до уровня плагинов и попутно убивают sandbox-костыль `getattr(services.plugins, "_registry")`.
- **P3** — самый крупный оставшийся костыль (двойная репрезентация), но full-reload корректен → это полировка+SSOT, не исправление багов. Поэтому после P2.
- **P4/P5** — следующий слой зрелости (runtime-контракты, декларативные табы).
- **P6 — последней и по триггеру.** Выносить движок, не модель. До app #2 — только держать движок import-чистым («физически в прототипе, логически framework-качества»).

## Что НЕ входит (явный scope cut)

- Вынос модели (entities Process/Wire/Topology) в framework — это app-specific, остаётся в прототипе.
- Полная замена framework `actions_module` — P1 решает соотношение, но не удаляет framework-слой без анализа других потребителей (SQL action_log, framework-тесты).
- Новый дизайн-систем компонентов «с нуля» (React-style) — отдельная история; P2/P3/P5 готовят почву (domain-driven формы, реестр), полноценная design-system — после.

## Ссылки

- [`phase-1-command-engine.md`](phase-1-command-engine.md) — детальный план P1.
- [`plans/_archive/2026-05-27_cross-tab-architecture/phase-g.md`](../_archive/2026-05-27_cross-tab-architecture/phase-g.md) — G.4 audit (домен-dispatch, мёртвый ActionBus), G.6 deferred (granular updates).
- `multiprocess_prototype/adapters/dispatch/command_dispatcher.py` — domain-dispatch + ProjectHistory.
- `multiprocess_framework/modules/actions_module/bus.py` — framework ActionBus (patch-undo, RBAC-hook, audit, SQL-log).
- [`CLAUDE.md`](../../CLAUDE.md) — слои импортов, plan-конвенции, layer-rules.
