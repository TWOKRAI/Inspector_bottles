# Целевая архитектура 10/10 — «Многопроцессный конструктор»

- **Дата:** 2026-07-11. Синтез ревью 5 доменов ([`review-2026-07-11.md`](review-2026-07-11.md)) + планов + предпочтений владельца.
- **Назначение:** эталон, к которому стремимся. Не план (план — [`plan.md`](plan.md)); этот документ отвечает «КАК выглядит идеал», чтобы каждое решение можно было сверять с ним.
- **Девиз:** *приложение — это данные и декларации; код — только там, где приложение уникально.*

---

## 0. Определение 10/10 (проверяемое)

Конструктор достиг 10/10, когда выполняются ВСЕ утверждения:

1. **Тест часа:** разработчик, никогда не видевший кодовую базу, по README+туториалу собирает и запускает работающее многопроцессное приложение (2 процесса, 1 свой плагин, 1 GUI-вкладка) **за ≤ 1 час**, не читая исходники фреймворка.
2. **Тест форка:** ни один файл `multiprocess_prototype/` не нужно копировать для нового приложения. `grep import multiprocess_prototype` по новому приложению = 0.
3. **Тест установки:** `pip install multiprocess-framework` ставит ядро БЕЗ OpenCV/pandas/NodeGraphQt (они — extras) и БЕЗ слова «Inspector» внутри (grep = 0, env `MPF_*`/`MULTIPROCESS_*` каноничны).
4. **Тест контракта:** любое control-сообщение с опечаткой в поле отклоняется на границе (strict), несовместимые порты не собираются в топологию, устаревший формат рецепта мигрирует автоматически, пропущенная state-дельта детектируется и восстанавливается.
5. **Тест живучести:** kill -9 любого процесса → система восстанавливается по декларативной политике (включая зависимые процессы), оператор получает громкое уведомление, ни одно system-сообщение не потеряно молча, crash-лог доехал до стора.
6. **Тест наблюдаемости:** для любого кадра/команды можно проследить полный путь (trace-id: жест → команда → лог → state-дельта → кадр) через GUI-вкладки или backend_ctl, без чтения исходников.

---

## 1. Модель уровней (закон архитектуры)

Четыре уровня; уровень — роль в модели импортов, не директория (правило №9 CLAUDE.md):

| Ур. | Что | Дом | Владеет |
|---|---|---|---|
| 0 | Python + библиотеки | — | — |
| 1 | **Механизмы**: процессы, IPC, роутинг, state, plugin-runtime, supervision | `multiprocess_framework/modules/` (24) | НИЧЕГО доменного, НИЧЕГО брендового |
| 2 | **Платформа**: композиция (`app_module`), словарь плагинов (`Plugins/`), сервисы (`Services/`), движок рецептов (модуль `recipe`) | верхний ярус framework + Plugins + Services | generic-сборка; переиспользуемое содержимое |
| 3 | **Приложение**: Inspector Bottles, minimal_app, будущие | `multiprocess_prototype/`, `examples/` | данные + branding + уникальные виджеты/хуки |

**Импорты только вниз** (enforced sentrux): framework → Services → Plugins → приложение. Внутри framework никто не импортирует `app_module`.

### 1.1. Модули ур.1 — четыре полки (ментальная модель вместо L1–L12)

| Полка | Назначение | Модули |
|---|---|---|
| **I. Transport** | контракты данных + доставка | base_manager, data_schema, message, dispatch, channel_routing, router, shared_resources |
| **II. Runtime** | жизнь одного процесса | logger, error, statistics, config, state_store, registers, event, command, actions, worker, chain, process |
| **III. Construction** | сборка системы из процессов | process_manager, service, display, *(+ recipe — новый)* |
| **IV. Presentation** | I/O с человеком | console, frontend |

Ортогональная ось востребованности: **core (15) / optional / frozen** (G0-ярусы, enforcement Ф8 H.1). Правило: манифесты/контракты пишутся только core/optional; frozen не обрастает зависимостями (sentrux-boundary).

---

## 2. Опорные принципы (действующие законы — сохраняются)

