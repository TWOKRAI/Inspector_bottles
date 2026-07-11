# Очередь планов — единая последовательность задач

> Обновлено **2026-07-11** (консолидация по команде владельца: всё готовое/поглощённое — в [`_archive/`](_archive/)).
>
> **Иерархия документов — 3 уровня, у каждого своя роль:**
>
> | Уровень | Документ | Роль |
> |---|---|---|
> | 1. Порядок | **этот файл** | ЧТО делаем и В КАКОЙ последовательности. Статусов задач здесь НЕТ |
> | 2. Исполнение | [`2026-07-06_constructor-master/`](2026-07-06_constructor-master/plan.md) | папка: мета-план (plan.md — детали задач, acceptance, **единственный источник статусов**) + файлы-детализации фаз (f3.x/f4.x/c6-design/…) |
> | 3. Стратегия | [`current-path/plan.md`](current-path/plan.md) | волны В0–В6, обоснование (ревью 2026-07-11), реестр NEW-задач, метрики пути |
>
> **Правило против дрейфа:** новые задачи вносятся в constructor-master; этот файл только упорядочивает и обновляется при закрытии блока (не каждой задачи).

## Сделано (свёрнуто; детали и merge-хэши — в constructor-master)

Ф0–Ф3 целиком · трек F (god-split F.1–F.7 + MERGE-GATE) · Ф4: 4.1/4.2/4.3/4.4/4.9 + добор H1–H8 · Ф5-ядро: 5.1/5.2/5.4–5.9/5.14–5.17/5.19–5.21 · Ф5-добор: C1/C2/C4/C5/C6(a,b,c)/C7 · post-review R1–R6 · NEW-2/NEW-3/NEW-5/NEW-8 · волны В0/В1 current-path (В1 — хвост ниже).

## Строгая последовательность (сверху вниз)

### Сейчас — хвост В1 (блокер всей recipe-оси)

| # | Задача | Где детали |
|---|---|---|
| 1 | ⛔ **Вердикт владельца: mini-GATE 4.8** — байт-diff канонизации рецептов подготовлен и ждёт | [f4.8-canonicalization-diff.md](2026-07-06_constructor-master/f4.8-canonicalization-diff.md) |
| 2 | **C3** — carve модуля `recipe`: yaml_io + assembler/planner + RecipeManager → framework | constructor-master, Ф5-добор |
| 3 | **4.7** — join/inspector из wires при assembly; снять `_hoist_inspector_from_metadata` | constructor-master, Ф4 |
| 4 | **C8** — docs-sync: карта модулей = код (chain-статус финализировать повторно после C6 d/e) | constructor-master, Ф5-добор |

### В2 — «РЫБА» (сердце цели; перед стартом — 3 вопроса скоупа 5.11 владельцу)

| # | Задача | Где детали |
|---|---|---|
| 5 | **5.11** — `app_module` skeleton + каркас `examples/minimal_app` + ManifestStore (NEW-1) + дискавери плагинов И сервисов | constructor-master, Ф5 + current-path В2 |
| 6 | **5.12** — `AppOrchestrator` generic + хук-точки двух сортов (state-bootstrap + display-reload) | constructor-master, Ф5 |
| 7 | **5.13** — minimal_app финализация + CI-smoke (инвариант 8 архитектуры) | constructor-master, Ф5 |

### В3 — GUI-конструктор (параллельно/после В2)

| # | Задача | Где детали |
|---|---|---|
| 8 | **NEW-D1 (= 5.10 S→M)** — механизм табов → frontend_module (TabRegistry; прототип = `TABS: list[TabSpec]`) | current-path §3-В3 |

### Хвост C-волны (по дизайну C6 — после 5.13, второй живой смок-детектор)

| # | Задача | Где детали |
|---|---|---|
| 9 | **C6(d)** — generic-механика на runnables `chain_module` (DAG/parallel — chain перестаёт дремать) | [c6-pipeline-engine-design.md](2026-07-06_constructor-master/c6-pipeline-engine-design.md) |
| 10 | **C6(e)** — chain использует пул `worker_module` | там же |

