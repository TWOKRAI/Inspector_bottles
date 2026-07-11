# Master Plan: Current Path — актуальный путь к конструктору

- **Slug:** current-path
- **Дата:** 2026-07-11
- **Статус:** ПРЕДЛОЖЕН (ждёт одобрения владельца)
- **Роль документа:** стратегический зонтик над всеми планами. Отвечает: где мы → куда идём → в каком порядке. **Статусы задач фаз Ф0–Ф8 ведутся ТОЛЬКО в [`constructor-master`](../2026-07-06_constructor-master/plan.md)** (он остаётся исполнительным планом); здесь — волны, новые оси и навигация.
- **Основания:** [`review-2026-07-11.md`](review-2026-07-11.md) (ревью 5 доменов) · [`architecture-10-of-10.md`](architecture-10-of-10.md) (целевая архитектура) · срез прогресса 2026-07-11.

## 1. Цель (формулировка владельца)

> Мощная удобная система создания многопроцессных приложений на Python — чтобы легко делать приложения ЛЮБОГО уровня. Второе приложение = рецепт + манифест + тонкий bootstrap.

Проверяемое определение «готово» — 6 тестов из [`architecture-10-of-10.md`](architecture-10-of-10.md) §0 (тест часа, тест форка, тест установки, тест контракта, тест живучести, тест наблюдаемости).

## 2. Где мы (срез 2026-07-11)

**Сделано** (детали в constructor-master): Ф0–Ф3 целиком, трек F целиком (god-split + F.7), Ф4.1/4.2/4.4 + добор H1–H8, Ф5-ядро (carve E1–E3, RuntimeDeps, state-plane, вся наблюдаемость 5.14–5.21), post-review R1–R6, C1/C2/C4/C5/C7 (Ф5-добор). main запушен. Инженерная база: 0 циклов импортов, чистое слоение, fencing, supervisor с watchdog, debug-plane, персистентная наблюдаемость.

**Оценка готовности к цели: ~5.5–6/10.** Разбивка по доменам (ревью):

| Домен | Сейчас | Узкое место |
|---|---|---|
| Ядро-конструктор | 4/10 | «рыбы» нет — новое приложение = форк ~29 файлов + 2 подкласса |
| Контракты IPC | 5/10 | warn-only, args/data-дуализм, 5 осей адресации |
| DX стороннего разработчика | 3/10 (агентский — 9) | README сломан, нет CI/examples/туториала/scaffold |
| Плагины/сервисы | 6/10 | нет статического манифеста, таксономия дрейфует |
| GUI-фреймворк | 6/10 | каркас вкладок в прототипе, брендинг зашит |
| Supervision | 6.5/10 | плоский: нет дерева/deps/эскалации |
| Наблюдаемость | 7/10 | нет trace-id/alerting/агрегации |
| Библиотека/пакет | 7/10 | не отделима: общий pyproject, тяжёлые deps, INSPECTOR_* |

**Два стратегических разрыва, которых НЕТ в текущих планах:**
1. **Отделимость библиотеки** (packaging, extras, de-brand, публичный API) — ни одна фаза её не несёт.
2. **Финальная приёмка реальностью** — второе приложение из «рыбы» как доказательство конструктора.

## 3. Дорожная карта — волны

Порядок фаз constructor-master НЕ ломается; волны уточняют приоритеты и добавляют две новые оси.

```
В0 merge → В1 фундамент модулей (C-волна + Ф4-хвосты) → В2 РЫБА (5.11-5.13 — сердце)
→ В3 GUI-конструктор → В4 hot-path Ф7 → В5 supervision-tree + Ф8 → В6 Конструктор v1.0
```

### В0 — Гигиена ✅ ИСПОЛНЕНА 2026-07-11
- Merge `fix/codegraph-routing-single-tool` → main (--no-ff). ✅
- **Быстрые победы вне фаз** (NEW-8): README → UTF-8 + реальный quickstart; CI-шаблон `.github/workflows`; убрать `d:/PROJECT_INNOTECH/...` из backend_ctl/AGENTS.md. ✅ (ветка `chore/dx-quick-wins-new8`, merge в main): README переписан (старые заметки сохранены в `docs/notes/2026_shared-resources-pickle-notes.md`), CI: validate+tests blocking (fw 3817 passed headless локально), ruff advisory (19 нарушений — накопленный долг, TODO снять `continue-on-error` после разбора), pyright отложен; AGENTS.md очищен.
- **Старт В1 — 2026-07-11:** C4/C5/C1 закрыты параллельными агентами (статусы в constructor-master; объединённый гейт 1701 passed, sentrux 9/9, quality 7081); далее C2 → 4.8 → C3. **Прогресс среза 2026-07-11 (обновлено):** C2 ✅ (merge 07993e22, ADR-RCP-003), C7 ✅ (merge 50798fa6), 4.3/4.9 ✅, 4.4 ✅ (ADR-PM-013, детали — constructor-master); 4.8 mini-GATE — prep влит (merge d4e29943, ADR-RCP-004), ждёт вердикта владельца; C6(a) дизайн влит (merge 39236585), рычаги (b)+(c) исполняются агентом; C3 остаётся заблокирован вердиктом 4.8; NEW-2/NEW-5 (В3, ниже) исполнены досрочно.

