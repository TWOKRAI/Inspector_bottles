# План: frontend-constructor — выделение фронт-конструктора из прототипа во фреймворк

**Статус:** READY (2026-07-18). Независимое ревью investigator-агентом пройдено: вердикт «готов с правками», все 5 правок внесены; балльная оценка — раздел «Балльная оценка» ниже.
**Slug:** `frontend-constructor` → `plans/frontend-constructor/plan.md` (multi-phase). Ветки по фазам: `docs/fc-f0-recon`, `refactor/fc-f1-facade-flip`, `feat/fc-f2-frontend-entry`, далее по фазе.
**Роль:** исполнение волны В3 (ось NEW-D) из `plans/current-path/plan.md`; `plans/proto-frontend-carve.md` (NEW-D2, DRAFT) поглощается фазой Ф2.
**Директива владельца:** «всё универсальное перетащить из прототипа во фреймворк» — прототип оставляет себе только прикладное.

---

## Контекст (зачем)

Бэкенд-конструктор уже выделен: `app_module` (composition root) + `examples/minimal_app` (headless-рыба, CI-smoke). Фронтенд — нет: GUI-кит фреймворка (`frontend_module`, ~22.6k LOC) наполовину состоит из мёртвого поколения, а живая генерик-машинерия (~5-6k LOC) живёт в прототипе. Анализ показал:

**frontend_module (фреймворк) — два поколения:**
- **Gen-1 МЁРТВ для v3** (v1/v2 удалены e128b930): `application/` (FrontendManager, WindowManager, run_process_attached_frontend, 683 LOC), `core/{widget_registry,window_registry,default_factories,layout_composer}`, `schemas/` (WidgetDescriptor...), `configs/`, `windows/loading_window`. Прототип их НЕ использует (0 потребителей, только forward-compat комментарии в `auth_state.py`). **Но фасад `__init__.py` экспортирует ТОЛЬКО Gen-1**, README quick-start документирует Gen-1, STATUS.md устарел (2026-04-17).
- **Gen-2 ЖИВОЕ**: `tabs/` (TabSpec/TabRegistry, ADR-135), `widgets/tabs/` (MVP-базы, SectionSpec, 3335 LOC), `state/` (TelemetryViewModel поверх telemetry_readmodel_module, FE-005), `components/` (6672 LOC: контролы + примитивы), `bridge/` (CommandSender request/response FE-004), `managers/`, `debug/` (ui_event_tap), `core/app_identity` (NEW-2 ✅). Потребляется deep-импортами мимо фасада (`widgets.tabs` ×29).
- Обратных зависимостей framework→frontend нет; бренда «Inspector» в прод-коде нет (гейт В3 частично выполнен). **Инверсия в тестах:** `tests/test_section_spec.py:219-225` и `tests/test_register_view_show_toggle.py:14-15` импортируют прототип.

**multiprocess_prototype/frontend (~44.7k LOC) — генерик, утёкший в приложение:**
- Composition root — бог-функция `run_gui()` **~749 строк** (`app.py:60-808`; вместе с хелперами `_setup_bridge_callbacks`/`_setup_timers` — композиционная поверхность ~955 LOC в 3 функциях), DI-контейнер сознательно удалён; установка приватных атрибутов чужого процесса (`process._stall_dump_fp`, `_ui_event_tap`, `_ui_command_sender`; чтение `process._bridge`/`_gui_state_proxy`); hot-reload чисткой `sys.modules` (`process.py:291-321`); захардкоженные wildcard-подписки `processes.**/system.**/devices.**/calibration.**` (`process.py:93-110`).
- **Доменно-нейтральная машинерия в прототипе** (кандидаты на промоушен): `GuiStateBindings`+`glob_match` (реактивный биндинг «glob-путь → свойство виджета», replay из read-model), `DataReceiverBridge` (worker→Qt main, классификация конвертов), `RequestRunner` (FE-004 называет его framework-контрактом), **весь `forms/`** (2259 LOC schema-driven формы поверх `field_info.extract_fields`; внутри дубль `builders_legacy` 363 vs `builders_binding` 486), примитивы `BaseAdminPanel`/`ActionToolbar`/`SlotSelector`/`SectionedForm`/`SideNavLayout`/`TreeNavWidget`, `qt_event_bus`, `wheel_guard`, `prefs/` (QSettings), `FrameworkRuntime` (раскол уже заявлен в `runtime_deps.py:23-26` — «переезд во framework Ф5.11», не выполнен).
- **13 шимов-реэкспортов** уже промоутнутого (`bridge/` ×7, `widgets/primitives/` ×6) — долг на удаление.
- **Device-quad копипаста** ×5+ (vfd, robot, hikvision, devices_common, calibration...): `_request()` ×5, `_extract_top()` ×3, пары `_bind_state/_unbind_state`, 18 фабрик `build_*_controls`.
- **MVP-несогласованность**: на фреймворковых MVP-базах только вкладка settings; ~17 презентеров ad-hoc.
- Deep-импорты мимо фасадов: `registers_module.core.field_info` ×28, `frontend_module.widgets.tabs` ×29.

