# Plan: Конструктор интерфейса — оболочка, подключения, виджет как единица (gui-constructor)

> **2026-09-27, потребитель:** [`robot-protocol-v2`](../robot-protocol-v2/plan.md) ред. 2 кладёт GUI робота пакетом `robot.*` в `Services/robot_comm/gui/` (Ф6 v2) и зависит от Task 1.0 (правило `Services/<x>/gui/`) и 1.5 (контекст виджета). Ручки Пульта робота — по адресам `devices/robot_*`.

- **Slug:** gui-constructor
- **Дата:** 2026-09-26
- **Статус:** DRAFT — ждёт ревью (`reviewer` MODE: plan) и approve владельца
- **Ветки:** `feat/gui-constructor-<фаза>` (`-f1` … `-f5-<срез>`), от свежего `main`, по ветке на фазу; worktree — по
  правилам `/dev:team`
- **Решение (ЧТО):** [`frontend-constructor/constructor-layers.md`](../frontend-constructor/constructor-layers.md) — запись
  владельца 2026-09-26. Этот план — **КАК**. Запись не пересказывается.
- **Ревью:** [`docs/reviews/2026-09-26_gui-constructor-layers-cto.md`](../../docs/reviews/2026-09-26_gui-constructor-layers-cto.md) —
  ACCEPT WITH CONDITIONS; каждое условие и находка — в таблице ниже.
- **Заменяет:** Ф4 (T4.1–T4.6) и Ф5 (`minimal_gui`) плана [`frontend-constructor`](../frontend-constructor/plan.md);
  дизайн T4.1 [`gui-bootstrap-design.md`](../frontend-constructor/gui-bootstrap-design.md) остаётся историей.

## Контекст

Владелец 2026-09-26: фронт собирается конструктором из виджетов; окна и вкладки у оболочки; фреймворк — конструктор
из модулей без предметных слов; `Services` — вертикальные срезы с пакетами виджетов; прототип — тонкий слой инспекции;
эталоны `examples/minimal_app` и `examples/minimal_gui`; Пульт — виджет ручек; следующие потребители — вкладка
симулятора с редактором слоёв и вкладка разметки. CTO принял направление с условиями: реестр подключений сразу,
веер кадров и неблокирующая подписка в контракте, оболочка вне Gen-1 `windows/`, подпакет `gui/` и правила для
`Services`, синхронизация соседних планов.

**Дизайн** (редакция T4.1, разбита под лимит 32 КБ):
- [`design-boot.md`](design-boot.md) — спека пакета, стадии, базовая линия характеризации, hot-reload;
- [`design-connection-context.md`](design-connection-context.md) — реестр подключений, Protocol рантайма, контекст
  виджета и его каналы, шаблоны «ревизия» и «долгая задача», Р-B/Р-C/Р-D;
- [`design-shell-layout.md`](design-shell-layout.md) — оболочка, раскладка и замок, `WidgetSpec`, место пакетов и
  правила, `inspector.classic`, Пульт и адреса.

## Цели

- Встроенный GUI собирается `GuiBootstrap` из спеки пакета через реестр подключений; оператор разницы не видит
  (характеризация boot-порядка равна до/после).
- Окна, доки, раскладка, замок, статус подключений — у оболочки фреймворка (`frontend_module/host/`); встроенный GUI
  и `apps/gui_client` — одна оболочка.
- `examples/minimal_gui` собирается без прототипа, `Services`, `Plugins` и проходит headless CI против `minimal_app`
  по сокету — приёмка gui-service 1.4 со стороны фреймворка.
- Вкладка симулятора — пакет `sim.*` из `Services/line_sim/gui/` на втором подключении; отвал одного бэкенда не
  трогает другой.
- Пульт: ручки из разных областей в одном виджете, адрес общий с `backend_ctl`.

## Out of scope

- Промоушен кита из прототипа (frontend-constructor Ф3, Блок В) и расщепление `frontend_module` (rework Р-4, 3.4).
  Этот план **добавляет** файлы; переносит codemod.
- Сеть, токен, TLS клиента (gui-service Ф2); `RemoteGuiRuntime` и `apps/gui_client` как код — gui-service 1.4/3.1.
- Разметка датасета и её сервис — план [`dataset-annotation`](../dataset-annotation/). Здесь только резерв канала
  файлов в контракте контекста.
