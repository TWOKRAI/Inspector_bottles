# Plan: Наведение порядка в frontend — компоненты и виджеты

- **Slug:** frontend-widgets-cleanup
- **Дата:** 2026-05-14
- **Статус:** IN_PROGRESS (Phase 0+1 done, Phase 2.0+2.0.5 done, Phase 2.1+ → rollout-finish.md)
- **Ветка:** refactor/frontend-widgets-cleanup (Phase 0-2.0.5), `refactor/widgets-rollout-finish` (Phase 2.1+)
- **Автор:** Director + User

## Context

В `multiprocess_prototype/frontend/widgets/` — 7 мёртвых папок (пустые, 0 LOC), создающих путаницу с рабочими (`widgets/pipeline/` vs `widgets/tabs/pipeline/`). Framework components (`checkbox/`, `slider/`, `spinbox/` и т.д.) — зрелые, с кастомной клавиатурой и фичами, но прототип их не использует — вместо этого создаёт сырые Qt-виджеты. Нужно навести порядок снизу вверх.

## Подпланы (дочерние)

| План | Статус | Что закрывает |
|------|--------|---------------|
| [`phase2-pilot.md`](phase2-pilot.md) | Phase 2.0 done, **2.1-2.7 superseded** | Pilot Checkbox на pilot_widgets через FormBuildingContext + ActionBusRegistersManager. Phase 2.1-2.7 переоформлены через rollout-finish |
| [`arch-polish.md`](arch-polish.md) | **DONE** 2026-05-15 (5 коммитов, H deferred) | Полировка архитектуры на пилоте: FieldMeta.widget единый, FormContext в FW, явный ActionBus (прокси удалён), multi-target fan-out, V2 поглощён framework'ом |
| [`rollout-finish.md`](rollout-finish.md) | **IN_PROGRESS** | Параллельный rollout на все builders + закрытие всех техдолгов одной волной (заменяет Phase 2.1-2.7) |

## Стратегия: 4 этапа

```
Phase 0: Очистка прототипа (мёртвые папки, кэш)
    ↓
Phase 1: Ревью framework components (по одному) — убедиться что лучше
    ↓
Phase 2: Заменить в прототипе сырые Qt → framework components
    ↓
Phase 3: Сравнить widgets прототипа с widgets фреймворка → перенести лучшие
```

Каждая фаза — отдельная ветка, ревьюим вместе по одному элементу.

---

## Phase 0: Очистка прототипа

- [x] 0.1 Очистить кэш
- [x] 0.2 Удалить 7 мёртвых папок: `base/`, `pipeline/`, `processing/`, `recipes/`, `settings/`, `sources/`, `tabs_setting/`
- [x] 0.3 Проверка: `git status` чистый, tracked файлы не затронуты

---

## Phase 1: Ревью framework components (по одному)

**Цель:** пройтись по каждому framework component, убедиться что он лучше прототипных аналогов.

**Артефакт:** [`docs/refactors/widgets-component-review.md`](../../docs/refactors/widgets-component-review.md) — 8 секций, решения по каждому компоненту.

| # | Компонент | LOC | Прототипный аналог | Решение для Phase 2 | Статус |
|---|---|---|---|---|---|
| 1.1 | `checkbox/` | 389 | `QCheckBox` + `QLabel` (`_build_bool`) | `CheckboxControl.create` (+`value_changed` Signal) | [x] |
| 1.2 | `numeric/` | 395 | `QDoubleSpinBox` (`_build_float`) | `NumericControl.create(view_type="spinbox")` | [x] |
| 1.3 | `slider/` | 349 | не используется | `SliderControl.create` (`int` ≤1000 range) | [x] |
| 1.4 | `spinbox/` | 272 | `QSpinBox` (`_build_int`) | `SpinBoxControl.create` (`int` большой range) | [x] |
| 1.5 | `compound/` | 313 | `ColorTripletWidget` (62 LOC) | `CompoundNumericControl.create`, удалить ColorTripletWidget | [x] |
| 1.6 | `label/` | 56 | `QLabel` напрямую | оставить сырой `QLabel` для unsupported (без выгоды) | [x] |
| 1.7 | `group/` | 285 | нет аналога | используется внутри numeric/spinbox/slider (+`value_changed` proxy) | [x] |
| **1.8** | **`combo/` (новый)** | — | `QComboBox` (`_build_literal`) | **создать в Phase 2** (8-й компонент) | [x] |

---

## Phase 2: Замена в прототипе (после Phase 1)

### Phase 2.0 — Pilot (DONE)
Checkbox для `robot_control.enabled` через FormBuildingContext + ActionBusRegistersManager. Закрыт `bcdb061` + 5 предшествующих коммитов. См. [`phase2-pilot.md`](phase2-pilot.md).

### Phase 2.0.5 — Архитектурная полировка на пилоте (DONE 2026-05-15)
FieldMeta.widget единый источник, FormContext в FW, явный ActionBus (прокси удалён, -94 LOC production), multi-target fan-out в TopologyBridge, V2 поглощён framework'ом. **5 коммитов:** `09191e3`, `fe25d12`, `d67ca70`, `0550f04`, `53a14cf`. См. [`arch-polish.md`](arch-polish.md).

### Phase 2.1+ — Rollout на остальные builders (IN_PROGRESS → rollout-finish.md)
Sequential Phase 2.1-2.7 из родительского phase2-плана **переоформлены через параллельные треки** в [`rollout-finish.md`](rollout-finish.md):
- Track 1: Framework facades (SpinBox/Slider/Numeric/Compound/Combo NEW + value_changed Signal)
- Track 2: Factory builders (`_build_int/float/literal/color3/str/path` — binding-aware)
- Track 3: Callers migration (InspectorPanel, ServicesTab, SettingsSystem, form_builder)
- Track 4: Final cleanup — dual-mode уход, FieldInfo re-export delete, process_name property delete, ColorTripletWidget delete

**Целевая таблица замен:**

| Тип поля | Сейчас | После Phase 2.1+ |
|---|---|---|
| `bool` | `CheckboxControl.create` (DONE) | то же + form_ctx обязателен в plugin path |
| `int` | `QSpinBox()` | `SpinBoxControl.create` или `SliderControl.create` (по meta.widget) |
| `float` | `QDoubleSpinBox()` | `NumericControl.create` |
| `literal` | `QComboBox()` | `ComboControl.create` (новый компонент FW) |
| `color3` | `ColorTripletWidget()` | `CompoundNumericControl.create` (ColorTripletWidget удалён) |
| `str/text/path` | `QLineEdit/QPlainTextEdit` | то же + form_ctx binding wrapper (без нового FW-компонента) |
| `label` | disabled QLabel | то же |

---

## Phase 3: Виджеты прототипа → фреймворк (после Phase 2)

Кандидаты (11 примитивов, 2974 LOC):
`ActionToolbar`, `CrudTable`, `DiffScrollTabLayout`, `EntityCard`, `MasterDetailLayout`, `SectionedForm`, `SideNavLayout`, `SlotSelector`, `StandardTabLayout`, `StatusIndicator`, `TreeNavWidget`