**Смежное:** план `plans/framework-layer-grouping/plan.md` не учитывает 27-й модуль `telemetry_readmodel_module` (создан 2026-07-18) и переезд `backend_ctl → tooling/`; счётчики в MODULES_STATUS/CONSTRUCTOR_BLUEPRINT отстали (25). Ветка `feat/backend-ctl-debug-console` выполняется параллельно — **`backend_ctl/` не трогать**.

---

## Решения (зафиксировать в Ф0, подтвердить владельцем)

- **Р1. `telemetry_readmodel_module` в layer-grouping → слой `state/`** (`state/telemetry_readmodel`). Онтология: проекция дерева StateStore (read-model рядом с write-моделью state_store); «телеметрия» — профиль использования. `observability/` отвергнут (та группа — производящая сторона: logger/error/stats эмитят), `foundation/` отвергнут (не примитив, потребители наверху). Альтернатива `observability/` допустима — решает владелец при патче grouping-плана.
- **Р2. `proto-frontend-carve.md` — поглотить**: шапка `SUPERSEDED → plans/frontend-constructor/plan.md Ф2`, файл остаётся справочной спецификацией (freeze, не kill). Предусловие carve-плана (хвост В1: C3/4.7) уже выполнено 2026-07-12.
- **Р3. Секвенирование с layer-grouping**: Ф0–Ф2 — **до** codemod (Ф0 патчит их mapping; Ф1 — только внутри frontend_module; Ф2 — только прототип+yaml), Ф3+ — **после** (промоушены кладутся сразу в финальные пути `application/frontend/*`, enforcement пишется поверх их `.importlinter`). Если grouping откладывается — весь план допустимо исполнить до него (промоушены в `modules/frontend_module/*`, codemod перепишет бесплатно). Жёсткий инвариант: **кодовые фазы никогда не параллельны Фазе 3-codemod** (freeze-окно).
- **Р4. Gen-1 — freeze, не kill** (правило владельца): убрать из фасада, пометить докстринг-маркерами `LEGACY Gen-1 (frozen)`, тесты остаются под pytest-маркером `legacy_gen1`. Не удалять.
- **Р5. Принцип промоушена — «всё универсальное → фреймворк»**: критерий = 0 упоминаний домена (bottle/inspection/устройства/пути прототипа). Прототип оставляет: ConnectionMap, `build_rm_from_topology`, `TABS: list[TabSpec]`, ThemeVariables (значения темы), device-секции, whitelist телеметрии, wildcard-подписки (как декларации).
- **Р6. Пограничный набор (~1.8k LOC) решается СПИСКОМ в Ф0 (T0.5), а не суждением инвентаря** (правка независимого ревью — иначе директива «всё универсальное» выполнится частично): `windows/main_window.py` (766 LOC) → **промоутится генерик-шелл `GuiHostWindow`** (меню/доки/статусбар/tab-host/apply-theme; прикладная компоновка остаётся в прототипе, T4.6); `dialogs/` helper `confirm_unsaved_changes` (стандарт платформы) → промоут; `prefs/` (QSettings) → промоут; `styles/` (загрузчик тем vs значения) / `permissions.py`+`auth_context.py` (глю vs матрица) / `startup_checks.py` — классифицировать в T0.5 поимённо.

```
Ф0 (доки) → Ф1 (гигиена fw) → Ф2 (граница фронт/бэк, ex-NEW-D2)
   ║  [freeze-окно: layer-grouping Ф0–Ф5; ветка backend_ctl влита до codemod]
Ф3 (промоушен всего универсального) → Ф4 (GuiBootstrap) → Ф5 (examples/minimal_gui)
   → Ф6 (enforcement+доки) → [опц. волны] Ф7 (device-kit) → Ф8 (MVP-унификация)
```
Ядро = Ф0–Ф6 (~12–16 дней); Ф7/Ф8 — отрезаемый хвост.

---

## Порядок выполнения (сводный, пошагово)