- Локальный UI обучения — не драйвер конструктора (обучение может уехать в облачный сервис, владелец 2026-09-26).
- Qt Advanced Docking System (Ф5, DEFERRED). Удаление Gen-1 `frontend_module` (решение rework, не этого плана).

## Решения (decisions log)

- **2026-09-26 (владелец):** всё содержание `constructor-layers.md` — слои, эталоны, форма конструктора, Пульт,
  следующие потребители. Не повторяется здесь.
- **2026-09-26 (CTO, условия 1–5):** реестр подключений с первого дня; `WidgetContext` с веером кадров и неблокирующей
  подпиской; `inspector.classic` = центральная часть окна + легаси-дверь с sunset-тестом; оболочка в
  `frontend_module/host/`; раскладка: YAML декларирует, блоб хранит правки, оба по `objectName`, замок переживает
  `restoreState`; `reload_namespace` — список; правила слоёв; синхронизация соседей.
- **2026-09-26 (планирование):** правила слоёв — **первая задача Ф1 (1.0)**, а не Ф2, как предлагал бриф: CTO
  поставил их условием «до первой строки кода». Rejected: правила вместе с оболочкой — границы появились бы после
  кода, который в них должен лечь.
- **2026-09-26 (планирование, по синтаксису sentrux):** «`Services` без Qt кроме `*/gui/*`» одним `[[boundaries]]`
  не выражается — пути буквальные префиксы, исключений нет (`.claude/plugins/mcp-sentrux/README.md:55-60`, греп ключей
  `rules.toml`). Решение: `examples ↛ Services/Plugins` — sentrux, `Services ↛ Qt` — грепный контракт-тест с тремя
  поимённо разрешёнными автономными инструментами. Rejected: перечислить в sentrux каждый Qt-free подкаталог каждого
  сервиса — новый сервис по умолчанию был бы не защищён.
- **2026-09-26 (планирование):** рантайм = одно подключение; флаги рестарта/остановки — у процесса/хоста, не у
  подключения (при N подключениях «перезапустить интерфейс» — одно событие).
- **2026-09-26 (планирование):** `pack_loader` — в этом плане (Task 1.4), а не в gui-service 1.4: пакет по строке
  грузит и встроенный GUI (`presentation.yaml`). `RemoteGuiRuntime` остаётся в gui-service 1.4.
- **2026-09-26 (планирование):** Ф5 frontend-constructor (`minimal_gui`) поглощается Task 2.4: та же цель, новая
  форма (оболочка + раскладка + пакет вместо трёх вкладок `app_spec.py`). Tree-nav MVP-вкладка из старой T5.1 —
  не условие (правило двух потребителей: кит tree-nav уже потребляется прототипом, эталону он не нужен).
- **2026-09-26 (сверка с `dataset-annotation`):** канал файлов — `ctx.files.fetch(ref={provider, name, id, variant},
  on_done)`, неблокирующий, на подключение; транспорт (HTTP loopback, адрес в состоянии) и клиент реализует план
  разметки (его 2.1); здесь — член контракта и заглушка (1.5). Правило `Services ↛ Qt` кроме `gui/` — **владелец этот
  план, Task 1.0**, и это грепный контракт-тест, **не** строка `rules.toml` (проверять наличие теста, а не
  `grep PySide6 .sentrux/rules.toml` — там уже есть чужие правила про `PySide6`, проверка дала бы ложное «есть»).
- **2026-09-26 (планирование):** одно место пакета симулятора — `Services/line_sim/gui/`; gui-service
  `architecture.md` правится (был `apps/line_sim/gui_spec.py`).

## Условия и находки CTO → где закрыты

