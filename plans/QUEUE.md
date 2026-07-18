# Очередь планов — единая последовательность задач

> Обновлено **2026-07-13** (**C-волна закрыта целиком**: C6(d) движок на ChainRunnable merge 22393392, C6(e) пул на worker_module merge — оба через Fable-ревью 8 углов; RS-7-остаток `workers`→рантайм оказался отдельной задачей (семантика WorkerSpec-тредов, не chain-пула) — в «Открытых решениях владельца»; попутно закрыт регресс RS-4 в layer-контракте merge d5c68d1b; ранее в тот же день — RS-волна целиком: RS-2+RS-3 71d3b479, RS-6+RS-5 7e77e9aa, RS-4 a42747be, RS-7 решение владельца; NEW-D1 bcabd296. Фронт → В4 Ф7 (GATE G3), В3 GUI-конструктор — по решению владельца).
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

Ф0–Ф3 целиком · трек F (god-split F.1–F.7 + MERGE-GATE) · Ф4: 4.1/4.2/4.3/4.4/4.7/4.8/4.9 + добор H1–H8 · Ф5-ядро: 5.1/5.2/5.4–5.9/5.14–5.17/5.19–5.21 · Ф5-добор: C1/C2/C3/C4/C5/C6(a,b,c)/C7/C8 · post-review R1–R6 · NEW-2/NEW-3/NEW-5/NEW-8 · волны В0/В1 current-path целиком (хвост В1 — mini-GATE 4.8 вердикт владельца, C3 carve `recipe`, 4.7 join/inspector ADR-PMM-017, C8 docs-sync карты модулей — закрыт 2026-07-12; chain-статус в картах модулей отражает состояние ДО C6(d)/(e) — финализировать повторно после них) · **В2 «РЫБА» целиком** (5.11 app_module skeleton + ManifestStore/дискавери, 5.12 AppOrchestrator generic + хуки двух сортов, 5.13 minimal_app финализация + CI-smoke — 2-й процесс + живой IPC + sentrux-boundary — закрыт 2026-07-12) · **Follow-up аудита В1** (AU-1 Save-канонизатор `gui_positions` + AU-2 escape-hatch `inspector`/`restart_policy` через typed/extras, миноры AU-3/4/5/7 — merges 7526a7bc + a1150d26 через Fable-ревью, закрыт 2026-07-12; **AU-6 остался** — попутно с физпереносом assembler/planner, ADR-RCP-005; хвост AU-5: `test_discovery.py` прямой `_plugins` — попутно с app_module) · **RS-1** единый Save-механизм (merge ad3c03ca, 2026-07-12) · **RS-2+RS-3** честный state после switch + громкий switch (merge 71d3b479, 2026-07-13: Ж-3 конверт state.merge, B-4 cleanup-хвост, B-5 list-алиас, pid+config в state на boot/switch/restart, B-2 protected=реальные выжившие, B-3 unstoppable alert+retry, Ж-4 confirmed-death shutdown, Ж-5 priority-дедуп) · **NEW-D1** TabRegistry во frontend_module (merge bcabd296) · **RS-6+RS-5** контракт фейков + валидация на записи + Displays-устойчивость (merge 7e77e9aa, 2026-07-13: реестр 11 фейков, Save/load-gate циклы/дубли, boot-контракт check() не расширен, легаси-рецепт не роняет Дисплеи read+write) · **RS-4** dirty-контур редактора (merge a42747be, 2026-07-13: TopologySession dirty+diverged, диалог Сохранить/Не сохранять/Отмена на активации+закрытии+UI-рестарте, diverged по подтверждённому apply, единый Save-путь ×3) · **RS-7** решение владельца 2026-07-13 (workers→рантайм с C6(e), active_services→freeze; пометки в схеме) — **RS-волна закрыта** · **C6(d)** движок pipeline на ChainRunnable (merge 22393392, 2026-07-13: адаптер PluginOperationStep через PluginRunner, SuspectTagStep per-position, бюджет границ в acceptance + контракт-тест «цепочка без IPC между звеньями», ADR-PM-015; Fable-ревью 1 HIGH+3 MED+2 LOW исправлены) · **C6(e)** пул chain на worker_module (merge 2026-07-13: WorkerPoolExecutor, ThreadPoolExecutor grep=0 — D2 закрыт, стоп-механика сентинелы+cancel+честный wait=True, ADR-CHN-009; Fable-ревью 2 итерации; RS-7-остаток workers→рантайм = отдельная задача, см. «Открытые решения») · **фикс регресса RS-4** layer-контракт test_runtime_deps (merge d5c68d1b) — **C-волна закрыта целиком, C6 [x]**.

