# Очередь планов — единая последовательность задач

> **Обновлено 2026-08-10 — генеральная сверка после приёмки F1.** Что сделано этим заходом: (1) секция наблюдаемости приведена к факту — F1 дала **7/10**, остаток уехал в `observability-f1-hardening`; (2) **все планы каталога пересчитаны и разложены по секциям** (активные / следующие / ждут решения / отложено / закрыто) — раньше семь закрытых планов числились вперемешку с активными; (3) шапки `telemetry-dashboard` и `telemetry-publish-control` стояли `DRAFT` при слитых в main ветках (сверено git: `937bc541`, `1f6bbd40`/ADR-PM-018) — исправлены, третий случай класса «шапка врёт» после coherence 2026-07-20; (4) исторические блоки «Ход Ф0» и решения закрытых фаз убраны — они дублируют план `observability-unified-routing`, где и живут; (5) снесённые главы истории доступны в git (`git log -- plans/QUEUE.md`).
>
> **Иерархия документов — 3 уровня, у каждого своя роль:**
>
> | Уровень | Документ | Роль |
> |---|---|---|
> | 1. Порядок | **этот файл** | ЧТО делаем и В КАКОЙ последовательности + крупноблочный статус. Пер-задачных статусов здесь нет |
> | 2. Исполнение | [`2026-07-06_constructor-master/`](2026-07-06_constructor-master/plan.md) | детали задач конструктора, acceptance, единственный источник статусов волн В0–В6 |
> | 3. Стратегия | [`current-path/plan.md`](current-path/plan.md) | волны В0–В6, обоснование, реестр NEW-задач |
>
> **Правила против дрейфа:** новые задачи конструктора — в constructor-master, этот файл только упорядочивает. **Любой план, живущий дольше одного дня, обязан иметь строку здесь** (урок 2026-07-20: целый трек шёл мимо файла). Статусы при каждой сверке подтверждаются git'ом, не памятью (три прецедента врущих шапок).

## Сделано (свёрнуто; детали и merge-хэши — в constructor-master)

Ф0–Ф3 целиком · трек F (god-split) · Ф4 + добор H1–H8 · Ф5-ядро + добор C1–C8 · post-review R1–R6 · NEW-2/3/5/8 · волны В0/В1/В2 целиком · follow-up аудита В1 · RS-волна целиком · C-волна целиком (C6 движок+пул на ChainRunnable/worker_module) · Supervision-подблок В5 (depends_on `db81ab27`, backoff+jitter `fc983743`, стратегии `0fe1f467`, alerting `3dcdab65`) · H.1 ярусная карта + H.2 GATE G4 · **весь трек наблюдаемости Ф0–Ф8 + ремедиация A–E** (см. ниже).

---

## Сейчас — фронт и порядок

### 1. MERGE трека наблюдаемости — риск №1, решение владельца

`main` стоит с 2026-07-26; в ветках `feat/observability-unified-routing` + `feat/observability-review-remediation` суммарно **330 коммитов**. Приёмка F1 merge **не блокирует**: fw-suite 7382 passed, validate зелёный, остаток вынесен отдельным планом. Чем дольше стоим, тем дороже стык с codemod layer-grouping (freeze-окно). Откладывать молча нельзя.

### 2. Наблюдаемость — [`observability-f1-hardening.md`](observability-f1-hardening.md)

**F1 закрыта повторной приёмкой 2026-08-10: 7/10, порог 8+ не взят** (оси 3 = 6, 5 = 8 — держат братья закрытых дефектов: хвост оркестратора и GUI остались ERROR-only, `documents.db` без auto_vacuum, telemetry-дверь в L3 без валидации, контракты судят имена, но не типы; флейк полного каталога `backend_ctl/tests` — 11 failed ×2 при зелёных соло). Отчёт: [`docs/reviews/2026-08-10_observability-acceptance-review.md`](../docs/reviews/2026-08-10_observability-acceptance-review.md), карта состояния: [`…real-state-map.md`](../docs/reviews/2026-08-10_observability-real-state-map.md). План-добивка: 4 фазы + переприёмка F2, **не начат — ждёт решений Р-1…Р-6 владельца**. Все 22 находки трассированы в задачи.