| # | Что | Где |
|---|---|---|
| Усл. 1 | редакция T4.1 (43 727 → три файла ≤ 32 КБ, содержание выше) | `design-*.md`; Ф1 1.3–1.5, Ф2 2.1–2.2 |
| Усл. 2 | синхронизация соседей | правки 2026-09-26 в: `frontend-constructor/plan.md`, gui-service (`plan.md`, `architecture.md`, `context.md`, `phase-1`, `phase-3`), rework 2б.2, `line-sim-layer-editor/plan.md`, `gui-bootstrap-design.md`, `constructor-layers.md` |
| Усл. 3 | правила `Services ↛ Qt` кроме `gui/`, `examples ↛ Services/Plugins` | Task 1.0 (форма — по синтаксису, см. решения) |
| Усл. 4 | вопрос (i) владельцу, развести четыре «Пульта» | (i) закрыт владельцем 2026-09-26 (`constructor-layers.md` → «Имена»); четыре значения — `design-shell-layout.md` §6.3, плашка терминологии в gui-service `plan.md` |
| Усл. 5 | числа (89 файлов / метод счёта; `line_sim` Qt-free) | `design-shell-layout.md` §4 (line_sim Qt-free, греп перепроверен); число 89 в плане не используется |
| Н1 | N рантаймов vs один Protocol | `design-connection-context.md` §1; Task 1.3 (контракт-набор на двух подключениях) |
| Н2 | веер кадров, блокирующая подписка | `design-connection-context.md` §3.3; Task 1.5 (литералы), 2.4, 3.3 |
| Н3 | gui-service 3.1 строит докинг второй раз | Task 2.1 — докинг у оболочки; gui-service 3.1 переписана: только подключения |
| Н4 | `GuiHostWindow` в удаляемом `windows/` | `frontend_module/host/`; строка в rework 2б.2; T4.6 вынут из Блока В |
| Н5 | пакеты в `Services` vs Qt-free контракты | `Services/<svc>/gui/`; Task 1.0; `architecture.md` исправлен |
| Н6 | числа | см. усл. 5 |
| Н7 | нативные доки: перенос между окнами программный | `design-shell-layout.md` §2.3; Task 2.1 «Переместить в окно» |
| Н8 | «Пульт» занят четырежды; дрейф `rules.toml:128` → `129-131` | §6.3 дизайна; ссылка исправлена в `design-connection-context.md` §5 |
| Н9 | `inspector.classic` без sunset | `design-connection-context.md` §3.6; Task 1.5 (sunset = 1), 2.2, 5.1 |
| Н10 | hot-reload не видит `Services/*/gui` | `design-boot.md` §5 (`reload_prefixes` списком); Task 1.4 |
| Идея f | правило двух потребителей ≠ право резать по нулю | `phase-5-split-and-promote.md` шапка; риски ниже |

## Фазы и задачи

Канон запуска каждой задачи с механизмом (`.claude/CLAUDE.md`): tester до кода в worktree на пред-коммите →
исполнитель → break-injection лида с предсказаниями по обоим наборам → живой стенд → reviewer синхронно.

### Phase 1 — Разборка сборки: стадии, реестр, контекст — [`phase-1-boot-split.md`](phase-1-boot-split.md)

- Task 1.0: Правила слоёв: `examples ↛ Services/Plugins` (sentrux), `Services ↛ Qt` кроме `gui/` (контракт-тест) [PENDING] (нет зависимостей) — **Module contract:** n/a
- Task 1.1: Характеризация boot-порядка, утечки слушателей, инвентари шины/кадров/`RuntimeDeps` [PENDING] (нет) — **Module contract:** n/a
- Task 1.2: Механическая разборка `run_gui` на стадии-функции (бывш. T4.2 + T4.5) [PENDING] (1.1) — **Module contract:** impl-only
- Task 1.3: `ConnectionRegistry` + `GuiHostRuntime` + `InProcessRuntime`, шина во фреймворк (бывш. T4.4) [PENDING] (1.2) — **Module contract:** new-full
- Task 1.4: `GuiBootstrap` + `GuiAppSpec` каталогом + `pack_loader` + зона hot-reload списком (бывш. T4.3) [PENDING] (1.3) — **Module contract:** public-api-change
- Task 1.5: `WidgetContext`, вкладки виджетами 1:1, `FrameHub`, `ctx.legacy_deps` + sunset [PENDING] (1.4) — **Module contract:** public-api-change

### Phase 2 — Оболочка, `inspector.classic`, `minimal_gui` — [`phase-2-shell-minimal-gui.md`](phase-2-shell-minimal-gui.md)

- Task 2.1: Оболочка `frontend_module/host/`: окна, доки, раскладка YAML + блоб, замок, «Переместить в окно» (бывш. T4.6) [PENDING] (Ф1) — **Module contract:** new-full
- Task 2.2: `inspector.classic` — центральная часть `MainWindow` в оболочке [PENDING] (2.1) — **Module contract:** impl-only
- Task 2.3: `minimal_app` шаги 1–2: счётчик в состоянии, команда с ответом [PENDING] (нет) — **Module contract:** impl-only
- Task 2.4: `examples/minimal_gui` + headless CI против `minimal_app` по сокету [PENDING] (2.1, 2.3, gui-service 1.4) — **Module contract:** new-full