1. **Dict at Boundary** — между процессами только pickle-safe dict; Pydantic внутри процесса.
2. **Меньше слоёв** — новая сущность обязана заменять существующие, а не добавляться рядом.
3. **Freeze-over-kill** — дремлющий код замораживается ярусом, не удаляется (Принцип №1: удаления только через G0/G4 per-item).
4. **Декларация + хуки вместо наследования** — build-time хук = callable, runtime-хук = import-path + dict (spawn не пиклит callable).
5. **Терять можно — молчать нельзя** — любой drop/overflow имеет счётчик и виден в state/GUI.
6. **module-contract** — новый публичный модуль = README + Protocol + contract-тесты.
7. **Fail-fast на сборке, не в hot-path** — все проверки (порты, requires, контракты) на этапе сборки топологии; рантайм платит только в dev-режиме.
8. **Одна истина — много представлений** — схема декларируется один раз (SchemaBase/Contract/манифест), всё остальное (валидация, формы, capabilities, docs) выводится.

---

## 3. Приложение 10/10 (внешний вид)

```
my_app/
  app.yaml          # манифест: name, version, extras, discovery-пути, активный pipeline
  system.yaml       # системные настройки + defaults
  recipes/          # рецепты и топологии (продукт)
  registers/        # SchemaBase-схемы регистров (= формы GUI автоматически)
  plugins/          # свои плагины (плюс общие из Plugins/)
  services/         # свои сервисы (маркер service.yaml)
  tabs.py           # TABS: list[TabSpec]  ← вся GUI-декларация
  run.py            # from multiprocess_framework...app_module import run_app; run_app("app.yaml")
```

- `run.py` < 10 LOC. Оркестратор приложения ≤ ~30 LOC (только хуки).
- Манифест версионирован (`version: 1` + `extras: dict`) с первого дня → движок миграций применяется к нему так же, как к рецептам.
- Манифест имеет ЕДИНСТВЕННУЮ точку read/write (`ManifestStore` в app_module) — это разделяемое состояние backend+GUI, а не конвенция.
- Discovery симметричен: `discovery.plugin_paths` + `discovery.service_paths` из app.yaml + маркер-файлы (`plugin`-манифест / `service.yaml`); дальний прицел — entry-points, чтобы плагин ставился pip-пакетом.
- Identity (имя, org, лого, title) — из `manifest.name`/`AppIdentity`, прокинутого композицией; фреймворк не знает слово «Inspector».

---

## 4. Контрактная плоскость: три оси + одна декларация

Сегодняшние 5+ осей адресации сворачиваются в **три ортогональных концерна**:

| Ось | Вопрос | Механизм |
|---|---|---|
| **A. Адрес** | кто получит | `targets` (dotted `process.worker`) — единственная ось «куда» |
| **B. Kind + QoS** | что за груз | `system \| command \| data \| event \| log \| state` → из kind ДЕТЕРМИНИРОВАННО выводятся канал (`{proc}_{kind}`) и QoS-профиль (reliability, history, drop_policy, deadline) — один резолвер в router |
| **C. Схема** | какая форма | одна Pydantic-схема на ключ (command/data_type) |

**Единая декларация** — пользователь описывает контракт ОДИН раз:

```python
Contract(key="db.query", schema=DBQuery, kind="command", plane="control")
```

из неё выводятся: форма конверта (один билдер — параметры всегда в `data`; `args` — read-only legacy-alias), канал и QoS, строгость на границе (control → strict, `extra="forbid"`; data → payload-валидатор по Port-декларации, dev-on/prod-off), карточка в `introspect.capabilities`.

Дополнительно:
- **State — revision-нумерованный поток** (etcd-паттерн): `Delta.revision` монотонный, подписчик детектирует пропуск и делает resync-from-revision. Счётчик переиспользует epoch fencing-плоскости — третий счётчик не заводится.
- **Fencing** (per-sender incarnation) — как есть (ADR-MSG-009), data-plane фенсится в Ф7 G.4.
- **Register-плоскость**: `FieldRouting` — единственный декларатор «поле → (канал, процесс)»; `connection_map`/`register_dispatch` — производные view, не параллельные истины.
- **Hot-path неприкосновенен**: плоский dict per-frame, `Message(**…)` не конструируется (инвариант 1); SHM — статические регионы + seqlock + кольцо на камеру (Ф7 G.3/G.4).

