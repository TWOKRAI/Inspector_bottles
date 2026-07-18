# Plan: Выделение фронт-части из прототипа (hardcoded shell) — фундамент под конструктор фронта

- **Slug:** proto-frontend-carve
- **Дата:** 2026-07-11
- **Статус:** **SUPERSEDED** → [`frontend-constructor/plan.md`](frontend-constructor/plan.md) Ф2 (2026-07-18). Поглощён (Р2): задачи Task 0.1/1.1/1.2/2.1/2.2/3.1 исполняются как frontend-constructor Ф2. Файл остаётся **справочной спецификацией** (freeze, не kill) — статусы фаз ведутся только в новом плане.
- **Ветка:** docs/plan-proto-frontend-carve (документ); ветка исполнения — `feat/proto-frontend-carve` (создаётся оркестратором при старте)
- **NEW-ID:** NEW-D2 (ось D — GUI/фронт-конструктор, после NEW-D1)
- **Волна:** В3 (GUI-конструктор) — фундаментный пред-шаг; исполнять **после хвоста В1** (recipe-ось C3/4.7)
- **Связь:** NEW-D1 (5.10, TabRegistry), 5.11–5.13 (РЫБА, headless-only), current-path §3-В3

## Overview

Выделить фронт-часть прототипа в **явно отделённую, пока хардкод, оболочку** так, чтобы
бэкенд стартовал и жил **без объявления фронта в обязательном фундаменте**, а фронт был
**отдельной точкой входа**. Ценность — НЕ «сделать бэкенд тестируемым» (он уже тестируется
headless через `backend_ctl` при `BACKEND_CTL=1`), а **чистая граница фронт/бэк** как
фундамент, на котором дальше будет строиться конструктор фронт-части (GUI-конструктор, В3).

Сегодня (срез 2026-07-11) граница «почти чистая на импортах, но замусорена на композиции»:

- **Обратных импортов `backend → frontend` на уровне Python — 0.** Есть лишь: docstring-
  упоминания (`backend/__init__.py`, `backend/dev_settings.example.py`, `backend/launch.py:195`)
  и один **дефолтный строковый путь** `"frontend/styles/themes"` в `backend/config/manifest.py:77`.
- Сцепление живёт на **уровне конфигурации/композиции**:
  1. `backend/topology/base.yaml` — обязательный фундамент — бандлит процесс `gui`
     (`process_class: multiprocess_prototype.frontend.process.GuiProcess`) вместе с always-on
     инфраструктурой (`devices`). Т.е. backend-топология **называет** фронт-класс строкой.
  2. `app.yaml` (манифест) смешивает концерны: `styles.dir: frontend/styles/themes` (фронт)
     рядом с `system/base/pipeline/recipes` (бэк).
  3. `manifest.py:77` — хардкод дефолта `"frontend/styles/themes"` в backend-парсере конфига.
  4. `main.py` / `run.py` — **единый composition root**: строит launcher, который спавнит
     ВСЕ процессы, включая `gui`.
  5. `gui` объявлен в **ДВУХ местах** — в `base.yaml` И инлайн в 5 рецептах
     (`phone_sketch`, `hikvision_letter_robot`, `dataset_circle_capture`,
     `camera_robot_calibration`, `letter_angle_inspect`). Это прямое пересечение с recipe-осью.

Механика уже позволяет headless: `AppManifest.base: Path | None = None` (при `None` фундамент
не подмешивается), тест `test_pipeline_alone_is_headless` подтверждает работу бэкенда без GUI.
Задача — **сделать headless-режим первоклассным и осознанным**, а фронт — отдельной оболочкой
с явной точкой входа, зафиксировав границу sentrux-инвариантом.

## Цель

1. `gui` (презентация) вынесен из **обязательного** фундамента в **явный презентационный
   overlay**; бэкенд по умолчанию бутается headless (`devices` + pipeline, без `gui`).
2. Фронт получает **отдельную точку входа** (`multiprocess_prototype/frontend/run.py`),
   которая запускает систему с включённым презентационным overlay; существующий
   `run.py`/`main.py` умеет headless-режим (backend-only) явным флагом/манифестом.
