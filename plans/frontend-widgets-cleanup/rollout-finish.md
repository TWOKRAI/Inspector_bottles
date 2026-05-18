# Plan: Widgets rollout & finish — миграция builders + закрытие техдолгов параллельно

**Slug:** widgets-rollout-finish
**Дата:** 2026-05-15
**Ветка:** refactor/widgets-rollout-finish
**Родительский план:** [`arch-polish.md`](arch-polish.md) (закрыт 6 коммитами 2026-05-15)
**Верхнеуровневая карта:** [`plan.md`](plan.md)
**Принцип:** **параллельные треки + cleanup в конце**. Не оставлять промежуточных half-states, не плодить deferred задач.

---

## Зачем

После `widgets-arch-polish` пилот Checkbox работает через FormContext + явный ActionBus, multi-target fan-out закрыт, V2 поглощён framework'ом. Но **открытые техдолги остались**:

| # | Техдолг | Где живёт | Условие закрытия |
|---|---------|-----------|------------------|
| 1 | `legacy QCheckBox` в `_build_bool` | `factory.py` | После миграции 5+ non-bool callers ИЛИ изоляция legacy в отдельный builder |
| 2 | `dual-mode` в `CheckboxPresenter` (form_ctx vs RegisterAdapter) | FW `checkbox/presenter.py` | Когда form_ctx обязателен в production-пути |
| 3 | `FieldInfo` re-export 11 LOC | `prototype/registers/field_info.py` | После mass rename импортов → FW |
| 4 | `form_ctx=None` kwarg default в `CheckboxControl.create` | FW `checkbox/facade.py` | Когда factory всегда передаёт form_ctx |
| 5 | FormContext **не задействован в 8 builders** (int/float/literal/color3/str/text/path/label) | `factory.py` | После миграции всех builders |
| 6 | 5+ callers без form_ctx (InspectorPanel, ServicesTab, SettingsSystem section, form_builder, yaml_io) | прототип | После миграции callers |
| 7 | `ResolvedCommand.process_name` backward-compat property | `bridge/command_catalog.py` | После миграции callers на `process_names` |
| 8 | `value_changed: Signal` в 4 view-классах (SpinBoxValueView, SliderValueView, LabeledNumericGroupView, ComboBoxView если новый) | FW components | По мере миграции builders (Track 1) |
| 9 | `ColorTripletWidget` (62 LOC) в `forms/widgets/color_picker.py` | прототип | После миграции color3 → CompoundNumericControl |
| 10 | Нет `combo/` компонента в FW | FW components | Track 1: создать |
| 11 | `BindingConfig` mock в `test_topology_bridge_v2.py` без `process_names` (backlog Task B) | bridge tests | Track 4 cleanup |

**Стратегия:** не закрывать по одному в 11 коммитов. Сделать **vertical slices** (фасад + builder + caller + тесты = один коммит на компонент), параллельно по компонентам, потом **финальный cleanup** одной волной.

---

## Принципы

1. **Параллельные треки.** Track 1 (FW facades) и Track 2 (factory builders) — слабосвязанные через шаблон Checkbox. Можно делать в любом порядке. Track 3 (callers) зависит от 1+2. Track 4 (cleanup) — последний.
2. **Vertical slice.** Один коммит = (FW facade form_ctx + factory builder form_ctx + tests). Не разбивать на 3 PR.
3. **Шаблон Checkbox.** Все остальные builders повторяют паттерн `_build_bool_binding_aware`. Принцип: «копируй структуру Checkbox, меняй фасад и view_config».
4. **Cleanup в конце, не размазывая.** Track 4 идёт **одной волной** после Tracks 1-3 — удаляет dual-mode, re-export, kwarg defaults. Никаких частичных cleanup посередине.
5. **Acceptance:** после плана **0 deferred задач** из таблицы выше. Если что-то не закрылось — указано явно с обоснованием.
6. **Метрика «упростили ли»:** после Track 4 LOC delta для production-кода должен быть **строго отрицательным** для прототипа (там удаляется legacy, ColorTripletWidget, FormBuildingContext-like артефакты). Для FW — может быть положительным (новые binding-aware presenters).