## Строгая последовательность (сверху вниз)

### Сейчас — В4 Ф7 hot-path (строго одним вскрытием, один агент; GATE G3 закрыт 2026-07-13; преамбула Ф7 — 3 требования перф-ревью 2026-07-12)

**C-волна ЗАКРЫТА 2026-07-13 целиком** (C1-C8, включая C6(d)/(e) — детали и merge-хэши в constructor-master). **GATE G3 ЗАКРЫТ владельцем 2026-07-13: старт Ф7 — ДА.** Вердикты: 1.8 record/replay — пропустить (остаётся опц); [frame-pool](2026-07-06_constructor-master/frame-pool-idea.md) — одобрен как дизайн-вход G.3/G.4 (внесён в acceptance; + аналоги индустрии iceoryx2/GStreamer/GenTL; + принцип 6: камер 2–3+, у каждой своя цепочка → пулы per-camera с изоляцией); baseline G.1 — лесенкой (синтетика → вебкамера → Hikvision, G.7 сравнивает same-tier); B-6..B-9 + HP-5-репродьюсер внесены в G.3/G.4 (RS→Ф7 закрыт).

| # | Задача | Где детали |
|---|---|---|
| 7 | **G.6** — trace-id/OTel-поля (первым: семантика, не hot-path-риск) + runtime-счётчик границ процесса на кадр | constructor-master, Ф7 |
| 8 | **G.1** — снять TRACE + perf-пробы + повторный baseline (FPS, p50/p99, **хопы/кадр**) | там же |
| 9 | **G.2** — характеризационные тесты доставки + kind-каналы + единый конверт команд | там же |
| 10 | **G.3** — FrameShm: одна стратегия записи + seqlock + startup-cleanup SHM + **громкий pickle-fallback (d)** | там же |
| 11 | **G.4** — QoS-профили kind + боевой RingBuffer (поглощает 3.3-остаток и QoS live-tail 5.21d) | там же |
| 12 | **G.5** — снятие двойной конверсии (строго после seqlock) | там же |
| 13 | **G.9** — GC-дисциплина: `gc.freeze()` + сборка по расписанию; per-frame путь без Pydantic (msgspec/dict, стык с TECH_STACK Волна 1); строго после G.5 | там же |
| 14 | **G.7** — приёмка: flip `use_kind_channels`, soak, FPS/p99 ≥ baseline, p99 без GC-выбросов | там же |
| 15 | **G.8** — drain→detach→stop воркера (поглощает pipeline-live-control Task 3.3) | там же |

### В5 — Supervision-tree + Ф8

