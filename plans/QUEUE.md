# Очередь планов

> Снимок на **2026-07-06** (обновлён в Ф0.6 constructor-master). Закрытые/устаревшие планы — в [`_archive/`](_archive/).

---

## 🧭 GOVERNING: constructor-master

**Действующий мастер-план:** [`2026-07-06_constructor-master/plan.md`](2026-07-06_constructor-master/plan.md)
(фазы Ф0-Ф8 + трек F; исполнение начато 2026-07-06, ветка `fix/constructor-f0`).
Он поглощает и упорядочивает: волны C-G роадмапа, god-split (трек F), recipe-orchestrator
Phase 5 (Ф5.3), pipeline-live-control Этап 3 (Ф3.10/G.8), kind-каналы (Ф7), carve E (Ф5),
app_module «рыба» ([app-template-idea.md](2026-07-06_constructor-master/app-template-idea.md)).

Прежние синтез-документы — теперь **исторический контекст** (сверяться при конфликте статусов,
но governing — constructor-master):

| Документ | Роль |
|----------|------|
| [2026-07-06_constructor-master](2026-07-06_constructor-master/plan.md) | **GOVERNING** — фазы Ф0-Ф8, gates G0-G4, метрики приёмки |
| [master-rework-roadmap](master-rework-roadmap.md) | Синтез 6 измерений (2026-06-18); K-таблица §6 — источник вердиктов G0 |
| [2026-07-03_review-and-constructor-plan](2026-07-03_review-and-constructor-plan.md) | Прежний governing (волны A-G) — поглощён constructor-master |
| [2026-07-03_god-split-design](2026-07-03_god-split-design.md) | Дизайн трека F — исполняется внутри constructor-master |

**Аудит затрёкен:** [`docs/audits/2026-07-04_arch-advice-constructor-2026.md`](../docs/audits/2026-07-04_arch-advice-constructor-2026.md)
(52 рекомендации P0-P4) — triage в [`2026-07-06_constructor-master/audit-triage.md`](2026-07-06_constructor-master/audit-triage.md)
(Ф0.6): каждая рекомендация → фаза/gate/отклонено-с-причиной. Дыра «ни один план не ссылается» закрыта.

---

## 📋 В очереди (partial / deferred / active)

### Рецепты / recipe-orchestrator
| План | Статус | Осталось |
|------|--------|----------|
| [recipe-orchestrator-unify](2026-06-06_recipe-orchestrator-unify.md) | Phase 1-4 **DONE** | **Phase 5 фактически поглощена задачей C3** ([`2026-07-06_constructor-master/plan.md`](2026-07-06_constructor-master/plan.md), Ф5-добор — `yaml_io`+assembler/planner+RecipeManager → модуль `recipe`); reverse-import блокер снят C1 (модуль recipe через Protocol, 0 reverse-import); C3 сейчас блокирован порядком C2→4.8→C3 (ждёт вердикта владельца по mini-GATE 4.8) |

### Pipeline / live-control
| План | Статус | Осталось |
|------|--------|----------|
| [pipeline-live-control](2026-05-31_pipeline-live-control/) | Этап 1-2 **DONE** | **Этап 3** — add/remove ноды на лету, адрес `proc.worker`, консистентность полукадров |
| [transport-router-hub](2026-05-31_transport-router-hub/) | P0-P2 **DONE** (гибрид: кадры-трубы, команды-почта) | P3/P4 — kind-каналы (= волна G роадмапа) |