### В4 — Ф7 hot-path (строго одним вскрытием, один агент; GATE G3 перед стартом)

| # | Задача | Где детали |
|---|---|---|
| 11 | **G.6** — trace-id/OTel-поля (первым: семантика, не hot-path-риск) | constructor-master, Ф7 |
| 12 | **G.1** — снять TRACE + perf-пробы + повторный baseline | там же |
| 13 | **G.2** — характеризационные тесты доставки + kind-каналы + единый конверт команд | там же |
| 14 | **G.3** — FrameShm: одна стратегия записи + seqlock + startup-cleanup SHM | там же |
| 15 | **G.4** — QoS-профили kind + боевой RingBuffer (поглощает 3.3-остаток и QoS live-tail 5.21d) | там же |
| 16 | **G.5** — снятие двойной конверсии (строго после seqlock) | там же |
| 17 | **G.7** — приёмка: flip `use_kind_channels`, soak, FPS/p99 ≥ baseline | там же |
| 18 | **G.8** — drain→detach→stop воркера (поглощает pipeline-live-control Task 3.3) | там же |

### В5 — Supervision-tree + Ф8

| # | Задача | Где детали |
|---|---|---|
| 19 | **3.9** — depends_on: порядок старта по readiness апстрима (поднято из «опц» в обязательное — предусловие Ф8) | constructor-master, Ф3 + current-path В5 |
| 20 | **NEW-6** — стратегии супервизора (rest_for_one/one_for_all, группы, backoff+jitter, эскалация give-up) | current-path §4 |
| 21 | **NEW-7** — alerting поверх supervisor-событий (gave_up/failed/drop-растёт → громко) | current-path §4 |
| 22 | **H.1** — ярусы core/optional/frozen + enforcement + **NEW-10** (24/24 interfaces.py, Protocol ObservableMixin, «один вход», contract-тест `__all__`) | constructor-master, Ф8 |
| 23 | **H.2 (GATE G4)** — исполнение kill-вердиктов G0 per-item, отдельными одобренными коммитами | там же |
| 24 | **H.3** — Registers⇄StateStore merge (с оглядкой на 3 оси ADR-COMM-006) | там же |
| 25 | **H.4** — один стандарт логирования прототипа | там же |
| 26 | **H.5** — ужесточение sentrux + разбор complex functions + перекалибровка метрик приёмки (вопрос R5c) | там же |
| 27 | **H.6** — финальная сверка, закрытие constructor-master | там же |

### В6 — Конструктор v1.0 (финал)

| # | Задача | Где детали |
|---|---|---|
| 28 | **NEW-9** — packaging: тяжёлые deps → extras → env-алиасы `MPF_*` → свой pyproject у framework | current-path §4/В6 |
| 29 | **NEW-4** — симметрия ресурсов плагина (configure↔shutdown контракт-тест, SHM owner-теги) | current-path §4 |
| 30 | **Туториал «своё приложение за час»** + scaffold-генератор (5.14опц) | current-path В6 |
| 31 | 🏁 **Финальная приёмка: второе продуктовое приложение из «рыбы» за день** + 6 тестов architecture-10-of-10 §0 | [architecture-10-of-10.md](current-path/architecture-10-of-10.md) |

### Опциональные (решаются по ходу, вне строгого порядка)

1.8 record/replay (решение на GATE G3) · 2.6 JSONL-sink · 4.10 driver watch-from-revision · 3.10 stop/start воркера (drain-часть уже в G.8) · 5.18 depth-reduction (**отложено владельцем** до sentrux Pro root-cause; порог 0.57 до H.5).

## Открытые решения владельца

| # | Решение | Что блокирует |
|---|---|---|
| 1 | **Вердикт mini-GATE 4.8** (байт-diff готов) | шаги 2–4 (C3 → recipe-ось) |
| 2 | **3 вопроса скоупа 5.11** (дискавери сервисов: маркер-файл?; GUI-часть рыбы отдельно?; minimal_app headless-only?) | старт В2 (шаг 5) |
| 3 | current-path §5: формальное одобрение Master plan; ранний вынос frozen-boundaries из H.1; R2-residual (гейт `recovered` на `health.status==ok`) | формально (В1 де-факто исполнен) |
| 4 | Снятие blueprint-шима C6(c) — 0 импортёров | нет (гигиена) |

