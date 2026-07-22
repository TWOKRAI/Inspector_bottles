# Очередь планов — единая последовательность задач

> **Обновлено 2026-07-22 — синхронизация трека backend_ctl.** `backend-ctl-proof-discipline` ЗАКРЫТ и слит в main (ff до `9a0f4137`); активным планом инструмента стал преемник `truth-holes-closure` (gui-шторм + правда инструмента). `transport-single-policy` внесён строкой (активен, после truth-holes). См. таблицу трека ниже.
>
> **Обновлено 2026-07-20 — гигиена статусов.** Файл простоял без правок с 2026-07-13, за это время в `main` уехали: **Ф7 почти целиком** (G.8/G.9/G.H/G.F закрыты, G.7 в работе — Фазы 0-1 пройдены), **frontend-constructor Блок А целиком**, **layer-grouping Фаза 2 частично** и **целый параллельный трек backend_ctl + телеметрии**, которого в этом файле не было вовсе. Всё сверено по git, не по памяти. Ниже — актуальный порядок.
>
> Предыдущая запись (2026-07-13, C-волна закрыта целиком: C6(d) движок на ChainRunnable merge 22393392, C6(e) пул на worker_module merge — оба через Fable-ревью 8 углов; RS-7-остаток `workers`→рантайм оказался отдельной задачей (семантика WorkerSpec-тредов, не chain-пула) — в «Открытых решениях владельца»; попутно закрыт регресс RS-4 в layer-контракте merge d5c68d1b; ранее в тот же день — RS-волна целиком: RS-2+RS-3 71d3b479, RS-6+RS-5 7e77e9aa, RS-4 a42747be, RS-7 решение владельца; NEW-D1 bcabd296. Фронт → В4 Ф7 (GATE G3), В3 GUI-конструктор — по решению владельца).
>
> **Иерархия документов — 3 уровня, у каждого своя роль:**
>
> | Уровень | Документ | Роль |
> |---|---|---|
> | 1. Порядок | **этот файл** | ЧТО делаем и В КАКОЙ последовательности + **крупноблочный статус** (закрыт блок / в работе / не начат). Пер-задачных статусов здесь нет — они в constructor-master |
> | 2. Исполнение | [`2026-07-06_constructor-master/`](2026-07-06_constructor-master/plan.md) | папка: мета-план (plan.md — детали задач, acceptance, **единственный источник статусов**) + файлы-детализации фаз (f3.x/f4.x/c6-design/…) |
> | 3. Стратегия | [`current-path/plan.md`](current-path/plan.md) | волны В0–В6, обоснование (ревью 2026-07-11), реестр NEW-задач, метрики пути |
>
> **Правило против дрейфа:** новые задачи вносятся в constructor-master; этот файл только упорядочивает и обновляется при закрытии блока (не каждой задачи).
>
> **Урок 2026-07-20:** правило выше не сработало — файл отстал на неделю, и в нём не оказалось целого трека (backend_ctl + телеметрия), потому что тот шёл не из constructor-master, а отдельными планами. **Дополнение к правилу: любой план, живущий дольше одного дня, обязан иметь строку в этом файле — даже если он вне волн В0–В6.** Иначе следующий заход планируется по неполной картине.

## Сделано (свёрнуто; детали и merge-хэши — в constructor-master)

