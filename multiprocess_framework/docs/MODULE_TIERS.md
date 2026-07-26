# Ярусная карта модулей — MODULE_TIERS.md

**Назначение.** Зафиксировать за каждым модулем `multiprocess_framework/modules/` ровно один **ярус**: `core` / `optional` / `frozen`. Ярус отвечает на вопрос «что будет, если модуль убрать»:

| Ярус | Определение | Что означает на практике |
|------|-------------|--------------------------|
| **core** | Без модуля **не бутится ни одно** приложение на фреймворке (прямая или транзитивная зависимость минимального boot-пути). | Развивается, покрывается манифестами/контрактами, ломать API нельзя без ADR. |
| **optional** | Подключается **по потребности** приложения. Минимальное приложение (`examples/minimal_app`) без него живёт. | Развивается, но приложение вправе его не знать. |
| **frozen** | Код **не трогаем**: не развиваем, не удаляем, новых потребителей не заводим. | Правки только по решению владельца; enforcement — boundary в `.sentrux/rules.toml` и/или контракт-тест. |

**Источник вердиктов:** GATE G0 (владелец, 2026-07-06) — [`plans/2026-07-06_constructor-master/plan.md`](../../plans/2026-07-06_constructor-master/plan.md) секция «GATE G0 §А». Настоящий документ — исполнение Ф8 H.1: карта сверена **с кодом**, а не с бумагой.

**Обновлено:** 2026-07-26 (Ф8 H.1, первичная сверка карта↔код).

> **Правило против дрейфа.** Эта таблица — единственный источник ярусов. Её сверяет контракт-тест [`modules/tests/test_module_tiers.py`](../modules/tests/test_module_tiers.py): каждый каталог-модуль на диске обязан иметь ровно одну строку, каждая строка — существующий каталог. Новый модуль без строки = красный тест.

---

## 1. Карта (27 модулей)

| Модуль | Ярус | Критерий |
|--------|------|----------|
| `base_manager` | core | Базовый класс всех менеджеров + `ObservableMixin` + `BaseAdapter`. Импортируется всеми. |
| `message_module` | core | `Message`/`MessageAdapter` — единица IPC. Dict at Boundary держится здесь. |
| `channel_routing_module` | core | CRM — общая база Logger/Error/Router/Stats. Транзитивно обязателен. |
| `logger_module` | core | Логирование процесса; создаётся в каждом процессе на boot. |
| `error_module` | core | Обработка ошибок процесса; наследник Logger, создаётся на boot. |
| `statistics_module` | core | Счётчики/окна агрегации; часть базового набора менеджеров процесса. |
| `dispatch_module` | core | Ядро диспетчеризации (`EXACT_MATCH`) — база router/command/CRM. Фичи beyond-EXACT_MATCH заморожены (§3). |
| `command_module` | core | Тонкий фасад над dispatch; команды процесса. |
| `router_module` | core | `AsyncSender`/`AsyncReceiver` — транспорт сообщений между процессами. |
| `config_module` | core | Конфиг на границе; обёртка над data_schema, участвует в boot каждого процесса. |
| `data_schema_module` | core | `SchemaBase`/`FieldMeta`/`FieldRouting`/`DataConverter` — ядро схем. Мертвецы модуля (dna_factory, version_manager, schema_visualizer, storage_manager) — KILL в H.2, не ярус. |
| `shared_resources_module` | core | PSR/ConfigStore/MemoryManager/QueueRegistry — разделяемые ресурсы, boot-обязательны. |
| `process_module` | core | База дочернего процесса (`ProcessModule`), плагинный рантайм. |
| `process_manager_module` | core | `SystemLauncher`/`ProcessRegistry`/Monitor/супервизия — оркестратор системы. |
| `worker_module` | core | LOOP/TASK-воркеры, lifecycle потоков внутри процесса. |
| `console_module` | core | `ConsoleManager` инстанцируется в **каждом** процессе (`process_managers.py`, `process_manager_process.py`) — модуль boot-обязателен. Интерактивный God-Mode заморожен как фича (§3). |
| `chain_module` | core | **Пересмотр вердикта G0 — см. §2.** Pipeline-движок `ProcessModule` стоит на `ChainRunnable` (C6(d), merge `22393392`): `generic/__init__.py` импортирует `PipelineExecutor` → `chain_module` на уровне импорта. |
| `app_module` | optional | Композиционная крыша («рыба», Ф5.11): собирает приложение из манифеста. Приложение вправе собираться руками — прототип так и делает. |
| `state_store_module` | optional | Реактивное дерево состояния; подключается приложениям, которым нужен shared state. |
| `registers_module` | optional | Рантайм вокруг экземпляров регистров (GUI-ориентирован). |
| `display_module` | optional | `DisplayRegistry` + YAML-persist; нужен только приложениям с дисплеями. |
| `service_module` | optional | `ServiceRegistry` + lifecycle сервисов; приложение может не иметь сервисов. |
| `frontend_module` | optional | PySide6-слой. Headless-приложение (`minimal_app`, BACKEND_CTL) живёт без него. Флагман Gen-1 заморожен как фича (§3). |
| `recipe` | optional | Крыша над рецептами (RecipeEngine/RecipeManager/миграции); приложение без рецептов её не подключает. |
| `actions_module` | optional | Building-blocks undo/redo (ActionBus PATCH + SnapshotHistory). Прод-undo прототипа идёт мимо — через domain-диспетчер (решение владельца 2026-07-08). |
| `event_module` | optional | Generic in-proc pub/sub (`EventBus` по `type(event)`); leaf-узел без зависимостей. |
| `telemetry_readmodel_module` | optional | Read-model телеметрии для GUI (ADR-136): запись всегда, чтение локально. Нужен потребителям телеметрии. |