### Phase 3 — Второй бэкенд, шина, пакет `sim.*` — [`phase-3-second-backend-sim.md`](phase-3-second-backend-sim.md)

- Task 3.1: N подключений в оболочке, изоляция отказов [PENDING] (2.1; вместе с gui-service 3.1) — **Module contract:** impl-only
- Task 3.2: Шина интерфейса с событиями, объявленными в пакетах [PENDING] (1.5) — **Module contract:** new-lite
- Task 3.3: Пакет `sim.*` в `Services/line_sim/gui/`: сцена, пульт ленты [PENDING] (3.1, 3.2, gui-service 3.2) — **Module contract:** new-full
- Task 3.4: Помощник «черновик + ревизия» (второй потребитель — редактор слоёв) [PENDING] (1.5, `line-sim-layer-editor` 1.2) — **Module contract:** new-lite
- Task 3.5: `minimal_app` шаги 3–4 [PENDING — по вытягиванию] (2.3, 2.4, 4.2 для шага 3) — **Module contract:** impl-only

### Phase 4 — Пульт — [`phase-4-pult-knobs.md`](phase-4-pult-knobs.md)

- Task 4.1: `KnobAddress` — один адрес для GUI, `backend_ctl`, агентов [PENDING] (нет) — **Module contract:** new-lite
- Task 4.2: `fw.pult` — модель ручки и отрисовка движком форм [PENDING] (4.1, 2.1, gui-service 1b.2c) — **Module contract:** new-lite
- Task 4.3: «Вынести на Пульт» у любого поля регистра [PENDING] (4.2, 3.2) — **Module contract:** impl-only
- Task 4.4: `Services/control_panel` на адресах `backend_ctl` [PENDING] (4.1) — **Module contract:** public-api-change

### Phase 5 — Дробление и перенос по нужде — [`phase-5-split-and-promote.md`](phase-5-split-and-promote.md)

- Task 5.1: Дробление `inspector.classic` [PENDING — по нужде] (Ф2, T3.0) — **Module contract:** impl-only
- Task 5.2: Срезы прототипа → `Services/<svc>/gui/` [PENDING — по нужде] (Ф2, Ф3, T3.0) — **Module contract:** new-full на срез
- Task 5.3: Qt Advanced Docking System [DEFERRED] (2.1) — **Module contract:** impl-only

## Порядок исполнения

```
1.0 ∥ 1.1 → 1.2 → 1.3 → 1.4 → 1.5 → 2.1 → 2.2 → [gui-service 1.4] → 2.4
                                         2.3 (∥ 2.1/2.2) ─────────┘
2.4 → 3.1 ∥ 3.2 → [gui-service 3.1, 3.2] → 3.3 → 3.4 (когда поставлен редактор слоёв)
4.1 (в любой момент) → 4.2 (после 1b.2c) → 4.3 (после 3.2);  4.4 после 4.1
Ф5 — по нужде
```

- **Один писатель `app.py`:** 1.2–1.5 и gui-service 1b.2b — строгая очередь.
- **Заполнители пауз (ревью CTO плана 2026-09-26):** 2.3 и 4.1 (Middle, без зависимостей, `app.py` не трогают) идут в
  паузах Senior+-цепочки 1.2 → 1.3 → 1.4 → 1.5 → 2.1 → 2.2 (один писатель `app.py`) — пока ведущая задача на
  тестере, инъекциях или ревью. Не больше одного заполнителя одновременно; цепочку они не задерживают.
- **Стенд:** 1.3 (`ui_tap_ping`), 1.5, 2.2, 2.4 (CI, без стенда владельца), 3.1, 3.3 — один live-трек на бэкенд
  (8765 инспектор, 8766 симулятор); координировать с live-задачами line-sim и gui-service.
- **Окно codemod rework:** если откроется во время Ф1–Ф3 — план на паузе, не сливается поверх codemod (как gui-service).

## Отношения с соседними планами