3. Backend-слой конфига **перестаёт называть frontend строкой** в обязательном пути
   (ссылка на `GuiProcess` уезжает в overlay; дефолт `frontend/styles/themes` де-хардкодится).
4. Инвариант `backend/* → frontend/*` (импорт-уровень) зафиксирован в `.sentrux/rules.toml`.

## Не-цели (явный скоуп-cut)

- ❌ **НЕ переписывание виджетов** и не реорг доменных папок фронта (chrome/sources/… —
  это отдельная работа, см. `docs/refactors/2026-04_widgets_reorg.md`).
- ❌ **НЕ TabRegistry / механизм табов** — это NEW-D1 (5.10 S→M), отдельная задача В3.
- ❌ **НЕ конструктор фронта** — он строится ПОЗЖЕ, поверх этой границы (В3).
- ❌ **НЕ полностью независимый dual-launcher runtime** (фронт как отдельный ОС-процесс,
   аттачащийся к уже-живому бэкенду через сокет). Это направление, но НЕ в этом плане:
   (а) владелец сказал «пока хардкодом»; (б) грабли «два бэкенда в одном прогоне» —
   общий PID-реестр (исправлено Ф1.9) и SHM-cleanup конфликтуют между параллельными
   системами (см. память `project_concurrent_backends_trap`). Runtime-аттач — задача
   будущего конструктора (В3), здесь только фундамент под неё.
- ❌ **НЕ сокращение forward-импортов `frontend → backend`.** Сейчас `frontend/app.py`
   тянет `backend.launch/config/state/recipes` — это «хардкод-shell» по определению задачи;
   разбор на IPC-only контракт — работа конструктора (В3), здесь допустимо оставить как есть.
- ❌ **НЕ трогать recipe-инлайн объявления `gui`** до координации с C3/4.7 (см. Риски).

## Что «хардкод-shell» значит на практике

«Пока хардкодом» = фронт остаётся **тонкой прошитой оболочкой прототипа**, а не
generic-конструктором:

- презентационный overlay — **фиксированный файл** (`frontend/presentation.yaml`), не
  собирается динамически;
- точка входа фронта — **явный скрипт** (`frontend/run.py`), с прошитым выбором overlay;
- фронт по-прежнему **форвард-импортит** backend-сборку (`launch`, `config`, `state`) —
  это допустимо и ожидаемо на этом шаге;
- gui по-прежнему **спавнится тем же launcher'ом** (через overlay), а НЕ отдельным
  процессом-аттачем — «отдельная точка входа» здесь = отдельный **скрипт запуска** с
  презентацией ON, тогда как backend-only запуск даёт headless.

Ценность именно в **структурной развязке**: обязательный фундамент бэкенда больше не знает
про фронт, граница закреплена инвариантом, а точка входа фронта отделена — этого достаточно,
чтобы В3 начал строить конструктор поверх, не распутывая композицию заново.

## Vertical slice (tracer bullet)

**Task 1.1 — вертикальный срез через конфиг ⊕ launch ⊕ entry:** одним прогоном показать
и headless-бут бэкенда (без `gui`, зелёный `backend_ctl`), и бут фронта через отдельную
точку входа (окно появляется). Срез проходит через: манифест (split `base`↔`presentation`)
→ launch (подмешивание overlay) → entry (`frontend/run.py`). Feedback loop — сразу, не в конце.

## Execution order

### Phase 0 — Фиксация границы (диагностика, без кода)

- **Task 0.1:** Boundary-inventory + sentrux baseline. [PENDING]
  - **Module contract:** n/a

### Phase 1 — Структурная развязка (vertical slice)

- **Task 1.1:** **[VERTICAL SLICE]** split фундамента `gui`↔`devices`, `presentation:` в
  манифесте, headless по умолчанию, `frontend/run.py` entry. [PENDING]
  - **Module contract:** public-api-change (расширение `AppManifest`)