**Итого:** core — 17, optional — 10, frozen — 0 (см. §2/§3).

**Границы карты.** Здесь только `multiprocess_framework/modules/`. Прикладные слои ярусов не имеют и живут по своим правилам: `Services/` (в т.ч. `sql` — выехал из framework в Phase 4.1, ADR-121, и в карту не входит), `Plugins/` (ADR-120), `multiprocess_prototype/`.

**Ярус ≠ слой.** Ярус — ось *важности* («что будет, если убрать»). Слой — ось *направления зависимостей* («кто кого вправе импортировать»), её вводит план [`framework-layer-grouping`](../../plans/framework-layer-grouping/plan.md): физическая перекладка 27 модулей в 9 папок-слоёв + enforcement через `import-linter`. Оси независимы: `chain_module` — ярус `core` и слой `execution`; `display_module` — `optional` и `catalogs`. После codemod Фазы 3 имена модулей изменятся (снимается суффикс `_module`) — таблицу §1 и контракт-тест придётся обновить, это внесено в чек-лист той Фазы.

---

## 2. Отличия от бумажной карты G0 (2026-07-06)

Карта G0 писалась до фаз Ф5-C6 и Ф7; при сверке с кодом разошлись три позиции. **Ни одна не является ре-интерпретацией вердикта: две — доборы, одна — фактический пересмотр.**

| # | Позиция | Было в G0 | Стало по коду | Почему |
|---|---------|-----------|---------------|--------|
| 1 | `chain_module` | **frozen**, «0 потребителей» | **core** | ⚠️ **Требует переподтверждения владельца.** Вердикт устарел: C6(d) (2026-07-13, merge `22393392`) поставил pipeline-движок `ProcessModule` на `ChainRunnable`. Импортёры: `process_module/generic/pipeline_executor.py`, `plugin_operation_step.py`, реэкспорт в `multiprocess_framework/__init__.py:125`. Boundary «никто не импортирует chain_module» **уронил бы прод** — поэтому не заводится. |
| 2 | `console_module` | вне таблицы ярусов (был только вердикт «модуль НЕ трогать») | **core** | Добор, не пересмотр: сам вердикт G0 №3 констатирует «ConsoleManager создаётся в КАЖДОМ процессе». Заморожена **фича** God-Mode, не модуль (§3). |
| 3 | `app_module`, `telemetry_readmodel_module` | отсутствовали (дрейф «20/21/22») | **optional** | Появились после G0: `app_module` — Ф5.11, `telemetry_readmodel_module` — 2026-07-18 (ADR-136). Это и есть «сверка H.1» из строки G0. |
| 4 | Механизмы форм 7b/7c/7d (`frontend_module`) | вердикт G0 №5: `WidgetRegistry` — **KILL после G2** | **frozen** (не kill) | Отменено более поздним гейтом: **GATE G2, владелец 2026-07-10** — «не удалять» → FREEZE. Ф5.6 закрыт decision-only, формализация frozen-яруса передана в H.1 — это §3 ниже. Строка «KILL после G2» в таблице G0 §Б устарела. |

**Следствие:** ярус `frozen` на уровне **модулей** сейчас пуст. Всё замороженное — фичи внутри живых модулей (§3). Это не ошибка карты, а факт: G0 замораживал ровно один целый модуль (`chain_module`), и тот ожил.