**Блок А — сейчас, ДО codemod layer-grouping** (каждая фаза = своя ветка от свежего main, merge по завершении):
1. **Ф0** — ветка `docs/fc-f0-recon`: T0.1 патч layer-grouping (27-й модуль → `state/telemetry_readmodel`, заметка backend_ctl→tooling/, precondition «влить feat/backend-ctl-debug-console») → T0.2 счётчики 25→27 → T0.3 SUPERSEDED для proto-frontend-carve + регистрация в current-path/QUEUE → T0.4 этот план в `plans/frontend-constructor/plan.md` → T0.5 пограничный список Р6 поимённо. Гейт: link-check.
2. **Ф1** — ветка `refactor/fc-f1-facade-flip`: T1.1 инвентарь Gen-1 → T1.2 фасад-флип → T1.3 README/STATUS → T1.4 перенос 2 тестов-инверсий → T1.5 фикс докстринга. Гейт: fw+proto сьюты offscreen, sentrux, qt-smoke.
3. **Ф2** — ветка `feat/fc-f2-frontend-entry`: T2.0 baseline → T2.1 presentation-overlay + `frontend/run.py` → T2.2 headless-флаг → T2.3 де-хардкод styles → T2.4 sentrux boundary → (T2.5 опц.) → T2.6 доки. Гейт: тесты топологии, live headless + capabilities, qt-mcp окно.

**Блок Б — внешние предусловия (вне этого плана):**
4. Влить параллельную ветку `feat/backend-ctl-debug-console` (другой чат).
5. Исполнить `plans/framework-layer-grouping` Ф0–Ф5 (codemod, freeze-окно — наши кодовые фазы стоят).

**Блок В — ПОСЛЕ группировки** (пути `application/frontend/*`):
6. **Ф3** — промоушены отдельными PR в порядке: T3.0 инвентарь-свип → T3.3 glob_match+GuiStateBindings (свой узкий Protocol) → T3.4 qt_event_bus/wheel_guard/prefs → T3.5 реализации-примитивы ×6 + dialogs-helper → T3.6 forms-движок (T3.6b опц.) → T3.7 FrameworkRuntime → **T3.1 DataReceiverBridge + T3.2 RequestRunner в конце** (после/с оглядкой на G.2) → T3.8 удаление 13 шимов. Гейт после каждого PR: сьюты + hot-reload qt-smoke + свип остатков.
7. **Ф4** — T4.1 дизайн-док (ревью владельца) → T4.2 механическая разборка + характеризация boot-порядка → T4.3 GuiBootstrap+GuiAppSpec → T4.4 GuiHostRuntime вместо `process._*` → T4.5 колбэки/таймеры → T4.6 GuiHostWindow. Полное трёхуровневое ревью (рисковое вскрытие). Здесь закрывается гейт В3 «вкладка одним TabSpec».
8. **Ф5** — T5.1 examples/minimal_gui (3 вкладки, вкл. tree-nav MVP) + туториал → T5.2 CI gui-smoke. Приёмка В3 — не резать.
9. **Ф6** — T6.1 import-linter public-interface → T6.2 добивка deep-импортов → T6.3 sentrux → T6.4 BLUEPRINT/ADR/STATUS.

**Блок Г — опциональные волны (режутся в любой точке, но без них «дублирование» ~5.5/10):**
10. **Ф7** — T7.1 device-kit → T7.2 пилот vfd+robot (wire-характеризация) → T7.3+ остальные устройства по PR.
11. **Ф8** — MVP-унификация: сначала вкладки с дуальным VM/legacy-путём телеметрии, затем processes → pipeline → plugins → displays → recipes.

Правила на всём протяжении: `backend_ctl/` не трогать; коммиты с `Refs: plans/frontend-constructor/plan.md`; статусы задач ведутся только в этом плане; каждый агент-исполнитель бранчуется от проверенного SHA main.

---

## Ф0 — Реконсиляция планов и доков (docs-only, ~0.5 дня)

| # | Задача | Файлы | Acceptance |
|---|--------|-------|------------|
| T0.1 | Патч layer-grouping: 27-й модуль в mapping/дерево (`telemetry_readmodel_module` → `state/telemetry_readmodel`), счётчики «26»→«27»; заметка «backend_ctl → tooling/ — отдельный пост-codemod план (BCTL-DECISIONS), grouping лишь переписывает импорты внутри backend_ctl»; в preconditions Фазы 3 поимённо: влить `feat/backend-ctl-debug-console` | `plans/framework-layer-grouping/plan.md` | grep «26 модул» = 0; mapping = 27 строк |
| T0.2 | Счётчики модулей 25→27 (+app_module, +telemetry_readmodel) | `MODULES_STATUS.md`, `docs/CONSTRUCTOR_BLUEPRINT.md` | оба перечисляют 27 (только счётчик+строки карты; полный ре-райт — Фаза 5 grouping) |
| T0.3 | proto-frontend-carve.md → SUPERSEDED; регистрация frontend-constructor в `current-path` §В3 и QUEUE.md | 3 файла | link-check зелёный; статусы фаз ведутся только в новом плане |
| T0.4 | Создать `plans/frontend-constructor/plan.md` с решениями Р1–Р6 | новый план | владелец подтвердил Р1–Р6 |
| T0.5 | Пограничный список (Р6): поимённая классификация `main_window.py`/`styles/`/`dialogs/`/`prefs/`/`permissions.py`/`auth_context.py`/`startup_checks.py` → `promote/app/frozen` | раздел плана | у каждого файла решение и целевой путь; «суждению T3.0» остаются только тривиальные случаи |