### Устройства / калибровка (частично hardware-gated)
| План | Статус | Осталось |
|------|--------|----------|
| [device-tree-recipe](device-tree-recipe.md) | Фаза D **DONE** | Фаза E частично (README+conn-индикатор done; остальное ждёт go-ahead владельца) |
| [camera-robot-calibration](camera-robot-calibration.md) | Часть 1 закрыта | Часть 2 (px→mm), Ф7 — железо |
| [dataset-circle-capture](dataset-circle-capture.md) | Часть 1 (pipeline) готова | Часть 2 (hand-eye calibration) на отдельной ветке |
| [robot-calibration](robot-calibration.md) | Частично (пересекается с camera-robot-calibration — уточнить) | Многофазная калибровка, hardware E2E |
| [robot-place-pose](robot-place-pose.md) | P1+P2 **DONE** (116 тестов) | P3 (съём↔укладка) + прошивка робота |
| [word-layout](word-layout.md) | Phase 1-2 **DONE** | Phase 3 частично, Phase 4; live-smoke на стенде — hardware-pending |
| [pult-control-panel](pult-control-panel.md) | Phase 1-3, 5.1-5.3/5.5 **DONE** | 5.4 (монитор) отложен; Phase 4 (README/STATUS + memory) |
| [letter-robot-cycle](letter-robot-cycle/) | Тракт распознавания **DONE** | Цикл укладки→возврата — в процессе (Tasks 1.1-1.5, 2.1) |
| [draw-mode-rework](draw-mode-rework/) | Этапы A-D в основном **DONE** (9/13 пунктов) | Остаток hardware-pending — **freeze**, не трогать до железа (роадмап §7 rank 8) |

### Точечные fix
| План | Статус | Суть |
|------|--------|------|
| [sql-insert-many-atomic](2026-06-05_sql-insert-many-atomic.md) | DRAFT, не начат | Атомарный + батчевый `insert_many` в `Services/sql` |
| [pipeline-color-inspection](pipeline-color-inspection.md) | **Отложено владельцем** | Атомарные плагины цвет-инспекции (hsv_mask→contour_finder) + universal Modbus-пакет |
| [telemetry-delivery-simplification](telemetry-delivery-simplification.md) | **DEFERRED (Option D)** | Видимый баг решён иначе (self-publish); ждёт 2-го реактивного потребителя |
| [constructor-maturity](2026-05-29_constructor-maturity/plan.md) | DETAILED, P1.1 audit DONE | **Отложено владельцем**: product > engine прямо сейчас |

---

## 📦 Backlog

- [ULTRACODE_BACKLOG](ULTRACODE_BACKLOG.md) — fan-out-задачи под мульти-агентный залп. **Ревалидировать перед запуском** — часть источников (§11 P0, старый telemetry HANDOFF) уже архивирована.

---

## ✅ Заархивировано в чистке 2026-07-06 (16 планов)

Признаны **FULLY DONE** или **SUPERSEDED** более новыми синтез-документами (master-rework-roadmap / review-and-constructor-plan). Подробности и обоснование по каждому — в истории чата/памяти сессии архивации.

**Fully done:**
- `2026-06-08_line-filter-virtual.md`, `2026-06-08_pipeline-free-layout.md`
- `2026-07-04_topology-switch-hardening.md` (7/7 задач)
- `dataset-gen-service.md`, `device-hub.md` (software; hardware-верификация — единственный незакрытый пункт), `ml-train-service.md`, `robot-vfd-services.md` (software)
- `displays-in-recipe/` (reviewer Opus APPROVED)
- `2026-05-31_backend-control-mcp/` (P0-P2 DONE)

**Superseded** (поглощены/переоценены более новыми документами):
- `comm-system-communication-audit.md`, `comm-system-execution-order.md`, `comm-system-target-architecture.md`, `comm-system-target-architecture.REVIEW.md` — AUDIT/CSA-семья систематически отстала от кода (см. master-rework-roadmap §1); живой статус теперь в роадмапе
- `2026-06-06_recipe-format-single-source.md` — T1 поглощён `displays-in-recipe` (DONE)
- `multiprocess-prototype-sparkling-lollipop.md`, `prototype-carveout.md` — carve-out теперь ведёт master-rework-roadmap §5 + review-and-constructor волна E

---

## Заархивировано в чистке 2026-06-07 (предыдущая волна)

- `recipe-v3-engine-decouple`, `replace-blueprint-hotswap`, `frames-blocker-hotswap-resource-release`, `recipe-topology-architecture-analysis`, `observability-control-plane/`, `telemetry-backend-control-HANDOFF`, `command-result-bridge`