### В1 — Фундамент модулей (= C-волна + Ф4-хвосты, ~2 нед)
Как в constructor-master: C4/C5 → C1→C2 (+4.8 mini-GATE) →C3 → C6 → C7 → C8. Уточнения из ревью:
- **C6 + NEW-C6a:** в дизайн добавить рычаг `ProcessConfig.extras` (domain-opaque dict вместо типизированных `inspector/chain_targets` полей) — развязывает вынос домена от переноса SystemBlueprint; туда же — вынос `frame_trace` из `__init_subclass__` базы плагина (C-6 ревью).
- **4.4 (манифест плагина) — расширить скоуп:** + `category` как Enum с канонизацией словаря (C-2), + `requires` с fail-fast на сборке (C-3), + `params_schema` статически из register_class (capabilities = runtime-зеркало). Формат манифеста = общий с app.yaml/service.yaml (`version + extras`).
- **4.3:** включить судьбу `validate_chain` (оживить для внутрипроцессных линейных цепочек) (C-4).
- **NEW-3:** отдельная задача «strict-валидация control-plane» (`extra="forbid"` на вложенном `data`; warn — режим раскатки, strict — целевой) — сейчас это устный «следующий инкремент» ADR-MSG-008 без владельца.
- **C7 — усилить:** ADR коннектора Service↔Plugin с проверяемым контрактом (тонкий = форвардер через client, тест «не импортирует ядро сервиса») (C-8); текстом зафиксировать целевые 3 оси контрактной плоскости (A/B/C из architecture §4) как вектор для G.2/G.4/H.3.
- Ф4-хвосты: 4.7 после C3; 4.9 (revision в Delta — переиспользовать epoch-счётчик, не третий) — можно параллельно C-волне.

### В2 — РЫБА (= 5.11–5.13, сердце всей цели, ~1.5 нед)
Статус «после carve» сохраняется, но восприятие инвертируется: **minimal_app строится ПЕРВЫМ инкрементом 5.11** против уже вынесенного `assemble_launcher` — как ранний детектор Inspector-допущений, а не финальная проверка.
- 5.11: + `ManifestStore` — единственная точка read/write app.yaml (закрывает гонку backend↔GUI, A4/NEW-1); + один framework-helper `discover()` вместо двух копий (A6); + баннер из `manifest.name` (A8).
- 5.12: первая пара хуков = state-bootstrap (build-time) + display-reload (runtime) — доказательство обоих сортов.
- 5.13: minimal_app в CI = инвариант 8 архитектуры.
- Вопросы скоупа 5.11 (3 шт.) — решить до старта волны (§5).

