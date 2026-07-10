# E4 — diff-отчёт 4 механизмов «схема→виджет» → GATE G2

**Задача:** Ф5.6 (a). Артефакт для решения владельца на **GATE G2**: какой из 4
механизмов «схема→виджет» — целевой, что убить. Часть (b) — унификация до одного
и gate «биндинг-стеков ≤2→1» — исполняется ПОСЛЕ выбора владельца.

**Дата:** 2026-07-10. Верификация — grep по `multiprocess_prototype` +
`multiprocess_framework` + `Services` + `Plugins`, исключая `__pycache__`.
Ссылки-первоисточники: `analysis.md` §7/§128/§131, `plan.md` §86.

---

## 1. Четыре механизма — сводка (верифицировано)

| # | Механизм | Где | LOC | Статус в проде | Кто инстанцирует |
|---|----------|-----|-----|----------------|------------------|
| **7a** | **legacy factory** (`builders_legacy` в `CardsFieldFactory`) | `frontend/forms/factory/` | 363 (legacy-builders) | **ЖИВОЙ** | `form_builder.py`, `register_view.py`, `model_picker.py` — весь прод-путь форм |
| **7b** | **binding-aware** (`builders_binding` + `FormContext`) | `frontend/forms/factory/builders_binding.py` + `frontend_module/forms/form_context.py` | 486 + 100 | **дремлет** (dead-in-prod) | `FormContext(...)` — **только в 11 тест-файлах**, ни одного прод-сайта с `form_ctx≠None` |
| **7c** | **ParamsForm / entity_editor** (`ParamsForm`, `SchemaInspectorPanel`, `EntityTreeWidget`, `BaseEditorModel`) | `frontend_module/widgets/entity_editor/` | ~1778 (пакет) | **МЁРТВ** | 0 живых потребителей вне модуля; прототип `entity_editor` не импортирует |
| **7d** | **WidgetRegistry / LayoutComposer** (`WidgetRegistry`, `LayoutComposer`, `WidgetDescriptor`, `default_factories`) | `frontend_module/core/` + `schemas/` | ~363 | **МЁРТВ** | `create_default_registry()` / `WidgetRegistry()` не зовётся **нигде** (даже в тестах); `LayoutComposer` — «будущий» |

> **7a и 7b — не два разных фабрики, а две ветки ОДНОГО `CardsFieldFactory`:**
> `create(fi, parent, form_ctx=None)` → `form_ctx is None` → legacy-builders (7a),
> иначе → binding-builders (7b). Именно это «биндинг-стеков 2», которые gate G2
> схлопывает до 1. 7c и 7d — независимые мёртвые механизмы флагмана
> (`frontend_module` «флагман», `plan.md` §86: FREEZE/KILL).

---

## 2. Чем 7a отличается от 7b (суть развилки)

| Ось | 7a legacy (ЖИВОЙ) | 7b binding-aware (дремлет) |
|-----|-------------------|----------------------------|
| **Кто пишет значение** | `change_signal` виджета → `RegisterView` пишет в `RegistersManager` | editor пишет сам через `FormContext.write` → **ActionBus** (coalescing, undo/redo, IPC-bridge); `change_signal=None` (RegisterView не дублирует) |
| **Зависимости** | RM + Qt | RM + Qt + **ActionBus** + `FormContext` (access_level, on_write_rejected/on_access_denied хуки) |
| **Активация в проде** | всегда (`form_ctx=None` во всех сайтах) | никогда (`FormContext` не создаётся в проде) |
| **Тестовое покрытие** | характеризационные тесты фабрики | 11 тест-файлов на binding-write |

**Критично:** 7b пишет через **ActionBus**, а ActionBus — НЕ прод-путь undo
(ADR-COMM-002 не исполняется, владелец 2026-07-08 решил `actions_module` сохранить,
но не как прод-undo — см. память `project_actions_module_keep`). Т.е. 7b — это
«правильный» реактивный дизайн (undoable/coalesced write), завязанный на механизм,
который сам сейчас не на прод-пути.

---

## 3. Варианты для G2 (решение владельца)

### Вариант A (рекомендуется) — целевой = 7a legacy, убить 7b + 7c + 7d
- Оставить `CardsFieldFactory` на legacy-builders (единственный живой стек).
- **Удалить:** `builders_binding.py` (486) + `FormContext` (100) + 11 binding-тестов; `entity_editor` (7c, ~1778); `WidgetRegistry`/`LayoutComposer`/`WidgetDescriptor`/`default_factories` (7d, ~363).
- **Итог:** 4→1 механизм, биндинг-стеков 2→1, минус ~2800 LOC dead/dormant.
- **Плюс:** максимальное упрощение, убирает параллельный стек и мёртвый флагман; двигает equality/redundancy.
- **Минус:** теряется реализованный (и протестированный) binding-write. Если реактивный undoable-write понадобится позже — восстанавливать из git или переписывать.

### Вариант B — целевой = 7b binding-aware, мигрировать на него, убить 7a + 7c + 7d
- Развести `form_ctx≠None` во все прод-сайты (`FormBuilder`/`RegisterView`), удалить legacy-стек.
- **Плюс:** «правильный» реактивный/undoable write как единственный путь.
- **Минус:** крупнее и риск на живом пути форм; **связано с оживлением ActionBus** (ADR-COMM-002), который сейчас НЕ на прод-пути → оправдано только если reactive-undo — близкая продуктовая цель.

### Вариант C — статус-кво (2 стека) — отвергнут
Это и есть долг, который закрывает E4.

---

## 4. Рекомендация

**Вариант A.** Обоснование: 7b/7c/7d — все dead-in-prod (верифицировано); 7b вдобавок
завязан на не-прод ActionBus. Reactive-undo write (единственное, что 7b даёт сверх 7a)
сейчас не на дорожной карте (ADR-COMM-002 заморожен). Держать 486+100 LOC параллельного
стека + 1778 мёртвого флагмана ради возможной будущей фичи — цена выше ценности; при
необходимости binding-write восстановим из истории git.

**Открытый вопрос владельцу (G2):** нужен ли реактивный/undoable form-write (7b) в
ближайшей перспективе?
- **Нет** → Вариант A (kill 7b/7c/7d, целевой legacy).
- **Да, скоро** → Вариант B (миграция на binding-aware + оживление ActionBus, ADR-COMM-002).

## 5. Область KILL (при Варианте A; исполнение — часть b / отдельный per-item коммит)

| Убрать | Файлы | LOC |
|--------|-------|-----|
| 7b binding-aware | `forms/factory/builders_binding.py`, `frontend_module/forms/form_context.py`, 11 `*_form_ctx*`/`test_form_context*` тестов | ~586 + тесты |
| 7c entity_editor | `frontend_module/widgets/entity_editor/` (ParamsForm, SchemaInspectorPanel, EntityTreeWidget, BaseEditorModel) | ~1778 |
| 7d widget-registry | `frontend_module/core/{widget_registry,layout_composer,default_factories}.py`, `schemas/widget_descriptor.py`, `interfaces.IWidgetRegistry` | ~363 |

**Перед KILL 7c/7d:** прогнать `sentrux check_rules` + полный прогон (характеризационные
тесты форм зелёные без правок — acceptance Ф5.6); снять ре-экспорты из
`frontend_module/__init__.py` и `core/__init__.py`. `CardsFieldFactory.create` — убрать
параметр `form_ctx` (упростить сигнатуру) после удаления 7b.