**Общий принцип владельца — FREEZE, а не KILL** (прецеденты: `actions_module` 2026-07-08, GATE G2 2026-07-10). Дремлющий рабочий и покрытый тестами код считается капиталом: цена хранения ниже риска потери. Поэтому `frozen` — рабочий ярус, а не «зал ожидания перед удалением». Удаление — только по явной per-item санкции владельца (GATE G4 / Ф8 H.2).

---

## 3. Замороженные фичи (внутри живых модулей)

Ярус `frozen` неприменим к модулю целиком, но применим к его частям. Источники — вердикты G0 §Б (2026-07-06) и **GATE G2 (2026-07-10)**, который для механизмов форм заменил KILL на FREEZE:

| Фича | Модуль | Вердикт | Enforcement |
|------|--------|---------|-------------|
| God-Mode консоли (интерактивный режим) | `console_module` | G0 №3: FREEZE только фичи, модуль core | доки + ревью |
| dispatch beyond-EXACT_MATCH (PATTERN/FALLBACK/CHAIN/ScenarioBuilder) | `dispatch_module` | G0 №2: FREEZE фич, модуль core | доки + ревью (0 прод-вызовов) |
| Флагман Gen-1: `FrontendManager`, `WindowManager`, `LayoutComposer` (7d) | `frontend_module` | G0 №5 + G2: FREEZE | boundary `.sentrux/rules.toml` (прикладные слои не импортируют `application/`) + контракт-тест `test_frozen_frontend_flagship_has_no_consumers`; маркер `legacy_gen1` в тестах |
| `WidgetRegistry` (7d) | `frontend_module` | ~~G0 №5: KILL после G2~~ → **G2: FREEZE** | доки + ревью; удаление снято с повестки H.2 |
| Binding-aware механизм форм: `builders_binding` + `FormContext` (7b) | `frontend_module` | G2: FREEZE | доки; активный прод-путь — 7a legacy (`form_ctx=None`), 7b дремлет |
| `entity_editor` ~1778 LOC (7c) | `frontend_module` | G2: FREEZE | доки; 0 живых потребителей (верифицировано E4) |

**Почему такой список, а не «удалить мёртвое».** Владелец стабильно выбирает **FREEZE вместо KILL**: дремлющий рабочий и покрытый тестами механизм — капитал и опциональность (7b — готовый reactive/undoable write, если ADR-COMM-002 когда-нибудь оживёт). «Унификация N→1» здесь означает *сузить активный путь до одного*, а не физически удалить остальные. Отчёт-первоисточник по 4 механизмам — [`e4-forms-mechanism-diff.md`](../../plans/2026-07-06_constructor-master/e4-forms-mechanism-diff.md).

**Правило Ф4 (остаётся в силе):** манифесты и контракты пишутся только ярусам `core`/`optional`; замороженным фичам — нет.

---

## 4. Публичный API модуля (NEW-10)

Инварианты, проверяемые контракт-тестом `modules/tests/test_module_tiers.py`:

1. **`interfaces.py` у каждого модуля** — 27/27. Внешний потребитель берёт типы/протоколы оттуда, а не из глубины пакета.
2. **`__all__` в `__init__.py`** — 27/27, и каждое имя из `__all__` реально резолвится.
3. **`__all__` в `interfaces.py`** — 27/27: контракт модуля перечислен явно, а не «всё, что не начинается с подчёркивания».
4. **Тесты модуля видны прогону** — каждый каталог `*/tests` под `modules/` присутствует в `testpaths` файла `modules/pytest.ini`.

**Не входит в H.1 — «один вход на модуль».** Правило «внешний импорт только через крышу модуля или `interfaces.py`» сейчас нарушено массово: 682 глубоких импорта (`modules.X.<sub>...`) против 116 плоских из потребителей (`multiprocess_prototype`/`Services`/`Plugins`/`examples`); только `process_module.plugins` даёт 302. Это рефакторинг масштаба отдельной задачи, а не сверка карты — вынесен из H.1 явно, чтобы не превращать «карта = код» в многодневную переделку импортов.

---

## 5. Связанные документы

| Что | Где |
|-----|-----|
| Статус и LOC по модулям | [`MODULES_STATUS.md`](../MODULES_STATUS.md) |
| Границы ответственности (кто за что отвечает) | [`MODULES_RESPONSIBILITY_MAP.md`](MODULES_RESPONSIBILITY_MAP.md) |
| Интеграционная карта конструктора | [`CONSTRUCTOR_BLUEPRINT.md`](CONSTRUCTOR_BLUEPRINT.md) |
| Вердикты G0 и исполнение KILL | [`plans/2026-07-06_constructor-master/plan.md`](../../plans/2026-07-06_constructor-master/plan.md) (§GATE G0, Ф8 H.2) |