### В3 — GUI-конструктор (параллельно/после В2, ~1 нед)
- **5.10 расширить S→M (NEW-D1):** перенести МЕХАНИЗМ (TabFactory/lazy/permission-фильтр) во frontend_module как TabRegistry; прототип = `TABS: list[TabSpec]`; permissions и predefined_roles деривятся из реестра (D-1/D-4/D-5).
- **NEW-2 AppIdentity (S):** `_ORG`/лого/title — инъекция из composition root; acceptance: grep «Inspector» по frontend_module = 0 (D-2/D-3, F3). **✅ 2026-07-11 досрочно** (ветка `feat/frontend-app-identity`, merge f5deff73): `frontend_module/core/app_identity.py` — `AppIdentity` frozen-dataclass + `set_app_identity()`, дефолт нейтральный (`MultiprocessApp`/env `MPF_APP_NAME`), composition root (`multiprocess_prototype/frontend/app.py`) инжектит явно; `prefs_store`/`window_registry`/`loading_window` читают идентичность вместо хардкода; QSettings прототипа не тронуты (не теряют user prefs). **Уточнение acceptance:** grep «Inspector» по `frontend_module` НЕ строго 0 — остаются generic-имена виджетов (`InspectorPanel`/`SchemaInspectorPanel`, паттерн «инспектор-панель», не бренд) и упоминания в ROADMAP.md; брендовые строки (org/лого/title) вынесены полностью.
- **NEW-5 Формы из схемы (S):** `build_form_for_schema(SchemaBase)` поверх `FieldInfo.from_schema` + каталог UI-hint полей FieldMeta; 7b/7c/7d остаются frozen (G2), новые фичи только через FieldMeta (D-6). **✅ 2026-07-11 досрочно** (ветка `feat/forms-from-schema`, merge e13b8721, ADR-DS-008): `FieldMeta` +`ui_group`/`ui_order`/`ui_hidden` (data_schema_module) + зеркало в `registers_module/core/field_info.py`; `frontend/forms/form_builder.py::build_form_for_schema` — новый механизм поверх каталога, НЕ трогает 7a/7b/7c/7d (frozen-вердикт G2/5.6 держится). Тесты: field_meta 46 + field_info 77 + build_form_for_schema 129.

### В4 — Hot-path Ф7 (как в constructor-master, строго одним вскрытием)
Уточнения из ревью: G.6 (trace-id) — вынести ПЕРВЫМ шагом фазы (семантические поля, не hot-path-рискованно; главный разрыв наблюдаемости E-4); в G.2/G.4 — свёртка оси kind (`queue_type` выводится из kind, один резолвер) = ось B архитектуры; G.4 приёмка «error-storm не топит heartbeat» live-тестом.

### В5 — Supervision-tree + Ф8 (~1.5 нед)
- **3.9 depends_on — поднять из «опц» в обязательное** (предусловие Ф8): порядок старта по readiness апстрима (E-3).
- **NEW-6 Стратегии супервизора (M):** `RestartPolicy.strategy` (one_for_one = текущее, rest_for_one/one_for_all — новые ветки) + группы в blueprint + экспоненциальный backoff с jitter + эскалация give-up (E-1/E-2). Аддитивно, флаг-откат.
- **NEW-7 Alerting (S):** правила «gave_up/failed/drop-растёт → громкая нотификация» поверх `_emit_supervisor_event` (E-5).
- Ф8 как в плане (H.1 ярусы+frozen-boundaries, G4 per-item, H.3 Registers⇄StateStore — с оглядкой на оси A/B/C, H.5 пороги) + **NEW-10 в H.1:** interfaces.py для actions_module (24/24), Protocol для ObservableMixin-контракта, правило «один вход на модуль» + contract-тест `__all__` (F5/F6/F8); C8 + 4-ярусная ментальная модель и фикс L11 registers (F7).

### В6 — Конструктор v1.0 (новая ось, после В5, ~2 нед)
- **NEW-9 Packaging (M/L, порядок от дешёвого):** (1) тяжёлые deps → extras `[vision]/[gui]/[plotting]` (F2); (2) env `MPF_*`/`MULTIPROCESS_*` каноничны, `INSPECTOR_*` — алиас, включая PID/health/log-level вне зоны C6 (F4, A8); (3) свой `pyproject.toml` у framework, прототип — потребитель пакета (F1, строго после C6).
- **NEW-4 Симметрия ресурсов плагина (S/M):** контракт-тест configure↔shutdown, SHM owner-теги на утечку (C-5).
- Туториал «своё приложение за час» + scaffold 5.14опц (после 5.13).
- **Финальная приёмка: второе продуктовое приложение из «рыбы» за день** — единственное честное доказательство 10/10.

## 4. Реестр новых задач (NEW — чего не было в планах)

