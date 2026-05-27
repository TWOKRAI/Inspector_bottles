# Plan: Cross-tab architecture refactor (master)

- **Slug:** cross-tab-architecture
- **Дата:** 2026-05-27
- **Статус:** DRAFT (только Phase A детализирована; B-G — high-level из brief'а)
- **Ветка:** `refactor/cross-tab-architecture`
- **Brief (документ с фазами и target-архитектурой):** [`docs/refactors/2026-05_cross_tab_architecture.md`](../../docs/refactors/2026-05_cross_tab_architecture.md) — 398 строк, разделы 4 (target) и 5 (фазы) — обязательны к прочтению.

## Назначение этого файла

Индекс / манифест плана. **Не дублирует brief.** Brief описывает «зачем, что и почему». Этот файл — карта «как идём», ссылки на детализированные phase-планы по мере их создания.

Конвенция (см. [`CLAUDE.md`](../../CLAUDE.md)): multi-phase план хранится в папке `plans/<date>_<slug>/`, внутри — `plan.md` (этот файл) + `phase-X.md` по одному на фазу. Каждый phase-файл детализируется отдельно, только когда подходит его очередь (избегаем premature planning).

## Источник фаз

Brief, раздел 5 — `## 5. Scope / план фаз`. Здесь дублируется только заголовок и статус каждой фазы. Детали (что делает, deliverables, ожидаемая длительность) — в brief'е и в соответствующих `phase-X.md`.

## Фазы

| Фаза | Название | Статус | Файл | Зависимости |
|------|----------|--------|------|-------------|
| **A** | Audit (read-only inventory) | DRAFT | [`phase-a-audit.md`](phase-a-audit.md) | — |
| **B** | Domain skeleton (`multiprocess_prototype/domain/`) | NOT PLANNED | — | A done |
| **C** | Adapters (YAML I/O, TopologyHolder compat, ProcessManager) | NOT PLANNED | — | B done |
| **D** | `AppServices` DI (replace `ctx.extras` dict-bag) | NOT PLANNED | — | C done |
| **E** | Per-tab migration (Pipeline → Processes → Recipes → Services → Plugins → Displays → Settings) | NOT PLANNED | — | D done |
| **F** | Удаление legacy (`config["topology"]`, `extras["topology"]`, fallback chains) | NOT PLANNED | — | E done |
| **G** | UX-фишки (auto-reveal, domain-level validation, cross-tab linking, diff-view) | NOT PLANNED | — | F done |

**Правило:** phase-N+1 не детализируется до approval'а deliverable phase-N. Например, `phase-b-domain.md` пишется ТОЛЬКО после ревью отчёта Phase A.

## Текущая позиция

Phase A — план готов (`phase-a-audit.md`), исполнен investigator-агентом (read-only). Deliverable: [`docs/refactors/2026-05_cross_tab_audit.md`](../../docs/refactors/2026-05_cross_tab_audit.md), 380 строк.

Следующий шаг: ревью audit'а + approval. После approval — детализация Phase B (создание `phase-b-domain.md`).

## Известные ограничения и риски (вне Phase A)

Этот раздел растёт по ходу выполнения, фиксируя то, что нашлось в audit'е и требует внимания позже.

- **Recipe_manager double contract** (audit, Inventory 6) — `@property` в `app_context.py:135`, но вызывается как `recipe_manager()` в `pipeline/presenter.py:730,803`. MagicMock-тесты прощают оба. **Требует расследования** до Phase B (это симптомный баг, может ломать live GUI). Возможно — отдельный hotfix.
- **DisplayRegistry — 8-й реестр**, не в `extras`. Доступ через `getattr` всегда возвращает `None` в production (Inventory 3). Phase D должна это исправить.
- **4 параллельные dataclass-обёртки** (`TopologyContext`, `StateContext`, `PluginsContext`, `ActionsContext`) — созданы, не подключены. Phase D решит: либо подключить, либо удалить.
- **Pipeline tab — крупнейший consumer** (21 из 40 топологических чтений). Phase E начинает с него.
- **53 ad-hoc MagicMock в 39 тест-файлах** — 0 strict-моков `MagicMock(spec=AppContext)`. Phase D потребует тестовой стратегии — builder вместо MagicMock.
- **Audit делался на ветке `refactor/cross-tab-architecture`** (без cross-tab create feature). Файлы `feat/cross-tab-process-create` — отдельные consumers тех же anti-patterns; при мерже feature-ветки потребуется delta-audit для новых файлов.

## Ссылки

- [`docs/refactors/2026-05_cross_tab_architecture.md`](../../docs/refactors/2026-05_cross_tab_architecture.md) — brief / problem statement / target.
- [`docs/refactors/2026-05_cross_tab_audit.md`](../../docs/refactors/2026-05_cross_tab_audit.md) — Phase A deliverable.
- [`CLAUDE.md`](../../CLAUDE.md) — правила проекта, plan conventions.
- [`.claude/modes/dev.md`](../../.claude/modes/dev.md) — режим работы Dev-команды.