### T0.5 — Пограничный список (Р6, классификация выполнена 2026-07-18)

Критерий: 0 упоминаний домена (bottle/defect/inspection/устройства) → `promote`; значения/компоновка/матрица → `app`; ADR-замороженное → `frozen`. Грепы домена по 3 неоднозначным файлам (`permissions.py`/`auth_context.py`/`startup_checks.py`) дали **0 доменных терминов** — все generic-глю.

| Файл (`multiprocess_prototype/frontend/`) | LOC | Домен-хиты | Классификация | Целевой путь / примечание |
|---|--:|--:|---|---|
| `windows/main_window.py` | 766 | — | **split** | generic-шелл `GuiHostWindow` (меню/доки/статусбар/tab-host/apply-theme) → `frontend/windows/` (T4.6); прикладная компоновка остаётся в прототипе |
| `widgets/dialogs/` (helper `confirm_unsaved_changes`) | — | — | **promote** | стандарт платформы (memory `feedback_dialog_conventions`) → `frontend/components/`; доменные диалоги остаются |
| `prefs/` (QSettings-обёртка) | — | — | **promote** | generic → `frontend/core/prefs/` (T3.4) |
| `styles/theme_loader.py`, `styles/style_manifest.py` | — | — | **promote** | загрузчик тем (generic) → `frontend/core/styles/`; `styles/themes/` (значения) → **app** |
| `permissions.py` | 54 | 0 | **promote (глю)** | generic RBAC-глю → framework; матрица ролей/значения — как декларация остаётся в прототипе (уточнить в T3.0) |
| `auth_context.py` | 47 | 0 | **promote** | generic → framework (T3.4/T3.7 рядом с runtime) |
| `startup_checks.py` | 169 | 0 | **promote** | generic startup-валидация → framework; проверить прикладные проверки поимённо в T3.0 |

Тривиальные случаи (чистые promote/shim-delete) остаются суждению инвентаря T3.0; здесь закрыты все 7 пограничных из Р6.

## Ф1 — Гигиена frontend_module (до codemod, ~1 день)

| # | Задача | Acceptance |
|---|--------|------------|
| T1.1 | Инвентарь Gen-1 с grep-доказательствами 0 потребителей (application/ 683, core/{widget_registry,window_registry,default_factories,layout_composer}, schemas/ 340, configs/ 75, windows/ 107, schema_adapter.py); таблица «живое/frozen» в STATUS | у каждого файла Gen-1 — доказательство; спорные классифицированы |
| T1.2 | **Фасад-флип `__init__.py`**: `__all__` = живое поколение (протоколы interfaces + tabs + state + app_identity + фасады components/widgets.tabs); Gen-1 убран из фасада, пакеты остаются импортируемыми с маркером `LEGACY Gen-1 (frozen <дата>)`; Gen-1 тесты → маркер `legacy_gen1`; `__version__` bump | fw-suite зелёный; grep `frontend_module.application` вне модуля = 0 (инвариант) |
| T1.3 | README/STATUS переписать под Gen-2: quick-start = TabSpec+TabRegistry+MVP+формы+TelemetryViewModel; Gen-1 — секция «Legacy» | quick-start не упоминает FrontendManager вне Legacy |
| T1.4 | Убрать инверсию тестов: `test_register_view_show_toggle.py` → тесты прототипа; прототипную часть `test_section_spec.py:219-225` → в тесты settings-вкладок прототипа | grep `multiprocess_prototype` по `frontend_module/tests` = 0; оба сьюта зелёные |
| T1.5 | Фикс докстринга `data_schema_module/core/descriptor_meta.py:23` (несуществующий импорт) | пример импортируется |

**Гейты:** `run_framework_tests.py` + pytest прототипа (offscreen), sentrux не хуже, qt-smoke.

## Ф2 — Граница фронт/бэк прототипа (поглощённый NEW-D2; до codemod, ~1.5-2 дня)

Задачи = Task 0.1/1.1/1.2/2.1/2.2/3.1 из `proto-frontend-carve.md` (остаётся справочной спецификацией):
- **T2.0** Boundary-inventory + sentrux baseline.
- **T2.1** `gui` из `backend/topology/base.yaml` → `frontend/presentation.yaml` overlay; `AppManifest.presentation`; `SystemBuilder: base ⊕ presentation ⊕ pipeline`; entry **`multiprocess_prototype/frontend/run.py`**; 4 теста топологии.
- **T2.2** headless-флаг основного входа (`INSPECTOR_HEADLESS=1`/`--headless`); headless перебивает presentation.
- **T2.3** де-хардкод `manifest.py:77` (`frontend/styles/themes`); styles опционален; фронт fail-loud.
- **T2.4** sentrux boundary `prototype/backend/* → frontend/*` forbid.
- **T2.5 (опц)** реконсиляция 5 рецептов с инлайн-`gui` (разблокирована; режется).
- **T2.6** STATUS/README прототипа: режимы запуска.