| # | Задача | Где детали |
|---|---|---|
| 16 | **3.9** — depends_on: порядок старта по readiness апстрима (поднято из «опц» в обязательное — предусловие Ф8) | constructor-master, Ф3 + current-path В5 |
| 17 | **NEW-6** — стратегии супервизора (rest_for_one/one_for_all, группы, backoff+jitter, эскалация give-up) | current-path §4 |
| 18 | **NEW-7** — alerting поверх supervisor-событий (gave_up/failed/drop-растёт/**pickle-fallback G.3(d)** → громко) | current-path §4 |
| 19 | **H.1** — ярусы core/optional/frozen + enforcement + **NEW-10** (24/24 interfaces.py, Protocol ObservableMixin, «один вход», contract-тест `__all__`) | constructor-master, Ф8 |
| 20 | **H.2 (GATE G4)** — исполнение kill-вердиктов G0 per-item, отдельными одобренными коммитами | там же |
| 21 | **H.3** — Registers⇄StateStore merge (с оглядкой на 3 оси ADR-COMM-006) | там же |
| 22 | **H.4** — один стандарт логирования прототипа | там же |
| 23 | **H.5** — ужесточение sentrux + разбор complex functions + перекалибровка метрик приёмки (вопрос R5c) | там же |
| 24 | **H.6** — финальная сверка, закрытие constructor-master | там же |

### В6 — Конструктор v1.0 (финал)

| # | Задача | Где детали |
|---|---|---|
| 25 | **NEW-9** — packaging: тяжёлые deps → extras → env-алиасы `MPF_*` → свой pyproject у framework (стык с TECH_STACK §11 чистка pyproject) | current-path §4/В6 |
| 26 | **NEW-4** — симметрия ресурсов плагина (configure↔shutdown контракт-тест, SHM owner-теги) | current-path §4 |
| 27 | **Туториал «своё приложение за час»** + scaffold-генератор (5.14опц) | current-path В6 |
| 28 | 🏁 **Финальная приёмка: второе продуктовое приложение из «рыбы» за день** + 6 тестов architecture-10-of-10 §0 | [architecture-10-of-10.md](current-path/architecture-10-of-10.md) |

### Параллельный трек — TECH_STACK 2026 (вне строгой последовательности конструктора)

Стратегия нативного стека — [`docs/direction/TECH_STACK_2026.md`](../docs/direction/TECH_STACK_2026.md) (живой документ, 2026-07-12). Волна 1 (2026 H2, каждый пункт — отдельный план): чистка pyproject (10 мёртвых core-deps) → bump Python 3.13 → `Services/analytics` (Polars) → msgspec на границах (стык с G.9/G.2) → ORT автодетект EP → Rerun dev-extra → пилот PySide6 6.11 → ADR лицензий моделей. Пункты, пересекающиеся с hot-path (msgspec на IPC-пути, бенч msgspec-vs-pickle), — исполнять В СОСТАВЕ Ф7 (G.2/G.9), не отдельно (принцип «одним вскрытием»); остальное (deps, analytics, Rerun, лицензии) — независимо, можно между волнами.

### Параллельный трек — frontend-constructor (исполнение В3 ось NEW-D)

План [`frontend-constructor/plan.md`](frontend-constructor/plan.md) — выделение фронт-конструктора из прототипа во фреймворк (поглощает NEW-D2/`proto-frontend-carve` → SUPERSEDED). **Блок А (Ф0 docs → Ф1 гигиена frontend_module → Ф2 граница фронт/бэк) — parallel-safe ДО codemod layer-grouping**, самодостаточен. Блок В (Ф3+ промоушены) — ПОСЛЕ codemod. Инвариант: кодовые фазы никогда не параллельны Фазе 3-codemod (freeze-окно). Старт Блока А — 2026-07-18.

### Опциональные (решаются по ходу, вне строгого порядка)

1.8 record/replay (решение на GATE G3) · 2.6 JSONL-sink · 4.10 driver watch-from-revision · 3.10 stop/start воркера (drain-часть уже в G.8) · 5.18 depth-reduction (**отложено владельцем** до sentrux Pro root-cause; порог 0.57 до H.5) · LP-1..LP-5 (находки живого прогона 2026-07-12, constructor-master «Живой прогон»; LP-1 name/description — кандидат на быстрый фикс до В3).

## Открытые решения владельца

| # | Решение | Что блокирует |
|---|---|---|
| 1 | **Байт-diff канонизации 2 оставшихся рецептов** (`camera_robot_calibration.yaml` −31, `dataset_circle_capture.yaml` — YAML-алиас) — тот же дубль `gui_positions`, что и в 4.8, обнаружен при apply, ещё не одобрен | нет (гигиена; 4.8 применена к 2 одобренным рецептам, C3 разблокирован) |
| 2 | ~~3 вопроса скоупа 5.11~~ — **решено владельцем 2026-07-11:** дискавери сервисов — маркер-файл `service.yaml`; GUI-часть «рыбы» — отдельно от headless-ядра; `minimal_app` — headless-only | нет (снято; блокер В2 снят, старт открыт) |
| 3 | current-path §5: формальное одобрение Master plan; ранний вынос frozen-boundaries из H.1; R2-residual (гейт `recovered` на `health.status==ok`) | формально (В1 де-факто исполнен) |
| 4 | Снятие blueprint-шима C6(c) — 0 импортёров | нет (гигиена) |
| 5 | **Доводка `Process.workers`→рантайм (RS-7-остаток)** — разведка C6(e) 2026-07-13: поле = `tuple[WorkerSpec]` (декларативные именованные треды процесса), НЕ chain-пул; нужны адаптер формата + проброс через ассемблер + решение: спавнить ли idle-треды без Pipeline-нагрузки (сейчас спавн = no-op треды). Пометка «пока не влияет» в схеме стоит | нет (отдельная задача; поле честно помечено) |
| 6 | ~~GATE G3 перед Ф7~~ — **ЗАКРЫТ владельцем 2026-07-13**: старт Ф7 ДА; frame-pool одобрен (в acceptance G.3/G.4); 1.8 пропустить; baseline лесенкой | нет (снято; В4 Ф7 стартован) |

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