- **Task 1.2:** headless-режим существующего `run.py`/`main.py` (backend-only флаг/манифест).
  [PENDING] (depends on 1.1)
  - **Module contract:** impl-only

### Phase 2 — Де-хардкод backend-слоя + инвариант

- **Task 2.1:** убрать строковую ссылку на frontend из backend-конфига (дефолт
  `frontend/styles/themes` в `manifest.py`; styles как презентационный концерн). [PENDING]
  (depends on 1.1)
  - **Module contract:** impl-only
- **Task 2.2:** sentrux-инвариант `backend/* → frontend/*` в `.sentrux/rules.toml`. [PENDING]
  (depends on 1.1)
  - **Module contract:** n/a

### Phase 3 — Документация и хэндофф в В3

- **Task 3.1:** обновить STATUS/README прототипа, зафиксировать границу и хэндофф в
  NEW-D1/конструктор. [PENDING] (depends on 1.1, 1.2, 2.1, 2.2)
  - **Module contract:** n/a

---

## Task 0.1 — Boundary-inventory + sentrux baseline

**Level:** Middle (Sonnet, normal)
**Assignee:** investigator (или developer в режиме анализа)
**Goal:** Зафиксировать полную карту точек сцепления фронт/бэк и снять baseline метрик до правок.
**Context:** Перед структурной операцией нужна доказательная база: где именно бэкенд «знает»
про фронт (импорты, строки в конфиге, топологии, рецепты), и baseline sentrux/тестов, чтобы
после Phase 1–2 показать дельту (0 обратных импортов, headless зелёный).
**Files:**
- `plans/proto-frontend-carve.md` — дописать раздел «Инвентарь границы» (в этот же файл, в конец)

**Steps:**
1. `mcp__sentrux__session_start` (baseline) ИЛИ `/mcp-sentrux:sentrux-baseline` — записать
   quality/modularity/acyclicity + текущие boundaries.
2. `mcp__qex__search_code` + `Grep`: собрать ВСЕ точки, где `multiprocess_prototype/backend`
   (топологии, рецепты, конфиг, python) ссылается на `frontend` — включая строковые
   `process_class`, дефолтные пути, docstring.
3. Отдельно перечислить рецепты (`recipes/*.yaml`), объявляющие `gui` инлайн, и пометить их
   как «зона C3/4.7» (не трогать в этом плане).
4. Зафиксировать headless-контур: `test_pipeline_alone_is_headless`, `BACKEND_CTL`-сокет,
   `AppManifest.base: None`.

**Acceptance criteria:**
- [ ] Раздел «Инвентарь границы» перечисляет все 5 классов сцепления (импорт-докстринги,
      `base.yaml` gui, `app.yaml` styles, `manifest.py:77`, recipe-инлайн gui) с `file:line`.
- [ ] Записан sentrux baseline (session id / метрики) — для дельты в Phase 3.
- [ ] Явный список рецептов с инлайн-`gui` (5 шт.) помечен «после C3/4.7».

**Out of scope:** любые правки кода/конфига; только чтение и запись раздела в план.
**Edge cases:** архивные топологии (`backend/topology/archive/*`) — отметить, но не считать
активным сцеплением.
**Dependencies:** —
**Module contract:** n/a

---

## Task 1.1 — [VERTICAL SLICE] split фундамента + `presentation:` в манифесте + entry фронта

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** `gui` вынесен из обязательного `base.yaml` в отдельный презентационный overlay;
манифест выбирает overlay ключом `presentation:`; бэкенд без overlay бутается headless;
существует отдельная точка входа `frontend/run.py`, запускающая систему с презентацией.
**Context:** Это сердцевина карва — тонкий срез через все слои сцепления сразу, дающий
ранний feedback. После него виден и headless-бэкенд, и фронт-энтри.
**Files:**
- `multiprocess_prototype/backend/topology/base.yaml` — **убрать процесс `gui`**; оставить
  только always-on инфру (`devices`). Обновить шапку-докстринг (gui уехал в overlay).