## Отложено / hardware-gated (вне последовательности)

| План | Статус | Осталось |
|------|--------|----------|
| [constructor-maturity](2026-05-29_constructor-maturity/plan.md) | **Отложено владельцем** (product > engine) | P1.2+ |
| [sql-insert-many-atomic](2026-06-05_sql-insert-many-atomic.md) | DRAFT, не начат | атомарный/батчевый `insert_many` |
| [pipeline-color-inspection](pipeline-color-inspection.md) | **Отложено владельцем** | атомарные плагины цвет-инспекции |
| [telemetry-delivery-simplification](telemetry-delivery-simplification.md) | **DEFERRED (Option D)** | ждёт 2-го реактивного потребителя |
| [device-tree-recipe](device-tree-recipe.md) | Фаза D DONE | Фаза E частично — ждёт go-ahead владельца |
| [camera-robot-calibration](camera-robot-calibration.md) | Часть 1 закрыта | Часть 2 (px→mm) — железо |
| [dataset-circle-capture](dataset-circle-capture.md) | Часть 1 готова | Часть 2 (hand-eye) — отдельная ветка |
| [robot-calibration](robot-calibration.md) | Частично | многофазная калибровка, hardware E2E |
| [robot-place-pose](robot-place-pose.md) | P1+P2 DONE | P3 + прошивка робота |
| [word-layout](word-layout.md) | Phase 1-2 DONE | Phase 3-4, live-smoke на стенде |
| [pult-control-panel](pult-control-panel.md) | Phase 1-3, 5.1-5.3/5.5 DONE | 5.4 отложен; Phase 4 (доки) |
| [letter-robot-cycle](letter-robot-cycle/) | Тракт распознавания DONE | цикл укладки→возврата |
| [draw-mode-rework](draw-mode-rework/) | A-D в основном DONE | **freeze** до железа |

## Архив

**Чистка 2026-07-11** (по команде владельца; всё в [`_archive/`](_archive/)):
- `master-rework-roadmap.md` — синтез 2026-06-18; поглощён constructor-master (K-таблица → вердикты G0; W7/W8 → Ф7)
- `2026-07-03_review-and-constructor-plan.md` — прежний governing, поглощён constructor-master
- `2026-07-03_god-split-design.md` — дизайн трека F; трек F закрыт целиком
- `2026-07-10_post-review-hardening.md` — ЗАКРЫТ 2026-07-11 (R1–R6 DONE; открытые вопросы переехали в H.5/H.1)
- `2026-06-06_recipe-orchestrator-unify.md` — Phase 1-4 DONE; Phase 5 = задача C3 constructor-master
- `2026-05-31_pipeline-live-control/` — Этапы 1-2 DONE; остаток = 3.10 (опц) + G.8 constructor-master (спека — `_archive/.../phase-3.md`)
- `2026-05-31_transport-router-hub/` — P0-P2 DONE; P3/P4 (kind-каналы) = Ф7 G.2–G.4
- `comm-system-*.md` (4 файла) — superseded ещё чисткой 2026-07-06, физически перенесены теперь
- `ULTRACODE_BACKLOG.md` — вердикт G0 №13 «архивировать» (владелец, 2026-07-06)

**Прежние волны:** чистка 2026-07-06 (16 планов: line-filter-virtual, pipeline-free-layout, topology-switch-hardening, dataset-gen-service, device-hub, ml-train-service, robot-vfd-services, displays-in-recipe, backend-control-mcp, recipe-format-single-source, prototype-carveout и др.) и чистка 2026-06-07 (recipe-v3-engine-decouple, replace-blueprint-hotswap, observability-control-plane и др.) — всё в [`_archive/`](_archive/).