Манифестная плоскость — **один формат** для трёх видов деклараций: `app.yaml`, манифест плагина (4.4), `service.yaml` — все несут `version + extras`, все мигрируются одним движком (модуль `recipe`, раннер извлекаемый).

---

## 5. Модель расширения: плагин и сервис

**Плагин 10/10:**
- **Статический манифест** читается БЕЗ импорта кода и без живого бэкенда (образец — VS Code `package.json` / Home Assistant `manifest.json`): `version`, `api_version` (semver контракта плагин↔фреймворк; mismatch на boot → WARNING/skip), `requires` (сервисы/фичи: `[service:device_hub, shm]`), `category` (**Enum**, канонический словарь, валидируется при регистрации), `params_schema` — статически из register_class; `introspect.capabilities` — runtime-зеркало того же источника.
- **Fail-fast контекст**: `requires` проверяется при сборке топологии — «плагин X требует worker_manager, процесс его не поднял» вместо позднего `AttributeError` из `getattr(...,None)`.
- **Симметрия ресурсов**: контракт-тест «что выделено в configure() — освобождено в shutdown()» (SHM owner-теги проверяются на утечку).
- **Валидация цепочек — вся**: cross-process (blueprint) + GUI (wire_validation) + внутрипроцессная линейная (`validate_chain` оживает в 4.3). Порты — до caps-negotiation (согласование H,W,dtype при линковке), не только compat-проверка.
- **База generic**: `ProcessModulePlugin` не тянет inspection-домен (`frame_trace` уходит из `__init_subclass__` в Plugins либо становится opt-in no-op-safe).
- **Коннектор Service↔app** — формальный протокол, не конвенция: тонкий плагин = форвардер через client сервиса, бизнес-логика в `Services/*`; enforced контракт-тестом «коннектор не импортирует ядро сервиса».

**Сервис 10/10:** маркер `service.yaml` (симметрично плагину), discovery из app.yaml, объявление в топологии как процесс/плагин — как сейчас, но auto-scan.

---

## 6. Runtime-плоскость: supervision tree

От плоского one_for_one — к дереву (образцы: OTP, systemd, k8s):

- **Стратегии групп**: `RestartPolicy.strategy = one_for_one | rest_for_one | one_for_all` + группировка в blueprint. `one_for_one` = текущее поведение (нулевая регрессия).
- **`depends_on` — обязательное ядро, не «опц»**: порядок старта/останова по readiness апстрима (ready_event ADR-PMM-011 уже есть — довести до gating). Без этого source→hub→sink приложения флапают.
- **Эскалация**: give-up узла — не терминал, а сигнал уровнем выше (родительская группа/системное правило).
- **Экспоненциальный backoff + jitter** (systemd-паттерн) вместо фиксированного.
- **Liveness ⟂ readiness** (k8s): обе пробы раздельно; health-restart (`FW_HEALTH_RESTART`) — решение владельца о default.
- **Alerting**: декларативные правила «`supervisor.event=gave_up` / `health.status=failed` / drop-счётчик растёт → громкая нотификация» (лог + вкладка + опц. внешний sink) поверх готового `_emit_supervisor_event`.
- Всё достигнутое сохраняется: fencing, routing-epoch, recovery-watchdog, окно N/T, авто-рестарт-всех default-on, честный breaker.

---

## 7. Наблюдаемость: «видят всё» — оператор и агент

Достроить существующий контур (hub → store → вкладки → live-tail → debug-plane) тремя недостающими частями:

1. **trace-id** (G.6): семантические OTel-совместимые поля в frame_trace/LogRecord/команде — БЕЗ OTel SDK. Один id прошивает: жест GUI → команда → лог → state-дельта → кадр.
2. **Агрегация ≠ транспорт** (граница D8): statistics_module — rollup-метрики (fps/latency/error-rate по окнам); hub — доставка и персистентность записей. Не сливать.
3. **QoS live-tail** (G.4): observability.record не теснит heartbeat при error-storm — единый drop-policy, приёмка live-тестом.

Плюс: backend_ctl остаётся первоклассным интерфейсом агента (capabilities-книжка, debug_session, verify-probe) и — через MCP — частью DX конструктора.

---

## 8. GUI-фреймворк: вкладка = данные, форма = схема