- `multiprocess_prototype/frontend/presentation.yaml` — **создать** overlay-топологию:
  единственный процесс `gui` (`protected: true`, `process_class:
  multiprocess_prototype.frontend.process.GuiProcess`, `plugins: []`) — 1-в-1 то, что было в base.
- `multiprocess_prototype/backend/config/manifest.py` — добавить поле
  `presentation: Path | None = None` в `AppManifest`; резолв в `load_manifest` (по аналогии
  с `base`); докстринг.
- `multiprocess_prototype/backend/launch.py` — при сборке подмешивать `presentation` overlay
  (тем же `merge_topologies`, что и `base`) **если задан**; порядок: `base ⊕ presentation ⊕
  pipeline` (dedupe base-wins сохраняется). Найти точку, где сейчас мёржится `base`
  (`SystemBuilder.from_manifest`), и добавить overlay туда же.
- `multiprocess_prototype/app.yaml` — **не** добавлять `presentation` (headless по умолчанию);
  оставить как есть, но убедиться, что без `presentation` система собирается без `gui`.
- `multiprocess_prototype/frontend/run.py` — **создать** тонкую точку входа: venv-guard (как
  в `multiprocess_prototype/run.py`) + запуск через манифест с включённым `presentation`
  (напр. env `INSPECTOR_PRESENTATION=frontend/presentation.yaml` или отдельный
  `app.frontend.yaml` манифест, наследующий `app.yaml` + `presentation:`). Выбор механизма —
  прошитый (хардкод), см. Steps.

**Steps:**
1. Вырезать блок процесса `gui` из `base.yaml` → перенести дословно в новый
   `frontend/presentation.yaml` (сохранить `protected: true`).
2. Расширить `AppManifest` полем `presentation: Path | None = None` + резолв в
   `load_manifest` (копия ветки `base_raw`).
3. В `SystemBuilder` (launch.py) подмешать overlay: `merged = merge_topologies(base,
   presentation)` перед merge с pipeline, только если `manifest.presentation` не `None`.
   Сохранить существующий контракт merge (base-wins dedupe, конкатенация
   `display_definitions`).
4. Создать `frontend/run.py`: прошитый запуск с презентацией. Рекомендуемый механизм
   (хардкод, минимум новых сущностей): `frontend/run.py` выставляет
   `os.environ["INSPECTOR_PRESENTATION"]` в путь к `presentation.yaml` и вызывает
   `main.main()`; `load_manifest`/`resolve_manifest_path` читает env-overlay так же, как
   `INSPECTOR_MANIFEST`. (Альтернатива — отдельный `app.frontend.yaml`; выбрать одну, описать
   в докстринге, НЕ обе.)
5. Обновить `test_base_merge.py`: `test_base_provides_gui_process` →
   `test_presentation_overlay_provides_gui_process` (gui теперь в overlay, не в base);
   `test_pipelines_have_no_gui` остаётся; добавить `test_base_is_headless_infra_only`
   (base содержит `devices`, НЕ содержит `gui`); добавить
   `test_base_plus_presentation_adds_gui_once`.

**Acceptance criteria:**
- [ ] `python scripts/run_framework_tests.py` и таргетные тесты топологии зелёные.
- [ ] Сборка из `app.yaml` (без `presentation`) даёт configs БЕЗ процесса `gui`
      (assert в тесте, аналог `test_pipeline_alone_is_headless`, но для полного манифеста).
- [ ] `frontend/presentation.yaml` содержит ровно один процесс `gui` (protected), класс
      `multiprocess_prototype.frontend.process.GuiProcess`.
- [ ] `AppManifest.presentation` резолвится в абсолютный путь; `None` = headless.
- [ ] `SystemBuilder` при заданном `presentation` даёт merged с `gui` ровно один раз.
- [ ] `frontend/run.py` существует, документирован (какой overlay-механизм выбран), и
      импортируется без побочных эффектов (не стартует Qt на импорте).
- [ ] Демонстрация среза: (а) headless-бут (`BACKEND_CTL=1`, backend-only) поднимает систему
      без окна; (б) `frontend/run.py`-энтри поднимает систему с окном.