| План | Что этот план берёт | Что отдаёт | Граница |
|---|---|---|---|
| [`gui-service`](../2026-09-22_gui-service/plan.md) | 1b.2a/1b.2b-pre/1b.2c (каталог, копии регистров, вердикт до формы); `RemoteGuiRuntime`, `apps/gui_client` (1.4); `ConnectionStore` (3.1); штатные виджеты против сима (3.2) | стадии, реестр, контекст, оболочку, загрузчик — предпосылка 1.4 вместо T4.1–T4.4 | докинг — здесь (2.1); подключения клиента — там |
| [`frontend-constructor`](../frontend-constructor/plan.md) | инвентарь T3.0, промоушен кита Ф3, гейты Ф6 | заменяет Ф4 (T4.1–T4.6) и Ф5 | Блок В остаётся там; T4.x/T5.x там помечены «перенесено» |
| [`framework-architecture-rework`](../framework-architecture-rework/plan.md) | окно codemod (не мешать), Р-4 | новые файлы `frontend_module/bootstrap/*`, `host/*`, `knobs/*` — в список 2б.2 | удаление Gen-1 (3.0) — решение rework, не этого плана |
| [`line-sim`](../line-sim/plan.md) | дерево `apps/line_sim` 8766, команды `belt.*` (2.3a), контракт слоёв 3.1a | точку посадки Qt-частей Ф6 (пакет `sim.*`) | бэкенд симулятора — там |
| [`line-sim-layer-editor`](../line-sim-layer-editor/plan.md) | — | пакет `sim.*`, помощник ревизии (3.4), шина (3.2) | команды слоёв на бэкенде и виджеты редактора — там; «автономное окно» заменено вкладкой пакета |
| [`dataset-annotation`](../dataset-annotation/) | транспорт и клиент канала файлов (его 2.1) | форма `ctx.files.fetch` в контракте, `WidgetSpec`/контекст (Ф1 1.5) для его 2.5b, правило `Services ↛ Qt` (1.0), шаблоны «ревизия»/«долгая задача» | сервис датасета, виджет разметки, адаптер `AnnotationPorts` до 1.5 (закат — его 2.5b) — там |

## Риски

- **Разборка `run_gui` меняет порядок тихо** — характеризация 1.1 до кода, инъекция перестановки.
- **Контракт подогнан под одно подключение** — контракт-набор на двух подключениях с 1.3; `RemoteGuiRuntime`
  подключается к тому же набору в gui-service 1.4.
- **Шина — Qt-тип** (открыто T4.1 §9): если инвентарь 1.1 покажет Qt-сигнальных потребителей, член `bus` уходит из
  Qt-free Protocol — переписывание контракт-набора 1.3. Ранний сигнал — отчёт 1.1.
- **Легаси-дверь становится единственной** — sunset-тест = 1 с 1.5; рост — красный.
- **Правило двух потребителей используют как нож** — Ф5 и этот раздел: строим по двум, не режем по нулю; Gen-1
  заморожен, не удаляется этим планом.
- **Числа сьют и строк устарели** — baseline переснимается в 1.1 первым шагом; числа T4.1 помечены «(T4.1)».
- **Окно codemod rework** пересекается по `frontend_module/` — план на паузе, новые файлы размечены доменом Р-4
  (`design-shell-layout.md` §7).
- **Стенд один** — live-задачи 1.3/1.5/2.2/3.1/3.3 не параллелятся с live-задачами line-sim/gui-service на том же порту.
- **Тестовый канон (STRICT):** tester на каждой задаче, один раз на механизм, до кода; break-injection по каждому
  свойству; reviewer синхронно после каждой задачи.

## Открытые вопросы

1. **Р-A, Р-B, Р-C, Р-D, Р-F** T4.1 владелец не оспорил, но явно не утверждал (`constructor-layers.md:106`). План
   на них стоит; подтверждение нужно до старта Task 1.3 (Р-B, Р-C) и 1.4 (Р-A, Р-F).
2. **Набор ручек Пульта без GUI** — нужна ли команда `backend_ctl`, читающая раскладку рабочего места, или агентам
   достаточно общего адреса (Ф4, «Открыто»).
3. **Миграция геометрии `INNOTECH/Inspector`** на ключ `AppIdentity` — одноразовое чтение; устраивает ли владельца
   на операторских машинах (`design-shell-layout.md` §2.4).
4. **Порядок с разметкой:** её 2.5b ждёт Task 1.5 этого плана; её 2.1 (канал файлов) может прийти раньше 1.5 — тогда
   `FileChannel` Protocol нужно взять из `design-connection-context.md` §3.4 до кода 1.5 (решение лида при постановке).
5. **Экранирование `/` в адресах** — если в именах процессов/регистров/полей встретится `/` (проверяет Task 4.1 грепом).
6. **Ловит ли sentrux внешний `to = "PySide6/*"`** — существующие правила этого не доказывают (проба Task 1.0).