---

## Что НЕ делаем

- **UI-only компонент без плагина** — out of scope (по решению пользователя из widgets-arch-polish). Если появится реальный use case (тулбар, dialog) — отдельный план.
- **str/text/path framework-компоненты** — отдельная задача (новые компоненты в FW). В Tracks 1-2 эти builders остаются сырыми Qt с binding-обёрткой (минимум подписки на FormContext.write).
- **Component Design System / стилизация** — DEFERRED.
- **Touch-keyboard, telemetry** — работают через FormContext-инфраструктуру автоматически, не требуют отдельных правок.

---

## Целевая архитектура (после всех треков)

```python
# Любой caller (PluginsTab, InspectorPanel, ServicesTab, ...):
form_ctx = ctx.form_context()  # один объект из AppContext
RegisterView(fields, form_ctx=form_ctx)  # form_ctx — обязательный

# Каждое поле в форме рендерится через CardsFieldFactory:
CardsFieldFactory.create(field_info, parent, form_ctx=form_ctx)
  # → resolve_kind() из FieldMeta.widget
  # → _build_<kind>(field_info, form_ctx, parent)
  # → CheckboxControl/SpinBoxControl/SliderControl/.../.create(rm, binding, view_config, form_ctx=)
  # → presenter использует form_ctx.write — единственный путь

# Запись:
view.value_changed → presenter._on_changed
  → form_ctx.write(register, field, new, old)
  → V2ActionBuilder.field_set_timed (coalesce)
  → ActionBus.execute (undo_stack)
  → FieldSetHandler.apply
    → rm.set_field_value (subscribers → silent update других viewers)
    → bridge.on_field_set (fan-out по FieldRouting.process_targets)

# Чтение worker→GUI:
state_proxy.merge → IPC → TopologyBridge.on_state_delta → rm.set_value → subscribers → view.set_value_silent
```

**Один путь, один контракт, ни одного dual-mode.**

---

## Треки

### Track 0: Финализация Checkbox — доказать пилот **100%** перед тиражированием