**Out of scope:** recipe-инлайн gui (5 рецептов) — НЕ трогать; сокращение forward-импортов
фронта; любые правки виджетов.
**Edge cases:**
- Рецепты, объявляющие `gui` инлайн, при запуске БЕЗ overlay (headless) всё ещё поднимут gui,
  т.к. рецепт сам его содержит — это **ожидаемо и вне скоупа** (реконсиляция — после C3/4.7).
  Задокументировать в докстринге `presentation.yaml`.
- `merge_topologies` base-wins: если overlay и pipeline оба дадут `gui` — победить должен
  overlay (проверить порядок аргументов merge; overlay мёржится ПЕРЕД pipeline).
- `protected: true` должен доезжать до proc_dict (регрессия У1) — покрыть тестом.
**Dependencies:** Task 0.1 (карта сцепления)
**Module contract:** public-api-change (`AppManifest` — публичный контракт конфига,
`interface`-эквивалент; расширение поля + докстринг + тест)

---

## Task 1.2 — headless-режим существующего `run.py`/`main.py`

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Существующая точка входа умеет явный backend-only режим (без презентации), не
полагаясь только на «манифест без presentation».
**Context:** После 1.1 headless = «манифест без `presentation`». Нужен явный, обнаруживаемый
способ сказать «подними бэкенд без фронта» из основной точки входа — для тестов, CI и
`backend_ctl`-сценариев, без правки yaml.
**Files:**
- `multiprocess_prototype/main.py` — распознать env/флаг headless (напр.
  `INSPECTOR_HEADLESS=1` ИЛИ CLI `--headless`), который **игнорирует** `presentation` даже
  если тот задан в манифесте (симметрия к `frontend/run.py`, который его включает).
- `multiprocess_prototype/backend/launch.py` — прокинуть флаг «не подмешивать presentation».

**Steps:**
1. Ввести единый резолвер презентации: `presentation` включён ⟺ (`manifest.presentation`
   задан ИЛИ env-overlay) И НЕ headless-флаг. Один источник истины, чтобы 1.1-entry и
   1.2-headless не разъехались.
2. Пробросить в `SystemBuilder.from_manifest(app, ..., include_presentation: bool)`.
3. Тест: `INSPECTOR_HEADLESS=1` + манифест С `presentation` → configs без `gui`.

**Acceptance criteria:**
- [ ] `INSPECTOR_HEADLESS=1` (или `--headless`) поднимает систему без `gui` даже при заданном
      `presentation` в манифесте.
- [ ] `frontend/run.py` и headless-режим используют ОДИН резолвер презентации (нет дубля логики).
- [ ] Тест на приоритет: headless-флаг перебивает `presentation`.

**Out of scope:** изменение поведения по умолчанию `app.yaml` (оно уже headless после 1.1).
**Edge cases:** одновременно `frontend/run.py` (presentation ON) и `INSPECTOR_HEADLESS=1` —
headless-флаг побеждает (документировать приоритет).
**Dependencies:** Task 1.1
**Module contract:** impl-only

---

## Task 2.1 — де-хардкод строковой ссылки на frontend в backend-конфиге

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Backend-парсер конфига (`manifest.py`) больше не содержит хардкод-дефолта
`"frontend/styles/themes"`; styles трактуются как презентационный концерн.
**Context:** Последняя строковая привязка backend→frontend вне overlay. `manifest.py:77`
дефолтит styles-каталог на `frontend/styles/themes`. Для чистой границы backend-слой не должен
знать раскладку фронта.
**Files:**
- `multiprocess_prototype/backend/config/manifest.py` — убрать литерал `"frontend/styles/themes"`
  из дефолта; сделать `styles` опциональным (`StylesRef | None`) ИЛИ дефолт-нейтральным
  (пустой/относительный без имени `frontend`), т.к. styles нужны только презентации.
- `multiprocess_prototype/app.yaml` — styles-путь остаётся здесь **явно** (не дефолтом);
  headless-бэкенд не читает styles.