**Acceptance:** headless по умолчанию (app.yaml без presentation → configs без gui, тест); `frontend/run.py` поднимает окно; sentrux backend→frontend зелёный.
**Гейты:** тесты топологии, live headless (`BACKEND_CTL=1` + capabilities), qt-mcp probe окна.

> === далее freeze-окно layer-grouping; пути ниже в пост-grouping виде `application/frontend/*` (при исполнении до grouping — те же под `modules/frontend_module/*`) ===

## Ф3 — Промоушен ВСЕГО универсального из прототипа (~4-6 дней, 6-9 PR)

**T3.0 Полный пофайловый инвентарь-свип** `multiprocess_prototype/frontend/` → сателлит `plans/frontend-constructor/promotion-inventory.md`: каждый файл классифицируется `promote | app | frozen | shim-delete` (bias по Р5: доменно-нейтральное → promote). Особо проверить пограничные: `windows/main_window.py` (766 LOC — generic-шелл vs прикладная компоновка), `styles/` (загрузчик тем vs значения), `prefs/` (QSettings-обёртка — generic), `dialogs/` (helper `confirm_unsaved_changes` — стандарт платформы из memory), `permissions.py`/`auth_context.py` (generic-глю vs прикладная матрица), `startup_checks.py`, `managers/theme_presets_manager.py` (возможный дубль fw-версии), `actions/` (ActionBus-обвязка — frozen, ADR-COMM-002 не исполняется), `state/telemetry_history.py`, `state_delta_message`.

**Единый рецепт промоушена** (для каждого PR): (1) контракт-first — Protocol/экспорт в `interfaces.py` + FE-запись в DECISIONS; (2) `git mv` код+тесты; (3) переписать все импорт-сайты прототипа, qex/grep-свип = 0 остаточных, **новых шимов не оставлять**; (4) grep домена по промоутнутому = 0; (5) аудит `except Exception` промоутнутых файлов (silent swallow во framework не заносим — сузить/залогировать); (6) fw+proto сьюты, sentrux, hot-reload qt-smoke.

Порядок по зависимостям:

| # | Что | Куда (fw) |
|---|-----|-----------|
| T3.1 | `DataReceiverBridge` (`bridge_impl.py`) + `IDeltaSource` Protocol — **дефолтно в КОНЦЕ фазы** (В4/G.2 «единый конверт» по роадмапу идёт ПОСЛЕ В3 и почти наверняка не влит) | `frontend/bridge/data_receiver.py` |
| T3.2 | `RequestRunner` — тоже в конце фазы (та же причина) | `frontend/bridge/` (закрывает FE-004) |
| T3.3 | `glob_match` + `GuiStateBindings` (`state/bindings.py`) | `frontend/state/` |
| T3.4 | `qt_event_bus`, `wheel_guard`, `prefs/` | `frontend/core/` |
| T3.5 | **Реализации-примитивы ×6** (НЕ путать с шимами T3.8 — другой набор!): action_toolbar, base_admin_panel, sectioned_form, side_nav_layout, slot_selector, tree_nav_widget (+dialogs-helper из T0.5) | `frontend/components/primitives/` |
| T3.6 | **Forms-движок** (~2259 LOC): form_builder, factory/{builders_binding,kinds,json_editor}, field_editor, register_view, view_mode_toggle; `builders_legacy` — с LEGACY-маркером. **T3.6b (опц):** схлопывание legacy→binding под характеризационными тестами | `frontend/forms/` |
| T3.7 | `FrameworkRuntime` (split из `runtime_deps.py`; `RuntimeDeps(FrameworkRuntime)` остаётся в прототипе) | `frontend/bootstrap/runtime.py` |
| T3.8 | Удаление **13 шимов-реэкспортов** (bridge ×7: command_sender/command_validator/diff_engine/system_commands/wire_monitor/wire_protocol/plugin_register_resolver; primitives-шимы ×6: crud_table/entity_card/master_detail/status_indicator/standard_tab_layout/diff_scroll_tab_layout) + чистых реэкспортов из T3.0 | прототип |

**Acceptance:** ~4-6k LOC генерик-кода во фреймворке с тестами; 13+ шимов удалены; grep остаточных путей = 0; hot-reload жив (промоутнутое ушло из purge-зоны `process.py`); sentrux/quality не хуже.
**DX-регресс (задокументировать честно):** промоутнутые виджеты/формы перестают подхватываться hot-reload'ом прототипа (purge-зона — только `multiprocess_prototype.frontend.*`) — правка framework-кода требует рестарта GUI. Зафиксировать в README прототипа (T2.6) и в контракте reload (T4.1).

