# Plan: Наведение порядка в frontend — компоненты и виджеты

- **Slug:** frontend-widgets-cleanup
- **Дата:** 2026-05-14
- **Статус:** IN_PROGRESS
- **Ветка:** refactor/frontend-widgets-cleanup (создать при первом коммите)
- **Автор:** Director + User

## Context

В `multiprocess_prototype/frontend/widgets/` — 7 мёртвых папок (пустые, 0 LOC), создающих путаницу с рабочими (`widgets/pipeline/` vs `widgets/tabs/pipeline/`). Framework components (`checkbox/`, `slider/`, `spinbox/` и т.д.) — зрелые, с кастомной клавиатурой и фичами, но прототип их не использует — вместо этого создаёт сырые Qt-виджеты. Нужно навести порядок снизу вверх.

> **Детальный план Phase 1 + Phase 2:** [`plans/frontend-widgets-cleanup-phase2.md`](frontend-widgets-cleanup-phase2.md)
> Включает целевую архитектуру (мост `ActionBusRegistersManager`, FormBuildingContext, dual-flow GUI↔worker через FieldMeta.routing + TopologyBridge + state_store), пилотную стратегию (Phase 2.0 — Checkbox/robot_control), карту интеграций, ревью-замечания.

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

**Артефакт:** [`docs/refactors/widgets-component-review.md`](../docs/refactors/widgets-component-review.md) — 8 секций, решения по каждому компоненту.

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

| Тип поля | Сейчас | После |
|---|---|---|
| `bool` | `QCheckBox()` | `CheckboxControl.create(...)` |
| `int` | `QSpinBox()` | `SpinBoxControl.create(...)` |
| `float` | `QDoubleSpinBox()` | `NumericControl.create(...)` |
| `color3` | `ColorTripletWidget()` | `CompoundNumericControl.create(...)` |
| `str` | `QLineEdit()` | остаётся (нет framework аналога) |

---

## Phase 3: Виджеты прототипа → фреймворк (после Phase 2)

Кандидаты (11 примитивов, 2974 LOC):
`ActionToolbar`, `CrudTable`, `DiffScrollTabLayout`, `EntityCard`, `MasterDetailLayout`, `SectionedForm`, `SideNavLayout`, `SlotSelector`, `StandardTabLayout`, `StatusIndicator`, `TreeNavWidget`
