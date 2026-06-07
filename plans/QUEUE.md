# Очередь планов

> Снимок на **2026-06-07**. Закрытые планы — в [`_archive/`](_archive/).
> Статусы выведены по git-истории + memory (часть планов не была помечена вручную).

---

## 🔥 Активно — ветка `fix/recipe-v3-engine-decouple`

| План | Состояние | Осталось |
|------|-----------|----------|
| [recipe-orchestrator-unify](2026-06-06_recipe-orchestrator-unify.md) | Phase 1-2 **DONE** (`5314d99b`, `362d16df`→`2407f5ac`, rollback `7a845d25`, чистка `191732eb`) | **Phase 3** (RecipeManager — единый владелец активного рецепта), **Phase 4** (тонкий GUI), **Phase 5** (carve-out `RecipeManager`/трансформер во framework) |

---

## 📋 В очереди

### Рецепты / follow-up
| План | Статус | Суть |
|------|--------|------|
| [displays-in-recipe](../docs/direction/displays-in-recipe.md) (ТЗ) | SPEC plan-ready, ⛔ ждёт unify Phase 2 | Определения дисплеев → в рецепт (секция `recipe.displays`), render-параметры (fit/scale/rotate/flip/crop/position), вкладка recipe-scoped, мигратор. Ревью Opus 6/10 → 3 блокера закрыты в ТЗ. Поглощает recipe-format T1 |
| [recipe-format-single-source](2026-06-06_recipe-format-single-source.md) | PLANNED (T1 поглощён displays-in-recipe) | T2 defer (prod-safety), T3 drop (косметика). T1 (single source дисплеев) уходит в displays-in-recipe |

### Pipeline / live-control
| План | Статус | Осталось |
|------|--------|----------|
| [pipeline-live-control](2026-05-31_pipeline-live-control/) | Этап 1-2 **DONE** (Task 2.4 `4327ccf8`) | **Этап 3** — add/remove ноды на лету, адрес `proc.worker`, консистентность полукадров |

### Точечные fix
| План | Статус | Суть |
|------|--------|------|
| [sql-insert-many-atomic](2026-06-05_sql-insert-many-atomic.md) | DRAFT | Атомарный + батчевый `insert_many` в `Services/sql` (`executemany` + 1 commit вместо per-row) |

### Транспорт / comm-system (стратегические; P0 закрыт)
| План | Статус | Осталось |
|------|--------|----------|
| [transport-router-hub](2026-05-31_transport-router-hub/) | P0-P2 **DONE** (гибрид: кадры-трубы, команды-почта) | P3/P4 — kind-каналы (= comm-system P1/P2), отложены ради pipeline-направления |
| [comm-system-target-architecture](comm-system-target-architecture.md) | мастер-план; §11 P0 **закрыт весь** | P1/P2 (kind-каналы, авто-reply/undo, carve-out). Спутники: [audit](comm-system-communication-audit.md), [REVIEW](comm-system-target-architecture.REVIEW.md) |
| [comm-system-execution-order](comm-system-execution-order.md) | S0/S1/S3 **DONE** | **S2** (merge ветки в main, ~303 коммита, FF-возможен) → **S4** → **S5** |
| [backend-control-mcp](2026-05-31_backend-control-mcp/plan.md) | P1.x в работе (fire-and-forget дыры закрыты) | P1.5b — дизайн-док стрима логов через router → ревью → код |

---

## 🧊 Отложено (deferred — ждут gate/решения владельца)

| План | Почему отложен |
|------|----------------|
| [constructor-maturity](2026-05-29_constructor-maturity/plan.md) | DETAILED, P1.1 audit **DONE** (вердикт A). Ждёт approval. Владелец: **product > engine** — constructor-зрелость отложена |
| [telemetry-delivery-simplification](telemetry-delivery-simplification.md) | DEFERRED (Option D). Видимый баг «—» решён иначе (self-publish). Ждёт реального масштаба (2-й реактивный потребитель) |
| [prototype-carveout](prototype-carveout.md) | Handoff. Частично поглощён recipe-orchestrator-unify Phase 5 (carve-out как forcing function) |
| [pipeline-color-inspection](pipeline-color-inspection.md) | НЕ начат. Отложено (2026-06-07): атомарные плагины цвет-инспекции (`hsv_mask`→`contour_finder`, painter отдельным процессом) + universal Modbus-пакет |

---

## 📦 Backlog

- [ULTRACODE_BACKLOG](ULTRACODE_BACKLOG.md) — fan-out-friendly задачи под мульти-агентный ultracode-залп (§11 quick-wins, потеря сообщений в `_route_to_worker`, RolesPanel/get_field).

---

## ✅ Заархивировано в этой чистке (2026-06-07)

- `recipe-v3-engine-decouple` — корень порчи v3-рецептов устранён (`6d5b90df`)
- `replace-blueprint-hotswap` — Task 1-7 **DONE** (двухфазная регистрация `5cd23192`)
- `frames-blocker-hotswap-resource-release` — блокер кадров решён (`5cd23192`)
- `recipe-topology-architecture-analysis` — анализ поглощён планом unify
- `observability-control-plane/` — Phase 1-4 **DONE** (влито в main `d63bae62`)
- `telemetry-backend-control-HANDOFF` — устарел, телеметрия починена
- `command-result-bridge` — **DONE 2026-06-07** (P1-P3 verified; P4 закрыт по существу: FE-004 + memory вместо дубль-ADR); разблокировал lifecycle p4.4.4 + pipeline-live Этап 3