## Ф4 — Composition root → GuiBootstrap во фреймворке (~3-4 дня; рисковое вскрытие → полное ревью)

| # | Задача | Acceptance |
|---|--------|------------|
| T4.1 | Дизайн-док `gui-bootstrap-design.md`: `GuiAppSpec` (identity, theme, tabs, subscriptions, telemetry-suffixes, hooks), стадии `identity→theme→runtime→state→tabs→window→timers→show`, `GuiHostRuntime` (легализация приватных атрибутов), контракт hot-reload (purge только app-namespace; DX-регресс из Ф3 описан явно); дизайн `GuiHostWindow` (T4.6) | ревью владельца до кода |
| T4.2 | Механическая разборка композиционной поверхности (~955 LOC: `run_gui` 60-808 + `_setup_bridge_callbacks` + `_setup_timers`) на стадии-функции в прототипе; каждая стадия — коммит + qt-smoke. **Acceptance ужесточён (ревью):** характеризационный тест boot-последовательности — зафиксировать порядок attach листенеров/подписок/старта таймеров ДО разборки, сверить ПОСЛЕ (smoke не ловит ordering-регрессы) | характеризация boot-порядка совпадает |
| T4.3 | `GuiBootstrap` в `frontend/bootstrap/` + перевод app.py на `GuiAppSpec` (домен остаётся декларациями: ConnectionMap, TABS, ThemeVariables, wildcard-подписки) | `run_gui` заменён `build_app_spec()+GuiBootstrap.run()`; **сложность не мигрирует в спеку**: app_spec-модуль ≤ ~300 строк деклараций, hooks — только именованные функции (не лямбда-простыни) |
| T4.4 | `process.py`: wildcard-подписки — параметр приложения; `install_runtime(GuiHostRuntime)` вместо тыканья `process._*`; контракт ui_event_tap сохранён | grep `process\._` присвоений из app.py = 0; `ui_tap_ping` зелёный |
| T4.5 | `_setup_bridge_callbacks`/`_setup_timers` → стадии/декларации | вложенные колбэки ликвидированы |
| T4.6 | **`GuiHostWindow`** (Р6, правка ревью): генерик-шелл из `main_window.py` (766 LOC) — меню/доки/статусбар/tab-host/apply-theme → `frontend/windows/`; в прототипе остаётся прикладная компоновка | новое приложение получает шелл из фреймворка; main_window прототипа — тонкая доменная надстройка |

**Гейт В3 здесь:** тест «вкладка добавляется одним TabSpec без правки framework».

## Ф5 — examples/minimal_gui (~1.5-2 дня; приёмка В3 — НЕ резать)

- **T5.1** `examples/minimal_gui/`: `run.py`, presentation-overlay поверх minimal_app, `app_spec.py` с **3 вкладками**: schema-форма поверх регистра minimal_app + панель TelemetryViewModel + **одна нетривиальная вкладка на MVP-базе с tree-nav** (`BaseTreeNavTab`+`TreeNavTabPresenter`+`SectionSpec`) — доказательство, что кит держит не только плоские формы (правка ревью). README-туториал «интерфейс за 30 минут» с рубрикой шагов (проверочный шаг: 4-я вкладка одним TabSpec).
- **T5.2** CI job `gui-smoke` (по образцу examples-smoke): `QT_QPA_PLATFORM=offscreen`, boot, вкладки построены, чистое закрытие.

**Acceptance:** рыба ≤ ~300 LOC app-кода; 0 импортов прототипа; CI зелёный; туториал воспроизведён по шагам. **Честная оговорка (в DoD):** minimal_gui доказывает добавление вкладок и MVP/tree-nav, но НЕ полный паритет со сложными вкладками уровня pipeline — тот доказывается самим прототипом на промоутнутом ките.

## Ф6 — Enforcement + доки (~1.5-2 дня)

- **T6.1** import-linter public-interface для frontend: потребление через фасад/interfaces/белый список суб-фасадов (`tabs`, `widgets.tabs`, `forms`, `components`, `state`, `bridge`, `bootstrap`).
- **T6.2** Добивка deep-импортов: `registers_module.core.field_info` ×28 (реэкспорт в фасаде registers + свип), state_store deep ×10, `forms.form_context` ×11.
- **T6.3** sentrux: `framework/* → prototype/*` forbid актуализировать.
- **T6.4** Доки: BLUEPRINT GUI-раздел (Gen-2: TabSpec/GuiBootstrap/minimal_gui), 3-4 ADR (фасад-флип, промоушены, GuiBootstrap), MODULES_STATUS, сверка WIDGET_COOKBOOK.

