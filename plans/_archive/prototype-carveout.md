# План: carve-out универсальных частей прототипа → framework

> **Handoff-док.** Создан в конце сессии по итогам стратегического обсуждения.
> В новом чате: «продолжаем carve-out по плану» → начать с аудита (Этап 0).

## Контекст и решение

Владелец хочет навести порядок в `multiprocess_prototype/`, вынося универсальные части
во `multiprocess_framework/` как модули. Подход — **carve-out как forcing function**:
перенос модуля заставляет определить `interfaces.py`, расцепить связи, написать
контракт-тесты и нарезать код по границе → split + тесты + интерфейсы как побочный
продукт дисциплины (а не отдельные расплывчатые задачи). Прецедент в проекте есть:
Phase 4 (`sql_module`→Services), Phase 5 (Plugins, ADR-120).

## Baseline (sentrux, прототип, на момент решения)

| Метрика | Значение |
|---|---|
| Файлов / строк | 575 / ~98.6k |
| Quality signal | **7065** |
| Ацикличность | **10000 (0 циклов)** — слои текут вниз, НЕ запутано |
| Модулярность | **4377 — узкое место** (466/653 связей межмодульные) |
| Дублирование | 9177 (низкое) |
| Покрытие тестами | **~49%** (192 файла без тестов) |

Размеры подпакетов: frontend 341 файл (app-specific, в основном остаётся), domain 38ф/~8k,
adapters 28ф/~6.3k, backend 45ф/~5.8k, registers+recipes 16ф (app-specific).

## Честные рамки (обязательно учесть)

1. **Выносимая поверхность узкая.** Тяжёлое generic (process_module, router, plugins, sql)
   уже вынесено в прошлые фазы. frontend (341 файл) — GUI Inspector'а, остаётся.
   «Выделить универсальное» ≠ «вынести прототип целиком».
2. **Ловушка одного потребителя.** domain+adapters (~14k loc) обслуживает ОДНО приложение.
   Вынос ради переиспользования при 1 консьюмере = заморозить app-решения в фреймворке как
   неправильную абстракцию. Правило: выносить при ≥2 потребителях или app-agnostic контракте.
   **domain/adapters пока НЕ трогать.**
3. **Тесты-characterization — ДО переноса.** Carve-out даёт forward контракт-тесты НОВОГО
   модуля, но «не сломал ли приложение при выносе» ловится только тестами старого поведения,
   написанными заранее. При 49% покрытия это критично.
4. **God-файлы carve-out закрывает частично.** presenter.py (~1700 строк) — в основном
   app-specific; во фреймворк уедет ~20%, останется app-god-файл → его split нужен отдельно
   app-side. Главные god-файлы: `frontend/widgets/tabs/pipeline/presenter.py` (~1700),
   `.../inspector/inspector_panel.py` (~870), крупные `tab.py`.
5. **Это engine-программа на недели**, против приоритета «продукт > движок»
   ([[project_priority_product_over_engine]]). Решение принимать осознанно.

## Кандидаты на вынос (по убыванию очевидности)

| Кандидат | Где | Готовность шва |
|---|---|---|
| `SystemBuilder` (blueprint dict → SystemLauncher) | `backend/launch.py` | **чистый, уже помечен под вынос** — пилот |
| Generic graph-editor (GraphScene/NodeItem/EdgeItem/auto_layout) | `frontend/widgets/tabs/pipeline/graph/` | средне — расцепить от domain (NodeData/PluginCatalog) |
| Frontend-примитивы (DiffScrollTabLayout, forms-фабрика/CardsFieldFactory) | `frontend/widgets/primitives/`, `frontend/forms/` | средне |
| domain/adapters (editor-domain) | `domain/`, `adapters/` | **НЕ сейчас** (1 потребитель) |

## Этапы

### Этап 0 — Аудит-карта (read-only, первым)
investigator проходит по подпакетам прототипа, помечает каждый: **universal /
app-specific / coupled**, и находит **обратные импорты** (`multiprocess_prototype.*`,
domain-app), которые блокируют вынос. Результат — карта «что выносимо и какой ценой».
Без неё пилот выбирается наугад.

### Этап 1 — Пилот: вынести `SystemBuilder`
Полная дисциплина модуля фреймворка:
1. `sentrux session_start` (зафиксировать baseline).
2. Characterization-тесты текущего поведения SystemBuilder (ДО переноса).
3. Создать модуль фреймворка с `interfaces.py` + README.md + STATUS.md + контракт-тесты.
4. Перенести логику blueprint→launcher; прототип вызывает через контракт (composition root).
5. Срезать обратные импорты; `mcp__sentrux__check_rules` (boundaries).
6. `sentrux session_end` → дельта. Замерить: LOC перенесено, тестов добавлено, разрезан ли
   god-файл, время, дельта quality/модулярности.

### Этап 2 — Решение по остальному
По результатам пилота (реально ли получили split+тесты+интерфейс и какой ценой) —
решить, продолжать ли с graph-editor / примитивами. **domain/adapters отложены до 2-го
приложения.** Параллельный отдельный трек (не carve-out): split app-side god-файлов +
характеризационные тесты — то, что прямо облегчает работу агентам.

## Критерии успеха пилота
- `check_rules` зелёный (нет обратных импортов framework→prototype).
- Контракт-тесты модуля + characterization-тесты прошли; общий прогон зелёный.
- Quality не упал (в идеале модулярность подросла); дельта задокументирована.
- Прототип-сторона по SystemBuilder стала тоньше.

## Ссылки
- Конвенция модуля фреймворка: README/STATUS/`interfaces.py`/`tests/` (см. CLAUDE.md правила).
- Слои импортов и enforcement: `.sentrux/rules.toml`.
- Sentrux session-workflow: `/quality:sentrux-baseline` → `/quality:sentrux-diff`.