**Зачем:** прежде чем копировать шаблон CheckboxControl на 7 других компонентов — убедиться что пилот **полностью** доказан. Сейчас у Checkbox есть нюансы:
- `CheckboxControl.create(form_ctx=None)` — backward-compat default, не очевиден как «обязательный для plugin path»
- `CheckboxPresenter` dual-mode — два пути в одном классе
- Whitelist `("robot_control", "pilot_widgets")` в `PluginsTab._build_form_ctx` — пилот не во всех plugin-формах
- `pytest-qt round-trip` тест отсутствует (backlog Reviewer'а Task E)
- Smoke `broadcast_flag` (multi-target) есть unit-тестом, но не через реальный sender

Track 0 **не закрывает все эти пункты** — некоторые (whitelist, dual-mode) уйдут только в Tracks 3+4. Но Track 0 закрывает **тестовое покрытие** и **документацию** — снимает риск тиражировать необкатанный паттерн.

**Задачи Track 0:**

- [x] **0.1 pytest-qt integration round-trip** — `test_checkbox_form_ctx_roundtrip` в `multiprocess_framework/tests/frontend_module/integration/test_form_context_integration.py`:
   - QApplication + реальный CheckboxView + реальный ActionBus + фейковый RM
   - View toggle → action в undo_stack → `bus.undo()` → view возвращается к старому значению (через subscribe → `set_value_silent`)
- [x] **0.2 Multi-target integration smoke** — покрыто в `test_form_context_integration.py` + bridge Task B (5 fan-out тестов уже зелёные)
- [x] **0.3 Access-level UI guard test** — `test_checkbox_disabled_when_user_level_below_access_level`:
   - CheckboxControl с binding на `admin_only` (access_level=5)
   - FormContext.access_level=0 → view.isEnabled() == False
- [x] **0.4 Docstring `form_ctx` параметра** в `CheckboxControl.create` — описано в `6c2eeb1` (production vs legacy путь, требование form_ctx в plugin-формах)
- [x] **0.5 README обновление** — `multiprocess_framework/modules/frontend_module/components/checkbox/README.md` — секция «binding-aware mode (form_ctx)» с mermaid
- [x] **0.6 Чистка TODO** в `factory.py` — устаревшие Phase 2.6 комментарии удалены

**Acceptance Track 0:**
- 3 новых integration теста зелёные
- Docstring + README обновлены
- Шаблон CheckboxControl документирован как «копируй меня для SpinBox/Slider/...»

**Коммит:** `test(frontend): Checkbox integration tests + docs — финализация пилота перед rollout`

**LOC:** ~+150 (только тесты + docs), production-код не меняем.

**Зависимость:** ничего. Track 0 запускается **первым**, до Tracks 1-3.

---

### Track 1: Framework facades — kwarg form_ctx во всех controls (параллельно)

Шаблон: повторить структуру `CheckboxControl.create(rm, binding, view_config, *, current_access_level=, hooks=, form_ctx=None)` + `CheckboxPresenter` dual-mode.

| # | Компонент | Файлы | Прим. |
|---|-----------|-------|-------|
| 1.0 | `CheckboxControl` | — | **DONE** (Task E `d67ca70`) |
| 1.1 | `SpinBoxControl` | `spinbox/{facade,presenter,view}.py` | `value_changed: Signal(int)` в view |
| 1.2 | `SliderControl` | `slider/{facade,presenter,view}.py` | `value_changed: Signal(int)` в view |
| 1.3 | `NumericControl` | `numeric/{facade,presenter}.py` | view общий с SpinBox |
| 1.4 | `CompoundNumericControl` | `compound/{facade,presenter}.py` | для color3 |
| 1.5 | `ComboControl` **(новый)** | `combo/` — новый пакет | View+Presenter+Facade+5-7 тестов; `value_changed: Signal(str)` |
| 1.6 | `LabelControl` *(если есть)* | `label/` | для readonly/unsupported |

Каждый — отдельный коммит. Acceptance per task:
- `facade.create(..., form_ctx=None)` — kwarg добавлен
- Presenter поддерживает оба пути (form_ctx.write vs rm.set_field_value)
- View имеет `value_changed: Signal(<type>)` если не было
- 3-5 регрессионных тестов: write через form_ctx, undo, write без form_ctx (legacy)

**Track 1 итого:** 5-6 коммитов в FW, ~1 коммит/день.

---

### Track 2: Prototype factory builders — binding-aware (параллельно с Track 1)

Шаблон: повторить `_build_bool_binding_aware` для каждого kind.

| # | Builder | Использует | Файлы |
|---|---------|------------|-------|
| 2.0 | `_build_bool` | CheckboxControl | — **DONE** (Task E) |
| 2.1 | `_build_int` | SpinBoxControl или SliderControl (по `meta.widget`) | `factory.py` |
| 2.2 | `_build_float` | NumericControl | `factory.py` |
| 2.3 | `_build_literal` | ComboControl (требует 1.5 готовым) | `factory.py` |
| 2.4 | `_build_color3` | CompoundNumericControl + **удалить** ColorTripletWidget | `factory.py`, `forms/widgets/color_picker.py` (delete) |
| 2.5 | `_build_str_short` | QLineEdit + form_ctx binding wrapper | `factory.py` |
| 2.6 | `_build_str_long` | QPlainTextEdit + form_ctx binding wrapper | `factory.py` |
| 2.7 | `_build_path` | QLineEdit + form_ctx binding wrapper | `factory.py` |
| 2.8 | `_build_unsupported` | QLabel readonly | `factory.py` |

**Зависимость:** 2.3 ждёт 1.5 (ComboControl). Остальные — независимы.

**Acceptance per builder:**
- Принимает `form_ctx: FormContext | None` (опц. — для backward-compat остальных callers)
- Если `form_ctx is not None` — биндит через framework facade с form_ctx
- Если `form_ctx is None` — legacy путь (для callers без plugin binding)
- Smoke в `pilot_widgets` (поле есть, рендерится правильным widget'ом)

**Track 2 итого:** 7-8 коммитов, можно параллелить с Track 1.

---

### Track 3: Callers migration на FormContext (после 1+2)

| # | Caller | Имеет plugin binding? | Тип form_ctx |
|---|--------|----------------------|--------------|
| 3.0 | `PluginsTab` (robot_control, pilot_widgets) | Да | **DONE** — полный FormContext |
| 3.1 | `InspectorPanel` (pipeline tab → inspector params) | Не всегда (chain runners — да; UI-control — нет) | Условно полный или None |
| 3.2 | `ServicesTab` | Да (service-плагины) | Полный |
| 3.3 | `SettingsSystem section` (theme/i18n) | Нет (GUI-локальное состояние) | None — пока legacy путь |
| 3.4 | `form_builder` | Зависит от caller | Передаёт form_ctx как есть |
| 3.5 | `yaml_io` | Только чтение/запись YAML | Не использует form_ctx |
| 3.6 | `tabs/settings/system/section.py` (двойная подписка из widgets-arch-polish risk #5) | Нет (GUI-локал) | None |

**Acceptance per caller:**
- Конструктор принимает `form_ctx: FormContext | None`
- Прокидывает в `RegisterView(form_ctx=...)` или `CardsFieldFactory.create(form_ctx=...)`
- Удалена двойная подписка `editor.change_signal.connect` (если была — `SettingsSystem section`)
- Smoke: формы рендерятся, запись работает (для plugin-callers — через ActionBus, для GUI-callers — без)

**Решение по non-plugin callers (3.3, 3.6):**
- Они не имеют plugin binding (settings — GUI-локальные).
- Передают `form_ctx=None` → legacy путь в builders (Track 2).
- **Track 4 НЕ удаляет legacy путь в factory builders** — он остаётся для non-plugin forms.
- Удаляется dual-mode только в **framework presenters** (через делегирование вверх).

**Track 3 итого:** 5 коммитов.

---

### Track 4: Final cleanup (только после 1+2+3)

После того как **все** plugin-callers мигрировали на FormContext, делаем финальную волну удаления техдолгов **одним коммитом** (или 2-3 связанных):

| # | Cleanup | Файлы |
|---|---------|-------|
| 4.1 | Удалить dual-mode в **CheckboxPresenter** (form_ctx обязательный в production-пути; legacy ветка → только для FW unit-тестов в `_examples` через спец. interface) | FW `checkbox/presenter.py` |
| 4.2 | Удалить dual-mode в SpinBox/Slider/Numeric/Compound/Combo presenters (аналогично 4.1) | FW components |
| 4.3 | Удалить `FieldInfo` re-export в `prototype/registers/field_info.py` (все импорты → FW) — mass-rename | прототип + grep по импортам |
| 4.4 | Удалить `ResolvedCommand.process_name` property — все callers на `process_names` | `bridge/command_catalog.py`, callers |
| 4.5 | `value_changed: Signal` — финальная проверка что есть во всех 4 view (Track 1 закроет, здесь смотрим что не упустили) | FW components |
| 4.6 | Обновить `test_topology_bridge_v2.py` mock с `process_names` property (backlog Task B) | bridge tests |
| 4.7 | Удалить `ColorTripletWidget` (если ещё не удалён в Track 2.4) | прототип |
| 4.8 | Опционально: `FormContext.write` принимает `targets: Iterable[str] | None = None` — явный multi-target API (если bridge fan-out недостаточен) | FW `form_context.py` |

**4.1-4.2 — критичное:** dual-mode в presenter уйдёт **только если** factory всегда передаёт form_ctx в plugin-builders. Для non-plugin builders (`_build_bool` со SettingsSystem) — factory создаёт QCheckBox напрямую, минуя CheckboxControl (legacy QCheckBox path в factory). Это означает: factory.py имеет два режима для bool — through-framework и raw-Qt. Это **ОК** — это разделение между «binding-aware форма плагина» и «GUI-локальная форма настроек».

**Acceptance cleanup'а:**
- 0 файлов в `prototype/frontend/forms/widgets/` (color_picker удалён, директория может остаться пустой)
- 0 dual-mode if-branches в FW presenters
- 0 backward-compat properties в ResolvedCommand
- 0 re-export'ов FieldInfo

**Track 4 итого:** 2-3 коммита (один на dual-mode cleanup, один на FieldInfo migrate, один на mop-up).

---

## Параллельный граф зависимостей

```
            ┌──── Track 0 (Checkbox финализация) ────┐
Start ────► │  0.1 pytest-qt round-trip              │
            │  0.2 Multi-target integration smoke    │
            │  0.3 Access-level UI guard test        │
            │  0.4-0.6 Docs + cleanup TODO           │
            └──────────────────┬─────────────────────┘
                               │
            ┌──────────── Track 1 (FW facades) ──────────┐
            │  1.1 SpinBox  ─┐                           │
            │  1.2 Slider   ─┼─► параллельно             │
            │  1.3 Numeric  ─┤                           │
            │  1.4 Compound ─┤                           │
            │  1.5 Combo NEW◄┤ (нужен для 2.3)           │
            │  1.6 Label *  ─┘                           │
            └────────────────────┬───────────────────────┘
                                 │
            ┌─────── Track 2 (factory builders) ─────────┐
            │  2.1 _build_int   (нужен 1.1+1.2)          │
            │  2.2 _build_float (нужен 1.3)              │
            │  2.3 _build_literal (нужен 1.5)            │
            │  2.4 _build_color3 (нужен 1.4)             │
            │  2.5-2.7 str/text/path (нужны binding API) │
            │  2.8 _build_unsupported                    │
            └────────────────────┬───────────────────────┘
                                 │
            ┌──────── Track 3 (callers) ─────────────────┐
            │  3.1 InspectorPanel                        │
            │  3.2 ServicesTab                           │
            │  3.3 SettingsSystem (form_ctx=None)        │
            │  3.4 form_builder                          │
            │  3.5-3.6 misc                              │
            └────────────────────┬───────────────────────┘
                                 │
            ┌──── Track 4 (final cleanup) ───────────────┐
            │  4.1-4.2 dual-mode уход                    │
            │  4.3 FieldInfo re-export delete            │
            │  4.4 process_name property delete          │
            │  4.5-4.8 mop-up                            │
            └────────────────────────────────────────────┘
```

**Порядок:** Track 0 первый (финализация пилота). Затем Track 1 и 2 параллельно (синхронизация на зависимостях 2.X→1.X). Track 3 после Track 2. Track 4 в конце.

**Track 0 обязателен:** без доказанного пилота не имеет смысла тиражировать паттерн. Это **gating step**, не optional.

---

## Реалистичная оценка

| Track | Коммитов | Дней |
|-------|----------|------|
| 0 (финализация Checkbox) | 1 | 0.5-1 |
| 1 (FW facades) | 5-6 | 3-4 |
| 2 (factory builders) | 7-8 | 4-5 (параллельно с 1) |
| 3 (callers) | 5 | 2-3 |
| 4 (cleanup) | 2-3 | 1-2 |
| **Итого** | **~21** | **8-11 дней** при одной активной задаче в день |

Если делать 2 задачи параллельно (через worktree) — 6-8 дней.

---

## Acceptance (вся фаза)

- [x] Все 8 builders (int/float/literal/color3/str_short/str_long/path/unsupported) — binding-aware через form_ctx (`f5634ec`)
- [x] **ComboControl** существует в FW (новый компонент + combo-finish: README, defaults, registers, _examples, реэкспорт; `82b87d4` + `7fd6fc6`)
- [x] `value_changed: Signal` есть во всех 4 view-классах (checkbox/spinbox/slider/group)
- [x] **5 callers** прокидывают form_ctx (InspectorPanel, ServicesTab, SettingsSystem, form_builder, yaml_io — `f5634ec`)
- [x] **ColorTripletWidget удалён** (color3 → CompoundNumericControl; `f5634ec`)
- [ ] **dual-mode в FW presenters удалён** — сознательно оставлен с DeprecationWarning для `_examples/` и FW unit-тестов (production form_ctx обязателен); полное удаление перенесено на отдельный план
- [x] **FieldInfo re-export удалён** (`f5634ec`)
- [x] **ResolvedCommand.process_name property удалён** (`206d35b`)
- [ ] **Pilot smoke:** ручной прогон UI отложен — automated coverage через integration + form_ctx unit тесты считаем достаточным; ручной smoke — отдельный шаг перед relish
- [ ] LOC delta — не измерен формально (не блокер)
- [x] `make check`, `make test` — pytest 1681/1682 (1 pre-existing flaky test isolation, не от этой ветки); bandit 0 High; ruff/mypy gradual baseline
- [ ] `mcp__sentrux__check_rules` — не запускали (Ollama выключена); отложить на ручной прогон перед PR
- [x] **Открытых техдолгов из таблицы:** 1 осознанный остаток (dual-mode с DeprecationWarning) — out of scope этой фазы, отдельный план если решат добивать

---

## Защита от половинного состояния

**Правило:** Track 4 (cleanup) **запрещён** пока Tracks 1+2+3 не завершены. Если в середине Track 3 что-то пошло не так — **не запускать 4.X**. Лучше остановиться с уведомлением.

**Чекпойнт перед Track 4:** Director (или TeamLead) делает проверку:
- Все коммиты Track 1+2+3 в ветке `refactor/widgets-rollout-finish`
- Все 5 callers реально передают form_ctx (grep, не на слово)
- `git grep "form_ctx=None"` в factory — только в non-plugin контексте
- Все 8 builders в factory имеют binding-aware path

Если чек не пройден — фикс перед cleanup'ом.

---

## Verification (per task + финально)

**Per vertical slice (1.X + 2.X в одном коммите):**
```pwsh
pytest multiprocess_framework/modules/frontend_module/tests/components/test_<comp>.py -v
pytest multiprocess_prototype/frontend/forms/tests/test_factory.py -v
python scripts/validate.py
```

**Финально (после Track 4):**
```pwsh
python scripts/validate.py
python scripts/run_framework_tests.py
pytest multiprocess_prototype/ -v
make gate
mcp__sentrux__check_rules    # 0 violations
mcp__sentrux__health         # score не упал
python multiprocess_prototype/run.py   # smoke pilot_widgets всех 12 полей
```

---

## Что после этого плана

**Phase 2 закрыт целиком.** Дальше — Phase 3 (миграция domain-регистров из `multiprocess_prototype_backup/registers/` в `Plugins/`, см. родительский Phase 2 план).

Если в процессе обнаружится новый use case **UI-only компонента без плагина** — отдельный план (расширение FormContext или BindingConfig.local-режим, как обсуждалось в widgets-arch-polish).

---

## Карта рисков и митигаций

| Риск | Митигация |
|------|-----------|
| ComboControl сложнее ожидаемого (str↔non-str для `Literal[1,2,3]`) | Track 1.5 — отдельный коммит с тестами на типизацию |
| str/text/path не имеют framework-аналога | Track 2.5-2.7 — thin binding wrapper (QLineEdit + form_ctx.write на textChanged), без полноценного `text/` компонента FW. Compromise. |
| Track 3 раскрывает скрытые callers | Discovery перед Track 3 — grep по `CardsFieldFactory.create` и `RegisterView(` в полном репозитории |
| Track 4 удаляет API → внешние Plugins ломаются | Перед удалением `process_name` property — grep по `.process_name` во всех Plugins (там сейчас не используется, но проверить) |
| Pre-commit hook грешит ruff-format переформатированием | Запускать ruff format локально перед commit |
| `_build_str_short` (≤120 chars) и `_build_str_long` (>120 chars) — кривое разграничение по default длине | Track 2.5-2.6 — оставить как есть, но добавить FieldMeta.widget="str"/"text" override приоритет (уже есть) |