**Acceptance:** `lint-imports` зелёный; grep-гейты в CI/make check. **Паттерн гейта исправлен (ревью):** НЕ голый `Inspector=0` (ложно упадёт на легитимном UI-вокабуляре `SchemaInspectorPanel`/`InspectorPanel`/`InspectorHeader` — 19 хитов), а домен-паттерн `bottle|defect|inspection|Inspector_bottles` по прод-коду frontend_module, исключая доки; deep-imports вне белого списка = 0.

## Ф7 — Device-kit (опц. волна, ~3-5 дней, режется в любой точке)

- **T7.1** `frontend/widgets/tabs/device_kit/`: `DevicePresenterBase` (`_request()` через RequestRunner, `_extract_top/_extract`), `StateBoundController` (bind/unbind-lifecycle поверх GuiStateBindings, авто-уборка), контракт section-factory поверх SectionSpec; обновить MVP_TEMPLATE.
- **T7.2** Пилот vfd + robot с характеризационными wire-тестами «те же команды/подписки» до/после.
- **T7.3+** Остальные по одному PR: hikvision, devices_common, phone, camera, neural, calibration.

**Acceptance per-устройство:** −30-50% LOC, 0 приватных `_request`, wire-характеризация без дрейфа.

## Ф8 — MVP-унификация презентеров (опц. волна, поэтапно)

Реальный объём: grep даёт **37 классов `*Presenter`** в прототипе (оценка «~17 ad-hoc» занижена — пересчитать в инвентаре T3.0: часть вложенные/уже на MVP-базе). Первыми — вкладки, держащие **отложенный остаток** плана `gui-telemetry-read-model` (сам Task 3.1 — DONE 2026-07-16; не вырезан дуальный VM/legacy путь — зависят немигрированные вкладки), затем processes → pipeline → plugins → displays → recipes. Каждая вкладка — отдельный PR на TabPresenterBase/TreeNavTabPresenter. Ф7 предварительно снимает device-презентеры из списка.

---

## Балльная оценка: до → после (независимое ревью, investigator-агент)

Независимый рецензент верифицировал ~90% фактуры по коду и оценил честно (без завышения: 151 `except Exception` в прототипе почти все останутся; без Ф8 презентеры остаются ad-hoc; minimal_gui не доказывает паритет с pipeline-вкладкой; риск регресса при разборке run_gui реален).

| # | Ось | ДО | Ядро Ф0-6 | +Хвост Ф7-8 | Обоснование |
|---|-----|:--:|:---------:|:-----------:|-------------|
| 1 | Переиспользуемость GUI-кита | 3 | 7.5 | 8.5 | генерик (~5-6k LOC) в прототипе → промоушен + GuiBootstrap + GuiHostWindow + minimal_gui; потолок ~8.5 — прикладные вкладки всегда custom |
| 2 | Правдивость фасада / инкапсуляция | 2 | 8.5 | 8.5 | фасад экспортит мёртвый Gen-1, живое — deep-импортами (×38/×28) → фасад-флип + public-interface линтер |
| 3 | Чистота границы фронт/бэк | 3 | 8 | 8 | gui в обязательном фундаменте, нет headless/входа, `process._` инъекция → headless-default + `frontend/run.py` + sentrux forbid |
| 4 | Composition root | 2 | 7.5 | 7.5 | бог-функция ~749 строк, DI удалён → staged GuiBootstrap; **природный потолок**: `except`-остаток, runtime-в-process |
| 5 | Дублирование во фронте | 3 | 5.5 | 8 | 13 шимов + device-quad ×5 + legacy/binding + презентеры; **ядро убирает только шимы+формы — основное сокращение в ОТРЕЗАЕМОМ хвосте**; без Ф7/Ф8 ось остаётся ~5.5 |
| 6 | Enforcement фронт-границ | 2 | 8 | 8 | нет линтера/гейтов → public-interface + sentrux + CI-grep (домен-паттерн) |
| 7 | DX нового GUI-приложения | 2 | 7.5 | 8 | нет рыбы/туториала → minimal_gui (3 вкладки, вкл. tree-nav MVP) + туториал; потолок: «30 минут» для простых приложений |
| 8 | Тестируемость / тесты | 4 | 7.5 | 8 | инверсия тестов, smoke не ловит ordering → инверсия убрана + gui-smoke offscreen + характеризация boot/форм |
| 9 | Согласованность доков | 3 | 8.5 | 8.5 | STATUS от 2026-04, README про мёртвое поколение, счётчики 25 vs 27 → Ф0/Ф1/Ф6 |
| 10 | Соответствие трендам | 5 | 7.5 | 8.5 | schema-driven+TabSpec есть, MVP юзает 1 вкладка → GuiAppSpec декларативный; потолок: full-DI отвергнут владельцем |
| | **Среднее** | **≈2.9** | **≈7.6** | **≈8.2** | |