**Steps:**
1. Проверить `mcp__qex__search_code` / `codegraph`: кто читает `manifest.styles` (только
   `frontend/app.py::apply_default_theme`?). Если только фронт — styles можно сделать
   опциональным полем без дефолта-frontend-пути.
2. Убрать литерал `frontend/styles/themes`; при отсутствии `styles` в yaml — `None`
   (headless не падает).
3. `frontend/app.py`: fail-loud если `styles` не задан, но презентация запускается
   (внятная ошибка вместо тихого дефолта).

**Acceptance criteria:**
- [ ] `grep -rn "frontend/styles" multiprocess_prototype/backend --include=*.py` = 0.
- [ ] Headless-манифест без `styles` грузится без ошибки.
- [ ] Фронт с отсутствующим `styles` даёт внятную ошибку (не тихий дефолт).
- [ ] Тесты `manifest`/`load_manifest` зелёные.

**Out of scope:** перенос самих файлов тем; докстринг-упоминания frontend в backend (они
безвредны — оставить или почистить попутно, не блокер).
**Edge cases:** существующий `app.yaml` уже задаёт `styles` явно — регрессии быть не должно.
**Dependencies:** Task 1.1
**Module contract:** impl-only

---

## Task 2.2 — sentrux-инвариант `backend/* → frontend/*`

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Обратный импорт `multiprocess_prototype/backend → multiprocess_prototype/frontend`
запрещён и проверяется sentrux (сейчас де-факто 0, задача — закрепить структурно).
**Context:** Граница уже чистая на импортах; без инварианта она может «поплыть» при развитии
конструктора. `.sentrux/rules.toml` уже содержит intra-prototype boundaries
(`domain→frontend`, `adapters→frontend`) — новый boundary ложится в тот же паттерн.
**Files:**
- `.sentrux/rules.toml` — добавить `[[boundaries]]` `from = "multiprocess_prototype/backend/*"`,
  `to = "multiprocess_prototype/frontend/*"`, `reason = "..."`.

**Steps:**
1. Добавить boundary-блок по образцу существующих (`domain→frontend`).
2. `mcp__sentrux__check_rules` / `/sentrux-check` — убедиться, что правило проходит (0 нарушений).
3. Если находятся нарушения (напр. новый импорт, добавленный в 1.x) — устранить (перенести
   в overlay/entry), не ослаблять правило.

**Acceptance criteria:**
- [ ] `.sentrux/rules.toml` содержит boundary `backend/* → frontend/*`.
- [ ] `/sentrux-check` (или `mcp__sentrux__check_rules`) — 0 нарушений нового правила.
- [ ] docstring-упоминания frontend в backend-python НЕ считаются нарушением (sentrux смотрит
      импорты, не строки) — подтвердить.

**Out of scope:** ужесточение прочих порогов sentrux (это H.5).
**Edge cases:** `frontend/run.py` импортит `main`/backend — это **forward** (fronт→backend),
разрешено; правило только про обратное направление.
**Dependencies:** Task 1.1
**Module contract:** n/a

---

## Task 3.1 — документация границы + хэндофф в В3

**Level:** Junior (Haiku, normal)
**Assignee:** docs-writer
**Goal:** Зафиксировать новую границу в STATUS/README прототипа и явно передать эстафету
конструктору фронта (NEW-D1 / В3).
**Context:** Следующий по оси D — NEW-D1 (TabRegistry) и далее конструктор фронта. Им нужна
явная точка опоры: «фронт отделён, вот его entry и overlay, вот инвариант, вот что осталось
(runtime-аттач, forward-импорты, recipe-инлайн gui)».
**Files:**
- `multiprocess_prototype/STATUS.md` — секция «Граница фронт/бэк»: headless по умолчанию,
  `presentation.yaml` overlay, `frontend/run.py` entry, sentrux-инвариант.
- `multiprocess_prototype/frontend/README.md` (создать/обновить) — как запускать фронт
  отдельно, что такое hardcoded shell, ссылка на В3.