Ф0–Ф3 целиком · трек F (god-split F.1–F.7 + MERGE-GATE) · Ф4: 4.1/4.2/4.3/4.4/4.7/4.8/4.9 + добор H1–H8 · Ф5-ядро: 5.1/5.2/5.4–5.9/5.14–5.17/5.19–5.21 · Ф5-добор: C1/C2/C3/C4/C5/C6(a,b,c)/C7/C8 · post-review R1–R6 · NEW-2/NEW-3/NEW-5/NEW-8 · волны В0/В1 current-path целиком (хвост В1 — mini-GATE 4.8 вердикт владельца, C3 carve `recipe`, 4.7 join/inspector ADR-PMM-017, C8 docs-sync карты модулей — закрыт 2026-07-12; chain-статус в картах модулей отражает состояние ДО C6(d)/(e) — финализировать повторно после них) · **В2 «РЫБА» целиком** (5.11 app_module skeleton + ManifestStore/дискавери, 5.12 AppOrchestrator generic + хуки двух сортов, 5.13 minimal_app финализация + CI-smoke — 2-й процесс + живой IPC + sentrux-boundary — закрыт 2026-07-12) · **Follow-up аудита В1** (AU-1 Save-канонизатор `gui_positions` + AU-2 escape-hatch `inspector`/`restart_policy` через typed/extras, миноры AU-3/4/5/7 — merges 7526a7bc + a1150d26 через Fable-ревью, закрыт 2026-07-12; **AU-6 остался** — попутно с физпереносом assembler/planner, ADR-RCP-005; хвост AU-5: `test_discovery.py` прямой `_plugins` — попутно с app_module) · **RS-1** единый Save-механизм (merge ad3c03ca, 2026-07-12) · **RS-2+RS-3** честный state после switch + громкий switch (merge 71d3b479, 2026-07-13: Ж-3 конверт state.merge, B-4 cleanup-хвост, B-5 list-алиас, pid+config в state на boot/switch/restart, B-2 protected=реальные выжившие, B-3 unstoppable alert+retry, Ж-4 confirmed-death shutdown, Ж-5 priority-дедуп) · **NEW-D1** TabRegistry во frontend_module (merge bcabd296) · **RS-6+RS-5** контракт фейков + валидация на записи + Displays-устойчивость (merge 7e77e9aa, 2026-07-13: реестр 11 фейков, Save/load-gate циклы/дубли, boot-контракт check() не расширен, легаси-рецепт не роняет Дисплеи read+write) · **RS-4** dirty-контур редактора (merge a42747be, 2026-07-13: TopologySession dirty+diverged, диалог Сохранить/Не сохранять/Отмена на активации+закрытии+UI-рестарте, diverged по подтверждённому apply, единый Save-путь ×3) · **RS-7** решение владельца 2026-07-13 (workers→рантайм с C6(e), active_services→freeze; пометки в схеме) — **RS-волна закрыта** · **C6(d)** движок pipeline на ChainRunnable (merge 22393392, 2026-07-13: адаптер PluginOperationStep через PluginRunner, SuspectTagStep per-position, бюджет границ в acceptance + контракт-тест «цепочка без IPC между звеньями», ADR-PM-015; Fable-ревью 1 HIGH+3 MED+2 LOW исправлены) · **C6(e)** пул chain на worker_module (merge 2026-07-13: WorkerPoolExecutor, ThreadPoolExecutor grep=0 — D2 закрыт, стоп-механика сентинелы+cancel+честный wait=True, ADR-CHN-009; Fable-ревью 2 итерации; RS-7-остаток workers→рантайм = отдельная задача, см. «Открытые решения») · **фикс регресса RS-4** layer-контракт test_runtime_deps (merge d5c68d1b) — **C-волна закрыта целиком, C6 [x]**.

## Строгая последовательность (сверху вниз)

### Сейчас — В4 Ф7 hot-path: **остался только G.7 (soak + приёмка + флип дефолтов)**

**Ф7 почти закрыта.** ЗАКРЫТЫ и в `main`: **G.1, G.2, G.3, G.4, G.5, G.6** (2026-07-13/14) · **G.8, G.9, G.H** Этапы 1+2 — merge `baff5f0a` 2026-07-15 с финальным ревью фазы G **APPROVE 8.0/10** (фиксы `0a7f16a6`) · **G.F** реестр из 18 feature-флагов (`c078fbc2`).

**G.7 — [~] единственная незакрытая, ход на 2026-07-16** (детали и числа — [g7-flip-plan.md](2026-07-06_constructor-master/g7-flip-plan.md)):

| Фаза G.7 | Статус |
|---|---|
| Фаза 0 — прекондиции | ✅ |
| Фаза 1 — лесенка per-flag | ✅ **закрыта целиком**: 9 флагов флипнуты по одному с замером (receive p99 0.123→0.001; torn=0; restore p99 1.4→0.16 ≈8.5×) |
| Фаза 2 — fault-инъекции | **частично**: 2.1 kill-9 читателя ✅, 2.2 kill-9 писателя ✅ частично, 2.5 teardown ✅ зафиксирован; **2.3 switch-probe и 2.4 slow-consumer — ⏳** |
| Фаза 3 — soak + приёмка | **фундамент ✅** (мультикамера на 2 синтетич. камерах, Join-фикс `83d7d48a`); **остаток — основная работа** |

**Остаток G.7 = следующий шаг В4:** soak ≥2ч × 2 рецепта → приёмка (FPS/p99 ≥ baseline, socket backend_ctl жив, drop-счётчики видимы) → флип дефолтов в реестре G.F → замер потолка 50-60 fps.