**Вердикт рецензента:** готов к исполнению **с правками** (все 5 внесены в этот план: GuiHostWindow/пограничный список Р6+T0.5+T4.6; усиление minimal_gui до tree-nav MVP; домен-паттерн вместо `Inspector=0`; характеризация boot-порядка + лимит app_spec в Ф4; фактические уточнения — run_gui 749, два разных набора «primitives ×6», 37 презентеров, статус Task 3.1, T3.1/T3.2 в конец Ф3 дефолтом).

---

## Риски

| Риск | Митигация |
|------|-----------|
| Пересечение с codemod layer-grouping (~1970 импортов) | Р3: Ф0–Ф2 до, Ф3+ после; никогда не параллельно Фазе 3-codemod |
| Альтернатива Р3 (весь план до grouping) = две волны импорт-переписывания подряд | Честно признать стоимость: промоушены добавят churn в зону codemod; допускать только если grouping откладывается надолго; иначе ждать |
| Ф3-Ф6 блокируются, если grouping слипается | Escape-клапан Р3; Ф0-Ф2 самодостаточны и дают ценность сами по себе |
| Параллельная ветка backend_ctl | `backend_ctl/` не трогаем; контракт ui_event_tap — acceptance T4.4 (ui_tap_ping) |
| G.2 «единый конверт» трогает bridge-швы | Старт T3.1/T3.2 после merge G.2, иначе в конец Ф3 |
| Hot-reload (sys.modules purge) ломается промоушенами | Контракт reload в T4.1; qt-smoke hot-reload после каждого промоушен-PR |
| Разборка run_gui — поведенческий регресс | T4.2 механическая, отдельными коммитами; полное трёхуровневое ревью (рисковое вскрытие) |
| builders_legacy vs binding — тонкие отличия | Характеризационные тесты дерева виджетов; схлопывание T3.6b опционально |
| Скрытый потребитель Gen-1 | T1.1 инвентарь с grep-доказательствами; пути остаются импортируемыми (freeze) |
| Тихие except Exception уезжают во framework | Шаг 5 рецепта промоушена (аудит только промоутнутых файлов) |

## Верификация (сквозная)

1. `python scripts/run_framework_tests.py` + pytest прототипа (`QT_QPA_PLATFORM=offscreen`) — после каждой задачи.
2. sentrux `session_start/end` per-фаза: quality/coupling не хуже; `check_rules` зелёный.
3. qt-smoke: прототип с `QT_MCP_PROBE=1` + qt_snapshot — вкладки строятся, hot-reload жив, ui_tap отвечает.
4. Live headless: `BACKEND_CTL=1` + `capabilities` (Ф2, Ф4).
5. grep/qex-свипы: остатки старых путей = 0 после каждого промоушена; `process\._` из app.py = 0.
6. CI: examples-smoke + новый gui-smoke; `lint-imports` (Ф6).
7. Коммиты: Conventional Commits + `Why:/Layer:/Refs: plans/frontend-constructor/plan.md`.

## DoD плана

- Гейт В3 закрыт: вкладка одним TabSpec (тест Ф4 + туториал Ф5); CI-гейт домен-паттерна (`bottle|defect|inspection|Inspector_bottles` = 0 по прод-коду frontend_module).
- Headless по умолчанию; фронт — отдельная точка входа; sentrux backend→frontend зелёный.
- Фасад frontend_module = живое поколение; Gen-1 заморожен (не удалён, не потребляется).
- Всё доменно-нейтральное из прототипа — во фреймворке (~5-7k LOC с тестами, вкл. GuiHostWindow-шелл); 13+ шимов удалены; пограничный список Р6 закрыт поимённо.
- Композиционная поверхность (~955 LOC в 3 функциях) разобрана на GuiBootstrap-стадии; характеризация boot-порядка совпадает; 0 приватных присвоений чужих атрибутов.
- examples/minimal_gui (3 вкладки, вкл. tree-nav MVP) в CI offscreen; туториал воспроизведён по шагам (оговорка: паритет с pipeline-сложностью доказывает прототип, не рыба).
- import-linter public-interface зелёный; BLUEPRINT/STATUS/ADR согласованы (27 модулей).

## Открытые вопросы владельцу (не блокируют старт Ф0)

1. Р1: слой telemetry_readmodel — рекомендую `state/` (альтернатива `observability/`).
2. Р3: окно Ф3+ — рекомендую после grouping (альтернатива «весь план до grouping» = две волны импорт-переписывания, дороже).
3. builders_legacy: freeze с маркером (дефолт) vs схлопывание T3.6b.
4. Объём хвостовых волн Ф7/Ф8: **без них ось «дублирование» остаётся ~5.5/10** (шимы уйдут, но device-quad ×5 и 37 презентеров останутся); рекомендую минимум Ф7-пилот vfd+robot.