- `multiprocess_prototype/backend/topology/base.yaml` — докстринг уже обновлён в 1.1 (сверить).

**Steps:**
1. Описать новую модель запуска: headless (`run.py`/`main.py`) vs фронт (`frontend/run.py`).
2. Перечислить **отложенное** (non-goals этого плана): dual-launcher runtime-аттач,
   сокращение forward-импортов, recipe-инлайн gui (после C3/4.7) — как вход для В3.
3. Дельта sentrux (baseline из 0.1 → after) — одна строка.

**Acceptance criteria:**
- [ ] `STATUS.md` описывает границу и оба режима запуска.
- [ ] `frontend/README.md` объясняет hardcoded shell + ссылку на В3/NEW-D1.
- [ ] Список отложенного явен (эстафета конструктору).

**Out of scope:** правки кода.
**Edge cases:** —
**Dependencies:** Task 1.1, 1.2, 2.1, 2.2
**Module contract:** n/a

---

## Риски и ограничения

1. **Пересечение с recipe-осью (C3 / 4.7) — главный риск.** `gui` объявлен инлайн в 5
   рецептах; C3 выносит модуль `recipe` в framework, 4.7 меняет assembly. Если карв тронет
   recipe-инлайн gui одновременно с C3/4.7 — merge-конфликты и двойная правка одной зоны.
   **Митигация:** этот план — **предусловие: исполнять ПОСЛЕ хвоста В1** (C3→4.7→C8).
   Phase 1 НЕ трогает рецепты (только `base.yaml` + манифест + launch overlay). Реконсиляция
   recipe-инлайн gui → отдельная задача после того, как recipe-модуль устоится.
2. **Параллельный merge 4.8 в main (другой агент).** Этот план НЕ редактирует
   `plan.md` constructor-master и файлы рецептов. Перед merge ветки в main — `git pull`/rebase
   на свежий main (4.8 мог уехать вперёд).
3. **Грабли «два бэкенда в одном прогоне»** (память `project_concurrent_backends_trap`):
   поэтому dual-launcher runtime-аттач вынесен в non-goals — общий PID-реестр и SHM-cleanup
   конфликтуют между параллельными системами. Здесь фронт спавнится тем же launcher'ом.
4. **`base` vs `presentation` порядок merge.** `merge_topologies` — base-wins dedupe; overlay
   должен мёржиться ПЕРЕД pipeline, чтобы презентация не перетёрлась и не задублировалась.
   Покрыть тестом (`test_base_plus_presentation_adds_gui_once`).
5. **Скрытые потребители `manifest.styles`.** Перед де-хардкодом (2.1) проверить codegraph/qex,
   что styles читает только фронт — иначе headless сломается.

## Регистрация в реестрах (для оркестратора)

- **current-path/plan.md:** добавить NEW-D2 в §4 (реестр NEW) и строку в §3-В3. Этот файл
  НЕ конфликтует с параллельным merge 4.8 (тот трогает constructor-master + рецепты).
  Регистрация выполнена в рамках этой ветки (одна строка §4 + один буллет §3-В3).
- **QUEUE.md:** после одобрения владельцем — добавить в волну В3 рядом с NEW-D1
  (обновляется при закрытии блока, не каждой задачи — здесь только пометка).
- **constructor-master:** НЕ трогать в этой ветке (параллельный агент); внесение NEW-D2 в
  соответствующую фазу — обычным порядком после merge 4.8.

## Критерий готовности (definition of done)

- Бэкенд стартует и живёт **без объявления фронта** в обязательном фундаменте (headless по
  умолчанию; `test`-assert configs без `gui` из полного `app.yaml`).
- Фронт — **отдельная точка входа** (`frontend/run.py`), поднимает систему с презентацией.
- **0 обратных импортов** `backend → frontend` (sentrux-инвариант зелёный).
- Backend-конфиг **не содержит** строкового литерала `frontend/styles/...`.
- Все фреймворк- и топология-тесты зелёные; sentrux-дельта неотрицательна.
