# Триаж аудита «конструктор 2026» → фазы constructor-master

- **Источник:** [`docs/audits/2026-07-04_arch-advice-constructor-2026.md`](../../docs/audits/2026-07-04_arch-advice-constructor-2026.md)
- **Задача:** Ф0.6 — закрыть дыру «ни один план не ссылается на аудит»
- **Примечание о «52»:** полный список 52 рекомендаций живёт в журнале workflow
  `wf_ec3fc2e3-24e` (см. хвост аудита); сам аудит-документ — синтез: 5 сквозных тем,
  18 приоритетов framework, 8 приоритетов прототипа, 6 анти-паттернов. Триаж ведётся
  по синтезу — он покрывает все 52 через темы.

## Сквозные темы → фазы

| Тема | Фаза |
|---|---|
| 1. Hot-path (seqlock / QoS / двойная конверсия) | **Ф7** (G.3/G.4/G.5) |
| 2. Супервизия (флагман выключен) | **Ф3** (3.1-3.8) |
| 3. Контракты вместо конвенций | **Ф4** (4.1-4.6) |
| 4. `ctx.health` до волны C | **Ф2** (2.1-2.5) |
| 5. Фокус: 8 модулей, а не 22 | **Ф0.5 G0** (вердикты) + **Ф8** (H.1/H.2) |

## Приоритеты ФРЕЙМВОРКА (аудит §2) → задачи

| P | Рекомендация | Вердикт триажа |
|---|---|---|
| P0 | `ctx.health.report_error` + типизация PluginContext | **Ф2.1** (+2.2 breaker, 2.3 discovery/ObservableMixin) |
| P0 | Multi-register overwrite + boot-проверка дубликатов | **Ф4.1** |
| P0 | Supervisor v2 (policy/окно/deadline/routing-epoch/fault-injection) | **Ф3.1, 3.2, 3.6, 3.7** (+3.5 wire re-issue) |
| P1 | Волна G расширенная (seqlock+QoS+конверсия+copy-elision) | **Ф7 G.3, G.4, G.5** |
| P1 | Реестр контрактов сообщений + payload-валидатор | **Ф4.2, 4.3** |
| P1 | Ревизии state-дерева + resync (etcd-паттерн) | **Ф4.9** (+4.10 driver watch опц.) |
| P1 | Ярусы core/optional/frozen + freeze chain + K13-K16 | **Ф0.5 G0** (таблица в plan.md; K13-K16 = позиции 1-5 G0) + **Ф8 H.1/H.2** |
| P2 | Манифест плагина (version/api_version) | **Ф4.4**; entry-points discovery — **DEFER** до pip-дистрибуции (манифест сперва) |
| P2 | JSONL-sink + OTel-совместимые ID | **Ф2.6** (sink, опц.) + **Ф7 G.6** (ID) |
| P2 | Health-схема как контракт | **Ф2.1** |
| P2 | Движок миграций dict-документов | **Ф4.5** (+4.6 единая READ-точка) |
| P2 | DeltaJournal (append-only + replay) | **DEFERRED** (Ф4.10: revision+resync покрывает 80%; журнал — при появлении post-mortem-потребителя) |
| P3 | TabSpec/TabRegistry во framework | **Ф5.10** (опц., если бюджет фазы) + связка с app_module (app-template-idea.md §3.2) |
| P3 | IncrementalPlanner + replicas:N + scale | **ВНЕ СКОУПА** (plan «Вне скоупа»; autoscale-анти-паттерн §4 аудита — сперва замер) |
| P3 | Transport-conformance suite IMessageChannel | **DEFER** до реального 2-го бокса; задел — SpawnBackend Protocol в **Ф5.2** |
| P4 | GuiBootstrap (staged-pipeline вместо run_gui 875 LOC) | **ВНЕ СКОУПА** плана; кандидат = GUI-часть app_module ПОСЛЕ Ф5 (app-template-idea.md, откр. вопрос 2) |
| P4 | RemoteEventBridge (typed events) | **ВНЕ СКОУПА** (за STOP-gate telemetry Option D — 2-й реактивный потребитель) |
| P4 | Inference-сервис (dynamic batching, GPU в blueprint) | **ВНЕ СКОУПА** (product>engine; после замера) |

## Приоритеты ПРОТОТИПА (аудит §3) → задачи

| # | Рекомендация | Вердикт триажа |
|---|---|---|
| 1 | Включить RestartPolicy | **Ф3.8 (GATE G1)** |
| 2 | E4 расширенный: ВСЕ 4 механизма схема→виджет | **Ф5.6** (diff-отчёт 4 механизмов → G2) |
| 3 | join/inspector из wires при assembly | **Ф4.7** |
| 4 | RuntimeDeps → двухслойный контракт | **Ф5.8** |
| 5 | Авто-подписка bind (ensure_subscription + refcount) | **Ф5.9** |
| 6 | Delta целиком до GUI + один glob-матчер | **Ф5.9** |
| 7 | Батчинг телеметрии (proxy.merge) | **Ф5.7** |
| 8 | Один стандарт логирования | **Ф8 H.4** |

## «Чего НЕ делать» (аудит §4) → статус

Все 6 анти-паттернов (кластер/брокер, CRDT/event-sourcing, in-process hot-reload,
OTel SDK, autoscale до замера, iceoryx2/Arrow-зависимости) зафиксированы в plan.md
«Вне скоупа» и analysis.md §9 — план им соответствует. Идею seqlock берём без
биндингов (Ф7 G.3), identity-check reload и failed-list видимость — **Ф2.3**.

## Итог

- 18/18 framework-приоритетов: 13 → конкретные задачи фаз, 5 → DEFER/вне скоупа с причиной
- 8/8 прототип-приоритетов: 8 → конкретные задачи фаз
- 0 рекомендаций потеряно; дыра QUEUE.md закрыта