**Историческая справка (GATE G3, 2026-07-13):** старт Ф7 одобрен владельцем; 1.8 record/replay — пропустить; [frame-pool](2026-07-06_constructor-master/frame-pool-idea.md) одобрен как дизайн-вход G.3/G.4; baseline лесенкой (синтетика → вебкамера → Hikvision, same-tier); B-6..B-9 + HP-5-репродьюсер внесены в G.3/G.4.

### В5 — Supervision-tree + Ф8

| # | Задача | Где детали |
|---|---|---|
| 1 | **3.9** — depends_on: порядок старта по readiness апстрима (поднято из «опц» в обязательное — предусловие Ф8) | constructor-master, Ф3 + current-path В5 |
| 2 | **NEW-6** — стратегии супервизора (rest_for_one/one_for_all, группы, backoff+jitter, эскалация give-up) | current-path §4 |
| 3 | **NEW-7** — alerting поверх supervisor-событий (gave_up/failed/drop-растёт/**pickle-fallback G.3(d)** → громко) | current-path §4 |
| 4 | **H.1** — ярусы core/optional/frozen + enforcement + **NEW-10** (24/24 interfaces.py, Protocol ObservableMixin, «один вход», contract-тест `__all__`) | constructor-master, Ф8 |
| 5 | **H.2 (GATE G4)** — исполнение kill-вердиктов G0 per-item, отдельными одобренными коммитами | там же |
| 6 | **H.3** — Registers⇄StateStore merge (с оглядкой на 3 оси ADR-COMM-006) | там же |
| 7 | **H.4** — один стандарт логирования прототипа | там же |
| 8 | **H.5** — ужесточение sentrux + разбор complex functions + перекалибровка метрик приёмки (вопрос R5c) | там же |
| 9 | **H.6** — финальная сверка, закрытие constructor-master | там же |

### В6 — Конструктор v1.0 (финал)

| # | Задача | Где детали |
|---|---|---|
| 10 | **NEW-9** — packaging: тяжёлые deps → extras → env-алиасы `MPF_*` → свой pyproject у framework (стык с TECH_STACK §11 чистка pyproject) | current-path §4/В6 |
| 11 | **NEW-4** — симметрия ресурсов плагина (configure↔shutdown контракт-тест, SHM owner-теги) | current-path §4 |
| 12 | **Туториал «своё приложение за час»** + scaffold-генератор (5.14опц) | current-path В6 |
| 13 | 🏁 **Финальная приёмка: второе продуктовое приложение из «рыбы» за день** + 6 тестов architecture-10-of-10 §0 | [architecture-10-of-10.md](current-path/architecture-10-of-10.md) |

### Параллельный трек — TECH_STACK 2026 (вне строгой последовательности конструктора)

Стратегия нативного стека — [`docs/direction/TECH_STACK_2026.md`](../docs/direction/TECH_STACK_2026.md) (живой документ, 2026-07-12). Волна 1 (2026 H2, каждый пункт — отдельный план): чистка pyproject (10 мёртвых core-deps) → bump Python 3.13 → `Services/analytics` (Polars) → msgspec на границах (стык с G.9/G.2) → ORT автодетект EP → Rerun dev-extra → пилот PySide6 6.11 → ADR лицензий моделей. Пункты, пересекающиеся с hot-path (msgspec на IPC-пути, бенч msgspec-vs-pickle), — исполнять В СОСТАВЕ Ф7 (G.2/G.9), не отдельно (принцип «одним вскрытием»); остальное (deps, analytics, Rerun, лицензии) — независимо, можно между волнами.

### Параллельный трек — frontend-constructor (исполнение В3 ось NEW-D)

План [`frontend-constructor/plan.md`](frontend-constructor/plan.md) — выделение фронт-конструктора из прототипа во фреймворк (поглощает NEW-D2/`proto-frontend-carve` → SUPERSEDED).

**Блок А ✅ ЗАКРЫТ 2026-07-19** (Ф0 `5307a2c2` → Ф1 фасад-флип, 5 коммитов → Ф2 `d6faaa80` граница фронт/бэк + headless-default). T2.5 опционален, пропущен; live headless-гейт T2.1 сознательно отложен.

✅ **Долг Ф2 закрыт 2026-07-20** (`8f814b00`): снапшоты перегенерены, **main зелёный — 602 passed**. Дрейф был из двух источников (Ф2 `d6faaa80` + телеметрия `173f5ff4`/ADR-PM-017), регрессов нет. Резидуалы (не блокеры): GUI-путь запуска не покрыт ни одним golden; `bootstrap.py:36` не защищён от explicit-null — чинить вместе.

**Блок В (Ф3+ промоушены) — ПОСЛЕ codemod.** Инвариант: кодовые фазы никогда не параллельны Фазе 3-codemod (freeze-окно).

### Параллельный трек — layer-grouping (блокер двух треков выше)

План [`framework-layer-grouping/plan.md`](framework-layer-grouping/plan.md). **Фаза 2 в основном закрыта 2026-07-18** (`92c19f2e` шим blueprint снесён · `d9dddf45` ConsoleProcessConfig перенесён · `bf484bcd` actions_module/interfaces.py) — но **приёмка фазы не проводилась** (перезамер циклов + прогон suite). Фазы 0/3/4/5 не начаты.

**Фаза 3 (codemod, ~1970 импортов / 910 файлов) — freeze-окно.** Её ждут: frontend-constructor Блок В и backend-ctl-framework-module Task 1.1/1.2 (слой `tooling/`). При старте пересобрать rename-таблицу: план не знает про `telemetry_readmodel_module` (2026-07-18) и переезд `backend_ctl → tooling/`.

### Параллельный трек — backend_ctl + телеметрия (2026-07-16…20; в этом файле раньше не отражался)

Самый активный трек последних дней, шёл целиком мимо QUEUE.md. Всё, кроме отмеченного, — в `main`:

| План | Статус | Осталось |
|---|---|---|
| [truth-holes-closure](truth-holes-closure.md) | **Единственный активный план инструмента** (2026-07-22) — преемник закрытого backend-ctl-proof-discipline. Ветка `fix/truth-holes-closure`. Основание: live-анализ 2026-07-22. Ф2/Ф3 ортогональны и параллелятся Ф1 | Ф1 gui-шторм (флип-лесенка) → Ф2 supervision-правда ∥ Ф3 ротация логов → Ф4 инструмент → Ф5 закрывающий live-прогон |
| [backend-ctl-proof-discipline](backend-ctl-proof-discipline.md) | ✅ **ЗАКРЫТ** 2026-07-22 (`5b6838e0` «ГЕЙТ ПЛАНА ЗАКРЫТ», 47 инструментов live-верифицированы; слит в main ff до `9a0f4137`). Поглотил шесть предшественников (архив: `_archive/`) | — (хвосты → truth-holes-closure) |
| [transport-single-policy](transport-single-policy.md) | Активный план **транспорта** (продукт, не инструмент) — ортогонален gui-шторму (state идёт targets-дверью, кадры — канальной). Не начат, ветки нет. **Порядок: после truth-holes** (унификация двери на здоровой, наблюдаемой системе + готовых счётчиках Ф4.3) | Фаза 0 доказ.база → Ф1 умная дверь → Ф2 release/reclaim → Ф3 backend_ctl типиз.ноль |
| [telemetry-pull-on-demand](telemetry-pull-on-demand.md) | **DRAFT** (2026-07-22) — направление владельца: уровни (FPS/latency/глубины) отдавать **по опросу**, процесс копит их локально; фронты (ошибки/смерти/переходы) остаются push. Ветки нет, ждёт go-ahead | инвентарь метрик levels-vs-edges → декомпозиция |
| [telemetry-coherence-remediation](telemetry-coherence-remediation.md) | ✅ закрыт 2026-07-18, merge `13623920`, Fable 47/60 (шапка исправлена с DRAFT 2026-07-20) | Task 3.2 шаг 3 (watcher фанит publish-секцию детям) — не блокирует, до Ф4 GUI |
| [gui-telemetry-read-model](gui-telemetry-read-model.md) | закрыт (ADR-136) | Task 1.3 — live qt-smoke |
| [telemetry-dashboard](telemetry-dashboard.md) | ✅ закрыт | — |
| [telemetry-publish-control](telemetry-publish-control.md) | ✅ закрыт (ADR-PM-018) | residual — каскад двух плоскостей |

**Следующий шаг трека (рекомендация ревьюера):** порядок `_system_ready_event` в `orchestrator.py` — снимает 12 красных тестов и возвращает доказуемость introspect-поверхности. Правка рискованная (сигнал ждут SystemLauncher, GUI-старт, harness) → нужен полный suite проекта, не только backend_ctl.

### Параллельный трек — robot-protocol-v2 (авторизован, не стартован)

План [`robot-protocol-v2/`](robot-protocol-v2/plan.md) (+ `tasks.md`, `protocol-spec.md`, `firmware-architecture.md`), заведён 2026-07-19 (`93dd484b`); канон v1-прошивки зафиксирован в git (`a45cff3e`). **Статус: draft, исполнение по команде владельца.** Ветки нет.

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