- **`TabSpec`/`TabRegistry` во frontend_module** (механизм: фабрика, lazy, permission-фильтр); приложение декларирует `TABS: list[TabSpec]` (id, title, factory, view_permission, order, icon). `TAB_ORDER`+`register_all_tabs`+permissions генерятся из реестра. Образец — VS Code contributes points.
- **Роли деривятся из TabRegistry**, не хардкодят tab-id в `Services/auth`.
- **Формы**: единственный активный механизм 7a эволюционирует — вход `build_form_for_schema(SchemaBase)` поверх `FieldInfo.from_schema`; новые UI-возможности = поля `FieldMeta` (группа, порядок, widget-hint, hidden, readonly-by-role), которые читает резолвер kinds. 7b/7c/7d — frozen-капитал, новые фичи туда не текут (G2-вердикт).
- **AppIdentity** (org, имя, лого, title) — инъекция из composition root; `grep "Inspector"` по frontend_module = 0.
- **MVP-дисциплина**: presenter Qt-free, мост GUI↔процессы — Dict at Boundary, состояние — через state-plane (5.9) с revision (4.9).

---

## 9. Дистрибуция и DX

- **Пакетируемость**: свой `pyproject.toml` у framework; тяжёлые deps — extras (`[vision]`, `[gui]`, `[plotting]`, `[ml]`); прототип — потребитель пакета, не со-пакет. Путь: extras → de-brand → env-fallback (`MPF_*`/`MULTIPROCESS_*`, `INSPECTOR_*` — алиас) → свой дистрибутив (после C6).
- **Публичный API**: один вход на модуль (`__init__` re-export'ит Protocol + конкретику; interfaces.py — для type-hints), 24/24 модуля с interfaces.py, Protocol у ObservableMixin-контракта; contract-тест «__all__ покрывает публичные символы»; semver фреймворка.
- **Документация-код**: README (UTF-8!) + туториал «своё приложение за час»; `examples/minimal_app` в CI как исполняемая документация и forcing function; scaffold `app new my_app`.
- **CI-шаблон**: `.github/workflows` — ruff + pyright + pytest + sentrux-check; форкающий получает gate бесплатно.
- **Приёмка конструктора** — только реальностью: **второе продуктовое приложение**, собранное из «рыбы» за день.

---

## 10. Инварианты 10/10 (enforce-список)

| # | Инвариант | Проверка |
|---|---|---|
| 1 | Импорты только вниз; framework не импортирует app_module; examples не импортирует prototype | sentrux rules |
| 2 | hot-path: без `Message(**…)` per-frame; TRACE=0; p99 ≤ baseline | Ф7 G-гейты, grep |
| 3 | Наблюдаемость: drop только со счётчиком; error/critical — write-through; swallow-без-report = 0 | AST-гейты (есть) |
| 4 | Control-plane strict: неизвестное поле → отказ на границе | contract-тесты |
| 5 | grep «Inspector» по multiprocess_framework = 0 (вне frozen/докстрингов) | grep-инвариант CI |
| 6 | Порты/requires валидируются при сборке; кривая топология не стартует | contract-тесты |
| 7 | Каждый модуль: README + interfaces.py + tests; один документированный вход | validate.py + contract-тест |
| 8 | minimal_app бутится headless в CI из «рыбы» без прототипа | CI-smoke |
| 9 | Любой документ-манифест несёт version; движок миграций один | property-тесты C2 |
| 10 | system-сообщения не теряются молча никогда | G.4-гейт (частично есть — 3.3) |

## 11. Анти-цели (НЕ делаем — защита от переусложнения)

- Никакого hook-фреймворка — плоский список типизированных хуков (правило N=1+minimal_app).
- Никакой venv-изоляции плагинов — процессная изоляция уже есть; `requirements` в манифесте — декларация, не механизм.
- Без OTel SDK — только семантические поля.
- Без нового корневого пакета `multiprocess_platform/` и без `prototype_2` — strangler fig на месте (решения 2026-07-06).
- Без единого `IPort`-суперинтерфейса поверх IChannel — «5 гнёзд» остаются метафорой документации.
- Ничего из анти-карго-культ-списка (analysis.md §9); генерализация только при втором потребителе.