### 3. Параллельно — [`otel-export.md`](otel-export.md) (Ф8.6)

Ред. 2 после независимого ревью спеки (6/10, 4 блокера учтены). Пересечение по файлам с остальными треками нулевое. **Старт не согласован.** До исполнения соответствие OTel — заявленное, не доказанное. Открытая развилка Р-6 плана: `scope` не доезжает до экспортёра.

### 4. Следующий крупный трек — ПЛАН ТЕЛЕМЕТРИИ (ещё не написан)

Вход в него открыт приёмкой F1. Единого плана нет — есть четыре входных куска, из которых он собирается:
- [`telemetry-pull-on-demand.md`](telemetry-pull-on-demand.md) — **DRAFT, направление владельца** (уровни по опросу, фронты push'ем); инвентарь 506 путей → 41 форма уже сделан в truth-holes 6.3 — при старте писать от него, не заново;
- **C1 / Ф8.3** — stats-разъём плагинов + доставка `kind=stats` в стор и хвост (решение Р-2в ремедиации: первая фаза телеметрии);
- residual coherence Task 3.2 шаг 3 (watcher фанит publish-секцию детям);
- gui-telemetry-read-model Task 1.3 (live qt-smoke).

Писать после merge наблюдаемости (ляжет на неё); hardening — до или параллельно.

## Остаток родительского плана — [`observability-unified-routing.md`](observability-unified-routing.md)

Ф0–Ф8 закрыты, кроме четырёх рядов (порядок): **Ф8.1** (три реестра в один каталог, разблокирует 2.3b) → **Ф5.4** (batch+glob в адресации) → **Ф5.2** (пакет Б-3/Б-4/Б-8 — ждёт решения владельца а/б/в) → **остаток Ф8** (8.2, 8.3→телеметрия, 8.5, 8.4-ADR + долги: ретеншен аудита, ~60 точек «проглоченного сбоя»). Ревью фаз: Ф3 8/10, Ф5 7.5/10, Ф7 7.5/10, приёмка целого 2026-08-09 6/10 → ремедиация → F1 7/10.

## Активные планы других треков

| Трек | План | Статус | Следующий шаг |
|---|---|---|---|
| backend_ctl | [backend-ctl-review-remediation](backend-ctl-review-remediation.md) | **единственный активный план инструмента**, не стартован, ветки нет | 4×P0 «правда не агрегируется» + пин контракта ответов + P1 SocketChannel |
| Транспорт кадров | [transport-single-policy](transport-single-policy.md) | активный план продукта, не начат | Ф0 доказательная база → умная дверь → release/reclaim |
| Жизненный цикл процесса | строки L-1/L-2/L-3 (ниже) | открыты, ветки нет | L-1+L-2 брать вместе (один корень) |
| Конструктор В4 | G.7 hot-path — **приостановлена** | статус не сверен запуском с 2026-07-16 | при возврате перепроверять по коду: soak ≥2ч ×2 рецепта → флип дефолтов G.F |
| Конструктор В5 | остаток оси Ф8: **H.3** (Registers⇄StateStore), **H.5** (sentrux+complex fn), **H.6** (закрытие constructor-master) | не начаты | после merge наблюдаемости (H.4 ею поглощена) |
| Конструктор В6 | NEW-9 packaging · NEW-4 симметрия ресурсов · туториал+scaffold · 🏁 финальная приёмка «второе приложение за день» | не начаты | после В5 |
| layer-grouping | [framework-layer-grouping](framework-layer-grouping/plan.md) | Фаза 2 в основном закрыта (приёмки не было); **Фаза 3 codemod ~1970 импортов = freeze-окно** | блокер frontend-constructor Блока В и `backend_ctl→tooling/`; при старте пересобрать rename-таблицу |
| frontend-constructor | [frontend-constructor](frontend-constructor/plan.md) | Блок А закрыт, main зелёный | Блок В — строго после codemod |
| TECH_STACK 2026 | [`docs/direction/TECH_STACK_2026.md`](../docs/direction/TECH_STACK_2026.md) | живой документ | волна 1 пунктами между волнами; msgspec-пункты — только в составе Ф7 |
| Робот | [robot-protocol-v2](robot-protocol-v2/plan.md) | авторизован 2026-07-19, не стартован | по команде владельца |

### Дефекты жизненного цикла процесса (заведено ревью Ф3, не наблюдаемость)

| # | Дефект | Что измерено | Статус |
|---|---|---|---|
| L-1 | `process.restart` не исполняется на живом стенде | `process_restart_verified`: pid не сменился, `instance_restarts` 0→0 | открыт |
| L-2 | Долг graceful-stop (5 с ханг, `stop_all_workers`/`put()`) | воспроизведён и на приёмке F1 («did not stop in 5.0s» у points/pult) | открыт, известен давно |
| L-3 | `errors_delivery_failed` не различает «приёмника нет» и «не успевает» | проба D8: 47/с шторм vs 0.15–0.36/с backpressure — один ключ | открыт |

До закрытия L-1 «инкарнация различает инстансы» — доказано тестами, не стендом (живьём везде `incarnation: 0`).

### Опциональные (вне строгого порядка)

1.8 record/replay · 2.6 JSONL-sink · 4.10 watch-from-revision · 3.10 stop/start воркера · 5.18 depth-reduction (отложено владельцем) · LP-1..LP-5.

## Открытые решения владельца

| # | Решение | Что блокирует |
|---|---|---|
| 1 | **Момент merge наблюдаемости** (330 коммитов, риск №1) | telemetry-план, H.3/H.5/H.6, чистый старт hardening (его Р-1) |
| 2 | **Р-1…Р-6 плана observability-f1-hardening** (ветка, GUI-дефолт уровня, типы контрактов, пустые снапшоты, env Services, потери на швах) | старт hardening |
| 3 | Ф5.2 unified-routing: вариант а/б/в (стор vs навигация vs гибрид) | Ф5.2 |
| 4 | Байт-diff канонизации 2 рецептов (`camera_robot_calibration`, `dataset_circle_capture`) | нет (гигиена) |
| 5 | Снятие blueprint-шима C6(c) — 0 импортёров | нет (гигиена) |
| 6 | Доводка `Process.workers`→рантайм (RS-7-остаток) | нет (поле помечено честно) |
| 7 | Ярус `chain_module`: подтвердить core (ожил в C6d) либо путь во frozen | H.2/G4-позиция №1 |
| 8 | Старт `otel-export` + его развилка Р-6 (`scope` до экспортёра) | otel-export |
| 9 | Физический перенос 12 закрытых планов в `_archive/` (список в секции «Закрыто») — на каждый 3–20 входящих ссылок из исторических доков, перенос без починки ссылок добавит битых | нет (гигиена; файлы помечены закрытыми на месте) |

## Отложено / hardware-gated (вне последовательности)

| План | Статус | Осталось |
|------|--------|----------|
| [constructor-maturity](2026-05-29_constructor-maturity/plan.md) | отложено владельцем (product > engine) | P1.2+ |
| [storage-stack-embedded-first](storage-stack-embedded-first.md) | DRAFT, не начат (поглотил `sql-insert-many-atomic`) | этапы 1-3: ретенция, файловая политика, `insert_many` |
| [pipeline-color-inspection](pipeline-color-inspection.md) | отложено владельцем | атомарные плагины цвет-инспекции |
| [device-tree-recipe](device-tree-recipe.md) | Фаза D DONE | Фаза E — ждёт go-ahead |
| [camera-robot-calibration](camera-robot-calibration.md) | Часть 1 закрыта | Часть 2 (px→mm) — железо |
| [dataset-circle-capture](dataset-circle-capture.md) | Часть 1 готова | Часть 2 (hand-eye) |
| [robot-calibration](robot-calibration.md) | частично | hardware E2E |
| [robot-place-pose](robot-place-pose.md) | P1+P2 DONE | P3 + прошивка робота |
| [word-layout](word-layout.md) | Phase 1-2 DONE | Phase 3-4, live-smoke |
| [pult-control-panel](pult-control-panel.md) | Phase 1-3, 5.1-5.3/5.5 DONE | 5.4 отложен; Phase 4 (доки) |
| [letter-robot-cycle](letter-robot-cycle/) | тракт распознавания DONE | цикл укладки→возврата |
| [draw-mode-rework](draw-mode-rework/) | A-D в основном DONE | **freeze** до железа |
| [telemetry-pull-on-demand](telemetry-pull-on-demand.md) | DRAFT — вход будущего плана телеметрии (см. «Сейчас» п.4) | декомпозиция от инвентаря 6.3 |

## Закрыто (файлы на месте; кандидаты в `_archive/` — решение №9)

| План | Закрыт | Остаток (кому передан) |
|---|---|---|
| [observability-review-remediation](observability-review-remediation.md) | фазы A–E + F1 (2026-08-10, вердикт 7/10) | весь остаток → `observability-f1-hardening`; merge — решение №1 |
| [truth-holes-closure](truth-holes-closure.md) | 2026-07-26 (6.3 вариант A, `0d8d1e3d`) | — |
| [backend-ctl-proof-discipline](backend-ctl-proof-discipline.md) | 2026-07-22 (`5b6838e0`, 47 инструментов live) | хвосты ушли в truth-holes |
| [telemetry-coherence-remediation](telemetry-coherence-remediation.md) | 2026-07-18 (merge `13623920`, Fable 47/60) | Task 3.2 ш.3 → план телеметрии |
| [gui-telemetry-read-model](gui-telemetry-read-model.md) | 2026-07-16 (ADR-136) | Task 1.3 qt-smoke → план телеметрии |
| [telemetry-dashboard](telemetry-dashboard.md) | merge `1f5083d3`+`937bc541` (шапка DRAFT исправлена 2026-08-10) | — |
| [telemetry-publish-control](telemetry-publish-control.md) | merge `1f6bbd40`, ADR-PM-018 (шапка DRAFT исправлена 2026-08-10) | residual «каскад двух плоскостей» → Ф8.2 unified-routing |
| [telemetry-delivery-simplification](telemetry-delivery-simplification.md) | SUPERSEDED → gui-telemetry-read-model (ADR-136) | — |
| [proto-frontend-carve](proto-frontend-carve.md) | SUPERSEDED → frontend-constructor Ф2; **остаётся справочной спецификацией (freeze, не архив — по собственной шапке)** | — |
| [depends-on-readiness](depends-on-readiness.md) | merge `db81ab27`, ADR-PMM-018 | — |
| [supervisor-backoff-jitter](supervisor-backoff-jitter.md) / [supervisor-strategies](supervisor-strategies.md) / [supervisor-alerting](supervisor-alerting.md) | `fc983743` / `0fe1f467` / `3dcdab65` (ADR-PMM-019/020/021) | alerting: pickle-fallback G.3(d) как источник — не подключён |
| [2026-06-05_sql-insert-many-atomic](2026-06-05_sql-insert-many-atomic.md) | ПОГЛОЩЁН storage-stack-embedded-first | — |

## Архив

**Чистка 2026-07-11** (по команде владельца; всё в [`_archive/`](_archive/)): `master-rework-roadmap` · `2026-07-03_review-and-constructor-plan` · `2026-07-03_god-split-design` · `2026-07-10_post-review-hardening` · `2026-06-06_recipe-orchestrator-unify` · `2026-05-31_pipeline-live-control/` · `2026-05-31_transport-router-hub/` · `comm-system-*` (4) · `ULTRACODE_BACKLOG`.

**Прежние волны:** чистка 2026-07-06 (16 планов) и чистка 2026-06-07 — всё в [`_archive/`](_archive/).