| ID | Суть | Усилие | Куда встроить | Источник |
|---|---|---|---|---|
| NEW-1 | `ManifestStore` — одна точка read/write app.yaml (+регресс-тест гонки) | S | acceptance 5.11 | A4 |
| NEW-2 | `AppIdentity` — de-brand frontend_module (org/лого/title инъекцией) | S | В3 | D-2/D-3/F3 |
| NEW-3 | Strict-валидация control-plane (`extra="forbid"` на data) | M | В1, после 4.3 | B3 |
| NEW-4 | Симметрия ресурсов плагина (configure↔shutdown контракт-тест) | S/M | В6 | C-5 |
| NEW-5 | `build_form_for_schema` + UI-hints в FieldMeta | S | В3 | D-6 |
| NEW-6 | Supervision: strategy/группы/эксп.backoff/эскалация | M | В5 | E-1/E-2 |
| NEW-7 | Alerting-правила поверх supervisor-событий | S | В5 | E-5 |
| NEW-8 | README UTF-8 + quickstart; CI-шаблон; чистка AGENTS.md-путей | S | В0 | E-7/E-8/E-9 |
| NEW-9 | Packaging: extras → env-алиасы → свой pyproject framework | M/L | В6 (extras можно раньше) | F1/F2/F4 |
| NEW-10 | Публичный API: 24/24 interfaces.py, Protocol ObservableMixin, «один вход», contract-тест `__all__` | S/M | Ф8 H.1 | F5/F6/F8 |
| NEW-C6a | `ProcessConfig.extras` (domain-opaque) + вынос frame_trace из базы плагина | — | дизайн C6 | A3/C-6 |
| NEW-D1 | 5.10: перенос МЕХАНИЗМА табов во frontend_module (расширение скоупа S→M) | M | В3 | D-1/D-4/D-5 |

Правки формулировок существующих задач: 4.4 (+Enum категорий, +requires fail-fast, +params_schema статически), 4.3 (+validate_chain), 3.9 (опц → обязательное), G.6 (первым в Ф7), 5.10 (механизм в прототипе — исправить преамбулу задачи), C7 (+контракт коннектора, +текст 3 осей).

## 5. Решения владельца (открытые, консолидировано)

1. **Одобрить этот Master plan** (волны + NEW-задачи + правки скоупов) и порядок В0→В6.
2. Перекалибровка «Метрик приёмки» constructor-master (R5c/H.5): рекомендация — пофазные гейты (max-LOC зоны, характеризационные тесты, grep-инварианты) вместо repo-wide modularity; 6 тестов architecture §0 — как финальные.
3. Ранний вынос frozen-boundaries из Ф8 H.1 (до C-волны — чтобы C6 не оброс зависимостями frozen-кода). Рекомендация: да, вынести.
4. Скоуп 5.11 — 3 вопроса из constructor-master (дискавери сервисов: рекомендация маркер-файл `service.yaml` + пути из app.yaml; GUI-часть рыбы — отдельно после; minimal_app — headless-only).
5. R2-residual: гейт `recovered` на `health.status==ok` (candidate В5/NEW-6).
6. NEW-8 (README/CI) — можно исполнять сразу, не дожидаясь одобрения волн? Рекомендация: да (нулевой риск).

## 6. Метрики пути (взамен некалиброванных чекпойнтов)

| Волна | Гейт-метрика |
|---|---|
| В1 | grep формат-веток вне модуля recipe = 0; один deep-merge; один CRM-нормализатор; property-тесты миграций зелёные |
| В2 | оба рецепта бутятся через `run_app`; minimal_app headless в CI; 0 импортов prototype из examples |
| В3 | вкладка добавляется одним TabSpec без правки frontend_module; grep «Inspector» по frontend_module = 0 |
| В4 | FPS ≥ baseline, p99 ≤ baseline, torn-frame-repro = 0; один конверт команд; trace-id прошивает жест→кадр |
| В5 | e2e: kill апстрима → rest_for_one рестартит зависимых; give-up → нотификация |
| В6 | `pip install multiprocess-framework` без cv2; **второе приложение собрано за день**; тест часа пройден новичком |

Финал = 6 тестов [`architecture-10-of-10.md`](architecture-10-of-10.md) §0.

## 7. Ландшафт документов (навигация)

| Документ | Роль |
|---|---|
| **этот план** | стратегия: волны, новые оси, метрики пути |
| [`architecture-10-of-10.md`](architecture-10-of-10.md) | эталон целевой архитектуры (сверка решений) |
| [`review-2026-07-11.md`](review-2026-07-11.md) | доказательная база (находки A/B/C/D/E/F с file:line) |
| [`../2026-07-06_constructor-master/plan.md`](../2026-07-06_constructor-master/plan.md) | **исполнительный план** — фазы, задачи, статусы, gates |
| [`../../docs/audits/2026-07-10_module-responsibility-duplication-map.md`](../../docs/audits/2026-07-10_module-responsibility-duplication-map.md) | карта ответственности + дубли D/N/V |
| `QUEUE.md` | указывает на constructor-master (governing) |

**Правило против дрейфа:** новые задачи из §4 после одобрения владельца ВНОСЯТСЯ в constructor-master (соответствующие фазы/доборы) обычным порядком; этот план обновляется только на уровне волн. Два источника статусов не заводим.
